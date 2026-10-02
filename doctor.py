"""Read-only package and selected model-environment diagnostics."""
import argparse
import sys
from pathlib import Path
from studio.core import load,new
from studio.diagnostics import check

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path(__file__).parent/'projects/my_project')
    p.add_argument('--model',action='store_true',help='Also test the selected CUDA Python and SadTalker imports; no inference.')
    a=p.parse_args();root=a.project.resolve();project=load(root) if (root/'project.json').exists() else new()
    report=check(root,project,a.model,log=lambda message:print(message,flush=True))
    print('Report:',root/'work/setup_report.json')
    return 1 if report['errors'] else 0

if __name__=='__main__':sys.exit(main())
