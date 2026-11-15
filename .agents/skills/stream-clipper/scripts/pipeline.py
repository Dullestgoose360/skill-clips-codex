import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.parse import urlparse
import uuid
from core import ClipError, atomic, candidates, checkpoint, digest, event, file_hash, interval, lock, read, run, seconds, select, source_id
import config
from media import ROOT, audio_peaks, captions, compose, faces, probe, runtime, tool, validate_media, ytdlp


def folder(home, sid):
    if not re.fullmatch(r'[a-z0-9_-]+-[a-f0-9]{24}', sid):
        raise ClipError('Use the exact source ID from inspect; partial paths are not accepted')
    return Path(home).resolve() / 'sources' / sid


def metadata(source):
    p = Path(source)
    if p.is_file():
        p = p.resolve()
        info = probe(p)
        h = file_hash(p)
        return dict(id=source_id('local', h), platform='local', creator='local file', title=p.stem,
                    url=str(p), duration=seconds(info['format']['duration']), date=None,
                    content_hash=h, size=p.stat().st_size)
    u = urlparse(source)
    host = (u.hostname or '').lower()
    if u.scheme != 'https' or u.username or u.password or not any(host == d or host.endswith('.'+d) for d in ['youtube.com','youtu.be','twitch.tv','kick.com']):
        raise ClipError('Expected a public HTTPS YouTube/Twitch/Kick URL or existing local file')
    raw = json.loads(run(ytdlp('--skip-download', '-J', source), 180))
    if raw.get('is_live') or raw.get('live_status') in ('is_live','is_upcoming'):
        raise ClipError('Use an ended, finite VOD')
    platform = 'youtube' if host.endswith('youtube.com') or host=='youtu.be' else 'twitch' if host.endswith('twitch.tv') else 'kick'
    if not raw.get('id') or not raw.get('duration'):
        raise ClipError('Missing stable ID or finite duration')
    formats = [dict(bytes=f.get('filesize') or f.get('filesize_approx'), tbr=f.get('tbr'), height=f.get('height'), audio=f.get('vcodec')=='none') for f in raw.get('formats',[]) if (f.get('height') or 0)<=1080]
    return dict(id=source_id(platform,raw['id']), platform=platform, platform_id=raw['id'],
                creator=raw.get('channel') or raw.get('uploader'), title=raw.get('title'),
                url=raw.get('webpage_url') or source, duration=seconds(raw['duration']),
                date=raw.get('upload_date') or raw.get('release_date'), formats=formats)


def inspect(home, source):
    meta = metadata(source)
    p = folder(home, meta['id'])
    with lock(p):
        if (p/'source.json').exists():
            previous = read(p/'source.json')
            if previous != meta:
                atomic(p/('source.'+uuid.uuid4().hex+'.previous.json'), previous)
        atomic(p/'source.json', meta)
    return meta


def authorize(p, confirmation):
    if not confirmation.strip():
        raise ClipError('Explicit user confirmation required')
    meta = read(p/'source.json')
    atomic(p/'authorization.json', dict(source_hash=digest(meta), confirmation=confirmation, time=time.time()))


def authorized(p):
    meta = read(p/'source.json')
    if not (p/'authorization.json').exists() or read(p/'authorization.json')['source_hash'] != digest(meta):
        raise ClipError('Source authorization missing or stale; show metadata and ask user')
    if meta['platform']=='local' and file_hash(meta['url']) != meta['content_hash']:
        raise ClipError('Local source changed; inspect and authorize again')
    return meta


def plan_full(p):
    meta = authorized(p)
    cfg = read(p/'config.json') if (p/'config.json').exists() else config.load()
    estimates = [f['bytes'] or ((f['tbr'] or 0)*1000/8*meta['duration']) for f in meta.get('formats',[])]
    estimate = math.ceil(max(estimates)*1.5) if estimates and max(estimates)>0 else None
    free = shutil.disk_usage(p).free
    plan = dict(source_hash=digest(meta), estimated_bytes=estimate, free_bytes=free,
                required_with_working_margin=estimate*3 if estimate else None,
                high_consumption=estimate is None or estimate>cfg['large_download_gb']*1024**3,
                insufficient=estimate is not None and estimate*3>free,
                note='Conservative format estimate, not a network guarantee; unknown size requires explicit approval.')
    atomic(p/'full-plan.json',plan)
    return plan


