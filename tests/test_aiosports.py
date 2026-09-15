"""AIOSports id handling, runnable without starting Quart or a database.

Run: python -m unittest discover -s tests
"""
import importlib
from pathlib import Path
import sys
from types import ModuleType
import unittest


# Load the module under an isolated package, avoiding app factory imports.
ROOT = Path(__file__).resolve().parents[1]
package = ModuleType('_scs_aiosports_tests')
package.__path__ = [str(ROOT / 'app')]
sys.modules[package.__name__] = package
aiosports = importlib.import_module('_scs_aiosports_tests.lib.aiosports')

humanize = aiosports.humanize_aiosports_id
is_channel = aiosports.is_aiosports_channel_id


class HumanizeIdTests(unittest.TestCase):
    # Provider tags are minted in the addon's src/providers/*.js; the first two
    # cases are the ids that prompted this, read off a live dashboard.
    CASES = [
        ('nuvio_sport_sf_denver_broncos_vs_kansas_city_chiefs',
         'Denver Broncos vs Kansas City Chiefs'),
        ('nuvio_sport_ts_ch_tbs', 'TBS'),
        ('nuvio_sport_ts_ch_espn2', 'ESPN2'),
        ('nuvio_sport_ts_ch_nfl_network', 'NFL Network'),
        ('nuvio_sport_ts_ch_fs1', 'FS1'),
        ('nuvio_sport_sf-los-angeles-lakers-vs-boston-celtics',
         'Los Angeles Lakers vs Boston Celtics'),
        ('nuvio_sport_iptv_local_abc_wabc', 'ABC Wabc'),
        ('nuvio_sport_cdn_ch_us_bein_sports', 'US beIN Sports'),
        ('nuvio_sport_wf_arsenal_vs_chelsea', 'Arsenal vs Chelsea'),
        ('nuvio_sport_spk_ufc_309_ppv', 'UFC 309 PPV'),
        ('nuvio_sport_ustv_the_cw', 'The CW'),
        ('nuvio_sport_ts_ch_motogp', 'MotoGP'),
        # An unrecognised tag survives into the title rather than being guessed
        # at: ugly, but it can never eat a real first word.
        ('nuvio_sport_zz9_real_madrid_vs_barcelona', 'Zz9 Real Madrid vs Barcelona'),
        # Already clean, and a bare slug with no addon prefix at all.
        ('nuvio_sport_sf_world_cup_final', 'World Cup Final'),
    ]

    def test_humanizes_ids(self):
        for content_id, expected in self.CASES:
            with self.subTest(content_id=content_id):
                self.assertEqual(humanize(content_id), expected)

    def test_title_case_does_not_mangle_acronyms(self):
        # The bug this replaces: str.title() renders these as 'Tbs' and 'Nfl'.
        self.assertEqual(humanize('nuvio_sport_ts_ch_tbs'), 'TBS')
        self.assertNotEqual(humanize('nuvio_sport_ts_ch_nfl_network'), 'Nfl Network')

    def test_small_words_stay_lowercase_only_in_the_middle(self):
        self.assertEqual(humanize('nuvio_sport_sf_a_vs_b'), 'A vs B')
        # ...but never at either end, where they read as a truncation.
        self.assertEqual(humanize('nuvio_sport_sf_vs'), 'Vs')

    def test_degenerate_ids(self):
        self.assertEqual(humanize(''), '')
        self.assertEqual(humanize(None), '')
        # Nothing survives stripping, so the raw id comes back rather than ''.
        self.assertEqual(humanize('nuvio_sport_'), 'nuvio_sport_')
        self.assertEqual(humanize('nuvio_sport_sf_'), 'nuvio_sport_sf_')


class ChannelDetectionTests(unittest.TestCase):
    def test_channel_ids(self):
        for content_id in ('nuvio_sport_ts_ch_tbs',
                           'nuvio_sport_cdn_ch_us_espn',
                           'nuvio_sport_iptv_12345',
                           'nuvio_sport_iptv_local_abc_wabc',
                           'nuvio_sport_ustv_the_cw'):
            with self.subTest(content_id=content_id):
                self.assertTrue(is_channel(content_id))

    def test_fixture_ids(self):
        for content_id in ('nuvio_sport_sf_denver_broncos_vs_kansas_city_chiefs',
                           'nuvio_sport_wf_arsenal_vs_chelsea',
                           'nuvio_sport_ts_12345'):
            with self.subTest(content_id=content_id):
                self.assertFalse(is_channel(content_id))

    def test_non_aiosports_ids(self):
        for content_id in ('tt3398228:1:4', 'kitsu:123', '', None):
            with self.subTest(content_id=content_id):
                self.assertFalse(is_channel(content_id))


class ArtworkUrlTests(unittest.TestCase):
    BASE = 'http://aiosports:7000'

    def rewrite(self, url):
        return aiosports._rewrite_art_url(url, self.BASE)

    def test_addon_artwork_is_proxied_through_our_origin(self):
        # Whatever host the addon stamped on it, only the path and query travel.
        for url in (f'{self.BASE}/img?url=https%3A%2F%2Fcdn.example%2Ftbs.png',
                    'http://192.168.1.50:7000/img?url=https%3A%2F%2Fcdn.example%2Ftbs.png'):
            with self.subTest(url=url):
                self.assertEqual(
                    self.rewrite(url),
                    '/aiosports/art?p=%2Fimg%3Furl%3Dhttps%253A%252F%252Fcdn.example%252Ftbs.png')

    def test_relative_artwork_is_proxied(self):
        self.assertEqual(self.rewrite('/logo/tbs.png'), '/aiosports/art?p=%2Flogo%2Ftbs.png')

    def test_public_https_artwork_passes_through(self):
        self.assertEqual(self.rewrite('https://cdn.example/tbs.png'), 'https://cdn.example/tbs.png')

    def test_unusable_artwork_is_dropped(self):
        # Plain-HTTP third-party artwork would be blocked as mixed content on an
        # HTTPS dashboard, and a protocol-relative URL escapes our origin.
        for url in ('http://cdn.example/tbs.png', '//evil.example/x.png',
                    'data:image/png;base64,AAAA', '', None, 123):
            with self.subTest(url=url):
                self.assertIsNone(self.rewrite(url))


if __name__ == '__main__':
    unittest.main()
