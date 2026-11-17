"""수정 이력. 개인정보·메모의 '값'은 기록하지 않고 대상과 동작만 남긴다."""
from __future__ import annotations

from .common import now_str


def log(conn, user_id, action: str, target: str = "", detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log(at, user_id, action, target, detail) VALUES (?, ?, ?, ?, ?)",
        (now_str(), user_id, action, target, detail),
    )
