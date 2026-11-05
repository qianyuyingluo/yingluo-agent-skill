"""Optimistic, atomic, auditable reviews; new arrivals never get silently reviewed."""
import json

import store
import validation as v


def snapshot(db, up_to, include_archived):
    state = store.status(db)
    if up_to < state["reviewed_through"] or up_to > state["total_added"]:
        raise ValueError("stale or invalid review boundary; generate a new review-plan")
    rows = list(db.execute("SELECT * FROM experiences WHERE id<=? ORDER BY id", (up_to,)))
    token = v.digest({"up_to": up_to, "watermark": state["reviewed_through"],
                      "include_archived": include_archived,
                      "versions": [[r["id"], r["revision"], r["status"]] for r in rows]})
    return token, [r for r in rows if include_archived or r["status"] != "archived"]


def plan(db, include_archived=False):
    with store.transaction(db):
        state = store.status(db)
        token, rows = snapshot(db, state["total_added"], include_archived)
        entries = [store.show(db, r["id"]) for r in rows]
        return {**state, "up_to": state["total_added"], "token": token,
                "include_archived": include_archived, "entries": entries,
                "instruction": "Review every entry; provide keep/archive/merge with reasons and evidence_refs."}


def validate_decision(value):
    v.fields(value, ("experience_id", "action", "reason", "evidence_refs"),
             ("merge_into", "revalidation"))
    v.integer(value["experience_id"], "experience_id")
    v.choice(value["action"], "action", ("keep", "archive", "merge"))
    v.text(value["reason"], "reason")
    v.strings(value["evidence_refs"], "evidence_refs")
    if value["action"] == "merge":
        v.integer(value.get("merge_into"), "merge_into")
    elif "merge_into" in value:
        raise ValueError("merge_into is only allowed for merge")
    if "revalidation" in value:
        if value["action"] != "keep":
            raise ValueError("revalidation is only allowed for keep")
        v.evidence(value["revalidation"], "pass")


def apply(db, value):
    v.fields(value, ("review_key", "up_to", "token", "include_archived", "decisions"))
    v.text(value["review_key"], "review_key", 200)
    v.integer(value["up_to"], "up_to")
    v.text(value["token"], "token", 64)
    if type(value["include_archived"]) is not bool:
        raise ValueError("include_archived must be boolean")
    if not isinstance(value["decisions"], list):
        raise ValueError("decisions must be a list")
    decisions = {}
    for item in value["decisions"]:
        validate_decision(item)
        if item["experience_id"] in decisions:
            raise ValueError("duplicate experience_id in review")
        decisions[item["experience_id"]] = item
    hashed = v.digest(value)
    with store.transaction(db):
        old = db.execute("SELECT id,payload_hash FROM reviews WHERE review_key=?",
                         (value["review_key"],)).fetchone()
        if old:
            if old["payload_hash"] != hashed:
                raise ValueError("review_key already exists with different content")
            return {"review_id": old["id"], "duplicate": True, **store.status(db)}
        token, planned = snapshot(db, value["up_to"], value["include_archived"])
        if value["token"] != token:
            raise ValueError("stale review token; generate a new review-plan")
        rows = {r["id"]: r for r in planned}
        if decisions.keys() != rows.keys():
            raise ValueError("decisions must cover every planned experience exactly once")
        for key, item in decisions.items():
            row = rows[key]
            if item["action"] == "keep" and row["status"] != "active":
                if "revalidation" not in item:
                    raise ValueError("restoring a non-active experience requires passing revalidation")
            if item["action"] == "merge":
                target = item["merge_into"]
                if target == key or target not in rows or decisions[target]["action"] != "keep":
                    raise ValueError("merge target must be another planned experience kept in this review")
                source_case = json.loads(row["payload"])
                target_case = json.loads(rows[target]["payload"])
                if any(source_case[k] != target_case[k] for k in ("project", "scope", "environment")):
                    raise ValueError("merge requires matching project, scope, and environment")
        for key, item in decisions.items():
            new_status = "active" if item["action"] == "keep" else "archived"
            db.execute("UPDATE experiences SET status=?,merged_into=?,revision=revision+1 WHERE id=?",
                       (new_status, item.get("merge_into"), key))
        cursor = db.execute("""INSERT INTO reviews
            (review_key,up_to,payload,payload_hash,created_at) VALUES (?,?,?,?,?)""",
            (value["review_key"], value["up_to"], v.canonical(value), hashed, v.now()))
        db.execute("UPDATE meta SET value=? WHERE key='review_watermark'", (value["up_to"],))
        return {"review_id": cursor.lastrowid, "duplicate": False, **store.status(db)}
