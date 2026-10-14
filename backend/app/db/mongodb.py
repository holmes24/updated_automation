"""
MongoDB connection (async, via Motor) and roster lookup.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from app.config import settings

logger = logging.getLogger("db")

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_url, tls=settings.mongodb_tls)
    return _client


def get_db():
    return get_client()[settings.mongodb_db_name]


def normalize_date_str(val: str | None) -> str:
    """Normalizes any date string (ISO YYYY-MM-DD, DD/MM/YYYY, or DD-MM-YYYY) to YYYY-MM-DD."""
    if not val:
        return ""
    val = str(val).strip()

    if re.match(r"^\d{4}-\d{2}-\d{2}", val):
        return val[:10]

    match = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})", val)
    if match:
        d, m, y = match.groups()
        return f"{y}-{m}-{d}"

    return val[:10]


class AssignedSite(BaseModel):
    name: str
    lat: float = Field(ge=-90, le=90)
    long: float = Field(ge=-180, le=180)


class Coordinator(BaseModel):
    pc_id: str
    name: str
    phone_number: str | None = None
    is_active: bool = True
    deactivated_at: str | None = None


class CoordinatorRegistrationRequest(BaseModel):
    name: str
    phone_number: str | None = None


class CoordinatorUpdateRequest(BaseModel):
    name: str | None = None
    phone_number: str | None = None
    is_active: bool | None = None


class RosterEntry(BaseModel):
    phone_number: str
    employee_id: str
    name: str
    is_active: bool = True
    deactivated_at: str | None = None
    pc_id: str | None = None
    area: str | None = None
    designation: str | None = None
    assigned_site: AssignedSite | None = None
    shift_start: str | None = None
    shift_end: str | None = None
    shift_grace_minutes: int | None = None


class EmployeeRegistrationRequest(BaseModel):
    phone_number: str
    name: str
    pc_id: str | None = None
    area: str | None = None
    designation: str | None = None
    assigned_site: AssignedSite | None = None
    shift_start: str | None = None
    shift_end: str | None = None
    shift_grace_minutes: int | None = None


class EmployeeUpdateRequest(BaseModel):
    phone_number: Optional[str] = None
    pc_id: Optional[str] = None
    area: Optional[str] = None
    designation: Optional[str] = None
    assigned_site: Optional[AssignedSite] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    shift_grace_minutes: Optional[int] = None
    is_active: Optional[bool] = None


def normalize_phone(value: str | None) -> str:
    """Canonical Indian phone number for WhatsApp/roster matching."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 10:
        return "91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits


async def lookup_roster(phone_number: str) -> RosterEntry | None:
    db = get_db()
    normalized = normalize_phone(phone_number)
    doc = await db.roster.find_one({"phone_number": normalized})
    if doc is None:
        # Backward compatibility with previously stored +91 / local numbers.
        variants = [normalized, "+" + normalized]
        if normalized.startswith("91") and len(normalized) == 12:
            variants.extend([normalized[2:], "0" + normalized[2:]])
        doc = await db.roster.find_one({"phone_number": {"$in": variants}})
    if doc is None:
        logger.warning("No roster entry found for phone number: %s", normalized)
        return None
    return RosterEntry(**doc)


async def get_roster_by_employee_id(employee_id: str) -> RosterEntry | None:
    db = get_db()
    doc = await db.roster.find_one({"employee_id": employee_id})
    if doc is None:
        return None
    return RosterEntry(**doc)


async def ensure_indexes() -> None:
    db = get_db()
    await db.roster.create_index("phone_number", unique=True)
    await db.roster.create_index("employee_id", unique=True)
    await db.roster.create_index("pc_id")
    await db.coordinators.create_index("pc_id", unique=True)
    await db.submissions.create_index("employee_id")
    await db.submissions.create_index("attendance_date")
    await db.submissions.create_index([("employee_id", 1), ("attendance_date", 1)])
    await db.submissions.create_index("image_hash")
    await db.face_embeddings.create_index("employee_id", unique=True)
    await db.admin_users.create_index("username", unique=True)
    await db.webhook_events.create_index("event_id", unique=True)
    await db.submissions.create_index("event_id", unique=True, sparse=True)
    await db.notifications.create_index("notification_id", unique=True)
    await db.notifications.create_index("status")


