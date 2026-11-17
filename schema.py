"""데이터베이스 스키마.

스키마를 바꿀 때는 MIGRATIONS 끝에 새 스크립트를 추가한다.
적용 여부는 SQLite의 PRAGMA user_version 으로 관리하므로 기존 데이터는 유지된다.
(2단계: attendance, grade_record, invoice / 3단계: notification 등을 이 방식으로 추가)
"""

MIGRATION_1 = """
CREATE TABLE user (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    role      TEXT NOT NULL CHECK (role IN ('원장', '강사')),
    pin_hash  TEXT NOT NULL,
    active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE family (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    memo             TEXT NOT NULL DEFAULT '',
    memo_updated_by  INTEGER REFERENCES user(id),
    memo_updated_at  TEXT
);

CREATE TABLE guardian (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id          INTEGER NOT NULL REFERENCES family(id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    relation           TEXT NOT NULL DEFAULT '',
    phone              TEXT NOT NULL DEFAULT '',
    contact_restricted INTEGER NOT NULL DEFAULT 0
);

-- 수업정보 영역: 모든 사용자가 열람
CREATE TABLE student (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id  INTEGER REFERENCES family(id) ON DELETE SET NULL,
    name       TEXT NOT NULL,
    grade      TEXT NOT NULL DEFAULT ''
);

-- 개인정보 영역: 원장 + 담당 강사만 열람 (별도 테이블로 분리)
CREATE TABLE student_private (
    student_id INTEGER PRIMARY KEY REFERENCES student(id) ON DELETE CASCADE,
    phone      TEXT NOT NULL DEFAULT '',
    address    TEXT NOT NULL DEFAULT '',
    school     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE class (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('정규', '특강')),
    start_date  TEXT,
    end_date    TEXT,
    fee         INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),
    CHECK (type = '정규' OR (start_date IS NOT NULL AND end_date IS NOT NULL))
);

CREATE TABLE class_teacher (
    class_id INTEGER NOT NULL REFERENCES class(id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES user(id),
    PRIMARY KEY (class_id, user_id)
);

CREATE TABLE enrollment (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id         INTEGER NOT NULL REFERENCES student(id) ON DELETE RESTRICT,
    class_id           INTEGER NOT NULL REFERENCES class(id) ON DELETE RESTRICT,
    status             TEXT NOT NULL DEFAULT '수강중' CHECK (status IN ('수강중', '휴원', '종료')),
    status_changed_at  TEXT NOT NULL,
    start_date         TEXT NOT NULL,
    UNIQUE (student_id, class_id)
);
CREATE INDEX idx_enrollment_student ON enrollment(student_id);
CREATE INDEX idx_enrollment_class ON enrollment(class_id);

CREATE TABLE setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    user_id  INTEGER,
    action   TEXT NOT NULL,
    target   TEXT NOT NULL DEFAULT '',
    detail   TEXT NOT NULL DEFAULT ''
);
"""

MIGRATIONS = [MIGRATION_1]

DEFAULT_SETTINGS = {
    "grace_leave_months": "3",   # 휴원 후 개인정보 열람 유예(개월)
    "grace_end_months": "1",     # 수강 종료 후 개인정보 열람 유예(개월)
    "auto_lock_minutes": "10",   # 무입력 자동 잠금(분)
}