def allow_full(p, confirmation):
    plan = read(p/'full-plan.json')
    if plan['source_hash'] != digest(authorized(p)) or plan['insufficient'] or not confirmation.strip():
        raise ClipError('Cannot approve stale plan or insufficient space')
    atomic(p/'full-approval.json',dict(plan_hash=digest(plan), confirmation=confirmation))


def full_source(p, meta, cfg):
    if not (p/'full-plan.json').exists() or not (p/'full-approval.json').exists():
        raise ClipError('Section download failed. Run plan-full and obtain explicit approval before fallback')
    plan = read(p/'full-plan.json')
    if read(p/'full-approval.json')['plan_hash'] != digest(plan) or plan['source_hash'] != digest(meta):
        raise ClipError('Full download approval stale')
    if plan['required_with_working_margin'] and shutil.disk_usage(p).free < plan['required_with_working_margin']:
        raise ClipError('Insufficient disk space')
    def produce():
        stage=p/'tmp'/uuid.uuid4().hex
        stage.mkdir(parents=True)
        out=stage/'full.mkv'
        run(ytdlp('-f','bv*[height<=1080]+ba/b[height<=1080]','--merge-output-format','mkv','--remux-video','mkv','-o',str(out),meta['url']),cfg['timeout'])
        validate_media(out,meta['duration'])
        return dict(path=str(out),hash=file_hash(out))
    record, _ = checkpoint(p,'full-source',digest(meta),produce)
    if not Path(record['path']).is_file() or file_hash(record['path'])!=record['hash']:
        raise ClipError('Full source cache corrupt; preserve files and re-inspect')
    return record['path']


def section(p, meta, cfg, start, end, audio=True):
    interval(start,end,meta['duration'])
    cache = p/'cache'/digest([digest(meta),start,end,audio])[:24]
    cache.mkdir(parents=True,exist_ok=True)
    receipt=cache/'receipt.json'
    if receipt.exists():
        r=read(receipt)
        target=Path(r['path'])
        if target.exists() and file_hash(target)==r['hash']:
            validate_media(target,end-start,video=not audio)
            return target
    stage=cache/uuid.uuid4().hex
    stage.mkdir()
    target=stage/('audio.wav' if audio else 'section.mp4')
    local = meta['url'] if meta['platform']=='local' else None
    if not local:
        download=stage/'download.mkv'
        try:
            run(ytdlp('-f','ba' if audio else 'bv*[height<=1080]+ba/b[height<=1080]',
                      '--download-sections',f'*{start:.3f}-{end:.3f}','--force-keyframes-at-cuts',
                      '--merge-output-format','mkv','--remux-video','mkv','-o',str(download),meta['url']),cfg['timeout'])
            # yt-dlp audio-only container may retain original extension.
            files=[x for x in stage.glob('download.*') if x.suffix not in ('.part','.ytdl')]
            if len(files)!=1:
                raise ClipError('Section output missing or ambiguous')
            validate_media(files[0],end-start,video=not audio)
            local=files[0]
            offset=0
        except (ClipError, TimeoutError):
            local=full_source(p,meta,cfg)
            offset=start
    else:
        offset=start
    cmd=[tool('ffmpeg'),'-v','error','-n','-ss',str(offset),'-i',str(local),'-t',str(end-start)]
    cmd += ['-vn','-ac','1','-ar','16000','-c:a','pcm_s16le'] if audio else ['-map','0:v:0','-map','0:a:0','-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac','-ar','48000']
    run(cmd+[str(target)],cfg['timeout'])
    validate_media(target,end-start,video=not audio)
    atomic(receipt,dict(path=str(target),hash=file_hash(target)))
    return target