async def get_next_pc_id() -> str:
    db = get_db()
    result = await db.counters.find_one_and_update(
        {"_id": "pc_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"PC{result['seq']:03d}"


async def register_coordinator(request: CoordinatorRegistrationRequest) -> Coordinator:
    db = get_db()
    pc_id = await get_next_pc_id()
    doc = {
        "pc_id": pc_id,
        "name": request.name,
        "phone_number": request.phone_number,
        "is_active": True,
    }
    await db.coordinators.insert_one(doc)
    return Coordinator(**doc)


async def get_coordinator_by_id(pc_id: str) -> Coordinator | None:
    db = get_db()
    doc = await db.coordinators.find_one({"pc_id": pc_id})
    if doc is None:
        return None
    return Coordinator(**doc)


async def list_coordinators(
    pc_id: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Coordinator], int]:
    query = {}
    if pc_id is not None:
        query["pc_id"] = pc_id
    if is_active is not None:
        query["is_active"] = is_active
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone_number": {"$regex": search, "$options": "i"}},
        ]
    db = get_db()
    total = await db.coordinators.count_documents(query)
    skip = (page - 1) * page_size
    entries = []
    async for doc in db.coordinators.find(query).skip(skip).limit(page_size):
        entries.append(Coordinator(**doc))
    return entries, total


