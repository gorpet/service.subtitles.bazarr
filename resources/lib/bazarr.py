# -*- coding: utf-8 -*-
"""
Thin client for the Bazarr REST API.

Bazarr only knows about media that Sonarr/Radarr have indexed, so every
lookup here goes through Bazarr's own copy of the library (its /api/series,
/api/episodes, /api/movies endpoints) rather than talking to Sonarr/Radarr
directly.

VERIFY-BEFORE-RELYING-ON note
------------------------------
Two parts of this file are best-effort reconstructions, not confirmed
against a live Bazarr install:

  1. The exact JSON field names of a manual-search result item, in
     `list_episode_subtitles` / `list_movie_subtitles`.
  2. The exact POST body Bazarr expects on `/api/episodes/subtitles` and
     `/api/movies/subtitles` to trigger a download of one chosen result.

Everything else here (auth, /api/series, /api/episodes, /api/movies shape)
matches Bazarr's published source layout.

To verify/fix the two flagged spots: open ``http://<bazarr-host>:6767/api``
in a browser (Bazarr, being a flask-restx app, serves interactive Swagger
docs there), expand the "Providers" and "Episodes/Movies" -> "subtitles"
sections, and compare their request/response models against
`_parse_search_result` and `_download_payload` below. Adjust the key names
there to match - the rest of the flow (id resolution, polling for the
written file) does not need to change.
"""

import time

import requests

from prelogging import Prelogger


class BazarrError(Exception):
    pass


class BazarrNotConfigured(BazarrError):
    pass


class BazarrItemNotFound(BazarrError):
    pass


