"""Speaker analysis for a recording: who speaks when, what they look like, who they are.

Three independent signals are combined, each reported honestly as a hint:

* **Voice clusters** - each transcript segment gets a voice fingerprint
  (MFCC statistics, numpy only) and segments are clustered with spherical
  k-means. Clusters are anonymous (``S1``, ``S2`` ...) and ordered by talk time.
  Over-clustering and then merging clusters after looking at them is more
  reliable than guessing the exact speaker count.
* **Visual samples** - for each cluster, frames from its longest confident
  segments, with the face whose mouth moves most marked as the likely talker.
* **Name hints** - self-introductions ("my name is ...") and hand-overs
  ("thank you, ...") found in the transcript, attributed to nearby clusters.

Results live in ``work/agent/speaker_analysis.json`` so an agent can inspect,
merge, relabel and link clusters to project speakers across calls.
"""
import math
import re
from pathlib import Path

import numpy as np

from ..core import path, read, save

ANALYSIS = 'work/agent/speaker_analysis.json'
RATE = 16000


# ---------------------------------------------------------------- voice features
def _mel_bank(n_fft, rate, n_mels=40, lo=60, hi=7600):
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    inv = lambda m: 700 * (10 ** (m / 2595) - 1)
    pts = inv(np.linspace(mel(lo), mel(hi), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / rate).astype(int)
    bank = np.zeros((n_mels, n_fft // 2 + 1), np.float32)
    for i in range(n_mels):
        a, b, c = bins[i], bins[i + 1], bins[i + 2]
        if b > a:
            bank[i, a:b] = (np.arange(a, b) - a) / (b - a)
        if c > b:
            bank[i, b:c] = (c - np.arange(b, c)) / (c - b)
    return bank


def mfcc(samples, rate=RATE, n=20, win=400, hop=160, n_fft=512):
    """(frames x n) MFCCs (c0 = log energy) at 100 frames/s, computed in blocks."""
    bank = _mel_bank(n_fft, rate)
    k = np.arange(n)[:, None]
    m = np.arange(bank.shape[0])[None, :]
    dct = np.cos(np.pi * k * (2 * m + 1) / (2 * bank.shape[0])).astype(np.float32)
    window = np.hamming(win).astype(np.float32)
    total = max(0, (len(samples) - win) // hop + 1)
    out = np.empty((total, n), np.float32)
    block = 60000
    for start in range(0, total, block):
        idx = np.arange(start, min(total, start + block))[:, None] * hop + np.arange(win)[None, :]
        frames = samples[idx] * window
        power = np.abs(np.fft.rfft(frames, n_fft)) ** 2
        out[start:start + len(idx)] = np.log(power @ bank.T + 1e-8) @ dct.T
    return out


def embed(features, segments, fps=100):
    """Per-segment voice fingerprint and a validity flag (enough voiced frames)."""
    body = features[:, 1:]
    body = (body - body.mean(0)) / (body.std(0) + 1e-6)  # recording-level CMVN
    delta = np.zeros_like(body)
    delta[1:-1] = (body[2:] - body[:-2]) / 2
    vectors, valid = [], []
    for s in segments:
        a, b = int(s['start'] * fps), int(s['end'] * fps)
        energy = features[a:b, 0]
        if len(energy) < 20:
            vectors.append(np.zeros(body.shape[1] * 3, np.float32))
            valid.append(False)
            continue
        voiced = energy > np.percentile(energy, 35)  # keep the louder (speech) frames
        x, d = body[a:b][voiced], delta[a:b][voiced]
        vectors.append(np.concatenate([x.mean(0), x.std(0), np.abs(d).mean(0)]))
        valid.append(len(x) >= 40)
    X = np.array(vectors, np.float32)
    ok = np.array(valid)
    if ok.any():
        mu, sd = X[ok].mean(0), X[ok].std(0) + 1e-6
        X = (X - mu) / sd
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    return X, ok


# ------------------------------------------------------------------- clustering
def kmeans(X, k, weights=None, seed=0, restarts=6, iters=60):
    """Spherical k-means with k-means++ seeding. Returns (labels, centroids)."""
    rng = np.random.default_rng(seed)
    w = np.ones(len(X)) if weights is None else np.asarray(weights, float)
    best = None
    for _ in range(restarts):
        C = [X[rng.choice(len(X), p=w / w.sum())]]
        for _ in range(1, k):
            d = 1 - np.max(X @ np.array(C).T, 1)
            p = np.clip(d, 0, None) ** 2 * w
            C.append(X[rng.choice(len(X), p=p / p.sum())] if p.sum() > 0 else X[rng.integers(len(X))])
        C = np.array(C)
        for _ in range(iters):
            labels = np.argmax(X @ C.T, 1)
            new = np.array([(X[labels == j] * w[labels == j, None]).sum(0) if np.any(labels == j) else C[j] for j in range(k)])
            new /= np.linalg.norm(new, axis=1, keepdims=True) + 1e-9
            if np.allclose(new, C, atol=1e-5):
                break
            C = new
        score = float((np.max(X @ C.T, 1) * w).sum())
        if best is None or score > best[0]:
            best = (score, labels, C)
    return best[1], best[2]


def silhouette(X, labels, limit=1500, seed=0):
    """Mean cosine silhouette on a sample (numpy only)."""
    if len(set(labels.tolist())) < 2:
        return -1.0
    idx = np.random.default_rng(seed).choice(len(X), min(limit, len(X)), replace=False)
    Xs, ls = X[idx], labels[idx]
    D = 1 - Xs @ Xs.T
    scores = []
    for i in range(len(Xs)):
        same = ls == ls[i]
        if same.sum() < 2:
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, ls == j].mean() for j in set(ls.tolist()) if j != ls[i])
        scores.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(scores)) if scores else -1.0


# ------------------------------------------------------------------- name hints
NOT_NAMES = {'going', 'just', 'not', 'so', 'very', 'glad', 'happy', 'sure', 'here', 'sorry', 'really', 'also',
             'now', 'still', 'the', 'a', 'an', 'in', 'on', 'at', 'with', 'from', 'all', 'one', 'actually', 'trying',
             'thinking', 'looking', 'gonna', 'kind', 'sort', 'curious', 'interested', 'excited', 'delighted',
             'honored', 'pleased', 'thrilled', 'everyone', 'everybody', 'you', 'all', 'okay', 'ok', 'good', 'great',
             'thank', 'thanks', 'yes', 'no', 'well', 'and', 'but', 'professor', 'doctor', 'dr', 'mr', 'ms', 'mrs'}
_NAME = r"((?:[A-Z][a-z'\-]+|[A-Z]\.)(?:\s+(?:[A-Z][a-z'\-]+|[A-Z]\.)){0,2})"
# Trigger phrases ignore case; the captured name must still be Capitalised.
_TITLE = r"(?:(?:Dr|Professor|Prof)\.?\s+)?"
SELF = re.compile(r"\b(?i:my name is|i'm|i am|this is)\s+" + _TITLE + _NAME)
ADDRESS = re.compile(r"\b(?i:thank you|thanks|welcome|over to you|hi|hello|go ahead|please)[,]?\s+" + _TITLE + _NAME)
TURN = re.compile(r"\b(?i:turn (?:it )?over to|hand (?:it )?over to|introduce|invite|next (?:we have|up is|is)|let me ask)\s+" + _TITLE + _NAME)


def _clean_name(raw):
    words = raw.split()
    while words and words[-1].lower().strip('.') in NOT_NAMES:
        words.pop()
    if not words or words[0].lower().strip('.') in NOT_NAMES:
        return None
    return ' '.join(words)


def name_hints(segments, labels):
    """[{name, kind, time, cluster, quote}] from introductions and hand-overs."""
    hints = []
    for i, s in enumerate(segments):
        text = s['text']
        for m in SELF.finditer(text):
            name = _clean_name(m.group(1))
            if name:
                hints.append({'name': name, 'kind': 'self-introduction (speaker of this line)', 'time': round(s['start'], 2),
                              'cluster': labels[i], 'quote': text.strip()[:200]})
        for rx, kind in [(ADDRESS, 'addressed (likely speaks next)'), (TURN, 'handed the floor (likely speaks next)')]:
            for m in rx.finditer(text):
                name = _clean_name(m.group(1))
                if not name:
                    continue
                nxt = next((labels[j] for j in range(i + 1, min(len(segments), i + 6)) if labels[j] not in (None, labels[i])), None)
                hints.append({'name': name, 'kind': kind, 'time': round(s['start'], 2), 'cluster': nxt,
                              'said_by': labels[i], 'quote': text.strip()[:200]})
    return hints


# --------------------------------------------------------------------- analysis
def _segments(root, p):
    if not p.get('transcript'):
        raise ValueError('Transcribe or import a transcript first (transcribe / import_transcript).')
    t = read(path(root, p['transcript']))
    return [{'start': float(s['start']), 'end': float(s['end']), 'text': s['text']} for s in t['segments'] if s['end'] > s['start']]


def viterbi(S, durations, gaps, ok, switch=.3):
    """Best cluster sequence: per-segment voice similarity minus a penalty per speaker change.

    Evidence is weighted by sqrt(duration) (unreliable segments count less); a
    change after a pause of over a second costs half as much, as turns usually
    begin after one.
    """
    n, k = S.shape
    w = np.sqrt(np.clip(durations, .3, 6)) * np.where(ok, 1.0, .25)
    E = S * w[:, None]
    pen = switch * np.where(gaps > 1.0, .5, 1.0)
    dp = E[0].copy()
    back = np.zeros((n, k), int)
    idx = np.arange(k)
    for i in range(1, n):
        j = int(np.argmax(dp))
        switch_score = dp[j] - pen[i]
        stay = dp >= switch_score
        back[i] = np.where(stay, idx, j)
        dp = np.where(stay, dp, switch_score) + E[i]
    out = np.zeros(n, int)
    out[-1] = int(np.argmax(dp))
    for i in range(n - 1, 0, -1):
        out[i - 1] = back[i, out[i]]
    return out


def analyze(root, p, num_speakers=None, max_speakers=8, visual=True, log=print, smoothing=.3):
    root = Path(root)
    if not p.get('media'):
        raise ValueError('Import a recording first (import_media).')
    from . import media
    segments = _segments(root, p)
    if len(segments) < 2:
        raise ValueError('Transcript has too few segments to analyse.')
    log(f'Decoding audio for {len(segments)} transcript segments...')
    samples = media.audio(path(root, p['media']['path']), RATE)
    log('Computing voice fingerprints...')
    X, ok = embed(mfcc(samples, RATE), segments)
    durations = np.array([s['end'] - s['start'] for s in segments])
    fit = ok & (durations >= 1.0)
    if fit.sum() < 4:
        fit = ok
    if fit.sum() < 2:
        raise ValueError('Too little clear speech to fingerprint voices.')
    Xf, wf = X[fit], np.sqrt(durations[fit])
    scores = {}
    if num_speakers:
        k = int(num_speakers)
        if not 1 <= k <= 12:
            raise ValueError('num_speakers must be 1-12')
    else:
        log('Choosing a cluster count...')
        for k in range(2, max(2, min(int(max_speakers), 12, int(fit.sum()) - 1)) + 1):
            labels_k, _ = kmeans(Xf, k, wf)
            scores[k] = round(silhouette(Xf, labels_k), 4)
        k = max(scores, key=scores.get) if scores else 1
    labels_fit, C = kmeans(Xf, k, wf) if k > 1 else (np.zeros(len(Xf), int), Xf.mean(0, keepdims=True))
    gaps = np.array([0.0] + [segments[i]['start'] - segments[i - 1]['end'] for i in range(1, len(segments))])
    labels = np.argmax(X @ C.T, 1)
    if k > 1 and smoothing > 0:
        # People talk in turns: decode the segment sequence with a switching
        # penalty, then re-estimate voices from the decoded turns (segmental k-means).
        for _ in range(3):
            labels = viterbi(X @ C.T, durations, gaps, ok, smoothing)
            C = np.array([X[(labels == j) & ok].mean(0) if np.any((labels == j) & ok) else C[j] for j in range(k)])
            C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-9
    sims = X @ C.T
    own = sims[np.arange(len(labels)), labels]
    other = np.where(np.eye(k, dtype=bool)[labels], -np.inf, sims).max(1) if k > 1 else np.zeros(len(labels))
    margin = np.clip(own - other, 0, None)  # 0 where turn smoothing overrode the local evidence
    talk = {j: float(durations[labels == j].sum()) for j in range(k)}
    order = sorted(range(k), key=lambda j: -talk[j])
    names = {j: f'S{n + 1}' for n, j in enumerate(order)}
    rows = [{'i': i, 'start': round(s['start'], 2), 'end': round(s['end'], 2), 'cluster': names[int(labels[i])],
             'confidence': round(float(margin[i]), 3) if ok[i] else 0.0, 'text': s['text'].strip()}
            for i, s in enumerate(segments)]
    clusters = {}
    for j in order:
        mine = [r for r in rows if r['cluster'] == names[j]]
        clusters[names[j]] = {'talk_seconds': round(talk[j], 1), 'segments': len(mine), 'speaker': None,
                              'first': mine[0]['start'] if mine else None, 'last': mine[-1]['end'] if mine else None}
    analysis = {'version': 1, 'media': p['media']['path'], 'transcript': p['transcript'], 'k': k,
                'silhouette_by_k': scores, 'segments': rows, 'clusters': clusters,
                'name_hints': name_hints(segments, [r['cluster'] for r in rows]), 'visual': {}}
    carried = carry_links(root, analysis, {s['id'] for s in p['speakers']})
    if carried:
        log('Kept speaker links: ' + ', '.join(f'{c}->{s}' for c, s in carried.items()))
    if visual and p['media'].get('video'):
        log('Sampling frames for each cluster...')
        analysis['visual'] = visual_samples(root, p, analysis, log=log)
    save(root / ANALYSIS, analysis)
    return analysis


def carry_links(root, new, roster, share=.6):
    """Re-link new clusters that mostly cover the talk time of a previously linked cluster."""
    f = Path(root) / ANALYSIS
    if not f.is_file():
        return {}
    try:
        old = read(f)
        if old.get('media') != new['media']:
            return {}
        owner = {}
        for r in old['segments']:
            sid = old['clusters'].get(r['cluster'], {}).get('speaker')
            if sid in roster:
                owner[(r['start'], r['end'])] = sid
    except (ValueError, KeyError, OSError):
        return {}
    carried = {}
    for name in new['clusters']:
        talk = {}
        total = 0.0
        for r in new['segments']:
            if r['cluster'] != name:
                continue
            d = r['end'] - r['start']
            total += d
            sid = owner.get((r['start'], r['end']))
            if sid:
                talk[sid] = talk.get(sid, 0) + d
        if talk and total:
            sid, t = max(talk.items(), key=lambda x: x[1])
            if t / total >= share and sid not in carried.values():
                new['clusters'][name]['speaker'] = sid
                carried[name] = sid
    return carried


def talker(root, burst, threshold=.006):
    """(faces in the middle frame, face whose mouth moves most across the burst or None)."""
    from . import faces
    ref = burst[len(burst) // 2]
    found = faces.detect(root, ref)
    if not found:
        return found, None
    if found[0].get('mouth_open') is None:  # Haar-only mode: no mouth measure
        return found, found[0] if len(found) == 1 else None
    for f in found:
        track = []
        for fr in burst:
            sub = faces.detect(root, _crop(fr, f['box'], 1.8))
            if sub and sub[0]['mouth_open'] is not None:
                track.append(sub[0]['mouth_open'])
        f['mouth_motion'] = round(float(np.std(track)), 4) if len(track) >= 3 else 0.0
    best = max(found, key=lambda f: f['mouth_motion'])
    # Below threshold nobody is visibly talking (voice-over, off-camera, tiny faces).
    return found, best if best['mouth_motion'] >= threshold else None


def positions(samples, width):
    """Group a cluster's talker boxes by place on screen: [(centre_x, centre_y, count)]."""
    groups = []
    for v in samples:
        b = v.get('talker_box')
        if not b:
            continue
        c = (b[0] + b[2] / 2, b[1] + b[3] / 2)
        reach = max(2.5 * b[2], .06 * width)
        for g in groups:
            if np.hypot(c[0] - g[0], c[1] - g[1]) <= reach:
                g[2] += 1
                break
        else:
            groups.append([c[0], c[1], 1])
    return sorted((tuple(g) for g in groups), key=lambda g: -g[2])


def visual_samples(root, p, analysis, per_cluster=8, log=print, only=None):
    """Per cluster: sample frames + the face that moves its mouth most while talking."""
    from . import faces, media
    from PIL import Image
    src = path(root, p['media']['path'])
    info = media.video_info(src)
    W, H = info['width'], info['height']
    analysis['frame_width'], analysis['frame_height'] = W, H
    out_dir = Path(root) / 'work/agent/speakers'
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in analysis['clusters']:
        if only and name not in only:
            continue
        rows = [r for r in analysis['segments'] if r['cluster'] == name and r['end'] - r['start'] >= 1.2]
        rows.sort(key=lambda r: -(r['end'] - r['start']) * (0.5 + r['confidence']))
        # One sample from each of the longest separate turns first: a second
        # person hiding in this cluster usually owns a whole turn of their own.
        picked = []
        mine = sorted((t for t in turns(analysis) if t['cluster'] == name and t['end'] - t['start'] >= 4),
                      key=lambda t: -(t['end'] - t['start']))
        for t in mine:
            inside = [r for r in rows if r['start'] >= t['start'] and r['end'] <= t['end']]
            if inside and all(abs(inside[0]['start'] - q['start']) > 20 for q in picked):
                picked.append(inside[0])
            if len(picked) >= per_cluster:
                break
        for r in rows:  # then spread the rest over the recording
            if len(picked) >= per_cluster:
                break
            if all(abs(r['start'] - q['start']) > 30 for q in picked):
                picked.append(r)
        samples = []
        for r in picked:
            mid = (r['start'] + r['end']) / 2
            t0 = max(r['start'], mid - .8)
            try:
                burst = media.frame_burst(src, t0, 1.6, 5, W, H)
            except Exception as e:  # unreadable spot: skip, keep going
                log(f'Frame read failed at {t0:.1f}s: {e}')
                continue
            if not len(burst):
                continue
            found, who = talker(root, burst)
            file = out_dir / f'{name}_{int(mid * 10):07d}.jpg'
            Image.fromarray(burst[len(burst) // 2]).save(file, quality=88)
            samples.append({'time': round(mid, 2), 'frame': file.relative_to(root).as_posix(), 'faces': len(found),
                            'talker_box': who['box'] if who else None,
                            'talker_quality': faces.quality(who, W, H) if who else None,
                            'quote': r['text'][:140]})
        result[name] = samples
        log(f'{name}: {len(samples)} sample frames')
    return result


def _crop(rgb, box, scale):
    x, y, w, h = box
    H, W = rgb.shape[:2]
    cx, cy, side = x + w / 2, y + h / 2, max(w, h) * scale
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    return np.ascontiguousarray(rgb[y0:int(min(H, cy + side / 2)), x0:int(min(W, cx + side / 2))])


# ----------------------------------------------------------------- persistence
def load_analysis(root):
    f = Path(root) / ANALYSIS
    if not f.is_file():
        raise ValueError('No speaker analysis yet; run analyze_speakers first.')
    return read(f)


def store_analysis(root, a):
    _recount(a)
    save(Path(root) / ANALYSIS, a)


def _recount(a):
    for name, c in list(a['clusters'].items()):
        mine = [r for r in a['segments'] if r['cluster'] == name]
        if not mine:
            del a['clusters'][name]
            a['visual'].pop(name, None)
            continue
        c.update(talk_seconds=round(sum(r['end'] - r['start'] for r in mine), 1), segments=len(mine),
                 first=mine[0]['start'], last=mine[-1]['end'])


def merge(root, clusters, into):
    a = load_analysis(root)
    for c in clusters + [into]:
        if c not in a['clusters']:
            raise ValueError(f'Unknown cluster {c}; known: {", ".join(a["clusters"])}')
    for r in a['segments']:
        if r['cluster'] in clusters:
            r['cluster'] = into
    for h in a['name_hints']:
        for key in ['cluster', 'said_by']:
            if h.get(key) in clusters:
                h[key] = into
    for c in clusters:
        if c != into:
            a['visual'].setdefault(into, []).extend(a['visual'].pop(c, []))
    store_analysis(root, a)
    return a


def relabel(root, start, end, cluster):
    """Assign every segment overlapping [start, end] mostly to cluster (new names allowed)."""
    a = load_analysis(root)
    if not re.fullmatch('[A-Za-z0-9_-]{1,30}', cluster):
        raise ValueError('Cluster names: 1-30 letters, digits, _ or -')
    a['clusters'].setdefault(cluster, {'talk_seconds': 0, 'segments': 0, 'speaker': None, 'first': None, 'last': None})
    changed = 0
    for r in a['segments']:
        overlap = min(end, r['end']) - max(start, r['start'])
        if overlap > .5 * (r['end'] - r['start']):
            r['cluster'] = cluster
            r['confidence'] = 1.0  # human/agent decision
            changed += 1
    for c in a['visual']:  # frames from the relabelled stretch no longer say who a cluster is
        a['visual'][c] = [v for v in a['visual'][c] if not start <= v['time'] <= end]
    store_analysis(root, a)
    return changed


def link(root, cluster, speaker_id):
    a = load_analysis(root)
    if cluster not in a['clusters']:
        raise ValueError(f'Unknown cluster {cluster}; known: {", ".join(a["clusters"])}')
    for c in a['clusters'].values():
        if c.get('speaker') == speaker_id and speaker_id is not None:
            c['speaker'] = None
    a['clusters'][cluster]['speaker'] = speaker_id
    store_analysis(root, a)
    return a


def speaker_of(a, cluster):
    return a['clusters'].get(cluster, {}).get('speaker')


def turns(a, min_gap=1.5):
    """Merge consecutive same-cluster segments into speaking turns."""
    out = []
    for r in a['segments']:
        if out and out[-1]['cluster'] == r['cluster'] and r['start'] - out[-1]['end'] <= min_gap:
            out[-1]['end'] = r['end']
            out[-1]['segments'] += 1
        else:
            out.append({'cluster': r['cluster'], 'start': r['start'], 'end': r['end'], 'segments': 1})
    return out


def assign_clips(p, a, overwrite=False, threshold=.6):
    """Set clip speakers from linked clusters. Returns a report; edits p in place."""
    report = {'assigned': [], 'mixed': [], 'unlinked': [], 'kept': []}
    roster = {s['id'] for s in p['speakers']}
    for c in p['clips']:
        talk = {}
        for r in a['segments']:
            o = min(c['end'], r['end']) - max(c['start'], r['start'])
            if o > 0:
                talk[r['cluster']] = talk.get(r['cluster'], 0) + o
        total = sum(talk.values()) or 1
        share = sorted(((v / total, k) for k, v in talk.items()), reverse=True)
        if not share:
            continue
        top_share, top = share[0]
        sid = speaker_of(a, top)
        mix = ', '.join(f'{k} {v:.0%}' for v, k in share[:3])
        if c['speaker'] and not overwrite:
            report['kept'].append(c['id'])
            continue
        if not sid or sid not in roster:
            report['unlinked'].append({'clip': c['id'], 'clusters': mix})
            continue
        if top_share < threshold:
            report['mixed'].append({'clip': c['id'], 'clusters': mix, 'suggestion': 'split_clips_by_speaker or edit boundaries'})
            continue
        if c['speaker'] != sid:
            c['speaker'] = sid
            c['reviewed'] = False
        report['assigned'].append({'clip': c['id'], 'speaker': sid, 'share': round(top_share, 2)})
    return report


def split_clips(p, a, clip_ids=None, min_seconds=4.0):
    """Split clips at speaker turns (segment boundaries). Returns {old_id: [new ids]}."""
    out_clips, changes = [], {}
    roster = {s['id'] for s in p['speakers']}
    for c in p['clips']:
        if clip_ids and c['id'] not in clip_ids:
            out_clips.append(c)
            continue
        parts = []
        for t in turns(a):
            lo, hi = max(c['start'], t['start']), min(c['end'], t['end'])
            if hi - lo <= 0:
                continue
            if parts and parts[-1]['cluster'] == t['cluster']:
                parts[-1]['end'] = hi
            else:
                parts.append({'cluster': t['cluster'], 'start': lo, 'end': hi})
        # Fold interjections shorter than min_seconds into the longer neighbour.
        while len(parts) > 1:
            short = min(range(len(parts)), key=lambda n: parts[n]['end'] - parts[n]['start'])
            if parts[short]['end'] - parts[short]['start'] >= min_seconds:
                break
            nb = [n for n in (short - 1, short + 1) if 0 <= n < len(parts)]
            into = max(nb, key=lambda n: parts[n]['end'] - parts[n]['start'])
            parts[into]['start'] = min(parts[into]['start'], parts[short]['start'])
            parts[into]['end'] = max(parts[into]['end'], parts[short]['end'])
            del parts[short]
            merged = []
            for part in parts:
                if merged and merged[-1]['cluster'] == part['cluster']:
                    merged[-1]['end'] = part['end']
                else:
                    merged.append(part)
            parts = merged
        if len(parts) <= 1:
            out_clips.append(c)
            continue
        ids = []
        for n, part in enumerate(parts):
            sid = speaker_of(a, part['cluster'])
            new = {**c, 'id': f"{c['id']}_{chr(97 + n) if n < 26 else n}", 'start': round(part['start'], 3),
                   'end': round(part['end'], 3), 'speaker': sid if sid in roster else None, 'reviewed': False,
                   'title': c['title'] + (f' ({n + 1}/{len(parts)})')}
            out_clips.append(new)
            ids.append(new['id'])
        changes[c['id']] = ids
    if changes:
        p['clips'] = out_clips
        for prod in p['productions']:
            prod['clips'] = [n for x in prod['clips'] for n in changes.get(x, [x])]
    return changes


def interleaving(a, short=8.0, minimum=3):
    """Cluster pairs that keep interrupting each other with short turns (A, B, A).

    Real conversations rarely alternate every few seconds for long; frequent
    short A-B-A patterns usually mean one person's voice was split into two
    clusters (or crosstalk). Returns [(a, b, count)] most frequent first.
    """
    t = turns(a)
    counts = {}
    for x, y, z in zip(t, t[1:], t[2:]):
        if x['cluster'] == z['cluster'] != y['cluster'] and y['end'] - y['start'] < short:
            key = tuple(sorted([x['cluster'], y['cluster']]))
            counts[key] = counts.get(key, 0) + 1
    return sorted(((k[0], k[1], n) for k, n in counts.items() if n >= minimum), key=lambda x: -x[2])


def places_warnings(a):
    """Clusters whose talking face shows up in more than one place on screen."""
    out = {}
    width, height = a.get('frame_width', 1280), a.get('frame_height', 720)
    for name, samples in a.get('visual', {}).items():
        groups = positions(samples, width)
        seen = sum(g[2] for g in groups)
        if len(groups) >= 2 and (groups[1][2] >= 2 or groups[1][2] / seen >= .3):
            where = ', '.join(f'x={g[0] / width:.2f} y={g[1] / height:.2f} ({g[2]} frames)' for g in groups[:4])
            out[name] = (f'the talking face appears at {len(groups)} different places ({where}) - possibly two people '
                         f'(or a camera cut / remote tile). inspect_cluster, then relabel_segments or re-run with num_speakers+1.')
            continue
        idle = [v['time'] for v in samples if not v.get('talker_box')]
        if groups and groups[0][2] >= 3 and len(idle) >= 2:
            when = ', '.join(_t(t) for t in sorted(idle))
            out[name] = (f'its usual talker is seen talking in {groups[0][2]} frames but nobody visibly talks at {when} - '
                         f'someone else (off-camera, small, or on a screen) may be speaking then. Look at those moments '
                         f'(view_frames), read the transcript around them for hand-overs, and relabel_segments if needed.')
    return out


def summary(a, quotes=2):
    """Compact, agent-readable digest of an analysis."""
    lines = [f"{len(a['clusters'])} voice clusters (k={a['k']}; silhouette by k: {a['silhouette_by_k'] or 'fixed'})."]
    for x, y, n in interleaving(a):
        lines.append(f'! {x} and {y} interrupt each other with short turns {n} times - possibly one person split in two '
                     f'(check frames; merge, relabel_segments, or re-run with fewer speakers).')
    for name, warn in places_warnings(a).items():
        lines.append(f'! {name}: {warn}')
    for name, c in a['clusters'].items():
        mine = sorted((r for r in a['segments'] if r['cluster'] == name), key=lambda r: -(r['end'] - r['start']))
        hints = sorted({h['name'] for h in a['name_hints'] if h.get('cluster') == name})
        lines.append(f"- {name}: {c['talk_seconds'] / 60:.1f} min over {c['segments']} segments "
                     f"({_t(c['first'])}-{_t(c['last'])}); linked speaker: {c['speaker'] or 'none'}; "
                     f"name hints: {', '.join(hints) or 'none'}; frames: {len(a['visual'].get(name, []))}")
        for r in mine[:quotes]:
            lines.append(f"    [{_t(r['start'])}] \"{r['text'][:110]}\"")
    return '\n'.join(lines)


def _t(s):
    if s is None:
        return '?'
    s = int(s)
    return f'{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}' if s >= 3600 else f'{s // 60}:{s % 60:02d}'