def speech(p, audio, cfg, device=None):
    stage=p/'tmp'/uuid.uuid4().hex
    stage.mkdir(parents=True)
    devices=[device] if device else (['cuda','cpu'] if cfg['device']=='auto' else [cfg['device'],'cpu'] if cfg['device']=='cuda' else ['cpu'])
    for dev in devices:
        req=stage/(dev+'-request.json')
        out=stage/(dev+'-result.json')
        atomic(req,dict(config=cfg,audio=str(audio),device=dev))
        try:
            run([sys.executable,str(ROOT/'scripts'/'worker.py'),str(req),str(out)],cfg['timeout'])
            return read(out)
        except Exception as e:
            event(p,'transcribe','device-failed',device=dev,error=type(e).__name__)
            if dev==devices[-1]:
                raise
            event(p,'transcribe','fallback',device='cpu')


def chat(p, meta, cfg):
    if meta['platform']!='youtube':
        return dict(status='unavailable',reason='Replay adapter implemented only for YouTube',peaks=[])
    stage=p/'tmp'/uuid.uuid4().hex
    stage.mkdir(parents=True)
    try:
        run(ytdlp('--skip-download','--write-subs','--sub-langs','live_chat','-o',str(stage/'chat'),meta['url']),cfg['timeout'])
        paths=list(stage.glob('*.live_chat.json'))
        if not paths:
            return dict(status='unavailable',reason='No replay returned',peaks=[])
        import collections
        import statistics
        counts=collections.Counter()
        with paths[0].open(encoding='utf-8') as f:
            for line in f:
                try:
                    t=float(json.loads(line)['replayChatItemAction']['videoOffsetTimeMsec'])/1000
                    if 0<=t<=meta['duration']:
                        counts[int(t//10)]+=1
                except (ValueError,KeyError,TypeError):
                    continue
        peaks=[]
        for i,n in counts.items():
            base=max(1,statistics.median([counts[j] for j in range(max(0,i-30),i+31)]))
            if n>=8 and n/base>=2.5:
                peaks.append(dict(second=i*10,ratio=round(n/base,2)))
        return dict(status='complete',peaks=peaks)
    except Exception as e:
        return dict(status='failed',error=type(e).__name__,peaks=[])


def prepare(p,cfg):
    meta=authorized(p)
    # Configuration revisions get separate generations; completed blocks remain recoverable.
    gen=digest([digest(meta),cfg])[:24]
    base=p/'generations'/gen
    base.mkdir(parents=True,exist_ok=True)
    atomic(p/'config.json',cfg)
    atomic(p/'active.json',dict(generation=gen))
    count=math.ceil(meta['duration']/cfg['block_seconds'])
    for i in range(count):
        start=i*cfg['block_seconds']; end=min(meta['duration'],start+cfg['block_seconds'])
        ctx_start=max(0,start-cfg['context_seconds']); ctx_end=min(meta['duration'],end+cfg['context_seconds'])
        block=base/'blocks'/f'{i:05d}'
        def produce():
            wav=section(p,meta,cfg,ctx_start,ctx_end)
            trans=speech(p,wav,cfg)
            for s in trans['segments']:
                s['start']+=ctx_start; s['end']+=ctx_start
                for w in s['words']:
                    w['start']+=ctx_start; w['end']+=ctx_start
            peaks=audio_peaks(wav)
            for peak in peaks:
                peak['second']+=ctx_start
            return dict(block=i,start=start,end=end,context_start=ctx_start,context_end=ctx_end,transcript=trans,audio_peaks=peaks)
        _, reused=checkpoint(block,'transcript',digest([gen,i]),produce)
        event(p,'block','reused' if reused else 'complete',block=i,total=count)
    chat_path=base/'chat.json'
    if not chat_path.exists() or read(chat_path)['status']=='failed':
        atomic(chat_path,chat(p,meta,cfg))
    return dict(source=meta['id'],generation=gen,blocks=count,path=str(base/'blocks'))


def active(p):
    authorized(p)
    cfg=read(p/'config.json')
    gen=read(p/'active.json')['generation']
    if gen!=digest([digest(read(p/'source.json')),cfg])[:24]:
        raise ClipError('Configuration changed; prepare again')
    return p/'generations'/gen,cfg


def import_analysis(p,number,path):
    base,cfg=active(p)
    block=base/'blocks'/f'{number:05d}'
    transcript=read(block/'transcript.json')
    parsed=candidates(read(path),read(p/'source.json')['duration'],cfg,(transcript['start'],transcript['end']))
    record=dict(transcript_hash=file_hash(block/'transcript.json'),items=parsed)
    if (block/'analysis.json').exists():
        atomic(block/('analysis.'+uuid.uuid4().hex+'.previous.json'),read(block/'analysis.json'))
    atomic(block/'analysis.json',record)
    return dict(block=number,candidates=len(parsed))


def review(p):
    base,cfg=active(p)
    meta=read(p/'source.json')
    all_items=[]; transcripts=[]; peaks=[]
    count=math.ceil(meta['duration']/cfg['block_seconds'])
    for i in range(count):
        b=base/'blocks'/f'{i:05d}'
        if not (b/'analysis.json').exists():
            raise ClipError(f'Analysis pending for block {i}')
        t=read(b/'transcript.json'); a=read(b/'analysis.json')
        if a['transcript_hash']!=file_hash(b/'transcript.json'):
            raise ClipError('Analysis is stale')
        # Revalidate stored analysis too; never trust files merely because they exist.
        raw=[{k:v for k,v in item.items() if k!='id'} for item in a['items']]
        all_items+=candidates(raw,meta['duration'],cfg,(t['start'],t['end']))
        transcripts+=t['transcript']['segments']; peaks+=t['audio_peaks']
    selected=select(all_items,cfg['clip_count'])
    for m in selected:
        m['transcript']=' '.join(dict.fromkeys(s['text'] for s in transcripts if s['start']<m['end'] and m['start']<s['end']))
        m['audio']=[v for v in peaks if m['start']<=v['second']<m['end']]
        m['camera']='Not analyzed; run preview'
    review_hash=digest([base.name,selected])
    out=base/'reviews'/review_hash[:24]
    out.mkdir(parents=True,exist_ok=True)
    atomic(out/'candidates.json',dict(source=meta,config=cfg,items=selected,hash=review_hash))
    atomic(base/'review.json',dict(path=str(out),hash=review_hash))
    rows=[]
    for m in selected:
        rows.append('<article><h2>'+html.escape(m['title'])+'</h2><p>'+html.escape(f"{m['id']} | {m['start']:.3f}–{m['end']:.3f}s | {m['end']-m['start']:.3f}s")+'</p><p>'+html.escape(m['transcript'])+'</p><p>'+html.escape(m['reason'])+'</p><pre>'+html.escape(json.dumps(m['audio'],ensure_ascii=False))+'</pre><p>Camera: pending audiovisual preview</p></article>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Clip review</title><style>body{font:18px system-ui;max-width:900px;margin:40px auto;background:#111827;color:#f3f4f6}article{padding:20px;border:1px solid #64748b;margin:20px 0}pre{white-space:pre-wrap}</style><h1>'+html.escape(meta['title'])+'</h1><p>'+html.escape(meta['url'])+'</p>'+''.join(rows),encoding='utf-8')
    return dict(path=str(out),candidates=selected)


def current_review(p):
    base,cfg=active(p)
    info=read(base/'review.json')
    path=Path(info['path'])
    data=read(path/'candidates.json')
    # Regenerate in memory through review to detect analysis changes and revoke stale approvals.
    review(p)
    fresh=read(base/'review.json')
    if fresh['hash']!=info['hash'] or data['hash']!=info['hash'] or digest([base.name,data['items']])!=info['hash']:
        raise ClipError('Candidates changed; show the new review and request approval again')
    return path,data,cfg


def approve(p,ids,confirmation):
    path,data,cfg=current_review(p)
    if not confirmation.strip() or not ids or set(ids)-{m['id'] for m in data['items']}:
        raise ClipError('Explicit approval of valid candidate IDs required')
    atomic(path/'approval.json',dict(review_hash=data['hash'],ids=sorted(set(ids)),confirmation=confirmation,time=time.time()))
    return dict(approved=ids)


def render(p,ids,preview=False):
    path,data,cfg=current_review(p)
    meta=authorized(p)
    if not ids or set(ids)-{m['id'] for m in data['items']}:
        raise ClipError('Unknown candidate')
    if not preview:
        if not (path/'approval.json').exists():
            raise ClipError('Candidate approval required before rendering')
        approval=read(path/'approval.json')
        if approval['review_hash']!=data['hash'] or set(ids)-set(approval['ids']):
            raise ClipError('Candidates not approved')
    base,_=active(p)
    words=[]
    for block in sorted((base/'blocks').glob('*')):
        for segment in read(block/'transcript.json')['transcript']['segments']:
            words+=segment['words']
    outputs=[]
    for m in data['items']:
        if m['id'] not in ids:
            continue
        interval(m['start'],m['end'],meta['duration'],cfg['min_duration'],cfg['max_duration'])
        mode='previews' if preview else 'approved'
        outdir=path/mode/m['id']; outdir.mkdir(parents=True,exist_ok=True)
        receipt=outdir/'result.json'
        if receipt.exists():
            old=read(receipt)
            if Path(old['path']).exists() and file_hash(old['path'])==old['sha256']:
                validate_media(old['path'],m['end']-m['start'],size=old['resolution'],full=True)
                outputs.append(old); continue
            raise ClipError('Existing result changed/corrupt; preserve and review before replacement')
        video=section(p,meta,cfg,m['start'],m['end'],False)
        camera=faces(video,cfg)
        stage=outdir/('work-'+uuid.uuid4().hex); stage.mkdir()
        w,h=cfg['width'],cfg['height']
        if preview:
            scale=min(1,640/max(w,h)); w=int(w*scale)//2*2; h=int(h*scale)//2*2
        selected_words={ (round(x['start'],3),round(x['end'],3),x['word']):x for x in words if x['start']<m['end'] and x['end']>m['start'] }
        relative=[dict(start=x['start']-m['start'],end=x['end']-m['start'],word=x['word']) for x in sorted(selected_words.values(),key=lambda x:x['start'])]
        captions(stage/'captions.ass',relative,m['title'],m['end']-m['start'],w,h,cfg)
        target=stage/'clip.mp4'
        codec='libx264' if preview else cfg['codec']
        quality=['-crf',str(cfg['crf']),'-preset','veryfast' if preview else cfg['preset']] if codec=='libx264' else ['-cq',str(cfg['crf']),'-preset','p4']
        run([tool('ffmpeg'),'-v','error','-n','-i',str(video),'-filter_complex',compose(w,h,camera,cfg),'-map','[v]','-map','0:a:0',
             '-c:v',codec,*quality,'-r',str(cfg['fps']),'-c:a','aac','-b:a','160k','-movflags','+faststart',str(target)],cfg['timeout'],cwd=stage)
        info=validate_media(target,m['end']-m['start'],size=[w,h],full=True)
        final=outdir/'clip.mp4'
        if final.exists():
            raise ClipError('Final exists without receipt; preserve it, never overwrite automatically')
        target.rename(final)
        record=dict(path=str(final),sha256=file_hash(final),resolution=[w,h],integrity=info,camera=camera,config=cfg,source=meta['id'],candidate=m,preview=preview)
        atomic(receipt,record)
        (outdir/'credit.txt').write_text(f"{m['title']}\n{m.get('post','')}\nSource: {meta['creator']} — {meta['url']}\n",encoding='utf-8')
        outputs.append(record)
    atomic(path/('preview-report.json' if preview else 'render-report.json'),outputs)
    return outputs
