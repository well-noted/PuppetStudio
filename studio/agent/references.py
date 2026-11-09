"""Find and save reference photos of a speaker from the recording."""
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from ..core import path, read, save
from . import faces, media, speakers

CANDIDATES = 'work/agent/references'


def _ranges(root, p, speaker_id):
    """Time ranges where this speaker talks: linked voice cluster first, else assigned clips."""
    ranges, prior = [], []
    try:
        a = speakers.load_analysis(root)
        linked = [c for c, v in a['clusters'].items() if v.get('speaker') == speaker_id]
        for c in linked:
            ranges += [(r['start'], r['end'], r['confidence']) for r in a['segments'] if r['cluster'] == c and r['end'] - r['start'] >= 1]
            prior += [v['talker_box'] for v in a['visual'].get(c, []) if v.get('talker_box')]
    except ValueError:
        pass
    if not ranges:
        ranges = [(c['start'], c['end'], .5) for c in p['clips'] if c['speaker'] == speaker_id]
    if not ranges:
        raise ValueError('No time ranges for this speaker: link a voice cluster (add_speaker/update_speaker cluster=...) '
                         'or assign clips first, or use set_reference with seconds and box.')
    return ranges, prior


def _times(ranges, n):
    """n sample times spread across the recording, favouring long confident ranges."""
    ranges = sorted(ranges, key=lambda r: -(r[1] - r[0]) * (.5 + r[2]))
    picked = []
    for lo, hi, _ in ranges:
        for t in ([(lo + hi) / 2] if hi - lo < 8 else [lo + (hi - lo) * .3, lo + (hi - lo) * .7]):
            if all(abs(t - q) > 12 for q in picked):
                picked.append(t)
        if len(picked) >= n:
            break
    return sorted(picked[:n])


def find(root, p, s, count=8, samples=24, log=print):
    root = Path(root)
    if not p.get('media') or not p['media'].get('video'):
        raise ValueError('The recording has no video; import a reference photo with set_reference path=... instead.')
    src = path(root, p['media']['path'])
    info = media.video_info(src)
    W, H = info['width'], info['height']
    ranges, prior = _ranges(root, p, s['id'])
    centre = np.median([[b[0] + b[2] / 2, b[1] + b[3] / 2] for b in prior], 0) if prior else None
    # A face counts only near where this voice was seen talking (static cameras);
    # otherwise a remote tile or a neighbour on screen gets picked.
    reach = max(2.0 * float(np.median([b[2] for b in prior])), .04 * W) if prior else None
    spread = float(np.median([np.hypot(b[0] + b[2] / 2 - centre[0], b[1] + b[3] / 2 - centre[1]) for b in prior])) if prior else 0
    if prior and spread > reach:
        centre = None  # talker seen in many places (moving camera, cuts): position is no guide
    found = []
    times = _times(ranges, samples)
    log(f'Scanning {len(times)} moments for clear views of {s["name"]}...')
    for t in times:
        if centre is None:
            # No known talking position: the right face is the one whose mouth
            # moves while this voice talks (not a silent face on a screen).
            try:
                burst = media.frame_burst(src, max(0, t - .8), 1.6, 5, W, H)
            except Exception:
                continue
            if not len(burst):
                continue
            fs, who = speakers.talker(root, burst)
            if who is None:
                continue
            rgb = burst[len(burst) // 2]
            found.append({'time': round(t, 2), 'face': who, 'how': 'mouth moving while this voice talks',
                          'score': faces.quality(who, W, H), 'faces_in_frame': len(fs), 'rgb': rgb})
            continue
        try:
            rgb = np.asarray(media.frame(src, t))
        except Exception:
            continue
        fs = faces.detect(root, rgb)
        if not fs:
            continue
        dist = lambda f: np.hypot(f['box'][0] + f['box'][2] / 2 - centre[0], f['box'][1] + f['box'][3] / 2 - centre[1])
        near = [f for f in fs if dist(f) <= reach]
        if not near:
            continue
        face, how = min(near, key=dist), 'at the talking position'
        found.append({'time': round(t, 2), 'face': face, 'how': how, 'score': faces.quality(face, W, H), 'faces_in_frame': len(fs), 'rgb': rgb})
    if not found:
        raise ValueError('No visibly talking face found in this speaker\'s segments (off-camera, too small, or turned away). '
                         'Look with view_frames (box=..., grid=true), then set_reference with seconds and box, or use a photo path.')
    found.sort(key=lambda x: -x['score'])
    folder = root / CANDIDATES / s['id']
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    out = []
    for n, c in enumerate(found[:count], 1):
        box = faces.portrait_box(c['face']['box'], W, H)
        crop = Image.fromarray(c['rgb']).crop(box)
        file = folder / f'cand_{n}.png'
        crop.save(file)
        out.append({'candidate': n, 'time': c['time'], 'score': c['score'], 'face_px': round(c['face']['box'][3]),
                    'crop_box': box, 'chosen_by': c['how'], 'faces_in_frame': c['faces_in_frame'],
                    'file': file.relative_to(root).as_posix()})
    save(folder / 'candidates.json', out)
    return out


def candidate_sheet(root, s, items):
    ims, caps = [], []
    for c in items:
        ims.append(Image.open(Path(root) / c['file']))
        caps.append(f'#{c["candidate"]} t={c["time"]:.0f}s face {c["face_px"]}px q={c["score"]:.2f}')
    return media.sheet(ims, caps, columns=4, cell_width=260)


def _upscale(im, minimum=640):
    if im.height < minimum:
        k = minimum / im.height
        im = im.resize((round(im.width * k), minimum), Image.Resampling.LANCZOS)
    return im


def set_reference(root, p, s, candidate=None, seconds=None, box=None, file=None, extra=False):
    """Save a reference crop. Returns (project-relative path, image)."""
    from ..core import action
    root = Path(root)
    if candidate is not None:
        items = read(root / CANDIDATES / s['id'] / 'candidates.json')
        item = next((c for c in items if c['candidate'] == int(candidate)), None)
        if not item:
            raise ValueError(f'No candidate #{candidate}; run find_reference_frames again.')
        im = Image.open(root / item['file']).convert('RGB')
    elif seconds is not None:
        if not p.get('media') or not p['media'].get('video'):
            raise ValueError('Recording has no video.')
        im = media.frame(path(root, p['media']['path']), float(seconds))
        if box:
            if len(box) != 4:
                raise ValueError('box is [x0, y0, x1, y1] as fractions (0-1) of the frame')
            x0, y0, x1, y1 = box
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError('box values are fractions 0-1 with x0<x1 and y0<y1')
            im = im.crop((round(x0 * im.width), round(y0 * im.height), round(x1 * im.width), round(y1 * im.height)))
    elif file:
        from .art import stage
        im = Image.open(stage(root, file)).convert('RGB')
    else:
        raise ValueError('Give candidate, seconds (+ optional box), or path.')
    im = _upscale(im)
    folder = root / 'assets' / s['id']
    folder.mkdir(parents=True, exist_ok=True)
    if extra:
        refs = folder / 'references'
        refs.mkdir(exist_ok=True)
        n = len(list(refs.glob('ref_*.png'))) + 1
        dest = refs / f'ref_{n}.png'
        im.save(dest)
        return dest.relative_to(root).as_posix(), im
    tmp = root / 'imports' / f'reference_{s["id"]}.png'
    tmp.parent.mkdir(exist_ok=True)
    im.save(tmp)
    action(root, 'import-asset', {'speaker': s['id'], 'kind': 'reference', 'path': str(tmp)}, lambda *_: None)
    return f'assets/{s["id"]}/reference.png', im
