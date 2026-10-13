"""
FastAPI entry point.

Webhook design constraints:
  - The public webhook performs validation and durable Redis enqueue only; AI processing never runs inline.
  - Payload structure verified against a real captured event
    (see app/schemas.py for field-level notes).
"""
import logging
import hmac
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth import create_access_token, get_current_admin, verify_api_key, verify_password
from app.config import settings
from app.db.mongodb import (
    AdminUser,
    CoordinatorRegistrationRequest,
    CoordinatorUpdateRequest,
    EmployeeRegistrationRequest,
    EmployeeUpdateRequest,
    ensure_indexes,
    get_admin_user,
    get_db,
    get_roster_by_employee_id,
    get_submissions_grouped,
    list_attendance,
    list_coordinators,
    list_employees,
    lookup_roster,
    register_coordinator,
    register_employee,
    resolve_flagged_submission,
    save_enrollment,
    update_admin_last_seen,
    update_coordinator,
    update_employee_details,
    create_manual_attendance,
    register_webhook_event,
    mark_webhook_queued,
)
from app.schemas import InteraktWebhookPayload
from app.security import verify_webhook_signature
from app.services.face_match import enroll_embeddings
from app.redis_queue import ATTENDANCE_STREAM, ensure_stream_group, enqueue, get_redis
from app.services.attendance_grid import compute_employee_grid, daterange
from app.services.attendance_export_xlsx import build_export_workbook
from app.services.alert_formatting import format_issue_list, flag_reason_from_issues
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="Attendance Verification Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str
    password: str


class ResolveRequest(BaseModel):
    decision: str  # "approved" or "rejected"
    reason: str | None = None


class ManualAttendanceRequest(BaseModel):
    employee_id: str
    date: str  # "YYYY-MM-DD"
    reason: str  # required — the whole point of this endpoint is an auditable justification


@app.on_event("startup")
async def on_startup():
    if settings.environment.lower() == "production":
        missing = []
        for name, value in {
            "JWT_SECRET_KEY": settings.jwt_secret_key,
            "APP_API_KEY": settings.app_api_key,
            "INTERAKT_WEBHOOK_SECRET": settings.interakt_webhook_secret,
            "INTERAKT_API_KEY": settings.interakt_api_key,
        }.items():
            if not value or value in {"replace_me", "replace_with_a_long_random_secret", "replace_with_a_long_random_api_key"}:
                missing.append(name)
        if not missing:
            if "*" in settings.cors_origins:
                missing.append("CORS_ORIGINS must not contain *")
        if missing:
            raise RuntimeError("Production security configuration invalid: " + ", ".join(missing))
    """
    Ensures MongoDB indexes exist before the app serves traffic — this is
    what makes duplicate phone_number rejection and unique employee_id
    actually enforced. Previously this only happened if someone manually
    ran scripts/test_db_connection.py first, which was a real gap (caught
    via testing — see conversation history for details).
    """
    await ensure_indexes()
    redis = get_redis()
    await ensure_stream_group(redis, ATTENDANCE_STREAM, "attendance-workers")
    await redis.close()
    logger.info("MongoDB indexes and Redis queue initialized")


@app.get("/health")
async def health():
    """Basic liveness endpoint; does not expose credentials or database details."""
    redis_ok = False
    try:
        redis = get_redis()
        redis_ok = bool(await redis.ping())
        await redis.close()
    except Exception:
        pass
    try:
        await get_db().command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
    status = "ok" if redis_ok and mongo_ok else "degraded"
    return {"status": status, "redis": redis_ok, "mongodb": mongo_ok}


