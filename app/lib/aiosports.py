"""Metadata helpers for AIOSports (``nuvio_sport_*``) content ids.

The AIOSports addon serves every item under Stremio type ``tv`` with ids shaped
``nuvio_sport_<provider-tag><native-id>``. Its meta handler answers HTTP 200
with ``{"meta": null}`` for any id that has dropped out of its live match list,
so a fixture that already finished is permanently unresolvable — which is why
the locally derived title below matters as much as the network lookup.

Everything here fails soft: with ``AIOSPORTS_ADDON_URL`` unset no request is
ever made and callers simply get ``None``.
"""

import re
from urllib.parse import quote, urlsplit, urlunsplit

AIOSPORTS_ID_PREFIX = 'nuvio_sport_'

# 24/7 channel artwork is static; a fixture's poster and status are not.
CHANNEL_TTL = 86400
EVENT_TTL = 300
MISS_TTL = 120

# AsyncCache.get() returns None for a miss, so a resolved-to-nothing lookup
# needs a sentinel of its own to be cached at all.
_MISS = object()

# Provider tags minted by the addon's providers (src/providers/*.js), longest
# first so 'ts_ch' wins over 'ts' and 'iptv_local' over 'iptv'. Only tags read
# from the addon's source are listed: an unrecognised tag is left in the title
# rather than guessed at, because wrongly eating a real first word
# ("St Louis Blues" -> "Louis Blues") is worse than a stray tag surviving.
_SOURCE_TAGS = (
    'iptv_local', 'streamic', 'sporty', 'cdn_ch', 'ts_ch',
    'ss99', 'ustv', 'iptv', 'cdn', 'spk', 'sf', 'ts', 'wf',
)

# Tags whose entries the addon builds as 24/7 channels (category 'networks',
# no kickoff date) rather than one-off fixtures.
_CHANNEL_TAGS = ('iptv_local', 'cdn_ch', 'ts_ch', 'ustv', 'iptv')

# The addon always joins tag to native id with '_', but a native id may itself
# be hyphenated, so accept either separator rather than depend on that.
_SOURCE_PREFIX = re.compile(r'^(?:' + '|'.join(_SOURCE_TAGS) + r')[-_]')
_CHANNEL_PREFIX = re.compile(r'^(?:' + '|'.join(_CHANNEL_TAGS) + r')[-_]')

# Paths the addon serves its own artwork from. Anything else is either a public
# URL the browser can load unaided or not artwork we will proxy.
_ADDON_ART_PATHS = ('/img', '/logo', '/marks', '/placeholder')

# The addon prefixes meta names with a status glyph: '📺 ' for a live channel,
# '🔴 LIVE: ' for a running fixture, '⏱️ ' for one yet to start.
_STATUS_PREFIX = re.compile(r'^(?:\U0001F4FA|\U0001F534\s*LIVE:|⏱️?)\s*')
_LEADING_INDEX = re.compile(r'^\d+_')
_SEPARATORS = re.compile(r'[\s_\-.:,/]+')
_ALPHA_NUM = re.compile(r'^([a-z]+)(\d{1,3})$')

_ACRONYMS = frozenset({
    'abc', 'acc', 'afc', 'afl', 'amc', 'atp', 'bbc', 'btn', 'cbc', 'cbs',
    'cfl', 'cnbc', 'cw', 'epl', 'espn', 'espnu', 'fa', 'fox', 'fs1', 'fs2',
    'gp', 'hbo', 'hd', 'ipl', 'itv', 'khl', 'lpga', 'mlb', 'mls', 'mma',
    'msg', 'nba', 'nbc', 'nbcsn', 'ncaa', 'ncaab', 'ncaaf', 'nfc', 'nfl',
    'nhl', 'nrl', 'odi', 'pga', 'ppv', 'sec', 'tbs', 'tnt', 'tsn', 'tv',
    'uefa', 'ufc', 'uk', 'us', 'usa', 'wnba', 'wta', 'wwe',
    'f1', 'f2', 'f3', 't20', 'uhd', '4k',
})
_MIXED_CASE = {'bein': 'beIN', 'motogp': 'MotoGP', 'espnews': 'ESPNews', 'dazn': 'DAZN'}
_LOWERCASE = frozenset({'a', 'an', 'and', 'at', 'de', 'for', 'in', 'of', 'on',
                        'the', 'to', 'v', 'vs', 'with'})


def is_aiosports_id(content_id):
    """True for ids served by the AIOSports addon."""
    return bool(content_id) and content_id.startswith(AIOSPORTS_ID_PREFIX)


def is_aiosports_channel_id(content_id):
    """True when the id looks like a 24/7 channel rather than a fixture."""
    if not is_aiosports_id(content_id):
        return False
    body = content_id[len(AIOSPORTS_ID_PREFIX):]
    return bool(_CHANNEL_PREFIX.match(body)) or '_ch_' in body


