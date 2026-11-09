"""Face finding for video frames: small faces in wide shots and close-ups alike.

OpenCV's bundled Haar cascade proposes boxes on the full-resolution frame
(it still finds ~20 px faces in a wide room shot). When MediaPipe and the
face-landmarker model Studio already uses for anatomy are available, every
proposal is refined on an upscaled crop: false positives are dropped and
each face gets landmark-derived measures (mouth opening, frontality, eyes).
Without MediaPipe the Haar boxes are returned unrefined.
"""
import math
import os
from pathlib import Path

import numpy as np

MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
_cache = {}


def model_path(root):
    """Reuse a project's (or the shared tools') landmarker; download once if absent."""
    candidates = [Path(root) / 'models/anatomy/face_landmarker.task']
    home = os.environ.get('STUDIO_TOOLS_HOME') or (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PuppetStudio/tools')
    candidates.append(Path(home) / 'models/face_landmarker.task')
    for c in candidates:
        if c.is_file():
            return c
    target = candidates[0]
    if os.environ.get('STUDIO_AGENT_OFFLINE'):
        raise FileNotFoundError('Face landmarker model not present (offline mode)')
    import urllib.request
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.download')
    urllib.request.urlretrieve(MODEL_URL, tmp)
    tmp.replace(target)
    return target


def _landmarker(root):
    if 'lm' in _cache:
        return _cache['lm']
    try:
        import mediapipe as mp
        opts = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path(root)),
                                              delegate=mp.tasks.BaseOptions.Delegate.CPU),
            num_faces=4, min_face_detection_confidence=.4, min_face_presence_confidence=.4)
        _cache['lm'] = (mp, mp.tasks.vision.FaceLandmarker.create_from_options(opts))
    except Exception:  # optional dependency or offline: Haar-only mode
        _cache['lm'] = None
    return _cache['lm']


def _haar():
    if 'haar' not in _cache:
        import cv2 as cv
        _cache['haar'] = cv.CascadeClassifier(str(Path(cv.data.haarcascades) / 'haarcascade_frontalface_default.xml'))
    return _cache['haar']


def _measures(points, w, h):
    """Landmark measures in a crop of size w x h (points normalized 0-1)."""
    p = np.array([[pt.x * w, pt.y * h] for pt in points])
    top, chin = p[10], p[152]
    face_h = max(1.0, float(np.linalg.norm(chin - top)))
    mouth = float(np.linalg.norm(p[14] - p[13])) / face_h
    left, right, nose = p[33], p[263], p[1]
    span = right[0] - left[0]
    frontal = 1 - min(1.0, abs((nose[0] - left[0]) / span - .5) * 2) if abs(span) > 1 else 0.0
    eye = (np.linalg.norm(p[159] - p[145]) + np.linalg.norm(p[386] - p[374])) / 2 / face_h
    x0, y0 = p.min(0)
    x1, y1 = p.max(0)
    return {'mouth_open': round(mouth, 4), 'frontal': round(float(frontal), 3),
            'eyes_open': round(float(eye), 4), 'box': [float(x0), float(y0), float(x1 - x0), float(y1 - y0)]}


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / max(1e-6, aw * ah + bw * bh - inter)


def _refine(lm, rgb, box):
    """Run the landmarker on an upscaled crop around box; return face dict or None."""
    mp, detector = lm
    import cv2 as cv
    H, W = rgb.shape[:2]
    x, y, w, h = box
    side = max(w, h) * 2.0
    cx, cy = x + w / 2, y + h / 2
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    x1, y1 = int(min(W, cx + side / 2)), int(min(H, cy + side / 2))
    crop = rgb[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    k = 320 / max(crop.shape[:2])
    big = cv.resize(crop, (max(1, round(crop.shape[1] * k)), max(1, round(crop.shape[0] * k))),
                    interpolation=cv.INTER_CUBIC if k > 1 else cv.INTER_AREA)
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(big)))
    best = None
    for points in result.face_landmarks:
        m = _measures(points, big.shape[1], big.shape[0])
        bx, by, bw, bh = m['box']
        m['box'] = [x0 + bx / k, y0 + by / k, bw / k, bh / k]
        if best is None or _iou(m['box'], box) > _iou(best['box'], box):
            best = m
    return best


def detect(root, rgb, min_size=18):
    """Faces in an RGB uint8 frame: [{'box':[x,y,w,h] px, 'mouth_open', 'frontal', ...}]."""
    import cv2 as cv
    gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
    boxes = [list(map(float, b)) for b in _haar().detectMultiScale(gray, 1.08, 4, minSize=(min_size, min_size))]
    lm = _landmarker(root)
    faces = []
    if lm:
        mp, detector = lm
        # Whole-frame pass catches large faces Haar misses (tilted, partially lit).
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        for points in result.face_landmarks:
            boxes.append(_measures(points, rgb.shape[1], rgb.shape[0])['box'])
        for b in boxes:
            if any(_iou(b, f['box']) > .3 for f in faces):
                continue
            f = _refine(lm, rgb, b)
            if f and f['box'][2] >= min_size * .8 and not any(_iou(f['box'], g['box']) > .3 for g in faces):
                faces.append(f)
    else:
        for b in boxes:
            if not any(_iou(b, f['box']) > .3 for f in faces):
                faces.append({'box': b, 'mouth_open': None, 'frontal': None, 'eyes_open': None})
    for f in faces:
        x, y, w, h = map(int, f['box'])
        patch = gray[max(0, y):y + h, max(0, x):x + w]
        f['sharpness'] = round(float(cv.Laplacian(patch, cv.CV_64F).var()) if patch.size else 0.0, 1)
        f['box'] = [round(v, 1) for v in f['box']]
    return sorted(faces, key=lambda f: -f['box'][2] * f['box'][3])


def portrait_box(face_box, width, height, scale=3.2, aspect=.8):
    """Head-and-shoulders crop around a face box, clamped to the frame."""
    x, y, w, h = face_box
    ch = h * scale
    cw = ch * aspect
    cx = x + w / 2
    cy = y + h * .5 + ch * .18  # shift down: more shoulders than headroom
    x0, y0 = max(0, cx - cw / 2), max(0, cy - ch / 2)
    x1, y1 = min(width, x0 + cw), min(height, y0 + ch)
    return [round(x0), round(y0), round(x1), round(y1)]


def quality(face, frame_w, frame_h):
    """0-1 reference-photo score: size dominates, then sharpness, frontality, open eyes."""
    size = min(1.0, math.sqrt(face['box'][2] * face['box'][3]) / (.35 * min(frame_w, frame_h)))
    sharp = min(1.0, face['sharpness'] / 400)
    frontal = face['frontal'] if face['frontal'] is not None else .5
    eyes = min(1.0, (face['eyes_open'] or .03) / .045)
    mouth = face['mouth_open'] if face['mouth_open'] is not None else .03
    calm = 1 - min(1.0, max(0.0, mouth - .05) / .08)  # mid-word wide mouths make poor likeness references
    return round(.5 * size + .18 * sharp + .14 * frontal + .09 * eyes + .09 * calm, 3)
