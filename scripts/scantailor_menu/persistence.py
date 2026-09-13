"""Preferences and execution identities shared by workbench and controller.

Only source-independent defaults persist across documents. Task snapshots retain
full geometry/rules and never consume subsequently changed preference files.
"""
import copy
import hashlib
import json
from pathlib import Path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def portable_config(config):
    result = {k: copy.deepcopy(v) for k, v in config.items() if k in ('schema_version', 'preset', 'image_encoding', 'defaults')}
    defaults = result.get('defaults', {})
    for section, keys in {'orientation': ['trim'], 'split': ['cutters'], 'deskew': ['basis'],
                          'content': ['page_rect', 'content_rect', 'basis'],
                          'output': ['distortion_model'], 'picture_zones': None, 'fill_zones': None}.items():
        if keys is None:
            defaults.pop(section, None)
        elif isinstance(defaults.get(section), dict):
            for key in keys:
                defaults[section].pop(key, None)
    split = defaults.get('split', {})
    if split.get('mode') == 'manual': split['mode'] = 'auto'
    content = defaults.get('content', {})
    for key in ('page_mode', 'content_mode'):
        if content.get(key) == 'manual': content[key] = 'off'
    content.pop('space', None)
    output = defaults.get('output', {})
    if output.get('dewarp') == 'manual': output['dewarp'] = 'off'
    return result


def output_inventory(folder):
    extensions = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.pdf', '.scan'}
    files = [p for p in Path(folder).rglob('*') if p.is_file() and
             (p.suffix.lower() in extensions or p.name in ('report.json', 'analysis.json', 'preview.html', 'batch-report.json'))]
    return {str(p.resolve()): digest(p) for p in files}


def verified(job):
    try:
        files = job.get('artifacts', {})
        return bool(files) and all(Path(p).is_file() and digest(p) == value for p, value in files.items())
    except OSError:
        return False


def outcome_complete(folder):
    root = Path(folder)
    for path in (root/'batch-report.json', root/'_scantailor'/'batch-report.json'):
        if path.exists():
            report = json.loads(path.read_text(encoding='utf-8-sig'))
            return bool(report.get('results')) and not report.get('failures') and not any(r.get('errors') for r in report['results'])
    path = root/'report.json'
    if not path.exists(): return False
    report = json.loads(path.read_text(encoding='utf-8-sig'))
    return bool(report.get('pages')) and not report.get('errors') and not report.get('import_errors')


def differences(old, new, prefix=''):
    changes = []
    for key in sorted(set(old) | set(new)):
        if key in ('scripts', 'cli', 'output', 'inputs', 'dependencies'): continue
        path = prefix + key
        left, right = old.get(key), new.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            changes.extend(differences(left, right, path + '.'))
        elif left != right:
            changes.append(f'{path}: {left} → {right}')
    return changes
