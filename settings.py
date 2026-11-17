"""설정값 조회·저장 (유예 기간, 자동 잠금 시간)."""
from __future__ import annotations

from ..db.schema import DEFAULT_SETTINGS
from . import audit
from .common import PermissionDenied, ValidationError

LIMITS = {
    "grace_leave_months": (0, 36, "휴원 후 열람 유예(개월)"),
    "grace_end_months": (0, 36, "수강 종료 후 열람 유예(개월)"),
    "auto_lock_minutes": (1, 120, "자동 잠금 시간(분)"),
}


def get_int(conn, key: str) -> int:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return int(row[0]) if row else int(DEFAULT_SETTINGS[key])


def parse_value(key: str, raw) -> int:
    low, high, label = LIMITS[key]
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ValidationError(f"{label}: 숫자를 입력하십시오.") from None
    if not low <= value <= high:
        raise ValidationError(f"{label}: {low}~{high} 사이로 입력하십시오.")
    return value


def set_int(conn, user, key: str, raw) -> int:
    if not user.is_director:
        raise PermissionDenied("설정은 원장만 변경할 수 있습니다.")
    value = parse_value(key, raw)
    with conn:
        conn.execute(
            "INSERT INTO setting(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        audit.log(conn, user.id, "setting.update", key, str(value))
    return value
