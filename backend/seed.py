"""Генератор синтетики (раздел 6 спеки). Идемпотентный.

Запуск (из папки backend/):  python seed.py
Требует доступной БД по DATABASE_URL.

Создаёт:
  - 5 реальных узлов Мангистау (раздел 3)
  - 3 демо-аккаунта + 25-30 перевозчиков + 12-15 отправителей
  - 90 дней почасовой traffic_history с реалистичными паттернами
    (пик пн-чт днём, спад ночь/вс, Актау самый загруженный,
     недельная сезонность + шум ±20%, 3-4 аномальных дня),
    объёмы откалиброваны на ~12 млн т/год через порт Актау
  - 60-80 заявок в разных статусах + назначения перевозчикам
  - 15-20 активных броней с QR
  - слоты на 7 дней вперёд по часу для всех узлов

Идемпотентность: каждый блок проверяет наличие данных и не дублирует.
RNG детерминирован (random.seed), поэтому первый прогон воспроизводим.
"""
from __future__ import annotations

import random
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

# Чтобы `import app...` работал при запуске `python seed.py` из любой папки.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.db import SessionLocal, init_db
from app.models import (
    Assignment,
    Booking,
    BookingStatus,
    CargoRequest,
    CargoType,
    Checkpoint,
    CheckpointKind,
    Direction,
    RequestStatus,
    Slot,
    TrafficHistory,
    User,
    UserRole,
)

RNG_SEED = 20260610
HISTORY_DAYS = 90
SLOT_DAYS_AHEAD = 7
SLOT_HOUR_START = 6   # слоты с 06:00
SLOT_HOUR_END = 22    # до 22:00 (последний слот 21:00-22:00)
PORT_ANNUAL_TARGET_T = 12_000_000  # публичная цифра для калибровки порта Актау

DEMO_PASSWORD = "demo123"

# Средний тоннаж на одну фуру по типу груза — для калибровки на 12 млн т/год.
AVG_TONNAGE = {
    CargoType.container: 20.0,
    CargoType.bulk: 26.0,
    CargoType.liquid: 28.0,
    CargoType.general: 15.0,
}


# ---------------------------------------------------------------------------
# Справочные данные
# ---------------------------------------------------------------------------
CHECKPOINTS = [
    # (name, kind, lat, lng, capacity_per_hour, base_peak_trucks)
    ("Порт Актау", CheckpointKind.sea_port, 43.621000, 51.157000, 40, 50),
    ("Порт Курык", CheckpointKind.sea_port, 42.760000, 52.880000, 30, 30),
    ("Погранпереход «Темир-Баба»", CheckpointKind.road_border, 41.550000, 52.580000, 25, 22),
    ("Ж/д переход «Болашак»", CheckpointKind.rail_border, 41.770000, 52.950000, 20, 16),
    ("Узел Бейнеу (трасса Актау–Бейнеу)", CheckpointKind.road_hub, 45.316000, 55.197000, 35, 35),
]

# Доли типов груза по узлам (раскладка для breakdown-аналитики).
CARGO_MIX = {
    "Порт Актау": {CargoType.container: 0.40, CargoType.bulk: 0.25, CargoType.liquid: 0.20, CargoType.general: 0.15},
    "Порт Курык": {CargoType.container: 0.35, CargoType.general: 0.30, CargoType.bulk: 0.20, CargoType.liquid: 0.15},
    "Погранпереход «Темир-Баба»": {CargoType.general: 0.40, CargoType.container: 0.30, CargoType.bulk: 0.20, CargoType.liquid: 0.10},
    "Ж/д переход «Болашак»": {CargoType.bulk: 0.40, CargoType.liquid: 0.30, CargoType.container: 0.20, CargoType.general: 0.10},
    "Узел Бейнеу (трасса Актау–Бейнеу)": {CargoType.general: 0.35, CargoType.container: 0.30, CargoType.bulk: 0.25, CargoType.liquid: 0.10},
}

