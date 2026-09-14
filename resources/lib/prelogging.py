# -*- coding: utf-8 -*-
import xbmc
import xbmcaddon

__addon__ = xbmcaddon.Addon()
__addonid__ = __addon__.getAddonInfo('id')


class Prelogger(object):
    """Small wrapper around xbmc.log so call sites read like a normal
    logger while everything still ends up in kodi.log with a consistent
    prefix and level. Debug messages are suppressed unless the addon's
    'debug_logging' setting is on."""

    def __init__(self):
        self.prefix = '[{0}] '.format(__addonid__)

    def _debug_enabled(self):
        try:
            return __addon__.getSettingBool('debug_logging')
        except Exception:
            return __addon__.getSetting('debug_logging') == 'true'

    def debug(self, msg):
        if self._debug_enabled():
            xbmc.log(self.prefix + str(msg), level=xbmc.LOGDEBUG)

    def info(self, msg):
        xbmc.log(self.prefix + str(msg), level=xbmc.LOGINFO)

    def notice(self, msg):
        self.info(msg)

    def warning(self, msg):
        xbmc.log(self.prefix + str(msg), level=xbmc.LOGWARNING)

    def error(self, msg):
        xbmc.log(self.prefix + str(msg), level=xbmc.LOGERROR)
