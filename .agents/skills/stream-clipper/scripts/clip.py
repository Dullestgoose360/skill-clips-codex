#!/usr/bin/env python3
"""Portable CLI; editorial choices stay with the agent and the user."""
import argparse
from difflib import SequenceMatcher
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import time
from core import ClipError, atomic, event, lock, read, run
import config
import pipeline as flow
from media import ROOT, runtime, tool, ytdlp


def doctor():
    packages={}
    for name in ('faster-whisper','ctranslate2','opencv-python-headless','numpy','yt-dlp','psutil'):
        try:
            packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name]=None
    binaries={}
    for name in ('ffmpeg','ffprobe'):
        try:
            binaries[name]=run([tool(name),'-version'],15).splitlines()[0]
        except Exception as e:
            binaries[name]=dict(error=type(e).__name__)
    try:
        import ctranslate2
        gpu=ctranslate2.get_cuda_device_count()
    except Exception:
        gpu=None
    return dict(skill=str(ROOT),cwd=str(Path.cwd()),user_home=str(Path.home()),python=sys.executable,
                python_version=sys.version.split()[0],packages=packages,binaries=binaries,cuda_devices=gpu,
                cuda_note='Detection is not a successful transcription; use benchmark',runtime=runtime())



def summarize_benchmark(results):
    """Summarize repeated CPU/CUDA observations without hiding failed runs."""
    summary = {}
    for device in ('cpu', 'cuda'):
        successful = [item for item in results if item['device'] == device and item['status'] == 'complete']
        failed = [item for item in results if item['device'] == device and item['status'] != 'complete']
        summary[device] = dict(successes=len(successful), failures=len(failed))
        for field in ('load_seconds', 'transcribe_seconds', 'wall_seconds'):
            values = [float(item[field]) for item in successful if item.get(field) is not None]
            summary[device]['median_' + field] = round(statistics.median(values), 4) if values else None
        for field in ('rss_bytes', 'vram_total_mib', 'vram_baseline_mib'):
            values = [float(item['resources'][field]) for item in successful
                      if item.get('resources', {}).get(field) is not None]
            summary[device]['median_' + field] = round(statistics.median(values), 2) if values else None
        deltas = []
        for item in successful:
            resource = item.get('resources') or {}
            if resource.get('vram_total_mib') is not None and resource.get('vram_baseline_mib') is not None:
                deltas.append(max(0, resource['vram_total_mib'] - resource['vram_baseline_mib']))
        summary[device]['median_vram_delta_mib'] = round(statistics.median(deltas), 2) if deltas else None

    cpu = summary['cpu']['median_transcribe_seconds']
    cuda = summary['cuda']['median_transcribe_seconds']
    summary['cuda_speedup_vs_cpu'] = round(cpu / cuda, 3) if cpu and cuda and cuda > 0 else None
    similarities = []
    for repetition in sorted({item['repetition'] for item in results}):
        cpu_runs = [item for item in results if item['device'] == 'cpu' and item['repetition'] == repetition and item['status'] == 'complete']
        cuda_runs = [item for item in results if item['device'] == 'cuda' and item['repetition'] == repetition and item['status'] == 'complete']
        if cpu_runs and cuda_runs:
            left = ' '.join(cpu_runs[0].get('transcript', '').split()).casefold()
            right = ' '.join(cuda_runs[0].get('transcript', '').split()).casefold()
            if left or right:
                similarities.append(SequenceMatcher(None, left, right).ratio())
    summary['cpu_cuda_transcript_similarity'] = round(statistics.mean(similarities), 4) if similarities else None
    summary['transcript_similarity_note'] = 'Consistency proxy only; not WER/CER and not a human accuracy assessment.'
    return summary

