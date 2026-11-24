# -*- coding: utf-8 -*-
"""
Thin client for the HolyArrs REST API (/api/v1, key in the X-Api-Key header).

Same job as bazarr.py, but HolyArrs has no ids that Kodi knows about, so the
playing file is found by PATH: the library lists every file with a path
relative to its library folder ("Nobody (2021)/Nobody (2021).mkv"), and Kodi's
playing path ends with it (the two share the same mount).

Calls used:
  GET  /api/v1/titles?q=<text>                 find titles (substring match)
  GET  /api/v1/titles/{id}/subtitles           the title's files and their relative paths
  POST /api/v1/files/{id}/subtitles/choices    ask every subtitle site now, list the scored
                                               candidates, save nothing
  POST /api/v1/files/{id}/subtitles/choose     {"site", "key"}: save one candidate beside the
                                               video, answers {"path": ...}
  PUT  /api/v1/titles/{id}/subtitle-wish       {"item_id", "languages": [...]} or {"item_id", "inherit": true}:
                                               one file's own wish, so a language outside the global
                                               wish can be searched on demand

Good to know:
  * "choices" lists candidates for the languages the file is MISSING and for
    subtitles HolyArrs itself saved earlier (so a hand pick can swap them). It
    does not re-ask for a subtitle that came from elsewhere (e.g. Bazarr).
  * Candidates are scored 0-100; a "refused" one (wrong title) is left out.
The API key needs the library-management permission (a key with the "all" scope has it).
"""

import re

try:
    from urllib.parse import unquote
except ImportError:  # Kodi Leia and earlier (Python 2)
    from urllib import unquote

import requests

from prelogging import Prelogger


class HolyArrsError(Exception):
    pass


class HolyArrsNotConfigured(HolyArrsError):
    pass


class HolyArrsItemNotFound(HolyArrsError):
    pass


_YEAR_TAIL = re.compile(r'\s*[\(\[]\d{4}[\)\]]\s*$')
_ID_TAIL = re.compile(r'\s*\{[a-z]+-[^}]*\}\s*$', re.I)
_SEASON_DIR = re.compile(r'^(season|series|saison|staffel|sezona|s)\s*\d+$|^specials?$', re.I)
_MAX_TITLES_PER_TERM = 8


def normalize_path(path):
    """Lower-case, forward slashes, percent-escapes undone (smb:// and nfs://
    paths can come back escaped), no trailing slash."""
    p = unquote(path or '').replace('\\', '/').strip().rstrip('/')
    return p.lower()


def path_matches(video_path, relative_path):
    """True when the video path ends with the library-relative path."""
    v, r = normalize_path(video_path), normalize_path(relative_path).lstrip('/')
    return bool(r) and (v == r or v.endswith('/' + r))


def search_terms(title=None, tvshow_title=None, video_path=None, media_type='movie'):
    """Names to look the title up by, best first: the title Kodi knows, then
    the folder names the file lives in (a movie's folder, a show's folder two
    levels up), with a trailing "(2021)" or "{tmdb-1}" taken off."""
    names = [tvshow_title if media_type == 'episode' else title]
    parts = [x for x in normalize_path_keep_case(video_path).split('/') if x]
    if media_type == 'episode':
        # The show's folder: one up from the file, or two up when a Season folder sits between.
        if len(parts) >= 3 and _SEASON_DIR.match(parts[-2]):
            names.append(parts[-3])
        elif len(parts) >= 2:
            names.append(parts[-2])
    elif len(parts) >= 2:
        names.append(parts[-2])
    out = []
    for n in names:
        n = _YEAR_TAIL.sub('', _ID_TAIL.sub('', n or '')).strip()
        if n and n.lower() not in [o.lower() for o in out]:
            out.append(n)
    return out


def normalize_path_keep_case(path):
    return unquote(path or '').replace('\\', '/').strip().rstrip('/')


