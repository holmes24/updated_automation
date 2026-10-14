import unittest
from datetime import timezone
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.db.mongodb import (
    Coordinator,
    CoordinatorRegistrationRequest,
    EmployeeRegistrationRequest,
    RosterEntry,
    _phone_number_is_registered,
    has_submission_today,
)
from app.main import get_attendance
from app.services.geofence import check_geofence


class GeofenceRadiusTests(unittest.TestCase):
    def test_person_specific_radius_controls_geofence(self):
        within_distance = check_geofence(0.01, 0, 0, 0, radius_meters=1200)
        outside_distance = check_geofence(0.01, 0, 0, 0, radius_meters=1000)
        default_radius = check_geofence(0.01, 0, 0, 0)

        self.assertTrue(within_distance[0])
        self.assertAlmostEqual(within_distance[1], 1112, delta=2)
        self.assertFalse(outside_distance[0])
        self.assertTrue(default_radius[0])

    def test_existing_and_new_people_default_to_five_kilometers(self):
        self.assertEqual(Coordinator(pc_id="PC001", name="Coordinator").geofence_radius_km, 5)
        self.assertEqual(
            RosterEntry(phone_number="911234567890", employee_id="FS001", name="Supervisor")
            .geofence_radius_km,
            5,
        )
        self.assertEqual(
            CoordinatorRegistrationRequest(name="Coordinator").geofence_radius_km, 5
        )
        self.assertEqual(
            EmployeeRegistrationRequest(
                phone_number="911234567890", name="Supervisor"
            ).geofence_radius_km,
            5,
        )

    def test_radius_must_be_positive(self):
        with self.assertRaises(ValidationError):
            CoordinatorRegistrationRequest(name="Coordinator", geofence_radius_km=0)
        with self.assertRaises(ValidationError):
            EmployeeRegistrationRequest(
                phone_number="911234567890",
                name="Supervisor",
                geofence_radius_km=-1,
            )


class SubmissionDuplicateQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_absence_is_excluded_for_late_attendance(self):
        database = _FakeDatabase()
        with patch("app.db.mongodb.get_db", return_value=database):
            exists = await has_submission_today(
                "PC001", "2026-10-14", include_system_absences=False
            )

        self.assertFalse(exists)
        self.assertEqual(
            database.submissions.query["$nor"],
            [{"entry_type": "system", "attendance_status": "absent"}],
        )

    async def test_system_absence_is_included_for_absence_finalization(self):
        database = _FakeDatabase()
        with patch("app.db.mongodb.get_db", return_value=database):
            await has_submission_today("PC001", "2026-10-14")

        self.assertNotIn("$nor", database.submissions.query)


class PhoneUniquenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_phone_conflicts_are_checked_across_people_and_roles(self):
        database = _FakeDatabase()
        database.roster.result = {"employee_id": "EMP003"}
        with patch("app.db.mongodb.get_db", return_value=database):
            roster_conflict = await _phone_number_is_registered(
                "1234567890", exclude_pc_id="PC001"
            )

        self.assertTrue(roster_conflict)
        self.assertIn("911234567890", database.roster.query["phone_number"]["$in"])

        database = _FakeDatabase()
        database.coordinators.result = {"pc_id": "PC002"}
        with patch("app.db.mongodb.get_db", return_value=database):
            coordinator_conflict = await _phone_number_is_registered(
                "1234567890", exclude_employee_id="EMP003", exclude_pc_id="PC001"
            )

        self.assertTrue(coordinator_conflict)
        self.assertEqual(database.roster.query["employee_id"], {"$ne": "EMP003"})
        self.assertEqual(database.coordinators.query["pc_id"], {"$ne": "PC001"})


class AttendanceListTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_absence_is_not_displayed_as_a_flagged_checkin(self):
        system_absence = {
            "employee_id": "PC001",
            "entry_type": "system",
            "attendance_status": "absent",
            "verdict": "verified",
            "review_status": "n/a",
            "issues": [],
        }
        manual_entry = {
            "employee_id": "PC002",
            "entry_type": "manual",
            "attendance_status": "present",
            "verdict": "verified",
            "review_status": "n/a",
            "issues": [],
        }
        with patch(
            "app.main.list_attendance",
            new=AsyncMock(return_value=([system_absence, manual_entry], 2)),
        ), patch("app.main.ZoneInfo", return_value=timezone.utc):
            response = await get_attendance(admin=None)

        self.assertEqual(response["records"][0]["attendance_code"], "A")
        self.assertEqual(
            response["records"][0]["review_display"],
            "System absent (no image received)",
        )
        self.assertEqual(response["records"][1]["attendance_code"], "M")

    async def test_geofence_display_includes_the_person_specific_kilometer_limit(self):
        submission = {
            "employee_id": "FS001",
            "entry_type": "whatsapp",
            "attendance_status": "pending",
            "verdict": "flagged",
            "review_status": "pending",
            "issues": ["geofence_fail_1116m"],
            "geofence_passed": False,
            "geofence_distance_m": 1116,
            "geofence_radius_meters": 1000,
        }
        with patch(
            "app.main.list_attendance",
            new=AsyncMock(return_value=([submission], 1)),
        ), patch("app.main.ZoneInfo", return_value=timezone.utc):
            response = await get_attendance(admin=None)

        self.assertEqual(
            response["records"][0]["geofence_display"],
            "Outside range (1.12 km; limit 1 km)",
        )


class _FakeDatabase:
    def __init__(self):
        self.submissions = _FakeCollection()
        self.attendance_overrides = _FakeCollection()
        self.roster = _FakeCollection()
        self.coordinators = _FakeCollection()


class _FakeCollection:
    def __init__(self, result=None):
        self.query = None
        self.result = result

    async def find_one(self, query, projection=None):
        self.query = query
        return self.result


if __name__ == "__main__":
    unittest.main()
