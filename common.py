"""서비스 계층 공통: 예외, 날짜 유틸."""
from __future__ import annotations

import calendar
from datetime import date, datetime


class ValidationError(ValueError):
    """입력값 오류. 메시지를 그대로 사용자에게 보여준다."""


class PermissionDenied(Exception):
    """권한 없음. 메시지를 그대로 사용자에게 보여준다."""


def parse_date(text) -> date:
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError("날짜는 YYYY-MM-DD 형식으로 입력하십시오. (예: 2026-03-02)") from None


def normalize_date(text, required=True):
    """검증 후 YYYY-MM-DD 로 정규화. 비필수 항목은 빈 값이면 None."""
    if text is None or not str(text).strip():
        if required:
            raise ValidationError("날짜를 입력하십시오.")
        return None
    return parse_date(text).isoformat()


def add_months(d: date, months: int) -> date:
    year, month0 = divmod(d.year * 12 + d.month - 1 + months, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