@app.post("/webhook/interakt")
async def interakt_webhook(
    request: Request,
    interakt_signature: str = Header(default=None, alias="Interakt-Signature"),
):
    """Validate, deduplicate, and durably enqueue an Interakt webhook.

    The HTTP request does no AI work. Redis Streams provides the durable handoff
    to the unified worker, while MongoDB stores the idempotency record.
    """
    raw_body = await request.body()
    if not verify_webhook_signature(raw_body, interakt_signature or ""):
        import hashlib

        received_signature = interakt_signature or ""
        received_hex = (
            received_signature[len("sha256="):]
            if received_signature.startswith("sha256=")
            else ""
        )

        expected_hex = hmac.new(
            key=settings.interakt_webhook_secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        logger.warning(
            "Webhook HMAC mismatch | body_length=%d | received_length=%d | expected_length=%d | prefix_ok=%s",
            len(raw_body),
            len(received_hex),
            len(expected_hex),
            received_signature.startswith("sha256="),
        )

        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = InteraktWebhookPayload.model_validate_json(raw_body)
    except Exception as exc:
        logger.error("Failed to parse webhook payload: %s", exc)
        return {"status": "received", "parsed": False}

    if payload.type != "message_received":
        return {"status": "ignored"}

    event_id = payload.data.message.id
    inserted = await register_webhook_event(event_id, payload.model_dump(mode="json"))

    # Duplicate events are safe to enqueue again: the worker claims the Mongo
    # event atomically, so only one copy can execute the AI pipeline. Re-enqueue
    # is intentional because a prior delivery may have crashed after persistence.
    if not inserted:
        logger.info("Webhook event %s already exists; checking for unfinished work", event_id)

    sender_phone = payload.data.customer.phone_number
    if settings.admin_phone_number and sender_phone == settings.admin_phone_number:
        await update_admin_last_seen(datetime.now(timezone.utc))
        from app.db.mongodb import complete_webhook_event
        await complete_webhook_event(event_id)
        return {"status": "admin_checkin", "duplicate": not inserted}

    redis = get_redis()
    try:
        await enqueue(redis, ATTENDANCE_STREAM, {
            "event_id": event_id,
            "payload": payload.model_dump(mode="json"),
            "attempt": 0,
        })
    finally:
        await redis.close()

    await mark_webhook_queued(event_id)
    return {"status": "received", "queued": True, "duplicate": not inserted}


@app.post("/auth/login")
async def login(request: LoginRequest, _: None = Depends(verify_api_key)):
    """
    CMS login — returns a JWT access token (valid for
    settings.jwt_expire_minutes). Pass it as `Authorization: Bearer <token>`
    on protected endpoints. There is no public registration endpoint —
    admin accounts are created via scripts/create_admin.py.
    """
    admin = await get_admin_user(request.username)
    unauthorized = HTTPException(status_code=401, detail="Incorrect username or password")
    if admin is None or not admin.is_active:
        raise unauthorized
    if not verify_password(request.password, admin.password_hash):
        raise unauthorized
    token = create_access_token(admin.username)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/config")
async def get_config(admin: AdminUser = Depends(get_current_admin)):
    """
    Read-only — non-biometric thresholds currently enforced by the
    pipeline, so the frontend never hardcodes a value that could drift
    from what the backend actually checks.

    Deliberately EXCLUDES face-match confidence thresholds — per product
    decision, match confidence/percentage is never surfaced to the
    frontend anywhere. The actual thresholds still fully govern
    verification internally (see config.py, services/face_match.py) —
    this is purely about what the API exposes, not what's enforced.
    """
    return {
        "geofence_radius_meters": settings.geofence_radius_meters,
        "shift_window_start": settings.shift_window_start,
        "shift_window_end": settings.shift_window_end,
        "shift_grace_minutes": settings.shift_grace_minutes,
        "duplicate_hash_hamming_threshold": settings.duplicate_hash_hamming_threshold,
    }


@app.post("/coordinators")
async def create_coordinator(
    request: CoordinatorRegistrationRequest, admin: AdminUser = Depends(get_current_admin)
):
    """
    Register a new Project Coordinator. pc_id is auto-generated
    (PC001, PC002, ...). Field supervisors are linked to a PC via
    pc_id on their own roster record (set at registration or via PATCH).
    """
    coordinator = await register_coordinator(request)
    return coordinator


@app.patch("/coordinators/{pc_id}")
async def patch_coordinator(
    pc_id: str, request: CoordinatorUpdateRequest, admin: AdminUser = Depends(get_current_admin)
):
    """Edit a coordinator's details, or deactivate them (is_active: false)."""
    updated = await update_coordinator(pc_id, request)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No coordinator found with pc_id: {pc_id}")
    return updated


@app.get("/coordinators")
async def get_coordinators(
    pc_id: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    admin: AdminUser = Depends(get_current_admin),
):
    """
    List Project Coordinators, or look up one specific PC via pc_id.
    Example: GET /coordinators?pc_id=PC001 — returns a list with 0 or 1
    item (same pattern as GET /employees — filtering, not a distinct
    single-object endpoint with its own 404 behavior).
    search matches name or phone_number (case-insensitive substring).
    """
    coordinators, total = await list_coordinators(
        pc_id=pc_id, is_active=is_active, search=search, page=page, page_size=page_size
    )
    return {
        "count": len(coordinators), "total": total, "page": page, "page_size": page_size,
        "coordinators": coordinators,
    }


@app.post("/employees")
async def create_employee(
    request: EmployeeRegistrationRequest, admin: AdminUser = Depends(get_current_admin)
):
    """
    Stage 1: HR registers a new employee with just phone number + name.
    employee_id is auto-generated and auto-incremented (EMP001, EMP002, ...).
    assigned_site, shift timing, and hierarchy fields (pc_id, area,
    designation) are left empty — set later via PATCH once decided.
    """
    try:
        employee = await register_employee(request)
    except ValueError as exc:
        # register_employee raises this for either a duplicate phone_number
        # OR an invalid pc_id — 409 (conflict) fits duplicates, but an
        # invalid pc_id is really a bad request (400), not a conflict.
        # Distinguish by message content since the function raises one
        # exception type for both cases.
        status = 400 if "pc_id" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc))
    return employee


