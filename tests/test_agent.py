"""Headless agent layer: speaker analysis, clip tools, art checks and the MCP server."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['STUDIO_AGENT_OFFLINE'] = '1'  # never download models in tests

from studio.core import new, save, store, load  # noqa: E402
from studio.agent import art, speakers, tools  # noqa: E402

RATE = 16000


def voice(seconds, low, high, buzz, seed):
    """Crude synthetic 'voice': band-limited noise plus a pitched buzz."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    spec = np.fft.rfft(rng.normal(size=n))
    f = np.fft.rfftfreq(n, 1 / RATE)
    spec[(f < low) | (f > high)] = 0
    t = np.arange(n) / RATE
    x = np.fft.irfft(spec, n)
    x = x / (np.abs(x).max() + 1e-9) * .3 + .2 * np.sign(np.sin(2 * np.pi * buzz * t)) * (np.sin(2 * np.pi * 3 * t) > -.3)
    return x.astype(np.float32)


def synthetic_project(root):
    """Two voices taking turns of 8-12 s, transcript cut into ~2 s segments."""
    order = ['A', 'B', 'A', 'B', 'A', 'B']
    lengths = [12, 10, 8, 12, 10, 8]
    audio, segments, truth, cursor = [], [], [], 0.0
    for n, (who, length) in enumerate(zip(order, lengths)):
        audio.append(voice(length, 200, 1200, 110, n) if who == 'A' else voice(length, 1500, 4500, 230, n))
        for k in range(int(length // 2)):
            text = 'My name is Ada Lovelace.' if (who == 'A' and n == 0 and k == 0) else ('Thank you, Grace.' if (who == 'A' and n == 0 and k == 5) else f'words {n} {k}.')
            segments.append({'start': cursor + k * 2 + .1, 'end': cursor + k * 2 + 1.9, 'text': text})
            truth.append(who)
        cursor += length
    samples = np.concatenate(audio)
    p = new()
    p['media'] = {'path': 'media/source.wav', 'duration': cursor, 'video': False}
    p['transcript'] = 'transcript/transcript.json'
    save(root / 'transcript/transcript.json', {'segments': segments, 'words': [], 'warnings': []})
    (root / 'media').mkdir(parents=True, exist_ok=True)
    (root / 'media/source.wav').write_bytes(b'')  # placeholder; audio decoding is patched
    store(root, p)
    return samples, truth


class SpeakerAnalysisTests(unittest.TestCase):
    def test_two_voices_cluster_by_turn_with_name_hints(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            samples, truth = synthetic_project(root)
            with mock.patch('studio.agent.media.audio', return_value=samples):
                a = speakers.analyze(root, load(root), max_speakers=4, visual=False, log=lambda *_: None)
            self.assertEqual(a['k'], 2)
            labels = [r['cluster'] for r in a['segments']]
            mapping = {t: max(set(labels), key=lambda c: sum(1 for x, y in zip(labels, truth) if x == c and y == t)) for t in 'AB'}
            self.assertNotEqual(mapping['A'], mapping['B'])
            purity = np.mean([mapping[t] == c for c, t in zip(labels, truth)])
            self.assertGreaterEqual(purity, .95)
            names = {h['name']: h for h in a['name_hints']}
            self.assertEqual(names['Ada Lovelace']['cluster'], mapping['A'])
            self.assertEqual(names['Grace']['cluster'], mapping['B'])  # addressed -> next speaker
            self.assertTrue((root / speakers.ANALYSIS).is_file())

            # Links survive a re-run when the new cluster covers the same talk.
            p = load(root)
            tools.call(tools.Context(root), 'add_speaker', {'name': 'Ada Lovelace', 'cluster': mapping['A']}, log=lambda *_: None)
            with mock.patch('studio.agent.media.audio', return_value=samples):
                b = speakers.analyze(root, load(root), num_speakers=2, visual=False, log=lambda *_: None)
            self.assertIn('ada_lovelace', [c['speaker'] for c in b['clusters'].values()])

    def test_viterbi_removes_single_segment_flicker(self):
        truth = np.array([0] * 10 + [1] * 10)
        S = np.where(np.eye(2)[truth] > 0, .6, .4)
        S[4] = [.45, .55]  # one weak contrary segment inside a turn
        S[15] = [.55, .45]
        out = speakers.viterbi(S, np.full(20, 2.0), np.full(20, .2), np.ones(20, bool), .3)
        self.assertEqual(out.tolist(), truth.tolist())
        strong = speakers.viterbi(S, np.full(20, 2.0), np.full(20, .2), np.ones(20, bool), 0)
        self.assertEqual(strong[4], 1)  # without smoothing the local evidence wins

    def test_assign_split_and_interleaving(self):
        a = {'segments': [{'start': 0, 'end': 10, 'cluster': 'S1'}, {'start': 10, 'end': 12, 'cluster': 'S2'},
                          {'start': 12, 'end': 30, 'cluster': 'S1'}, {'start': 30, 'end': 50, 'cluster': 'S2'}],
             'clusters': {'S1': {'speaker': 'ann'}, 'S2': {'speaker': 'bob'}}}
        p = {'speakers': [{'id': 'ann'}, {'id': 'bob'}],
             'clips': [{'id': 'c1', 'start': 0, 'end': 30, 'speaker': None, 'reviewed': True, 'title': 'One'},
                       {'id': 'c2', 'start': 0, 'end': 50, 'speaker': None, 'reviewed': True, 'title': 'Two'}],
             'productions': [{'clips': ['c2']}]}
        rep = speakers.assign_clips(p, a)
        self.assertEqual([x['clip'] for x in rep['assigned']], ['c1'])
        self.assertEqual(p['clips'][0]['speaker'], 'ann')
        self.assertFalse(p['clips'][0]['reviewed'])
        self.assertEqual([x['clip'] for x in rep['mixed']], ['c2'])
        changes = speakers.split_clips(p, a, ['c2'], min_seconds=6)
        self.assertEqual(changes, {'c2': ['c2_a', 'c2_b']})  # the 2 s interjection folds into the first part
        parts = {c['id']: c for c in p['clips']}
        self.assertEqual((parts['c2_a']['start'], parts['c2_a']['end'], parts['c2_a']['speaker']), (0, 30, 'ann'))
        self.assertEqual((parts['c2_b']['start'], parts['c2_b']['end'], parts['c2_b']['speaker']), (30, 50, 'bob'))
        self.assertEqual(p['productions'][0]['clips'], ['c2_a', 'c2_b'])
        flicker = {'segments': [{'start': i * 3, 'end': i * 3 + 2.5, 'cluster': 'S1' if i % 2 else 'S2'} for i in range(10)], 'clusters': {}}
        self.assertEqual(speakers.interleaving(flicker)[0][:2], ('S1', 'S2'))


class ArtCheckTests(unittest.TestCase):
    def check(self, draw):
        with tempfile.TemporaryDirectory() as d:
            im = Image.new('RGB', (1024, 1536), 'white')
            draw(ImageDraw.Draw(im))
            f = Path(d) / 'art.png'
            im.save(f)
            return art.check(d, f)

    def test_flags_extra_figures_cropping_and_missing_face(self):
        two = self.check(lambda g: (g.rectangle([100, 200, 450, 1300], fill='black'), g.rectangle([560, 200, 900, 1300], fill='black')))
        self.assertFalse(two['ok'])
        self.assertTrue(any('separate large shapes' in e for e in two['errors']))
        cropped = self.check(lambda g: g.rectangle([300, 100, 700, 1535], fill='black'))
        self.assertTrue(any('bottom' in e for e in cropped['errors']))
        faceless = self.check(lambda g: g.rectangle([300, 100, 700, 1400], fill='black'))
        self.assertTrue(any('No face' in e for e in faceless['errors']))
        self.assertTrue(faceless['suggestions'])

    def test_brief_requires_reference_and_stages_uploads(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store(root, new())
            ctx = tools.Context(root)
            tools.call(ctx, 'add_speaker', {'name': 'Ada Lovelace', 'title': 'Analyst'}, log=lambda *_: None)
            with self.assertRaises(ValueError):
                tools.call(ctx, 'art_brief', {'speaker': 'ada_lovelace'}, log=lambda *_: None)
            photo = root / 'photo.png'
            Image.new('RGB', (400, 500), (180, 150, 120)).save(photo)
            tools.call(ctx, 'set_reference', {'speaker': 'ada_lovelace', 'path': str(photo)}, log=lambda *_: None)
            self.assertTrue((root / 'assets/ada_lovelace/reference.png').is_file())
            out = tools.call(ctx, 'art_brief', {'speaker': 'ada_lovelace', 'notes': 'Round glasses.'}, log=lambda *_: None)
            b = out['data']
            self.assertIn('Ada Lovelace, Analyst', b['prompt'])
            self.assertIn('Round glasses.', b['prompt'])
            self.assertTrue(all(Path(x).is_file() for x in b['upload']))
            self.assertTrue(Path(b['brief']).is_file())

    def test_gemini_adapter_parses_inline_image(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ref = root / 'ref.png'
            Image.new('RGB', (64, 64), 'gray').save(ref)
            buf = __import__('io').BytesIO()
            Image.new('RGB', (32, 48), 'white').save(buf, format='PNG')
            body = {'candidates': [{'content': {'parts': [{'text': 'here'}, {'inlineData': {'mimeType': 'image/png', 'data': __import__('base64').b64encode(buf.getvalue()).decode()}}]}}]}
            seen = {}

            class Reply:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return json.dumps(body).encode()

            def fake(req, timeout):
                seen['url'] = req.full_url
                seen['key'] = req.headers.get('X-goog-api-key')
                seen['body'] = json.loads(req.data)
                return Reply()
            with mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}), mock.patch('urllib.request.urlopen', fake):
                rel, said = art.gemini(root, {'id': 'ada'}, {}, 'draw', [ref], log=lambda *_: None)
            self.assertTrue((root / rel).is_file())
            self.assertEqual(said, 'here')
            self.assertIn(':generateContent', seen['url'])
            self.assertEqual(seen['key'], 'test-key')
            self.assertNotIn('test-key', seen['url'])  # key in header, never the URL
            self.assertEqual(seen['body']['contents'][0]['parts'][1]['inline_data']['mime_type'], 'image/png')


class ToolTests(unittest.TestCase):
    def test_arguments_validated_and_clip_production_flow(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store(root, new())
            ctx = tools.Context(root)
            quiet = lambda *_: None
            with self.assertRaisesRegex(ValueError, 'unknown argument'):
                tools.call(ctx, 'project_status', {'bogus': 1}, log=quiet)
            with self.assertRaisesRegex(ValueError, 'missing required'):
                tools.call(ctx, 'add_speaker', {}, log=quiet)
            with self.assertRaisesRegex(ValueError, 'variable NAME'):
                tools.call(ctx, 'configure', {'settings': {'gemini_key_env': 'sk-123secret'}}, log=quiet)
            tools.call(ctx, 'add_speaker', {'name': 'Ann'}, log=quiet)
            tools.call(ctx, 'update_clips', {'add': [{'start': 5, 'end': 20, 'title': 'Two', 'speaker': 'ann'},
                                                     {'start': 0, 'end': 4, 'title': 'One', 'speaker': 'ann'}]}, log=quiet)
            out = tools.call(ctx, 'create_production', {'name': 'Ann solo', 'speakers': ['ann'], 'for_speakers': True}, log=quiet)
            p = load(root)
            prod = p['productions'][0]
            self.assertEqual(out['data']['production'], 'ann_solo')
            self.assertEqual([next(c['title'] for c in p['clips'] if c['id'] == x) for x in prod['clips']], ['One', 'Two'])
            tools.call(ctx, 'update_production', {'production': 'ann_solo', 'actors': {'ann': {'x': 700, 'label': {'x': 80}}},
                                                  'scene': {'subtitles': {'size': 28}}}, log=quiet)
            prod = load(root)['productions'][0]
            self.assertEqual((prod['scene']['actors'][0]['x'], prod['scene']['actors'][0]['label']['x'], prod['scene']['subtitles']['size']), (700, 80, 28))
            with self.assertRaises(ValueError):
                tools.call(ctx, 'update_production', {'production': 'ann_solo', 'actors': {'ann': {'height': 5000}}}, log=quiet)
            tools.call(ctx, 'update_clips', {'remove': [prod['clips'][0]]}, log=quiet)
            self.assertEqual(len(load(root)['productions'][0]['clips']), 1)
            status = tools.call(ctx, 'project_status', {}, log=quiet)['text']
            self.assertIn('ann: Ann', status)
            self.assertIn('Next steps', status)
            self.assertTrue(all(t['schema']['type'] == 'object' for t in tools.TOOLS.values()))


class McpServerTests(unittest.TestCase):
    def test_stdio_handshake_tools_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            store(Path(d), new())
            proc = subprocess.Popen([sys.executable, str(ROOT / 'studio.py'), '--project', d, 'mcp'], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, 'STUDIO_AGENT_OFFLINE': '1'})
            msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}},
                    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'project_status', 'arguments': {}}},
                    {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'add_speaker', 'arguments': {}}},
                    {'jsonrpc': '2.0', 'id': 5, 'method': 'resources/read', 'params': {'uri': 'puppet-studio://guide'}},
                    {'jsonrpc': '2.0', 'id': 6, 'method': 'no/such'}]
            out, err = proc.communicate(''.join(json.dumps(m) + '\n' for m in msgs).encode(), timeout=60)
            replies = [json.loads(x) for x in out.decode('utf-8').splitlines()]  # stdout must be pure JSON-RPC
            byid = {r['id']: r for r in replies}
            self.assertEqual(sorted(byid), [1, 2, 3, 4, 5, 6])
            self.assertEqual(byid[1]['result']['protocolVersion'], '2025-03-26')
            self.assertIn('guide', byid[1]['result']['instructions'])
            names = {t['name'] for t in byid[2]['result']['tools']}
            self.assertTrue({'analyze_speakers', 'find_reference_frames', 'art_brief', 'import_artwork', 'render', 'wait_for_job'} <= names)
            self.assertFalse(byid[3]['result']['isError'])
            self.assertIn('Next steps', byid[3]['result']['content'][0]['text'])
            self.assertTrue(byid[4]['result']['isError'])
            self.assertIn('playbook', byid[5]['result']['contents'][0]['text'])
            self.assertEqual(byid[6]['error']['code'], -32601)


if __name__ == '__main__':
    unittest.main()
