import unittest
from datetime import datetime

from attendance_utils import parse_check_in_at, should_skip_duplicate


class DummyLog:
    def __init__(self, check_in_at):
        self.check_in_at = check_in_at


class AttendanceUtilsTests(unittest.TestCase):
    def test_parse_check_in_at_handles_zulu_time(self):
        parsed = parse_check_in_at("2026-07-08T07:31:00Z")
        self.assertIsInstance(parsed, datetime)
        self.assertEqual(parsed, datetime(2026, 7, 8, 7, 31, 0))

    def test_parse_check_in_at_rejects_invalid_datetime(self):
        self.assertIsNone(parse_check_in_at("not-a-date"))

    def test_should_skip_duplicate_inside_window(self):
        last_log = DummyLog(datetime(2026, 7, 8, 10, 0, 0))
        incoming = datetime(2026, 7, 8, 10, 0, 40)
        self.assertTrue(should_skip_duplicate(last_log, incoming, dedup_seconds=60))

    def test_should_skip_duplicate_outside_window(self):
        last_log = DummyLog(datetime(2026, 7, 8, 10, 0, 0))
        incoming = datetime(2026, 7, 8, 10, 2, 0)
        self.assertFalse(should_skip_duplicate(last_log, incoming, dedup_seconds=60))


if __name__ == "__main__":
    unittest.main()