@app.patch("/employees/{employee_id}")
async def patch_employee(
    employee_id: str, request: EmployeeUpdateRequest, admin: AdminUser = Depends(get_current_admin)
):
    """
    Stage 2: fill in assigned_site, shift timing, and/or hierarchy fields
    (pc_id, area, designation) once decided, or update phone_number (e.g.
    employee got a new number — see update_employee_details() docstring
    for the "takes effect immediately" caveat). Partial update — only
    fields actually provided in the request body change.
    """
    try:
        updated = await update_employee_details(employee_id, request)
    except ValueError as exc:
        # "already registered to a different employee" is a genuine
        # conflict (409), matching create_employee's convention — an
        # invalid pc_id is a plain bad request (400)
        status = 409 if "already" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    if updated is None:
        raise HTTPException(
            status_code=404, detail=f"No employee found with employee_id: {employee_id}"
        )
    return updated


@app.get("/employees")
async def get_employees(
    pc_id: str | None = None,
    area: str | None = None,
    designation: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    admin: AdminUser = Depends(get_current_admin),
):
    """
    Roster listing for the CMS — all filters optional, combine any of them.
    Example: GET /employees?pc_id=PC001&is_active=true&page=2
    search matches name or phone_number (case-insensitive substring).
    """
    employees, total = await list_employees(
        pc_id=pc_id, area=area, designation=designation, is_active=is_active,
        search=search, page=page, page_size=page_size,
    )
    return {
        "count": len(employees), "total": total, "page": page, "page_size": page_size,
        "employees": employees,
    }


