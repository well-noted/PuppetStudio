#!/usr/bin/env python3
"""Line-art registration, matte proposals, and RGB compositing. See README.md."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from fractions import Fraction

import cv2
import numpy as np
from PIL import Image, ImageOps
import masking

cv2.setRNGSeed(19)


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def rgb(path):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert('RGBA')
        white = Image.new('RGBA', im.size, (255, 255, 255, 255))
        return np.asarray(Image.alpha_composite(white, im).convert('RGB')).copy()


def write_image(path, arr):
    Image.fromarray(arr).save(path)


def box_checked(box, w, h):
    x, y, bw, bh = map(int, box)
    if min(x, y) < 0 or min(bw, bh) <= 0 or x + bw > w or y + bh > h:
        raise ValueError(f'Box {box} is outside {w}x{h}; boxes use x,y,width,height.')
    return x, y, bw, bh


def poly_mask(shape, polygons):
    h, w = shape[:2]
    m = np.zeros((h, w), np.uint8)
    for polygon in polygons:
        p = np.asarray(polygon, dtype=float)
        if p.ndim != 2 or p.shape[0] < 3 or p.shape[1] != 2 or not np.isfinite(p).all():
            raise ValueError('Each polygon needs at least three finite [x,y] points.')
        if (p < 0).any() or (p > 1).any():
            raise ValueError('Polygon coordinates must be normalized to [0,1].')
        p = np.rint(p * [w - 1, h - 1]).astype(np.int32)
        cv2.fillPoly(m, [p], 255)
    return m


def stable_mask(shape, cfg):
    # Upper half is a geometric starting point, not a semantic glasses detector.
    polygons = cfg.get('stable_polygons', [[[0.05, 0.05], [0.95, 0.05],
                                            [0.95, 0.55], [0.05, 0.55]]])
    m = poly_mask(shape, polygons)
    if np.count_nonzero(m) < 100:
        raise ValueError('Stable registration region is too small.')
    if "_content_box" in cfg:
        m = cv2.bitwise_and(m, rect_mask(shape, cfg["_content_box"]))
    return m


def edges(im):
    g = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY)
    return cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0.6), 40, 120)


def edge_soft(im):
    return cv2.GaussianBlur(edges(im).astype(np.float32) / 255, (5, 5), 0.8)


def homogeneous(m):
    return np.vstack([m, [0, 0, 1]])


def warp(im, m, shape, border=255):
    h, w = shape[:2]
    value = (border,) * im.shape[2] if im.ndim == 3 else border
    return cv2.warpAffine(im, m.astype(np.float32), (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=value)


def similarity_info(m):
    return {'scale': float(np.hypot(m[0, 0], m[1, 0])),
            'rotation_degrees': float(np.degrees(np.arctan2(m[1, 0], m[0, 0]))),
            'origin_x': float(m[0, 2]), 'origin_y': float(m[1, 2])}


def validate_similarity(m):
    m = np.asarray(m, dtype=float)
    if m.shape != (2, 3) or not np.isfinite(m).all():
        raise ValueError('Expected finite 2x3 forward affine matrix.')
    if np.linalg.det(m[:, :2]) <= 0 or not np.allclose(
            m[:, :2].T @ m[:, :2], np.eye(2) * np.sum(m[:, 0] ** 2), atol=1e-5):
        raise ValueError('Transform must be an orientation-preserving similarity.')
    return m


def quality(target, moving, m, stable):
    h, w = target.shape[:2]
    valid = warp(np.full(moving.shape[:2], 255, np.uint8), m, target.shape, 0) > 254
    valid &= stable > 0
    a = edges(target)
    # Warp the edge map, avoiding false edges at the white canvas boundary.
    b = warp(edges(moving), m, target.shape, 0) > 40
    aa, bb = (a > 0) & valid, b & valid
    na, nb = int(aa.sum()), int(bb.sum())
    if min(na, nb) < 30:
        return {'chamfer_px': 999.0, 'edge_coverage': 0.0, 'valid_fraction': 0.0}
    da = cv2.distanceTransform((~aa).astype(np.uint8), cv2.DIST_L2, 3)
    db = cv2.distanceTransform((~bb).astype(np.uint8), cv2.DIST_L2, 3)
    # Symmetric truncated Chamfer distance, in ORIGINAL bust pixels.
    d = float((np.minimum(da[bb], 10).mean() + np.minimum(db[aa], 10).mean()) / 2)
    coverage = float(((da[bb] <= 1.5).mean() + (db[aa] <= 1.5).mean()) / 2)
    return {'chamfer_px': d, 'edge_coverage': coverage,
            'valid_fraction': float(valid.sum() / max(1, (stable > 0).sum()))}


def feature_candidate(target, moving, stable):
    detector = cv2.ORB_create(nfeatures=4000, edgeThreshold=10, fastThreshold=8)
    kt, dt = detector.detectAndCompute(cv2.cvtColor(target, cv2.COLOR_RGB2GRAY), stable)
    km, dm = detector.detectAndCompute(cv2.cvtColor(moving, cv2.COLOR_RGB2GRAY), None)
    if dt is None or dm is None or len(dt) < 6 or len(dm) < 6:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(dm, dt, k=2)
    reverse = {x.queryIdx: x.trainIdx for x in matcher.match(dt, dm)}
    good = [x for p in pairs if len(p) == 2 for x, y in [p]
            if x.distance < 0.75 * y.distance and reverse.get(x.trainIdx) == x.queryIdx]
    if len(good) < 6:
        return None
    src = np.float32([km[x.queryIdx].pt for x in good])
    dst = np.float32([kt[x.trainIdx].pt for x in good])
    m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                           ransacReprojThreshold=2, maxIters=3000)
    if m is None:
        return None
    good_dst = dst[inliers.ravel() > 0]
    n = len(good_dst)
    if n < 6 or n / len(good) < 0.4 or np.ptp(good_dst[:, 0]) < target.shape[1] * 0.15:
        return None
    return m, {'method': 'ORB-RANSAC', 'inliers': n, 'matches': len(good)}


def template_candidates(target, moving, cfg):
    """Bounded multiscale search; masked NCC on blurred ink edges."""
    th, tw = target.shape[:2]
    mh, mw = moving.shape[:2]
    target_edges = edge_soft(target)
    widths = np.linspace(*cfg.get('search_width_px', [0.35 * tw, tw]),
                         int(cfg.get('scale_steps', 40)))
    angles = cfg.get('search_angles_degrees', [-4, 0, 4])
    candidates = []
    for width in widths:
        s = width / mw
        rw, rh = max(2, round(mw * s)), max(2, round(mh * s))
        if rw > tw or rh > th or min(rw, rh) < 12:
            continue
        resized = cv2.resize(moving, (rw, rh), interpolation=cv2.INTER_AREA)
        e = edge_soft(resized)
        # Mask is in VIDEO coordinates; adjust if the output is a tight face crop.
        sm = poly_mask(resized.shape, cfg.get('video_stable_polygons',
                      [[[0.04, 0.04], [0.96, 0.04], [0.96, 0.56], [0.04, 0.56]]]))
        if np.count_nonzero(e[sm > 0]) < 30:
            continue
        for angle in angles:
            r = cv2.getRotationMatrix2D(((rw - 1) / 2, (rh - 1) / 2), angle, 1)
            te = warp(e, r, e.shape, 0)
            tm = warp(sm, r, sm.shape, 0)
            scores = cv2.matchTemplate(target_edges, te, cv2.TM_CCORR_NORMED, mask=tm)
            scores[~np.isfinite(scores)] = -1
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            # Resize uses pixel centers: x_small = s*x_large + (s-1)/2.
            # Enforce isotropic scaling; integer resize differences are subpixel.
            exact = np.array([[s, 0, (s - 1) / 2], [0, s, (s - 1) / 2], [0, 0, 1]])
            m = homogeneous(r) @ exact
            m[:2, 2] += [x, y]
            candidates.append((m[:2], {'method': 'edge-template', 'ncc': float(score)}))
    return sorted(candidates, key=lambda x: x[1]['ncc'], reverse=True)[:5]


def refine(target, moving, m, stable):
    aligned = warp(moving, m, target.shape)
    validity = warp(np.full(moving.shape[:2], 255, np.uint8), m, target.shape, 0)
    mask = cv2.bitwise_and(stable, (validity > 254).astype(np.uint8) * 255)
    w = np.eye(2, 3, dtype=np.float32)
    try:
        cc, w = cv2.findTransformECC(edge_soft(target), edge_soft(aligned), w,
                                     cv2.MOTION_EUCLIDEAN,
                                     (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 80, 1e-5),
                                     mask, 5)
        # ECC maps template -> input; our saved matrix maps input -> template.
        refined = (np.linalg.inv(homogeneous(w)) @ homogeneous(m))[:2]
        displacement = np.linalg.norm(refined[:, 2] - m[:, 2])
        if displacement <= 5 and abs(similarity_info(w)['rotation_degrees']) <= 3:
            if quality(target, moving, refined, stable)['chamfer_px'] < quality(
                    target, moving, m, stable)['chamfer_px']:
                return refined, float(cc)
    except cv2.error:
        pass
    return m, None


def solve(target, moving, cfg, anchors=None):
    stable = stable_mask(target.shape, cfg)
    if anchors is not None:
        src = np.asarray(anchors['video_points'], np.float32)
        dst = np.asarray(anchors['bust_points'], np.float32)
        if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2 or len(src) < 3:
            raise ValueError('Need >=3 paired video_points/bust_points from SAME frame.')
        if not np.isfinite(src).all() or not np.isfinite(dst).all():
            raise ValueError('Anchor points must be finite.')
        m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                               ransacReprojThreshold=2)
        if m is None or int(inliers.sum()) < 3:
            raise ValueError('Anchor fit failed.')
        candidates = [(m, {'method': 'paired-anchors', 'inliers': int(inliers.sum())})]
    else:
        candidates = template_candidates(target, moving, cfg)
        feat = feature_candidate(target, moving, stable)
        if feat is not None:
            candidates.append(feat)
    if not candidates:
        raise ValueError('No registration candidates. Use paired anchors or broaden search.')
    results = []
    for m, detail in candidates:
        m, cc = refine(target, moving, m, stable)
        q = quality(target, moving, m, stable)
        results.append((m, {**detail, **q, 'ecc': cc}))
    results.sort(key=lambda x: x[1]['chamfer_px'])
    m, detail = results[0]
    info = similarity_info(m)
    passed = (detail['chamfer_px'] <= cfg.get('max_chamfer_px', 2.0)
              and detail['edge_coverage'] >= cfg.get('min_edge_coverage', 0.55)
              and detail['valid_fraction'] >= cfg.get('min_valid_fraction', 0.55)
              and abs(info['rotation_degrees']) <= cfg.get('max_rotation_degrees', 8))
    return validate_similarity(m), {**detail, **info, 'quality_passed': bool(passed)}


def probe(path):
    if not shutil.which('ffprobe'):
        raise RuntimeError('Install FFmpeg and put ffmpeg/ffprobe on PATH.')
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                               '-show_format', '-of', 'json', str(path)], text=True))


def video_info(path):
    p = probe(path)
    s = next(s for s in p['streams'] if s['codec_type'] == 'video')
    try:
        rate = Fraction(s.get('avg_frame_rate', '0/1'))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid video frame rate.') from exc
    if rate <= 0:
        raise ValueError('Invalid video frame rate.')
    if s.get('r_frame_rate') and Fraction(s['r_frame_rate']) != rate:
        raise ValueError('Variable/ambiguous frame rate. Normalize to CFR first (see README).')
    # Inspect presentation timestamps; average frame rate alone cannot establish CFR.
    ts = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
        '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(path)], text=True))
    times = [float(f['best_effort_timestamp_time']) for f in ts.get('frames', [])
             if 'best_effort_timestamp_time' in f]
    if len(times) > 1:
        step = float(1 / rate)
        if np.max(np.abs(np.diff(times) - step)) > max(0.0001, step * 0.02):
            raise ValueError('Nonuniform presentation timestamps; normalize to CFR first.')
    rotation = s.get('tags', {}).get('rotate', '0')
    side_rotation = [d.get('rotation', 0) for d in s.get('side_data_list', [])]
    if float(rotation) != 0 or any(float(r) != 0 for r in side_rotation):
        raise ValueError('Rotation metadata present; bake orientation into a CFR video first.')
    return p, s, rate


def sample_video(path, count=9):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f'Cannot decode {path}')
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if n <= 0:
        cap.release()
        raise ValueError('Frame count unavailable; transcode to CFR first.')
    indices = np.unique(np.linspace(0, n - 1, min(n, count)).astype(int))
    out = []
    try:
        for i in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, bgr = cap.read()
            if not ok:
                raise ValueError(f'Cannot decode frame {i}')
            out.append((int(i), cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    finally:
        cap.release()
    return out


def rect_mask(shape, box):
    h,w = shape[:2]
    x,y,bw,bh = box_checked(box,w,h)
    m = np.zeros((h,w),np.uint8)
    m[y:y+bh,x:x+bw] = 255
    return m


def asset_layout(metadata, shape):
    """Legacy assets are unpadded. v2 separates the body crop from the bust canvas."""
    bx,by,cw,ch = metadata['bust_box_body']
    content = metadata.get('bust_content_box', [0,0,cw,ch])
    px,py,pw,ph = box_checked(content,shape[1],shape[0])
    if (pw,ph) != (cw,ch):
        raise ValueError('Content dimensions differ from raw body crop.')
    matrix = np.array([[1.,0.,bx-px],[0.,1.,by-py]])
    if 'bust_to_body' in metadata and not np.allclose(matrix,metadata['bust_to_body']):
        raise ValueError('Inconsistent padding/body transform metadata.')
    return matrix, [px,py,pw,ph]


def cmd_extract(args):
    sheet = rgb(args.sheet)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bh,bw = sheet.shape[:2]
    body_box = box_checked(args.body,bw,bh)
    x,y,w,h = body_box
    body = sheet[y:y+h,x:x+w].copy()
    bx,by,cw,ch = box_checked(args.bust,w,h)
    crop = body[by:by+ch,bx:bx+cw].copy()
    pl=pt=pr=pb=0
    if args.square_pad:
        size=max(cw,ch)
        pl,pt=(size-cw)//2,(size-ch)//2
        pr,pb=size-cw-pl,size-ch-pt
        canvas=np.empty((size,size,3),np.uint8)
        canvas[:]=args.pad_color
        canvas[pt:pt+ch,pl:pl+cw]=crop
    else:
        canvas=crop
    write_image(out/'body.png',body)
    write_image(out/'bust.png',canvas)
    save_json(out/'assets.json',{'version':2,'sheet':str(Path(args.sheet).resolve()),
        'sheet_sha256':digest(args.sheet),'body_box_sheet':body_box,
        'bust_box_body':[bx,by,cw,ch],'bust_size':[canvas.shape[1],canvas.shape[0]],
        'bust_content_box':[pl,pt,cw,ch],'padding_ltrb':[pl,pt,pr,pb],
        'padding_offset_xy':[float(pl),float(pt)],
        'ideal_center_padding_xy':[(max(cw,ch)-cw)/2 if args.square_pad else 0.,
                                   (max(cw,ch)-ch)/2 if args.square_pad else 0.],
        'bust_to_body':[[1.,0.,float(bx-pl)],[0.,1.,float(by-pt)]],
        'pad_color':args.pad_color,'body':'body.png','bust':'bust.png'})
    print(f'Assets saved to {out}; bust {canvas.shape[1]}x{canvas.shape[0]}, padding {pl,pt,pr,pb}')


def cmd_components(args):
    im = rgb(args.sheet)
    # Geometric candidates only: detached props/white gaps defeat semantic grouping.
    gray = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY)
    ink = (gray < args.threshold).astype(np.uint8) * 255
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.join, args.join)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink)
    boxes = []
    preview = im.copy()
    for i in range(1, n):
        x, y, w, h, area = map(int, stats[i])
        if area < args.min_area:
            continue
        boxes.append({'id': len(boxes), 'box_xywh': [x, y, w, h], 'ink_area': area})
        cv2.rectangle(preview, (x, y), (x+w-1, y+h-1), (255, 0, 0), 2)
        cv2.putText(preview, str(len(boxes)-1), (x, max(15, y)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 0, 0), 2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    save_json(out / 'component_candidates.json', boxes)
    write_image(out / 'component_candidates.png', preview)
    print(f'{len(boxes)} geometric candidates; choose crop from preview.')


def cmd_register(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    metadata = load_json(args.assets)
    asset_dir = Path(args.assets).resolve().parent
    target = rgb(asset_dir / metadata['bust'])
    cfg = load_json(args.config) if args.config else {}
    bust_to_body, content_box = asset_layout(metadata,target.shape)
    cfg['_content_box'] = content_box
    p, vs, rate = video_info(args.video)
    samples = sample_video(args.video, args.samples)
    anchors = load_json(args.anchors) if args.anchors else None
    if anchors is not None:
        frame_index = int(anchors['frame_index'])
        cap = cv2.VideoCapture(str(args.video))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, fr = cap.read()
        cap.release()
        if not ok:
            raise ValueError('Cannot read the specified anchor frame.')
        candidates = [(frame_index, cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))]
    else:
        # Representative frame minimizes sample-wide L1 difference; not guaranteed neutral.
        small = np.stack([cv2.resize(fr, (64, 64)) for _, fr in samples]).astype(float)
        med = np.median(small, axis=0)
        costs = np.mean(np.abs(small-med), axis=(1, 2, 3))
        order = np.argsort(costs)[:min(3, len(samples))]
        candidates = [samples[i] for i in order]
    fitted = []
    failures = []
    for index, frame in candidates:
        try:
            m, detail = solve(target, frame, cfg, anchors)
            fitted.append((index, frame, m, detail))
        except ValueError as exc:
            failures.append({'frame_index': index, 'error': str(exc)})
    if not fitted:
        raise ValueError('All representative-frame fits failed: ' + json.dumps(failures))
    index, frame, m, detail = min(fitted, key=lambda item: item[3]['chamfer_px'])
    x, y, cw, ch = metadata['bust_box_body']
    body_matrix = (homogeneous(bust_to_body) @ homogeneous(m))[:2]
    aligned = warp(frame, m, target.shape)
    overlay = np.rint(target.astype(float)*0.5 + aligned.astype(float)*0.5).astype(np.uint8)
    write_image(out / 'alignment_overlay.png', overlay)
    # Red=source ink, cyan=animated ink; aligned strokes appear pale/white.
    e0, e1 = edges(target), warp(edges(frame), m, target.shape, 0)
    edge_preview = np.stack([e0, e1, e1], axis=-1)
    write_image(out / 'alignment_edges.png', edge_preview)
    stable = stable_mask(target.shape, cfg)
    diagnostics = []
    for fi, fr in samples:
        mm, cc = refine(target, fr, m, stable)
        diagnostics.append({'frame_index': fi, **quality(target, fr, m, stable),
                            'local_refine_shift_px': float(np.linalg.norm(mm[:, 2]-m[:, 2])) if cc is not None else None})
    temporal_passes = sum(d['chamfer_px'] <= cfg.get('max_chamfer_px', 2.0)
                          and d['edge_coverage'] >= cfg.get('min_edge_coverage', 0.55)
                          and d['valid_fraction'] >= cfg.get('min_valid_fraction', 0.55)
                          for d in diagnostics)
    temporal_fraction = temporal_passes / len(diagnostics)
    detail['sample_pass_fraction'] = temporal_fraction
    detail['quality_passed'] &= temporal_fraction >= cfg.get('min_sample_pass_fraction', 0.8)
    detail['body_origin_x'] = float(body_matrix[0, 2])
    detail['body_origin_y'] = float(body_matrix[1, 2])
    detail['projected_video_width'] = detail['scale'] * vs['width']
    detail['projected_video_height'] = detail['scale'] * vs['height']
    report = {'version': 1, 'assets': str(Path(args.assets).resolve()),
              'video': str(Path(args.video).resolve()), 'video_sha256': digest(args.video),
              'bust_sha256': digest(asset_dir / metadata['bust']),
              'body_sha256': digest(asset_dir / metadata['body']),
              'video_width': vs['width'], 'video_height': vs['height'],
              'fps': str(rate), 'reference_frame_index': index,
              'matrix_video_to_bust': m.tolist(), 'matrix_video_to_body': body_matrix.tolist(),
              'bust_box_body': [x,y,cw,ch], 'bust_content_box':content_box,
              'bust_to_body':bust_to_body.tolist(), 'quality':detail,
              'sample_diagnostics': diagnostics, 'config': cfg, 'fit_failures': failures,
              'fitted_candidates': [{'frame_index': i, **d} for i, fr, mat, d in fitted]}
    save_json(out / 'registration.json', report)
    print(json.dumps(detail, indent=2))
    if not detail['quality_passed']:
        raise ValueError('Quality gate failed. Inspect previews; tune stable regions or use anchors.')


def checked_inputs(reg_path):
    reg = load_json(reg_path)
    metadata = load_json(reg['assets'])
    asset_dir = Path(reg['assets']).parent
    bust = asset_dir / metadata['bust']
    body = asset_dir / metadata['body']
    for path, key in [(reg['video'], 'video_sha256'), (bust, 'bust_sha256'), (body, 'body_sha256')]:
        if digest(path) != reg[key]:
            raise ValueError(f'Input changed since registration: {path}; register again.')
    if metadata['bust_box_body'] != reg['bust_box_body']:
        raise ValueError('Crop metadata changed; register again.')
    body_rgb,bust_rgb = rgb(body),rgb(bust)
    mapping,content = asset_layout(metadata,bust_rgb.shape)
    if not np.allclose(mapping,reg.get('bust_to_body', [[1,0,reg['bust_box_body'][0]],[0,1,reg['bust_box_body'][1]]])):
        raise ValueError('Padding metadata changed; register again.')
    return reg,metadata,body_rgb,bust_rgb


def inward_feather(binary, width):
    if width <= 0:
        return binary.astype(np.float32) / 255
    # Pad before distance transform so an ROI touching the image border tapers inward.
    d = cv2.distanceTransform(np.pad((binary > 0).astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    t = np.clip(d / width, 0, 1)
    return t*t*(3-2*t)


def resolve_gate(args, cfg, bust):
    if args.gate:
        gate=load_json(args.gate)
    elif args.mouth_box:
        if args.region == 'lower-face' and (args.nose_y is None or args.jaw_y is None):
            raise ValueError('Lower-face box mode needs --nose-y and --jaw-y in bust pixels.')
        gate=masking.gate_from_box(args.mouth_box,bust.shape,args.nose_y,args.jaw_y,args.jaw_width)
    elif cfg.get('mask_gate'):
        gate=cfg['mask_gate']
    else:
        raise ValueError('Auto mask requires --gate, --mouth-box, or config mask_gate. '
                         'Use gate with landmarks/predictor, or edit-mask to click anatomy. '
                         'Broad animate_polygons alone are no longer accepted.')
    masking.gate_fields(gate,bust.shape,args.region,args.radius_scale)
    return gate


def cmd_mask(args):
    reg,metadata,body,bust=checked_inputs(args.registration)
    cfg=dict(reg['config'])
    if args.config:
        cfg.update(load_json(args.config))
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    _,content_box=asset_layout(metadata,bust.shape)
    content=rect_mask(bust.shape,content_box)
    info={}
    if args.polygon or args.points:
        if args.polygon:
            poly=load_json(args.polygon)
            if poly.get('image_size', [bust.shape[1],bust.shape[0]]) != [bust.shape[1],bust.shape[0]]:
                raise ValueError('Polygon image size differs from bust.')
            if poly.get('coordinate_space','bust-normalized') != 'bust-normalized':
                raise ValueError('Polygon must use bust-normalized coordinates.')
        else:
            pts=np.asarray(args.points,float).reshape(-1,2)
            pts=pts/[bust.shape[1]-1,bust.shape[0]-1]
            poly={'include_polygons':[pts.tolist()],'protect_polygons':[]}
        binary=poly_mask(bust.shape,poly['include_polygons'])
        protect=poly_mask(bust.shape,poly.get('protect_polygons',[])+cfg.get('protect_polygons',[]))
        method='explicit-polygons'
        save_json(out/'polygon.json',poly)
    else:
        gate=resolve_gate(args,cfg,bust)
        protect=poly_mask(bust.shape,cfg.get('protect_polygons',[])+gate.get('protect_polygons',[]))
        allowed=poly_mask(bust.shape,cfg['animate_polygons']) if cfg.get('animate_polygons') else None
        frames=sample_video(reg['video'],args.samples)
        m=np.asarray(reg['matrix_video_to_bust'],float)
        stack=np.stack([warp(fr,m,bust.shape) for _,fr in frames])
        valid=warp(np.full(frames[0][1].shape[:2],255,np.uint8),m,bust.shape,0)
        content[valid<254]=0
        binary,fields=masking.propose_mask(bust,stack,gate,content,protect,allowed,
            args.region,args.radius_scale,args.motion_threshold,args.difference_threshold,
            args.margin,args.min_area,stable_mask(bust.shape,cfg))
        method='anatomical-mouth-weighted-proposal'
        write_image(out/'motion_heatmap.png',np.uint8(np.clip(fields['variation']*4,0,255)))
        write_image(out/'weighted_motion.png',np.uint8(np.clip(fields['weighted_motion']*4,0,255)))
        write_image(out/'distance_weight.png',np.uint8(np.rint(fields['distance_weight']*255)))
        write_image(out/'anatomical_gate.png',fields['hard_gate'])
        save_json(out/'gate.json',gate)
        info={'region':args.region,'static_noise_floor':fields['static_noise_floor'],
              'motion_threshold':args.motion_threshold,'difference_threshold':args.difference_threshold,
              'radius_scale':args.radius_scale,'gate':gate}
    binary[(protect>0)|(content==0)]=0
    if not np.any(binary):
        raise ValueError('Empty mask after anatomical/protection/content clipping; inspect gate.')
    alpha=np.uint8(np.rint(inward_feather(binary,args.feather)*255))
    write_image(out/'mask.png',alpha)
    tint=bust.copy()
    tint[alpha>0]=np.uint8(.65*tint[alpha>0]+.35*np.array([255,0,160]))
    write_image(out/'mask_preview.png',tint)
    save_json(out/'mask_info.json',{'method':method,'feather_bust_px':args.feather,
        'coverage_fraction':float(np.mean(alpha>0)),'registration_sha256':digest(args.registration),**info})
    print(f'Mask saved: {out / "mask.png"}; inspect gate and open/closed mouth previews.')


def cmd_gate(args):
    reg,metadata,body,bust=checked_inputs(args.registration)
    if args.landmarks:
        pts=np.loadtxt(args.landmarks,dtype=float).reshape(-1,2)
        mapping,content=asset_layout(metadata,bust.shape)
        if args.landmark_space=='content':
            pts+=content[:2]
        elif args.landmark_space=='body':
            pts-=mapping[:,2]
        if args.landmark_affine:
            affine=np.asarray(args.landmark_affine,float).reshape(2,3)
            pts=pts @ affine[:,:2].T+affine[:,2]
    else:
        try:
            import dlib
        except ImportError as e:
            raise ValueError('Optional dlib is not installed. Use --landmarks or edit-mask instead.') from e
        predictor=dlib.shape_predictor(str(Path(args.predictor).resolve()))
        if args.face_box:
            x,y,w,h=box_checked(args.face_box,bust.shape[1],bust.shape[0])
            face=dlib.rectangle(x,y,x+w-1,y+h-1)
        else:
            faces=dlib.get_frontal_face_detector()(bust,1)
            if len(faces)!=1:
                raise ValueError(f'Detected {len(faces)} faces; use --face-box or edit-mask.')
            face=faces[0]
        shape=predictor(bust,face)
        pts=np.array([[shape.part(i).x,shape.part(i).y] for i in range(shape.num_parts)])
    gate=masking.gate_from_landmarks(pts,bust.shape)
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    hard,weight,core,seed=masking.gate_fields(gate,bust.shape,args.region)
    preview=bust.copy()
    preview[hard>0]=np.uint8(.7*preview[hard>0]+.3*np.array([0,180,240]))
    for x,y in pts:
        cv2.circle(preview,(round(x),round(y)),1,(255,0,0),-1)
    save_json(out/'gate.json',gate)
    write_image(out/'gate_preview.png',preview)
    np.savetxt(out/'landmarks_bust.txt',pts,fmt='%.4f')
    print(f'Gate written to {out / "gate.json"}; verify landmark fit before masking.')


def cmd_edit_mask(args):
    from mask_editor import write_editor
    reg,metadata,body,bust=checked_inputs(args.registration)
    initial=load_json(args.load) if args.load else None
    write_editor(args.out,bust,initial)
    print(f'Open {Path(args.out).resolve()} in a browser; draw polygons or click anatomy, then export.')


def srgb_decode(v):
    v = v.astype(np.float32) / 255
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055)**2.4)


def srgb_encode(v):
    v = np.clip(v, 0, 1)
    return np.uint8(np.rint(np.clip(np.where(v <= 0.0031308, v*12.92,
                                            1.055*np.power(v, 1/2.4)-0.055), 0, 1)*255))


def compose(base, face, alpha, m):
    # Work only inside the animated region; static body pixels need no per-frame gamma conversion.
    yy,xx=np.nonzero(alpha)
    if not len(xx):return base.copy()
    x0,x1=int(xx.min()),int(xx.max())+1;y0,y1=int(yy.min()),int(yy.max())+1
    matrix=np.asarray(m,dtype=np.float32).copy();matrix[:,2]-=[x0,y0]
    shape=(y1-y0,x1-x0)
    aligned=warp(face,matrix,shape)
    valid=warp(np.full(face.shape[:2],255,np.uint8),matrix,shape,0).astype(np.float32)/255
    local=alpha[y0:y1,x0:x1];a=(local.astype(np.float32)/255*valid)[...,None]
    static=base[y0:y1,x0:x1]
    patch=srgb_encode(srgb_decode(static)*(1-a)+srgb_decode(aligned)*a)
    patch[local==0]=static[local==0]
    result=base.copy();result[y0:y1,x0:x1]=patch
    return result


def capture_count(path):
    cap = cv2.VideoCapture(str(path))
    try:
        return cap.get(cv2.CAP_PROP_FRAME_COUNT)
    finally:
        cap.release()


def cmd_render(args):
    reg, metadata, body, bust = checked_inputs(args.registration)
    if not reg['quality']['quality_passed']:
        raise ValueError('Registration did not pass quality checks; register again.')
    # Explicit mask path allows using a reviewed/edited candidate without semantic guessing.
    with Image.open(args.mask) as im:
        mask = np.asarray(im.convert('L')).copy()
    if mask.shape != bust.shape[:2] or not mask.any():
        raise ValueError('Mask must be nonempty and have the exact bust dimensions.')
    m = validate_similarity(np.asarray(reg['matrix_video_to_body']))
    h, w = body.shape[:2]
    alpha = np.zeros((h, w), np.uint8)
    x, y, cw, ch = metadata['bust_box_body']
    _,content_box=asset_layout(metadata,bust.shape)
    px,py,pw,ph=content_box
    alpha[y:y+ch,x:x+cw]=mask[py:py+ph,px:px+pw]
    samples = sample_video(reg['video'], min(6, args.preview_samples))
    preview = Path(args.preview_dir)
    preview.mkdir(parents=True, exist_ok=True)
    for i, fr in samples:
        write_image(preview / f'frame_{i:06d}.png', compose(body, fr, alpha, m))
    if args.preview_only:
        print(f'Lossless RGB previews saved to {preview}')
        return
    if not shutil.which('ffmpeg'):
        raise RuntimeError('ffmpeg is not on PATH.')
    p, stream, rate = video_info(reg['video'])
    audio_path = args.audio or reg['video']
    audio_probe = probe(audio_path)
    has_audio = any(s['codec_type'] == 'audio' for s in audio_probe['streams'])
    if args.audio and not has_audio:
        raise ValueError('Explicit audio input contains no audio stream.')
    output = Path(args.output).resolve()
    if output.exists() and not args.overwrite:
        raise ValueError('Output exists; choose another name or use --overwrite.')
    protected_inputs = {Path(reg['video']).resolve(), Path(audio_path).resolve(),
                        Path(reg['assets']).resolve(), Path(args.mask).resolve()}
    asset_dir = Path(reg['assets']).parent
    protected_inputs |= {(asset_dir / metadata[k]).resolve() for k in ['body', 'bust']}
    if output in protected_inputs:
        raise ValueError('Output would overwrite an input.')
    output.parent.mkdir(parents=True, exist_ok=True)
    common = ['ffmpeg', '-hide_banner', '-y' if args.overwrite else '-n', '-f', 'rawvideo',
              '-pix_fmt', 'rgb24', '-s:v', f'{w}x{h}', '-r', str(rate), '-i', 'pipe:0']
    if has_audio:
        common += ['-i', str(Path(audio_path).resolve())]
    common += ['-map', '0:v:0']
    if has_audio:
        common += ['-map', '1:a:0', '-c:a', 'aac', '-b:a', '192k']
    else:
        common += ['-an']
    if args.encoder == 'ffv1':
        if output.suffix.lower() != '.mkv':
            raise ValueError('FFV1 master needs an .mkv output.')
        common += ['-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'bgr0']
    else:
        # Pad right/bottom only. 701x1013 becomes 702x1014, never silently resize.
        common += ['-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:white', '-pix_fmt', 'yuv420p']
        if args.encoder == 'nvenc':
            common += ['-c:v', 'h264_nvenc', '-preset', 'p6', '-rc', 'vbr', '-cq', '18', '-b:v', '0']
        else:
            common += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18']
        common += ['-movflags', '+faststart']
    # Video EOF determines duration. Short audio does not truncate the rendered frames.
    expected_count = int(capture_count(reg['video']))
    if expected_count <= 0:
        raise ValueError('Cannot establish output duration.')
    if has_audio:
        common += ['-af', 'apad']
    common += ['-t', format(float(expected_count / rate), '.9f'), str(output)]
    logpath = output.with_suffix(output.suffix + '.ffmpeg.log')
    capture = cv2.VideoCapture(reg['video'])
    count = 0
    try:
        with open(logpath, 'wb') as log:
            process = subprocess.Popen(common, stdin=subprocess.PIPE, stderr=log)
            try:
                while True:
                    ok, bgr = capture.read()
                    if not ok:
                        break
                    frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    if frame.shape[:2] != (reg['video_height'], reg['video_width']):
                        raise ValueError('Video frame dimensions changed.')
                    result = compose(body, frame, alpha, m)
                    process.stdin.write(np.ascontiguousarray(result).tobytes())
                    count += 1
            except BaseException:
                process.stdin.close()
                process.wait()
                raise
            process.stdin.close()
            code = process.wait()
            if code or count == 0:
                raise RuntimeError(f'FFmpeg failed ({code}); see {logpath}. For NVENC try --encoder x264.')
    finally:
        capture.release()
    if count != expected_count:
        raise RuntimeError(f'Decoded {count}/{expected_count} frames; output may be incomplete.')
    expected = stream.get('nb_frames')
    if expected and expected.isdigit() and count != int(expected):
        raise RuntimeError(f'Decoded {count}/{expected} frames; output may be incomplete.')
    save_json(output.with_suffix(output.suffix + '.json'),
              {'frames': count, 'fps': str(rate), 'duration_seconds': float(count/rate),
               'input_canvas': [w, h], 'encoder': args.encoder,
               'registration_sha256': digest(args.registration), 'mask_sha256': digest(args.mask),
               'audio': str(Path(audio_path).resolve()) if has_audio else None,
               'command': common, 'output_probe': probe(output)})
    print(f'{count} frames rendered to {output}')


def cmd_inspect(args):
    p, s, rate = video_info(args.video)
    print(json.dumps({'width': s['width'], 'height': s['height'], 'fps': str(rate),
                      'pixel_format': s.get('pix_fmt'), 'color_range': s.get('color_range'),
                      'color_space': s.get('color_space'),
                      'duration': p.get('format', {}).get('duration'),
                      'audio_streams': sum(s['codec_type']=='audio' for s in p['streams'])}, indent=2))
    if args.landmarks:
        pts = np.loadtxt(args.landmarks, dtype=float).reshape(-1, 2)
        if pts.shape != (68, 2) or not np.isfinite(pts).all():
            raise ValueError('Expected exactly 68 finite 2D landmark pairs.')
        print('Landmarks require their own documented coordinate space, not video dimensions.')
        print(json.dumps({'outer_eye_span': float(np.linalg.norm(pts[45]-pts[36])),
                          'nose_tip': pts[30].tolist(), 'chin': pts[8].tolist()}, indent=2))
    if args.mat:
        from scipy.io import loadmat
        print({k: str(v.shape) for k, v in loadmat(args.mat).items() if not k.startswith('__')})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest='command', required=True)
    q = sp.add_parser('components', help='Propose character-sheet bounding boxes')
    q.add_argument('--sheet', required=True); q.add_argument('--out', required=True)
    q.add_argument('--threshold', type=int, default=245)
    q.add_argument('--join', type=int, default=11); q.add_argument('--min-area', type=int, default=1000)
    q.set_defaults(func=cmd_components)
    q = sp.add_parser('extract')
    q.add_argument('--sheet', required=True); q.add_argument('--out', required=True)
    q.add_argument('--body', type=int, nargs=4, required=True, metavar=('X','Y','W','H'))
    q.add_argument('--bust', type=int, nargs=4, required=True, metavar=('X','Y','W','H'))
    q.add_argument('--square-pad',action='store_true',help='Center-pad extracted rectangle without resizing')
    q.add_argument('--pad-color',type=int,nargs=3,default=[255,255,255],metavar=('R','G','B'))
    q.set_defaults(func=cmd_extract)
    q = sp.add_parser('register')
    q.add_argument('--assets', required=True); q.add_argument('--video', required=True)
    q.add_argument('--out', required=True); q.add_argument('--config'); q.add_argument('--anchors')
    q.add_argument('--samples', type=int, default=9); q.set_defaults(func=cmd_register)
    q = sp.add_parser('mask')
    q.add_argument('--registration', required=True); q.add_argument('--out', required=True)
    q.add_argument('--config',help='Override mask configuration without re-registering')
    group=q.add_mutually_exclusive_group()
    group.add_argument('--polygon'); group.add_argument('--points',type=float,nargs='+',help='Pixel X Y pairs')
    group.add_argument('--gate'); group.add_argument('--mouth-box',type=float,nargs=4,metavar=('X','Y','W','H'))
    q.add_argument('--nose-y',type=float); q.add_argument('--jaw-y',type=float); q.add_argument('--jaw-width',type=float)
    q.add_argument('--region',choices=['mouth','lower-face'],default='mouth')
    q.add_argument('--radius-scale',type=float,default=1.)
    q.add_argument('--samples', type=int, default=25)
    q.add_argument('--motion-threshold', type=float, default=12)
    q.add_argument('--difference-threshold', type=float, default=22)
    q.add_argument('--min-area', type=int, default=12); q.add_argument('--margin', type=int, default=3)
    q.add_argument('--feather', type=float, default=1.5); q.set_defaults(func=cmd_mask)
    q=sp.add_parser('gate',help='Construct anatomical gate from source landmarks or optional dlib')
    q.add_argument('--registration',required=True); q.add_argument('--out',required=True)
    group=q.add_mutually_exclusive_group(required=True)
    group.add_argument('--landmarks'); group.add_argument('--predictor')
    q.add_argument('--face-box',type=int,nargs=4)
    q.add_argument('--landmark-space',choices=['bust','content','body'],default='bust')
    q.add_argument('--landmark-affine',type=float,nargs=6,help='Explicit detector-to-bust affine a b tx c d ty')
    q.add_argument('--region',choices=['mouth','lower-face'],default='mouth'); q.set_defaults(func=cmd_gate)
    q=sp.add_parser('edit-mask',help='Generate a standalone local polygon/anatomy editor')
    q.add_argument('--registration',required=True); q.add_argument('--out',required=True)
    q.add_argument('--load',help='Initial polygon or gate JSON'); q.set_defaults(func=cmd_edit_mask)
    q = sp.add_parser('render')
    q.add_argument('--registration', required=True); q.add_argument('--mask', required=True)
    q.add_argument('--output', default='composite.mp4'); q.add_argument('--audio')
    q.add_argument('--encoder', choices=['x264', 'nvenc', 'ffv1'], default='x264')
    q.add_argument('--overwrite', action='store_true'); q.add_argument('--preview-only', action='store_true')
    q.add_argument('--preview-dir', default='preview'); q.add_argument('--preview-samples', type=int, default=6)
    q.set_defaults(func=cmd_render)
    q = sp.add_parser('inspect')
    q.add_argument('--video', required=True); q.add_argument('--landmarks'); q.add_argument('--mat')
    q.set_defaults(func=cmd_inspect)
    a = p.parse_args()
    if hasattr(a, 'samples') and a.samples < 1:
        p.error('--samples must be positive')
    if hasattr(a,'pad_color') and any(c<0 or c>255 for c in a.pad_color):
        p.error('--pad-color requires 0..255 RGB values')
    if hasattr(a,'points') and a.points is not None and (len(a.points)<6 or len(a.points)%2):
        p.error('--points requires at least three X Y pairs')
    if a.command=='gate' and a.landmark_affine and a.landmark_space!='bust':
        p.error('--landmark-affine maps raw detector coordinates directly to bust; do not combine with another space')
    if a.command=='mask' and (a.margin<0 or a.feather<0 or a.min_area<1 or a.motion_threshold<0 or a.difference_threshold<0):
        p.error('Mask sizes/thresholds must be nonnegative; min-area must be positive')
    try:
        a.func(a)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as e:
        p.exit(1, f'ERROR: {e}\n')


if __name__ == '__main__':
    main()
