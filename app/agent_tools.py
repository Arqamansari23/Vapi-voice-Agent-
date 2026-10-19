"""Business logic behind the voice agent's function tools.

Each handler takes the tool arguments the LLM produced and returns a short,
plain-English string that Vapi feeds back to the LLM. Results start with a
status keyword (SUCCESS, VALIDATION_ERROR, ...) that the system prompt tells
the agent how to handle, so failures are spoken to the caller, never silent.
"""

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app import services
from app.models import Patient
from app.schemas import PatientCreate, PatientOut, PatientUpdate, format_errors, normalize_phone

logger = logging.getLogger(__name__)

SAVE_FAILED = (
    "SAVE_FAILED: The record could not be saved because of a system error. Nothing was saved. "
    "Apologize to the caller and follow the save-failure instructions."
)


def _known_fields(args: dict, model: type[BaseModel]) -> dict:
    """Ignore stray keys the LLM may add so they don't surface as confusing errors."""
    return {k: v for k, v in args.items() if k in model.model_fields}


def _validation_message(exc: ValidationError) -> str:
    problems = "; ".join(f"{e['field']} ({e['message']})" for e in format_errors(exc.errors()))
    return (
        f"VALIDATION_ERROR: These fields were rejected: {problems}. Explain the problem to the "
        "caller in plain words, ask again for only these fields, then call the tool again."
    )


def _describe(patient: Patient) -> str:
    return (
        f"patient_id={patient.patient_id}, name={patient.first_name} {patient.last_name}, "
        f"date_of_birth={patient.date_of_birth:%m/%d/%Y}"
    )


def _is_true(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "yes", "1"}


def lookup_patient_by_phone(db: Session, args: dict) -> str:
    try:
        phone = normalize_phone(args.get("phone_number", ""))
    except ValueError as exc:
        return f"VALIDATION_ERROR: phone_number ({exc}). Ask the caller for their 10-digit phone number again."

    matches = services.find_by_phone(db, phone)
    if not matches:
        return "NOT_FOUND: No existing patient has this phone number. Continue the new registration."
    records = "; ".join(_describe(p) for p in matches)
    return (
        f"FOUND: {len(matches)} existing record(s) with this phone number: {records}. "
        "Ask the caller if they would like to update their existing record instead. "
        "Use the date of birth only to verify the caller; never read it out."
    )


def register_patient(db: Session, args: dict) -> str:
    try:
        data = PatientCreate.model_validate(_known_fields(args, PatientCreate))
    except ValidationError as exc:
        return _validation_message(exc)

    if not _is_true(args.get("allow_duplicate")):
        existing = services.find_by_phone(db, data.phone_number)
        if existing:
            return (
                f"DUPLICATE_FOUND: A patient already exists with this phone number: "
                f"{'; '.join(_describe(p) for p in existing)}. Nothing was saved. Ask the caller whether "
                "to update that record (update_patient) or create a separate new record "
                "(call register_patient again with allow_duplicate=true)."
            )

    try:
        patient = services.create_patient(db, data)
    except services.DatabaseError:
        return SAVE_FAILED

    logger.info("patient_registered %s", json.dumps(PatientOut.model_validate(patient).model_dump(mode="json")))
    return (
        f"SUCCESS: Patient registered with patient_id={patient.patient_id}. "
        f"Tell the caller: You're all set, {patient.first_name}."
    )


def update_patient(db: Session, args: dict) -> str:
    try:
        patient_id = uuid.UUID(str(args.get("patient_id")))
    except ValueError:
        return "ERROR: patient_id is missing or invalid. Use the patient_id returned by lookup_patient_by_phone."

    try:
        changes = PatientUpdate.model_validate(_known_fields(args, PatientUpdate))
    except ValidationError as exc:
        return _validation_message(exc)

    try:
        patient = services.update_patient(db, patient_id, changes)
    except services.NotFoundError:
        return "NOT_FOUND: That patient record no longer exists. Offer to register the caller as a new patient."
    except services.DatabaseError:
        return SAVE_FAILED

    logger.info("patient_updated %s", json.dumps(PatientOut.model_validate(patient).model_dump(mode="json")))
    return f"SUCCESS: Record updated for {patient.first_name} {patient.last_name}."


TOOL_HANDLERS: dict[str, Callable[[Session, dict], str]] = {
    "lookup_patient_by_phone": lookup_patient_by_phone,
    "register_patient": register_patient,
    "update_patient": update_patient,
}
