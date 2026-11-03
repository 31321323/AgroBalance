import hashlib
import math
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.orm import Session
from .db import get_db, engine, SessionLocal
from .models import User, LoginSession, LoginAttempt, Crop, Field, Weather, BalanceDay, Irrigation, Recommendation, now
from .schemas import Register, Login, Profile, PasswordChange, FieldInput, CropInput, CalculateInput, IrrigationInput
from .services import seed_crops, seed_demo, today, replay, current_recommendation, weather_payload, utc_iso
from .calculation import crop_stage

hasher = PasswordHasher()
COOKIE = 'agrobalance_session'
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
ORIGINS = set(os.getenv('ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173').split(','))
if render_url := os.getenv('RENDER_EXTERNAL_URL'):
    ORIGINS.add(render_url)

@asynccontextmanager
async def lifespan(app):
    # Schema is managed exclusively by Alembic; startup fails on missing migrations.
    with SessionLocal() as db:
        db.execute(select(User.id).limit(1))
    yield

app = FastAPI(title='AgroBalance API', version='1.0.0', lifespan=lifespan)

@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        if (origin and origin not in ORIGINS) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': 'Недопустимый источник запроса'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response

@app.exception_handler(StaleDataError)
async def concurrent_edit(request, exc):
    return JSONResponse({'detail': 'Данные изменились в другом запросе. Обновите страницу и повторите.'}, status_code=409)

@app.exception_handler(IntegrityError)
async def duplicate_record(request, exc):
    return JSONResponse({'detail': 'Запись уже существует или изменена одновременно. Обновите страницу.'}, status_code=409)

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def verify(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False

DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))

def auth(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    login = db.get(LoginSession, digest(token)) if token else None
    expires = login.expires.replace(tzinfo=timezone.utc) if login and login.expires.tzinfo is None else login.expires if login else None
    if not login or expires <= now():
        raise HTTPException(401, 'Войдите в аккаунт')
    return db.get(User, login.user_id)

def session_for(db, user, response):
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(token_hash=digest(token), user_id=user.id, expires=now()+timedelta(days=7)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=SECURE, samesite='strict', max_age=604800, path='/')

def user_view(user):
    return {'id': user.id, 'name': user.name, 'email': user.email, 'demo': user.demo}

def rate_limit(db, request, scope, limit=10):
    # Shared across workers via DB; do not trust client-supplied forwarding headers.
    key = digest(scope + ':' + (request.client.host if request.client else 'unknown'))
    cutoff = now() - timedelta(minutes=15)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created < cutoff))
    count = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.key == key))
    if count >= limit:
        db.commit()
        raise HTTPException(429, 'Слишком много попыток. Повторите через 15 минут.', headers={'Retry-After': '900'})
    db.add(LoginAttempt(key=key))
    db.commit()

def owned(db, user, field_id, lock=False):
    query = select(Field).where(Field.id == field_id, Field.user_id == user.id)
    if lock:
        query = query.with_for_update()
    field = db.scalar(query)
    if not field:
        raise HTTPException(404, 'Участок не найден')
    return field

def lock_field(db, user, field_id):
    field = owned(db, user, field_id, True)
    field.version += 1
    db.flush()
    return field

def crop_owned(db, user, crop_id):
    crop = db.get(Crop, crop_id)
    if not crop or crop.user_id != user.id:
        raise HTTPException(404, 'Культура не найдена')
    return crop

def serialize(row):
    return {c.name: utc_iso(value) if isinstance(value := getattr(row, c.name), datetime) else value
            for c in row.__table__.columns if c.name not in ('user_id', 'version')}

def field_view(db, field):
    crop = db.get(Crop, field.crop_id)
    kc, stage = crop_stage(crop, field.planting_date, today(field))
    return {**serialize(field), 'crop_name': crop.name, 'kc': kc, 'stage': stage,
            'recommendation': current_recommendation(db, field)}

@app.get('/api/health')
def health(db: Session = Depends(get_db)):
    db.execute(select(User.id).limit(1))
    return {'status': 'ok'}

