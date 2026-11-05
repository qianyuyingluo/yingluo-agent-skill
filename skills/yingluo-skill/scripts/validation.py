"""Validate reported observations; never execute commands from memory."""
import hashlib
import json
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, field, maximum=10000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field}: expected nonempty string, at most {maximum} characters")
    return value


def integer(value, field, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field}: expected integer >= {minimum}")
    return value


def choice(value, field, options):
    if not isinstance(value, str) or value not in options:
        raise ValueError(f"{field}: expected one of {', '.join(options)}")


def fields(value, required, optional=()):
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"invalid fields: missing={sorted(missing)}, unknown={sorted(extra)}")


def strings(value, field, minimum=1):
    if not isinstance(value, list) or not minimum <= len(value) <= 64:
        raise ValueError(f"{field}: expected list with {minimum}..64 strings")
    for item in value:
        text(item, field)


def evidence(value, expected_result):
    fields(value, ("method", "expected", "observed", "artifact_ref", "verified_at", "result"))
    for name in ("method", "expected", "observed", "artifact_ref"):
        text(value[name], f"evidence.{name}")
    if value["result"] != expected_result:
        raise ValueError(f"evidence.result must be {expected_result}")
    text(value["verified_at"], "evidence.verified_at", 80)
    try:
        moment = datetime.fromisoformat(value["verified_at"].replace("Z", "+00:00"))
        if moment.utcoffset() is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise ValueError("evidence.verified_at: use ISO 8601 with timezone") from exc


def case(value):
    fields(value, ("case_key", "title", "project", "scope", "environment", "tags",
                   "error", "cause", "cause_status", "failed_attempts", "solution",
                   "boundaries", "verification"))
    for name in ("case_key", "title", "project", "error", "cause"):
        text(value[name], name, 200 if name in ("case_key", "project", "title") else 10000)
    choice(value["scope"], "scope", ("project", "global"))
    choice(value["cause_status"], "cause_status", ("confirmed", "hypothesis"))
    if not isinstance(value["environment"], dict) or not 1 <= len(value["environment"]) <= 32:
        raise ValueError("environment: expected nonempty object with at most 32 entries")
    for key, item in value["environment"].items():
        text(key, "environment key", 100)
        text(item, "environment value", 1000)
    strings(value["tags"], "tags", 0)
    strings(value["failed_attempts"], "failed_attempts", 0)
    strings(value["solution"], "solution")
    strings(value["boundaries"], "boundaries")
    evidence(value["verification"], "pass")
    return value


def outcome(value):
    fields(value, ("event_key", "experience_id", "result", "notes"), ("verification",))
    text(value["event_key"], "event_key", 200)
    integer(value["experience_id"], "experience_id")
    choice(value["result"], "result", ("success", "failure", "inapplicable"))
    text(value["notes"], "notes")
    if value["result"] != "inapplicable":
        evidence(value.get("verification"), "pass" if value["result"] == "success" else "fail")
    elif "verification" in value:
        raise ValueError("inapplicable uses notes, not verification")
    return value