DIRECTION_MIX = [(Direction.export, 0.45), (Direction.import_, 0.35), (Direction.transit, 0.20)]

# Суточный профиль (24 ч): спад ночью, пик днём.
HOUR_FACTOR = [
    0.15, 0.12, 0.10, 0.10, 0.14, 0.25,  # 00-05
    0.45, 0.65, 0.85, 0.95, 1.00, 1.00,  # 06-11
    0.95, 0.92, 0.98, 0.95, 0.80, 0.62,  # 12-17
    0.50, 0.40, 0.32, 0.26, 0.20, 0.16,  # 18-23
]

# Профиль по дням недели (0=пн): пик пн-чт, спад вс.
DOW_FACTOR = {0: 1.00, 1: 1.00, 2: 0.98, 3: 0.95, 4: 0.85, 5: 0.60, 6: 0.40}

COMPANY_PREFIX = [
    "Каспий", "Мангистау", "Актау", "Бейнеу", "Тенгиз", "Жайык", "Арал",
    "Шевченко", "Адай", "Устюрт", "Жетыбай", "Курык", "Сай-Утес", "Форт",
]
COMPANY_SUFFIX = ["Транс", "Логистик", "Лоджистикс", "Карго", "Экспедиция", "Сервис", "Трейд"]
PERSON_NAMES = [
    "Айдар Нурланов", "Бекзат Сериков", "Гульнара Ахметова", "Данияр Калиев",
    "Ержан Сапаров", "Жанна Оразбаева", "Кайрат Дюсенов", "লаура Бекова",
    "Марат Жумабеков", "Нуржан Тулегенов", "Оразбек Кенжебаев", "Перизат Алиева",
    "Руслан Ибрагимов", "Самал Нургалиева", "Талгат Усенов", "Улан Сейтказы",
    "Фарида Конысбаева", "Хасен Молдагалиев", "Чингиз Абенов", "Шынар Досанова",
    "Айгерим Косанова", "Бауыржан Ермеков", "Динара Сулейменова", "Елдос Каиргельдин",
    "Жанибек Турлыбеков", "Канат Оспанов", "Лязат Жаксыбекова", "Медет Айтжанов",
    "Назгуль Бектурова", "Олжас Сагынбаев",
]
PLACES = [
    "Актау", "Бейнеу", "Жанаозен", "Форт-Шевченко", "Курык", "Жетыбай",
    "Шетпе", "Сай-Утес", "Мунайлы", "Таучик", "Атырау", "Бейнеу-Порт",
]
PLATE_LETTERS = "ABCEHKMOPTXY"  # латиница, как на казахских номерах


def _company() -> str:
    form = random.choice(["ТОО", "ИП", "ТОО"])
    return f'{form} «{random.choice(COMPANY_PREFIX)}{random.choice(COMPANY_SUFFIX)}»'


def _plate() -> str:
    digits = random.randint(100, 999)
    letters = "".join(random.choice(PLATE_LETTERS) for _ in range(3))
    return f"{digits} {letters} 12"  # 12 — регион Мангистау


# ---------------------------------------------------------------------------
# get-or-create helpers (идемпотентность)
# ---------------------------------------------------------------------------
def get_or_create_user(db: Session, email: str, **kwargs) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(email=email, **kwargs)
    db.add(user)
    db.flush()
    return user


def get_or_create_checkpoint(db: Session, name: str, **kwargs) -> Checkpoint:
    cp = db.scalar(select(Checkpoint).where(Checkpoint.name == name))
    if cp:
        return cp
    cp = Checkpoint(name=name, **kwargs)
    db.add(cp)
    db.flush()
    return cp


