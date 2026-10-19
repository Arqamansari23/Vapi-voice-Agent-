"""ORM model for the patients table."""

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Sex(str, enum.Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    DECLINE = "Decline to Answer"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Required demographics (Mapped[str] => NOT NULL)
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[Sex] = mapped_column(
        Enum(Sex, name="sex", values_callable=lambda e: [m.value for m in e])
    )
    phone_number: Mapped[str] = mapped_column(String(10))
    email: Mapped[str | None] = mapped_column(String(254))

    # Address
    address_line_1: Mapped[str] = mapped_column(String(100))
    address_line_2: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    zip_code: Mapped[str] = mapped_column(String(10))

    # Optional extras
    insurance_provider: Mapped[str | None] = mapped_column(String(100))
    insurance_member_id: Mapped[str | None] = mapped_column(String(30))
    preferred_language: Mapped[str] = mapped_column(String(50), default="English")
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10))

    # Audit timestamps (UTC). deleted_at != NULL means soft-deleted.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Defence in depth: the API validates first, but the DB rejects bad shapes too.
    __table_args__ = (
        CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_patients_first_name_len"),
        CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_patients_last_name_len"),
        CheckConstraint("length(phone_number) = 10", name="ck_patients_phone_len"),
        CheckConstraint(
            "emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10",
            name="ck_patients_emergency_phone_len",
        ),
        CheckConstraint("length(state) = 2", name="ck_patients_state_len"),
        CheckConstraint("length(zip_code) IN (5, 10)", name="ck_patients_zip_len"),
        Index("ix_patients_phone_number", "phone_number"),
        Index("ix_patients_last_name", "last_name"),
    )
