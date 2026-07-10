"""
YAML based localization helpers.

The old backend used flat keys through common.LNG.G("key").  This module keeps
that key style while loading text from locales/*.yaml.
"""
import locale
import os
import ast
import sys

try:
    import yaml
except Exception:
    yaml = None

allLang = {}
sysLang = None
defaultLang = 'zh_CN'


def _get_locales_path():
    candidates = [os.path.join(os.getcwd(), 'locales')]
    frozen_root = getattr(sys, '_MEIPASS', None)
    if frozen_root:
        candidates.append(os.path.join(frozen_root, 'locales'))
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(project_root, 'locales'))

    checked = set()
    for candidate in candidates:
        candidate = os.path.normpath(candidate)
        if candidate in checked:
            continue
        checked.add(candidate)
        if os.path.isdir(candidate):
            return candidate
    raise FileNotFoundError(f"No lang path found in: {', '.join(checked)}")


def normalize_lang(lang):
    if not lang:
        return None
    lang = str(lang).split(',')[0].split(';')[0].strip()
    if not lang:
        return None
    lang = lang.replace('-', '_')
    lang_lower = lang.lower()
    mapping = {
        'zh': 'zh_CN',
        'zh_cn': 'zh_CN',
        'zh_hans': 'zh_CN',
        'zh_hans_cn': 'zh_CN',
        'chinese (simplified)_china': 'zh_CN',
        'eng': 'en',
        'en': 'en',
        'en_us': 'en',
        'english_united states': 'en',
    }
    if lang_lower in mapping:
        return mapping[lang_lower]
    if lang_lower.startswith('zh'):
        return 'zh_CN'
    if lang_lower.startswith('en'):
        return 'en'
    return lang


def getSysLang():
    lang = locale.getlocale()[0] or os.environ.get('LANG') or os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES')
    return normalize_lang(lang) or defaultLang


def initLang():
    global allLang
    allLang = {}
    locales_path = _get_locales_path()
    for file in os.listdir(locales_path):
        if file.endswith('.yaml'):
            filename = os.path.join(locales_path, file)
            langKey = file[:-5]
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
                allLang[langKey] = _load_yaml(content)
    if defaultLang not in allLang:
        raise Exception(f"No default lang: {defaultLang}")
    global sysLang
    sysLang = getOrSetDefaultLang(getSysLang())


def _parse_simple_value(val):
    val = val.strip()
    if val == '':
        return ''
    if val in ['true', 'True']:
        return True
    if val in ['false', 'False']:
        return False
    if val.startswith(('"', "'")) and val.endswith(('"', "'")):
        try:
            return ast.literal_eval(val)
        except Exception:
            return val[1:-1]
    return val


def _load_yaml(content):
    if yaml is not None:
        return yaml.safe_load(content) or {}
    data = {}
    current_key = None
    for raw_line in content.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith('#'):
            continue
        if raw_line.startswith('  -') and current_key is not None:
            data[current_key].append(_parse_simple_value(raw_line.split('-', 1)[1]))
            continue
        if raw_line.startswith(' '):
            continue
        if ':' not in raw_line:
            continue
        key, val = raw_line.split(':', 1)
        key = key.strip()
        val = val.strip()
        if val == '':
            data[key] = []
            current_key = key
        else:
            data[key] = _parse_simple_value(val)
            current_key = None
    return data


def getOrSetDefaultLang(lang):
    if not allLang:
        initLang()
    lang = normalize_lang(lang) or defaultLang
    if lang not in allLang:
        lang = lang.split('_')[0]
        if lang not in allLang:
            lang = defaultLang
    return lang


def _get_value(data, key):
    cu = data
    for item in key.split('.'):
        cu = cu[item]
    return cu


def t(params, lang=None):
    if not allLang:
        initLang()
    lang = getOrSetDefaultLang(lang if lang is not None else sysLang)
    cu = allLang[lang]
    cuDefault = allLang[defaultLang]
    try:
        return _get_value(cu, params)
    except Exception:
        try:
            return _get_value(cuDefault, params)
        except Exception:
            return params
