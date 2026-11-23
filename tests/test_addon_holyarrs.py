# -*- coding: utf-8 -*-
"""Runs the add-on's real search/download code with the HolyArrs backend, Kodi stubbed."""
import importlib
import json
import os
import sys
import unittest
from unittest import mock

from kodistubs import ROOT, install

S = install()
sys.path.insert(0, ROOT)
addon = importlib.import_module('addon')


class FakeClient(object):
    def __init__(self, results=None, found=None, saved='Nobody (2021)/Nobody (2021).hr.srt', fail=None):
        self.results, self.saved, self.fail = results or [], saved, fail
        self.found = found if found is not None else {'file_id': 11, 'relative_path': 'Nobody (2021)/Nobody (2021).mkv'}
        self.calls = []

    def find_file(self, video_path, media_type='movie', title=None, tvshow_title=None):
        self.calls.append(('find_file', video_path, media_type, title, tvshow_title))
        if self.fail == 'notfound':
            raise addon.HolyArrsItemNotFound('nope')
        if self.fail == 'down':
            raise RuntimeError('connection refused')
        return self.found

    def list_subtitles(self, file_id):
        self.calls.append(('list', file_id))
        return self.results

    def choose(self, file_id, result):
        self.calls.append(('choose', file_id, result['subtitle']))
        if self.fail == 'choose':
            raise RuntimeError('boom')
        return self.saved


def result(lang='hr', site='Titlovi', key='2', score=72, rel='Rel.A'):
    return {'language': lang, 'forced': False, 'hearing_impaired': False, 'provider': site, 'score': score,
            'release_info': rel, 'subtitle': {'site': site, 'key': key}}


def handler(query, client):
    h = addon.ActionHandler(['plugin://service.subtitles.bazarr/', '1', query])
    h.client = client
    return h


class SearchTests(unittest.TestCase):
    def setUp(self):
        S.reset()

    def test_backend_setting_picks_the_client(self):
        S.settings['backend'] = 'holyarrs'
        self.assertEqual(type(addon.ActionHandler(['p', '1', '?action=search']).client).__name__, 'HolyArrsClient')
        S.settings['backend'] = 'bazarr'
        self.assertEqual(type(addon.ActionHandler(['p', '1', '?action=search']).client).__name__, 'BazarrClient')
        S.settings['backend'] = 'garbage'
        self.assertEqual(type(addon.ActionHandler(['p', '1', '?action=search']).client).__name__, 'BazarrClient')

    def test_missing_holyarrs_settings_notify_and_stop(self):
        S.settings['holyarrs_apikey'] = ''
        h = addon.ActionHandler(['p', '1', '?action=search'])
        self.assertIsNone(h.client)
        self.assertIn('str32005', S.notifications[-1])
        h.do()
        self.assertEqual(S.items, [])

    def test_search_lists_wanted_languages_only(self):
        c = FakeClient([result('hr', key='2', score=72), result('sr', key='9', score=60), result('en', key='5', score=90)])
        handler('?action=search&languages=Croatian,Serbian', c).do()
        self.assertEqual(c.calls[0], ('find_file', '/media/movies/Nobody (2021)/Nobody (2021).mkv', 'movie', 'Nobody', None))
        self.assertEqual(c.calls[1], ('list', 11))
        self.assertEqual([i[1] for i in S.items], ['Croatian', 'Serbian'])  # English filtered out, label is a plain language name
        self.assertIn('Titlovi', S.items[0][2])
        url = S.items[0][0]
        self.assertIn('action=download', url)
        self.assertIn('%22kind%22%3A+%22holyarrs%22', url)  # context says holyarrs

    def test_episode_search_passes_show_and_path(self):
        S.playing = {'type': 'episode', 'file': '/m/series/Krypton/Season 02/Krypton 02x09 - Blood Moon.mkv'}
        S.infolabels = {'VideoPlayer.Season': '2', 'VideoPlayer.Episode': '9', 'VideoPlayer.TVShowTitle': 'Krypton'}
        c = FakeClient([result()])
        handler('?action=search&languages=Croatian', c).do()
        self.assertEqual(c.calls[0], ('find_file', '/m/series/Krypton/Season 02/Krypton 02x09 - Blood Moon.mkv', 'episode', None, 'Krypton'))
        self.assertEqual(len(S.items), 1)

    def test_nothing_to_offer_says_so(self):
        handler('?action=search&languages=Croatian', FakeClient([])).do()
        self.assertEqual(S.items, [])
        self.assertIn('str32008', S.notifications[-1])

    def test_not_found_and_unreachable_notify(self):
        handler('?action=search&languages=Croatian', FakeClient(fail='notfound')).do()
        self.assertIn('str32006', S.notifications[-1])
        handler('?action=search&languages=Croatian', FakeClient(fail='down')).do()
        self.assertIn('str32007', S.notifications[-1])
        self.assertEqual(S.items, [])

    def test_bazarr_backend_still_uses_the_bazarr_flow(self):
        S.settings['backend'] = 'bazarr'
        h = addon.ActionHandler(['p', '1', '?action=search&languages=Croatian'])
        h.client = mock.Mock()
        h.client.find_movie.return_value = (5, '/x')
        h.client.list_movie_subtitles.return_value = [{'language': 'hr', 'provider': 'p', 'release_info': 'r', 'subtitle': 's'}]
        h.do()
        h.client.find_movie.assert_called_once()
        self.assertEqual(len(S.items), 1)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        S.reset()

    def query(self, res=None, kind='holyarrs'):
        ctx = json.dumps({'kind': kind, 'file_id': 11})
        from urllib.parse import quote_plus
        return '?action=download&context=%s&result=%s&filepath=%s' % (
            quote_plus(ctx), quote_plus(json.dumps(res or result())), quote_plus('/media/movies/Nobody (2021)/Nobody (2021).mkv'))

    def test_download_chooses_and_hands_kodi_the_saved_file(self):
        S.existing = {'/media/movies/Nobody (2021)/Nobody (2021).hr.srt'}
        c = FakeClient()
        handler(self.query(), c).do()
        self.assertEqual(c.calls, [('choose', 11, {'site': 'Titlovi', 'key': '2'})])
        self.assertEqual(S.items[-1][0], '/media/movies/Nobody (2021)/Nobody (2021).hr.srt')

    def test_download_waits_for_the_share_then_gives_up(self):
        c = FakeClient()
        with mock.patch.object(addon.time, 'sleep'):
            handler(self.query(), c).do()
        self.assertEqual(S.items[-1][0], '')           # empty item = nothing for Kodi to load
        self.assertIn('str32003', S.notifications[-1])

    def test_download_failure_notifies(self):
        handler(self.query(), FakeClient(fail='choose')).do()
        self.assertEqual(S.items[-1][0], '')
        self.assertIn('str32007', S.notifications[-1])


if __name__ == '__main__':
    unittest.main()
