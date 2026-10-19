"""Patient service layer: the only code that touches the database.

Shared by the REST API and the Vapi tool handlers.
"""

import logging
import uuid
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Patient, utcnow
from app.schemas import PatientCreate, PatientUpdate

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    pass


class DatabaseError(Exception):
    pass


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Database write failed")
        raise DatabaseError("Could not save the patient record") from exc


def _active() -> Select:
    return select(Patient).where(Patient.deleted_at.is_(None))


def create_patient(db: Session, data: PatientCreate) -> Patient:
    patient = Patient(**data.model_dump())
    db.add(patient)
    _commit(db)
    db.refresh(patient)
    return patient


def get_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = db.scalar(_active().where(Patient.patient_id == patient_id))
    if patient is None:
        raise NotFoundError(f"Patient {patient_id} not found")
    return patient


def list_patients(
    db: Session,
    last_name: str | None = None,
    date_of_birth: date | None = None,
    phone_number: str | None = None,
) -> list[Patient]:
    stmt = _active()
    if last_name:
        stmt = stmt.where(func.lower(Patient.last_name) == last_name.strip().lower())
    if date_of_birth:
        stmt = stmt.where(Patient.date_of_birth == date_of_birth)
    if phone_number:
        stmt = stmt.where(Patient.phone_number == phone_number)
    return list(db.scalars(stmt.order_by(Patient.created_at.desc())))


def find_by_phone(db: Session, phone_number: str) -> list[Patient]:
    return list_patients(db, phone_number=phone_number)


def update_patient(db: Session, patient_id: uuid.UUID, changes: PatientUpdate) -> Patient:
    patient = get_patient(db, patient_id)
    for field, value in changes.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    patient.updated_at = utcnow()
    _commit(db)
    db.refresh(patient)
    return patient


def soft_delete_patient(db: Session, patient_id: uuid.UUID) -> Patient:
    patient = get_patient(db, patient_id)
    patient.deleted_at = utcnow()
    _commit(db)
    db.refresh(patient)
    return patient


DEMO_PATIENTS = [
    {
        "first_name": "Jane", "last_name": "Doe", "date_of_birth": "03/14/1988", "sex": "Female",
        "phone_number": "5125550101", "email": "jane.doe@example.com",
        "address_line_1": "100 Congress Ave", "address_line_2": "Apt 4B", "city": "Austin",
        "state": "TX", "zip_code": "78701", "insurance_provider": "Blue Cross Blue Shield",
        "insurance_member_id": "BCB123456789",
    },
    {
        "first_name": "John", "last_name": "Smith", "date_of_birth": "11/02/1975", "sex": "Male",
        "phone_number": "3125550199", "address_line_1": "233 S Wacker Dr", "city": "Chicago",
        "state": "IL", "zip_code": "60606", "emergency_contact_name": "Mary Smith",
        "emergency_contact_phone": "3125550198",
    },
]


def seed_demo_patients(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Patient)):
        return
    for record in DEMO_PATIENTS:
        create_patient(db, PatientCreate.model_validate(record))
    logger.info("Seeded %d demo patients", len(DEMO_PATIENTS))
