"""Agent tool registry: one definition serves MCP and the ``studio.py agent`` CLI.

Each tool takes a JSON object and returns ``{'text', 'data', 'images'}`` where
images are ``(PIL.Image, caption)`` pairs. Tools marked ``long`` run as
background jobs; they wait up to ``wait_seconds`` and otherwise hand back a
job ID for ``wait_for_job``.
"""
import copy
import json
import re
from pathlib import Path

from PIL import Image

from ..core import ROOT, action, load, new, path, read, store

TOOLS = {}


class Context:
    def __init__(self, root, in_job=False):
        self.root = Path(root).expanduser().resolve()
        self.in_job = in_job

    def project(self):
        if not (self.root / 'project.json').is_file():
            raise ValueError(f'No project at {self.root}; call open_project with create=true.')
        return load(self.root)

    def speaker(self, p, sid):
        s = next((x for x in p['speakers'] if x['id'] == sid), None)
        if s is None and isinstance(sid, str):  # accept the display name too
            named = [x for x in p['speakers'] if x['name'].strip().lower() == sid.strip().lower()]
            s = named[0] if len(named) == 1 else None
        if s is None:
            known = ', '.join(f'{x["id"]} ({x["name"]})' for x in p['speakers']) or 'none yet'
            raise ValueError(f'Unknown speaker {sid!r}; known: {known}')
        return s


def tool(name, description, props=None, required=(), long=False):
    def wrap(fn):
        schema = {'type': 'object', 'properties': dict(props or {}), 'required': list(required), 'additionalProperties': False}
        if long:
            schema['properties']['wait_seconds'] = {'type': 'number', 'description': 'Seconds to wait for completion before returning a job ID (0-110, default 45).'}
        TOOLS[name] = {'name': name, 'description': description.strip(), 'schema': schema, 'fn': fn, 'long': long}
        return fn
    return wrap


def result(text='', data=None, images=None):
    return {'text': text, 'data': data, 'images': images or []}


def call(ctx, name, args, log=print, background=True):
    if name not in TOOLS:
        raise ValueError(f'Unknown tool {name}')
    t = TOOLS[name]
    args = dict(args or {})
    wait = args.pop('wait_seconds', 45)
    allowed = set(t['schema']['properties'])
    extra = set(args) - allowed
    if extra:
        raise ValueError(f'{name}: unknown argument(s) {", ".join(sorted(extra))}; allowed: {", ".join(sorted(allowed)) or "none"}')
    missing = [r for r in t['schema']['required'] if r not in args]
    if missing:
        raise ValueError(f'{name}: missing required argument(s) {", ".join(missing)}')
    if t['long'] and background and not ctx.in_job:
        from . import jobs
        job = jobs.start(ctx.root, name, args)
        log(f'Started job {job["id"]} for {name}')
        return _job_reply(ctx, jobs.wait(ctx.root, job['id'], min(110, max(0, float(wait)))))
    lines = []
    def collect(x):
        lines.append(str(x))
        log(x)
    out = t['fn'](ctx, args, collect)
    if lines and not ctx.in_job:
        out['text'] = (out.get('text') or '') + ('\n\nLog:\n' + '\n'.join(lines[-25:]) if out.get('text') else '\n'.join(lines[-25:]))
    return out


def _job_reply(ctx, st):
    if st['status'] == 'completed':
        r = st.get('result') or {}
        images = []
        for im in r.get('images', []):
            with Image.open(ctx.root / im['file']) as x:
                images.append((x.copy(), im['caption']))
        return result(f'Job {st["id"]} ({st["tool"]}) completed in {st["elapsed_seconds"]}s.\n\n' + (r.get('text') or ''), r.get('data'), images)
    if st['status'] == 'running':
        return result(f'Job {st["id"]} ({st["tool"]}) is still running after {st["elapsed_seconds"]}s. '
                      f'Call wait_for_job with job="{st["id"]}" to keep waiting.\nRecent log:\n' + '\n'.join(st['log_tail'][-12:]),
                      {'job': st['id'], 'status': 'running'})
    return result(f'Job {st["id"]} ({st["tool"]}) {st["status"]}: {st.get("error", "")}\nRecent log:\n' + '\n'.join(st['log_tail'][-20:]),
                  {'job': st['id'], 'status': st['status'], 'error': st.get('error')})


