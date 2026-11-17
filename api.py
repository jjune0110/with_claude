"""JSON API. 권한 판정·검증은 모두 services 계층에서 처리하고, 여기서는 요청/응답만 변환한다."""
from __future__ import annotations

import re

from ..services import settings
from ..services.common import PermissionDenied, ValidationError
from ..services.registry import Registry

ROUTES = []


def route(method: str, pattern: str, access: str = "login"):
    """access: 'public' | 'login' | 'director'"""
    regex = re.compile("^" + pattern + "$")

    def decorator(func):
        ROUTES.append((method, regex, access, func))
        return func

    return decorator


def match(method: str, path: str):
    for m, regex, access, func in ROUTES:
        found = regex.match(path)
        if found and m == method:
            return func, access, [int(g) for g in found.groups()]
    return None


class Context:
    def __init__(self, server, session, params, body, query):
        self.server = server
        self.conn = server.conn
        self.auth = server.auth
        self.session = session
        self.user = session.user if session else None
        self.params = params
        self.body = body
        self.query = query
        self.reg = Registry(self.conn, self.user) if self.user else None
        self.new_user = None      # 로그인 성공 시 세션 발급
        self.end_session = False  # 로그아웃·잠금 시 세션 폐기

    def s(self, key: str) -> str:
        value = self.body.get(key, "")
        return "" if value is None else str(value)

    def opt_int(self, key: str):
        value = self.body.get(key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError("잘못된 요청입니다.") from None


def user_dict(user) -> dict:
    return {"id": user.id, "name": user.name, "role": user.role, "is_director": user.is_director}


# ---------------------------------------------------------------- 세션
@route("GET", r"/api/state", "public")
def state(c):
    return {
        "has_users": c.auth.has_users(),
        "user": user_dict(c.user) if c.user else None,
        "lock_minutes": settings.get_int(c.conn, "auto_lock_minutes"),
    }


@route("GET", r"/api/login-users", "public")
def login_users(c):
    return {"users": c.auth.list_login_users()}


@route("POST", r"/api/setup", "public")
def setup(c):
    if c.s("pin") != c.s("pin2"):
        raise ValidationError("PIN 확인이 일치하지 않습니다.")
    user = c.auth.create_first_director(c.s("name"), c.s("pin"))
    c.new_user = user
    return {"user": user_dict(user)}


@route("POST", r"/api/login", "public")
def login(c):
    user_id = c.opt_int("user_id")
    if user_id is None:
        raise ValidationError("사용자를 선택하십시오.")
    user = c.auth.login(user_id, c.s("pin"))
    c.new_user = user
    return {"user": user_dict(user)}


@route("POST", r"/api/logout", "public")
def logout(c):
    c.end_session = True
    return {"ok": True}


@route("POST", r"/api/lock", "public")
def lock(c):
    c.end_session = True
    return {"ok": True}


@route("POST", r"/api/ping")
def ping(c):
    return {"ok": True}


@route("POST", r"/api/shutdown", "director")
def shutdown(c):
    c.server.request_shutdown()
    return {"ok": True}


# ---------------------------------------------------------------- 학생
@route("GET", r"/api/students")
def students(c):
    return {"students": c.reg.list_students(c.query.get("q", ""))}


@route("POST", r"/api/students")
def student_create(c):
    return {"id": c.reg.create_student(c.s("name"), c.s("grade"), c.opt_int("family_id"))}


@route("GET", r"/api/students/(\d+)")
def student_detail(c):
    sid = c.params[0]
    student = c.reg.get_student(sid)
    out = {"student": student, "enrollments": c.reg.list_enrollments(sid),
           "private": None, "private_error": None, "family_name": None}
    try:
        out["private"] = c.reg.get_private(sid)
    except PermissionDenied as exc:
        out["private_error"] = str(exc)
    if c.user.is_director and student["family_id"]:
        out["family_name"] = next(
            (f["name"] for f in c.reg.list_families() if f["id"] == student["family_id"]), None)
    return out


@route("PUT", r"/api/students/(\d+)")
def student_update(c):
    c.reg.update_student(c.params[0], c.s("name"), c.s("grade"), c.opt_int("family_id"))
    return {"ok": True}


@route("DELETE", r"/api/students/(\d+)")
def student_delete(c):
    c.reg.delete_student(c.params[0])
    return {"ok": True}


@route("PUT", r"/api/students/(\d+)/private")
def student_private(c):
    c.reg.save_private(c.params[0], c.s("phone"), c.s("address"), c.s("school"))
    return {"ok": True}


# ---------------------------------------------------------------- 수강
@route("POST", r"/api/students/(\d+)/enrollments")
def enroll(c):
    class_id = c.opt_int("class_id")
    if class_id is None:
        raise ValidationError("수업을 선택하십시오.")
    return {"id": c.reg.enroll(c.params[0], class_id, c.s("start_date"))}


@route("PUT", r"/api/enrollments/(\d+)")
def enrollment_status(c):
    c.reg.set_status(c.params[0], c.s("status"), c.s("date"))
    return {"ok": True}


@route("DELETE", r"/api/enrollments/(\d+)")
def enrollment_delete(c):
    c.reg.remove_enrollment(c.params[0])
    return {"ok": True}


# ---------------------------------------------------------------- 가족·보호자
@route("GET", r"/api/families")
def families(c):
    return {"families": c.reg.list_families()}


@route("POST", r"/api/families")
def family_create(c):
    return {"id": c.reg.create_family(c.s("name"))}


@route("GET", r"/api/families/(\d+)")
def family_detail(c):
    fid = c.params[0]
    return {"family": c.reg.get_family(fid), "students": c.reg.family_students(fid),
            "guardians": c.reg.list_guardians(fid)}


@route("PUT", r"/api/families/(\d+)")
def family_rename(c):
    c.reg.rename_family(c.params[0], c.s("name"))
    return {"ok": True}


@route("DELETE", r"/api/families/(\d+)")
def family_delete(c):
    c.reg.delete_family(c.params[0])
    return {"ok": True}


@route("PUT", r"/api/families/(\d+)/memo")
def family_memo(c):
    c.reg.update_memo(c.params[0], c.s("memo"))
    return {"ok": True}


@route("POST", r"/api/families/(\d+)/guardians")
def guardian_add(c):
    return {"id": c.reg.add_guardian(c.params[0], c.s("name"), c.s("relation"), c.s("phone"),
                                     bool(c.body.get("contact_restricted")))}


@route("PUT", r"/api/guardians/(\d+)")
def guardian_update(c):
    c.reg.update_guardian(c.params[0], c.s("name"), c.s("relation"), c.s("phone"),
                          bool(c.body.get("contact_restricted")))
    return {"ok": True}


@route("DELETE", r"/api/guardians/(\d+)")
def guardian_delete(c):
    c.reg.delete_guardian(c.params[0])
    return {"ok": True}


# ---------------------------------------------------------------- 수업·특강 (원장)
@route("GET", r"/api/classes", "director")
def classes(c):
    return {"classes": c.reg.list_classes()}


@route("POST", r"/api/classes", "director")
def class_create(c):
    return {"id": c.reg.create_class(c.s("name"), c.s("type"), c.s("start_date"), c.s("end_date"), c.s("fee"))}


@route("PUT", r"/api/classes/(\d+)", "director")
def class_update(c):
    c.reg.update_class(c.params[0], c.s("name"), c.s("type"), c.s("start_date"), c.s("end_date"), c.s("fee"))
    return {"ok": True}


@route("DELETE", r"/api/classes/(\d+)", "director")
def class_delete(c):
    c.reg.delete_class(c.params[0])
    return {"ok": True}


@route("GET", r"/api/classes/(\d+)/teachers", "director")
def class_teachers(c):
    return {"candidates": c.reg.teacher_candidates(), "selected": c.reg.get_teacher_ids(c.params[0])}


@route("PUT", r"/api/classes/(\d+)/teachers", "director")
def class_set_teachers(c):
    ids = c.body.get("user_ids")
    if not isinstance(ids, list):
        raise ValidationError("잘못된 요청입니다.")
    c.reg.set_teachers(c.params[0], ids)
    return {"ok": True}


# ---------------------------------------------------------------- 사용자·설정 (원장)
@route("GET", r"/api/users", "director")
def users(c):
    return {"users": c.auth.list_users()}


@route("POST", r"/api/users", "director")
def user_create(c):
    if c.s("pin") != c.s("pin2"):
        raise ValidationError("PIN 확인이 일치하지 않습니다.")
    return {"id": c.auth.create_user(c.user, c.s("name"), c.s("role"), c.s("pin")).id}


@route("PUT", r"/api/users/(\d+)/pin", "director")
def user_pin(c):
    if c.s("pin") != c.s("pin2"):
        raise ValidationError("PIN 확인이 일치하지 않습니다.")
    c.auth.reset_pin(c.user, c.params[0], c.s("pin"))
    return {"ok": True}


@route("PUT", r"/api/users/(\d+)/active", "director")
def user_active(c):
    c.auth.set_active(c.user, c.params[0], bool(c.body.get("active")))
    return {"ok": True}


@route("GET", r"/api/settings", "director")
def settings_get(c):
    return {key: settings.get_int(c.conn, key) for key in settings.LIMITS}


@route("PUT", r"/api/settings", "director")
def settings_put(c):
    parsed = {key: settings.parse_value(key, c.body[key]) for key in settings.LIMITS if key in c.body}
    for key, value in parsed.items():          # 모두 검증을 통과한 뒤에만 저장
        settings.set_int(c.conn, c.user, key, value)
    return {key: settings.get_int(c.conn, key) for key in settings.LIMITS}