@app.get("/attendance")
async def get_attendance(
    employee_id: str | None = None,
    pc_id: str | None = None,
    verdict: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    admin: AdminUser = Depends(get_current_admin),
):
    """
    Attendance submission records for the CMS — filterable by employee,
    PC (all employees under that coordinator), verdict, and date range
    (date_from/date_to as YYYY-MM-DD).
    Example: GET /attendance?pc_id=PC001&date_from=2026-09-01&verdict=flagged
    search matches the submitting employee's name (case-insensitive).

    Each record includes issues_display: a human-readable version of the
    raw issues[] codes (which have runtime-computed suffixes like
    "geofence_fail_300m" — not safe to string-match directly). Use
    issues_display for UI text; issues[] if you need the raw codes.
    """
    records, total = await list_attendance(
        employee_id=employee_id, pc_id=pc_id, verdict=verdict,
        date_from=date_from, date_to=date_to, search=search,
        page=page, page_size=page_size,
    )
    from app.services.attendance_grid import marker_for_submission
    from app.services.shift_check import check_shift_window
    local_tz = ZoneInfo("Asia/Kolkata")
    for record in records:
        issues = record.get("issues") or []
        record["issues_display"] = format_issue_list(issues)
        record["flag_reason"] = flag_reason_from_issues(issues) if record.get("verdict") == "flagged" else None
        photo_ts = record.get("photo_timestamp") or (record.get("overlay") or {}).get("timestamp")
        if photo_ts:
            try:
                capture = datetime.fromisoformat(str(photo_ts).replace("Z", "+00:00"))
                if capture.tzinfo is None:
                    capture = capture.replace(tzinfo=local_tz)
                capture = capture.astimezone(local_tz)
                record["check_in_at_ist"] = capture.isoformat()
                employee = await get_roster_by_employee_id(record["employee_id"]) if record.get("employee_id") else None
                if employee:
                    status, _ = check_shift_window(capture, employee.shift_start, employee.shift_end, employee.shift_grace_minutes)
                    record["shift_status"] = status
            except (ValueError, TypeError):
                record["check_in_at_ist"] = None
        else:
            record["check_in_at_ist"] = None
        record["attendance_code"] = marker_for_submission(record)
        if record.get("entry_type") == "system" and record.get("attendance_status") == "absent":
            record["attendance_code"] = "A"
        if record.get("verdict") == "verified" and record["check_in_at_ist"] is None:
            record["attendance_code"] = "F"
        record["review_display"] = (
            "Approved" if record.get("review_status") == "approved" else
            "Rejected" if record.get("review_status") == "rejected" else
            "Pending review" if record.get("verdict") == "flagged" else
            "Automatically verified" if record.get("verdict") == "verified" else
            "Not applicable"
        )
        if record.get("geofence_passed") is True:
            distance = record.get("geofence_distance_m")
            record["geofence_display"] = f"Within range ({distance:.0f} m)" if isinstance(distance, (int, float)) else "Within range"
        elif record.get("geofence_passed") is False:
            distance = record.get("geofence_distance_m")
            record["geofence_display"] = f"Outside range ({distance:.0f} m)" if isinstance(distance, (int, float)) else "Outside range (distance unavailable)"
        else:
            record["geofence_display"] = "Not verified (GPS/site missing)"
    return {
        "count": len(records), "total": total, "page": page, "page_size": page_size,
        "records": records,
    }


@app.post("/attendance/manual")
async def create_manual_entry(
    request: ManualAttendanceRequest, admin: AdminUser = Depends(get_current_admin)
):
    """
    Deliberate backdoor for when the WhatsApp/AI pipeline fails (bad
    photo, dropped webhook, etc.) — NOT a general alternative to the
    normal flow. Always creates a verdict="verified" record (manual
    entries skip all automated checks by design). Shows as a distinct
    "M" marker in the Excel export, never conflated with an
    auto-verified "P".

    Blocked if a submission already exists for this employee/date — if
    an existing record is wrong, resolve it via
    PATCH /attendance/{id}/resolve instead of creating a second one here.
    """
    try:
        record = await create_manual_attendance(
            request.employee_id, request.date, request.reason, admin.username
        )
    except ValueError as exc:
        status = 404 if "No employee found" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc))
    return record


@app.patch("/attendance/{submission_id}/resolve")
async def resolve_attendance(
    submission_id: str, request: ResolveRequest, admin: AdminUser = Depends(get_current_admin)
):
    """
    Admin resolves a flagged submission: "approved" -> counts as Present
    in the attendance export, "rejected" -> counts as Absent. Only works
    on submissions currently in "flagged" verdict state — already-verified
    or already-resolved records can't be re-resolved through this endpoint.
    """
    if request.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail='decision must be "approved" or "rejected"')
    updated = await resolve_flagged_submission(
        submission_id, request.decision, admin.username, request.reason
    )
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="No flagged submission found with that ID (already resolved, verified, or doesn't exist)",
        )
    return updated


