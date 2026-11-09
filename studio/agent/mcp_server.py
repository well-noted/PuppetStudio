"""Model Context Protocol server (stdio, JSON-RPC 2.0) for headless Puppet Studio.

Dependency-free: newline-delimited JSON over stdin/stdout as in the MCP stdio
transport. stdout carries protocol messages only; everything else that would
print (Studio logs, native libraries) is redirected to stderr.

Run:  python studio.py --project projects/NAME mcp
"""
import json
import os
import sys
import traceback

from . import media
from .tools import TOOLS, Context, call, describe

VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05']
SERVER = {'name': 'puppet-studio', 'title': 'Puppet Studio (headless)', 'version': '0.1.0'}
INSTRUCTIONS = """Puppet Studio turns a recorded talk/panel into illustrated, lip-synced puppet videos.
Start every session with `guide` (the full playbook) and `project_status` (what is done, what is next).
Workflow: import_media -> transcribe -> analyze_speakers -> inspect_cluster / merge_clusters -> add_speaker(cluster=) ->
propose_clips -> assign_clip_speakers / split_clips_by_speaker -> review clips (update_clips reviewed=true) ->
find_reference_frames -> set_reference -> art_brief (browser, e.g. Gemini web) or generate_art (API) -> check_artwork ->
import_artwork -> review_anatomy -> approve_anatomy -> create_production -> snapshot -> render preview=true -> view_frames -> render.
Look at images before deciding: every visual tool returns pictures. Never invent names, quotes or context.
Long tools return a job ID when not finished in wait_seconds; continue with wait_for_job."""


def _content(out):
    blocks = []
    text = out.get('text') or ''
    if out.get('data') is not None and not text:
        text = json.dumps(out['data'], indent=1, default=str)
    if text:
        blocks.append({'type': 'text', 'text': text})
    for im, caption in out.get('images', []):
        data, mime = media.encode(im)
        blocks.append({'type': 'image', 'data': data, 'mimeType': mime})
        if caption:
            blocks.append({'type': 'text', 'text': f'(image above: {caption})'})
    return blocks or [{'type': 'text', 'text': 'Done.'}]


def _guide():
    from ..core import ROOT
    return (ROOT / 'docs/AGENTS.md').read_text(encoding='utf-8')


class Server:
    def __init__(self, root, out):
        self.ctx = Context(root)
        self.out = out

    def send(self, msg):
        self.out.write((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))
        self.out.flush()

    def log(self, x):
        print(x, file=sys.stderr, flush=True)

    def handle(self, msg):
        method, mid, params = msg.get('method'), msg.get('id'), msg.get('params') or {}
        if method is None:
            return None  # a response to something we never sent
        if mid is None:
            return None  # notification (initialized, cancelled, ...)
        try:
            return {'jsonrpc': '2.0', 'id': mid, 'result': self.dispatch(method, params)}
        except KeyError as e:
            return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32602, 'message': f'Missing parameter {e}'}}
        except LookupError as e:
            return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': str(e)}}

    def dispatch(self, method, params):
        if method == 'initialize':
            asked = params.get('protocolVersion')
            return {'protocolVersion': asked if asked in VERSIONS else VERSIONS[0],
                    'capabilities': {'tools': {'listChanged': False}, 'resources': {}, 'prompts': {}},
                    'serverInfo': SERVER, 'instructions': INSTRUCTIONS}
        if method == 'ping':
            return {}
        if method == 'tools/list':
            return {'tools': describe()}
        if method == 'tools/call':
            name = params['name']
            if name not in TOOLS:
                return {'content': [{'type': 'text', 'text': f'Unknown tool {name}'}], 'isError': True}
            try:
                return {'content': _content(call(self.ctx, name, params.get('arguments') or {}, log=self.log)), 'isError': False}
            except Exception as e:  # tool errors go back to the model as readable text
                traceback.print_exc(file=sys.stderr)
                return {'content': [{'type': 'text', 'text': f'{name} failed: {e or e.__class__.__name__}'}], 'isError': True}
        if method == 'resources/list':
            return {'resources': [{'uri': 'puppet-studio://guide', 'name': 'guide', 'title': 'Puppet Studio agent playbook',
                                   'mimeType': 'text/markdown'}]}
        if method == 'resources/read':
            if params['uri'] != 'puppet-studio://guide':
                raise LookupError('Unknown resource')
            return {'contents': [{'uri': params['uri'], 'mimeType': 'text/markdown', 'text': _guide()}]}
        if method == 'resources/templates/list':
            return {'resourceTemplates': []}
        if method == 'prompts/list':
            return {'prompts': [{'name': 'make_production', 'title': 'Make a puppet production from a recording',
                                 'description': 'Run the whole Puppet Studio workflow for a recording.',
                                 'arguments': [{'name': 'recording', 'description': 'Path to the video/audio file', 'required': True},
                                               {'name': 'project', 'description': 'Project name (folder under projects/)', 'required': False},
                                               {'name': 'style', 'description': 'Art style', 'required': False}]}]}
        if method == 'prompts/get':
            if params['name'] != 'make_production':
                raise LookupError('Unknown prompt')
            a = params.get('arguments') or {}
            text = (f'Make an illustrated puppet production from the recording at {a.get("recording")}. '
                    f'Use project "{a.get("project") or "my_project"}" (open_project create=true). '
                    + (f'Art style: {a["style"]}. ' if a.get('style') else '')
                    + 'First read the guide tool and follow its workflow and quality bar. Look at every image you are shown before '
                      'deciding, verify speaker identities from captions/introductions, and render a preview before a full render.')
            return {'messages': [{'role': 'user', 'content': {'type': 'text', 'text': text}}]}
        if method == 'logging/setLevel':
            return {}
        raise LookupError(f'Method not found: {method}')

    def serve(self, stdin):
        for raw in stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                self.send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}})
                continue
            batch = msg if isinstance(msg, list) else [msg]
            replies = [r for r in (self.handle(m) for m in batch if isinstance(m, dict)) if r]
            if replies:
                self.send(replies if isinstance(msg, list) else replies[0])


def protect_stdout():
    """Keep fd 1 for protocol bytes; route print() and native writes to stderr."""
    proto = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return proto


def main(root):
    out = protect_stdout()
    Server(root, out).serve(sys.stdin.buffer)
