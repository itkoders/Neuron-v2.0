import sqlite3
import unittest
from contextlib import closing

from sms_bridge import (
    init_sms_bridge, make_pair_code, pair_device,
    enqueue_score_sms, claim_tasks, report_task
)


class SmsBridgeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = None

        def run(sql, params=(), fetch="none"):
            cur = self.db.execute(sql, params)
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            else:
                result = None
            self.db.commit()
            return result

        self.run = run
        init_sms_bridge(self.run)
        self.now = "2026-11-14T12:00:00"

    def tearDown(self):
        self.db.close()

    def test_pair_code_is_single_use(self):
        code = make_pair_code(self.run, 12, self.now)
        paired = pair_device(self.run, code, "Android test", "", self.now)
        self.assertIsNotNone(paired)
        self.assertEqual(paired["teacher_id"], 12)
        self.assertIsNone(pair_device(self.run, code, "Android test", "", self.now))

    def test_score_creates_one_sms_task(self):
        code = make_pair_code(self.run, 12, self.now)
        pair_device(self.run, code, "Android test", "", self.now)
        student = {"id": 31, "fio": "Ali Valiyev", "phone": "+998901234567"}
        subject = {"name": "Tarix"}
        self.assertTrue(enqueue_score_sms(self.run, 12, student, subject, "Test", 45, self.now))
        self.assertTrue(enqueue_score_sms(self.run, 12, student, subject, "Test", 45, self.now))
        tasks = claim_tasks(self.run, 12, self.now)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["phone"], "+998901234567")
        self.assertIn("JIDDIY OGOHLANTIRISH", tasks[0]["body"])
        self.assertTrue(report_task(self.run, 12, tasks[0]["id"], "sent", "", self.now))
        self.assertEqual(claim_tasks(self.run, 12, self.now), [])


if __name__ == "__main__":
    unittest.main()
