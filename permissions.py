"""개인정보 열람 권한 판정.

규칙(확정):
- 원장: 항상 열람 가능
- 강사: 본인이 담당하는 수업에 등록된 학생이면 담당 강사. 수업별로 독립 판정하며 하나라도 해당되면 열람 가능
    · 수강중  → 가능
    · 휴원    → 휴원일(상태 변경일)부터 '휴원 유예 개월' 이내
    · 종료    → 종료일(상태 변경일)부터 '종료 유예 개월' 이내
    · 특강 수업은 기간(종료일)이 지나면 '종료'로 간주하며 종료일을 상태 변경일로 본다
- 휴원 중 복귀하면 수강중으로 전환되어 기간이 초기화된다 (상태 변경일 갱신으로 처리)
- 유예 기간 설정을 바꾸면 진행 중인 건에도 즉시 적용된다 (판정 시점마다 설정값을 읽음)
"""
from __future__ import annotations

from datetime import date

from . import settings
from .common import add_months, parse_date


def effective_state(status: str, changed_at: str, class_type: str, class_end, today: date):
    """(실효 상태, 기준일) 반환. 기간이 끝난 특강의 '수강중'은 '종료'로 간주한다."""
    if status == "수강중" and class_type == "특강" and class_end:
        end = parse_date(class_end)
        if today > end:
            return "종료", end
    return status, parse_date(changed_at)


def allows(status: str, changed: date, today: date, leave_months: int, end_months: int) -> bool:
    if status == "수강중":
        return True
    if status == "휴원":
        return today <= add_months(changed, leave_months)
    if status == "종료":
        return today <= add_months(changed, end_months)
    return False


class PermissionService:
    def __init__(self, conn):
        self.conn = conn

    def can_view_private(self, user, student_id: int, today: date | None = None) -> bool:
        if user is None:
            return False
        if user.is_director:
            return True
        today = today or date.today()
        leave_m = settings.get_int(self.conn, "grace_leave_months")
        end_m = settings.get_int(self.conn, "grace_end_months")
        rows = self.conn.execute(
            """SELECT e.status, e.status_changed_at, c.type, c.end_date
                 FROM enrollment e
                 JOIN class c ON c.id = e.class_id
                 JOIN class_teacher t ON t.class_id = c.id
                WHERE e.student_id = ? AND t.user_id = ?""",
            (student_id, user.id),
        ).fetchall()
        for r in rows:
            status, changed = effective_state(r["status"], r["status_changed_at"], r["type"], r["end_date"], today)
            if allows(status, changed, today, leave_m, end_m):
                return True
        return False

    def can_view_family(self, user, family_id: int, today: date | None = None) -> bool:
        """가족(보호자 연락처·메모)은 가족 구성원 중 한 명이라도 담당이면 열람 가능."""
        if user is None:
            return False
        if user.is_director:
            return True
        ids = [r[0] for r in self.conn.execute("SELECT id FROM student WHERE family_id = ?", (family_id,))]
        return any(self.can_view_private(user, sid, today) for sid in ids)
