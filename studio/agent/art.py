"""Artwork pipeline for agents: briefs, quality checks, provider drafts, import and review.

An agent can get figure art three ways, all ending in the same checked import:

1. ``gemini`` API route - set GEMINI_API_KEY (or the configured variable) and
   call ``generate``; the reference photos go in, a PNG draft comes out.
2. ``openai``-compatible images/edits route - Studio's existing provider.
3. A chat assistant in a browser (for example Gemini on the web through the
   agent's own computer-use/browser tools) - ``brief`` writes the exact prompt
   and gathers the reference images in one folder to upload; the downloaded
   result is then passed to ``import_art``.

Every draft is measured by ``check`` before import so the agent can re-prompt
with concrete corrections instead of importing a figure that will fail anatomy
detection or render badly.
"""
import base64
import io
import json
import os
import shutil
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from ..core import path, read

GEMINI_MODEL = 'gemini-2.5-flash-image'
GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'

REQUIREMENTS = [
    'Exactly one person: the whole seated figure, head to shoes, plus a plain chair.',
    'Portrait canvas, 2:3 (for example 1024 x 1536); figure centred, filling ~85% of the height, with a clear white margin on every side - nothing touches or crosses the edge.',
    'Pure flat white background (#FFFFFF). No floor, cast shadow, scenery, frame, text, captions, watermark, colour swatches or extra poses.',
    'Face toward the viewer (straight on or a slight three-quarter turn), both eyes open and visible, nothing covering the mouth, chin or jaw (no hand, microphone, beard over lips, mask or glasses glare).',
    'Mouth relaxed and gently parted, a small visible gap between the lips; not smiling widely, not closed tight.',
    'Neutral pose: sitting upright, hands resting on the thighs, arms clear of the face and neck; legs and feet fully visible.',
    'Clean illustration: consistent line weight, flat colours, minimal shading; no photographic texture or noise.',
]


def style_of(cfg, style=None):
    return (style or cfg.get('style') or '').strip()


def prompt(s, cfg, style=None, notes='', kind='neutral', description=''):
    """Model-agnostic generation prompt."""
    st = style_of(cfg, style)
    if kind == 'pose':
        return (f'Edit the attached puppet illustration of {s["name"]}. Keep the exact same canvas size, framing, art style, '
                f'colours, head, face, hair, chair, legs and feet - pixel-for-pixel where possible. Change ONLY the arms and '
                f'hands into this gesture: {description}. The hands stay between the shoulders and the knees and do not '
                f'cover the face, mouth or neck. Pure white background, no text, no extra figures.'
                + (f' {notes.strip()}' if notes.strip() else ''))
    who = f'{s["name"]}' + (f', {s["title"]}' if s.get('title') else '')
    lines = [
        f'Create a single full-body illustration of {who}, based on the attached reference photo(s). '
        'Capture their likeness: face shape, hairline and hair, skin tone, facial hair, glasses, age and build, '
        'and the clothing they wear in the reference.',
        f'Art style: {st}' if st else '',
        'Composition and requirements:',
        *[f'- {r}' for r in REQUIREMENTS],
        'This figure becomes a talking puppet, so the face must be clear and the mouth area unobstructed.',
        notes.strip(),
    ]
    return '\n'.join(x for x in lines if x)


def references(root, s):
    """All reference images for a speaker: the primary one first, then extras."""
    root = Path(root)
    found = []
    if s.get('reference'):
        found.append(path(root, s['reference']))
    extra = root / 'assets' / s['id'] / 'references'
    if extra.is_dir():
        found += sorted(f for f in extra.glob('*.png') if f not in found)
    return [f for f in found if f.is_file()]


