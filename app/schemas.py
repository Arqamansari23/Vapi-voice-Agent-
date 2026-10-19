"""Pydantic schemas: the single source of truth for patient validation.

Both the REST API and the Vapi tool endpoint validate through these models,
so the voice agent can never write data the API would reject. Validators are
deliberately tolerant of how people *say* things on the phone ("Texas",
"(512) 555-0101", "1/5/1990") and normalize to the canonical stored format.
"""

import re
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    field_serializer,
    model_validator,
)

from app.models import Sex

# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
_STATE_BY_NAME = {name.lower(): abbr for abbr, name in US_STATES.items()}

_SEX_ALIASES = {
    "m": Sex.MALE, "male": Sex.MALE, "man": Sex.MALE,
    "f": Sex.FEMALE, "female": Sex.FEMALE, "woman": Sex.FEMALE,
    "other": Sex.OTHER, "o": Sex.OTHER, "non-binary": Sex.OTHER, "nonbinary": Sex.OTHER,
    "decline to answer": Sex.DECLINE, "decline": Sex.DECLINE, "declined": Sex.DECLINE,
    "prefer not to say": Sex.DECLINE, "prefer not to answer": Sex.DECLINE,
}

# Unicode letters, optionally joined by single spaces, hyphens or apostrophes.
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_MEMBER_ID_RE = re.compile(r"^[A-Z0-9]{1,30}$")

REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)

# --------------------------------------------------------------------------- #
# Reusable validators (also used directly for query-param parsing)
# --------------------------------------------------------------------------- #


def normalize_phone(value: Any) -> str:
    """'+1 (512) 555-0101' -> '5125550101'. Raises ValueError if not a valid US number."""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(f"must be a 10-digit U.S. phone number (got {len(digits)} digits)")
    if digits[0] in "01":
        raise ValueError("is not a valid U.S. number (area code cannot start with 0 or 1)")
    return digits


def parse_date(value: Any) -> date:
    """Accept MM/DD/YYYY (canonical), M/D/YYYY, MM-DD-YYYY or ISO YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("must be a valid date in MM/DD/YYYY format")


def _check_date_of_birth(value: date) -> date:
    today = datetime.now(UTC).date()
    if value > today:
        raise ValueError("cannot be in the future")
    if value.year < today.year - 120:
        raise ValueError("must be within the last 120 years")
    return value


def _name_validator(max_len: int):
    def validate(value: str) -> str:
        value = " ".join(value.replace("’", "'").split())  # curly apostrophe, extra spaces
        if not 1 <= len(value) <= max_len:
            raise ValueError(f"must be 1-{max_len} characters")
        if not _NAME_RE.match(value):
            raise ValueError("may only contain letters, hyphens, apostrophes and spaces")
        return value

    return validate


def _text_validator(max_len: int):
    def validate(value: str) -> str:
        value = " ".join(value.split())
        if not 1 <= len(value) <= max_len:
            raise ValueError(f"must be 1-{max_len} characters")
        return value

    return validate


def _parse_sex(value: Any) -> Sex:
    if isinstance(value, Sex):
        return value
    sex = _SEX_ALIASES.get(" ".join(str(value).lower().split()))
    if sex is None:
        raise ValueError("must be one of: Male, Female, Other, Decline to Answer")
    return sex


def _normalize_state(value: str) -> str:
    key = " ".join(value.replace(".", "").split())
    if key.upper() in US_STATES:
        return key.upper()
    if abbr := _STATE_BY_NAME.get(key.lower()):
        return abbr
    raise ValueError("must be a valid 2-letter U.S. state abbreviation")


def _normalize_zip(value: str) -> str:
    value = value.replace(" ", "")
    if re.fullmatch(r"\d{9}", value):
        value = f"{value[:5]}-{value[5:]}"
    if not _ZIP_RE.match(value):
        raise ValueError("must be a 5-digit ZIP code or ZIP+4 (12345-6789)")
    return value


def _normalize_member_id(value: str) -> str:
    value = re.sub(r"[\s\-]", "", value).upper()
    if not _MEMBER_ID_RE.match(value):
        raise ValueError("must be 1-30 letters and numbers")
    return value


PersonName = Annotated[str, AfterValidator(_name_validator(50))]
ContactName = Annotated[str, AfterValidator(_name_validator(100))]
PhoneNumber = Annotated[str, AfterValidator(normalize_phone)]
DateOfBirth = Annotated[date, BeforeValidator(parse_date), AfterValidator(_check_date_of_birth)]
SexValue = Annotated[Sex, BeforeValidator(_parse_sex)]
Text100 = Annotated[str, AfterValidator(_text_validator(100))]
Text50 = Annotated[str, AfterValidator(_text_validator(50))]
StateCode = Annotated[str, AfterValidator(_normalize_state)]
ZipCode = Annotated[str, AfterValidator(_normalize_zip)]
MemberId = Annotated[str, AfterValidator(_normalize_member_id)]

# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class _PatientInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        coerce_numbers_to_str=True,  # LLMs sometimes send ZIP/phone as numbers
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_blank_strings(cls, data: Any) -> Any:
        # "" means "not provided": defaults apply and required fields report "Field required".
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not (isinstance(v, str) and not v.strip())}
        return data


class PatientCreate(_PatientInput):
    first_name: PersonName
    last_name: PersonName
    date_of_birth: DateOfBirth
    sex: SexValue
    phone_number: PhoneNumber
    email: EmailStr | None = None
    address_line_1: Text100
    address_line_2: Text100 | None = None
    city: Text100
    state: StateCode
    zip_code: ZipCode
    insurance_provider: Text100 | None = None
    insurance_member_id: MemberId | None = None
    preferred_language: Text50 = "English"
    emergency_contact_name: ContactName | None = None
    emergency_contact_phone: PhoneNumber | None = None


class PatientUpdate(_PatientInput):
    """Partial update: only fields present in the payload are changed."""

    first_name: PersonName | None = None
    last_name: PersonName | None = None
    date_of_birth: DateOfBirth | None = None
    sex: SexValue | None = None
    phone_number: PhoneNumber | None = None
    email: EmailStr | None = None
    address_line_1: Text100 | None = None
    address_line_2: Text100 | None = None
    city: Text100 | None = None
    state: StateCode | None = None
    zip_code: ZipCode | None = None
    insurance_provider: Text100 | None = None
    insurance_member_id: MemberId | None = None
    preferred_language: Text50 | None = None
    emergency_contact_name: ContactName | None = None
    emergency_contact_phone: PhoneNumber | None = None

    @model_validator(mode="after")
    def _check_fields(self) -> "PatientUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        nulled = [f for f in REQUIRED_FIELDS if f in self.model_fields_set and getattr(self, f) is None]
        if nulled:
            raise ValueError(f"required fields cannot be cleared: {', '.join(nulled)}")
        return self


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: Sex
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @field_serializer("date_of_birth")
    def _serialize_dob(self, value: date) -> str:
        return value.strftime("%m/%d/%Y")

    @field_serializer("created_at", "updated_at", "deleted_at")
    def _serialize_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite drops tzinfo; values are stored as UTC
            value = value.replace(tzinfo=UTC)
        return value.isoformat()


def format_errors(errors: list[dict]) -> list[dict]:
    """Turn pydantic errors into [{field, message}] that humans (and the LLM) can read."""
    formatted = []
    for err in errors:
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        formatted.append({
            "field": ".".join(loc) or "request",
            "message": err.get("msg", "invalid value").removeprefix("Value error, "),
        })
    return formatted