@app.post('/api/auth/register', status_code=201)
def register(data: Register, response: Response, request: Request, db: Session = Depends(get_db)):
    rate_limit(db, request, 'register', 10)
    email = str(data.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, 'Этот email уже зарегистрирован')
    user = User(email=email, name=data.name, password_hash=hasher.hash(data.password))
    db.add(user)
    db.flush()
    seed_crops(db, user.id)
    session_for(db, user, response)
    return user_view(user)

@app.post('/api/auth/login')
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit(db, request, 'login')
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, 'Неверный email или пароль')
    session_for(db, user, response)
    return user_view(user)

@app.post('/api/auth/demo')
def demo(request: Request, response: Response, db: Session = Depends(get_db)):
    if os.getenv('ENABLE_DEMO', 'true').lower() != 'true':
        raise HTTPException(404, 'Демонстрационный режим отключён')
    rate_limit(db, request, 'demo', 15)
    user = User(email='demo-'+secrets.token_hex(12)+'@example.test', name='Александр', demo=True,
                password_hash=hasher.hash(secrets.token_urlsafe(32)))
    db.add(user)
    db.flush()
    crops = seed_crops(db, user.id)
    seed_demo(db, user, crops)
    session_for(db, user, response)
    return user_view(user)

@app.post('/api/auth/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(request.cookies.get(COOKIE, ''))))
    db.commit()
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}

@app.get('/api/auth/me')
def me(user: User = Depends(auth)):
    return user_view(user)

@app.put('/api/auth/profile')
def profile(data: Profile, user: User = Depends(auth), db: Session = Depends(get_db)):
    user.name = data.name
    db.commit()
    return user_view(user)

