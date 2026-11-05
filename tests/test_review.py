from support import DatabaseTest, decisions, example, feedback, review, store


class ReviewTests(DatabaseTest):
    def test_full_review_archives_without_losing_counter_or_history(self):
        self.add_many(20)
        value = decisions(review.plan(self.db))
        for item in value["decisions"][:5]:
            item["action"] = "archive"
        result = review.apply(self.db, value)
        self.assertEqual(result["counts"], {"active": 15, "needs_review": 0, "archived": 5})
        self.assertEqual(result["new_since_review"], 0)
        self.assertEqual(len(store.show(self.db, 1)["reviews"]), 1)
        self.add_many(20, 21)
        self.assertTrue(store.status(self.db)["review_due"])
        self.assertEqual(store.status(self.db)["new_since_review"], 20)

    def test_new_arrivals_not_swallowed_by_older_review(self):
        self.add_many(20)
        value = decisions(review.plan(self.db))
        self.add_many(20, 21)
        result = review.apply(self.db, value)
        self.assertTrue(result["review_due"])
        self.assertEqual(result["reviewed_through"], 20)
        self.assertEqual(result["new_since_review"], 20)

    def test_outcome_makes_snapshot_stale(self):
        store.add(self.db, example())
        value = decisions(review.plan(self.db))
        store.record_outcome(self.db, feedback())
        with self.assertRaisesRegex(ValueError, "stale"):
            review.apply(self.db, value)
        self.assertEqual(store.status(self.db)["reviewed_through"], 0)
        self.assertEqual(store.show(self.db, 1)["status"], "needs_review")

    def test_retries_idempotent_other_old_review_rejected(self):
        store.add(self.db, example())
        value = decisions(review.plan(self.db))
        review.apply(self.db, value)
        self.assertTrue(review.apply(self.db, value)["duplicate"])
        value["review_key"] = "review/other"
        with self.assertRaises(ValueError):
            review.apply(self.db, value)

    def test_partial_and_duplicate_decisions_rejected(self):
        self.add_many(2)
        for mode in ("missing", "duplicate"):
            value = decisions(review.plan(self.db))
            if mode == "missing":
                value["decisions"].pop()
            else:
                value["decisions"].append(value["decisions"][0])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                review.apply(self.db, value)
        self.assertEqual(store.status(self.db)["reviewed_through"], 0)

    def test_nonactive_keep_requires_revalidation_and_rolls_back_all(self):
        self.add_many(2)
        store.record_outcome(self.db, feedback(2))
        value = decisions(review.plan(self.db))
        value["decisions"][0]["action"] = "archive"
        with self.assertRaises(ValueError):
            review.apply(self.db, value)
        self.assertEqual(store.show(self.db, 1)["status"], "active")
        value["decisions"][1]["revalidation"] = example()["verification"]
        review.apply(self.db, value)
        self.assertEqual(store.show(self.db, 2)["status"], "active")

    def test_merge_keeps_source_evidence_and_rejects_cycles(self):
        self.add_many(2)
        value = decisions(review.plan(self.db))
        value["decisions"][0].update(action="merge", merge_into=2)
        value["decisions"][1].update(action="merge", merge_into=1)
        with self.assertRaises(ValueError):
            review.apply(self.db, value)
        value["decisions"][1]["action"] = "keep"
        del value["decisions"][1]["merge_into"]
        review.apply(self.db, value)
        source = store.show(self.db, 1)
        self.assertEqual(source["merged_into"], 2)
        self.assertEqual(source["case"], example())
        self.assertEqual(source["status"], "archived")

    def test_merge_across_environments_rejected(self):
        store.add(self.db, example())
        store.add(self.db, example(2, environment={"python": "3.10"}))
        value = decisions(review.plan(self.db))
        value["decisions"][0].update(action="merge", merge_into=2)
        with self.assertRaises(ValueError):
            review.apply(self.db, value)

    def test_restore_archive_with_explicit_plan_and_new_proof(self):
        store.add(self.db, example())
        value = decisions(review.plan(self.db))
        value["decisions"][0]["action"] = "archive"
        review.apply(self.db, value)
        self.assertEqual(review.plan(self.db)["entries"], [])
        restore = decisions(review.plan(self.db, True), "review/restore")
        restore["decisions"][0]["revalidation"] = example()["verification"]
        review.apply(self.db, restore)
        self.assertEqual(store.show(self.db, 1)["status"], "active")
        self.assertEqual(len(store.show(self.db, 1)["reviews"]), 2)

    def test_archive_failure_does_not_reactivate_it(self):
        store.add(self.db, example())
        value = decisions(review.plan(self.db))
        value["decisions"][0]["action"] = "archive"
        review.apply(self.db, value)
        store.record_outcome(self.db, feedback())
        self.assertEqual(store.show(self.db, 1)["status"], "archived")
