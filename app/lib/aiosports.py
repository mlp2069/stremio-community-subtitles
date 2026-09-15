import os
import re
import socket
import struct
from urllib.parse import quote

import aiohttp
from quart import current_app


def _docker_gateway():
    """Return the container's default IPv4 gateway when running under Docker."""
    try:
        with open('/proc/net/route', 'r', encoding='utf-8') as routes:
            for line in routes.readlines()[1:]:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == '00000000':
                    return socket.inet_ntoa(struct.pack('<L', int(fields[2], 16)))
    except (OSError, ValueError, struct.error):
        pass
    return None


def _candidate_bases():
    """AIOSports locations, ordered from explicit config to local fallbacks."""
    configured = os.environ.get('AIOSPORTS_URL', '').strip().rstrip('/')
    candidates = []
    if configured:
        candidates.append(configured)

    # Common same-host/container layouts. Duplicate entries are removed below.
    candidates.extend([
        'http://aiosports:7000',
        'http://aiosports:7001',
        'http://host.docker.internal:7000',
    ])
    gateway = _docker_gateway()
    if gateway:
        candidates.append(f'http://{gateway}:7000')

    seen = set()
    return [url for url in candidates if not (url in seen or seen.add(url))]


def _clean_name(name, fallback):
    title = str(name or fallback).strip()
    # AIOSports prefixes indicate status in players; they are noisy in SCS history.
    title = re.sub(r'^(?:📺\s*|🔴\s*LIVE:\s*|⏱️\s*)', '', title).strip()
    return title or fallback


async def get_aiosports_metadata(content_id):
    """Fetch the canonical title and landscape artwork for an AIOSports item."""
    if not content_id or not content_id.startswith('nuvio_sport_'):
        return None

    timeout = aiohttp.ClientTimeout(total=2.5, connect=1.0)
    path_id = quote(content_id, safe='')

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for base in _candidate_bases():
            url = f'{base}/meta/tv/{path_id}.json'
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        continue
                    payload = await response.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
            except Exception as exc:
                current_app.logger.debug('AIOSports metadata lookup failed via %s: %s', base, exc)
                continue

            meta = payload.get('meta') if isinstance(payload, dict) else None
            if not isinstance(meta, dict):
                continue

            return {
                'title': _clean_name(meta.get('name'), content_id),
                'poster_url': meta.get('poster') or meta.get('background'),
                'background_url': meta.get('background') or meta.get('poster'),
                'year': None,
                'season': None,
                'episode': None,
                'id': content_id,
                'id_type': 'aiosports',
                'poster_shape': 'landscape',
            }

    current_app.logger.info('Could not resolve AIOSports metadata for %s', content_id)
    return None
