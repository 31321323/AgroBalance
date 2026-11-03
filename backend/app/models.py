from datetime import datetime, timezone, date
from sqlalchemy import String, ForeignKey, UniqueConstraint, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(512))
    demo: Mapped[bool] = mapped_column(default=False)

class LoginSession(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Crop(Base):
    __tablename__ = 'crops'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kc_initial: Mapped[float]
    kc_mid: Mapped[float]
    kc_end: Mapped[float]
    days_initial: Mapped[int]
    days_development: Mapped[int]
    days_mid: Mapped[int]
    days_late: Mapped[int]
    source: Mapped[str] = mapped_column(String(1000))

class Field(Base):
    __tablename__ = 'fields'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    area: Mapped[float]
    latitude: Mapped[float]
    longitude: Mapped[float]
    location: Mapped[str] = mapped_column(String(100), default='')
    timezone: Mapped[str] = mapped_column(String(100), default='Europe/Chisinau')
    soil: Mapped[str] = mapped_column(String(100))
    crop_id: Mapped[int] = mapped_column(ForeignKey('crops.id'))
    planting_date: Mapped[date]
    irrigation_type: Mapped[str] = mapped_column(String(100))
    efficiency: Mapped[float]
    taw: Mapped[float | None]
    p: Mapped[float | None]
    initial_deficit: Mapped[float | None]
    target_deficit: Mapped[float | None]
    balance_start: Mapped[date]
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {'version_id_col': version}

class Weather(Base):
    __tablename__ = 'weather_data'
    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey('fields.id', ondelete='CASCADE'), unique=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    source: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)

class BalanceDay(Base):
    __tablename__ = 'balance_days'
    __table_args__ = (UniqueConstraint('field_id', 'day'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey('fields.id', ondelete='CASCADE'), index=True)
    day: Mapped[date]
    eto: Mapped[float]
    kc: Mapped[float]
    pe: Mapped[float]
    source: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Irrigation(Base):
    __tablename__ = 'irrigations'
    __table_args__ = (UniqueConstraint('field_id', 'request_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey('fields.id', ondelete='CASCADE'), index=True)
    day: Mapped[date]
    status: Mapped[str] = mapped_column(String(20))
    planned_volume: Mapped[float]
    actual_volume: Mapped[float | None]
    efficiency: Mapped[float]
    area: Mapped[float]
    note: Mapped[str] = mapped_column(String(500), default='')
    request_key: Mapped[str] = mapped_column(String(100))

class Recommendation(Base):
    __tablename__ = 'recommendations'
    __table_args__ = (UniqueConstraint('field_id', 'day'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    field_id: Mapped[int] = mapped_column(ForeignKey('fields.id', ondelete='CASCADE'), index=True)
    day: Mapped[date]
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict] = mapped_column(JSON)
