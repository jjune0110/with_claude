"""SQLite 연결과 스키마 마이그레이션. 모든 경로는 프로그램 폴더 기준 상대 경로다."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .schema import DEFAULT_SETTINGS, MIGRATIONS

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("ACADEMY_DB") or (DATA_DIR / "academy.db"))


def connect(db_path=None, check_same_thread: bool = True) -> sqlite3.Connection:
    path = str(db_path) if db_path is not None else str(DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for target, script in enumerate(MIGRATIONS, start=1):
        if target > version:
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {target}")
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO setting(key, value) VALUES (?, ?)", (key, value))
    conn.commit()
