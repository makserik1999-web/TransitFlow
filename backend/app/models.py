"""SQLAlchemy-модели и enum'ы строго по разделу 5 спеки."""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# ---------------------------------------------------------------------------
# Enum'ы (раздел 5)
# ---------------------------------------------------------------------------
class UserRole(str, enum.Enum):
    shipper = "shipper"
    carrier = "carrier"
    analyst = "analyst"


class CheckpointKind(str, enum.Enum):
    sea_port = "sea_port"
    road_border = "road_border"
    rail_border = "rail_border"
    road_hub = "road_hub"


class CargoType(str, enum.Enum):
    container = "container"
    bulk = "bulk"
    liquid = "liquid"
    general = "general"


class RequestStatus(str, enum.Enum):
    open = "open"
    accepted = "accepted"
    slot_booked = "slot_booked"
    done = "done"
    cancelled = "cancelled"


class BookingStatus(str, enum.Enum):
    booked = "booked"
    arrived = "arrived"
    passed = "passed"
    no_show = "no_show"


class Direction(str, enum.Enum):
    export = "export"
    import_ = "import"  # 'import' — зарезервированное слово; значение в БД = "import"
    transit = "transit"


# Общие helper'ы для Enum-колонок: храним value ("shipper"), а не имя.
def _enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


# ---------------------------------------------------------------------------
# Таблицы
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"), nullable=False, index=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)

    requests: Mapped[list["CargoRequest"]] = relationship(
        back_populates="shipper", foreign_keys="CargoRequest.shipper_id"
    )
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="carrier", foreign_keys="Assignment.carrier_id"
    )


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[CheckpointKind] = mapped_column(_enum(CheckpointKind, "checkpoint_kind"), nullable=False)
    lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    lng: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    capacity_per_hour: Mapped[int] = mapped_column(Integer, nullable=False)

    slots: Mapped[list["Slot"]] = relationship(back_populates="checkpoint")
    traffic: Mapped[list["TrafficHistory"]] = relationship(back_populates="checkpoint")


class CargoRequest(Base):
    __tablename__ = "cargo_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    cargo_type: Mapped[CargoType] = mapped_column(_enum(CargoType, "cargo_type"), nullable=False)
    weight_t: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    desired_date: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[RequestStatus] = mapped_column(
        _enum(RequestStatus, "request_status"), nullable=False, default=RequestStatus.open, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    shipper: Mapped["User"] = relationship(back_populates="requests", foreign_keys=[shipper_id])
    assignment: Mapped["Assignment | None"] = relationship(back_populates="request", uselist=False)


class Assignment(Base):
    __tablename__ = "assignments"
    # request_id UNIQUE — одна заявка принимается ровно одним перевозчиком.
    __table_args__ = (UniqueConstraint("request_id", name="uq_assignments_request_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("cargo_requests.id"), nullable=False)
    carrier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    truck_plate: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    request: Mapped["CargoRequest"] = relationship(back_populates="assignment")
    carrier: Mapped["User"] = relationship(back_populates="assignments", foreign_keys=[carrier_id])
    booking: Mapped["Booking | None"] = relationship(back_populates="assignment", uselist=False)


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    checkpoint_id: Mapped[int] = mapped_column(ForeignKey("checkpoints.id"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    booked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    checkpoint: Mapped["Checkpoint"] = relationship(back_populates="slots")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="slot")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), nullable=False, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False, index=True)
    qr_token: Mapped[uuid.UUID] = mapped_column(unique=True, default=uuid.uuid4, nullable=False, index=True)
    status: Mapped[BookingStatus] = mapped_column(
        _enum(BookingStatus, "booking_status"), nullable=False, default=BookingStatus.booked
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    slot: Mapped["Slot"] = relationship(back_populates="bookings")
    assignment: Mapped["Assignment"] = relationship(back_populates="booking")


class TrafficHistory(Base):
    __tablename__ = "traffic_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    checkpoint_id: Mapped[int] = mapped_column(ForeignKey("checkpoints.id"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    trucks_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cargo_type: Mapped[CargoType] = mapped_column(_enum(CargoType, "cargo_type"), nullable=False)
    direction: Mapped[Direction] = mapped_column(_enum(Direction, "direction"), nullable=False)

    checkpoint: Mapped["Checkpoint"] = relationship(back_populates="traffic")