def brief(root, p, s, style=None, notes='', kind='neutral', pose='', description=''):
    """Write handoff/art/<speaker>/ with BRIEF.md, prompt.txt and the images to upload."""
    root = Path(root)
    cfg = p['settings']
    if kind == 'pose':
        if not s.get('asset'):
            raise ValueError('Import the neutral figure before briefing a gesture.')
        if not pose or not description:
            raise ValueError('Gesture briefs need a pose ID and a description of the arm/hand gesture.')
        uploads = [path(root, s['asset'])]
    else:
        uploads = references(root, s)
        if not uploads:
            raise ValueError('No reference image yet: run find_reference_frames + set_reference (or import a photo with set_reference path=...).')
    folder = root / 'handoff' / 'art' / s['id']
    folder.mkdir(parents=True, exist_ok=True)
    staged = []
    for i, f in enumerate(uploads):
        dest = folder / (f'{"neutral" if kind == "pose" else "reference"}_{i + 1}.png')
        shutil.copy2(f, dest)
        staged.append(str(dest))
    text = prompt(s, cfg, style, notes, kind, description)
    (folder / 'prompt.txt').write_text(text + '\n', encoding='utf-8')
    downloads = root / 'imports'
    downloads.mkdir(exist_ok=True)
    save_as = downloads / (f'{s["id"]}_{pose or "neutral"}_{uuid.uuid4().hex[:6]}.png')
    steps = [
        'Open https://gemini.google.com/app (or another image-capable assistant the user is signed in to) in the browser.',
        'Start a new chat. If there is a model/tool picker, choose the image generation/editing option.',
        f'Attach the image file(s): {", ".join(staged)}.',
        f'Paste the full text of {folder / "prompt.txt"} as the message and send it.',
        'Wait for the image. If it violates a requirement, reply with one specific correction (see check_artwork suggestions) rather than starting over.',
        f'Download the full-resolution image (not a screenshot) and save or move it to {save_as} - any path works; pass it to import_artwork.',
        'Run check_artwork on the file; fix problems by re-prompting, then import_artwork.',
    ]
    doc = [f'# Art brief: {s["name"]} ({kind}{" " + pose if pose else ""})', '', '## Upload', *[f'- {x}' for x in staged],
           '', '## Prompt', '', text, '', '## Browser steps', *[f'{i + 1}. {x}' for i, x in enumerate(steps)], '',
           'The user must have signed in themselves; do not enter credentials. Generated art is a draft: likeness and anatomy need review.']
    (folder / 'BRIEF.md').write_text('\n'.join(doc) + '\n', encoding='utf-8')
    return {'speaker': s['id'], 'kind': kind, 'pose': pose, 'prompt': text, 'upload': staged,
            'brief': str(folder / 'BRIEF.md'), 'suggested_download_path': str(save_as), 'browser_steps': steps,
            'requirements': REQUIREMENTS if kind == 'neutral' else []}


# ------------------------------------------------------------------ checking
def _flatten(file):
    with Image.open(file) as im:
        im = ImageOps.exif_transpose(im)
        rgba = np.asarray(im.convert('RGBA'), np.float32) / 255
    a = rgba[:, :, 3:4]
    return np.uint8(np.rint((rgba[:, :, :3] * a + 1 - a) * 255)), bool(np.any(rgba[:, :, 3] < .99))


def _components(mask):
    import cv2 as cv
    n, lab, stats, _ = cv.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    return [stats[i] for i in range(1, n)]


