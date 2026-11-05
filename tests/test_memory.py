import copy
from concurrent.futures import ThreadPoolExecutor

from support import DatabaseTest, example, feedback, store


class MemoryTests(DatabaseTest):
    def test_missing_or_failed_verification_cannot_enter(self):
        for mode in ("missing", "failed", "empty", "timestamp"):
            with self.subTest(mode=mode):
                value = example()
                if mode == "missing":
                    del value["verification"]
                elif mode == "failed":
                    value["verification"]["result"] = "fail"
                elif mode == "timestamp":
                    value["verification"]["verified_at"] = "2026-11-05T10:00:00"
                else:
                    value["solution"] = []
                with self.assertRaises(ValueError):
                    store.add(self.db, value)
        self.assertEqual(store.status(self.db)["total_added"], 0)

    def test_unknown_fields_and_wrong_types_rejected(self):
        for field, value in (("extra", "x"), ("environment", []), ("scope", True),
                             ("tags", "python"), ("cause_status", "guaranteed")):
            case = example()
            case[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                store.add(self.db, case)

    def test_idempotent_add_and_conflicting_key(self):
        first = store.add(self.db, example())
        second = store.add(self.db, example())
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        with self.assertRaises(ValueError):
            store.add(self.db, example(title="different"))
        self.assertEqual(store.status(self.db)["total_added"], 1)

    def test_twentieth_unique_add_triggers_review(self):
        self.add_many(19)
        self.assertFalse(store.add(self.db, example(19))["review_due"])
        self.assertTrue(store.add(self.db, example(20))["review_due"])
        self.assertTrue(store.status(self.db)["review_due"])

    def test_search_scope_tags_environment_and_chinese(self):
        store.add(self.db, example())
        store.add(self.db, example(2, project="other"))
        store.add(self.db, example(3, project="shared", scope="global"))
        self.assertEqual(len(store.search(self.db, "导入失败")), 1)
        rows = store.search(self.db, "导入失败", "synthetic-demo", ["python"], {"python": "3.11"})
        self.assertEqual({r["id"] for r in rows}, {1, 3})
        self.assertEqual(store.search(self.db, "导入失败", "synthetic-demo", environment={"python": "3.10"}), [])
        self.assertEqual(store.search(self.db, "导入失败", "synthetic-demo", tags=["missing"]), [])
        injected = store.search(self.db, "' OR 1=1 --", "synthetic-demo")
        self.assertTrue({r["id"] for r in injected}.issubset({1, 3}))
        store.search(self.db, "'; DROP TABLE experiences; --", "synthetic-demo")
        self.assertEqual(store.status(self.db)["total_added"], 3)

    def test_failure_quarantines_and_success_does_not_restore(self):
        store.add(self.db, example())
        result = store.record_outcome(self.db, feedback())
        self.assertTrue(result["review_due"])
        self.assertEqual(store.search(self.db, "Python", "synthetic-demo"), [])
        store.record_outcome(self.db, feedback(result="success", event_key="event/2"))
        row = store.show(self.db, 1)
        self.assertEqual(row["status"], "needs_review")
        self.assertEqual(row["usage"], {"failure": 1, "success": 1})

    def test_feedback_idempotent_and_inapplicable_not_failure(self):
        store.add(self.db, example())
        data = feedback(result="inapplicable")
        store.record_outcome(self.db, data)
        self.assertTrue(store.record_outcome(self.db, data)["duplicate"])
        row = store.show(self.db, 1)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["usage"], {"inapplicable": 1})
        self.assertEqual(row["revision"], 2)
        changed = copy.deepcopy(data)
        changed["notes"] = "changed"
        with self.assertRaises(ValueError):
            store.record_outcome(self.db, changed)

    def test_invalid_feedback_does_not_write(self):
        for data in (feedback(999), feedback(True), {**feedback(), "verification": None}):
            with self.assertRaises(ValueError):
                store.record_outcome(self.db, data)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 0)

    def test_data_survives_new_connection(self):
        store.add(self.db, example())
        with store.connect(self.path) as second:
            self.assertEqual(store.show(second, 1)["case"]["case_key"], "test/1")

    def test_concurrent_unique_and_duplicate_writes(self):
        def write(index):
            with store.connect(self.path) as db:
                return store.add(db, example(index))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, list(range(1, 21)) * 2))
        self.assertEqual(sum(not r["duplicate"] for r in results), 20)
        self.assertEqual(store.status(self.db)["total_added"], 20)

    def test_missing_db_is_not_silently_created(self):
        missing = self.path.parent / "wrong.sqlite3"
        with self.assertRaises(ValueError):
            with store.connect(missing):
                pass
        self.assertFalse(missing.exists())
