"""SQLite storage, scoped retrieval, and append-only usage evidence."""
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import validation as v

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('schema_version', 1), ('review_watermark', 0);
CREATE TABLE IF NOT EXISTS experiences (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 case_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
 project TEXT NOT NULL, scope TEXT NOT NULL CHECK(scope IN ('project','global')),
 search_text TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','needs_review','archived')),
 revision INTEGER NOT NULL DEFAULT 1,
 merged_into INTEGER REFERENCES experiences(id), created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS experiences_scope ON experiences(status, project, scope);
CREATE TABLE IF NOT EXISTS outcomes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
 experience_id INTEGER NOT NULL REFERENCES experiences(id), result TEXT NOT NULL,
 payload TEXT NOT NULL, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outcomes_experience ON outcomes(experience_id);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY AUTOINCREMENT, review_key TEXT NOT NULL UNIQUE,
 up_to INTEGER NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
"""


@contextmanager
def connect(path, initialize=False):
    path = Path(path).expanduser().resolve()
    if initialize:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.is_file():
        raise ValueError("database does not exist; use init with the intended persistent path")
    db = sqlite3.connect(path.as_uri() + ("?mode=rwc" if initialize else "?mode=rw"),
                         uri=True, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        if initialize:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and "meta" not in tables:
                raise ValueError("refusing to initialize an unrelated database")
            if not tables:
                db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
        version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not version or version[0] != 1:
            raise ValueError("unsupported database schema version")
        yield db
    finally:
        db.close()


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def status(db):
    row = db.execute("""SELECT COALESCE(MAX(id),0) AS total,
        (SELECT value FROM meta WHERE key='review_watermark') AS watermark,
        SUM(status='active') AS active, SUM(status='needs_review') AS needs_review,
        SUM(status='archived') AS archived FROM experiences""").fetchone()
    total, watermark = row["total"], row["watermark"]
    return {"total_added": total, "reviewed_through": watermark,
            "new_since_review": total - watermark, "review_interval": 20,
            "review_due": total - watermark >= 20 or bool(row["needs_review"]),
            "counts": {k: row[k] or 0 for k in ("active", "needs_review", "archived")}}


def get_row(db, experience_id):
    row = db.execute("SELECT * FROM experiences WHERE id=?", (experience_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown experience id: {experience_id}")
    return row


def view(db, row):
    usage = {r["result"]: r["n"] for r in db.execute(
        "SELECT result, COUNT(*) AS n FROM outcomes WHERE experience_id=? GROUP BY result",
        (row["id"],))}
    return {"id": row["id"], "status": row["status"], "revision": row["revision"],
            "merged_into": row["merged_into"], "created_at": row["created_at"],
            "case": json.loads(row["payload"]), "usage": usage}


def show(db, experience_id):
    result = view(db, get_row(db, experience_id))
    result["outcomes"] = [json.loads(r[0]) for r in db.execute(
        "SELECT payload FROM outcomes WHERE experience_id=? ORDER BY id", (experience_id,))]
    result["reviews"] = []
    for row in db.execute("SELECT id, payload, created_at FROM reviews ORDER BY id"):
        data = json.loads(row["payload"])
        for decision in data["decisions"]:
            if decision["experience_id"] == experience_id:
                result["reviews"].append({"review_id": row["id"],
                    "created_at": row["created_at"], "decision": decision})
    return result


def add(db, value):
    v.case(value)
    hashed = v.digest(value)
    with transaction(db):
        old = db.execute("SELECT id,payload_hash FROM experiences WHERE case_key=?",
                         (value["case_key"],)).fetchone()
        if old:
            if old["payload_hash"] != hashed:
                raise ValueError("case_key already exists with different content")
            return {"id": old["id"], "duplicate": True, **status(db)}
        search_text = " ".join([value["title"], value["error"], value["cause"],
                                *value["tags"], *value["solution"]]).casefold()
        cursor = db.execute("""INSERT INTO experiences
            (case_key,payload,payload_hash,project,scope,search_text,created_at)
            VALUES (?,?,?,?,?,?,?)""", (value["case_key"], v.canonical(value), hashed,
            value["project"], value["scope"], search_text, v.now()))
        return {"id": cursor.lastrowid, "duplicate": False, **status(db)}


def record_outcome(db, value):
    v.outcome(value)
    hashed = v.digest(value)
    with transaction(db):
        old = db.execute("SELECT id,payload_hash FROM outcomes WHERE event_key=?",
                         (value["event_key"],)).fetchone()
        if old:
            if old["payload_hash"] != hashed:
                raise ValueError("event_key already exists with different content")
            return {"outcome_id": old["id"], "duplicate": True, **status(db)}
        row = get_row(db, value["experience_id"])
        new_status = "needs_review" if value["result"] == "failure" and row["status"] != "archived" else row["status"]
        db.execute("UPDATE experiences SET revision=revision+1,status=? WHERE id=?",
                   (new_status, row["id"]))
        cursor = db.execute("""INSERT INTO outcomes
            (event_key,experience_id,result,payload,payload_hash,created_at) VALUES (?,?,?,?,?,?)""",
            (value["event_key"], row["id"], value["result"], v.canonical(value), hashed, v.now()))
        return {"outcome_id": cursor.lastrowid, "duplicate": False, **status(db)}


def search(db, query, project=None, tags=(), environment=None, limit=5):
    v.text(query, "query", 1000)
    v.integer(limit, "limit")
    if limit > 20:
        raise ValueError("limit must be <= 20")
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query.casefold())))[:16]
    if not terms:
        return []
    sql = "SELECT * FROM experiences WHERE status='active' AND "
    params = []
    if project:
        sql += "(project=? OR scope='global')"
        params.append(project)
    else:
        sql += "scope='global'"
    sql += " AND (" + " OR ".join("search_text LIKE ?" for _ in terms) + ")"
    params.extend("%" + term + "%" for term in terms)
    matches = []
    for row in db.execute(sql, params):
        data = json.loads(row["payload"])
        if not set(tags).issubset(data["tags"]):
            continue
        if any(data["environment"].get(k) != val for k, val in (environment or {}).items()):
            continue
        score = sum(1 + 2 * (t in data["title"].casefold()) for t in terms if t in row["search_text"])
        matches.append((score, row))
    matches.sort(key=lambda item: (-item[0], -item[1]["id"]))
    return [{"match_score": score, **view(db, row)} for score, row in matches[:limit]]
