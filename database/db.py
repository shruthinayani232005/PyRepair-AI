"""SQLite 'agent memory': every debugging session is stored and can be reopened."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "pyrepair.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, original_code TEXT,
            error TEXT, diagnosis TEXT, repaired_code TEXT, attempts INTEGER,
            status TEXT, output TEXT, details TEXT)""")


def save_session(res):
    first = res["original_result"]
    error = f'{first["error_type"]}: {first["error_message"]}' if not first["success"] else ""
    diag = res["attempts"][-1]["diagnosis"] if res["attempts"] else {}
    final = res["final_result"]
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sessions (created_at, original_code, error, diagnosis, repaired_code,"
            " attempts, status, output, details) VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), res["original_code"], error,
             json.dumps(diag), res["final_code"], len(res["attempts"]), res["status"],
             (final["stdout"] + final["stderr"]), json.dumps(res)))
        return cur.lastrowid


def list_sessions(limit=50):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, created_at, error, status, attempts FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,))]


def get_session(session_id):
    with _conn() as c:
        row = c.execute("SELECT details FROM sessions WHERE id=?", (session_id,)).fetchone()
        return json.loads(row["details"]) if row else None


def clear_history():
    with _conn() as c:
        c.execute("DELETE FROM sessions")
