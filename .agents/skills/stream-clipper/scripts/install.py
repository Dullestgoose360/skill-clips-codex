"""Safe, verified skill sync with sibling backup and non-destructive rollback."""
import argparse
import datetime
import os
from pathlib import Path
import shutil
import stat
import uuid

from core import ClipError, atomic, file_hash, read

EXCLUDE = {'.venv', '.runtime', '__pycache__', '.git', 'runtime.json', 'install-receipt.json'}
REQUIRED = ('SKILL.md', 'agents/openai.yaml', 'scripts/clip.py', 'scripts/core.py', 'requirements.txt')


def absolute(path):
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def reject_reparse_components(path):
    """Refuse symlinks/junctions in the destination chain to avoid redirected writes."""
    path = absolute(path)
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    for node in reversed((path, *path.parents)):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ClipError(f'Cannot inspect installation path component: {node}') from exc
        attributes = getattr(info, 'st_file_attributes', 0)
        if stat.S_ISLNK(info.st_mode) or (reparse and attributes & reparse):
            raise ClipError(f'Symlink/junction in installation path is not supported: {node}')
    return path


def reject_tree_links(root):
    root = Path(root)
    for item in (root, *root.rglob('*')):
        if not item.exists():
            continue
        try:
            info = item.lstat()
        except OSError as exc:
            raise ClipError(f'Cannot inspect skill path: {item}') from exc
        reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        attributes = getattr(info, 'st_file_attributes', 0)
        if stat.S_ISLNK(info.st_mode) or (reparse and attributes & reparse):
            raise ClipError(f'Symlink/junction inside skill directory is not supported: {item}')


def manifest(root):
    root = Path(root)
    if not root.is_dir():
        raise ClipError(f'Skill directory does not exist: {root}')
    return {
        str(item.relative_to(root)).replace('\\', '/'): file_hash(item)
        for item in sorted(root.rglob('*'))
        if item.is_file() and not any(part in EXCLUDE for part in item.relative_to(root).parts)
    }


def validate_source(source):
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise ClipError(f'Source skill directory does not exist: {source}')
    reject_tree_links(source)
    for name in REQUIRED:
        if not (source / name).is_file():
            raise ClipError('Incomplete skill: ' + name)
    return source


def verify(destination):
    destination = reject_reparse_components(destination)
    if not destination.is_dir():
        raise ClipError(f'Installed skill directory does not exist: {destination}')
    reject_tree_links(destination)
    validate_source(destination)
    receipt_path = destination / 'install-receipt.json'
    if not receipt_path.is_file():
        raise ClipError('Install receipt missing; run the installer or inspect this skill manually')
    receipt = read(receipt_path)
    expected = receipt.get('files')
    if not isinstance(expected, dict):
        raise ClipError('Install receipt has no valid file manifest')
    actual = manifest(destination)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(expected) & set(actual) if expected[k] != actual[k])
        raise ClipError(f'Installed files differ from receipt; missing={missing[:5]}, extra={extra[:5]}, changed={changed[:5]}')
    return dict(valid=True, destination=str(destination), files=len(actual),
                source=receipt.get('source'), backup=receipt.get('backup'),
                snapshot=bool(receipt.get('snapshot', False)))


def install(source, destination):
    source = validate_source(source)
    destination = reject_reparse_components(destination)

    # Never copy into the source, into one of its descendants, or over a source ancestor.
    if source == destination or source in destination.parents or destination in source.parents:
        raise ClipError('Unsafe install destination: source and destination must be separate trees')

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = reject_reparse_components(destination)
    if destination.exists() and not destination.is_dir():
        raise ClipError('Install destination exists and is not a directory')
    if destination.exists():
        reject_tree_links(destination)
        if not (destination / 'SKILL.md').is_file():
            raise ClipError('Existing destination is not a skill; inspect it manually before replacing')
        old_manifest = manifest(destination)
    else:
        old_manifest = None

    stage = destination.with_name('.' + destination.name + '.stage-' + uuid.uuid4().hex)
    backup = None

    try:
        shutil.copytree(source, stage, ignore=lambda _directory, names: [name for name in names if name in EXCLUDE])
        wanted = manifest(source)
        if manifest(stage) != wanted:
            raise ClipError('Staged copy verification failed; current installation was not changed')

        if destination.exists():
            backup = destination.with_name(
                destination.name + '.backup-' +
                datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' +
                uuid.uuid4().hex[:8]
            )
            destination.rename(backup)

            # Snapshot the exact pre-update manifest, including user-added files, for a verifiable rollback.
            previous_receipt = None
            old_receipt_path = backup / 'install-receipt.json'
            if old_receipt_path.is_file():
                try:
                    previous_receipt = read(old_receipt_path)
                except (ValueError, OSError):
                    previous_receipt = None
            backup_receipt = dict(
                source=(previous_receipt or {}).get('source', 'previous installation snapshot'),
                destination=str(destination),
                files=old_manifest,
                previous_files=(previous_receipt or {}).get('previous_files'),
                backup=(previous_receipt or {}).get('backup'),
                installed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                snapshot=True,
            )
            atomic(backup / 'install-receipt.json', backup_receipt)

            # Preserve local runtime state without mixing it into the source-controlled manifest.
            for item in ('.runtime', '.venv'):
                previous = backup / item
                if previous.exists():
                    reject_tree_links(previous)
                    shutil.copytree(previous, stage / item)
            previous_runtime = backup / 'runtime.json'
            if previous_runtime.is_file():
                shutil.copy2(previous_runtime, stage / 'runtime.json')

        receipt = dict(
            source=str(source),
            destination=str(destination),
            files=wanted,
            previous_files=old_manifest,
            backup=str(backup) if backup else None,
            installed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        # Write and verify receipt in staging before switching the active installation.
        atomic(stage / 'install-receipt.json', receipt)
        if manifest(stage) != wanted:
            raise ClipError('Final staged manifest changed unexpectedly; current installation was not changed')
        stage.rename(destination)
        return dict(valid=True, destination=str(destination), files=len(wanted),
                    backup=str(backup) if backup else None, source=str(source))
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if backup and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise


def rollback(destination, backup):
    destination = reject_reparse_components(destination)
    backup = reject_reparse_components(backup)
    if backup.parent != destination.parent or not backup.name.startswith(destination.name + '.backup-'):
        raise ClipError('Backup must be a sibling folder created by this installer')
    if not backup.is_dir():
        raise ClipError('Backup folder does not exist')

    # Refuse to restore a corrupt or manually altered backup.
    verify(backup)

    if destination.exists():
        if not destination.is_dir() or not (destination / 'SKILL.md').is_file():
            raise ClipError('Current destination is not a recognizable skill; refusing to replace it')
        reject_tree_links(destination)
        retained = destination.with_name(destination.name + '.rollback-retained-' + uuid.uuid4().hex[:8])
        destination.rename(retained)
    else:
        retained = None

    try:
        backup.rename(destination)
    except BaseException:
        if retained and retained.exists() and not destination.exists():
            retained.rename(destination)
        raise
    return dict(restored=str(destination), retained=str(retained) if retained else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Install, verify or roll back the personal Stream Clipper skill')
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--destination', type=Path, default=Path.home() / '.agents' / 'skills' / 'stream-clipper')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify', action='store_true', help='verify installed files against the install receipt')
    mode.add_argument('--rollback', type=Path, help='restore this exact sibling backup without deleting current files')
    args = parser.parse_args()

    import json
    if args.verify:
        result = verify(args.destination)
    elif args.rollback:
        result = rollback(args.destination, args.rollback)
    else:
        result = install(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
