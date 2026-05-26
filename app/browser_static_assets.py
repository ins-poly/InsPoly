from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote


VENDOR_BROWSER_URL_PREFIX = "/vendor/browser/"
VENDOR_BROWSER_ROOT = Path(__file__).resolve().parent / "vendor" / "browser"

_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def is_browser_vendor_asset_path(request_path: str) -> bool:
    return unquote(str(request_path or "")).startswith(VENDOR_BROWSER_URL_PREFIX)


def load_browser_vendor_asset(
    request_path: str,
    *,
    vendor_root: Path = VENDOR_BROWSER_ROOT,
) -> tuple[bytes, str] | None:
    decoded_path = unquote(str(request_path or ""))
    if not decoded_path.startswith(VENDOR_BROWSER_URL_PREFIX):
        return None

    relative = decoded_path.removeprefix(VENDOR_BROWSER_URL_PREFIX)
    if not relative or relative.endswith("/"):
        return None

    root = vendor_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None

    content_type = _MIME_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
    return candidate.read_bytes(), content_type