def secs(v):
    """Seconds from a number or a 'm:ss' / 'h:mm:ss' string."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str) and re.fullmatch(r'\s*\d+(?::\d{1,2}){0,2}(?:\.\d+)?\s*', v):
        total = 0.0
        for part in v.strip().split(':'):
            total = total * 60 + float(part)
        return total
    raise ValueError(f'Time {v!r}: use seconds (e.g. 754.5) or m:ss / h:mm:ss (e.g. "12:34")')


TIME = {'type': ['number', 'string'], 'description': 'Seconds, or "m:ss" / "h:mm:ss".'}


def _t(s):
    s = int(round(s))
    return f'{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}' if s >= 3600 else f'{s // 60}:{s % 60:02d}'


def _project_file(ctx, value, must_exist=True):
    f = Path(str(value).strip().strip('"'))
    f = f if f.is_absolute() else ctx.root / f
    f = f.resolve()
    if must_exist and not f.is_file():
        raise ValueError(f'File not found: {f}')
    return f


# ======================================================================= orient
@tool('guide', 'Read the Puppet Studio agent playbook: the end-to-end workflow, quality bar and pitfalls. Read it once at the start of a session.')
def _guide(ctx, a, log):
    return result((ROOT / 'docs/AGENTS.md').read_text(encoding='utf-8'))


@tool('open_project', 'Select (or create) the Puppet Studio project folder that every other tool acts on. Projects normally live in <studio>/projects/<name>.',
      {'path': {'type': 'string', 'description': 'Project folder; relative paths resolve against <studio>/projects.'},
       'create': {'type': 'boolean', 'description': 'Create an empty project if none exists (default false).'},
       'name': {'type': 'string', 'description': 'Display name for a new project.'}}, ['path'])
def _open(ctx, a, log):
    from ..machine_setup import inherit_tools
    root = Path(a['path']).expanduser()
    root = (root if root.is_absolute() else ROOT / 'projects' / root).resolve()
    if not (root / 'project.json').is_file():
        if not a.get('create'):
            raise ValueError(f'No project.json in {root}. Pass create=true to start a new project there.')
        root.mkdir(parents=True, exist_ok=True)
        p = inherit_tools(new())
        if a.get('name'):
            p['name'] = a['name']
        store(root, p)
    ctx.root = root
    return _status(ctx, {}, log)


@tool('project_status', 'Where the project stands: recording, transcript, speaker analysis, each speaker\'s reference/art/anatomy, clips, productions, renders, running job - plus the recommended next steps. Call it whenever you are unsure what to do next.')
def _status(ctx, a, log):
    p = ctx.project()
    root = ctx.root
    cfg = p['settings']
    lines = [f'Project: {p["name"]} ({root})']
    nxt = []
    m = p.get('media')
    if m:
        lines.append(f'Recording: {m["path"]} ({_t(m["duration"])}, {"video" if m.get("video") else "audio only"})')
    else:
        lines.append('Recording: none')
        nxt.append('import_media with the recording path.')
    if p.get('transcript'):
        t = read(path(root, p['transcript']))
        lines.append(f'Transcript: {len(t["segments"])} segments, {len(t.get("words", []))} timed words')
    elif m:
        lines.append('Transcript: none')
        nxt.append('transcribe (local Whisper, slow on CPU) or import_transcript if you have JSON/SRT.')
    analysis = None
    from . import speakers as sp
    try:
        analysis = sp.load_analysis(root)
        linked = {c: v['speaker'] for c, v in analysis['clusters'].items()}
        lines.append('Voice clusters: ' + ', '.join(f'{c}->{s or "?"} ({analysis["clusters"][c]["talk_seconds"] / 60:.1f}m)' for c, s in linked.items()))
        if any(v is None for v in linked.values()):
            nxt.append('inspect_cluster each unlinked cluster, merge_clusters duplicates, then add_speaker/update_speaker with cluster=... to link them.')
    except ValueError:
        if p.get('transcript'):
            nxt.append('analyze_speakers to find who speaks when (start without num_speakers; then check every cluster for two people).')
    lines.append(f'Speakers ({len(p["speakers"])}):')
    for s in p['speakers']:
        clips = [c for c in p['clips'] if c['speaker'] == s['id']]
        flags = {'reference': bool(s.get('reference')), 'art': bool(s.get('asset')), 'anatomy': bool(s.get('profile')),
                 'approved': bool(s.get('approved')), 'closed_mouth': bool(s.get('closed')), 'breathing_mask': bool(s.get('breath')),
                 'gestures': len(s.get('poses', []))}
        lines.append(f'  - {s["id"]}: {s["name"]} | {s.get("title", "")} | clips {len(clips)} | ' + ', '.join(f'{k}={v}' for k, v in flags.items()))
        if not s.get('reference') and not s.get('asset'):
            nxt.append(f'{s["id"]}: find_reference_frames then set_reference.')
        elif not s.get('asset'):
            nxt.append(f'{s["id"]}: art_brief (browser) or generate_art (API), check_artwork, then import_artwork.')
        elif not s.get('profile'):
            nxt.append(f'{s["id"]}: import_artwork ran without anatomy - run review_anatomy / calibrate via import_artwork again.')
        elif not s.get('approved'):
            nxt.append(f'{s["id"]}: review_anatomy, then approve_anatomy if the boxes sit on the face and mouth.')
        elif not s.get('closed'):
            nxt.append(f'{s["id"]}: optional polish - generate_asset_draft kind=closed (and breath), review, import_asset_draft.')
    clips = p['clips']
    if clips:
        un = [c for c in clips if not c['speaker']]
        rv = [c for c in clips if c['reviewed']]
        lines.append(f'Clips: {len(clips)} ({len(un)} without speaker, {len(rv)} reviewed)')
        if un and analysis:
            nxt.append('assign_clip_speakers (then split_clips_by_speaker for mixed clips).')
        if len(rv) < len(clips):
            nxt.append('Read each clip (list_clips / read_transcript), fix boundaries/titles/intros with update_clips, and mark reviewed=true.')
    elif p.get('transcript'):
        nxt.append('propose_clips (or update_clips add=[...] with your own selections).')
    lines.append(f'Productions ({len(p["productions"])}): ' + (', '.join(f'{x["id"]} [{len(x["clips"])} clips, {len(x["scene"]["actors"])} figures]' for x in p['productions']) or 'none'))
    if not p['productions'] and any(s.get('approved') for s in p['speakers']):
        nxt.append('create_production per speaker (or shared), then snapshot to check the layout.')
    backend = cfg['backend']
    ready = backend == 'still' or (cfg.get('sadtalker_repo') and cfg.get('sadtalker_python'))
    lines.append(f'Render backend: {backend}' + ('' if ready else ' (NOT configured - run diagnose/discover_tools, or configure backend=still for composition-only tests)'))
    from . import jobs
    busy = jobs.running(root)
    if busy:
        lines.append(f'Running job: {busy} (wait_for_job)')
    if p['productions'] and ready:
        nxt.append('render preview=true for one production, view the result with view_frames, then render the rest.')
    lines.append('')
    lines.append('Next steps:' if nxt else 'Next steps: none outstanding.')
    lines += [f'  {i + 1}. {x}' for i, x in enumerate(dict.fromkeys(nxt))]
    return result('\n'.join(lines), {'next_steps': list(dict.fromkeys(nxt))})


SETTINGS = {'transcription': ['local', 'api', 'huggingface'], 'whisper_model': str, 'language': str, 'planning': ['rules', 'api'],
            'target_seconds': float, 'max_seconds': float, 'backend': ['sadtalker', 'still'], 'style': str,
            'image_model': str, 'chat_model': str, 'api_base': str, 'key_env': str, 'gemini_model': str,
            'gemini_key_env': str, 'sadtalker_repo': str, 'sadtalker_python': str, 'expression_scale': float,
            'chunk_seconds': float, 'hf_model': str, 'hf_key_env': str, 'transcription_model': str}


@tool('configure', 'Change project settings: transcription (local|api|huggingface), whisper_model (tiny..large-v3), language, planning (rules|api), target_seconds/max_seconds for proposed clips, backend (sadtalker|still), style (art style text), gemini_model, gemini_key_env, image_model, api_base, key_env (env var NAMES only - never secrets). Without arguments it shows the current settings.',
      {'settings': {'type': 'object', 'description': 'Key/value pairs to change.'}})
def _configure(ctx, a, log):
    p = ctx.project()
    for k, v in (a.get('settings') or {}).items():
        rule = SETTINGS.get(k)
        if rule is None:
            raise ValueError(f'Setting {k} is not adjustable here; allowed: {", ".join(SETTINGS)}')
        if isinstance(rule, list) and v not in rule:
            raise ValueError(f'{k} must be one of {rule}')
        if rule is float:
            v = float(v)
        if k.endswith('key_env') and not re.fullmatch('[A-Z_][A-Z0-9_]{0,79}', str(v)):
            raise ValueError('Key settings take an environment variable NAME, e.g. GEMINI_API_KEY - never the key itself.')
        p['settings'][k] = v
    store(ctx.root, p)
    shown = {k: p['settings'].get(k) for k in SETTINGS}
    return result(json.dumps(shown, indent=1), shown)


# ===================================================================== recording
@tool('import_media', 'Import the source recording (video or audio) by local path. WARNING: replaces the transcript and all clips of this project.',
      {'path': {'type': 'string'}}, ['path'])
def _import_media(ctx, a, log):
    action(ctx.root, 'import-media', {'path': a['path']}, log)
    return _status(ctx, {}, log)


@tool('transcribe', 'Transcribe the recording with the configured provider (local Whisper by default; CPU takes roughly 0.3-1x real time for "small"). Reuses a cached raw transcript when the media and settings are unchanged.', long=True)
def _transcribe(ctx, a, log):
    action(ctx.root, 'transcribe', {}, log)
    t = read(path(ctx.root, ctx.project()['transcript']))
    return result(f'Transcript ready: {len(t["segments"])} segments.')


@tool('import_transcript', 'Import an existing timed transcript (Studio/Whisper JSON with segments, or .srt).',
      {'path': {'type': 'string'}}, ['path'])
def _import_transcript(ctx, a, log):
    action(ctx.root, 'import-transcript', {'path': str(_project_file(ctx, a['path']))}, log)
    t = read(path(ctx.root, ctx.project()['transcript']))
    return result(f'Transcript imported: {len(t["segments"])} segments.')


@tool('read_transcript', 'Read transcript segments with timestamps (and voice-cluster labels once analyze_speakers has run). Use start/end (seconds) to page through long recordings.',
      {'start': TIME, 'end': TIME, 'max_segments': {'type': 'integer', 'description': 'Default 200.'},
       'contains': {'type': 'string', 'description': 'Only segments containing this text (case-insensitive).'}})
def _read_transcript(ctx, a, log):
    p = ctx.project()
    if not p.get('transcript'):
        raise ValueError('No transcript yet.')
    segs = read(path(ctx.root, p['transcript']))['segments']
    labels = {}
    from . import speakers as sp
    try:
        an = sp.load_analysis(ctx.root)
        labels = {(r['start'], r['end']): r['cluster'] for r in an['segments']}
        names = {c: v['speaker'] for c, v in an['clusters'].items()}
    except ValueError:
        names = {}
    lo, hi = secs(a.get('start', 0)), secs(a['end']) if 'end' in a else float('inf')
    needle = (a.get('contains') or '').lower()
    rows = [s for s in segs if s['end'] > lo and s['start'] < hi and needle in s['text'].lower()]
    limit = int(a.get('max_segments', 200))
    out = []
    for s in rows[:limit]:
        c = labels.get((round(s['start'], 2), round(s['end'], 2)))
        who = f' {c}' + (f'={names[c]}' if names.get(c) else '') if c else ''
        out.append(f'[{_t(s["start"])} {s["start"]:.1f}-{s["end"]:.1f}{who}] {s["text"].strip()}')
    more = f'\n... {len(rows) - limit} more; continue with start={rows[limit]["start"]:.1f}' if len(rows) > limit else ''
    return result('\n'.join(out) + more or 'No matching segments.')


@tool('view_frames', 'Look at video frames. Give times (seconds) from the recording - or from a render with source=<project-relative mp4>. Several times come back as one labelled contact sheet. box=[x0,y0,x1,y1] (fractions 0-1) zooms into a region, e.g. to read a name caption or see a face.',
      {'times': {'type': 'array', 'items': TIME}, 'source': {'type': 'string'},
       'box': {'type': 'array', 'items': {'type': 'number'}, 'description': '[x0,y0,x1,y1] fractions 0-1 of the full frame; the crop is enlarged for reading.'},
       'grid': {'type': 'boolean', 'description': 'Overlay a labelled 0.1 grid in full-frame fractions, for choosing box values.'},
       'width': {'type': 'integer', 'description': 'Per-frame width in the sheet (default 480; one frame or a box: 960).'}},
      ['times'])
def _view_frames(ctx, a, log):
    from . import media
    p = ctx.project()
    src = _project_file(ctx, a['source']) if a.get('source') else (path(ctx.root, p['media']['path']) if p.get('media') else None)
    if src is None:
        raise ValueError('No recording imported.')
    times = [secs(t) for t in a['times'][:16]]
    box = a.get('box')
    if box and not (len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ValueError('box is [x0, y0, x1, y1] as fractions 0-1 with x0<x1 and y0<y1')
    ims = []
    for t in times:
        im = media.frame(src, t)
        if box:
            x0, y0, x1, y1 = box
            im = im.crop((round(x0 * im.width), round(y0 * im.height), round(x1 * im.width), round(y1 * im.height)))
            target = int(a.get('width', 960))
            if im.width < target:  # enlarge small regions so captions/faces are readable
                im = im.resize((target, round(im.height * target / im.width)), Image.Resampling.LANCZOS)
        if a.get('grid'):
            im = media.grid(im, box or [0, 0, 1, 1])
        ims.append(im)
    note = f' Region {box} of the frame, enlarged.' if box else ''
    if len(ims) == 1:
        return result(f'Frame at {times[0]:.2f}s ({ims[0].width}x{ims[0].height}).{note}', images=[(ims[0], f't={times[0]:.2f}s')])
    w = int(a.get('width', 960 if box else 480))
    return result(f'{len(ims)} frames.', images=[(media.sheet(ims, [f'{t:.1f}s' for t in times], min(4, len(ims)), w), 'frames')])


@tool('view_image', 'Look at any image file (drafts, references, overlays, downloads) - absolute or project-relative path.',
      {'path': {'type': 'string'}}, ['path'])
def _view_image(ctx, a, log):
    from . import media
    f = _project_file(ctx, a['path'])
    im = media.on_white(f)
    return result(f'{f} ({im.width}x{im.height})', images=[(im, f.name)])


# ====================================================================== speakers
@tool('analyze_speakers', 'Diarize the recording: cluster transcript segments by voice (S1, S2... ordered by talk time), sample frames per cluster marking the face whose mouth moves, and collect name hints from introductions/hand-overs. Re-running replaces previous clusters and links. Start without num_speakers (automatic choice); set it only to fix a cluster that visibly holds two people (+1) or two clusters that are one voice (-1).',
      {'num_speakers': {'type': 'integer', 'description': 'Fixed cluster count (1-12). Omit to choose automatically.'},
       'max_speakers': {'type': 'integer', 'description': 'Upper bound for automatic choice (default 8).'},
       'visual': {'type': 'boolean', 'description': 'Sample video frames per cluster (default true; ~3 s per frame).'},
       'smoothing': {'type': 'number', 'description': 'Turn-taking penalty (default 0.3; 0 = label every segment independently, higher = fewer, longer turns).'}}, long=True)
def _analyze(ctx, a, log):
    from . import speakers as sp
    p = ctx.project()
    an = sp.analyze(ctx.root, p, a.get('num_speakers'), a.get('max_speakers', 8), a.get('visual', True), log, a.get('smoothing', .3))
    roster = sorted({s['id'] for s in p['speakers']} - {c['speaker'] for c in an['clusters'].values()})
    hints = [f'  {h["name"]}: {h["kind"]} at {_t(h["time"])} -> {h.get("cluster") or "?"} ("{h["quote"][:80]}")' for h in an['name_hints'][:25]]
    text = sp.summary(an) + ('\n\nName hints:\n' + '\n'.join(hints) if hints else '\n\nNo name hints found in the transcript.')
    text += '\n\nNext: inspect_cluster for each cluster (frames + quotes), merge_clusters where two clusters are one person, then add_speaker with cluster=...'
    if roster:
        text += f'\nSpeakers without a voice cluster: {", ".join(roster)}; use update_speaker cluster=... to link.'
    images = []
    if an['visual']:
        images.append((_overview(ctx, an), 'one sample frame per cluster'))
    return result(text, {'clusters': an['clusters']}, images)


def _overview(ctx, an):
    from . import media
    from PIL import ImageDraw
    ims, caps = [], []
    for c, samples in an['visual'].items():
        if not samples:
            continue
        best = max(samples, key=lambda x: x.get('talker_quality') or 0)
        im = Image.open(ctx.root / best['frame']).convert('RGB')
        if best.get('talker_box'):
            x, y, w, h = best['talker_box']
            ImageDraw.Draw(im).rectangle([x - 4, y - 4, x + w + 4, y + h + 4], outline=(255, 40, 40), width=4)
        ims.append(im)
        caps.append(f'{c} @ {_t(best["time"])}')
    return media.sheet(ims, caps, min(3, len(ims)), 420)


@tool('inspect_cluster', 'See one voice cluster: its sample frames (red box = face moving its mouth while this voice talks), longest quotes, time span and name hints. Use it to decide who the cluster is.',
      {'cluster': {'type': 'string'}, 'quotes': {'type': 'integer', 'description': 'Number of quotes (default 8).'}}, ['cluster'])
def _inspect(ctx, a, log):
    from . import media, speakers as sp
    from PIL import ImageDraw
    an = sp.load_analysis(ctx.root)
    c = a['cluster']
    if c not in an['clusters']:
        raise ValueError(f'Unknown cluster {c}; known: {", ".join(an["clusters"])}')
    info = an['clusters'][c]
    rows = sorted((r for r in an['segments'] if r['cluster'] == c), key=lambda r: -(r['end'] - r['start']))
    quotes = [f'  [{_t(r["start"])} conf {r["confidence"]:.2f}] {r["text"][:160]}' for r in rows[:int(a.get('quotes', 8))]]
    hints = [f'  {h["name"]}: {h["kind"]} ({_t(h["time"])}: "{h["quote"][:90]}")' for h in an['name_hints'] if h.get('cluster') == c]
    said = [f'  {h["name"]} ({_t(h["time"])})' for h in an['name_hints'] if h.get('said_by') == c and h.get('cluster') != c]
    turns = [t for t in sp.turns(an) if t['cluster'] == c]
    spans = ', '.join(f'{_t(t["start"])}-{_t(t["end"])}' for t in sorted(turns, key=lambda t: -(t['end'] - t['start']))[:8])
    text = (f'{c}: {info["talk_seconds"] / 60:.1f} min, {info["segments"]} segments, linked speaker: {info["speaker"] or "none"}\n'
            f'Longest turns: {spans}\nQuotes:\n' + '\n'.join(quotes) + '\nName hints for this voice:\n' + ('\n'.join(hints) or '  none')
            + ('\nNames this voice addressed (not itself):\n' + '\n'.join(said) if said else ''))
    images = []
    samples = an['visual'].get(c, [])
    p = ctx.project()
    if not samples and p.get('media') and p['media'].get('video'):
        log(f'Sampling frames for {c} (none yet, e.g. after relabel_segments)...')
        an['visual'].update(sp.visual_samples(ctx.root, p, an, log=log, only=[c]))
        sp.store_analysis(ctx.root, an)
        samples = an['visual'].get(c, [])
    warn = sp.places_warnings(an).get(c)
    if warn:
        text += f'\nWARNING: {warn}'
    if samples:
        ims, caps = [], []
        for v in samples[:8]:
            im = Image.open(ctx.root / v['frame']).convert('RGB')
            if v.get('talker_box'):
                x, y, w, h = v['talker_box']
                ImageDraw.Draw(im).rectangle([x - 4, y - 4, x + w + 4, y + h + 4], outline=(255, 40, 40), width=5)
            ims.append(im)
            caps.append(f'{_t(v["time"])}' + ('' if v.get('talker_box') else ' (no visible talker)'))
        images.append((media.sheet(ims, caps, min(3, len(ims)), 420), f'{c} sample frames'))
        text += '\nNo red box means no visible face was moving its mouth (remote audio, off-camera, or tiny faces) - zoom with view_frames box=... if needed.'
    else:
        text += '\nNo frames available (audio-only recording, or no segment of 1.2 s or longer).'
    return result(text, None, images)


@tool('merge_clusters', 'Merge voice clusters that are the same person into one (e.g. merge ["S4"] into "S2").',
      {'clusters': {'type': 'array', 'items': {'type': 'string'}}, 'into': {'type': 'string'}}, ['clusters', 'into'])
def _merge(ctx, a, log):
    from . import speakers as sp
    an = sp.merge(ctx.root, a['clusters'], a['into'])
    return result(sp.summary(an, 1))


@tool('relabel_segments', 'Reassign all transcript segments within [start, end] seconds to a cluster (existing or new name such as "S7"). Use when you can see/hear a stretch was attributed to the wrong voice.',
      {'start': TIME, 'end': TIME, 'cluster': {'type': 'string'}}, ['start', 'end', 'cluster'])
def _relabel(ctx, a, log):
    from . import speakers as sp
    n = sp.relabel(ctx.root, secs(a['start']), secs(a['end']), a['cluster'])
    return result(f'{n} segments relabelled to {a["cluster"]}. inspect_cluster {a["cluster"]} samples fresh frames for it.')


@tool('add_speaker', 'Add a person to the project roster (the name/title are shown on screen), optionally linking a voice cluster to them. Only name people the recording identifies (captions, introductions) or the user supplied; otherwise use a neutral label like "Panelist 2" and say so.',
      {'name': {'type': 'string'}, 'title': {'type': 'string', 'description': 'Role/affiliation shown under the name.'},
       'cluster': {'type': 'string', 'description': 'Voice cluster to link (S1...).'}}, ['name'])
def _add_speaker(ctx, a, log):
    before = {s['id'] for s in ctx.project()['speakers']}
    action(ctx.root, 'add-speaker', {'name': a['name'], 'title': a.get('title', '')}, log)
    sid = next(s['id'] for s in ctx.project()['speakers'] if s['id'] not in before)
    if a.get('cluster'):
        from . import speakers as sp
        sp.link(ctx.root, a['cluster'], sid)
    return result(f'Added speaker {sid}' + (f' linked to {a["cluster"]}' if a.get('cluster') else '') + '.', {'speaker': sid})


@tool('update_speaker', 'Rename a speaker, change their title, or (re)link a voice cluster to them (cluster="" unlinks).',
      {'speaker': {'type': 'string'}, 'name': {'type': 'string'}, 'title': {'type': 'string'}, 'cluster': {'type': 'string'}}, ['speaker'])
def _update_speaker(ctx, a, log):
    p = ctx.project()
    s = ctx.speaker(p, a['speaker'])
    for k in ['name', 'title']:
        if k in a:
            s[k] = a[k]
            for prod in p['productions']:
                for act in prod['scene']['actors']:
                    if act['id'] == s['id']:
                        act[k] = a[k]
    store(ctx.root, p)
    if 'cluster' in a:
        from . import speakers as sp
        an = sp.load_analysis(ctx.root)
        for c, v in an['clusters'].items():
            if v.get('speaker') == s['id']:
                v['speaker'] = None
        sp.store_analysis(ctx.root, an)
        if a['cluster']:
            sp.link(ctx.root, a['cluster'], s['id'])
    return result(f'Updated {s["id"]}.')


# ========================================================================= clips
@tool('propose_clips', 'Propose clips from the transcript (local sentence/pause rules by default; target_seconds/max_seconds settings apply). WARNING: replaces all existing clips and empties productions.', long=False)
def _propose(ctx, a, log):
    action(ctx.root, 'propose', {}, log)
    p = ctx.project()
    return result(f'{len(p["clips"])} clips proposed. Next: assign_clip_speakers, then review them.\n\n' + _clip_lines(p, p['clips'][:40]))


def _clip_flags(c, segs):
    """Quality notes for a clip: very short, or not ending on a sentence."""
    notes = []
    if c['end'] - c['start'] < 8:
        notes.append('short (<8 s)')
    inside = [x for x in segs or [] if x['end'] > c['start'] + .05 and x['start'] < c['end'] - .05]
    if inside:
        if not re.search(r'[.!?]["\')\]]?$', inside[-1]['text'].strip()):
            notes.append('ends mid-sentence')
        if inside[-1]['end'] > c['end'] + .3:
            notes.append(f'cuts the segment ending at {inside[-1]["end"]:.1f}s')
        if inside[0]['start'] < c['start'] - .3:
            notes.append(f'starts inside the segment from {inside[0]["start"]:.1f}s')
    return notes


def _clip_lines(p, clips, segs=None):
    names = {s['id']: s['name'] for s in p['speakers']}
    out = []
    for c in clips:
        flags = _clip_flags(c, segs)
        out.append(f'{c["id"]} [{_t(c["start"])}-{_t(c["end"])} = {c["start"]:.1f}-{c["end"]:.1f}s, {c["end"] - c["start"]:.0f}s] '
                   f'speaker={c["speaker"] or "-"} ({names.get(c["speaker"], "unassigned")}) reviewed={"yes" if c["reviewed"] else "no"} '
                   f'group={c.get("group") or "-"} "{c["title"][:70]}"' + (f'  !! {"; ".join(flags)}' if flags else ''))
    return '\n'.join(out)


def _segments(ctx, p):
    return read(path(ctx.root, p['transcript']))['segments'] if p.get('transcript') else None


@tool('list_clips', 'List clips with times (m:ss and seconds), speaker id/name, review state, group and title, plus "!!" quality flags (short, ends mid-sentence, cuts a segment). Filter by speaker (id or name) or unassigned; include_text adds the transcript of each clip.',
      {'speaker': {'type': 'string'}, 'unassigned': {'type': 'boolean'}, 'include_text': {'type': 'boolean'},
       'offset': {'type': 'integer'}, 'limit': {'type': 'integer', 'description': 'Default 60.'}})
def _list_clips(ctx, a, log):
    p = ctx.project()
    clips = p['clips']
    if a.get('speaker'):
        sid = ctx.speaker(p, a['speaker'])['id']
        clips = [c for c in clips if c['speaker'] == sid]
    if a.get('unassigned'):
        clips = [c for c in clips if not c['speaker']]
    off, lim = int(a.get('offset', 0)), int(a.get('limit', 60))
    page = clips[off:off + lim]
    segs = _segments(ctx, p)
    if a.get('include_text') and segs is not None:
        lines = []
        for c in page:
            lines.append(_clip_lines(p, [c], segs))
            lines.append('    ' + ' '.join(s['text'].strip() for s in segs if s['end'] > c['start'] and s['start'] < c['end'])[:1500])
            if c.get('intro'):
                lines.append('    intro: ' + c['intro'])
        text = '\n'.join(lines)
    else:
        text = _clip_lines(p, page, segs)
    more = f'\n... {len(clips) - off - lim} more (offset={off + lim})' if len(clips) > off + lim else ''
    return result(f'{len(clips)} clips\n' + text + more)


@tool('update_clips', 'Edit, add or remove clips. changes=[{id, start?, end?, title?, speaker?, intro?, group?, reviewed?}], add=[{start, end, title, speaker?, intro?, group?}], remove=[ids]. Times are seconds or "m:ss"; speaker is an id or exact name. Changing start/end/speaker clears reviewed unless you set it. intro is the optional context card shown before the clip (<=1600 chars, only facts supported by the recording). Set reviewed=true only after reading the clip text and checking it starts and ends on complete sentences. Returns the affected clips with quality flags.',
      {'changes': {'type': 'array', 'items': {'type': 'object'}}, 'add': {'type': 'array', 'items': {'type': 'object'}},
       'remove': {'type': 'array', 'items': {'type': 'string'}}})
def _update_clips(ctx, a, log):
    from ..core import newid
    p = ctx.project()
    byid = {c['id']: c for c in p['clips']}
    fields = {'start', 'end', 'title', 'speaker', 'intro', 'group', 'reviewed'}
    touched = []

    def clean(ch):
        ch = dict(ch)
        for k in ['start', 'end']:
            if k in ch:
                ch[k] = secs(ch[k])
        if ch.get('speaker'):
            ch['speaker'] = ctx.speaker(p, ch['speaker'])['id']
        return ch
    for ch in a.get('changes', []):
        c = byid.get(ch.get('id'))
        if c is None:
            raise ValueError(f'Unknown clip {ch.get("id")}')
        bad = set(ch) - fields - {'id'}
        if bad:
            raise ValueError(f'Clip fields allowed: {", ".join(sorted(fields))}')
        ch = clean(ch)
        if any(k in ch and ch[k] != c[k] for k in ['start', 'end', 'speaker']) and 'reviewed' not in ch:
            ch['reviewed'] = False
        c.update({k: v for k, v in ch.items() if k != 'id'})
        touched.append(c['id'])
    for new_clip in a.get('add', []):
        bad = set(new_clip) - fields
        if bad or not {'start', 'end'} <= set(new_clip):
            raise ValueError('New clips need start and end; allowed fields: ' + ', '.join(sorted(fields)))
        new_clip = clean(new_clip)
        cid = newid(p['clips'], f'clip_{len(p["clips"]) + 1:03}')
        p['clips'].append({'id': cid, 'title': new_clip.get('title', f'Clip {cid}'), 'speaker': new_clip.get('speaker'),
                           'intro': new_clip.get('intro', ''), 'group': new_clip.get('group', ''), 'reviewed': bool(new_clip.get('reviewed', False)),
                           'start': new_clip['start'], 'end': new_clip['end']})
        touched.append(cid)
    gone = set(a.get('remove', []))
    unknown = gone - set(byid)
    if unknown:
        raise ValueError(f'Unknown clip(s) to remove: {", ".join(sorted(unknown))}')
    if gone:
        p['clips'] = [c for c in p['clips'] if c['id'] not in gone]
        for prod in p['productions']:
            prod['clips'] = [x for x in prod['clips'] if x not in gone]
    p['clips'].sort(key=lambda c: c['start'])
    store(ctx.root, p)
    shown = [c for c in p['clips'] if c['id'] in touched]
    groups = {c.get('group') for c in shown if c.get('group')}
    pending = [c['id'] for c in p['clips'] if c.get('group') in groups and not c['reviewed']]
    text = f'Saved. {len(p["clips"])} clips' + (f', removed {", ".join(sorted(gone))}' if gone else '') + '.'
    if shown:
        text += '\n' + _clip_lines(p, shown, _segments(ctx, p))
    if pending:
        text += f'\nSame group, still unreviewed: {", ".join(pending)}'
    return result(text)


@tool('assign_clip_speakers', 'Assign each clip the speaker linked to the voice cluster that dominates it. Clips with no dominant voice are reported as mixed (split them or fix boundaries). Existing assignments are kept unless overwrite=true.',
      {'overwrite': {'type': 'boolean'}, 'threshold': {'type': 'number', 'description': 'Minimum share of talk time for the dominant voice (default 0.6).'}})
def _assign(ctx, a, log):
    from . import speakers as sp
    p = ctx.project()
    an = sp.load_analysis(ctx.root)
    rep = sp.assign_clips(p, an, a.get('overwrite', False), a.get('threshold', .6))
    store(ctx.root, p)
    text = (f'Assigned {len(rep["assigned"])}, kept {len(rep["kept"])}, mixed {len(rep["mixed"])}, '
            f'unlinked cluster {len(rep["unlinked"])}.')
    if rep['mixed']:
        text += '\nMixed: ' + '; '.join(f'{m["clip"]} ({m["clusters"]})' for m in rep['mixed'][:30])
    if rep['unlinked']:
        text += '\nDominated by an unlinked cluster: ' + '; '.join(f'{m["clip"]} ({m["clusters"]})' for m in rep['unlinked'][:30])
    return result(text, rep)


@tool('split_clips_by_speaker', 'Split clips at speaker turns (on transcript segment boundaries) so each part has one voice. Interjections shorter than min_seconds stay inside the surrounding part. Productions are updated to use the parts.',
      {'clips': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Clip IDs (default: all).'},
       'min_seconds': {'type': 'number', 'description': 'Parts shorter than this fold into a neighbour (default 8).'}})
def _split(ctx, a, log):
    from . import speakers as sp
    p = ctx.project()
    ch = sp.split_clips(p, sp.load_analysis(ctx.root), a.get('clips'), a.get('min_seconds', 8.0))
    store(ctx.root, p)
    return result(f'Split {len(ch)} clips: ' + '; '.join(f'{k} -> {", ".join(v)}' for k, v in ch.items()) if ch else 'No clip contains more than one speaker turn.', ch)


# ===================================================================== references
@tool('find_reference_frames', 'Find the clearest views of a speaker in the video (largest, sharpest, most frontal face while their voice is talking) and show numbered head-and-shoulders candidates. Needs a linked voice cluster or assigned clips.',
      {'speaker': {'type': 'string'}, 'count': {'type': 'integer', 'description': 'Candidates to keep (default 8).'},
       'samples': {'type': 'integer', 'description': 'Moments to scan (default 24).'}}, ['speaker'], long=True)
def _find_refs(ctx, a, log):
    from . import references as rf
    p = ctx.project()
    s = ctx.speaker(p, a['speaker'])
    items = rf.find(ctx.root, p, s, int(a.get('count', 8)), int(a.get('samples', 24)), log)
    text = '\n'.join(f'#{c["candidate"]}: t={c["time"]:.1f}s face {c["face_px"]}px quality {c["score"]:.2f} ({c["chosen_by"]}, {c["faces_in_frame"]} faces in frame)' for c in items)
    text += ('\n\nPick the candidate that clearly shows THIS person (check against inspect_cluster) with a sharp, unobstructed face: '
             'set_reference candidate=N. Add 1-2 more angles with extra=true for better likeness. Faces under ~80 px are weak references; '
             'prefer close-ups (screen shares, remote video tiles) when the person appears in them.')
    return result(text, items, [(rf.candidate_sheet(ctx.root, s, items), f'{s["id"]} reference candidates')])


@tool('set_reference', 'Save a reference photo for a speaker: a candidate number from the last find_reference_frames run FOR THIS SPEAKER (candidates are kept per speaker), a moment of the video (seconds + optional box=[x0,y0,x1,y1] fractions to crop the person), or an image file path. extra=true adds an additional angle instead of replacing the primary reference.',
      {'speaker': {'type': 'string'}, 'candidate': {'type': 'integer'}, 'seconds': TIME,
       'box': {'type': 'array', 'items': {'type': 'number'}}, 'path': {'type': 'string'}, 'extra': {'type': 'boolean'}}, ['speaker'])
def _set_ref(ctx, a, log):
    from . import references as rf
    p = ctx.project()
    s = ctx.speaker(p, a['speaker'])
    rel, im = rf.set_reference(ctx.root, p, s, a.get('candidate'), secs(a['seconds']) if 'seconds' in a else None, a.get('box'), a.get('path'), a.get('extra', False))
    return result(f'Saved {rel} ({im.width}x{im.height}).', {'path': rel}, [(im, rel)])


# =========================================================================== art
@tool('art_brief', 'Prepare an art request for a chat assistant in the browser (e.g. Gemini on the web via computer-use): writes handoff/art/<speaker>/BRIEF.md + prompt.txt, stages the images to upload, and returns step-by-step browser instructions. kind=pose briefs a gesture variant of the imported neutral figure.',
      {'speaker': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['neutral', 'pose']}, 'pose': {'type': 'string', 'description': 'Gesture ID for kind=pose, e.g. explain.'},
       'description': {'type': 'string', 'description': 'Gesture description for kind=pose, e.g. "right hand raised, palm open, explaining".'},
       'style': {'type': 'string', 'description': 'Override the project art style for this request.'},
       'notes': {'type': 'string', 'description': 'Extra instructions (likeness details you noticed: glasses, beard, clothing...).'}}, ['speaker'])
def _brief(ctx, a, log):
    from . import art
    p = ctx.project()
    s = ctx.speaker(p, a['speaker'])
    b = art.brief(ctx.root, p, s, a.get('style'), a.get('notes', ''), a.get('kind', 'neutral'), a.get('pose', ''), a.get('description', ''))
    text = (f'Brief: {b["brief"]}\nUpload: {", ".join(b["upload"])}\nSave the result to (suggested): {b["suggested_download_path"]}\n\n'
            f'--- PROMPT ---\n{b["prompt"]}\n--- END PROMPT ---\n\nBrowser steps:\n' + '\n'.join(f'{i + 1}. {x}' for i, x in enumerate(b['browser_steps'])))
    return result(text, b)


@tool('generate_art', 'Generate a figure draft through an image API: provider=gemini (needs GEMINI_API_KEY or the configured gemini_key_env) or provider=openai (images/edits at api_base with key_env). Uses the speaker\'s reference photos (kind=neutral) or neutral figure (kind=pose). The draft is checked and shown; it is NOT imported.',
      {'speaker': {'type': 'string'}, 'provider': {'type': 'string', 'enum': ['gemini', 'openai']}, 'kind': {'type': 'string', 'enum': ['neutral', 'pose']},
       'pose': {'type': 'string'}, 'description': {'type': 'string'}, 'style': {'type': 'string'}, 'notes': {'type': 'string'}},
      ['speaker'], long=True)
def _generate(ctx, a, log):
    from . import art
    p = ctx.project()
    s = ctx.speaker(p, a['speaker'])
    kind = a.get('kind', 'neutral')
    prov = a.get('provider', 'gemini')
    said = ''
    if prov == 'gemini':
        uploads = [path(ctx.root, s['asset'])] if kind == 'pose' else art.references(ctx.root, s)
        if not uploads:
            raise ValueError('Set a reference first (find_reference_frames + set_reference).')
        text = art.prompt(s, p['settings'], a.get('style'), a.get('notes', ''), kind, a.get('description', ''))
        rel, said = art.gemini(ctx.root, s, p['settings'], text, uploads, log)
    else:
        if kind == 'pose':
            action(ctx.root, 'generate-asset', {'speaker': s['id'], 'kind': 'pose', 'pose': a.get('pose', ''), 'description': a.get('description', ''), 'method': 'api'}, log)
            rel = ctx.speaker(ctx.project(), s['id'])['asset_drafts'][-1]['path']
        else:
            action(ctx.root, 'generate-art', {'speaker': s['id']}, log)
            rel = ctx.speaker(ctx.project(), s['id'])['draft']
    return _checked(ctx, s, ctx.root / rel, kind, f'Draft saved: {rel}' + (f'\nModel said: {said}' if said else ''))


def _checked(ctx, s, file, kind, head=''):
    from . import art
    neutral = path(ctx.root, s['asset']) if kind == 'pose' and s.get('asset') else None
    rep = art.check(ctx.root, file, s, kind, neutral)
    lines = [head] if head else []
    lines.append('PASS' if rep['ok'] else 'FAIL')
    lines += [f'ERROR: {e}' for e in rep['errors']] + [f'WARNING: {w}' for w in rep['warnings']]
    if rep['suggestions']:
        lines.append('Re-prompt with: ' + ' '.join(rep['suggestions']))
    lines.append('Metrics: ' + json.dumps(rep['metrics']))
    lines.append('Also judge likeness yourself against the reference (hair, glasses, facial hair, skin tone, clothing).')
    return result('\n'.join(lines), {**rep, 'path': str(file)}, [(art.preview(ctx.root, file, rep), 'blue = figure bounds, red = detected face')])


@tool('check_artwork', 'Measure a figure image before importing: single figure, clean white background, nothing cropped, size, face detectable/frontal, mouth gently parted; returns errors, warnings and re-prompt suggestions plus a marked preview.',
      {'path': {'type': 'string'}, 'speaker': {'type': 'string', 'description': 'Needed for kind=pose (compares with the neutral canvas).'},
       'kind': {'type': 'string', 'enum': ['neutral', 'pose']}}, ['path'])
def _check(ctx, a, log):
    p = ctx.project()
    s = ctx.speaker(p, a['speaker']) if a.get('speaker') else {'id': '', 'name': ''}
    return _checked(ctx, s, _project_file(ctx, a['path']), a.get('kind', 'neutral'))


@tool('import_artwork', 'Import a figure image as the speaker\'s neutral master (kind=neutral; resets anatomy, extras and gestures) or as a gesture (kind=pose with pose=<id>; must match the neutral canvas and change only the arm area). Neutral imports run anatomy detection and return the overlay to review. Refuses images that fail check_artwork unless force=true.',
      {'speaker': {'type': 'string'}, 'path': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['neutral', 'pose']},
       'pose': {'type': 'string'}, 'force': {'type': 'boolean'}}, ['speaker', 'path'], long=True)
def _import_art(ctx, a, log):
    from . import art
    p = ctx.project()
    s = ctx.speaker(p, a['speaker'])
    kind = a.get('kind', 'neutral')
    src = art.stage(ctx.root, a['path'])
    if kind == 'pose':
        if not s.get('asset'):
            raise ValueError('Import the neutral figure first.')
        if not a.get('pose'):
            raise ValueError('Give pose=<gesture id>, e.g. explain.')
        src = art.fit_pose(ctx.root, src, path(ctx.root, s['asset']))
    rep = art.check(ctx.root, src, s, kind, path(ctx.root, s['asset']) if kind == 'pose' else None)
    if not rep['ok'] and not a.get('force'):
        return result('Not imported - fix these first (or force=true if you are sure):\n' + '\n'.join(rep['errors'])
                      + ('\nRe-prompt with: ' + ' '.join(rep['suggestions']) if rep['suggestions'] else ''), rep,
                      [(art.preview(ctx.root, src, rep), 'rejected draft')])
    action(ctx.root, 'import-asset', {'speaker': s['id'], 'kind': kind, 'path': str(src), 'pose': a.get('pose', '')}, log)
    if kind == 'pose':
        s = ctx.speaker(ctx.project(), s['id'])
        pose = next(x for x in s['poses'] if x['id'] == a['pose'])
        im = Image.open(path(ctx.root, pose['path']))
        return result(f'Gesture {a["pose"]} imported (pixels outside the arm envelope were restored from the neutral). Check the arms look right.',
                      None, [(im, a['pose'])])
    log('Detecting anatomy...')
    try:
        art.calibrate(ctx.root, s, log)
    except Exception as e:
        return result(f'Artwork imported, but anatomy detection failed: {e}\nTry artwork with a larger, clearer, front-facing face, '
                      'or import a reviewed profile.json.', None, [(Image.open(path(ctx.root, ctx.speaker(ctx.project(), s['id'])['asset'])), 'imported')])
    return _review(ctx, {'speaker': s['id']}, log, 'Artwork imported and anatomy detected. ')


@tool('review_anatomy', 'Show the detected anatomy on the speaker\'s artwork: blue = bust crop used for the talking face, red = mouth box, green line = nose, magenta line = jaw. Approve only if the red box covers the lips and the bust contains the whole head.',
      {'speaker': {'type': 'string'}}, ['speaker'])
def _review(ctx, a, log, head=''):
    from . import art
    p = ctx.project()
    s = ctx.speaker(p, a['speaker'])
    full, crop = art.anatomy_overlay(ctx.root, s)
    if crop is None:
        return result(head + 'No anatomy profile yet; import_artwork runs detection.', None, [(full, 'artwork')])
    prof = read(path(ctx.root, s['profile']))
    text = head + (f'Approved: {s.get("approved")}. Bust {list(map(round, prof["bust"]))}, mouth {list(map(round, prof["mouth_box_body"]))}.\n'
                   'Check: red box tightly around the lips (not the nose or chin); blue box holds the whole head with some neck; nose line above the mouth, jaw line below. '
                   'If correct, approve_anatomy. If wrong, the art likely needs a clearer face - regenerate.')
    return result(text, prof, [(full, 'full figure'), (crop.resize((min(640, crop.width * 2), round(crop.height * min(640, crop.width * 2) / crop.width))), 'bust close-up')])


@tool('approve_anatomy', 'Approve the detected anatomy after review_anatomy looked right. Required before rendering with the talking-face backend.',
      {'speaker': {'type': 'string'}}, ['speaker'])
def _approve(ctx, a, log):
    action(ctx.root, 'approve', {'speaker': a['speaker']}, log)
    return result(f'Anatomy approved for {a["speaker"]}.')


@tool('generate_asset_draft', 'Make a reviewable draft of an extra: kind=closed (closed-mouth rest for silences), breath (torso breathing mask), inference-bust (padded face crop for lip sync), pose (gesture via image API). method=local (default for closed/breath/inference-bust, no network) or api. Returns the draft image; import it with import_asset_draft after checking it.',
      {'speaker': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['closed', 'breath', 'inference-bust', 'pose']},
       'method': {'type': 'string', 'enum': ['local', 'api']}, 'pose': {'type': 'string'}, 'description': {'type': 'string'}}, ['speaker', 'kind'])
def _gen_draft(ctx, a, log):
    args = {'speaker': a['speaker'], 'kind': a['kind'], 'method': a.get('method', 'local'), 'pose': a.get('pose', ''), 'description': a.get('description', '')}
    action(ctx.root, 'generate-asset', args, log)
    d = ctx.speaker(ctx.project(), a['speaker'])['asset_drafts'][-1]
    im = Image.open(path(ctx.root, d['path']))
    hint = {'breath': 'White = moves with breathing. It must cover only the chest/torso - never the chair, arms, head or legs.',
            'closed': 'Lips should look naturally closed with no seam or colour shift around the mouth.',
            'inference-bust': 'Whole head centred, mouth gently parted.', 'pose': 'Only the arms/hands may differ from the neutral figure.'}[a['kind']]
    return result(f'Draft: {d["path"]}\n{hint}\nIf it is right: import_asset_draft path="{d["path"]}".', d, [(im, d['path'])])


@tool('import_asset_draft', 'Import a draft made by generate_asset_draft (by its path).',
      {'speaker': {'type': 'string'}, 'path': {'type': 'string'}}, ['speaker', 'path'])
def _import_draft(ctx, a, log):
    action(ctx.root, 'import-asset-draft', {'speaker': a['speaker'], 'path': a['path']}, log)
    return result('Imported.')


# =================================================================== productions
def _layout(scene, speakers):
    from ..core import actor
    n = len(speakers)
    acts = [actor(s, i) for i, s in enumerate(speakers)]
    if n >= 3:
        for i, act in enumerate(acts):
            act['x'] = round(1280 * (i + .5) / n)
            act['height'] = round(min(535, 535 * 2.4 / n))
            w = max(160, round(1280 / n) - 30)
            act['label'].update(x=round(1280 * i / n) + 15, width=w, name_size=max(18, round(36 * 2 / n)), title_size=max(12, round(22 * 2 / n)))
    scene['actors'] = acts
    return scene


@tool('create_production', 'Create a production (a reusable scene + ordered clips). speakers = figures on stage (default: all speakers of the chosen clips). clips = clip IDs; or for_speakers=true to take every clip of those speakers in time order. output: separate|together|both; intro_mode: clip|production|none.',
      {'name': {'type': 'string'}, 'speakers': {'type': 'array', 'items': {'type': 'string'}}, 'clips': {'type': 'array', 'items': {'type': 'string'}},
       'for_speakers': {'type': 'boolean'}, 'output': {'type': 'string', 'enum': ['separate', 'together', 'both']},
       'intro_mode': {'type': 'string', 'enum': ['clip', 'production', 'none']}}, ['name'])
def _create_prod(ctx, a, log):
    from scene import default_scene
    from ..core import newid
    p = ctx.project()
    clips = list(a.get('clips') or [])
    sids = a.get('speakers') or sorted({c['speaker'] for c in p['clips'] if c['id'] in clips and c['speaker']})
    if not sids:
        raise ValueError('Name the speakers to put on stage (speakers=[...]).')
    roster = [ctx.speaker(p, x) for x in sids]
    if a.get('for_speakers'):
        clips = [c['id'] for c in sorted(p['clips'], key=lambda c: c['start']) if c['speaker'] in sids]
    known = {c['id']: c for c in p['clips']}
    for c in clips:
        if c not in known:
            raise ValueError(f'Unknown clip {c}')
        if known[c]['speaker'] not in sids:
            raise ValueError(f'Clip {c} belongs to {known[c]["speaker"] or "nobody"}, who is not on stage.')
    prod = {'id': newid(p['productions'], a['name']), 'name': a['name'], 'clips': clips, 'output': a.get('output', 'both'),
            'intro_mode': a.get('intro_mode', 'clip'), 'scene': _layout(default_scene(), roster)}
    p['productions'].append(prod)
    store(ctx.root, p)
    missing = [s['id'] for s in roster if not s.get('asset')]
    return result(f'Created production {prod["id"]} with {len(clips)} clips.' + (f' Artwork still missing for: {", ".join(missing)}.' if missing else ' Run snapshot to check the layout.'), {'production': prod['id']})


def _merge_into(dst, patch):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge_into(dst[k], v)
        else:
            dst[k] = v


@tool('update_production', 'Change a production: name, clips (replace order), add_clips, remove_clips, output, intro_mode, scene (deep-merged patch, e.g. {"background":{"color":"#f3f5f9"},"subtitles":{"size":28},"intro":{"enabled":true,"text":"..."}}), actors ({speaker_id: patch} e.g. {"x":900,"height":560,"mirror":true,"label":{"x":60},"gestures":{"seed":7}}). Canvas is 1280x720; actor x = figure centre, y = feet line. Call snapshot afterwards.',
      {'production': {'type': 'string'}, 'name': {'type': 'string'}, 'clips': {'type': 'array', 'items': {'type': 'string'}},
       'add_clips': {'type': 'array', 'items': {'type': 'string'}}, 'remove_clips': {'type': 'array', 'items': {'type': 'string'}},
       'output': {'type': 'string', 'enum': ['separate', 'together', 'both']}, 'intro_mode': {'type': 'string', 'enum': ['clip', 'production', 'none']},
       'scene': {'type': 'object'}, 'actors': {'type': 'object'}}, ['production'])
def _update_prod(ctx, a, log):
    p = ctx.project()
    prod = next((x for x in p['productions'] if x['id'] == a['production']), None)
    if not prod:
        raise ValueError(f'Unknown production {a["production"]}; known: {", ".join(x["id"] for x in p["productions"])}')
    for k in ['name', 'output', 'intro_mode']:
        if k in a:
            prod[k] = a[k]
    if 'clips' in a:
        prod['clips'] = list(a['clips'])
    prod['clips'] += [c for c in a.get('add_clips', []) if c not in prod['clips']]
    prod['clips'] = [c for c in prod['clips'] if c not in set(a.get('remove_clips', []))]
    if a.get('scene'):
        patch = copy.deepcopy(a['scene'])
        if 'actors' in patch or 'canvas' in patch:
            raise ValueError('Use the actors argument for figures; the canvas is fixed at 1280x720.')
        _merge_into(prod['scene'], patch)
    for sid, patch in (a.get('actors') or {}).items():
        act = next((x for x in prod['scene']['actors'] if x['id'] == sid), None)
        if not act:
            raise ValueError(f'{sid} is not on stage in this production.')
        _merge_into(act, patch)
    store(ctx.root, p)
    return result(f'Saved {prod["id"]}: {len(prod["clips"])} clips.')


@tool('snapshot', 'Render one still frame of a production with the final renderer (figures, labels, background, lighting) to check the layout.',
      {'production': {'type': 'string'}}, ['production'])
def _snapshot(ctx, a, log):
    action(ctx.root, 'snapshot', {'production': a['production']}, log)
    with Image.open(ctx.root / 'work/snapshot.png') as im:
        return result('Snapshot of ' + a['production'] + '. Subtitles are not shown in stills; check them in a preview render.', None, [(im.copy(), 'snapshot')])


@tool('render', 'Render productions (preview=true renders the first 12 s of each clip - do this first for every new speaker). Clips must have speakers and reviewed=true. Can take minutes to hours; resumes from caches.',
      {'productions': {'type': 'array', 'items': {'type': 'string'}}, 'preview': {'type': 'boolean'}}, long=True)
def _render(ctx, a, log):
    rep = action(ctx.root, 'render', {'productions': a.get('productions'), 'preview': a.get('preview', False)}, log)
    from ..gallery import catalog
    items = catalog(ctx.root)[:20]
    return result('Render finished.\n' + '\n'.join(f'{x["path"]} ({x["kind"]}, {x.get("duration") or "?"}s)' for x in items), {'report': rep})


@tool('list_renders', 'List rendered files (newest first). Inspect them with view_frames source=<path>.')
def _renders(ctx, a, log):
    from ..gallery import catalog
    items = catalog(ctx.root)
    return result('\n'.join(f'{x["path"]} | {x["production_name"]} | {x["title"]} | {x["kind"]} | {x.get("duration") or "?"}s' for x in items) or 'No renders yet.', items)


# ========================================================================== jobs
@tool('job_status', 'Status and recent log of a background job (default: the most recent).',
      {'job': {'type': 'string'}, 'tail': {'type': 'integer'}})
def _job_status(ctx, a, log):
    from . import jobs
    st = jobs.status(ctx.root, a.get('job'), int(a.get('tail', 30)))
    if st['status'] in ('completed', 'failed', 'cancelled'):
        return _job_reply(ctx, st)
    return result(f'{st["id"]} {st["tool"]}: {st["status"]} ({st["elapsed_seconds"]}s)\n' + '\n'.join(st['log_tail']), {'status': st['status']})


@tool('wait_for_job', 'Wait (up to seconds, max 110 per call) for a background job and return its result when done.',
      {'job': {'type': 'string'}, 'seconds': {'type': 'number'}}, ['job'])
def _wait(ctx, a, log):
    from . import jobs
    return _job_reply(ctx, jobs.wait(ctx.root, a['job'], min(110, float(a.get('seconds', 100)))))


@tool('cancel_job', 'Stop a running background job (its process tree is terminated; caches already written are kept).',
      {'job': {'type': 'string'}}, ['job'])
def _cancel(ctx, a, log):
    from . import jobs
    st = jobs.cancel(ctx.root, a['job'])
    return result(f'Cancelled {st["id"]}.')


@tool('diagnose', 'Check this computer for rendering: GPU, FFmpeg, transcription, and (model=true) the talking-face environment startup.',
      {'model': {'type': 'boolean'}}, long=True)
def _diagnose(ctx, a, log):
    rep = action(ctx.root, 'diagnose', {'model': a.get('model', False)}, log)
    return result('\n'.join(f'{c["name"]}: {c["status"]} {c.get("detail", "")}' for c in rep.get('checks', [])), rep)


@tool('discover_tools', 'Find and verify existing animation tools (SadTalker checkout + CUDA Python) on this computer and save them for the project.', long=True)
def _discover(ctx, a, log):
    rep = action(ctx.root, 'discover-tools', {}, log)
    return result(json.dumps(rep, indent=1, default=str)[:4000], None)


def describe():
    return [{'name': t['name'], 'description': t['description'], 'inputSchema': t['schema']} for t in TOOLS.values()]
