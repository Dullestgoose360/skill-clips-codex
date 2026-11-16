"""Strict data validation, atomic state and bounded subprocesses (stdlib only)."""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import uuid


class ClipError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ClipError('Duplicate JSON key: ' + k)
        out[k] = v
    return out


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ClipError('Nonfinite JSON')))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def seconds(v):
    if isinstance(v, bool):
        raise ClipError('Boolean is not a timestamp')
    if isinstance(v, str):
        if not re.fullmatch(r'\d+(?::[0-5]\d){0,2}(?:\.\d+)?', v):
            raise ClipError('Expected seconds, MM:SS or HH:MM:SS')
        parts = [float(x) for x in v.split(':')]
        v = sum(x * 60 ** i for i, x in enumerate(reversed(parts)))
    if not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise ClipError('Timestamp must be finite and nonnegative')
    return float(v)


def interval(start, end, duration, minimum=0, maximum=float('inf')):
    s, e = seconds(start), seconds(end)
    if not s < e <= duration + 0.001 or not minimum <= e - s <= maximum:
        raise ClipError('Invalid interval or duration; timestamps are never silently extended')
    return s, e


def source_id(platform, identifier):
    slug = re.sub('[^a-zA-Z0-9_-]', '-', str(platform))[:24] or 'source'
    return slug.lower() + '-' + digest([platform, identifier])[:24]


def candidates(data, duration, cfg, bounds=None):
    if not isinstance(data, list):
        raise ClipError('Analysis must be a JSON array')
    result = []
    for m in data:
        required = {'start', 'end', 'title', 'reason', 'score'}
        if not isinstance(m, dict) or not required <= m.keys() or m.keys() - required - {'post'}:
            raise ClipError('Invalid candidate keys')
        s, e = interval(m['start'], m['end'], duration, cfg['min_duration'], cfg['max_duration'])
        if bounds and not bounds[0] <= s < bounds[1]:
            raise ClipError('Candidate must start in the analyzed block')
        if isinstance(m['score'], bool) or not isinstance(m['score'], (float, int)) or not 0 <= m['score'] <= 100:
            raise ClipError('Score must be a finite number from 0 to 100')
        for k in ('title', 'reason'):
            if not isinstance(m[k], str) or not m[k].strip() or len(m[k]) > 2000:
                raise ClipError('Invalid ' + k)
        if 'post' in m and (not isinstance(m['post'], str) or len(m['post']) > 4000):
            raise ClipError('Invalid post')
        item = dict(m, start=s, end=e)
        item['id'] = digest(item)[:20]
        result.append(item)
    return result


def select(items, count):
    out = []
    for m in sorted(items, key=lambda m: (-m['score'], m['start'], m['id'])):
        if not any(m['start'] < n['end'] and n['start'] < m['end'] for n in out):
            out.append(m)
            if len(out) == count:
                break
    return sorted(out, key=lambda m: m['start'])


def event(folder, stage, status, **values):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    item = dict(time=time.time(), stage=stage, status=status, **values)
    with (folder / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(json.dumps(item, ensure_ascii=False), flush=True)


def run(args, timeout=1800, cwd=None):
    """Never log command URLs/headers; terminate process tree on timeout/interruption."""
    p = subprocess.Popen([str(x) for x in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         cwd=cwd, text=True, encoding='utf-8', errors='replace',
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                         start_new_session=os.name != 'nt')
    try:
        out, err = p.communicate(timeout=timeout)
    except BaseException:
        # Kill the whole process tree, then drain and close both pipes before re-raising.
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
            else:
                import signal
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        finally:
            try:
                p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
            finally:
                if p.stdout:
                    p.stdout.close()
                if p.stderr:
                    p.stderr.close()
        raise
    if p.returncode:
        # Tool diagnostics may contain signed media URLs, cookies or headers. Keep them out of logs.
        raise ClipError(f'{Path(str(args[0])).name} failed (exit {p.returncode}); stage can be retried')
    return out


@contextlib.contextmanager
def lock(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / '.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ClipError('Source locked; check status/process before recover-lock')
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def checkpoint(folder, name, key, producer):
    """Commit only complete, hash-verified artifacts; preserve old output on corruption/change."""
    folder = Path(folder)
    state = folder / (name + '.state.json')
    target = folder / (name + '.json')
    if state.exists() and target.exists():
        try:
            old = read(state)
            if old['key'] == key and old['hash'] == file_hash(target):
                return read(target), True
        except (ValueError, KeyError):
            pass
    event(folder, name, 'running')
    try:
        value = producer()
        if target.exists():
            backup = target.with_name(target.name + '.' + uuid.uuid4().hex + '.previous')
            target.rename(backup)
        atomic(target, value)
        atomic(state, dict(key=key, hash=file_hash(target), status='complete'))
        event(folder, name, 'complete')
        return value, False
    except BaseException as e:
        event(folder, name, 'failed', error=type(e).__name__)
        raise
