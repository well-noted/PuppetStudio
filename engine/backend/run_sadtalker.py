#!/usr/bin/env python3
"""Run an explicit SadTalker checkout in its own environment; record exact output."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True)
    p.add_argument('--python', required=True, help='Absolute path to SadTalker environment python')
    p.add_argument('--image', required=True); p.add_argument('--audio', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--enhancer', choices=['none', 'gfpgan', 'RestoreFormer'], default='none')
    p.add_argument('--preprocess', choices=['full', 'crop', 'extcrop', 'resize', 'extfull'], default='full')
    p.add_argument('--size', choices=[256, 512], type=int, default=512)
    p.add_argument('--expression-scale', type=float, default=1.0)
    p.add_argument('--batch-size',type=int,default=1)
    p.add_argument('--landmark-hints',type=Path)
    a = p.parse_args()
    repo = Path(a.repo).resolve()
    image, audio = Path(a.image).resolve(), Path(a.audio).resolve()
    python = Path(a.python).resolve()
    for item in [repo / 'inference.py', image, audio, python]:
        if not item.is_file():
            p.error(f'Missing file: {item}')
    root = Path(a.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run = root / ('run_' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                  + '_' + uuid.uuid4().hex[:8])
    run.mkdir()
    help_result = subprocess.run([str(python), 'inference.py', '--help'], cwd=repo,
                                 text=True, capture_output=True, check=True)
    for option in ['--verbose', '--still', '--preprocess', '--size','--batch_size']:
        if option not in help_result.stdout:
            p.error(f'This checkout lacks {option}; inspect its CLI before running.')
    cmd = [str(python), 'inference.py', '--source_image', str(image), '--driven_audio', str(audio),
           '--result_dir', str(run), '--checkpoint_dir', str(repo / 'checkpoints'),
           '--preprocess', a.preprocess, '--size', str(a.size), '--expression_scale',
           str(a.expression_scale), '--still', '--verbose','--batch_size',str(a.batch_size)]
    if a.enhancer != 'none':
        cmd += ['--enhancer', a.enhancer]
    if a.landmark_hints:
        helper=Path(__file__).resolve().parent/'sadtalker_landmarks.py'
        landmarks=run/'source_landmarks.json'
        preflight_log=run/'landmark_preflight.log'
        with preflight_log.open('wb') as f:
            preflight=subprocess.run([str(python),str(helper),'--repo',str(repo),'--image',str(image),
                '--hints',str(a.landmark_hints.resolve()),'--output',str(landmarks)],cwd=repo,stdout=f,stderr=subprocess.STDOUT)
        print(preflight_log.read_text(encoding='utf-8',errors='replace')[-8000:],flush=True)
        if preflight.returncode:raise RuntimeError('Illustration landmark preflight failed; see '+str(preflight_log))
        cmd=[str(python),str(Path(__file__).resolve().parent/'sadtalker_source_bootstrap.py'),
            '--repo',str(repo),'--landmarks',str(landmarks),*cmd[2:]]
    # Native process failures are checked; no "newest folder" or arbitrary first MP4.
    log = run / 'inference.log'
    with log.open('wb') as f:
        result = subprocess.run(cmd, cwd=repo, stdout=f, stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text(encoding='utf-8',errors='replace')[-12000:],flush=True)
        raise RuntimeError(f'SadTalker failed ({result.returncode}); see {log}')
    # Upstream inference.py moves its final output beside the timestamp directory.
    candidates = sorted(run.glob('*.mp4'))
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one top-level final MP4, found {len(candidates)} in {run}. '
                           'Inspect inference.log; do not silently choose an intermediate.')
    output = candidates[0]
    version = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                             capture_output=True, text=True) if shutil.which('git') else None
    probe = None
    if shutil.which('ffprobe'):
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                                    '-show_format', '-of', 'json', str(output)], text=True))
    report = {'output': str(output), 'run_directory': str(run), 'command': cmd,
              'repo_commit': version.stdout.strip() if version and version.returncode == 0 else None,
              'enhancer': a.enhancer, 'preprocess': a.preprocess, 'probe': probe}
    (run / 'run.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(str(output))
    print(f'Run provenance: {run / "run.json"}')


if __name__ == '__main__':
    main()