@app.get("/attendance/export")
async def export_attendance(
    month: int | None = None,
    year: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    pc_id: str | None = None,
    admin: AdminUser = Depends(get_current_admin),
):
    """
    Excel export — Coordinators sheet, Field People sheet, and one sheet
    per PC with a day-by-day P/A/F/N-A grid (see attendance_grid.py for
    marker meanings and the deactivation rule).

    Scope: EITHER month+year (e.g. ?month=9&year=2026) OR date_from+date_to
    (YYYY-MM-DD) — pass one pair, not both. Optionally narrow to one PC
    via pc_id; omit it for the full org.
    """
    if month is not None and year is not None:
        if date_from or date_to:
            raise HTTPException(status_code=400, detail="Pass either month+year OR date_from/date_to, not both")
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        date_from = f"{year:04d}-{month:02d}-01"
        date_to = f"{year:04d}-{month:02d}-{last_day:02d}"
    elif date_from is not None and date_to is not None:
        pass  # use as given
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either month+year or date_from+date_to",
        )

    days = daterange(date_from, date_to)

    # Export needs EVERY matching record, not a paginated page — pass a
    # large page_size explicitly so this doesn't silently truncate to the
    # default 50 now that list_coordinators/list_employees are paginated.
    coordinators, _ = await list_coordinators(pc_id=pc_id, page_size=100_000)
    coordinators = [c.model_dump() for c in coordinators]
    employees, _ = await list_employees(pc_id=pc_id, page_size=100_000)
    employees = [e.model_dump() for e in employees]

    if pc_id is not None and not coordinators:
        raise HTTPException(status_code=404, detail=f"No coordinator found with pc_id: {pc_id}")

    employee_ids = [e["employee_id"] for e in employees]
    submissions_by_employee = await get_submissions_grouped(employee_ids, date_from, date_to)

    grids = {}
    for emp in employees:
        grids[emp["employee_id"]] = compute_employee_grid(
            emp.get("is_active", True),
            emp.get("deactivated_at"),
            submissions_by_employee.get(emp["employee_id"], {}),
            days,
        )

    xlsx_bytes = build_export_workbook(coordinators, employees, grids, days)

    filename = f"attendance_{date_from}_to_{date_to}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/enroll-face")
async def enroll_face(
    employee_id: str = Form(...),
    photos: list[UploadFile] = File(...),
    admin: AdminUser = Depends(get_current_admin),
):
    """
    HR/admin-facing enrollment endpoint — uploads 1 to 5 reference photos
    for an employee, used later by face-identity verification. 5 is
    recommended for best accuracy (see our design discussion on why), but
    fewer is accepted — useful for early testing or partial rollout.

    NOTE: does not require live WhatsApp traffic to test — call directly
    via curl/Postman with employee_id (form field) and 1-5 image files
    (multipart, field name "photos", repeated).

    IMPORTANT: per our design discussion, do not call this in production
    until biometric consent (DPDP) is confirmed collected for the employee
    being enrolled — this endpoint does not itself verify consent.
    """
    if not (1 <= len(photos) <= 5):
        raise HTTPException(
            status_code=400,
            detail=f"Between 1 and 5 reference photos required, got {len(photos)}",
        )

    roster_entry = await get_roster_by_employee_id(employee_id)
    if roster_entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"No roster entry found for employee_id: {employee_id}",
        )

    image_bytes_list = [await photo.read() for photo in photos]
    embeddings = enroll_embeddings(image_bytes_list)

    if len(embeddings) == 0:
        raise HTTPException(
            status_code=422,
            detail="No face detected in any of the 5 photos — enrollment failed",
        )
    if len(embeddings) < 5:
        logger.warning(
            "Only %d reference photo(s) with a detectable face for employee %s — "
            "fewer than the recommended 5, matching may be less robust to angle/lighting variance",
            len(embeddings), employee_id,
        )

    await save_enrollment(employee_id, embeddings)

    return {
        "status": "enrolled",
        "employee_id": employee_id,
        "name": roster_entry.name,
        "embeddings_stored": len(embeddings),
    }


@app.post("/sites/extract-photo")
async def extract_site_photo(file: UploadFile = File(...), admin: AdminUser = Depends(get_current_admin)):
    """Extract GPS camera overlay; admin must confirm coordinates before saving."""
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG or WebP image")
    data = await file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Maximum image size is 8 MB")
    from app.services.ocr import extract_overlay_data
    try:
        result = extract_overlay_data(data)
    except Exception:
        logger.exception("GPS image OCR failed")
        raise HTTPException(status_code=422, detail="Could not read GPS image")
    if result.latitude is None or result.longitude is None:
        raise HTTPException(status_code=422, detail="GPS coordinates not found; enter manually")
    if not (-90 <= result.latitude <= 90 and -180 <= result.longitude <= 180):
        raise HTTPException(status_code=422, detail="Invalid GPS coordinates")
    return {"name": result.place or "GPS photo location", "lat": result.latitude, "long": result.longitude, "requires_confirmation": True}
