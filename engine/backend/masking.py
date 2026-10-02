"""Anatomically bounded, mouth-weighted matte proposals. No whole-bust fallback."""
import cv2
import numpy as np


def validate_points(points, shape):
    pts = np.asarray(points, dtype=float)
    h, w = shape[:2]
    if pts.shape != (68, 2) or not np.isfinite(pts).all():
        raise ValueError('Expected 68 finite 2D landmarks in the named source space.')
    if (pts < 0).any() or (pts[:, 0] > w-1).any() or (pts[:, 1] > h-1).any():
        raise ValueError('Landmarks outside bust. Convert detector/crop coordinates explicitly.')
    lips = pts[48:68]
    mw = np.ptp(lips[:, 0])
    if mw < 4 or np.ptp(lips[:, 1]) < 1 or not (pts[33, 1] < lips[:, 1].mean() < pts[8, 1]):
        raise ValueError('Implausible mouth/nose/chin geometry; inspect landmarks or use editor.')
    return pts


def gate_from_landmarks(points, shape):
    pts = validate_points(points, shape)
    h, w = shape[:2]
    lips = pts[48:68]
    lo, hi = lips.min(axis=0), lips.max(axis=0)
    center = (lo + hi) / 2
    # Exclude outer jaw endpoints near ears, and clip the entire contour below nose base.
    top, bottom = float(pts[33, 1]), float(pts[8, 1])
    contour = np.vstack([pts[31], pts[35], pts[3:14]])
    contour[:, 1] = np.clip(contour[:, 1], top, bottom)
    contour = cv2.convexHull(contour.astype(np.float32)).reshape(-1, 2)
    return {'version': 2, 'coordinate_space': 'bust-normalized', 'image_size': [w, h],
            'mouth_box': [lo[0]/(w-1), lo[1]/(h-1), (hi[0]-lo[0])/(w-1), (hi[1]-lo[1])/(h-1)],
            'mouth_center': (center/[w-1, h-1]).tolist(),
            'nose_y': top/(h-1), 'jaw_y': bottom/(h-1),
            'jaw_polygon': (contour/[w-1, h-1]).tolist(),
            'source': '68-landmarks', 'protect_polygons': []}


def gate_from_box(box, shape, nose_y=None, jaw_y=None, jaw_width=None):
    h, w = shape[:2]
    x, y, mw, mh = map(float, box)
    if min(x, y) < 0 or min(mw, mh) < 2 or x+mw > w-1 or y+mh > h-1:
        raise ValueError('Mouth box must be finite, at least 2x2 and inside the bust.')
    if not np.isfinite([x,y,mw,mh]).all():
        raise ValueError('Mouth box must be finite.')
    # Box-only mode deliberately stays local to the mouth; anatomy must be supplied for jaw coverage.
    top = max(0, y-mh) if nose_y is None else float(nose_y)
    bottom = min(h-1, y+2*mh) if jaw_y is None else float(jaw_y)
    if not 0 <= top < y+mh/2 < bottom <= h-1 or top > y or bottom < y+mh:
        raise ValueError('Need nose_y <= mouth top and jaw_y >= mouth bottom, within bust.')
    jw = float(jaw_width) if jaw_width is not None else mw*1.8
    if not np.isfinite(jw) or jw < mw:
        raise ValueError('Jaw width must be finite and at least the mouth width.')
    cx, cy = x+mw/2, y+mh/2
    # Truncated cone: narrow at nose, broad across lower cheeks, narrower at chin.
    polygon = np.array([[cx-mw*.45, top], [cx+mw*.45, top],
                        [cx+jw*.5, cy+mh*.25], [cx+jw*.36, bottom],
                        [cx-jw*.36, bottom], [cx-jw*.5, cy+mh*.25]])
    polygon = np.clip(polygon, [0,0], [w-1,h-1])
    return {'version': 2, 'coordinate_space': 'bust-normalized', 'image_size': [w,h],
            'mouth_box': [x/(w-1), y/(h-1), mw/(w-1), mh/(h-1)],
            'mouth_center': [cx/(w-1), cy/(h-1)], 'nose_y': top/(h-1), 'jaw_y': bottom/(h-1),
            'jaw_polygon': (polygon/[w-1,h-1]).tolist(), 'source': 'explicit-mouth-box',
            'protect_polygons': []}


