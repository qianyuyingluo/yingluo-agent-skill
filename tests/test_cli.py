import json
import os
import subprocess
import sys

from support import DatabaseTest, ROOT, SKILL, decisions, example


class CliTests(DatabaseTest):
    def call(self, *args, data=None, include_db=True):
        command = [sys.executable, str(SKILL / "scripts" / "memory.py")]
        if include_db:
            command += ["--db", str(self.path)]
        env = os.environ.copy()
        env.pop("YINGLUO_MEMORY_DB", None)
        return subprocess.run(command + list(args), input=data, capture_output=True,
                              text=True, encoding="utf-8", env=env, cwd=ROOT)

    def test_cli_end_to_end_including_review_and_persistence(self):
        result = self.call("add", "--file", "-", data=json.dumps(example(), ensure_ascii=False))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["id"], 1)
        found = self.call("search", "--query", "导入失败", "--project", "synthetic-demo")
        self.assertEqual(len(json.loads(found.stdout)["matches"]), 1)
        plan = json.loads(self.call("review-plan").stdout)
        result = self.call("review", "--file", "-", data=json.dumps(decisions(plan)))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["reviewed_through"], 1)
        result = self.call("show", "--id", "1")
        self.assertEqual(len(json.loads(result.stdout)["reviews"]), 1)

    def test_bad_inputs_are_json_errors_without_traceback(self):
        for data in ("{", '{"case_key":"a","case_key":"b"}', '{"x":NaN}', "[]"):
            result = self.call("add", "--file", "-", data=data)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)["ok"])
            self.assertNotIn("Traceback", result.stderr)

    def test_missing_path_and_bad_arguments(self):
        for args, include_db in ((("status",), False), (("show",), True),
                                  (("search", "--query", "x", "--env", "broken"), True)):
            result = self.call(*args, include_db=include_db)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)["ok"])

    def test_init_is_idempotent_and_preserves_data(self):
        self.call("add", "--file", "-", data=json.dumps(example()))
        result = self.call("init")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["total_added"], 1)