class BazarrClient(object):

    def __init__(self, base_url, api_key, verify_ssl=True, timeout=15):
        if not base_url or not api_key:
            raise BazarrNotConfigured("Bazarr URL or API key is not configured")
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.log = Prelogger()
        self.sess = requests.Session()
        self.sess.headers.update({'X-API-KEY': self.api_key})

    # ---------------------------------------------------------------
    # low level helpers
    # ---------------------------------------------------------------

    def _get(self, path, params=None):
        url = '{0}{1}'.format(self.base_url, path)
        self.log.debug("GET {0} params={1}".format(url, params))
        r = self.sess.get(url, params=params or {}, timeout=self.timeout, verify=self.verify_ssl)
        r.raise_for_status()
        return r.json()

    def _post(self, path, data=None):
        url = '{0}{1}'.format(self.base_url, path)
        self.log.debug("POST {0} data={1}".format(url, data))
        r = self.sess.post(url, data=data or {}, timeout=self.timeout, verify=self.verify_ssl)
        r.raise_for_status()
        return r

    # ---------------------------------------------------------------
    # id resolution - Bazarr's own copy of the Sonarr/Radarr library
    # ---------------------------------------------------------------

    def find_series_id(self, tvdb_id=None, imdb_id=None, title=None):
        data = self._get('/api/series')
        for series in data.get('data', []):
            if tvdb_id and str(series.get('tvdbId')) == str(tvdb_id):
                return series.get('sonarrSeriesId')
            if imdb_id and series.get('imdbId') == imdb_id:
                return series.get('sonarrSeriesId')
        if title:
            title_lower = title.lower()
            for series in data.get('data', []):
                if str(series.get('title', '')).lower() == title_lower:
                    return series.get('sonarrSeriesId')
        raise BazarrItemNotFound("Series not found in Bazarr (tvdb={0}, imdb={1}, title={2})".format(
            tvdb_id, imdb_id, title))

    def find_episode(self, series_id, season, episode):
        data = self._get('/api/episodes', params={'seriesid[]': series_id})
        for ep in data.get('data', []):
            if int(ep.get('season', -1)) == int(season) and int(ep.get('episode', -1)) == int(episode):
                return ep.get('sonarrEpisodeId'), ep.get('path')
        raise BazarrItemNotFound("Episode S{0}E{1} not found under series id {2}".format(
            season, episode, series_id))

    def find_movie(self, imdb_id=None, title=None, year=None):
        data = self._get('/api/movies')
        for movie in data.get('data', []):
            if imdb_id and movie.get('imdbId') == imdb_id:
                return movie.get('radarrId'), movie.get('path')
        if title:
            title_lower = title.lower()
            for movie in data.get('data', []):
                if str(movie.get('title', '')).lower() == title_lower and (
                        not year or str(movie.get('year')) == str(year)):
                    return movie.get('radarrId'), movie.get('path')
        raise BazarrItemNotFound("Movie not found in Bazarr (imdb={0}, title={1}, year={2})".format(
            imdb_id, title, year))

    # ---------------------------------------------------------------
    # manual search - confirmed against bazarr/api/providers/providers_episodes.py
    # and providers_movies.py (morpheus65535/bazarr, master branch)
    # ---------------------------------------------------------------

    def list_episode_subtitles(self, series_id, episode_id):
        # GET /api/providers/episodes only takes episodeid - seriesid isn't
        # part of this endpoint's request parser.
        data = self._get('/api/providers/episodes', params={'episodeid': episode_id})
        return [self._parse_search_result(item) for item in data.get('data', [])]

    def list_movie_subtitles(self, radarr_id):
        data = self._get('/api/providers/movies', params={'radarrid': radarr_id})
        return [self._parse_search_result(item) for item in data.get('data', [])]

    @staticmethod
    def _parse_search_result(item):
        """Normalize one manual-search result per ProviderEpisodesGetResponse /
        ProviderMoviesGetResponse. Two fields are NOT what a first guess would
        expect: 'release_info' is a list of strings (not one string), and
        'forced' / 'hearing_impaired' / 'original_format' come back as the
        literal strings "True"/"False" (not JSON booleans)."""
        return {
            'language': item.get('language'),
            'forced': str(item.get('forced')).lower() == 'true',
            'hearing_impaired': str(item.get('hearing_impaired')).lower() == 'true',
            'original_format': str(item.get('original_format')).lower() == 'true',
            'provider': item.get('provider'),
            'score': item.get('score'),
            'release_info': ' / '.join(item.get('release_info') or []),
            'matches': item.get('matches'),
            'dont_matches': item.get('dont_matches'),
            # Opaque handle Bazarr expects back verbatim to identify which
            # result to actually download.
            'subtitle': item.get('subtitle'),
        }

    # ---------------------------------------------------------------
    # download - this is a POST to the SAME path as the manual search GET,
    # not /api/episodes|movies/subtitles (that pair is for uploading a local
    # file, and requires multipart 'file' - sending form fields there is
    # what produced the 400).
    # ---------------------------------------------------------------

    def download_episode_subtitle(self, series_id, episode_id, result):
        payload = self._download_payload(result)
        payload['seriesid'] = series_id
        payload['episodeid'] = episode_id
        self._post('/api/providers/episodes', data=payload)

    def download_movie_subtitle(self, radarr_id, result):
        payload = self._download_payload(result)
        payload['radarrid'] = radarr_id
        self._post('/api/providers/movies', data=payload)

    @staticmethod
    def _download_payload(result):
        def bool_str(value):
            return 'True' if value else 'False'

        return {
            'hi': bool_str(result.get('hearing_impaired')),
            'forced': bool_str(result.get('forced')),
            # Forced to False regardless of what the search result reports -
            # true here appears to make Bazarr write a second, language-less
            # copy alongside the normally-named one. Revert to
            # bool_str(result.get('original_format')) once that's confirmed
            # one way or the other via Bazarr's own history/log.
            'original_format': 'False',
            'provider': result['provider'],
            'subtitle': result['subtitle'],
        }


def wait_for_subtitle_file(list_dir_fn, video_dir, video_stem, lang_code, timeout_seconds, poll_interval=1):
    """Poll a directory for a subtitle file that (a) appeared after we asked
    Bazarr to download one and (b) looks like it belongs to this video and
    language. `list_dir_fn` is injected so this module stays free of Kodi
    imports (xbmcvfs) and can be unit tested on a desktop Python."""
    deadline = time.time() + timeout_seconds
    before = set(list_dir_fn(video_dir))
    while time.time() < deadline:
        time.sleep(poll_interval)
        after = set(list_dir_fn(video_dir))
        new_files = after - before
        for name in new_files:
            lower = name.lower()
            if not lower.endswith(('.srt', '.ass', '.ssa', '.sub', '.vtt')):
                continue
            if video_stem.lower() in lower or lang_code.lower() in lower:
                return name
        # keep growing "before" in case Bazarr writes a temp file first
        before = after
    return None
