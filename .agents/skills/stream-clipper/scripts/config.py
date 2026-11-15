from copy import deepcopy
from core import ClipError, read

DEFAULT = dict(platform='youtube', topic='', subject='', creator='', keywords=[], language=None,
               video_count=7, clip_count=3, min_duration=20, max_duration=60,
               editorial_criteria='Self-contained, accurate and engaging; preserve speech continuity.',
               block_seconds=720, context_seconds=5, model='tiny', device='auto', cpu_threads=8,
               allow_model_download=False, profile='9:16', width=1080, height=1920,
               fps=30, codec='libx264', crf=21, preset='medium', layout='fit',
               camera_fraction=.4, camera_box=None, game_position=.5,
               face_threshold=.8, face_samples=14, face_min_hits=3,
               subtitles=True, title_overlay=True, subtitle_size=.05, subtitle_y=.16,
               timeout=1800, large_download_gb=2)


def load(path=None):
    cfg = deepcopy(DEFAULT)
    if path:
        patch = read(path)
        if not isinstance(patch, dict) or patch.keys() - cfg.keys():
            raise ClipError('Unknown configuration keys')
        cfg.update(patch)
        if 'profile' in patch and not {'width', 'height'} & patch.keys():
            cfg['width'], cfg['height'] = {'9:16':(1080,1920), '16:9':(1920,1080), '1:1':(1080,1080)}.get(cfg['profile'], (0,0))
    for name, lo, hi in [('video_count',1,100),('clip_count',1,100),('block_seconds',5,3600),('cpu_threads',1,64),('width',64,3840),('height',64,3840),('fps',1,120),('face_samples',3,100),('face_min_hits',1,100),('timeout',10,14400)]:
        v = cfg[name]
        if isinstance(v, bool) or not isinstance(v,int) or not lo <= v <= hi:
            raise ClipError('Invalid config: '+name)
    for name, lo, hi in [('min_duration',.1,3600),('max_duration',.1,3600),('context_seconds',0,60),('face_threshold',.1,1),('camera_fraction',.1,.8),('game_position',0,1),('subtitle_size',.01,.2),('subtitle_y',0,.8),('large_download_gb',.01,100),('crf',0,51)]:
        v = cfg[name]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not lo <= v <= hi:
            raise ClipError('Invalid config: '+name)
    if cfg['min_duration'] > cfg['max_duration'] or cfg['face_min_hits'] > cfg['face_samples']:
        raise ClipError('Inverted config bounds')
    for name, choices in dict(platform=['youtube','twitch','kick','local'],device=['auto','cpu','cuda'],profile=['9:16','16:9','1:1'],codec=['libx264','h264_nvenc'],layout=['fit','camera-top'],preset=['ultrafast','veryfast','fast','medium','slow']).items():
        if cfg[name] not in choices:
            raise ClipError('Invalid '+name)
    ratios = {'9:16':9/16,'16:9':16/9,'1:1':1}
    if cfg['width']%2 or cfg['height']%2 or abs(cfg['width']/cfg['height']-ratios[cfg['profile']]) > .01:
        raise ClipError('Resolution must be even and match profile')
    for name in ('allow_model_download','subtitles','title_overlay'):
        if not isinstance(cfg[name],bool):
            raise ClipError('Expected boolean: '+name)
    for name in ('topic','subject','creator','editorial_criteria','model'):
        if not isinstance(cfg[name],str):
            raise ClipError('Expected text: '+name)
    if cfg['language'] is not None and (not isinstance(cfg['language'],str) or len(cfg['language']) not in (2,3)):
        raise ClipError('Invalid language')
    if not isinstance(cfg['keywords'],list) or any(not isinstance(x,str) for x in cfg['keywords']):
        raise ClipError('Keywords must be strings')
    if cfg['camera_box'] is not None and (not isinstance(cfg['camera_box'],list) or len(cfg['camera_box'])!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or v<0 for v in cfg['camera_box'])):
        raise ClipError('Invalid camera box')
    return cfg
