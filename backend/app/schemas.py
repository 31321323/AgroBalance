from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator, field_validator

class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False, str_strip_whitespace=True)

class Register(Schema):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=1, max_length=100)

class Login(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class Profile(Schema):
    name: str = Field(min_length=1, max_length=100)

class PasswordChange(Schema):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

class FieldInput(Schema):
    name: str = Field(min_length=1, max_length=100)
    area: float = Field(gt=0, le=1000000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location: str = Field(default='', max_length=100)
    timezone: str = 'Europe/Chisinau'
    soil: str = Field(min_length=1, max_length=100)
    crop_id: int
    planting_date: date
    irrigation_type: str = Field(min_length=1, max_length=100)
    efficiency: float = Field(gt=0, le=1)
    taw: float | None = Field(default=None, gt=0, le=2000)
    p: float | None = Field(default=None, gt=0, le=1)
    initial_deficit: float | None = Field(default=None, ge=0)
    target_deficit: float | None = Field(default=None, ge=0)
    balance_start: date

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Неизвестный часовой пояс IANA')
        return value

    @model_validator(mode='after')
    def deficits(self):
        if self.taw is not None:
            if any(v is not None and v > self.taw for v in (self.initial_deficit, self.target_deficit)):
                raise ValueError('Дефицит не должен превышать TAW')
            if self.p is not None and self.target_deficit is not None and self.target_deficit >= self.p * self.taw:
                raise ValueError('Целевой дефицит должен быть ниже порога RAW')
        if self.balance_start < self.planting_date:
            raise ValueError('Начало баланса не может быть раньше посадки')
        return self

class CropInput(Schema):
    kc_initial: float = Field(ge=0, le=3)
    kc_mid: float = Field(ge=0, le=3)
    kc_end: float = Field(ge=0, le=3)
    days_initial: int = Field(gt=0, le=365)
    days_development: int = Field(gt=0, le=365)
    days_mid: int = Field(gt=0, le=365)
    days_late: int = Field(gt=0, le=365)
    source: str = Field(min_length=3, max_length=1000)

class CalculateInput(Schema):
    day: date
    eto: float | None = Field(default=None, ge=0, le=30)
    effective_rain: float = Field(ge=0, le=1000)

class IrrigationInput(Schema):
    day: date
    status: Literal['planned', 'completed']
    planned_volume: float = Field(ge=0, le=1000000000)
    actual_volume: float | None = Field(default=None, ge=0, le=1000000000)
    note: str = Field(default='', max_length=500)
    request_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode='after')
    def actual_required(self):
        if self.status == 'completed' and self.actual_volume is None:
            raise ValueError('Для выполненного полива укажите фактический объём')
        if self.status == 'planned' and self.actual_volume is not None:
            raise ValueError('Фактический объём указывается после выполнения')
        return self
