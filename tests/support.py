import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("SKILL_TEST_PATH", ROOT / "skills" / "yingluo-skill"))
sys.path.insert(0, str(SKILL / "scripts"))
import review
import store


def example(index=1, **changes):
    value = json.loads((ROOT / "examples" / "case.json").read_text(encoding="utf-8"))
    value["case_key"] = f"test/{index}"
    value.update(changes)
    return value


def feedback(experience_id=1, result="failure", event_key="event/1"):
    value = {"event_key": event_key, "experience_id": experience_id,
             "result": result, "notes": "Synthetic test feedback"}
    if result != "inapplicable":
        value["verification"] = example()["verification"]
        value["verification"]["result"] = "pass" if result == "success" else "fail"
    return value


def decisions(plan, key="review/1"):
    return {"review_key": key, "up_to": plan["up_to"], "token": plan["token"],
            "include_archived": plan["include_archived"],
            "decisions": [{"experience_id": row["id"], "action": "keep",
                "reason": "Synthetic evidence checked", "evidence_refs": ["synthetic://test"]}
                for row in plan["entries"]]}


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "memory.sqlite3"
        self.connection = store.connect(self.path, initialize=True)
        self.db = self.connection.__enter__()

    def tearDown(self):
        self.connection.__exit__(None, None, None)
        self.temp.cleanup()

    def add_many(self, count, start=1):
        for i in range(start, start + count):
            store.add(self.db, example(i))