async def update_coordinator(
    pc_id: str, updates: CoordinatorUpdateRequest
) -> Coordinator | None:
    db = get_db()
    set_fields = updates.model_dump(exclude_unset=True)

    if "is_active" in set_fields:
        current = await get_coordinator_by_id(pc_id)
        if current is not None and current.is_active != set_fields["is_active"]:
            if set_fields["is_active"] is False:
                set_fields["deactivated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            else:
                set_fields["deactivated_at"] = None

    if not set_fields:
        return await get_coordinator_by_id(pc_id)
    doc = await db.coordinators.find_one_and_update(
        {"pc_id": pc_id},
        {"$set": set_fields},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        return None
    return Coordinator(**doc)


async def delete_coordinator_if_unassigned(pc_id: str) -> int | None:
    """Delete a coordinator only when no roster entries reference it.

    Returns the number of linked supervisors, or None if the coordinator
    does not exist.
    """
    db = get_db()
    linked_supervisors = await db.roster.count_documents({"pc_id": pc_id})
    if linked_supervisors:
        return linked_supervisors

    result = await db.coordinators.delete_one({"pc_id": pc_id})
    return 0 if result.deleted_count == 1 else None


async def get_next_employee_id() -> str:
    db = get_db()
    result = await db.counters.find_one_and_update(
        {"_id": "employee_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    seq = result["seq"]
    return f"EMP{seq:03d}"


async def register_employee(request: EmployeeRegistrationRequest) -> RosterEntry:
    if request.pc_id is not None:
        if await get_coordinator_by_id(request.pc_id) is None:
            raise ValueError(f"pc_id {request.pc_id} does not match any registered coordinator")

    db = get_db()
    employee_id = await get_next_employee_id()
    doc = {
        "employee_id": employee_id,
        "phone_number": request.phone_number,
        "name": request.name,
        "is_active": True,
        "pc_id": request.pc_id,
        "area": request.area,
        "designation": request.designation,
        "assigned_site": request.assigned_site.model_dump() if request.assigned_site else None,
        "shift_start": request.shift_start,
        "shift_end": request.shift_end,
        "shift_grace_minutes": request.shift_grace_minutes,
    }
    try:
        await db.roster.insert_one(doc)
    except Exception as exc:
        if "duplicate key" in str(exc).lower():
            raise ValueError(f"phone_number {request.phone_number} is already registered")
        raise
    return RosterEntry(**doc)


async def update_employee_details(
    employee_id: str, updates: EmployeeUpdateRequest
) -> Optional[RosterEntry]:
    if updates.pc_id is not None:
        if await get_coordinator_by_id(updates.pc_id) is None:
            raise ValueError(f"pc_id {updates.pc_id} does not match any registered coordinator")

    db = get_db()
    set_fields = {
        k: (v.model_dump() if isinstance(v, AssignedSite) else v)
        for k, v in updates.model_dump(exclude_unset=True).items()
    }

    if "is_active" in set_fields:
        current = await get_roster_by_employee_id(employee_id)
        if current is not None and current.is_active != set_fields["is_active"]:
            if set_fields["is_active"] is False:
                set_fields["deactivated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            else:
                set_fields["deactivated_at"] = None

    if not set_fields:
        return await get_roster_by_employee_id(employee_id)

    try:
        doc = await db.roster.find_one_and_update(
            {"employee_id": employee_id},
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER,
        )
    except Exception as exc:
        if "duplicate key" in str(exc).lower():
            raise ValueError(
                f"phone_number {set_fields.get('phone_number')} is already registered to a different employee"
            )
        raise
    if doc is None:
        return None
    return RosterEntry(**doc)


async def delete_employee_without_attendance(employee_id: str) -> int | None:
    """Delete a supervisor only when no attendance submissions reference them.

    Returns the number of attendance records, or None if the supervisor does
    not exist.
    """
    db = get_db()
    if await db.roster.find_one({"employee_id": employee_id}, {"_id": 1}) is None:
        return None

    attendance_count = await db.submissions.count_documents({"employee_id": employee_id})
    if attendance_count:
        return attendance_count

    result = await db.roster.delete_one({"employee_id": employee_id})
    if result.deleted_count != 1:
        return None

    await db.face_embeddings.delete_one({"employee_id": employee_id})
    return 0


async def save_enrollment(employee_id: str, embeddings: list[list[float]]) -> None:
    db = get_db()
    await db.face_embeddings.update_one(
        {"employee_id": employee_id},
        {"$set": {"employee_id": employee_id, "embeddings": embeddings}},
        upsert=True,
    )


async def get_enrollment(employee_id: str) -> list[list[float]]:
    db = get_db()
    doc = await db.face_embeddings.find_one({"employee_id": employee_id})
    if doc is None:
        return []
    return doc.get("embeddings", [])


async def list_employees_by_pc(pc_id: str) -> list[RosterEntry]:
    db = get_db()
    entries = []
    async for doc in db.roster.find({"pc_id": pc_id}):
        entries.append(RosterEntry(**doc))
    return entries


async def list_employees(
    pc_id: str | None = None,
    area: str | None = None,
    designation: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[RosterEntry], int]:
    query = {}
    if pc_id is not None:
        query["pc_id"] = pc_id
    if area is not None:
        query["area"] = area
    if designation is not None:
        query["designation"] = designation
    if is_active is not None:
        query["is_active"] = is_active
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone_number": {"$regex": search, "$options": "i"}},
        ]

    db = get_db()
    total = await db.roster.count_documents(query)
    skip = (page - 1) * page_size
    entries = []
    async for doc in db.roster.find(query).skip(skip).limit(page_size):
        entries.append(RosterEntry(**doc))
    return entries, total


async def get_admin_last_seen():
    db = get_db()
    doc = await db.admin_state.find_one({"_id": "admin"})
    if doc is None:
        return None
    return doc.get("last_message_utc")


async def list_attendance(
    employee_id: str | None = None,
    pc_id: str | None = None,
    verdict: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    db = get_db()
    query: dict = {}

    if employee_id is not None:
        query["employee_id"] = employee_id
    if verdict is not None:
        query["verdict"] = verdict

    if date_from is not None or date_to is not None:
        date_conditions = []
        if date_from is not None:
            norm_from = normalize_date_str(date_from)
            date_conditions.append({
                "$or": [
                    {"attendance_date": {"$gte": norm_from}},
                    {"received_at_utc": {"$gte": norm_from}},
                ]
            })
        if date_to is not None:
            norm_to = normalize_date_str(date_to)
            date_conditions.append({
                "$or": [
                    {"attendance_date": {"$lte": norm_to}},
                    {"received_at_utc": {"$lte": norm_to + "T23:59:59.999999"}},
                ]
            })
        if len(date_conditions) == 1:
            query.update(date_conditions[0])
        elif len(date_conditions) > 1:
            query["$and"] = date_conditions

    if pc_id is not None:
        employee_ids = [e.employee_id for e in await list_employees_by_pc(pc_id)]
        query["employee_id"] = {"$in": employee_ids}

    if search:
        matching, _ = await list_employees(search=search, page=1, page_size=10_000)
        matched_ids = [e.employee_id for e in matching]
        if "employee_id" in query and isinstance(query["employee_id"], dict):
            existing_ids = set(query["employee_id"]["$in"])
            query["employee_id"] = {"$in": list(existing_ids & set(matched_ids))}
        else:
            query["employee_id"] = {"$in": matched_ids}

    total = await db.submissions.count_documents(query)
    skip = (page - 1) * page_size
    results = []
    async for doc in (
        db.submissions.find(query)
        .sort([("received_at_utc", -1), ("_id", -1)])
        .skip(skip)
        .limit(page_size)
    ):
        doc["_id"] = str(doc["_id"])
        if not doc.get("attendance_date"):
            doc["attendance_date"] = normalize_date_str(doc.get("received_at_utc"))
        results.append(doc)
    return results, total


async def delete_attendance_submission(submission_id: str) -> bool:
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        object_id = ObjectId(submission_id)
    except InvalidId:
        return False

    result = await get_db().submissions.delete_one({"_id": object_id})
    return result.deleted_count == 1


async def has_submission_today(employee_id: str, date_str: str) -> bool:
    """Checks whether this employee already has ANY submission for the date."""
    norm_date = normalize_date_str(date_str)
    parts = norm_date.split("-")
    alt_date = f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else norm_date

    db = get_db()
    existing = await db.submissions.find_one(
        {
            "employee_id": employee_id,
            "$or": [
                {"attendance_date": norm_date},
                {"received_at_utc": {"$regex": f"^{norm_date}"}},
                {"received_at_utc": {"$regex": f"^{alt_date}"}},
            ],
        }
    )
    return existing is not None


async def resolve_flagged_submission(
    submission_id: str, decision: str, resolved_by: str, reason: str | None = None
):
    from bson import ObjectId

    if decision not in ("approved", "rejected"):
        raise ValueError('decision must be "approved" or "rejected"')

    db = get_db()
    try:
        obj_id = ObjectId(submission_id)
    except Exception:
        return None

    doc = await db.submissions.find_one({"_id": obj_id})
    if doc is None or doc.get("verdict") != "flagged":
        return None

    attendance_status = "present" if decision == "approved" else "absent"

    await db.submissions.update_one(
        {"_id": obj_id},
        {
            "$set": {
                "review_status": decision,
                "attendance_status": attendance_status,
                "resolved_by": resolved_by,
                "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
                "resolution_reason": reason,
            }
        },
    )
    updated = await db.submissions.find_one({"_id": obj_id})
    updated["_id"] = str(updated["_id"])
    return updated


async def get_submissions_grouped(
    employee_ids: list[str],
    date_from: str,
    date_to: str,
) -> dict[str, dict[str, dict]]:
    """Selects one daily attendance outcome per employee for the Excel grid."""
    db = get_db()
    result: dict[str, dict[str, dict]] = {emp_id: {} for emp_id in employee_ids}

    if not employee_ids:
        return result

    norm_from = normalize_date_str(date_from)
    norm_to = normalize_date_str(date_to)

    cursor = db.submissions.find({"employee_id": {"$in": employee_ids}})

    def rank(sub: dict) -> tuple[int, str, str]:
        verdict = sub.get("verdict")
        review = sub.get("review_status")
        entry_type = sub.get("entry_type")
        shift = sub.get("shift_status")
        timestamp = str(sub.get("received_at_utc") or "")
        record_id = str(sub.get("_id") or "")

        if entry_type == "manual":
            priority = 6
        elif verdict == "verified":
            priority = 5
        elif verdict == "flagged" and review == "approved":
            priority = 4
        elif verdict == "flagged" and review == "rejected":
            priority = 3
        elif verdict == "inactive_account":
            priority = 2
        elif verdict == "flagged":
            priority = 1
        else:
            priority = 0

        on_time_pref = 1 if shift != "late" else 0
        return (priority * 10 + on_time_pref, timestamp, record_id)

    async for doc in cursor:
        emp_id = doc.get("employee_id")
        if emp_id not in result:
            continue

        raw_date = doc.get("attendance_date") or doc.get("received_at_utc")
        day = normalize_date_str(raw_date)

        if not (norm_from <= day <= norm_to):
            continue

        current = result[emp_id].get(day)
        if current is None or rank(doc) > rank(current):
            result[emp_id][day] = doc

    return result


async def create_manual_attendance(
    employee_id: str, date: str, reason: str, created_by: str
) -> dict:
    roster_entry = await get_roster_by_employee_id(employee_id)
    if roster_entry is None:
        raise ValueError(f"No employee found with employee_id: {employee_id}")

    norm_date = normalize_date_str(date)
    if await has_submission_today(employee_id, norm_date):
        raise ValueError(
            f"A submission already exists for {employee_id} on {norm_date} — "
            f"use PATCH /attendance/{{id}}/resolve on the existing record instead"
        )

    db = get_db()
    doc = {
        "employee_id": employee_id,
        "sender_phone": roster_entry.phone_number,
        "caption": None,
        "media_url": None,
        "image_hash": None,
        "overlay": None,
        "geofence_passed": None,
        "geofence_distance_m": None,
        "face_present": None,
        "face_count": None,
        "identity_verdict": None,
        "identity_score": None,
        "shift_status": "on_time",
        "attendance_date": norm_date,
        "attendance_status": "present",
        "verdict": "verified",
        "review_status": "n/a",
        "issues": [],
        "entry_type": "manual",
        "created_by": created_by,
        "reason": reason,
        "received_at_utc": f"{norm_date}T00:00:00Z",
    }
    result = await db.submissions.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


async def update_admin_last_seen(timestamp) -> None:
    db = get_db()
    await db.admin_state.update_one(
        {"_id": "admin"},
        {"$set": {"last_message_utc": timestamp}},
        upsert=True,
    )


async def register_webhook_event(event_id: str, payload: dict) -> bool:
    db = get_db()
    try:
        await db.webhook_events.insert_one({
            "event_id": event_id,
            "status": "received",
            "payload": payload,
        })
        return True
    except Exception as exc:
        if "duplicate key" in str(exc).lower():
            return False
        raise


async def claim_webhook_event(event_id: str) -> bool:
    db = get_db()
    doc = await db.webhook_events.find_one_and_update(
        {"event_id": event_id, "status": {"$in": ["received", "queued", "failed"]}},
        {"$set": {"status": "processing", "processing_started_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    return doc is not None


async def mark_webhook_queued(event_id: str) -> None:
    db = get_db()
    await db.webhook_events.update_one(
        {"event_id": event_id, "status": {"$in": ["received", "failed"]}},
        {"$set": {"status": "queued", "queued_at": datetime.now(timezone.utc)}}
    )


async def complete_webhook_event(event_id: str) -> None:
    db = get_db()
    await db.webhook_events.update_one(
        {"event_id": event_id},
        {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc)}}
    )


async def fail_webhook_event(event_id: str, error: str, dead_letter: bool = False) -> None:
    db = get_db()
    await db.webhook_events.update_one(
        {"event_id": event_id},
        {"$set": {"status": "dead_letter" if dead_letter else "failed", "last_error": error[:2000], "last_failed_at": datetime.now(timezone.utc)}}
    )


async def create_notification(notification: dict) -> bool:
    db = get_db()
    try:
        await db.notifications.insert_one(notification)
        return True
    except Exception as exc:
        if "duplicate key" in str(exc).lower():
            return False
        raise


async def claim_notification(notification_id: str) -> bool:
    db = get_db()
    doc = await db.notifications.find_one_and_update(
        {"notification_id": notification_id, "status": {"$in": ["pending", "retry"]}},
        {"$set": {"status": "processing", "processing_started_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )
    return doc is not None


async def mark_notification_sent(notification_id: str) -> None:
    db = get_db()
    await db.notifications.update_one(
        {"notification_id": notification_id},
        {"$set": {"status": "sent", "sent_at": datetime.now(timezone.utc)}}
    )


async def mark_notification_retry(notification_id: str, error: str) -> None:
    db = get_db()
    await db.notifications.update_one(
        {"notification_id": notification_id},
        {"$set": {"status": "retry", "last_error": error[:2000], "last_failed_at": datetime.now(timezone.utc)}}
    )


class AdminUser(BaseModel):
    username: str
    password_hash: str
    is_active: bool = True
    role: str = "super_admin"
    pc_id: str | None = None


async def get_admin_user(username: str) -> AdminUser | None:
    db = get_db()
    doc = await db.admin_users.find_one({"username": username})
    if doc is None:
        return None
    return AdminUser(**doc)


async def create_admin_user(
    username: str,
    password_hash: str,
    role: str = "super_admin",
    pc_id: str | None = None,
) -> AdminUser:
    db = get_db()
    doc = {
        "username": username,
        "password_hash": password_hash,
        "is_active": True,
        "role": role,
        "pc_id": pc_id,
    }
    try:
        await db.admin_users.insert_one(doc)
    except Exception as exc:
        if "duplicate key" in str(exc).lower():
            raise ValueError(f"username {username} is already taken")
        raise
    return AdminUser(**doc)