# ---------------------------------------------------------------------------
# Блоки сидирования
# ---------------------------------------------------------------------------
def seed_checkpoints(db: Session) -> dict[str, Checkpoint]:
    result: dict[str, Checkpoint] = {}
    for name, kind, lat, lng, cap, _base in CHECKPOINTS:
        result[name] = get_or_create_checkpoint(
            db, name, kind=kind, lat=lat, lng=lng, capacity_per_hour=cap
        )
    db.commit()
    return result


def seed_users(db: Session) -> dict[str, list[User]]:
    # Демо-аккаунты (раздел 4): shipper@demo / carrier@demo / analyst@demo, пароль demo123.
    demo = [
        ("shipper@demo", "Демо Отправитель", UserRole.shipper, "ТОО «Каспий Логистик»"),
        ("carrier@demo", "Демо Перевозчик", UserRole.carrier, "ИП «Адай Транс»"),
        ("analyst@demo", "Демо Аналитик акимата", UserRole.analyst, "Акимат Мангистауской области"),
    ]
    for email, name, role, company in demo:
        get_or_create_user(
            db, email, name=name, role=role, company=company,
            password_hash=hash_password(DEMO_PASSWORD),
        )

    shippers: list[User] = []
    carriers: list[User] = []

    n_shippers = random.randint(12, 15)
    n_carriers = random.randint(25, 30)

    for i in range(n_shippers):
        email = f"shipper{i+1}@transit.kz"
        u = get_or_create_user(
            db, email, name=random.choice(PERSON_NAMES), role=UserRole.shipper,
            company=_company(), password_hash=hash_password(DEMO_PASSWORD),
        )
        shippers.append(u)

    for i in range(n_carriers):
        email = f"carrier{i+1}@transit.kz"
        u = get_or_create_user(
            db, email, name=random.choice(PERSON_NAMES), role=UserRole.carrier,
            company=_company(), password_hash=hash_password(DEMO_PASSWORD),
        )
        carriers.append(u)

    db.commit()

    # Демо-отправитель/перевозчик тоже участвуют в заявках.
    demo_shipper = db.scalar(select(User).where(User.email == "shipper@demo"))
    demo_carrier = db.scalar(select(User).where(User.email == "carrier@demo"))
    if demo_shipper:
        shippers.append(demo_shipper)
    if demo_carrier:
        carriers.append(demo_carrier)

    return {"shippers": shippers, "carriers": carriers}


def _weighted_direction() -> Direction:
    r = random.random()
    acc = 0.0
    for d, w in DIRECTION_MIX:
        acc += w
        if r <= acc:
            return d
    return Direction.transit