def humanize_aiosports_id(content_id):
    """Readable display title derived from a ``nuvio_sport_*`` id.

    Used when the addon cannot be reached or no longer knows the id. Returns the
    raw id when nothing meaningful survives stripping, and '' for a falsy input.
    Pure: no network, no config, no app context.
    """
    raw = (content_id or '').strip()
    if not raw:
        return ''

    body = raw[len(AIOSPORTS_ID_PREFIX):] if raw.startswith(AIOSPORTS_ID_PREFIX) else raw
    body = _SOURCE_PREFIX.sub('', body, count=1)
    body = _LEADING_INDEX.sub('', body)

    tokens = [token for token in _SEPARATORS.split(body.lower()) if token]
    if not tokens:
        return raw

    last = len(tokens) - 1
    return ' '.join(_render_token(t, i, last) for i, t in enumerate(tokens)) or raw


def _render_token(token, index, last_index):
    if token in _MIXED_CASE:
        return _MIXED_CASE[token]
    if token in _ACRONYMS:
        return token.upper()
    # 'espn2', 'fs1' and friends: an acronym carrying a channel number.
    alpha_num = _ALPHA_NUM.match(token)
    if alpha_num and alpha_num.group(1) in _ACRONYMS:
        return token.upper()
    # Small words stay lowercase, but never at either end of the title.
    if token in _LOWERCASE and 0 < index < last_index:
        return token
    # Not str.capitalize(): that would lowercase the tail of tokens like '76ers'.
    return token[0].upper() + token[1:]


def addon_base_url():
    """Configured addon base URL, normalised, or '' when the feature is off."""
    from quart import current_app

    base = (current_app.config.get('AIOSPORTS_ADDON_URL') or '').strip().rstrip('/')
    return base if base.startswith(('http://', 'https://')) else ''


def _local_art_url(path_and_query):
    """Point artwork at our own origin so any browser can load it."""
    return '/aiosports/art?p=' + quote(path_and_query, safe='')


def _rewrite_art_url(art_url, base):
    """Turn an addon artwork URL into one the viewer's browser can fetch.

    The addon rewrites meta poster/background/logo to ``<requesting-host>/img?url=``
    (src/index.js:1604-1608), so a server-side lookup yields a URL built from the
    base *we* asked with — or from its own ADDON_URL override. Either way it can
    be a LAN address a phone cannot reach, or plain HTTP on an HTTPS dashboard,
    so anything on one of the addon's own paths is re-anchored and proxied.
    """
    if not art_url or not isinstance(art_url, str):
        return None

    if art_url.startswith('/'):
        return _local_art_url(art_url) if art_url[:2] != '//' else None

    parts = urlsplit(art_url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        return None
    if parts.path.startswith(_ADDON_ART_PATHS):
        return _local_art_url(urlunsplit(('', '', parts.path, parts.query, '')))
    # Artwork hot-linked straight from a public CDN needs no help from us.
    return art_url if parts.scheme == 'https' else None


async def _fetch_metadata(content_id):
    import asyncio

    import aiohttp
    from quart import current_app

    base = addon_base_url()
    if not base:
        return None  # Feature disabled: no socket is opened at all.

    url = f"{base}/meta/tv/{quote(content_id, safe='')}.json"
    try:
        timeout = aiohttp.ClientTimeout(total=2.5, connect=1.0, sock_connect=1.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={'Accept': 'application/json'}) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        current_app.logger.debug(f"AIOSports lookup failed for {content_id}: {e}")
        return None
    except Exception as e:
        current_app.logger.warning(f"Unexpected AIOSports lookup error for {content_id}: {e}")
        return None

    meta = payload.get('meta') if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        # 200 with {"meta": null}: the addon no longer carries this fixture.
        return None

    name = _STATUS_PREFIX.sub('', str(meta.get('name') or '')).strip()
    artwork = meta.get('poster') or meta.get('background') or meta.get('logo')
    return {
        'title': name or humanize_aiosports_id(content_id),
        # season/episode/year stay None: the dashboard appends 'SxxEyy' and
        # ' (year)' to the title whenever they are set, which is nonsense here.
        'poster_url': _rewrite_art_url(artwork, base),
        'year': None,
        'season': None,
        'episode': None,
        'id': content_id,
        'id_type': 'aiosports',
        'poster_shape': 'landscape',
        'is_channel': is_aiosports_channel_id(content_id),
    }


async def get_aiosports_metadata(content_id):
    """Resolve AIOSports metadata, or None when unresolvable. Never raises."""
    from ..extensions import cache

    key = f'aiosports_meta:{content_id}'
    cached = await cache.get(key)
    if cached is not None:
        # Callers add a 'display_title' key, so hand out a copy of the entry.
        return None if cached is _MISS else dict(cached)

    metadata = await _fetch_metadata(content_id)
    if metadata is None:
        await cache.set(key, _MISS, MISS_TTL)
        return None

    await cache.set(key, metadata, CHANNEL_TTL if metadata['is_channel'] else EVENT_TTL)
    return dict(metadata)