def check(root, file, s=None, kind='neutral', neutral=None):
    """Measure a figure draft; return {'ok', 'errors', 'warnings', 'metrics', 'suggestions'}."""
    from . import faces
    import cv2 as cv
    rgb, transparent = _flatten(file)
    h, w = rgb.shape[:2]
    errors, warnings, fixes = [], [], []
    m = {'width': w, 'height': h, 'aspect': round(w / h, 3), 'transparent_background': transparent}
    if w * h > 16_000_000:
        errors.append('Image exceeds 16 megapixels.')
    if min(w, h) < 512:
        errors.append(f'Too small ({w}x{h}); ask for at least 1024 px on the short side.')
        fixes.append('Request a higher-resolution image (1024 x 1536).')
    ink = np.min(rgb, 2) < 235
    if not ink.any():
        return {'ok': False, 'errors': ['Image is blank.'], 'warnings': [], 'metrics': m, 'suggestions': ['Generate again.']}
    border = np.concatenate([rgb[:4].reshape(-1, 3), rgb[-4:].reshape(-1, 3), rgb[:, :4].reshape(-1, 3), rgb[:, -4:].reshape(-1, 3)])
    m['border_white'] = round(float(np.mean(np.min(border, 1) > 240)), 3)
    if m['border_white'] < .97:
        errors.append(f'Background is not clean white at the edges ({m["border_white"]:.0%} white).')
        fixes.append('Ask for a pure flat white (#FFFFFF) background with no floor, shadow or scenery, and a margin on every side.')
    k = max(3, round(min(w, h) / 200))
    solid = cv.morphologyEx(ink.astype(np.uint8), cv.MORPH_CLOSE, np.ones((k, k), np.uint8))
    parts = sorted(_components(solid), key=lambda st: -st[4])
    big = [st for st in parts if st[4] > .02 * parts[0][4]]
    m['separate_shapes'] = len(big)
    main = parts[0]
    if len(big) > 1:
        second = big[1][4] / main[4]
        m['second_shape_ratio'] = round(float(second), 3)
        if second > .25:
            errors.append(f'{len(big)} separate large shapes - looks like more than one figure, a pose sheet or swatches.')
            fixes.append('Ask for exactly one figure and nothing else on the canvas (no extra poses, swatches, text or props).')
        else:
            warnings.append(f'{len(big) - 1} detached shape(s) besides the figure (text, prop, or floating detail?). Check the preview.')
    ys, xs = np.nonzero(ink)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    m['figure_box'] = [x0, y0, x1 - x0 + 1, y1 - y0 + 1]
    m['figure_height_fraction'] = round((y1 - y0 + 1) / h, 3)
    margins = {'left': x0 / w, 'right': (w - 1 - x1) / w, 'top': y0 / h, 'bottom': (h - 1 - y1) / h}
    m['margins'] = {k2: round(v, 3) for k2, v in margins.items()}
    cut = [k2 for k2, v in margins.items() if v < .006]
    if cut:
        errors.append(f'Figure touches the {", ".join(cut)} edge - it may be cropped (feet, head or elbows cut off).')
        fixes.append('Ask for the entire figure, head to shoes, with a white margin on all sides.')
    if kind == 'neutral':
        if m['figure_height_fraction'] < .6:
            warnings.append(f'Figure fills only {m["figure_height_fraction"]:.0%} of the height; small figures lose face detail.')
            fixes.append('Ask for the figure to fill about 85% of the canvas height.')
        if m['aspect'] > .9:
            warnings.append('Canvas is wide for a single seated figure; a 2:3 portrait canvas works best.')
    found = faces.detect(root, rgb, min_size=24)
    m['faces_detected'] = len(found)
    if found:
        f = found[0]
        m['face'] = {'box': f['box'], 'height_fraction_of_figure': round(f['box'][3] / max(1, y1 - y0), 3),
                     'mouth_open': f['mouth_open'], 'frontal': f['frontal'], 'eyes_open': f['eyes_open'],
                     'sharpness': f['sharpness']}
        if len(found) > 1 and found[1]['box'][2] > .5 * f['box'][2]:
            errors.append(f'{len(found)} faces detected - only one person should be drawn.')
            fixes.append('Ask for exactly one person.')
        if f['frontal'] is not None and f['frontal'] < .45:
            warnings.append('Face is turned well away from the viewer; lip sync works best facing forward.')
            fixes.append('Ask for the face to look toward the viewer (straight on or a slight three-quarter turn).')
        if kind == 'neutral' and f['mouth_open'] is not None:
            if f['mouth_open'] < .012:
                warnings.append('Mouth looks closed; a gently parted mouth gives better talking-face results.')
                fixes.append('Ask for the lips gently parted with a small visible gap, relaxed, not smiling widely.')
            elif f['mouth_open'] > .09:
                warnings.append('Mouth is wide open; ask for a relaxed, slightly parted mouth.')
        if f['eyes_open'] is not None and f['eyes_open'] < .012:
            warnings.append('Eyes may be closed.')
    elif kind == 'neutral':
        errors.append('No face detected - anatomy calibration will fail on this artwork.')
        fixes.append('Ask for a clear, front-facing face with visible eyes, nose and mouth, and a larger figure.')
    if neutral is not None:
        ref = np.asarray(Image.open(neutral).convert('RGB'))
        m['neutral_size'] = [ref.shape[1], ref.shape[0]]
        if abs(ref.shape[1] / ref.shape[0] - w / h) > .03:
            errors.append(f'Gesture canvas aspect {w}x{h} does not match the neutral {ref.shape[1]}x{ref.shape[0]}.')
            fixes.append('Ask the assistant to keep the exact same canvas, size and framing as the attached figure.')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'metrics': m,
            'suggestions': list(dict.fromkeys(fixes))}


