"""Verified source sync with backup and rollback. Does not edit Codex global configuration."""
import argparse
import datetime
import os
from pathlib import Path
import shutil
import sys
import uuid
from core import ClipError, atomic, file_hash, read

EXCLUDE={'.venv','.runtime','__pycache__','.git','runtime.json','install-receipt.json'}


def manifest(root):
    return {str(p.relative_to(root)).replace('\\','/'):file_hash(p) for p in sorted(Path(root).rglob('*'))
            if p.is_file() and not any(part in EXCLUDE for part in p.relative_to(root).parts)}


def validate_source(source):
    source=Path(source).resolve()
    for name in ['SKILL.md','agents/openai.yaml','scripts/clip.py','scripts/core.py','requirements.txt']:
        if not (source/name).is_file(): raise ClipError('Incomplete skill: '+name)
    for p in source.rglob('*'):
        if not any(x in EXCLUDE for x in p.relative_to(source).parts) and p.is_symlink():
            raise ClipError('Symlink in skill payload')
    return source


def install(source,destination):
    source=validate_source(source); destination=Path(destination).absolute()
    if destination.is_symlink() or source==destination.resolve() or source in destination.resolve().parents:
        raise ClipError('Unsafe install destination')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=destination.with_name('.'+destination.name+'-stage-'+uuid.uuid4().hex)
    backup=None
    old_manifest=None
    if destination.exists():
        # Inspect content before altering; preserve everything, including user changes.
        old_manifest=manifest(destination)
        if not (destination/'SKILL.md').is_file():
            raise ClipError('Existing destination is not a skill; inspect it manually')
    shutil.copytree(source,stage,ignore=lambda d,n:[x for x in n if x in EXCLUDE])
    wanted=manifest(source)
    if manifest(stage)!=wanted: raise ClipError('Copy verification failed; destination unchanged')
    try:
        if destination.exists():
            backup=destination.with_name(destination.name+'.backup-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
            destination.rename(backup)
            # Reuse existing runtime without copying or modifying backup code.
            for item in ('.runtime','.venv'):
                if (backup/item).exists():
                    shutil.copytree(backup/item,stage/item)
            if (backup/'runtime.json').exists(): shutil.copy2(backup/'runtime.json',stage/'runtime.json')
        stage.rename(destination)
    except BaseException:
        if backup and not destination.exists(): backup.rename(destination)
        raise
    receipt=dict(source=str(source),destination=str(destination),files=wanted,previous_files=old_manifest,backup=str(backup) if backup else None)
    atomic(destination/'install-receipt.json',receipt)
    return receipt


def rollback(destination,backup):
    destination=Path(destination).absolute(); backup=Path(backup).absolute()
    if destination.is_symlink() or backup.is_symlink() or backup.parent!=destination.parent or not backup.name.startswith(destination.name+'.backup-'):
        raise ClipError('Backup must be a verified sibling installation backup')
    validate_source(backup)
    retained=destination.with_name(destination.name+'.rollback-retained-'+uuid.uuid4().hex[:8])
    if destination.exists(): destination.rename(retained)
    try: backup.rename(destination)
    except BaseException:
        if retained.exists(): retained.rename(destination)
        raise
    return dict(restored=str(destination),retained=str(retained))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--destination',type=Path,default=Path.home()/'.agents'/'skills'/'stream-clipper')
    p.add_argument('--rollback',type=Path)
    a=p.parse_args()
    import json
    print(json.dumps(rollback(a.destination,a.rollback) if a.rollback else install(a.source,a.destination),indent=2))
