"""REST endpoints for patient records."""

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.models import Patient
from app.responses import ApiError, success
from app.schemas import PatientCreate, PatientOut, PatientUpdate, normalize_phone, parse_date

router = APIRouter(prefix="/patients", tags=["patients"])


def _out(patient: Patient) -> dict:
    return PatientOut.model_validate(patient).model_dump(mode="json")


def _parse_filter(name: str, value: str | None, parser: Callable[[str], Any]) -> Any:
    if not value:
        return None
    try:
        return parser(value)
    except ValueError as exc:
        raise ApiError(400, "bad_request", f"Invalid query parameter '{name}'",
                       [{"field": name, "message": str(exc)}]) from exc


@router.get("")
def list_patients(
    last_name: str | None = Query(None, max_length=50),
    date_of_birth: str | None = Query(None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: str | None = Query(None, description="Any format; normalized to 10 digits"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    patients = services.list_patients(
        db,
        last_name=last_name,
        date_of_birth=_parse_filter("date_of_birth", date_of_birth, parse_date),
        phone_number=_parse_filter("phone_number", phone_number, normalize_phone),
    )
    return success([_out(p) for p in patients])


@router.get("/{patient_id}")
def get_patient(patient_id: uuid.UUID, db: Session = Depends(get_db)) -> JSONResponse:
    return success(_out(services.get_patient(db, patient_id)))


@router.post("", status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)) -> JSONResponse:
    return success(_out(services.create_patient(db, payload)), status_code=201)


@router.put("/{patient_id}")
def update_patient(patient_id: uuid.UUID, payload: PatientUpdate, db: Session = Depends(get_db)) -> JSONResponse:
    return success(_out(services.update_patient(db, patient_id, payload)))


@router.delete("/{patient_id}")
def delete_patient(patient_id: uuid.UUID, db: Session = Depends(get_db)) -> JSONResponse:
    return success(_out(services.soft_delete_patient(db, patient_id)))
