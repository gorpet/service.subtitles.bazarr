# -*- coding: utf-8 -*-
"""Just enough of Kodi's Python modules to import the add-on and run its search/download
paths on a desktop Python. Not a Kodi emulator."""
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'resources', 'lib'))


class State(object):
    settings = {}
    infolabels = {}
    notifications = []
    log = []
    items = []          # xbmcplugin.addDirectoryItem calls: (url, label, label2)
    existing = set()    # paths xbmcvfs.exists() answers True for
    playing = {}
    langs = {'croatian': 'hr', 'english': 'en', 'serbian': 'sr', 'bosnian': 'bs'}

    @classmethod
    def reset(cls):
        cls.settings = {'backend': 'holyarrs', 'holyarrs_url': 'http://h', 'holyarrs_apikey': 'k',
                        'bazarr_url': 'http://b', 'bazarr_apikey': 'k', 'verify_ssl': 'true',
                        'download_wait_seconds': '1', 'debug_logging': 'false'}
        cls.notifications, cls.log, cls.items, cls.existing = [], [], [], set()
        cls.playing = {'type': 'movie', 'file': '/media/movies/Nobody (2021)/Nobody (2021).mkv',
                       'title': 'Nobody', 'year': 2021, 'imdb': 'tt7888964'}


def install():
    S = State
    S.reset()
    xbmc = types.ModuleType('xbmc')
    xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 0, 1, 2, 3
    xbmc.ENGLISH_NAME, xbmc.ISO_639_1 = 'english', 'iso1'
    xbmc.log = lambda msg, level=0: S.log.append(msg)
    xbmc.executebuiltin = lambda cmd: S.notifications.append(cmd)
    xbmc.getInfoLabel = lambda label: S.infolabels.get(label, '')
    xbmc.getCondVisibility = lambda cond: False
    def rpc(req):
        method = json.loads(req)['method']
        result = {'VideoLibrary.GetEpisodeDetails': {'episodedetails': {'tvshowid': 1}},
                  'VideoLibrary.GetTVShowDetails': {'tvshowdetails': {'uniqueid': {'tvdb': '296762', 'imdb': 'tt5000000'}}}}.get(method, {})
        return json.dumps({'result': result})
    xbmc.executeJSONRPC = rpc

    def convert(name, fmt):
        n = str(name).strip().lower()
        if fmt == xbmc.ISO_639_1:
            return S.langs.get(n) or (n if n in S.langs.values() else '')
        rev = {v: k.capitalize() for k, v in S.langs.items()}
        return rev.get(n, '')
    xbmc.convertLanguage = convert

    class Tag(object):
        def getMediaType(self): return S.playing['type']
        def getUniqueID(self, k): return S.playing.get(k, '')
        def getYear(self): return S.playing.get('year', 0)
        def getTitle(self): return S.playing.get('title', '')
        def getDbId(self): return 1

    class Player(object):
        def isPlaying(self): return True
        def getVideoInfoTag(self): return Tag()
        def getPlayingFile(self): return S.playing['file']
    xbmc.Player = Player

    xbmcaddon = types.ModuleType('xbmcaddon')

    class Addon(object):
        def getAddonInfo(self, k): return {'path': ROOT, 'name': 'Bazarr', 'id': 'service.subtitles.bazarr'}.get(k, '')
        def getSetting(self, k): return S.settings.get(k, '')
        def getSettingBool(self, k): return S.settings.get(k) == 'true'
        def getSettingInt(self, k): return int(S.settings.get(k) or 0)
        def getLocalizedString(self, i): return 'str%d' % i
    xbmcaddon.Addon = Addon

    xbmcgui = types.ModuleType('xbmcgui')

    class ListItem(object):
        def __init__(self, label='', label2=''): self.label, self.label2 = label, label2
        def setArt(self, art): self.art = art
    xbmcgui.ListItem = ListItem
    xbmcgui.Dialog = lambda: types.SimpleNamespace()

    xbmcplugin = types.ModuleType('xbmcplugin')
    xbmcplugin.addDirectoryItem = lambda handle, url, listitem, isFolder=False: S.items.append((url, listitem.label, listitem.label2))
    xbmcplugin.endOfDirectory = lambda h: None

    xbmcvfs = types.ModuleType('xbmcvfs')
    xbmcvfs.translatePath = lambda p: p
    xbmcvfs.exists = lambda p: p in S.existing
    xbmcvfs.listdir = lambda d: ([], [])

    for name, mod in (('xbmc', xbmc), ('xbmcaddon', xbmcaddon), ('xbmcgui', xbmcgui), ('xbmcplugin', xbmcplugin), ('xbmcvfs', xbmcvfs)):
        sys.modules[name] = mod
    return S