def seed_traffic(db: Session, checkpoints: dict[str, Checkpoint]) -> None:
    existing = db.scalar(select(func.count()).select_from(TrafficHistory))
    if existing:
        print(f"  traffic_history уже содержит {existing} строк — пропуск генерации.")
        return

    base_peak = {name: bp for name, _k, _la, _ln, _c, bp in CHECKPOINTS}

    today = datetime.now(timezone.utc).date()
    start_day = today - timedelta(days=HISTORY_DAYS)

    # Аномальные дни (раздел 6): 3-4 дня всплеск/обвал — их найдёт AI-сводка.
    anomaly_pool = list(range(10, HISTORY_DAYS - 5))
    anomaly_days = sorted(random.sample(anomaly_pool, k=random.randint(3, 4)))
    anomalies: dict[int, float] = {}
    for d in anomaly_days:
        anomalies[d] = random.choice([2.4, 2.2, 0.30, 0.35])

    # --- Пасс 1: сырые значения (float) ---
    # raw[(cp_name, day_idx, hour)] = trucks_float
    raw: dict[tuple[str, int, int], float] = {}
    for name in checkpoints:
        peak = base_peak[name]
        for day_idx in range(HISTORY_DAYS):
            d = start_day + timedelta(days=day_idx)
            dow = d.weekday()
            dow_f = DOW_FACTOR[dow]
            trend = 0.90 + 0.20 * (day_idx / (HISTORY_DAYS - 1))  # лёгкий рост за 90 дней
            anomaly_f = anomalies.get(day_idx, 1.0)
            for hour in range(24):
                noise = random.uniform(0.80, 1.20)  # шум ±20%
                val = peak * HOUR_FACTOR[hour] * dow_f * trend * noise * anomaly_f
                raw[(name, day_idx, hour)] = val

    # --- Калибровка по порту Актау на ~12 млн т/год ---
    port = "Порт Актау"
    port_mix = CARGO_MIX[port]
    port_t_90 = 0.0
    for day_idx in range(HISTORY_DAYS):
        for hour in range(24):
            trucks = raw[(port, day_idx, hour)]
            for cargo, w in port_mix.items():
                port_t_90 += trucks * w * AVG_TONNAGE[cargo]
    annual_est = port_t_90 * (365.0 / HISTORY_DAYS)
    scale = PORT_ANNUAL_TARGET_T / annual_est if annual_est > 0 else 1.0

    # --- Пасс 2: масштабируем, раскладываем по типам груза, пишем строки ---
    rows: list[TrafficHistory] = []
    for name, cp in checkpoints.items():
        mix = CARGO_MIX[name]
        for day_idx in range(HISTORY_DAYS):
            d = start_day + timedelta(days=day_idx)
            for hour in range(24):
                total = raw[(name, day_idx, hour)] * scale
                ts = datetime.combine(d, time(hour=hour), tzinfo=timezone.utc)
                for cargo, w in mix.items():
                    count = int(round(total * w))
                    if count <= 0:
                        continue
                    rows.append(TrafficHistory(
                        checkpoint_id=cp.id,
                        ts=ts,
                        trucks_count=count,
                        cargo_type=cargo,
                        direction=_weighted_direction(),
                    ))

    db.bulk_save_objects(rows)
    db.commit()
    print(f"  traffic_history: {len(rows)} строк, scale={scale:.3f}, "
          f"аномальные дни (idx)={anomaly_days}")


def seed_requests(db: Session, users: dict[str, list[User]], checkpoints: dict[str, Checkpoint]) -> None:
    existing = db.scalar(select(func.count()).select_from(CargoRequest))
    if existing:
        print(f"  cargo_requests уже содержит {existing} строк — пропуск.")
        return

    shippers = users["shippers"]
    carriers = users["carriers"]
    cp_list = list(checkpoints.values())

    n_requests = random.randint(60, 80)
    # Распределение статусов (раздел 6: заявки в разных статусах).
    status_weights = [
        (RequestStatus.open, 0.30),
        (RequestStatus.accepted, 0.20),
        (RequestStatus.slot_booked, 0.25),
        (RequestStatus.done, 0.20),
        (RequestStatus.cancelled, 0.05),
    ]

    today = datetime.now(timezone.utc).date()
    booked_assignments: list[Assignment] = []

    for _ in range(n_requests):
        shipper = random.choice(shippers)
        cargo = random.choice(list(CargoType))
        weight = round(random.uniform(5, 30), 1)
        origin, dest = random.sample(PLACES, 2)

        r = random.random()
        acc = 0.0
        status = RequestStatus.open
        for st, w in status_weights:
            acc += w
            if r <= acc:
                status = st
                break

        # desired_date: открытые/принятые — в будущем, done/cancelled — в прошлом.
        if status in (RequestStatus.done, RequestStatus.cancelled):
            desired = today - timedelta(days=random.randint(1, 25))
            created = datetime.combine(desired, time(8), tzinfo=timezone.utc) - timedelta(days=random.randint(1, 5))
        else:
            desired = today + timedelta(days=random.randint(0, 6))
            created = datetime.now(timezone.utc) - timedelta(days=random.randint(0, 10))

        req = CargoRequest(
            shipper_id=shipper.id, cargo_type=cargo, weight_t=weight,
            origin=origin, destination=dest, desired_date=desired,
            status=status, created_at=created,
        )
        db.add(req)
        db.flush()

        # Назначение перевозчику для accepted/slot_booked/done.
        if status in (RequestStatus.accepted, RequestStatus.slot_booked, RequestStatus.done):
            carrier = random.choice(carriers)
            asg = Assignment(
                request_id=req.id, carrier_id=carrier.id, truck_plate=_plate(),
                accepted_at=created + timedelta(hours=random.randint(1, 24)),
            )
            db.add(asg)
            db.flush()
            if status in (RequestStatus.slot_booked, RequestStatus.done):
                booked_assignments.append(asg)

    db.commit()
    print(f"  cargo_requests: {n_requests} шт; назначений под бронь: {len(booked_assignments)}")
    # Бронируем подмножество (15-20 активных броней) на будущих слотах.
    _seed_bookings(db, booked_assignments, checkpoints)


