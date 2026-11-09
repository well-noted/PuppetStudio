"""Frame/audio extraction and image helpers shared by the agent tools."""
import base64
import io
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def video_info(file):
    data = json.loads(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(file)]))
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
    info = {'duration': float(data['format'].get('duration', 0)), 'video': video is not None}
    if video:
        info.update(width=int(video['width']), height=int(video['height']))
    return info


def frame(file, seconds, max_width=None):
    """One RGB frame as a PIL image (fast keyframe seek, then accurate decode)."""
    scale = ['-vf', f'scale=min({int(max_width)}\\,iw):-2'] if max_width else []
    raw = subprocess.run(
        ['ffmpeg', '-v', 'error', '-ss', f'{max(0.0, float(seconds)):.3f}', '-i', str(file),
         '-frames:v', '1', *scale, '-f', 'image2pipe', '-vcodec', 'png', '-'],
        capture_output=True, check=True).stdout
    if not raw:
        raise ValueError(f'No video frame at {seconds:.2f}s')
    return Image.open(io.BytesIO(raw)).convert('RGB')


def frame_burst(file, seconds, duration, fps, width, height):
    """Several consecutive frames as an (n, h, w, 3) uint8 array, scaled to width x height."""
    raw = subprocess.run(
        ['ffmpeg', '-v', 'error', '-ss', f'{max(0.0, float(seconds)):.3f}', '-i', str(file),
         '-t', f'{duration:.3f}', '-vf', f'fps={fps},scale={width}:{height}',
         '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        capture_output=True, check=True).stdout
    n = len(raw) // (width * height * 3)
    return np.frombuffer(raw[:n * width * height * 3], np.uint8).reshape(n, height, width, 3)


def audio(file, rate=16000):
    """Mono float32 samples of the whole file."""
    raw = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', str(file), '-vn', '-ac', '1', '-ar', str(rate),
         '-f', 's16le', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def font(size):
    for name in ['arial.ttf', 'DejaVuSans.ttf', 'Arial.ttf']:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def label(image, text, size=18):
    """Draw a readable caption tag in the top-right corner (in place).

    Top-right keeps the tag off name labels (top-left) and subtitles (bottom).
    """
    draw = ImageDraw.Draw(image)
    f = font(size)
    box = draw.textbbox((0, 0), text, font=f)
    x = max(0, image.width - box[2] - 10)
    draw.rectangle([x, 0, image.width, box[3] + 8], fill=(0, 0, 0))
    draw.text((x + 5, 3), text, fill=(255, 255, 0), font=f)
    return image


def sheet(images, captions=None, columns=None, cell_width=320, background=(32, 32, 32)):
    """Contact sheet of PIL images, each scaled to cell_width, with optional captions."""
    if not images:
        raise ValueError('Nothing to show')
    columns = columns or min(4, len(images))
    cells = []
    for i, im in enumerate(images):
        im = im.convert('RGB')
        im = im.resize((cell_width, max(1, round(im.height * cell_width / im.width))), Image.Resampling.LANCZOS)
        if captions and captions[i]:
            label(im, str(captions[i]), 16 if cell_width < 400 else 20)
        cells.append(im)
    row_heights = [max(c.height for c in cells[r:r + columns]) for r in range(0, len(cells), columns)]
    out = Image.new('RGB', (columns * cell_width + (columns + 1) * 4, sum(row_heights) + (len(row_heights) + 1) * 4), background)
    y = 4
    for r, h in enumerate(row_heights):
        for c, cell in enumerate(cells[r * columns:(r + 1) * columns]):
            out.paste(cell, (4 + c * (cell_width + 4), y))
        y += h + 4
    return out


def encode(image, max_side=1400, quality=85):
    """Return (base64, mime) for an MCP image block, bounded for token cost."""
    im = image.convert('RGB') if image.mode not in ['RGB', 'L'] else image
    if max(im.size) > max_side:
        k = max_side / max(im.size)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format='JPEG', quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), 'image/jpeg'


def on_white(path_or_image):
    """Flatten RGBA artwork on white for display."""
    im = Image.open(path_or_image) if isinstance(path_or_image, (str, Path)) else path_or_image
    im = im.convert('RGBA')
    bg = Image.new('RGBA', im.size, 'white')
    bg.alpha_composite(im)
    return bg.convert('RGB')
