"""Build permanent HTTP(S) landing URLs carried by printed QR images."""
from urllib.parse import urlencode, urlsplit, urlunsplit

from storage import AppError, qr_id_from_raw


def normalize_app_base(url: str) -> str:
    url = str(url or '').strip()
    parts = urlsplit(url)
    if parts.scheme not in ('https', 'http') or not parts.netloc or parts.username or parts.password:
        raise AppError('APP_BASE_URL은 http(s)://도메인 형식이어야 합니다.')
    # The QR itself must always open the main app, not an admin/query/hash page.
    path = parts.path.rstrip('/') + '/'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


def fixed_qr_url(qr_id: str, base: str) -> str:
    qr_id_from_raw('SCAN:' + str(qr_id))
    if not base:
        raise AppError('APP_BASE_URL을 Streamlit Secrets에 설정해주세요.')
    return normalize_app_base(base) + '?' + urlencode({'qr': qr_id})
