"""
Extracts structured data (place, lat/long, date, time) from the burned-in
GPS Map Camera overlay on employee selfies.

TESTED against a real sample image (Individual_pic.jpeg, 28/08/2026 submission)
— raw Tesseract OCR on the full image reliably captured all fields with no
preprocessing needed:

    ie GPS Map Camera
    Ashti, Maharashtra, India
    R53f+rwr, Maliwada, Ashti, Maharashtra 414203, India
    Lat 18.804903° Long 75.174764°
    Friday, 28/08/2026 09:27 AM GMT +05:30

All three regex extractions (lat/long, date/time, place) matched correctly
against this real output. Worth re-testing against a handful more real
employee submissions once live traffic starts — overlay position/wording
can vary slightly by phone/app version, and this was validated against
one sample only.
"""
import logging
import re
from datetime import datetime
from io import BytesIO
from typing import Optional
import os

import pytesseract


if os.name == "nt" and os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger("ocr")

LAT_LONG_PATTERN = re.compile(r"Lat\s+([\-0-9.,:]+)[Â°\"']?\s+Long\s+([\-0-9.,:]+)[Â°\"']?", re.IGNORECASE)
DATETIME_PATTERN = re.compile(
    r"(\w+day),?\s+(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)\s+GMT\s*([+\-]\d{2}:\d{2})"
)
PLACE_PATTERN = re.compile(r"([A-Za-z .]+,\s*[A-Za-z .]+,\s*India)")


class OverlayData(BaseModel):
    raw_text: str
    place: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timestamp: Optional[datetime] = None
    extraction_complete: bool = False
    exif_timestamp: Optional[datetime] = None


def extract_overlay_data(image_bytes: bytes) -> OverlayData:
    """
    Run OCR on an employee's selfie and extract the GPS Map Camera overlay
    fields needed for geofence + shift-window checks.
    """
    img = Image.open(BytesIO(image_bytes))
    raw_text = pytesseract.image_to_string(img)

    result = OverlayData(raw_text=raw_text)
    try:
        exif = img.getexif()
        # DateTimeOriginal=36867, DateTimeDigitized=36868, DateTime=306
        for tag in (36867, 36868, 306):
            value = exif.get(tag)
            if value:
                try:
                    result.exif_timestamp = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                    break
                except ValueError:
                    pass
    except Exception:
        logger.debug("EXIF metadata unavailable", exc_info=True)

    if match := LAT_LONG_PATTERN.search(raw_text):
        lat_str = match.group(1).replace(",", ".").replace(":", ".")
        lon_str = match.group(2).replace(",", ".").replace(":", ".")

        try:
            result.latitude = float(lat_str)
            result.longitude = float(lon_str)
        except ValueError:
            logger.warning(
                "Could not convert lat/long: %s, %s",
                lat_str,
                lon_str,
            )
    else:
        logger.warning("Could not extract lat/long from overlay")

    if match := DATETIME_PATTERN.search(raw_text):
        _, date_str, time_str, tz_offset = match.groups()
        # Combine into a parseable string — GMT offset from image (e.g. +05:30)
        dt_str = f"{date_str} {time_str} {tz_offset}"
        try:
            result.timestamp = datetime.strptime(dt_str, "%d/%m/%Y %I:%M %p %z")
        except ValueError:
            logger.warning("Found date/time text but failed to parse: %s", dt_str)
    else:
        logger.warning("Could not extract date/time from overlay")

    if match := PLACE_PATTERN.search(raw_text):
        result.place = match.group(1).strip()

    result.extraction_complete = (
        result.latitude is not None
        and result.longitude is not None
        and result.timestamp is not None
    )

    return result