def seed_slots(db: Session, checkpoints: dict[str, Checkpoint]) -> None:
    existing = db.scalar(select(func.count()).select_from(Slot))
    if existing:
        print(f"  slots уже содержит {existing} строк — пропуск.")
        return

    today = datetime.now(timezone.utc).date()
    rows: list[Slot] = []
    for cp in checkpoints.values():
        for day_off in range(SLOT_DAYS_AHEAD):
            d = today + timedelta(days=day_off)
            for hour in range(SLOT_HOUR_START, SLOT_HOUR_END):
                starts = datetime.combine(d, time(hour=hour), tzinfo=timezone.utc)
                rows.append(Slot(
                    checkpoint_id=cp.id,
                    starts_at=starts,
                    ends_at=starts + timedelta(hours=1),
                    capacity=cp.capacity_per_hour,
                    booked_count=0,
                ))
    db.bulk_save_objects(rows)
    db.commit()
    print(f"  slots: {len(rows)} шт (на {SLOT_DAYS_AHEAD} дней вперёд, {SLOT_HOUR_START}:00-{SLOT_HOUR_END}:00)")


def _seed_bookings(db: Session, assignments: list[Assignment], checkpoints: dict[str, Checkpoint]) -> None:
    existing = db.scalar(select(func.count()).select_from(Booking))
    if existing:
        print(f"  bookings уже содержит {existing} строк — пропуск.")
        return

    # Берём будущие слоты с запасом ёмкости.
    future_slots = list(db.scalars(
        select(Slot).where(Slot.booked_count < Slot.capacity).order_by(Slot.starts_at)
    ))
    if not future_slots:
        print("  bookings: нет доступных слотов (сначала seed_slots) — пропуск.")
        return

    n_target = min(len(assignments), random.randint(15, 20))
    chosen = random.sample(assignments, n_target) if len(assignments) >= n_target else assignments

    status_pool = ([BookingStatus.booked] * 6) + [BookingStatus.arrived, BookingStatus.passed]
    created = 0
    for asg in chosen:
        slot = random.choice(future_slots)
        if slot.booked_count >= slot.capacity:
            continue
        b = Booking(
            slot_id=slot.id, assignment_id=asg.id,
            qr_token=uuid.uuid4(), status=random.choice(status_pool),
        )
        slot.booked_count += 1
        db.add(b)
        created += 1
    db.commit()
    print(f"  bookings: {created} активных броней с QR")


def main() -> None:
    random.seed(RNG_SEED)
    init_db()
    print("Сидирование TransitFlow…")
    with SessionLocal() as db:
        checkpoints = seed_checkpoints(db)
        print(f"  checkpoints: {len(checkpoints)} узлов")
        users = seed_users(db)
        print(f"  users: {len(users['shippers'])} отправителей + {len(users['carriers'])} перевозчиков (+3 демо)")
        seed_traffic(db, checkpoints)
        seed_slots(db, checkpoints)
        seed_requests(db, users, checkpoints)
    print("Готово.")


if __name__ == "__main__":
    main()
