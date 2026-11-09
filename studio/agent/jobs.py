"""Background jobs for long agent tools (transcription, analysis, generation, rendering).

A job runs one registered tool in a child ``studio.py --project P agent-job ID``
process so the MCP connection stays responsive and the work survives slow
steps. State lives in ``work/agent/jobs/ID.json``; output in ``ID.log``; the
tool's result (with any images saved as files) in ``ID.result.json``.
"""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from ..core import ROOT, read, save

FOLDER = 'work/agent/jobs'
_procs = {}


def folder(root):
    f = Path(root) / FOLDER
    f.mkdir(parents=True, exist_ok=True)
    return f


def running(root):
    """The running job in this server process, if any."""
    for key, proc in list(_procs.items()):
        if proc.poll() is None:
            state = read(folder(root) / f'{key}.json') if (folder(root) / f'{key}.json').is_file() else {}
            if state.get('project') == str(Path(root).resolve()):
                return key
    return None


def start(root, tool, args):
    root = Path(root).resolve()
    busy = running(root)
    if busy:
        raise ValueError(f'Job {busy} is still running; wait_for_job or cancel_job first.')
    key = time.strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(3)
    state = {'id': key, 'tool': tool, 'args': args, 'status': 'running', 'started': time.time(), 'project': str(root)}
    save(folder(root) / f'{key}.json', state)
    log = (folder(root) / f'{key}.log').open('w', encoding='utf-8')
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1'}
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    proc = subprocess.Popen([sys.executable, str(ROOT / 'studio.py'), '--project', str(root), 'agent-job', key],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                            creationflags=flags, start_new_session=os.name != 'nt')
    log.close()
    _procs[key] = proc
    state['pid'] = proc.pid
    save(folder(root) / f'{key}.json', state)
    return state


def status(root, key=None, tail=30):
    f = folder(root)
    if not key:
        jobs = sorted(f.glob('*.json'), key=lambda x: x.stat().st_mtime, reverse=True)
        jobs = [j for j in jobs if not j.name.endswith('.result.json')]
        if not jobs:
            raise ValueError('No jobs have been started in this project.')
        key = jobs[0].stem
    state_file = f / f'{key}.json'
    if not state_file.is_file():
        raise ValueError(f'Unknown job {key}')
    state = read(state_file)
    proc = _procs.get(key)
    if state['status'] == 'running' and proc is not None and proc.poll() is not None:
        # Child died without recording an outcome (crash, kill).
        state = read(state_file)
        if state['status'] == 'running':
            state.update(status='failed', error=f'Worker exited with code {proc.returncode}', finished=time.time())
            save(state_file, state)
    logf = f / f'{key}.log'
    lines = logf.read_text(encoding='utf-8', errors='replace').splitlines() if logf.is_file() else []
    noise = ('W0000', 'I0000', 'INFO: Created TensorFlow', 'WARNING: All log messages')
    lines = [x for x in lines if not x.startswith(noise)]
    state['log_tail'] = lines[-tail:]
    state['elapsed_seconds'] = round((state.get('finished') or time.time()) - state['started'], 1)
    resf = f / f'{key}.result.json'
    if state['status'] == 'completed' and resf.is_file():
        state['result'] = read(resf)
    return state


def wait(root, key, seconds):
    deadline = time.time() + max(0, min(float(seconds), 600))
    while True:
        st = status(root, key)
        if st['status'] != 'running' or time.time() >= deadline:
            return st
        time.sleep(1.0)


def cancel(root, key):
    st = status(root, key)
    if st['status'] != 'running':
        raise ValueError(f'Job {key} is not running ({st["status"]}).')
    pid = st.get('pid')
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
    else:
        import signal
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    state = read(folder(root) / f'{key}.json')
    state.update(status='cancelled', finished=time.time())
    save(folder(root) / f'{key}.json', state)
    return state


def run_child(root, key):
    """Entry point inside the worker process."""
    from .tools import Context, call
    f = folder(root)
    state = read(f / f'{key}.json')
    ctx = Context(root, in_job=True)
    log = lambda x: print(x, flush=True)
    try:
        result = call(ctx, state['tool'], state['args'], log=log, background=False)
        images = []
        for n, (im, caption) in enumerate(result.get('images', [])):
            file = f / f'{key}_{n + 1}.jpg'
            im.convert('RGB').save(file, quality=88)
            images.append({'file': file.relative_to(Path(root).resolve()).as_posix(), 'caption': caption})
        save(f / f'{key}.result.json', {'text': result.get('text', ''), 'data': result.get('data'), 'images': images})
        state.update(status='completed', finished=time.time())
        save(f / f'{key}.json', state)
    except Exception as e:  # report every failure to the agent, never silently
        state.update(status='failed', error=str(e) or e.__class__.__name__, finished=time.time())
        save(f / f'{key}.json', state)
        print('ERROR:', e, flush=True)
        raise SystemExit(1)
