"""Проверка, что сид лёг и паттерны трафика видны.

Запуск (из backend/):  python check_seed.py

Печатает:
  - счётчики строк по всем таблицам
  - распределение заявок/броней по статусам
  - тепловую ASCII-карту средней загрузки порта Актау (час × день недели):
    видно дневной пик и спад ночь/вс
  - топ дней по суммарному трафику — там должны торчать аномальные дни
  - годовую экстраполяцию тоннажа порта (калибровка ~12 млн т)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Assignment,
    Booking,
    CargoRequest,
    Checkpoint,
    Slot,
    TrafficHistory,
    User,
)

AVG_TONNAGE = {"container": 20.0, "bulk": 26.0, "liquid": 28.0, "general": 15.0}
DOW_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
BLOCKS = " .:-=+*#%@"  # градации загрузки для ASCII-карты


def _counts(db: Session) -> None:
    print("\n=== Счётчики таблиц ===")
    for model in (User, Checkpoint, TrafficHistory, CargoRequest, Assignment, Slot, Booking):
        n = db.scalar(select(func.count()).select_from(model))
        print(f"  {model.__tablename__:<18} {n:>8}")


def _status_breakdown(db: Session) -> None:
    print("\n=== Заявки по статусам ===")
    rows = db.execute(
        select(CargoRequest.status, func.count()).group_by(CargoRequest.status)
    ).all()
    for status, n in sorted(rows, key=lambda r: str(r[0])):
        print(f"  {status.value:<12} {n:>4}")

    print("\n=== Брони по статусам ===")
    rows = db.execute(select(Booking.status, func.count()).group_by(Booking.status)).all()
    for status, n in sorted(rows, key=lambda r: str(r[0])):
        print(f"  {status.value:<12} {n:>4}")


def _heatmap(db: Session) -> None:
    port = db.scalar(select(Checkpoint).where(Checkpoint.name.like("Порт Актау%")))
    if not port:
        print("\n(порт Актау не найден — пропуск тепловой карты)")
        return

    # Средний trucks_count по (день недели, час). dow: 0=вс в SQL → приведём.
    dow = func.extract("dow", TrafficHistory.ts)   # 0=вс..6=сб (Postgres)
    hour = func.extract("hour", TrafficHistory.ts)
    rows = db.execute(
        select(dow, hour, func.sum(TrafficHistory.trucks_count))
        .where(TrafficHistory.checkpoint_id == port.id)
        .group_by(dow, hour)
    ).all()

    # grid[py_dow][hour] = суммарный трафик; усредним на число недель (~13).
    grid = [[0.0] * 24 for _ in range(7)]
    for d, h, s in rows:
        py_dow = (int(d) - 1) % 7  # Postgres 0=вс → python 0=пн
        grid[py_dow][int(h)] += float(s)

    flat = [v for row in grid for v in row if v > 0]
    if not flat:
        print("\n(нет данных трафика — пропуск карты)")
        return
    vmax = max(flat)

    print("\n=== Загрузка порта Актау: час × день недели (темнее = больше фур) ===")
    # Ось часов: десятки сверху, единицы снизу.
    print("  hh   " + "".join(str(h // 10) if h % 2 == 0 else " " for h in range(24)))
    print("       " + "".join(str(h % 10) for h in range(24)))
    for py_dow in range(7):
        line = ""
        for h in range(24):
            v = grid[py_dow][h]
            idx = int((v / vmax) * (len(BLOCKS) - 1)) if vmax else 0
            line += BLOCKS[idx]
        print(f"  {DOW_NAMES[py_dow]}  {line}")
    print("  (пик днём пн-чт, спад ночью и в Вс — паттерн раздела 6)")


def _top_days(db: Session) -> None:
    day = func.date(TrafficHistory.ts)
    rows = db.execute(
        select(day, func.sum(TrafficHistory.trucks_count).label("t"))
        .group_by(day)
        .order_by(func.sum(TrafficHistory.trucks_count).desc())
    ).all()
    if not rows:
        return
    print("\n=== Топ-5 дней по трафику (всплески = аномалии) ===")
    for d, t in rows[:5]:
        print(f"  {d}  {int(t):>7} фур")
    print("=== Анти-топ-5 (обвалы) ===")
    for d, t in rows[-5:]:
        print(f"  {d}  {int(t):>7} фур")


def _port_tonnage(db: Session) -> None:
    port = db.scalar(select(Checkpoint).where(Checkpoint.name.like("Порт Актау%")))
    if not port:
        return
    rows = db.execute(
        select(TrafficHistory.cargo_type, func.sum(TrafficHistory.trucks_count))
        .where(TrafficHistory.checkpoint_id == port.id)
        .group_by(TrafficHistory.cargo_type)
    ).all()
    days_span = db.scalar(
        select(func.count(func.distinct(func.date(TrafficHistory.ts))))
        .where(TrafficHistory.checkpoint_id == port.id)
    ) or 1
    total_t = sum(float(n) * AVG_TONNAGE[ct.value] for ct, n in rows)
    annual = total_t * (365.0 / days_span)
    print("\n=== Калибровка порта Актау ===")
    print(f"  тоннаж за {days_span} дн.: {total_t/1e6:.2f} млн т")
    print(f"  годовая экстраполяция:   {annual/1e6:.2f} млн т  (цель ~12 млн т)")


def main() -> None:
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(TrafficHistory))
        if not total:
            print("БД пуста — сначала запусти: python seed.py")
            return
        _counts(db)
        _status_breakdown(db)
        _heatmap(db)
        _top_days(db)
        _port_tonnage(db)
    print("\nОК: данные на месте, паттерны видны.")


if __name__ == "__main__":
    main()
