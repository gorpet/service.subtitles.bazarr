# -*- coding: utf-8 -*-
import unittest
from unittest import mock

from kodistubs import install

install()
import holyarrs  # noqa: E402
from holyarrs import HolyArrsClient, HolyArrsItemNotFound, HolyArrsNotConfigured  # noqa: E402


class FakeResp(object):
    def __init__(self, data):
        self.data, self.content = data, b'x'

    def raise_for_status(self): pass
    def json(self): return self.data


def client_with(routes):
    """routes: {(method, path): json or callable(params/json) -> json}; records every call."""
    c = HolyArrsClient('http://h/', 'key')
    c.calls = []

    def route(method, url, **kw):
        path = url.split('/api/v1', 1)[1]
        c.calls.append((method, path, kw.get('params') or kw.get('json')))
        r = routes[(method, path)]
        return FakeResp(r(kw) if callable(r) else r)
    c.sess = mock.Mock()
    c.sess.get = lambda url, **kw: route('GET', url, **kw)
    c.sess.post = lambda url, **kw: route('POST', url, **kw)
    c.sess.put = lambda url, **kw: route('PUT', url, **kw)
    return c


class PathTests(unittest.TestCase):
    def test_match_is_a_path_suffix_case_and_escape_insensitive(self):
        rel = 'Nobody (2021)/Nobody (2021).mkv'
        for video in ('/media/movies/Nobody (2021)/Nobody (2021).mkv',
                      'smb://nas/StorageOne/movies/Nobody%20(2021)/Nobody%20(2021).mkv',
                      'nfs://10.10.1.10/StorageOne/MOVIES/nobody (2021)/NOBODY (2021).MKV',
                      'D:\\Movies\\Nobody (2021)\\Nobody (2021).mkv', rel):
            self.assertTrue(holyarrs.path_matches(video, rel), video)
        self.assertFalse(holyarrs.path_matches('/media/Nobody (2021)/Other.mkv', rel))
        self.assertFalse(holyarrs.path_matches('/media/xNobody (2021)/Nobody (2021).mkv', rel))  # whole folder names only
        self.assertFalse(holyarrs.path_matches('/media/a.mkv', ''))

    def test_search_terms(self):
        self.assertEqual(holyarrs.search_terms('Nobody', None, '/m/movies/Nobody (2021)/Nobody (2021).mkv', 'movie'), ['Nobody'])
        self.assertEqual(holyarrs.search_terms('Wolfs: Redux', None, '/m/Wolfs (2024)/Wolfs (2024).mkv', 'movie'), ['Wolfs: Redux', 'Wolfs'])
        self.assertEqual(holyarrs.search_terms(None, 'Krypton', '/m/series/Krypton/Season 02/Krypton 02x09.mkv', 'episode'), ['Krypton'])
        self.assertEqual(holyarrs.search_terms(None, 'Krypton (2018)', '/m/series/Krypton/Season 02/k.mkv', 'episode'), ['Krypton'])  # "(2018)" is dropped, the folder name adds nothing new
        self.assertEqual(holyarrs.search_terms(None, 'The Show', '/m/series/The Show (2010)/The Show 01x01.mkv', 'episode'), ['The Show'])
        self.assertEqual(holyarrs.search_terms('X', None, '/m/Movie (2020) {tmdb-5}/f.mkv', 'movie'), ['X', 'Movie'])


