"""``studio.py --project P agent TOOL --args JSON``: the MCP tools for shell-only agents and scripts."""
import json
import sys
import time

from .tools import TOOLS, Context, call


def main(root, name, raw_args='{}', wait=600):
    if name in ['list', 'help']:
        for t in TOOLS.values():
            props = ', '.join(t['schema']['properties'])
            print(f'{t["name"]}({props})\n    {t["description"]}\n')
        return
    ctx = Context(root)
    args = json.loads(raw_args)
    if TOOLS.get(name, {}).get('long'):
        args.setdefault('wait_seconds', 0)
    log = lambda x: print(x, file=sys.stderr, flush=True)
    out = call(ctx, name, args, log=log)
    job = (out.get('data') or {}).get('job') if isinstance(out.get('data'), dict) else None
    if job and (out.get('data') or {}).get('status') == 'running':
        from .tools import _job_reply
        from . import jobs
        deadline = time.time() + wait
        seen = 0
        while time.time() < deadline:
            st = jobs.wait(ctx.root, job, min(10, max(1, deadline - time.time())))
            full = jobs.status(ctx.root, job, tail=100000)['log_tail']
            for line in full[seen:]:
                log('  ' + line)
            seen = len(full)
            if st['status'] != 'running':
                break
        out = _job_reply(ctx, jobs.status(ctx.root, job))
    print(out.get('text') or json.dumps(out.get('data'), indent=1, default=str))
    if out.get('images'):
        folder = ctx.root / 'work/agent/cli'
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%H%M%S')
        for n, (im, caption) in enumerate(out['images'], 1):
            f = folder / f'{name}_{stamp}_{n}.jpg'
            im.convert('RGB').save(f, quality=88)
            print(f'[image] {f}  ({caption})')