class HolyArrsClient(object):

    def __init__(self, base_url, api_key, verify_ssl=True, timeout=60):
        if not base_url or not api_key:
            raise HolyArrsNotConfigured("HolyArrs URL or API key is not configured")
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.log = Prelogger()
        self.sess = requests.Session()
        self.sess.headers.update({'X-Api-Key': self.api_key})

    # ---------------------------------------------------------------
    # low level helpers
    # ---------------------------------------------------------------

    def _get(self, path, params=None):
        url = '{0}/api/v1{1}'.format(self.base_url, path)
        self.log.debug("GET {0} params={1}".format(url, params))
        r = self.sess.get(url, params=params or {}, timeout=self.timeout, verify=self.verify_ssl)
        r.raise_for_status()
        return r.json()

    def _post(self, path, payload=None):
        url = '{0}/api/v1{1}'.format(self.base_url, path)
        self.log.debug("POST {0} json={1}".format(url, payload))
        r = self.sess.post(url, json=payload, timeout=self.timeout, verify=self.verify_ssl)
        r.raise_for_status()
        return r.json() if r.content else {}

    def _put(self, path, payload=None):
        url = '{0}/api/v1{1}'.format(self.base_url, path)
        self.log.debug("PUT {0} json={1}".format(url, payload))
        r = self.sess.put(url, json=payload, timeout=self.timeout, verify=self.verify_ssl)
        r.raise_for_status()
        return r.json() if r.content else {}

    # ---------------------------------------------------------------
    # find the file Kodi is playing
    # ---------------------------------------------------------------

    def find_file(self, video_path, media_type='movie', title=None, tvshow_title=None):
        """Return {'file_id', 'relative_path', 'title_id', 'title'} for the file
        whose library path the video path ends with."""
        tried = []
        for term in search_terms(title, tvshow_title, video_path, media_type):
            tried.append(term)
            data = self._get('/titles', params={'q': term})
            for t in (data.get('titles') or [])[:_MAX_TITLES_PER_TERM]:
                wanted_kind = 'movie' if media_type == 'movie' else 'show'
                if t.get('kind') and t.get('kind') != wanted_kind:
                    continue
                files = self._get('/titles/{0}/subtitles'.format(t['id'])).get('files') or []
                for f in files:
                    if path_matches(video_path, f.get('relative_path')):
                        wish = (f.get('wish') or {}).get('languages') or []
                        return {'file_id': f['file_id'], 'item_id': f.get('item_id'), 'relative_path': f['relative_path'],
                                'title_id': t['id'], 'title': t.get('name'), 'wish': wish}
        raise HolyArrsItemNotFound("No HolyArrs file ends like {0!r} (looked up: {1})".format(video_path, tried))

    # ---------------------------------------------------------------
    # asking for a language the wish does not name
    # ---------------------------------------------------------------

    def ensure_languages(self, found, wanted):
        """Make the file's wish name the languages asked for in Kodi.

        HolyArrs lists, and saves, candidates only for languages in the file's wish. With
        a short global wish (say only Croatian) a person asking Kodi for Bosnian would get
        nothing, so the missing languages are added to this ONE file's wish (the item's
        own wish, the global setting is not touched) and the wish is kept until the pick
        is saved. Returns the language codes that were added; clear_wish() removes them."""
        have = [w.get('language') for w in found.get('wish') or []]
        extra = []
        for code in wanted or []:
            code = (code or '').lower()
            if code and code not in have and code not in extra:
                extra.append(code)
        if not extra or not found.get('item_id'):
            return []
        entries = [dict(w) for w in found.get('wish') or []] + [{'language': c} for c in extra]
        self._put('/titles/{0}/subtitle-wish'.format(found['title_id']), {'item_id': found['item_id'], 'languages': entries})
        return extra

    def clear_wish(self, title_id, item_id):
        """Drop the file's own wish so it follows the global one again."""
        self._put('/titles/{0}/subtitle-wish'.format(title_id), {'item_id': item_id, 'inherit': True})

    # ---------------------------------------------------------------
    # manual search and download
    # ---------------------------------------------------------------

    def list_subtitles(self, file_id):
        """Ask the subtitle sites now and return the candidates, best first,
        shaped like the Bazarr client's results. Nothing is saved."""
        data = self._post('/files/{0}/subtitles/choices'.format(file_id))
        results = []
        for outcome in data.get('outcomes') or []:
            for c in outcome.get('choices') or []:
                score = c.get('score') or {}
                if score.get('refused'):
                    continue
                results.append({
                    'language': c.get('language'),
                    'forced': bool(c.get('forced')),
                    'hearing_impaired': bool(c.get('hearing_impaired')),
                    'provider': c.get('site'),
                    'score': score.get('total'),
                    'release_info': ' / '.join(c.get('release_names') or []),
                    # What "choose" wants back to identify the candidate.
                    'subtitle': {'site': c.get('site'), 'key': c.get('key')},
                })
        results.sort(key=lambda r: -(r['score'] or 0))
        return results

    def choose(self, file_id, result):
        """Save one candidate beside the video; returns the saved file's path
        as HolyArrs reports it."""
        sub = result['subtitle']
        data = self._post('/files/{0}/subtitles/choose'.format(file_id), {'site': sub['site'], 'key': sub['key']})
        return data.get('path')
