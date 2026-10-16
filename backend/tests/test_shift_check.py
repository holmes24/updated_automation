import unittest
from datetime import datetime

from app.services.shift_check import NON_FAILURE_STATUSES, check_shift_window


class ShiftCheckTests(unittest.TestCase):
    def test_after_grace_is_classified_without_flagging_for_shift_alone(self):
        status, reason = check_shift_window(
            datetime.fromisoformat("2026-10-16T10:19:00+05:30"),
            employee_shift_start="09:00",
            employee_shift_end="18:00",
            employee_grace_minutes=60,
        )

        self.assertEqual(status, "after_grace")
        self.assertIn("AL", reason)
        self.assertIn(status, NON_FAILURE_STATUSES)


if __name__ == "__main__":
    unittest.main()