class ClientTests(unittest.TestCase):
    def test_not_configured(self):
        with self.assertRaises(HolyArrsNotConfigured):
            HolyArrsClient('', 'k')
        with self.assertRaises(HolyArrsNotConfigured):
            HolyArrsClient('http://h', '')

    def test_key_header_and_base_url(self):
        c = HolyArrsClient('http://h/', 'secret')
        self.assertEqual(c.sess.headers['X-Api-Key'], 'secret')
        self.assertEqual(c.base_url, 'http://h')

    def test_find_file_by_path_skips_other_titles_and_kinds(self):
        c = client_with({
            ('GET', '/titles'): {'titles': [{'id': 1, 'kind': 'show', 'name': 'Nobody (show)'}, {'id': 2, 'kind': 'movie', 'name': 'Nobody'},
                                            {'id': 3, 'kind': 'movie', 'name': 'Nobody 2'}]},
            ('GET', '/titles/2/subtitles'): {'files': [{'file_id': 20, 'relative_path': 'Nobody (2021)/Nobody (2021).mkv'}]},
            ('GET', '/titles/3/subtitles'): {'files': [{'file_id': 30, 'relative_path': 'Nobody 2 (2025)/Nobody 2 (2025).mkv'}]},
        })
        got = c.find_file('/media/movies/Nobody 2 (2025)/Nobody 2 (2025).mkv', 'movie', title='Nobody')
        self.assertEqual((got['file_id'], got['title_id']), (30, 3))
        self.assertNotIn(('GET', '/titles/1/subtitles', None), [x[:2] + (None,) for x in c.calls if x[1] == '/titles/1/subtitles'])
        self.assertEqual(c.calls[0][2], {'q': 'Nobody'})

    def test_find_file_falls_back_to_the_folder_name(self):
        c = client_with({
            ('GET', '/titles'): lambda kw: {'titles': [{'id': 2, 'kind': 'movie', 'name': 'Nobody'}] if kw['params']['q'] == 'Nobody' else []},
            ('GET', '/titles/2/subtitles'): {'files': [{'file_id': 20, 'relative_path': 'Nobody (2021)/Nobody (2021).mkv'}]},
        })
        # Kodi calls it by a localized title; the folder name still finds it.
        got = c.find_file('/m/Nobody (2021)/Nobody (2021).mkv', 'movie', title='Niko')
        self.assertEqual(got['file_id'], 20)

    def test_find_file_not_found(self):
        c = client_with({('GET', '/titles'): {'titles': []}})
        with self.assertRaises(HolyArrsItemNotFound):
            c.find_file('/m/x/y.mkv', 'movie', title='y')

    def test_list_subtitles_shape_order_and_refused(self):
        def choice(site, key, lang, total, **kw):
            d = {'site': site, 'key': key, 'language': lang, 'hearing_impaired': False, 'forced': False,
                 'release_names': ['Rel.A', 'Rel.B'], 'score': {'total': total, 'parts': []}}
            d.update(kw)
            return d
        c = client_with({('POST', '/files/7/subtitles/choices'): {'outcomes': [
            {'want': {'language': 'hr'}, 'choices': [choice('Titlovi', '1', 'hr', 53), choice('Titlovi', '2', 'hr', 72, hearing_impaired=True),
                                                     {'site': 'Titlovi', 'key': '3', 'language': 'hr', 'score': {'total': 0, 'refused': 'wrong title'}}]},
            {'want': {'language': 'sr'}, 'choices': [choice('Titlovi', '9', 'sr', 60, forced=True)]},
            {'want': {'language': 'bs'}, 'result': 'none_good_enough'}]}})
        got = c.list_subtitles(7)
        self.assertEqual([r['subtitle']['key'] for r in got], ['2', '9', '1'])
        self.assertEqual(got[0], {'language': 'hr', 'forced': False, 'hearing_impaired': True, 'provider': 'Titlovi', 'score': 72,
                                  'release_info': 'Rel.A / Rel.B', 'subtitle': {'site': 'Titlovi', 'key': '2'}})
        self.assertTrue(got[1]['forced'])

    def test_list_subtitles_nothing_to_offer(self):
        c = client_with({('POST', '/files/7/subtitles/choices'): {'outcomes': [], 'sites_asked': []}})
        self.assertEqual(c.list_subtitles(7), [])

    def test_find_file_returns_the_item_and_the_current_wish(self):
        wish = [{'language': 'hr', 'hearing_impaired': 'normal', 'forced': False}]
        c = client_with({
            ('GET', '/titles'): {'titles': [{'id': 2, 'kind': 'movie', 'name': 'Nobody'}]},
            ('GET', '/titles/2/subtitles'): {'files': [{'file_id': 20, 'item_id': 21, 'relative_path': 'Nobody (2021)/Nobody (2021).mkv', 'wish': {'from': 'default', 'languages': wish}}]},
        })
        got = c.find_file('/m/Nobody (2021)/Nobody (2021).mkv', 'movie', title='Nobody')
        self.assertEqual((got['file_id'], got['item_id'], got['title_id'], got['wish']), (20, 21, 2, wish))

    def test_ensure_languages_adds_only_what_the_wish_lacks_to_this_item(self):
        c = client_with({('PUT', '/titles/2/subtitle-wish'): {}})
        found = {'title_id': 2, 'item_id': 21, 'wish': [{'language': 'hr', 'hearing_impaired': 'normal', 'forced': False}]}
        added = c.ensure_languages(found, ['hr', 'BS', 'sr', 'bs', ''])
        self.assertEqual(added, ['bs', 'sr'])
        method, path, body = c.calls[-1]
        self.assertEqual((method, path), ('PUT', '/titles/2/subtitle-wish'))
        self.assertEqual(body['item_id'], 21)
        self.assertEqual([w['language'] for w in body['languages']], ['hr', 'bs', 'sr'])
        self.assertEqual(body['languages'][0], found['wish'][0])  # the wish it already had is kept as it was

    def test_ensure_languages_does_nothing_when_all_are_wished_or_no_item(self):
        c = client_with({})
        found = {'title_id': 2, 'item_id': 21, 'wish': [{'language': 'hr'}]}
        self.assertEqual(c.ensure_languages(found, ['hr']), [])
        self.assertEqual(c.ensure_languages(found, []), [])
        self.assertEqual(c.ensure_languages({'title_id': 2, 'item_id': None, 'wish': []}, ['bs']), [])
        self.assertEqual(c.calls, [])  # no request at all

    def test_clear_wish_asks_the_item_to_follow_the_global_wish(self):
        c = client_with({('PUT', '/titles/2/subtitle-wish'): {}})
        c.clear_wish(2, 21)
        self.assertEqual(c.calls[-1], ('PUT', '/titles/2/subtitle-wish', {'item_id': 21, 'inherit': True}))

    def test_choose_posts_site_and_key_and_returns_the_path(self):
        c = client_with({('POST', '/files/7/subtitles/choose'): {'path': 'Nobody (2021)/Nobody (2021).hr.srt'}})
        p = c.choose(7, {'subtitle': {'site': 'Titlovi', 'key': '2'}})
        self.assertEqual(p, 'Nobody (2021)/Nobody (2021).hr.srt')
        self.assertEqual(c.calls[-1], ('POST', '/files/7/subtitles/choose', {'site': 'Titlovi', 'key': '2'}))


    def test_a_refused_key_is_not_reported_as_unreachable(self):
        c = HolyArrsClient('http://h/', 'key')
        for status in (401, 403):
            r = mock.Mock(status_code=status)
            c.sess = mock.Mock(get=mock.Mock(return_value=r))
            with self.assertRaises(holyarrs.HolyArrsAuthError):
                c._get('/titles')

    def test_other_http_errors_keep_status_and_message(self):
        c = HolyArrsClient('http://h/', 'key')
        r = mock.Mock(status_code=409)
        r.json.return_value = {'error': 'language not wished'}
        c.sess = mock.Mock(post=mock.Mock(return_value=r))
        with self.assertRaises(holyarrs.HolyArrsHTTPError) as ctx:
            c._post('/files/7/subtitles/choose', {})
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn('language not wished', str(ctx.exception))

    def test_conflicting_subtitles_are_this_videos_files_in_this_language(self):
        names = ['Nobody (2021).mkv', 'Nobody (2021).hr.srt', 'Nobody (2021).hr.forced.srt', 'Nobody (2021).en.srt',
                 'Nobody (2021).hr.srt.bak', 'Nobody (2021) Extras.hr.srt', 'Other.hr.srt']
        self.assertEqual(holyarrs.conflicting_subtitles(names, 'Nobody (2021)', 'hr'),
                         ['Nobody (2021).hr.forced.srt', 'Nobody (2021).hr.srt'])
        self.assertEqual(holyarrs.conflicting_subtitles(names, 'Nobody (2021)', ''), [])

    def test_only_the_did_not_save_refusal_counts_as_a_foreign_file_conflict(self):
        e = holyarrs.HolyArrsHTTPError
        self.assertTrue(holyarrs.is_foreign_file_conflict(e(409, 'a subtitle file HolyArrs did not save is at that name; it is left alone')))
        self.assertFalse(holyarrs.is_foreign_file_conflict(e(409, 'the candidate cannot be used')))
        self.assertFalse(holyarrs.is_foreign_file_conflict(e(502, 'a subtitle file HolyArrs did not save')))
        self.assertFalse(holyarrs.is_foreign_file_conflict(RuntimeError('did not save')))


if __name__ == '__main__':
    unittest.main()