def preview(root, file, report=None):
    """Draft on white with the figure box and detected face marked."""
    rgb, _ = _flatten(file)
    im = Image.fromarray(rgb)
    d = ImageDraw.Draw(im)
    lw = max(2, round(max(im.size) / 400))
    if report:
        m = report['metrics']
        if m.get('figure_box'):
            x, y, bw, bh = m['figure_box']
            d.rectangle([x, y, x + bw, y + bh], outline=(0, 160, 255), width=lw)
        if m.get('face'):
            x, y, bw, bh = m['face']['box']
            d.rectangle([x, y, x + bw, y + bh], outline=(255, 0, 0), width=lw)
    return im


# ----------------------------------------------------------------- providers
def gemini(root, s, cfg, text, uploads, log=print):
    """Gemini image generation over REST. Returns the saved draft path (project-relative)."""
    env = cfg.get('gemini_key_env', 'GEMINI_API_KEY')
    key = os.environ.get(env) or (os.environ.get('GOOGLE_API_KEY') if env == 'GEMINI_API_KEY' else None)
    if not key:
        raise ValueError(f'Set {env} in the environment that launches the agent server (never in project JSON), '
                         'or use art_brief and a browser session instead.')
    model = cfg.get('gemini_model', GEMINI_MODEL)
    parts = [{'text': text}]
    for f in uploads:
        parts.append({'inline_data': {'mime_type': 'image/png', 'data': base64.b64encode(Path(f).read_bytes()).decode()}})
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseModalities': ['TEXT', 'IMAGE'], 'imageConfig': {'aspectRatio': '2:3'}}}
    req = urllib.request.Request(f'{GEMINI_BASE}/models/{model}:generateContent', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
    log(f'Requesting image from {model}...')
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode('utf-8', 'replace')
        raise ValueError(f'Gemini HTTP {e.code}: {detail}') from None
    except urllib.error.URLError:
        raise ValueError('Gemini connection failed') from None
    image, said = None, []
    for cand in data.get('candidates', []):
        for part in (cand.get('content') or {}).get('parts', []):
            blob = part.get('inlineData') or part.get('inline_data')
            if blob and blob.get('data'):
                image = base64.b64decode(blob['data'])
            elif part.get('text'):
                said.append(part['text'])
    if not image:
        reason = data.get('promptFeedback') or [c.get('finishReason') for c in data.get('candidates', [])]
        raise ValueError(f'Gemini returned no image ({reason}). Text: {" ".join(said)[:300]}')
    if len(image) > 20 * 1024 * 1024:
        raise ValueError('Image response exceeds 20 MiB')
    return _save_draft(root, s, image), ' '.join(said)[:500]


def _save_draft(root, s, raw):
    dest = Path(root) / 'assets' / s['id'] / f'draft_art_{uuid.uuid4().hex[:8]}.png'
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(raw)) as im:
        im.convert('RGBA').save(dest)
    return dest.relative_to(root).as_posix()


# -------------------------------------------------------------------- import
def stage(root, src):
    """Copy an outside file into imports/ so project-relative paths work."""
    root = Path(root).resolve()
    src = Path(str(src).strip().strip('"').strip("'")).expanduser()
    src = src if src.is_absolute() else root / src
    src = src.resolve()
    if not src.is_file():
        raise ValueError(f'File not found: {src}')
    if src.is_relative_to(root):
        return src
    dest = root / 'imports' / (uuid.uuid4().hex[:8] + src.suffix.lower())
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def fit_pose(root, file, neutral):
    """Resize a gesture draft to the neutral canvas when only the scale differs."""
    with Image.open(neutral) as n:
        size = n.size
    with Image.open(file) as im:
        if im.size == size:
            return file
        if abs(im.width / im.height - size[0] / size[1]) > .03:
            raise ValueError(f'Gesture canvas {im.size} does not match neutral {size}; ask for the same framing.')
        out = Path(root) / 'imports' / (Path(file).stem + f'_fit{size[0]}x{size[1]}.png')
        out.parent.mkdir(exist_ok=True)
        im.convert('RGBA').resize(size, Image.Resampling.LANCZOS).save(out)
        return out


