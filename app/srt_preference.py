import copy

from quart import Blueprint, request
from quart_auth import current_user, login_required
from sqlalchemy import select
from pysubs2 import SSAFile

from .extensions import async_session_maker
from .models import User
from .routes.utils import NoCacheResponse, respond_with_no_cache


srt_preference_bp = Blueprint('srt_preference', __name__)


def _prefers_srt(user):
    preferences = (user.provider_credentials or {}).get('_preferences', {})
    return bool(preferences.get('prioritize_srt_subtitles', False))


@srt_preference_bp.post('/account/srt-preference')
@login_required
async def update_srt_preference():
    data = await request.get_json()
    enabled = bool((data or {}).get('enabled', False))

    async with async_session_maker() as session:
        result = await session.execute(select(User).filter_by(id=current_user.auth_id))
        user = result.scalar_one_or_none()
        if not user:
            return {'success': False, 'error': 'User not found'}, 404

        credentials = dict(user.provider_credentials or {})
        preferences = dict(credentials.get('_preferences') or {})
        preferences['prioritize_srt_subtitles'] = enabled
        credentials['_preferences'] = preferences
        user.provider_credentials = credentials
        await session.commit()

    return {'success': True, 'enabled': enabled}


@srt_preference_bp.route('/<manifest_token>/download/<download_identifier>.srt')
async def srt_download(manifest_token: str, download_identifier: str):
    # Reuse the existing selection/provider pipeline, then strip VTT styling into SRT.
    from .routes.subtitles import unified_download

    response = await unified_download(manifest_token, download_identifier)
    raw = await response.get_data()
    text = raw.decode('utf-8', errors='replace')

    if text.lstrip().upper().startswith('WEBVTT'):
        try:
            text = SSAFile.from_string(text, format_='vtt').to_string('srt')
        except Exception:
            # If conversion fails, preserve the original response instead of breaking playback.
            return response

    return NoCacheResponse(text, status=response.status_code, mimetype='application/x-subrip')


@srt_preference_bp.after_app_request
async def prioritize_srt_entries(response):
    # Only touch Stremio subtitle-list JSON responses.
    if '/subtitles/' not in request.path or response.mimetype != 'application/json':
        return response

    parts = [part for part in request.path.split('/') if part]
    if not parts:
        return response

    user = await User.get_by_manifest_token(parts[0])
    if not user or not _prefers_srt(user):
        return response

    try:
        payload = await response.get_json()
    except Exception:
        return response

    subtitles = payload.get('subtitles') if isinstance(payload, dict) else None
    if not isinstance(subtitles, list):
        return response

    srt_entries = []
    for entry in subtitles:
        if not isinstance(entry, dict):
            continue
        url = entry.get('url', '')
        if not isinstance(url, str) or not url.endswith('.vtt'):
            continue

        srt_entry = copy.deepcopy(entry)
        srt_entry['id'] = f"{entry.get('id', 'subtitle')}_srt"
        srt_entry['url'] = f"{url[:-4]}.srt"
        srt_entries.append(srt_entry)

    if not srt_entries:
        return response

    payload['subtitles'] = srt_entries + subtitles
    return respond_with_no_cache(payload)
