"""Local media operations. Optional heavy imports stay inside workers."""
import math
import os
from pathlib import Path
import shutil
import sys
import wave
from core import ClipError, read, run, seconds

ROOT = Path(__file__).resolve().parents[1]


def runtime():
    return read(ROOT / 'runtime.json') if (ROOT / 'runtime.json').exists() else {}


def tool(name):
    configured = runtime().get(name)
    if configured:
        p = Path(configured)
        return str(p if p.is_absolute() else ROOT / p)
    return shutil.which(name) or name


def probe(path):
    import json
    return json.loads(run([tool('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], 120))


def validate_media(path, duration=None, video=True, size=None, full=False):
    """Validate streams, duration, A/V alignment and optionally decode every packet."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ClipError(f'Media file is missing or empty: {path.name}')
    try:
        payload = probe(path)
        streams = payload.get('streams', [])
        if not isinstance(streams, list):
            raise ClipError('ffprobe returned an invalid stream list')
        audio = [stream for stream in streams if isinstance(stream, dict) and stream.get('codec_type') == 'audio']
        videos = [stream for stream in streams if isinstance(stream, dict) and stream.get('codec_type') == 'video']
        actual_duration = seconds((payload.get('format') or {}).get('duration'))
    except ClipError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ClipError('ffprobe metadata is incomplete or invalid') from exc

    if actual_duration <= 0 or not audio or (video and not videos):
        raise ClipError('Media must contain a nonempty audio stream and the required video stream')
    if duration is not None and abs(actual_duration - duration) > max(.35, duration * .01):
        raise ClipError(f'Unexpected media duration: expected {duration:.3f}s, got {actual_duration:.3f}s')

    first_video = videos[0] if videos else None
    if size:
        if first_video is None or (int(first_video['width']), int(first_video['height'])) != tuple(size):
            raise ClipError('Unexpected video dimensions')

    if video:
        def track_range(stream):
            start_value = stream.get('start_time')
            duration_value = stream.get('duration')
            start = float(start_value) if start_value not in (None, 'N/A', '') else 0.0
            length = float(duration_value) if duration_value not in (None, 'N/A', '') else actual_duration
            if not math.isfinite(start) or not math.isfinite(length) or length <= 0:
                raise ClipError('Invalid audio/video stream timing')
            return start, start + length

        audio_range = track_range(audio[0])
        video_range = track_range(first_video)
        if abs(audio_range[0] - video_range[0]) > .25 or abs(audio_range[1] - video_range[1]) > .35:
            raise ClipError('Audio/video timeline mismatch')

    if full:
        maps = ['-map', '0:a:0']
        if video:
            maps += ['-map', '0:v:0']
        run([tool('ffmpeg'), '-v', 'error', '-xerror', '-i', str(path), *maps, '-f', 'null', '-'],
            max(120, actual_duration * 4))

    return dict(duration=actual_duration, bytes=path.stat().st_size,
                width=int(first_video['width']) if first_video else None,
                height=int(first_video['height']) if first_video else None,
                audio_streams=len(audio), video_streams=len(videos), full_decode=full)

def ytdlp(*args):
    cmd = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist', '--no-warnings',
           '--socket-timeout', '30', '--retries', '3', '--fragment-retries', '3',
           '--ffmpeg-location', str(Path(tool('ffmpeg')).parent)]
    if shutil.which('node'):
        cmd += ['--js-runtimes', 'node']
    return cmd + list(args)


def audio_peaks(path):
    import numpy as np
    db = []
    with wave.open(str(path)) as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise ClipError('Expected mono PCM16')
        while b := f.readframes(f.getframerate()):
            a = np.frombuffer(b, dtype='<i2').astype(np.float32)
            db.append(float(20 * np.log10(max(float(np.sqrt(np.mean(a * a))), 1) / 32768)))
    if not db:
        return []
    baseline = float(np.median(db))
    return [{'second': i, 'dbfs': round(v, 2), 'above_median_db': round(v - baseline, 2)}
            for i, v in enumerate(db) if v - baseline >= 8]


def face_cluster(samples, width, height, min_hits=3):
    """Count distinct sampled frames, rather than mixing all faces into one median."""
    import numpy as np
    clusters = []
    for frame, box in samples:
        center = np.array(box[:2]) + np.array(box[2:]) / 2
        match = next((c for c in clusters if np.linalg.norm(center - c['center']) < width * .08), None)
        if match is None:
            match = {'center': center, 'boxes': [], 'frames': set()}
            clusters.append(match)
        match['boxes'].append(box)
        match['frames'].add(frame)
        match['center'] = np.median([np.array(b[:2]) + np.array(b[2:]) / 2 for b in match['boxes']], axis=0)
    eligible = [c for c in clusters if len(c['frames']) >= min_hits]
    if not eligible:
        return None
    best = max(eligible, key=lambda c: (len(c['frames']), -float(c['center'][0])))
    box = np.median(best['boxes'], axis=0).tolist()
    box[0], box[1] = max(0, box[0]), max(0, box[1])
    box[2], box[3] = min(box[2], width - box[0]), min(box[3], height - box[1])
    return {'box': box, 'hits': len(best['frames']), 'clusters': len(eligible)}


def faces(path, cfg):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        w, h, n = [int(cap.get(x)) for x in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT, cv2.CAP_PROP_FRAME_COUNT)]
        if min(w, h, n) <= 0:
            raise ClipError('Cannot read video for face detection')
        if cfg.get('camera_box'):
            x, y, cw, ch = cfg['camera_box']
            if x < 0 or y < 0 or cw <= 0 or ch <= 0 or x + cw > w or y + ch > h:
                raise ClipError('Manual camera box outside video')
            return dict(box=[x, y, cw, ch], method='manual', frame=[w, h])
        model = runtime().get('face_model')
        if not model:
            return dict(box=None, method='unavailable', reason='YuNet model not configured', frame=[w, h])
        model = str(ROOT / model) if not Path(model).is_absolute() else model
        scale = min(1., 960 / w)
        sw, sh = int(w * scale), int(h * scale)
        detector = cv2.FaceDetectorYN.create(model, '', (sw, sh), cfg['face_threshold'])
        samples = []
        for k in range(cfg['face_samples']):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(n - 1, int(n * (k + .5) / cfg['face_samples'])))
            ok, frame = cap.read()
            if not ok:
                continue
            _, found = detector.detect(cv2.resize(frame, (sw, sh)))
            for row in found if found is not None else []:
                if row[14] >= cfg['face_threshold'] and row[3] / scale >= h * .03:
                    samples.append((k, [float(x / scale) for x in row[:4]]))
        result = face_cluster(samples, w, h, cfg['face_min_hits'])
        return dict(result or {'box': None, 'hits': 0}, method='yunet', samples=cfg['face_samples'], frame=[w, h])
    finally:
        cap.release()


def ass_time(t):
    centis = int(round(max(0, t) * 100))
    return f'{centis // 360000}:{centis // 6000 % 60:02}:{centis // 100 % 60:02}.{centis % 100:02}'


def clean_text(t):
    return t.replace('\\', '/').replace('{', '(').replace('}', ')').replace('\r', ' ').replace('\n', ' ')


def captions(path, words, title, duration, width, height, cfg):
    size = max(16, round(width * cfg['subtitle_size']))
    lines = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {width}', f'PlayResY: {height}', 'WrapStyle: 0',
             '[V4+ Styles]', 'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             f'Style: Main,Arial,{size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,1,2,20,20,{int(height * cfg["subtitle_y"])},1',
             '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    if cfg['title_overlay']:
        lines += [f'Dialogue: 1,0:00:00.00,{ass_time(duration)},Main,,0,0,0,,{{\\an8\\pos({width//2},{int(height*.06)})}}{clean_text(title)}']
    if cfg['subtitles']:
        for word in words:
            s, e = max(0, word['start']), min(duration, word['end'])
            if s < e:
                lines.append(f'Dialogue: 0,{ass_time(s)},{ass_time(e)},Main,,0,0,0,,{clean_text(word["word"])}')
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')


def compose(width, height, camera, cfg):
    box = camera.get('box') if cfg['layout'] == 'camera-top' else None
    if box:
        w, h = camera['frame']
        x, y, fw, fh = box
        ch = int(height * cfg['camera_fraction']) // 2 * 2
        if camera['method'] != 'manual':
            cw = min(w, max(fw * 3.2, 100))
            crop_h = min(h, cw * ch / width)
            cw = crop_h * width / ch
            x, y = min(max(x + fw/2 - cw/2, 0), w-cw), min(max(y + fh*.65 - crop_h/2, 0), h-crop_h)
            fw, fh = cw, crop_h
        vals = [max(2 if i > 1 else 0, int(v)//2*2) for i, v in enumerate((x,y,fw,fh))]
        x, y, fw, fh = vals
        gx = cfg['game_position']
        return (f'[0:v]split=2[c][g];[c]crop={fw}:{fh}:{x}:{y},scale={width}:{ch}:force_original_aspect_ratio=increase,crop={width}:{ch},setsar=1[cam];'
                f'[g]scale={width}:{height-ch}:force_original_aspect_ratio=increase,crop={width}:{height-ch}:(iw-ow)*{gx}:(ih-oh)/2,setsar=1[game];'
                '[cam][game]vstack=inputs=2,format=yuv420p,ass=captions.ass[v]')
    return (f'[0:v]split=2[b][f];[b]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=15:2[bg];'
            f'[f]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p,ass=captions.ass[v]')
