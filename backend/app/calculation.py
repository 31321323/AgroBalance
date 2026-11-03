"""Pure daily water balance. All depths mm, area ha, volumes m³."""
from math import isfinite

def calculate(*, taw, p, previous_deficit, eto, kc, effective_rain, target_deficit, efficiency, area):
    values = (taw, p, previous_deficit, eto, kc, effective_rain, target_deficit, efficiency, area)
    if not all(isfinite(x) for x in values):
        raise ValueError('Параметры должны быть конечными числами')
    if not (taw > 0 and 0 < p <= 1 and 0 < efficiency <= 1 and area > 0):
        raise ValueError('Недопустимые TAW, p, эффективность или площадь')
    if not (0 <= previous_deficit <= taw and 0 <= target_deficit <= taw and min(eto, kc, effective_rain) >= 0):
        raise ValueError('Недопустимый дефицит, ETo, Kc или осадки')
    etc = kc * eto
    deficit = max(0.0, min(taw, previous_deficit + etc - effective_rain))
    raw = p * taw
    needed = deficit >= raw
    net = max(0.0, deficit - target_deficit) if needed else 0.0
    gross = net / efficiency
    return dict(etc=round(etc, 6), deficit=round(deficit, 6), raw=round(raw, 6), needed=needed,
                net=round(net, 6), gross=round(gross, 6), volume=round(gross * area * 10, 6))

def crop_stage(crop, planting_date, day):
    age = (day - planting_date).days
    a, b, c, d = crop.days_initial, crop.days_development, crop.days_mid, crop.days_late
    if age < 0:
        return None, 'Посадка ещё не выполнена'
    if age < a:
        return crop.kc_initial, 'Начальная стадия'
    if age < a + b:
        return crop.kc_initial + (crop.kc_mid - crop.kc_initial) * (age - a) / b, 'Развитие'
    if age < a + b + c:
        return crop.kc_mid, 'Середина сезона'
    if age < a + b + c + d:
        return crop.kc_mid + (crop.kc_end - crop.kc_mid) * (age - a - b - c) / d, 'Созревание'
    return None, 'Расчётный сезон завершён'