def main():
    parser=argparse.ArgumentParser(description='Stream Clipper: authorized sources, reviewed candidates, local export')
    parser.add_argument('--home',type=Path,default=Path(os.environ.get('STREAM_CLIPPER_HOME',Path.home()/'stream-clipper')))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor'); sub.add_parser('config')
    a=sub.add_parser('discover'); a.add_argument('--config',required=True)
    a=sub.add_parser('inspect'); a.add_argument('source')
    for command in ('authorize','allow-full'):
        a=sub.add_parser(command); a.add_argument('source_id'); a.add_argument('--confirmation',required=True)
    for command in ('prepare','benchmark'):
        a=sub.add_parser(command); a.add_argument('source_id'); a.add_argument('--config')
        if command=='benchmark':
            a.add_argument('--seconds',type=float,default=30); a.add_argument('--repeats',type=int,default=2)
    a=sub.add_parser('import-analysis'); a.add_argument('source_id'); a.add_argument('--block',type=int,required=True); a.add_argument('--file',required=True)
    a=sub.add_parser('approve'); a.add_argument('source_id'); a.add_argument('--ids',nargs='+',required=True); a.add_argument('--confirmation',required=True)
    for command in ('preview','render'):
        a=sub.add_parser(command); a.add_argument('source_id'); a.add_argument('--ids',nargs='+',required=True)
    for command in ('review','plan-full','recover-lock','cleanup-plan','cleanup'):
        a=sub.add_parser(command); a.add_argument('source_id')
        if command=='cleanup': a.add_argument('--confirmation',required=True)
    sub.add_parser('status')
    args=parser.parse_args()
    if args.command=='doctor': return doctor()
    if args.command=='config': return config.load()
    if args.command=='discover':
        cfg=config.load(args.config)
        if cfg['platform']!='youtube':
            raise ClipError('Use public platform discovery or direct links for Twitch/Kick; automated search not implemented')
        terms=' '.join([cfg['topic'],cfg['subject'],cfg['creator'],*cfg['keywords']]).strip()
        if not terms: raise ClipError('Configure topic/subject/creator/keywords')
        data=json.loads(run(ytdlp('--flat-playlist','--skip-download','-J',f'ytsearch{cfg["video_count"]}:{terms}'),180))
        return [dict(title=v.get('title'),creator=v.get('channel') or v.get('uploader'),url=v.get('url'),duration=v.get('duration'),date=v.get('upload_date')) for v in data.get('entries',[])]
    if args.command=='inspect': return flow.inspect(args.home,args.source)
    if args.command=='status':
        result=[]
        for p in (args.home/'sources').glob('*'):
            if not (p/'source.json').exists(): continue
            item=dict(source=read(p/'source.json'),locked=(p/'.lock').exists())
            if (p/'active.json').exists():
                base=p/'generations'/read(p/'active.json')['generation']
                item.update(transcribed=len(list(base.glob('blocks/*/transcript.state.json'))),analyzed=len(list(base.glob('blocks/*/analysis.json'))))
            result.append(item)
        return result
    p=flow.folder(args.home,args.source_id)
    if args.command=='recover-lock':
        import psutil
        pid=int((p/'.lock').read_text())
        if psutil.pid_exists(pid): raise ClipError('Lock owner still exists; do not steal it')
        (p/'.lock').unlink()
        return dict(recovered=True)
    with lock(p):
        if args.command=='authorize': return flow.authorize(p,args.confirmation)
        if args.command=='prepare': return flow.prepare(p,config.load(args.config))
        if args.command=='plan-full': return flow.plan_full(p)
        if args.command=='allow-full': return flow.allow_full(p,args.confirmation)
        if args.command=='import-analysis': return flow.import_analysis(p,args.block,args.file)
        if args.command=='review': return flow.review(p)
        if args.command=='approve': return flow.approve(p,args.ids,args.confirmation)
        if args.command in ('render','preview'): return flow.render(p,args.ids,args.command=='preview')
        if args.command=='benchmark':
            meta=flow.authorized(p); cfg=config.load(args.config)
            if not 1<=args.seconds<=120 or not 1<=args.repeats<=5:
                raise ClipError('Benchmark requires 1–120 seconds and 1–5 repetitions')
            sample_seconds=min(args.seconds,meta['duration'])
            audio=flow.section(p,meta,cfg,0,sample_seconds)
            results=[]
            for repetition in range(args.repeats):
                for dev in ('cpu','cuda'):
                    try:
                        trans=flow.speech(p,audio,cfg,dev)
                        result={key:trans[key] for key in ('device','compute_type','load_seconds','transcribe_seconds','wall_seconds','resources')}
                        result.update(status='complete',repetition=repetition,
                                      transcript=' '.join(segment['text'] for segment in trans['segments']))
                    except Exception as exc:
                        result=dict(device=dev,status='failed',error=type(exc).__name__,repetition=repetition)
                    results.append(result)
                    event(p,'benchmark',result['status'],device=dev,repetition=repetition)
            summary=summarize_benchmark(results)
            destination=p/('benchmark-'+str(time.time_ns())+'.json')
            atomic(destination,dict(schema_version=2,source=meta['id'],seconds=sample_seconds,config=cfg,
                                    order='CPU int8 then CUDA float16 in each repetition; each sample uses an isolated worker process',
                                    results=results,summary=summary,
                                    measurement='RSS includes worker process tree. VRAM is total device use sampled periodically, not isolated per process; other applications contribute. Transcript similarity is a consistency proxy, not WER/CER.'))
            return dict(path=str(destination),seconds=sample_seconds,summary=summary,results=results)
        if args.command=='cleanup-plan':
            flow.authorized(p)
            # Only disposable worker/chat intermediates. Never source cache, generations, previews or finals.
            paths=[str(x.resolve()) for x in (p/'tmp').glob('*') if x.is_dir() and not x.is_symlink()]
            protected=set()
            if (p/'full-source.json').exists(): protected.add(str(Path(read(p/'full-source.json')['path']).parent.resolve()))
            paths=[x for x in paths if x not in protected]
            atomic(p/'cleanup-plan.json',paths)
            return paths
        if args.command=='cleanup':
            flow.authorized(p)
            if args.confirmation!='DELETE LISTED TEMPORARIES': raise ClipError('Review cleanup-plan and use its explicit confirmation phrase')
            paths=read(p/'cleanup-plan.json'); root=(p/'tmp').resolve()
            protected=Path(read(p/'full-source.json')['path']).parent.resolve() if (p/'full-source.json').exists() else None
            for raw in paths:
                target=Path(raw)
                if target.is_symlink() or target.resolve().parent!=root or target.resolve()==protected: raise ClipError('Unsafe cleanup path')
            for raw in paths: shutil.rmtree(raw)
            return dict(removed=paths)


if __name__=='__main__':
    try:
        result=main()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ClipError,FileNotFoundError,KeyError,json.JSONDecodeError) as e:
        print(json.dumps(dict(status='error',message=str(e)),ensure_ascii=False),file=sys.stderr)
        sys.exit(2)
