from datetime import date, timedelta, datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Field, Crop, Weather, BalanceDay, Irrigation, Recommendation, User, now
from .calculation import calculate, crop_stage

SOURCE = 'https://www.fao.org/4/x0490e/x0490e0b.htm (FAO-56, таблица 12; длительности стадий — демонстрационные, требуют местной калибровки)'

def utc_iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()

def today(field):
    return datetime.now(ZoneInfo(field.timezone)).date()

def seed_crops(db: Session, user_id):
    specs = [('Пшеница', .3, 1.15, .25, 20, 30, 50, 30), ('Кукуруза', .3, 1.2, .35, 20, 35, 40, 30),
             ('Хлопчатник', .35, 1.15, .5, 30, 50, 60, 40), ('Томат', .6, 1.15, .8, 30, 40, 40, 25),
             ('Картофель', .5, 1.15, .75, 25, 30, 45, 30)]
    crops = []
    for name, ini, mid, end, a, b, c, d in specs:
        crop = Crop(user_id=user_id, name=name, kc_initial=ini, kc_mid=mid, kc_end=end,
                    days_initial=a, days_development=b, days_mid=c, days_late=d, source=SOURCE)
        db.add(crop)
        crops.append(crop)
    db.flush()
    return crops

def seed_demo(db, user: User, crops):
    day = datetime.now(ZoneInfo('Europe/Chisinau')).date()
    for i, (name, crop, area, deficit, soil) in enumerate([
        ('Северное поле', crops[1], 1, 39, 'Суглинок'),
        ('Томатная долина', crops[3], 2.4, 18, 'Чернозём'),
        ('Зелёный горизонт', crops[4], 3.2, 26, 'Супесь')]):
        field = Field(user_id=user.id, name=name, area=area, latitude=47.01 + i * .04, longitude=28.86,
                      location='Кишинёв, Молдова', timezone='Europe/Chisinau', soil=soil, crop_id=crop.id,
                      planting_date=day-timedelta(days=65), irrigation_type='Капельное' if i else 'Дождевание',
                      efficiency=.8 if i == 0 else .9, taw=100, p=.4, initial_deficit=deficit,
                      target_deficit=12, balance_start=day)
        db.add(field)
        db.flush()
        db.add(Weather(field_id=field.id, source='demo', data={'days': [
            {'day': (day + timedelta(days=j)).isoformat(), 'temperature': 24 + j, 'humidity': 62-j*3,
             'wind': 2.8, 'rain': [3, 0, 1][j], 'eto': round(4/crop.kc_mid, 6)} for j in range(3)]}))
        db.add(BalanceDay(field_id=field.id, day=day, eto=4/crop.kc_mid, kc=crop.kc_mid, pe=2, source='demo'))
        for j in range(1, 6):
            db.add(Irrigation(field_id=field.id, day=day-timedelta(days=j*3), status='completed',
                              planned_volume=area*(20+j)*10, actual_volume=area*(18+j)*10,
                              area=area, efficiency=field.efficiency, request_key=f'demo-{i}-{j}',
                              note='Демонстрационная запись до начала текущего баланса'))
        db.flush()
        replay(db, field)

def weather_payload(weather):
    if not weather:
        return {'days': [], 'stale': True, 'source': None, 'fetched_at': None, 'error': 'Погодные данные ещё не загружены'}
    stamp = weather.fetched_at.replace(tzinfo=timezone.utc) if weather.fetched_at.tzinfo is None else weather.fetched_at
    return {**weather.data, 'source': weather.source, 'fetched_at': stamp.isoformat(),
            'stale': (now()-stamp).total_seconds() > 21600, 'demo': weather.source == 'demo'}

def replay(db, field):
    """Replay from immutable baseline; planned irrigations never change actual balance.

    Each day's ETc/Pe is applied once, then completed irrigation. Gaps stop the
    sequence. Forecast rows are scenarios, never the starting point for today.
    """
    db.flush()
    db.execute(delete(Recommendation).where(Recommendation.field_id == field.id))
    if any(v is None for v in (field.taw, field.p, field.initial_deficit, field.target_deficit)):
        return
    previous = field.initial_deficit
    days = list(db.scalars(select(BalanceDay).where(BalanceDay.field_id == field.id).order_by(BalanceDay.day)))
    events = list(db.scalars(select(Irrigation).where(Irrigation.field_id == field.id, Irrigation.status == 'completed')))
    expected = field.balance_start
    for row in days:
        if row.day < expected:
            continue
        if row.day != expected:
            break
        if row.source == 'needs_review':
            break
        result = calculate(taw=field.taw, p=field.p, previous_deficit=previous, eto=row.eto, kc=row.kc,
                           effective_rain=row.pe, target_deficit=field.target_deficit,
                           efficiency=field.efficiency, area=field.area)
        actual_net = sum(e.actual_volume / (e.area * 10) * e.efficiency for e in events if e.day == row.day)
        after = max(0, result['deficit'] - actual_net)
        # Recommendation is for water still needed after all confirmed events.
        remaining = calculate(taw=field.taw, p=field.p, previous_deficit=after, eto=0, kc=0, effective_rain=0,
                              target_deficit=field.target_deficit, efficiency=field.efficiency, area=field.area)
        result.update(deficit_before_irrigation=result['deficit'], deficit=round(after, 6),
                      needed=remaining['needed'], net=remaining['net'], gross=remaining['gross'], volume=remaining['volume'],
                      actual_net=round(actual_net, 6), previous_deficit=previous, eto=row.eto, kc=row.kc,
                      effective_rain=row.pe, source=row.source, area=field.area, efficiency=field.efficiency,
                      taw=field.taw, p=field.p, target_deficit=field.target_deficit,
                      forecast=row.day > today(field), inputs_updated_at=utc_iso(row.updated_at),
                      day=row.day.isoformat(), status='irrigate' if remaining['needed'] else 'ok')
        db.add(Recommendation(field_id=field.id, day=row.day, data=result))
        previous = after
        expected += timedelta(days=1)
    db.flush()

def current_recommendation(db, field):
    row = db.scalar(select(Recommendation).where(Recommendation.field_id == field.id, Recommendation.day == today(field)))
    if not row:
        return {'status': 'insufficient', 'message': 'Заполните параметры и непрерывный ежедневный баланс от даты начала до сегодня.'}
    data = dict(row.data)
    data['computed_at'] = utc_iso(row.computed_at)
    updated = datetime.fromisoformat(data['inputs_updated_at'])
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    if (now()-updated).total_seconds() > 21600:
        data.update(status='insufficient', message='Исходные погодные данные старше 6 часов. Обновите погоду и расчёт.')
    return data
