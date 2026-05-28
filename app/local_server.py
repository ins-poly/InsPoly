from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import ParseResult, parse_qs, urlencode, urlparse, urlunparse

from http.server import ThreadingHTTPServer
import threading

LOCAL_API_SESSION_COOKIE = "inspoly_session"
MAX_JSON_BODY_BYTES = 1_000_000
MAX_OVERSIZED_BODY_DRAIN_BYTES = 64 * 1024
ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost"}


class LocalRequestError(ValueError):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(slots=True)
class LocalServerHandle:
    server: ThreadingHTTPServer
    url: str
    label: str
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def serve_forever(self) -> None:
        self.server.serve_forever()

    def start_background(self, *, thread_name: str | None = None) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self.server.serve_forever,
            name=thread_name or f"{self.label} server",
            daemon=True,
        )
        self._thread.start()

    def close(self, *, timeout: float = 5.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self._thread and self._thread.is_alive():
            self.server.shutdown()
            self._thread.join(timeout=timeout)
        self.server.server_close()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def tokenized_local_url(port: int, session_token: str) -> str:
    query = urlencode({"token": session_token})
    return urlunparse(("http", f"127.0.0.1:{port}", "/", "", query, ""))


def session_cookie_header(session_token: str) -> str:
    return f"{LOCAL_API_SESSION_COOKIE}={session_token}; Path=/; SameSite=Strict"


def request_has_valid_session(handler: object, parsed: ParseResult, session_token: str) -> bool:
    values = parse_qs(parsed.query).get("token", [])
    header_token = str(handler.headers.get("X-InsPoly-Session", "") or "")
    cookie_token = _cookie_value(str(handler.headers.get("Cookie", "") or ""), LOCAL_API_SESSION_COOKIE)
    candidates = [header_token, cookie_token, *values]
    return any(secrets.compare_digest(str(candidate), session_token) for candidate in candidates if candidate)


def require_local_request(handler: object, parsed: ParseResult, session_token: str, *, require_token: bool) -> bool:
    if not _host_allowed(handler):
        _send_local_error(handler, HTTPStatus.FORBIDDEN, "Forbidden host.")
        return False
    if not _origin_allowed(handler):
        _send_local_error(handler, HTTPStatus.FORBIDDEN, "Forbidden origin.")
        return False
    if require_token and not request_has_valid_session(handler, parsed, session_token):
        _send_local_error(handler, HTTPStatus.FORBIDDEN, "Missing or invalid InsPoly session token.")
        return False
    return True


def read_json_body(handler: object, *, max_bytes: int = MAX_JSON_BODY_BYTES) -> dict[str, object]:
    raw_length = str(handler.headers.get("Content-Length", "0") or "0")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise LocalRequestError(HTTPStatus.BAD_REQUEST, "Invalid Content-Length.") from exc
    if length > max_bytes:
        if length <= max_bytes + MAX_OVERSIZED_BODY_DRAIN_BYTES:
            _discard_request_body(handler, length)
        else:
            setattr(handler, "close_connection", True)
        raise LocalRequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "JSON request body is too large.")
    content_type = str(handler.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
    if length and content_type != "application/json":
        raise LocalRequestError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/json request body.")
    body = handler.rfile.read(length) if length else b"{}"
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise LocalRequestError(HTTPStatus.BAD_REQUEST, "Invalid JSON request body.") from exc
    if not isinstance(payload, dict):
        raise LocalRequestError(HTTPStatus.BAD_REQUEST, "JSON request body must be an object.")
    return payload


def safe_child_path(root: Path, name: str, *, suffix: str | None = None) -> Path:
    if not name:
        raise ValueError("Missing file name.")
    candidate = (root / name).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Path is outside the allowed InsPoly directory.") from exc
    if suffix is not None and candidate.suffix != suffix:
        raise ValueError(f"Expected a {suffix} file.")
    return candidate


def require_allowed_path(path: Path, allowed_roots: list[Path]) -> Path:
    candidate = path.resolve()
    for root in allowed_roots:
        try:
            candidate.relative_to(root.resolve())
            return candidate
        except ValueError:
            continue
    raise ValueError("Path is outside the allowed InsPoly output directories.")


def open_local_path(path: Path, *, platform_name: str | None = None) -> None:
    resolved = path.resolve()
    platform = platform_name or sys.platform
    if platform == "darwin":
        subprocess.run(["open", str(resolved)], check=False)
        return
    if platform.startswith("win"):
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise RuntimeError("Windows file opener is unavailable.")
        startfile(str(resolved))
        return
    subprocess.run(["xdg-open", str(resolved)], check=False)


def _discard_request_body(handler: object, length: int) -> None:
    remaining = max(0, length)
    while remaining:
        chunk = handler.rfile.read(min(remaining, 64 * 1024))
        if not chunk:
            break
        remaining -= len(chunk)


def _host_allowed(handler: object) -> bool:
    host_header = str(handler.headers.get("Host", "") or "")
    if not host_header:
        return True
    host, port = _split_host_port(host_header)
    if host not in ALLOWED_LOCAL_HOSTS:
        return False
    expected_port = str(getattr(handler.server, "server_port", "") or "")
    return not port or not expected_port or port == expected_port


def _origin_allowed(handler: object) -> bool:
    origin = str(handler.headers.get("Origin", "") or "")
    if not origin:
        return True
    parsed = urlparse(origin)
    if parsed.scheme != "http":
        return False
    host, port = _split_host_port(parsed.netloc)
    if host not in ALLOWED_LOCAL_HOSTS:
        return False
    expected_port = str(getattr(handler.server, "server_port", "") or "")
    return bool(port) and (not expected_port or port == expected_port)


def _split_host_port(value: str) -> tuple[str, str]:
    text = value.strip().lower()
    if text.startswith("["):
        host, _, rest = text.partition("]")
        port = rest[1:] if rest.startswith(":") else ""
        return host.strip("[]"), port
    host, sep, port = text.rpartition(":")
    if sep and port.isdigit():
        return host, port
    return text, ""


def _cookie_value(header: str, name: str) -> str:
    for part in header.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key == name:
            return value
    return ""


def _send_local_error(handler: object, status: HTTPStatus, message: str) -> None:
    data = json.dumps({"ok": False, "error": message}, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
