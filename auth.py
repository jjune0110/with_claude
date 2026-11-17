"""사용자·로그인(PIN). PIN은 PBKDF2 해시로만 저장한다 (표준 라이브러리만 사용)."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time

from . import audit
from .common import PermissionDenied, ValidationError
from .models import User

ITERATIONS = 200_000
MAX_FAILS = 5
LOCK_SECONDS = 30


class AuthError(Exception):
    pass


def validate_pin(pin: str) -> str:
    if not re.fullmatch(r"[0-9]{4,6}", pin or ""):
        raise ValidationError("PIN은 숫자 4~6자리로 입력하십시오.")
    return pin


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except ValueError:
        return False


class AuthService:
    def __init__(self, conn):
        self.conn = conn
        self._fails: dict[int, list] = {}  # user_id -> [횟수, 잠금 해제 시각]

    # ---- 조회 ----
    def has_users(self) -> bool:
        return self.conn.execute("SELECT 1 FROM user LIMIT 1").fetchone() is not None

    def list_users(self):
        return [dict(r) for r in self.conn.execute("SELECT id, name, role, active FROM user ORDER BY role DESC, name")]

    def list_login_users(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT id, name, role FROM user WHERE active = 1 ORDER BY role DESC, name")]

    # ---- 생성 ----
    def create_first_director(self, name: str, pin: str) -> User:
        if self.has_users():
            raise PermissionDenied("이미 사용자가 등록되어 있습니다.")
        return self._insert(None, name, "원장", pin)

    def create_user(self, actor: User, name: str, role: str, pin: str) -> User:
        if not actor.is_director:
            raise PermissionDenied("사용자 관리는 원장만 할 수 있습니다.")
        if role not in ("원장", "강사"):
            raise ValidationError("역할을 선택하십시오.")
        return self._insert(actor.id, name, role, pin)

    def _insert(self, actor_id, name: str, role: str, pin: str) -> User:
        name = (name or "").strip()
        if not name:
            raise ValidationError("이름: 필수 입력 항목입니다.")
        validate_pin(pin)
        if self.conn.execute("SELECT 1 FROM user WHERE name = ?", (name,)).fetchone():
            raise ValidationError("같은 이름의 사용자가 이미 있습니다.")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO user(name, role, pin_hash) VALUES (?, ?, ?)", (name, role, hash_pin(pin)))
            audit.log(self.conn, actor_id, "user.create", f"user:{cur.lastrowid}", role)
        return User(cur.lastrowid, name, role)

    # ---- 로그인 ----
    def login(self, user_id: int, pin: str) -> User:
        now = time.monotonic()
        state = self._fails.get(user_id)
        if state and state[1] > now:
            raise AuthError(f"로그인 시도가 너무 많습니다. {int(state[1] - now) + 1}초 후 다시 시도하십시오.")
        row = self.conn.execute(
            "SELECT id, name, role, pin_hash FROM user WHERE id = ? AND active = 1", (user_id,)).fetchone()
        if row is None or not verify_pin(pin or "", row["pin_hash"]):
            count = (state[0] if state else 0) + 1
            self._fails[user_id] = [count, now + LOCK_SECONDS if count >= MAX_FAILS else 0]
            if count >= MAX_FAILS:
                self._fails[user_id][0] = 0
            raise AuthError("PIN이 올바르지 않습니다.")
        self._fails.pop(user_id, None)
        return User(row["id"], row["name"], row["role"])

    # ---- 관리 ----
    def reset_pin(self, actor: User, user_id: int, new_pin: str) -> None:
        if not actor.is_director:
            raise PermissionDenied("PIN 재설정은 원장만 할 수 있습니다.")
        validate_pin(new_pin)
        with self.conn:
            self.conn.execute("UPDATE user SET pin_hash = ? WHERE id = ?", (hash_pin(new_pin), user_id))
            audit.log(self.conn, actor.id, "user.reset_pin", f"user:{user_id}")

    def set_active(self, actor: User, user_id: int, active: bool) -> None:
        if not actor.is_director:
            raise PermissionDenied("사용자 관리는 원장만 할 수 있습니다.")
        if not active:
            if user_id == actor.id:
                raise ValidationError("본인 계정은 사용 중지할 수 없습니다.")
            row = self.conn.execute("SELECT role FROM user WHERE id = ?", (user_id,)).fetchone()
            if row and row["role"] == "원장":
                left = self.conn.execute(
                    "SELECT COUNT(*) FROM user WHERE role = '원장' AND active = 1 AND id != ?", (user_id,)).fetchone()[0]
                if left == 0:
                    raise ValidationError("마지막 원장 계정은 사용 중지할 수 없습니다.")
        with self.conn:
            self.conn.execute("UPDATE user SET active = ? WHERE id = ?", (1 if active else 0, user_id))
            audit.log(self.conn, actor.id, "user.activate" if active else "user.deactivate", f"user:{user_id}")
