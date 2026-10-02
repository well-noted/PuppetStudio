"""Prepare a same-canvas gesture locally without changing protected pixels."""
import argparse,json
from pathlib import Path
from PIL import Image
from studio.gesture_prepare import composite,DEFAULT_REGION

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--neutral',type=Path,required=True);p.add_argument('--pose',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--mask',type=Path);p.add_argument('--region',type=float,nargs=4,default=DEFAULT_REGION,metavar=('LEFT','TOP','RIGHT','BOTTOM'));p.add_argument('--feather',type=float,default=8);a=p.parse_args()
 for source in [a.neutral,a.pose,a.mask]:
  if source and a.out.resolve()==source.resolve():p.error('Output must be a new file; sources stay unchanged')
 if a.out.suffix.lower()!='.png':p.error('Use a .png output to preserve alpha')
 output,report=composite(Image.open(a.neutral),Image.open(a.pose),a.region,a.feather,Image.open(a.mask) if a.mask else None);a.out.parent.mkdir(parents=True,exist_ok=True);output.save(a.out);a.out.with_suffix('.report.json').write_text(json.dumps(report,indent=2)+'\n');print('Saved '+str(a.out)+'; protected pixels changed: '+str(report['protected_changed_pixels'])+'. Review before importing.')
if __name__=='__main__':main()