def gate_fields(gate, shape, region='mouth', radius_scale=1.0):
    h, w = shape[:2]
    if gate.get('coordinate_space') != 'bust-normalized':
        raise ValueError('Gate must declare coordinate_space=bust-normalized.')
    if gate.get('image_size') != [w,h]:
        raise ValueError('Gate image size differs from bust; regenerate it.')
    b = np.asarray(gate['mouth_box'], float)
    if b.shape != (4,) or not np.isfinite(b).all() or (b < 0).any() or (b > 1).any():
        raise ValueError('Invalid normalized mouth_box.')
    x,y,mw,mh = b * [w-1,h-1,w-1,h-1]
    if min(mw,mh) < 1 or x+mw > w-1+.001 or y+mh > h-1+.001:
        raise ValueError('Invalid mouth extent.')
    center=np.asarray(gate['mouth_center'],float)
    if center.shape!=(2,) or not np.isfinite(center).all():
        raise ValueError('Invalid mouth center.')
    cx,cy=center*[w-1,h-1]
    if not x <= cx <= x+mw or not y <= cy <= y+mh:
        raise ValueError('Mouth center must lie inside mouth box.')
    top, bottom = float(gate['nose_y'])*(h-1), float(gate['jaw_y'])*(h-1)
    if not (0 <= top <= y < cy < y+mh <= bottom <= h-1):
        raise ValueError('Invalid nose/mouth/chin ordering; fix gate in editor.')
    poly = np.asarray(gate['jaw_polygon'], float)
    if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3 or not np.isfinite(poly).all() or (poly<0).any() or (poly>1).any():
        raise ValueError('Invalid jaw polygon.')
    if not .25 <= radius_scale <= 3:
        raise ValueError('--radius-scale must be between 0.25 and 3.')
    hard = np.zeros((h,w), np.uint8)
    cv2.fillPoly(hard, [np.rint(poly*[w-1,h-1]).astype(np.int32)], 255)
    yy,xx = np.mgrid[:h,:w]
    # Even malformed/expanded polygons cannot cross explicit anatomical top/bottom planes.
    hard[(yy < np.ceil(top)) | (yy > np.floor(bottom))] = 0
    rx = max(3, mw * (0.95 if region == 'mouth' else 1.45)) * radius_scale
    ry = max(mh*1.8, mw*.30) if region == 'mouth' else max(bottom-cy, cy-top)*1.30
    ry = max(3, ry) * radius_scale
    r2 = ((xx-cx)/rx)**2 + ((yy-cy)/ry)**2
    weight = np.maximum(0, 1-r2)**2
    weight[hard == 0] = 0
    hard[(r2 >= 1)] = 0
    # Persistent source-image mismatch is permitted only near the mouth, never across the jaw/torso.
    core = (r2 <= .40) & (hard > 0)
    seed = np.zeros((h,w), np.uint8)
    cv2.rectangle(seed, (int(np.floor(x)),int(np.floor(y))),
                  (int(np.ceil(x+mw)),int(np.ceil(y+mh))), 255, -1)
    seed[hard == 0] = 0
    if not seed.any():
        raise ValueError('Gate excludes the mouth; fix the jaw contour.')
    return hard, weight.astype(np.float32), core, seed


def propose_mask(bust, stack, gate, content, protect, allowed=None, region='mouth',
                 radius_scale=1., motion_threshold=12., difference_threshold=22., margin=3,
                 min_area=12, stable=None):
    hard, weight, core, seed = gate_fields(gate, bust.shape, region, radius_scale)
    hard[(content == 0) | (protect > 0)] = 0
    if allowed is not None:
        hard[allowed == 0] = 0
    weight[hard == 0] = 0
    seed[hard == 0] = 0
    # Reduce codec-scale pixel noise before measuring differences.
    stack = np.stack([cv2.GaussianBlur(fr.astype(np.float32),(3,3),.6) for fr in stack])
    source = cv2.GaussianBlur(bust.astype(np.float32),(3,3),.6)
    ref = ((stable > 0) if stable is not None else (content > 0)) & (hard == 0)
    ref &= content > 0
    if ref.sum() >= 100:
        offsets = np.median((stack-source)[:,ref,:],axis=1)
        offsets = np.clip(offsets,-15,15)
        stack = np.clip(stack-offsets[:,None,None,:],0,255)
    q10,q90 = np.percentile(stack,[10,90],axis=0)
    variation = np.max(q90-q10,axis=2)
    differences = np.percentile(np.max(np.abs(stack-source),axis=3),90,axis=0)
    # Estimate static noise independently of the moving mouth; avoid unbounded suppression.
    noise = float(np.clip(np.percentile(variation[ref],70),0,8)) if ref.sum() >= 100 else 0.
    signal = np.maximum(variation-noise,0)*weight
    active = (signal > motion_threshold) | ((differences*weight > difference_threshold) & core)
    active &= hard > 0
    active |= seed > 0  # Include original mouth ink even when there is little measured motion.
    binary = active.astype(np.uint8)*255
    binary = cv2.morphologyEx(binary,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    binary[hard == 0] = 0
    n,labels,stats,_ = cv2.connectedComponentsWithStats(binary)
    keep = np.zeros_like(binary)
    attachment = cv2.dilate(seed,np.ones((7,7),np.uint8)) > 0
    for i in range(1,n):
        component = labels == i
        anchored = bool(np.any(component & attachment))
        if stats[i,cv2.CC_STAT_AREA] >= min_area and (anchored or region == 'lower-face'):
            keep[component] = 255
    if margin:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*margin+1,2*margin+1))
        keep = cv2.dilate(keep,k)
    # FINAL intersection after all morphology enforces zero spill, including protected holes.
    keep[hard == 0] = 0
    return keep, {'hard_gate': hard,'distance_weight': weight,'variation': variation,
                  'weighted_motion': signal,'static_noise_floor': noise,
                  'mouth_seed': seed,'source_core': core.astype(np.uint8)*255}
