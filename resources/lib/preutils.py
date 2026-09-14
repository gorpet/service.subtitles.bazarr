# -*- coding: utf-8 -*-
try:
    from urllib.parse import parse_qs, quote_plus
except ImportError:  # Kodi Leia and earlier (Python 2)
    from urlparse import parse_qs
    from urllib import quote_plus

import xbmc


def get_params(raw_query):
    """Kodi passes the plugin invocation query string (with the leading
    '?') as sys.argv[2]. Turn it into a {key: [values]} dict the same way
    the stock subtitle addons do."""
    query = raw_query
    if query.startswith('?'):
        query = query[1:]
    return parse_qs(query)


def get_quoted_str(value):
    return quote_plus(value if value is not None else '')


def kodi_langs_to_iso639_1(languages_csv):
    """The 'languages' plugin param is a comma-separated list of Kodi
    English language names (e.g. 'English,Croatian,Serbian'). Convert each
    to a lowercase ISO 639-1 code Bazarr's API expects, dropping any Kodi
    can't map."""
    codes = []
    for name in languages_csv.split(','):
        name = name.strip()
        if not name:
            continue
        code = xbmc.convertLanguage(name, xbmc.ISO_639_1)
        if code:
            codes.append(code.lower())
    return codes


def path_stem(path):
    """'/media/tv/Show/S01E02.mkv' -> 'S01E02' - used to loosely match a
    freshly-written subtitle file to the video it belongs to."""
    base = path.replace('\\', '/').rsplit('/', 1)[-1]
    return base.rsplit('.', 1)[0] if '.' in base else base


def dir_of(path):
    norm = path.replace('\\', '/')
    return norm.rsplit('/', 1)[0] if '/' in norm else '.'
