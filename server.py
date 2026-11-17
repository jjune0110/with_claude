"""표준 라이브러리만 사용하는 로컬 웹서버. 127.0.0.1(이 PC)에서만 접속을 받는다.

보안 방침
- 외부 접속 차단: 127.0.0.1 에만 바인딩, Host 헤더 검증(DNS 리바인딩 방어)
- 세션: 무작위 토큰 쿠키(HttpOnly, SameSite=Strict), 무입력 시간이 지나면 서버에서 만료
- CSRF 방어: 변경 요청은 사용자 지정 헤더 + Origin 검사 필수, 응답에 CORS 허용 없음
- 화면은 모든 값을 textContent 로만 출력하고, CSP 로 외부·인라인 스크립트를 차단
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import sys
import threading
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..services import settings
from ..services.auth import AuthError, AuthService
from ..services.common import PermissionDenied, ValidationError
from . import api

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}
COOKIE_NAME = "academy_session"
MAX_BODY = 1_000_000
SESSION_GRACE_SECONDS = 15
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class Session:
    __slots__ = ("user", "last")

    def __init__(self, user):
        self.user = user
        self.last = time.monotonic()


class AppServer(HTTPServer):
    # Windows 에서는 SO_REUSEADDR 가 '같은 포트 중복 실행'을 허용하므로 끈다.
    allow_reuse_address = not sys.platform.startswith("win")

    def __init__(self, address, conn):
        super().__init__(address, Handler)
        self.conn = conn
        self.auth = AuthService(conn)
        self.sessions: dict[str, Session] = {}
        port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {f"http://{host}" for host in self.allowed_hosts}

    # ---- 세션 ----
    def new_session(self, user) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = Session(user)
        return token

    def get_session(self, token):
        session = self.sessions.get(token) if token else None
        if session is None:
            return None
        limit = settings.get_int(self.conn, "auto_lock_minutes") * 60 + SESSION_GRACE_SECONDS
        now = time.monotonic()
        if now - session.last > limit:
            self.sessions.pop(token, None)
            return None
        session.last = now
        return session

    def drop_session(self, token) -> None:
        self.sessions.pop(token, None)

    def request_shutdown(self) -> None:
        threading.Thread(target=self.shutdown, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "AcademyApp"
    sys_version = ""

    def log_message(self, *args) -> None:  # 콘솔을 조용하게 유지
        pass

    do_GET = lambda self: self._handle("GET")        # noqa: E731
    do_POST = lambda self: self._handle("POST")      # noqa: E731
    do_PUT = lambda self: self._handle("PUT")        # noqa: E731
    do_DELETE = lambda self: self._handle("DELETE")  # noqa: E731

    # ---- 응답 ----
    def _send(self, status: int, body: bytes, content_type: str, extra_headers=()) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict, extra_headers=()) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra_headers)

    def _error(self, status: int, message: str, code: str = "") -> None:
        self._json(status, {"error": message, "code": code})

    # ---- 처리 ----
    def _handle(self, method: str) -> None:
        try:
            self._dispatch(method)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            try:
                self._error(500, "처리 중 오류가 발생했습니다. 문제가 계속되면 프로그램을 다시 실행하십시오.")
            except OSError:
                pass

    def _cookie_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            jar = SimpleCookie(raw)
        except Exception:  # noqa: BLE001
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValidationError("요청이 너무 큽니다.")
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValidationError("잘못된 요청입니다.") from None
        if not isinstance(data, dict):
            raise ValidationError("잘못된 요청입니다.")
        return data

    def _dispatch(self, method: str) -> None:
        server: AppServer = self.server  # type: ignore[assignment]
        if (self.headers.get("Host") or "").lower() not in server.allowed_hosts:
            return self._error(403, "허용되지 않은 접속입니다.")
        if method != "GET":
            origin = self.headers.get("Origin")
            if (origin and origin.lower() not in server.allowed_origins) or \
                    self.headers.get("X-Requested-With") != "academy":
                return self._error(403, "허용되지 않은 요청입니다.")

        parts = urlsplit(self.path)
        if not parts.path.startswith("/api/"):
            if method != "GET":
                return self._error(405, "허용되지 않은 방식입니다.")
            return self._static(parts.path)

        found = api.match(method, parts.path)
        if found is None:
            return self._error(404, "요청을 찾을 수 없습니다.")
        handler, access, params = found

        token = self._cookie_token()
        session = server.get_session(token)
        if access != "public" and session is None:
            return self._error(401, "로그인이 필요합니다. (자동 잠금 또는 세션 만료)", "login")
        if access == "director" and not session.user.is_director:
            return self._error(403, "원장만 수행할 수 있습니다.")

        try:
            body = self._read_body() if method in ("POST", "PUT") else {}
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            ctx = api.Context(server, session, params, body, query)
            payload = handler(ctx)
        except ValidationError as exc:
            return self._error(400, str(exc), "invalid")
        except PermissionDenied as exc:
            return self._error(403, str(exc), "denied")
        except AuthError as exc:
            return self._error(401, str(exc), "auth")
        except sqlite3.IntegrityError:
            return self._error(409, "처리할 수 없습니다. 중복되었거나 연결된 데이터가 있습니다.", "conflict")

        headers = []
        if ctx.new_user is not None:
            if token:
                server.drop_session(token)
            new_token = server.new_session(ctx.new_user)
            headers.append(("Set-Cookie", f"{COOKIE_NAME}={new_token}; Path=/; HttpOnly; SameSite=Strict"))
        elif ctx.end_session:
            server.drop_session(token)
            headers.append(("Set-Cookie", f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"))
        self._json(200, payload, headers)

    def _static(self, path: str) -> None:
        entry = STATIC_FILES.get(path)
        if entry is None:
            return self._error(404, "찾을 수 없습니다.")
        filename, content_type = entry
        self._send(200, (STATIC_DIR / filename).read_bytes(), content_type)
