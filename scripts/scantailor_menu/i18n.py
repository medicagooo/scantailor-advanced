"""Application-owned display strings; machine values and user text stay opaque.

Windows preferred UI languages are resolved once at startup (or when System is
selected). UI preference is independent of processing snapshots/fingerprints.
Resource files are UTF-8 and shipped beside this module in portable bundles.
"""
from pathlib import Path
import ctypes
import json

LANGUAGES = ('auto', 'en', 'zh-Hans', 'zh-Hant')
NAMES = {'en': 'English', 'zh-Hans': '简体中文', 'zh-Hant': '繁體中文'}
def read_catalog(name, directory=None):
    path = (Path(directory) if directory else Path(__file__).parent/'locales') / f'{name}.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or any(not isinstance(v,str) for v in value.values()):
            raise ValueError('Invalid language catalog')
        return value
    except (OSError, ValueError):
        if name == 'en': raise RuntimeError('English language resources are missing or damaged. Re-extract the complete package.')
        return {}  # Missing locale resource falls back to the English catalog.

_catalogs = {name: read_catalog(name) for name in NAMES}
_current = 'en'

def match_language(name):
    parts = str(name).replace('_', '-').lower().split('-')
    if parts[0] == 'en': return 'en'
    if parts[0] != 'zh': return None
    if 'hant' in parts: return 'zh-Hant'
    if 'hans' in parts: return 'zh-Hans'
    return 'zh-Hant' if any(p in ('tw','hk','mo') for p in parts) else 'zh-Hans'

def preferred_languages():
    """Read per-user Windows UI preferences, not code page or regional format."""
    try:
        api = ctypes.WinDLL('kernel32', use_last_error=True).GetUserPreferredUILanguages
        api.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        api.restype = ctypes.c_int
        count, size = ctypes.c_ulong(), ctypes.c_ulong()
        if not api(8, ctypes.byref(count), None, ctypes.byref(size)) or not size.value: return []
        buffer = ctypes.create_unicode_buffer(size.value)
        if not api(8, ctypes.byref(count), buffer, ctypes.byref(size)): return []
        return [s for s in buffer[:size.value].split('\0') if s]
    except (AttributeError, OSError, ValueError):
        return []

def resolve_language(preference, preferred=None):
    if preference not in LANGUAGES: raise ValueError('Unsupported interface language')
    if preference != 'auto': return preference
    return next((match_language(s) for s in (preferred_languages() if preferred is None else preferred) if match_language(s)), 'en')

def set_language(preference):
    global _current
    _current = resolve_language(preference)
    return _current

def language(): return _current

def tr(key, **values):
    if values.get('count') == 1 and key + '.one' in _catalogs['en']: key += '.one'
    text = _catalogs[_current].get(key, _catalogs['en'].get(key, key))
    return text.format(**values) if values else text

def catalog(locale):
    return {**_catalogs['en'], **_catalogs[locale]}
