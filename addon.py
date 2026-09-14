# -*- coding: utf-8 -*-

import json
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

__addon__ = xbmcaddon.Addon()
__dialog__ = xbmcgui.Dialog()
__player__ = xbmc.Player()
__addonname__ = __addon__.getAddonInfo('name')
__addonid__ = __addon__.getAddonInfo('id')
get_local_str = __addon__.getLocalizedString

__cwd__ = xbmcvfs.translatePath(__addon__.getAddonInfo('path'))
__resource__ = xbmcvfs.translatePath(os.path.join(__cwd__, 'resources', 'lib'))
sys.path.append(__resource__)

from prelogging import Prelogger  # noqa: E402
import preutils as pu  # noqa: E402
from bazarr import (  # noqa: E402
    BazarrClient, BazarrNotConfigured, BazarrItemNotFound, wait_for_subtitle_file,
)

try:
    import requests
except ImportError:
    requests = None


class ActionHandler(object):

    def __init__(self, raw_params):
        self.log = Prelogger()
        self.params = pu.get_params(raw_params[2])
        self.action = self.params['?action'][0] if '?action' in self.params else self.params.get('action', [None])[0]
        self.handle = int(raw_params[1])
        self.log.debug("Action='{0}' params={1}".format(self.action, self.params))

        self.ACTION_MAP = {
            'search': self.search,
            'manualsearch': self.manual_search,
            'download': self.download,
        }

        self.client = self._build_client()

    def _build_client(self):
        base_url = __addon__.getSetting('bazarr_url')
        api_key = __addon__.getSetting('bazarr_apikey')
        try:
            verify_ssl = __addon__.getSettingBool('verify_ssl')
        except Exception:
            verify_ssl = __addon__.getSetting('verify_ssl') != 'false'
        try:
            return BazarrClient(base_url, api_key, verify_ssl=verify_ssl)
        except BazarrNotConfigured:
            self.notify(get_local_str(32000))
            return None

    def notify(self, message):
        xbmc.executebuiltin('Notification({0}, {1})'.format(__addonname__, message))
        self.log.warning(message)

    def do(self):
        if self.action not in self.ACTION_MAP:
            self.notify(get_local_str(32000))
            return
        if self.client is None:
            return
        self.ACTION_MAP[self.action]()

    # -----------------------------------------------------------------
    # search - list available subtitles for the item Kodi is asking about
    # -----------------------------------------------------------------

    def search(self):
        show = self.get_current_show()
        wanted_langs = pu.kodi_langs_to_iso639_1(self.params.get('languages', [''])[0])
        self.log.debug("Current show: {0}, wanted langs: {1}".format(show, wanted_langs))

        try:
            if show['type'] == 'episode':
                series_id = self.client.find_series_id(tvdb_id=show.get('tvdb_id'), title=show.get('tvshow_title'))
                episode_id, _ = self.client.find_episode(series_id, show['season'], show['episode'])
                results = self.client.list_episode_subtitles(series_id, episode_id)
                context = {'kind': 'episode', 'series_id': series_id, 'episode_id': episode_id}
            else:
                radarr_id, _ = self.client.find_movie(imdb_id=show.get('imdb_id'), title=show.get('title'),
                                                        year=show.get('year'))
                results = self.client.list_movie_subtitles(radarr_id)
                context = {'kind': 'movie', 'radarr_id': radarr_id}
        except BazarrItemNotFound as exc:
            self.log.warning(str(exc))
            self.notify(get_local_str(32002))
            return
        except Exception as exc:  # noqa: BLE001 - surface any transport error to the user
            self.log.error("Bazarr request failed: {0}".format(exc))
            self.notify(get_local_str(32001))
            return

        # NOTE: verify what format Bazarr's 'language' field is actually in
        # (alpha2 'hr' vs alpha3 'hrv' vs full name) against your instance
        # and adjust this comparison if nothing matches despite results
        # existing.
        if wanted_langs:
            results = [r for r in results if str(r.get('language', '')).lower()[:2] in wanted_langs]

        if not results:
            self.notify(get_local_str(32004))
            return

        for result in results:
            self._add_search_result_item(show, context, result)

    def manual_search(self):
        # Bazarr's manual-search endpoints don't take a free-text query -
        # they search using the library item's own metadata. A typed search
        # term has nothing to bind to on the Bazarr side, so just re-run the
        # normal search.
        self.search()

    def _add_search_result_item(self, show, context, result):
        lang_code = str(result.get('language', ''))
        kodi_lang_name = xbmc.convertLanguage(lang_code, xbmc.ENGLISH_NAME) or lang_code
        # 'label' must be a plain language name/code - Kodi's C++ subtitle
        # dialog parses THIS field (via CLangCodeExpander::ConvertToISO6391)
        # to build the destination filename when saving to the movie folder.
        # Anything else here (provider, brackets, etc.) makes that parse
        # fail and produces a language-less filename instead of matching
        # Bazarr's own naming.
        label = kodi_lang_name
        label2 = "[B]{0} - {1}[/B]".format(result.get('provider') or '', result.get('release_info') or '')
        list_item = xbmcgui.ListItem(label=label, label2=label2)
        kodi_lang = xbmc.convertLanguage(lang_code, xbmc.ISO_639_1) or lang_code
        list_item.setArt({'thumb': kodi_lang})

        plugin_url = "plugin://{0}/?action=download&context={1}&result={2}&filepath={3}".format(
            __addonid__,
            pu.get_quoted_str(json.dumps(context)),
            pu.get_quoted_str(json.dumps(result, default=str)),
            pu.get_quoted_str(show['file_original_path']),
        )
        xbmcplugin.addDirectoryItem(handle=self.handle, url=plugin_url, listitem=list_item, isFolder=False)

    # -----------------------------------------------------------------
    # download - tell Bazarr to fetch the chosen result, then find the file
    # -----------------------------------------------------------------

    def download(self):
        context = json.loads(self.params['context'][0])
        result = json.loads(self.params['result'][0])
        video_path = self.params['filepath'][0]

        try:
            if context['kind'] == 'episode':
                self.client.download_episode_subtitle(context['series_id'], context['episode_id'], result)
            else:
                self.client.download_movie_subtitle(context['radarr_id'], result)
        except Exception as exc:  # noqa: BLE001
            self.log.error("Bazarr download call failed: {0}".format(exc))
            self.notify(get_local_str(32001))
            self.add_subtitle_dir_item('')
            return

        try:
            wait_seconds = __addon__.getSettingInt('download_wait_seconds')
        except Exception:
            wait_seconds = int(__addon__.getSetting('download_wait_seconds') or 8)

        video_dir = pu.dir_of(video_path)
        video_stem = pu.path_stem(video_path)
        lang_code = str(result.get('language', ''))

        def list_dir(path):
            _dirs, files = xbmcvfs.listdir(path)
            return files

        found_name = wait_for_subtitle_file(list_dir, video_dir, video_stem, lang_code, wait_seconds)
        if not found_name:
            self.log.warning("Bazarr accepted the download but no new subtitle file appeared under {0} within {1}s"
                              .format(video_dir, wait_seconds))
            self.notify(get_local_str(32003))
            self.add_subtitle_dir_item('')
            return

        subtitle_path = video_dir.rstrip('/') + '/' + found_name
        self.add_subtitle_dir_item(subtitle_path)

    def add_subtitle_dir_item(self, subtitle_path):
        list_item = xbmcgui.ListItem(label=subtitle_path)
        xbmcplugin.addDirectoryItem(handle=self.handle, url=subtitle_path, listitem=list_item, isFolder=False)

    # -----------------------------------------------------------------
    # figure out what's currently playing / focused, same approach the
    # original titlovi-cobric addon used
    # -----------------------------------------------------------------

    def get_current_show(self):
        item = {}
        if __player__.isPlaying():
            tag = __player__.getVideoInfoTag()
            media_type = tag.getMediaType()
            item['type'] = media_type
            item['file_original_path'] = __player__.getPlayingFile()

            if media_type == 'episode':
                item['season'] = int(xbmc.getInfoLabel("VideoPlayer.Season") or 0)
                item['episode'] = int(xbmc.getInfoLabel("VideoPlayer.Episode") or 0)
                item['tvshow_title'] = xbmc.getInfoLabel("VideoPlayer.TVShowTitle").replace(':', '')
                episode_id = tag.getDbId()
                episode_details = self._json_rpc('VideoLibrary.GetEpisodeDetails', {
                    'episodeid': episode_id, 'properties': ['tvshowid']})
                tvshow_id = episode_details['episodedetails']['tvshowid']
                show_details = self._json_rpc('VideoLibrary.GetTVShowDetails', {
                    'tvshowid': tvshow_id, 'properties': ['uniqueid']})
                unique_ids = show_details['tvshowdetails'].get('uniqueid', {})
                item['tvdb_id'] = unique_ids.get('tvdb')
                item['imdb_id'] = unique_ids.get('imdb')
            elif media_type == 'movie':
                item['imdb_id'] = tag.getUniqueID('imdb')
                item['year'] = tag.getYear()
                item['title'] = tag.getTitle()
        else:
            item = self._get_current_show_from_focused_item()

        self.log.debug("Resolved current show: {0}".format(item))
        return item

    def _get_current_show_from_focused_item(self):
        media_type = xbmc.getInfoLabel("ListItem.DBTYPE")
        is_episode = media_type == 'episode' or xbmc.getCondVisibility("Container.Content(episodes)")
        item = {
            'file_original_path': xbmc.getInfoLabel("ListItem.FileNameAndPath"),
        }
        if is_episode:
            item['type'] = 'episode'
            item['season'] = int(xbmc.getInfoLabel("ListItem.Season") or 0)
            item['episode'] = int(xbmc.getInfoLabel("ListItem.Episode") or 0)
            item['tvshow_title'] = xbmc.getInfoLabel("ListItem.TVShowTitle").replace(':', '')
            item['tvdb_id'] = None  # not reliably available for a focused (non-playing) episode item
            item['imdb_id'] = None
        else:
            item['type'] = 'movie'
            item['title'] = xbmc.getInfoLabel("ListItem.Title") or xbmc.getInfoLabel("ListItem.OriginalTitle")
            item['year'] = xbmc.getInfoLabel("ListItem.Year")
            item['imdb_id'] = None
        return item

    @staticmethod
    def _json_rpc(method, params):
        request = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        if 'error' in response:
            raise RuntimeError("JSON-RPC {0} failed: {1}".format(method, response['error']))
        return response['result']


if __name__ == '__main__':
    handler = ActionHandler(sys.argv)
    handler.do()
    xbmcplugin.endOfDirectory(int(sys.argv[1]))
