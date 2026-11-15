"""Isolated transcription worker: a CUDA native crash cannot kill the coordinator."""
import os
from pathlib import Path
import sys
import threading
import time
from core import atomic, read
from media import ROOT, runtime


def transcribe(request):
    cfg = request['config']
    rt = runtime()
    handles = []
    for directory in rt.get('cuda_dirs', []):
        directory = str(ROOT / directory) if not Path(directory).is_absolute() else directory
        if os.name == 'nt':
            handles.append(os.add_dll_directory(directory))
        os.environ['PATH'] = directory + os.pathsep + os.environ.get('PATH', '')
    import psutil
    from faster_whisper import WhisperModel
    peak = {'rss_bytes': 0, 'vram_total_mib': None, 'vram_baseline_mib': None}
    stop = threading.Event()
    def sample():
        from core import run
        proc = psutil.Process()
        tick = 0
        while not stop.is_set():
            try:
                peak['rss_bytes'] = max(peak['rss_bytes'], sum(p.memory_info().rss for p in [proc, *proc.children(recursive=True)] if p.is_running()))
                if tick % 5 == 0:
                    v = int(run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'], 5).splitlines()[0])
                    if peak['vram_baseline_mib'] is None:
                        peak['vram_baseline_mib'] = v
                    peak['vram_total_mib'] = max(peak['vram_total_mib'] or 0, v)
            except Exception:
                pass
            tick += 1
            stop.wait(.2)
    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    start = time.perf_counter()
    cache = rt.get('model_cache', '.runtime/models')
    cache = str(ROOT / cache) if not Path(cache).is_absolute() else cache
    try:
        device = request['device']
        model = WhisperModel(cfg['model'], device=device, compute_type='int8' if device=='cpu' else 'float16',
                             cpu_threads=cfg['cpu_threads'], download_root=cache,
                             local_files_only=not cfg['allow_model_download'])
        loaded = time.perf_counter()
        segments, info = model.transcribe(request['audio'], language=cfg['language'], word_timestamps=True,
                                          vad_filter=True, beam_size=1, condition_on_previous_text=False)
        out = []
        for s in segments:
            out.append(dict(start=s.start, end=s.end, text=s.text.strip(), words=[dict(start=w.start,end=w.end,word=w.word.strip()) for w in s.words or []]))
        return dict(language=info.language, segments=out, device=device, compute_type='int8' if device=='cpu' else 'float16',
                    load_seconds=loaded-start, transcribe_seconds=time.perf_counter()-loaded,
                    wall_seconds=time.perf_counter()-start, resources=peak)
    finally:
        stop.set()
        thread.join(timeout=6)


if __name__ == '__main__':
    try:
        atomic(sys.argv[2], transcribe(read(sys.argv[1])))
    except Exception as e:
        # Do not print arbitrary model/downloader exceptions that may contain credentials.
        print(type(e).__name__, file=sys.stderr)
        sys.exit(1)
