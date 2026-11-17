"""학생·가족·수업·수강 등록 서비스. 모든 권한 검사와 수정 이력은 이 계층에서 처리한다."""
from __future__ import annotations

from datetime import date

from . import audit
from .common import PermissionDenied, ValidationError, normalize_date, now_str
from .permissions import PermissionService, effective_state

STATUSES = ("수강중", "휴원", "종료")
CLASS_TYPES = ("정규", "특강")
MEMO_LIMIT = 500


def _required(value, label: str, max_len: int = 100) -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationError(f"{label}: 필수 입력 항목입니다.")
    if len(text) > max_len:
        raise ValidationError(f"{label}: {max_len}자 이내로 입력하십시오.")
    return text


def _optional(value, label: str, max_len: int = 200) -> str:
    text = (value or "").strip()
    if len(text) > max_len:
        raise ValidationError(f"{label}: {max_len}자 이내로 입력하십시오.")
    return text


class Registry:
    def __init__(self, conn, user):
        self.conn = conn
        self.user = user
        self.perm = PermissionService(conn)

    # ---------- 공통 ----------
    def _require_director(self) -> None:
        if not self.user.is_director:
            raise PermissionDenied("원장만 수행할 수 있습니다.")

    def _log(self, action: str, target: str = "", detail: str = "") -> None:
        audit.log(self.conn, self.user.id, action, target, detail)

    def _rows(self, sql: str, params=()):
        return [dict(r) for r in self.conn.execute(sql, params)]

    # ---------- 가족 ----------
    def list_families(self):
        rows = self._rows("SELECT id, name FROM family ORDER BY name")
        if self.user.is_director:
            return rows
        return [r for r in rows if self.perm.can_view_family(self.user, r["id"])]

    def _check_family(self, family_id: int) -> None:
        if not self.perm.can_view_family(self.user, family_id):
            raise PermissionDenied("이 가족 정보를 열람할 권한이 없습니다.")

    def get_family(self, family_id: int):
        self._check_family(family_id)
        rows = self._rows(
            """SELECT f.id, f.name, f.memo, f.memo_updated_at, u.name AS memo_updated_by
                 FROM family f LEFT JOIN user u ON u.id = f.memo_updated_by WHERE f.id = ?""", (family_id,))
        if not rows:
            raise ValidationError("가족 정보를 찾을 수 없습니다.")
        return rows[0]

    def family_students(self, family_id: int):
        self._check_family(family_id)
        return self._rows("SELECT id, name, grade FROM student WHERE family_id = ? ORDER BY name", (family_id,))

    def create_family(self, name: str) -> int:
        self._require_director()
        name = _required(name, "가족 이름")
        with self.conn:
            cur = self.conn.execute("INSERT INTO family(name) VALUES (?)", (name,))
            self._log("family.create", f"family:{cur.lastrowid}")
        return cur.lastrowid

    def rename_family(self, family_id: int, name: str) -> None:
        self._require_director()
        name = _required(name, "가족 이름")
        with self.conn:
            self.conn.execute("UPDATE family SET name = ? WHERE id = ?", (name, family_id))
            self._log("family.update", f"family:{family_id}")

    def delete_family(self, family_id: int) -> None:
        self._require_director()
        if self.conn.execute("SELECT 1 FROM student WHERE family_id = ?", (family_id,)).fetchone():
            raise ValidationError("소속 학생이 있어 삭제할 수 없습니다. 학생의 가족 지정을 먼저 해제하십시오.")
        with self.conn:
            self.conn.execute("DELETE FROM family WHERE id = ?", (family_id,))
            self._log("family.delete", f"family:{family_id}")

    def update_memo(self, family_id: int, text: str) -> None:
        self._check_family(family_id)
        text = (text or "").rstrip()
        if len(text) > MEMO_LIMIT:
            raise ValidationError(f"메모는 {MEMO_LIMIT}자 이내로 입력하십시오. (현재 {len(text)}자)")
        with self.conn:
            self.conn.execute(
                "UPDATE family SET memo = ?, memo_updated_by = ?, memo_updated_at = ? WHERE id = ?",
                (text, self.user.id, now_str(), family_id))
            self._log("family.memo", f"family:{family_id}")  # 내용은 기록하지 않음

    # ---------- 보호자 ----------
    def list_guardians(self, family_id: int):
        self._check_family(family_id)
        return self._rows(
            "SELECT id, name, relation, phone, contact_restricted FROM guardian WHERE family_id = ? ORDER BY id",
            (family_id,))

    def _guardian_values(self, name, relation, phone):
        return (_required(name, "보호자 이름"), _optional(relation, "관계", 30), _optional(phone, "연락처", 30))

    def add_guardian(self, family_id: int, name, relation, phone, contact_restricted=False) -> int:
        self._require_director()
        n, r, p = self._guardian_values(name, relation, phone)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO guardian(family_id, name, relation, phone, contact_restricted) VALUES (?,?,?,?,?)",
                (family_id, n, r, p, 1 if contact_restricted else 0))
            self._log("guardian.create", f"guardian:{cur.lastrowid}")
        return cur.lastrowid

    def update_guardian(self, guardian_id: int, name, relation, phone, contact_restricted=False) -> None:
        self._require_director()
        n, r, p = self._guardian_values(name, relation, phone)
        with self.conn:
            self.conn.execute(
                "UPDATE guardian SET name=?, relation=?, phone=?, contact_restricted=? WHERE id=?",
                (n, r, p, 1 if contact_restricted else 0, guardian_id))
            self._log("guardian.update", f"guardian:{guardian_id}")

    def delete_guardian(self, guardian_id: int) -> None:
        self._require_director()
        with self.conn:
            self.conn.execute("DELETE FROM guardian WHERE id = ?", (guardian_id,))
            self._log("guardian.delete", f"guardian:{guardian_id}")

    # ---------- 학생 (수업정보: 전원 열람) ----------
    def list_students(self, keyword: str = ""):
        keyword = (keyword or "").strip()
        if keyword:
            return self._rows(
                "SELECT id, name, grade, family_id FROM student WHERE name LIKE ? ORDER BY name",
                (f"%{keyword}%",))
        return self._rows("SELECT id, name, grade, family_id FROM student ORDER BY name")

    def get_student(self, student_id: int):
        rows = self._rows("SELECT id, name, grade, family_id FROM student WHERE id = ?", (student_id,))
        if not rows:
            raise ValidationError("학생 정보를 찾을 수 없습니다.")
        return rows[0]

    def create_student(self, name, grade, family_id) -> int:
        self._require_director()
        name = _required(name, "학생 이름")
        grade = _optional(grade, "학년", 20)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO student(name, grade, family_id) VALUES (?,?,?)", (name, grade, family_id))
            self._log("student.create", f"student:{cur.lastrowid}")
        return cur.lastrowid

    def update_student(self, student_id: int, name, grade, family_id) -> None:
        self._require_director()
        name = _required(name, "학생 이름")
        grade = _optional(grade, "학년", 20)
        with self.conn:
            self.conn.execute(
                "UPDATE student SET name=?, grade=?, family_id=? WHERE id=?", (name, grade, family_id, student_id))
            self._log("student.update", f"student:{student_id}")

    def delete_student(self, student_id: int) -> None:
        self._require_director()
        if self.conn.execute("SELECT 1 FROM enrollment WHERE student_id = ?", (student_id,)).fetchone():
            raise ValidationError("수강 내역이 있는 학생은 삭제할 수 없습니다. 수강 등록을 먼저 취소하십시오.")
        with self.conn:
            self.conn.execute("DELETE FROM student WHERE id = ?", (student_id,))
            self._log("student.delete", f"student:{student_id}")

    # ---------- 학생 (개인정보: 원장 + 담당 강사) ----------
    def get_private(self, student_id: int):
        if not self.perm.can_view_private(self.user, student_id):
            raise PermissionDenied("개인정보 열람 권한이 없습니다. (원장 또는 담당 강사만 열람 가능)")
        rows = self._rows("SELECT phone, address, school FROM student_private WHERE student_id = ?", (student_id,))
        return rows[0] if rows else {"phone": "", "address": "", "school": ""}

    def save_private(self, student_id: int, phone, address, school) -> None:
        self._require_director()
        values = (_optional(phone, "연락처", 30), _optional(address, "주소", 200), _optional(school, "학교", 60))
        with self.conn:
            self.conn.execute(
                """INSERT INTO student_private(student_id, phone, address, school) VALUES (?,?,?,?)
                   ON CONFLICT(student_id) DO UPDATE SET
                       phone = excluded.phone, address = excluded.address, school = excluded.school""",
                (student_id, *values))
            self._log("student.private.update", f"student:{student_id}")  # 값은 기록하지 않음

    # ---------- 수업·특강 (원장 전용: 금액 포함) ----------
    def list_classes(self):
        self._require_director()
        return self._rows(
            """SELECT c.id, c.name, c.type, c.start_date, c.end_date, c.fee,
                      (SELECT GROUP_CONCAT(u.name, ', ')
                         FROM class_teacher t JOIN user u ON u.id = t.user_id
                        WHERE t.class_id = c.id) AS teachers
                 FROM class c ORDER BY c.type, c.name""")

    def _class_values(self, name, ctype, start, end, fee):
        name = _required(name, "수업 이름")
        if ctype not in CLASS_TYPES:
            raise ValidationError("유형을 선택하십시오.")
        start_n = normalize_date(start, required=(ctype == "특강"))
        end_n = normalize_date(end, required=(ctype == "특강"))
        if start_n and end_n and start_n > end_n:
            raise ValidationError("종료일이 시작일보다 빠릅니다.")
        try:
            fee_n = int(str(fee).replace(",", "").strip() or "0")
        except ValueError:
            raise ValidationError("금액: 숫자만 입력하십시오.") from None
        if fee_n < 0:
            raise ValidationError("금액: 0 이상으로 입력하십시오.")
        return name, ctype, start_n, end_n, fee_n

    def create_class(self, name, ctype, start, end, fee) -> int:
        self._require_director()
        values = self._class_values(name, ctype, start, end, fee)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO class(name, type, start_date, end_date, fee) VALUES (?,?,?,?,?)", values)
            self._log("class.create", f"class:{cur.lastrowid}")
        return cur.lastrowid

    def update_class(self, class_id: int, name, ctype, start, end, fee) -> None:
        self._require_director()
        values = self._class_values(name, ctype, start, end, fee)
        with self.conn:
            self.conn.execute(
                "UPDATE class SET name=?, type=?, start_date=?, end_date=?, fee=? WHERE id=?", (*values, class_id))
            self._log("class.update", f"class:{class_id}")

    def delete_class(self, class_id: int) -> None:
        self._require_director()
        if self.conn.execute("SELECT 1 FROM enrollment WHERE class_id = ?", (class_id,)).fetchone():
            raise ValidationError("수강생이 있는 수업은 삭제할 수 없습니다.")
        with self.conn:
            self.conn.execute("DELETE FROM class WHERE id = ?", (class_id,))
            self._log("class.delete", f"class:{class_id}")

    def teacher_candidates(self):
        self._require_director()
        return self._rows("SELECT id, name FROM user WHERE role = '강사' AND active = 1 ORDER BY name")

    def get_teacher_ids(self, class_id: int):
        self._require_director()
        return [r[0] for r in self.conn.execute("SELECT user_id FROM class_teacher WHERE class_id = ?", (class_id,))]

    def set_teachers(self, class_id: int, user_ids) -> None:
        self._require_director()
        valid = {r["id"] for r in self.teacher_candidates()}
        ids = [int(i) for i in user_ids]
        if any(i not in valid for i in ids):
            raise ValidationError("사용 중인 강사만 지정할 수 있습니다.")
        with self.conn:
            self.conn.execute("DELETE FROM class_teacher WHERE class_id = ?", (class_id,))
            self.conn.executemany("INSERT INTO class_teacher(class_id, user_id) VALUES (?, ?)",
                                  [(class_id, i) for i in ids])
            self._log("class.teachers", f"class:{class_id}", ",".join(map(str, ids)))

    # ---------- 수강 등록 ----------
    def list_enrollments(self, student_id: int, today: date | None = None):
        today = today or date.today()
        rows = self._rows(
            """SELECT e.id, e.class_id, c.name AS class_name, c.type AS class_type, c.end_date,
                      e.status, e.status_changed_at, e.start_date
                 FROM enrollment e JOIN class c ON c.id = e.class_id
                WHERE e.student_id = ? ORDER BY c.name""", (student_id,))
        for r in rows:
            eff, _ = effective_state(r["status"], r["status_changed_at"], r["class_type"], r["end_date"], today)
            r["effective_status"] = eff
        return rows

    def enroll(self, student_id: int, class_id: int, start_date) -> int:
        self._require_director()
        start = normalize_date(start_date)
        if self.conn.execute("SELECT 1 FROM enrollment WHERE student_id=? AND class_id=?",
                             (student_id, class_id)).fetchone():
            raise ValidationError("이미 수강 등록된 수업입니다. 다시 수강하려면 '상태 변경'을 이용하십시오.")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO enrollment(student_id, class_id, status, status_changed_at, start_date) "
                "VALUES (?, ?, '수강중', ?, ?)", (student_id, class_id, start, start))
            self._log("enrollment.create", f"enrollment:{cur.lastrowid}")
        return cur.lastrowid

    def set_status(self, enrollment_id: int, status: str, changed_date) -> None:
        self._require_director()
        if status not in STATUSES:
            raise ValidationError("상태를 선택하십시오.")
        changed = normalize_date(changed_date)
        with self.conn:
            self.conn.execute(
                "UPDATE enrollment SET status = ?, status_changed_at = ? WHERE id = ?",
                (status, changed, enrollment_id))
            self._log("enrollment.status", f"enrollment:{enrollment_id}", f"{status} {changed}")

    def remove_enrollment(self, enrollment_id: int) -> None:
        self._require_director()
        with self.conn:
            self.conn.execute("DELETE FROM enrollment WHERE id = ?", (enrollment_id,))
            self._log("enrollment.delete", f"enrollment:{enrollment_id}")
