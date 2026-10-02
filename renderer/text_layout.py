"""Portable font selection and caption wrapping."""
import os
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

def find_font(requested=None):
    candidates=[requested] if requested else []
    candidates += [Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arial.ttf',
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/System/Library/Fonts/Supplemental/Arial.ttf')]
    for p in candidates:
        if p and Path(p).is_file():return str(p)
    raise ValueError('No suitable font found. Set "font" to a TTF file in the job.')

def wrap_lines(text,font,max_width):
    draw=ImageDraw.Draw(Image.new('RGB',(1,1)));lines=[];line=''
    for word in text.split():
        candidate=(line+' '+word).strip()
        if draw.textlength(candidate,font=font)>max_width and line:lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    return lines