def calibrate(root, s, log=print):
    """Studio's anatomy detection, with a face-crop retry for full-body art.

    The engine's tiled scan can see a small face several times (or not at
    all). If it fails and exactly one face is clearly found here, the same
    engine routine runs on a crop around that face and its coordinates are
    mapped back - identical measurements, cleaner input.
    """
    import importlib.util
    from ..core import ROOT, action, digest, load, save, store
    root = Path(root)
    try:
        action(root, 'calibrate', {'speaker': s['id']}, log)
        return 'engine'
    except ValueError as first:
        from . import faces
        rgb, _ = _flatten(path(root, s['asset']))
        found = [f for f in faces.detect(root, rgb, min_size=24)]
        if len(found) != 1 and not (len(found) > 1 and found[1]['box'][2] < .35 * found[0]['box'][2]):
            raise ValueError(f'{first} (Agent check found {len(found)} faces, so no crop retry.)') from None
        log('Engine scan failed; retrying anatomy on a crop around the detected face.')
        x, y, w, h = found[0]['box']
        side = int(max(w, h) * 3.2)
        cx, cy = x + w / 2, y + h / 2
        H, W = rgb.shape[:2]
        x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side * .55))
        x1, y1 = int(min(W, x0 + side)), int(min(H, y0 + side))
        crop_file = root / 'work/agent/anatomy_crop.png'
        crop_file.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgb[y0:y1, x0:x1]).save(crop_file)
        spec = importlib.util.spec_from_file_location('anatomy', ROOT / 'engine/animate.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        prof = mod.auto_profile(crop_file, root / 'models/anatomy')
        bx, by, bw, bh = prof['bust']
        if (bx <= 0 and x0 > 0) or (by <= 0 and y0 > 0) or (bx + bw >= x1 - x0 and x1 < W) or (by + bh >= y1 - y0 and y1 < H):
            raise ValueError('Face crop too tight for the bust box; supply a reviewed profile.json.')
        prof['bust'] = [bx + x0, by + y0, bw, bh]
        mx, my, mw, mh = prof['mouth_box_body']
        prof['mouth_box_body'] = [mx + x0, my + y0, mw, mh]
        prof['nose_y_body'] += y0
        prof['jaw_y_body'] += y0
        prof['animation_polygon_body'] = [[px + x0, py + y0] for px, py in prof['animation_polygon_body']]
        prof['name'] = 'automatic-face (face crop)'
        prof['source_sha256'] = digest(path(root, s['asset']))
        dest = root / 'assets' / s['id'] / 'profile.json'
        save(dest, prof)
        p = load(root)
        sp = next(x for x in p['speakers'] if x['id'] == s['id'])
        sp['profile'] = dest.relative_to(root).as_posix()
        sp['approved'] = False
        store(root, p)
        return 'face-crop'


def anatomy_overlay(root, s):
    """Neutral art with the detected bust, mouth, nose and jaw drawn for review."""
    if not s.get('asset'):
        raise ValueError('No artwork imported for this speaker yet.')
    im = Image.open(path(root, s['asset'])).convert('RGB')
    if not s.get('profile'):
        return im, None
    prof = read(path(root, s['profile']))
    d = ImageDraw.Draw(im)
    lw = max(2, round(max(im.size) / 450))
    x, y, w, h = prof['bust']
    d.rectangle([x, y, x + w, y + h], outline=(0, 140, 255), width=lw)
    x, y, w, h = prof['mouth_box_body']
    d.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=lw)
    bx, _, bw, _ = prof['bust']
    for key, color in [('nose_y_body', (0, 170, 0)), ('jaw_y_body', (200, 0, 200))]:
        if key in prof:
            d.line([bx, prof[key], bx + bw, prof[key]], fill=color, width=lw)
    bust = prof['bust']
    crop = im.crop((int(bust[0]), int(bust[1]), int(bust[0] + bust[2]), int(bust[1] + bust[3])))
    return im, crop