@app.post('/api/auth/password')
def password(data: PasswordChange, request: Request, response: Response, user: User = Depends(auth), db: Session = Depends(get_db)):
    rate_limit(db, request, 'password')
    if not verify(data.current_password, user.password_hash):
        raise HTTPException(400, 'Текущий пароль неверен')
    user.password_hash = hasher.hash(data.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    session_for(db, user, response)
    return {'ok': True}

@app.get('/api/crops')
def crops(user: User = Depends(auth), db: Session = Depends(get_db)):
    return [serialize(c) for c in db.scalars(select(Crop).where(Crop.user_id == user.id).order_by(Crop.id))]

@app.put('/api/crops/{crop_id}')
def update_crop(crop_id: int, data: CropInput, user: User = Depends(auth), db: Session = Depends(get_db)):
    crop = crop_owned(db, user, crop_id)
    for key, value in data.model_dump().items():
        setattr(crop, key, value)
    # Existing daily Kc snapshots remain reproducible; new calculations use new coefficients.
    db.commit()
    return serialize(crop)

@app.get('/api/fields')
def fields(user: User = Depends(auth), db: Session = Depends(get_db)):
    return [field_view(db, f) for f in db.scalars(select(Field).where(Field.user_id == user.id).order_by(Field.id))]

@app.post('/api/fields', status_code=201)
def create_field(data: FieldInput, user: User = Depends(auth), db: Session = Depends(get_db)):
    crop_owned(db, user, data.crop_id)
    field = Field(user_id=user.id, **data.model_dump())
    if data.balance_start > today(field):
        raise HTTPException(422, 'Начало текущего баланса не может быть в будущем')
    db.add(field)
    db.commit()
    return field_view(db, field)

@app.get('/api/fields/{field_id}')
def get_field(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    return field_view(db, owned(db, user, field_id))

@app.put('/api/fields/{field_id}')
def update_field(field_id: int, data: FieldInput, user: User = Depends(auth), db: Session = Depends(get_db)):
    field = lock_field(db, user, field_id)
    crop_owned(db, user, data.crop_id)
    old_geo = (field.latitude, field.longitude, field.timezone)
    old_crop = (field.crop_id, field.planting_date)
    for key, value in data.model_dump().items():
        setattr(field, key, value)
    if field.balance_start > today(field):
        raise HTTPException(422, 'Начало текущего баланса не может быть в будущем')
    if old_geo != (field.latitude, field.longitude, field.timezone):
        db.execute(delete(Weather).where(Weather.field_id == field.id))
    if old_geo != (field.latitude, field.longitude, field.timezone) or old_crop != (field.crop_id, field.planting_date):
        for row in db.scalars(select(BalanceDay).where(BalanceDay.field_id == field.id, BalanceDay.day >= today(field))):
            row.source = 'needs_review'
    replay(db, field)
    db.commit()
    return field_view(db, field)

@app.delete('/api/fields/{field_id}')
def delete_field(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    db.delete(owned(db, user, field_id, True))
    db.commit()
    return {'ok': True}

@app.get('/api/fields/{field_id}/weather')
def weather(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    owned(db, user, field_id)
    return weather_payload(db.scalar(select(Weather).where(Weather.field_id == field_id)))

@app.post('/api/fields/{field_id}/weather/refresh')
def refresh_weather(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    field = lock_field(db, user, field_id)
    cached = db.scalar(select(Weather).where(Weather.field_id == field.id))
    if user.demo and cached and cached.source == 'demo':
        return weather_payload(cached)
    payload = weather_payload(cached)
    if cached and cached.source == 'Open-Meteo' and (now()-cached.fetched_at.replace(tzinfo=timezone.utc)).total_seconds() < 60:
        return payload
    try:
        with httpx.Client(timeout=8) as client:
            res = client.get('https://api.open-meteo.com/v1/forecast', params={
                'latitude': field.latitude, 'longitude': field.longitude, 'timezone': field.timezone,
                'forecast_days': 3, 'wind_speed_unit': 'ms',
                'daily': 'temperature_2m_mean,relative_humidity_2m_mean,wind_speed_10m_max,precipitation_sum,et0_fao_evapotranspiration'})
            res.raise_for_status()
            daily = res.json()['daily']
            days = [{'day': day, 'temperature': daily['temperature_2m_mean'][i],
                     'humidity': daily['relative_humidity_2m_mean'][i], 'wind': daily['wind_speed_10m_max'][i],
                     'rain': daily['precipitation_sum'][i], 'eto': daily['et0_fao_evapotranspiration'][i]}
                    for i, day in enumerate(daily['time'])]
        if not cached:
            cached = Weather(field_id=field.id, source='Open-Meteo', data={})
            db.add(cached)
        cached.data, cached.source, cached.fetched_at = {'days': days}, 'Open-Meteo', now()
        db.commit()
        return weather_payload(cached)
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
        db.rollback()
        return {**payload, 'error': 'Погодный сервис недоступен. Используйте сохранённые данные или ручной ввод.'}

@app.post('/api/fields/{field_id}/calculate')
def compute(field_id: int, data: CalculateInput, user: User = Depends(auth), db: Session = Depends(get_db)):
    field = lock_field(db, user, field_id)
    if data.day < field.balance_start or data.day > today(field)+timedelta(days=2):
        raise HTTPException(422, 'Дата должна быть от начала баланса до двух суток вперёд')
    if any(v is None for v in (field.taw, field.p, field.initial_deficit, field.target_deficit)):
        raise HTTPException(422, 'Требуется уточнение данных: укажите TAW, p, начальный и целевой дефицит')
    kc, stage = crop_stage(db.get(Crop, field.crop_id), field.planting_date, data.day)
    if kc is None:
        raise HTTPException(422, stage + '. Уточните дату посадки и длительности стадий.')
    eto, source = data.eto, 'manual'
    if eto is None:
        cached = weather_payload(db.scalar(select(Weather).where(Weather.field_id == field.id)))
        item = next((d for d in cached['days'] if d['day'] == data.day.isoformat()), None)
        if cached['stale'] or not item or item.get('eto') is None:
            raise HTTPException(422, 'Нет актуального ETo для этой даты. Обновите погоду или введите ETo вручную.')
        eto, source = item['eto'], cached['source']
    if not isinstance(eto, (int, float)) or not math.isfinite(eto) or not 0 <= eto <= 30:
        raise HTTPException(422, 'Погодный сервис вернул некорректный ETo. Введите значение вручную.')
    row = db.scalar(select(BalanceDay).where(BalanceDay.field_id == field.id, BalanceDay.day == data.day))
    if not row:
        row = BalanceDay(field_id=field.id, day=data.day)
        db.add(row)
    row.eto, row.kc, row.pe, row.source, row.updated_at = eto, kc, data.effective_rain, source, now()
    replay(db, field)
    result = db.scalar(select(Recommendation).where(Recommendation.field_id == field.id, Recommendation.day == data.day))
    db.commit()
    if not result:
        return {'status': 'insufficient', 'message': 'Данные сохранены. Заполните пропущенные дни от начала баланса.'}
    return {**result.data, 'computed_at': utc_iso(result.computed_at)}

@app.get('/api/fields/{field_id}/recommendations')
def recommendations(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    owned(db, user, field_id)
    return [{**r.data, 'computed_at': utc_iso(r.computed_at)} for r in db.scalars(select(Recommendation).where(Recommendation.field_id == field_id).order_by(Recommendation.day))]

@app.get('/api/fields/{field_id}/balance-days')
def balance_days(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    owned(db, user, field_id)
    return [serialize(r) for r in db.scalars(select(BalanceDay).where(BalanceDay.field_id == field_id).order_by(BalanceDay.day))]

@app.get('/api/irrigations')
def all_irrigations(user: User = Depends(auth), db: Session = Depends(get_db)):
    return [{**serialize(i), 'field_name': name} for i, name in db.execute(select(Irrigation, Field.name).join(Field).where(Field.user_id == user.id).order_by(Irrigation.day.desc(), Irrigation.id.desc()))]

@app.get('/api/fields/{field_id}/irrigations')
def irrigations(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    owned(db, user, field_id)
    return [serialize(i) for i in db.scalars(select(Irrigation).where(Irrigation.field_id == field_id).order_by(Irrigation.day.desc()))]

def validate_irrigation(field, data):
    if data.status == 'completed' and data.day > today(field):
        raise HTTPException(422, 'Нельзя подтвердить будущий полив')

@app.post('/api/fields/{field_id}/irrigations', status_code=201)
def add_irrigation(field_id: int, data: IrrigationInput, user: User = Depends(auth), db: Session = Depends(get_db)):
    field = lock_field(db, user, field_id)
    previous = db.scalar(select(Irrigation).where(Irrigation.field_id == field.id, Irrigation.request_key == data.request_key))
    if previous:
        return serialize(previous)
    validate_irrigation(field, data)
    event = Irrigation(field_id=field.id, area=field.area, efficiency=field.efficiency, **data.model_dump())
    db.add(event)
    replay(db, field)
    db.commit()
    return serialize(event)

@app.put('/api/fields/{field_id}/irrigations/{event_id}')
def edit_irrigation(field_id: int, event_id: int, data: IrrigationInput, user: User = Depends(auth), db: Session = Depends(get_db)):
    field = lock_field(db, user, field_id)
    event = db.get(Irrigation, event_id)
    if not event or event.field_id != field.id:
        raise HTTPException(404, 'Полив не найден')
    validate_irrigation(field, data)
    for key, value in data.model_dump(exclude={'request_key'}).items():
        setattr(event, key, value)
    replay(db, field)
    db.commit()
    return serialize(event)

@app.delete('/api/fields/{field_id}/irrigations/{event_id}')
def delete_irrigation(field_id: int, event_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    field = lock_field(db, user, field_id)
    event = db.get(Irrigation, event_id)
    if not event or event.field_id != field.id:
        raise HTTPException(404, 'Полив не найден')
    db.delete(event)
    replay(db, field)
    db.commit()
    return {'ok': True}

@app.get('/api/fields/{field_id}/analytics')
def analytics(field_id: int, user: User = Depends(auth), db: Session = Depends(get_db)):
    field = owned(db, user, field_id)
    events = list(db.scalars(select(Irrigation).where(Irrigation.field_id == field.id)))
    return {'actual_volume': sum(i.actual_volume or 0 for i in events if i.status == 'completed'),
            'completed_count': sum(i.status == 'completed' for i in events),
            'events': [serialize(i) for i in events],
            'balance': [{**r.data} for r in db.scalars(select(Recommendation).where(Recommendation.field_id == field.id).order_by(Recommendation.day))]}

DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    def spa(path: str):
        if path.startswith('api/'):
            raise HTTPException(404, 'Маршрут API не найден')
        return FileResponse(DIST / 'index.html')
