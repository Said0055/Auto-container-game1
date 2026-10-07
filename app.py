import hashlib
import hmac
import json
import os
import random
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "game.db")
STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Авто Контейнеры API", lifespan=lifespan)

RARITIES = {
    "Обычная": {"xp": 20, "index": 1, "color": "#9aa5b5"},
    "Необычная": {"xp": 45, "index": 2, "color": "#4bd27c"},
    "Эпическая": {"xp": 90, "index": 3, "color": "#a66bff"},
    "Легендарная": {"xp": 180, "index": 4, "color": "#ff9f43"},
    "Мифическая": {"xp": 350, "index": 5, "color": "#ff5261"},
}
RARITY_ORDER = list(RARITIES)

CARS = [
    {"name":"Lada 2107", "value":12000, "rarity":"Обычная", "c1":"#d9dee5", "c2":"#707983"},
    {"name":"ВАЗ 2114", "value":18000, "rarity":"Обычная", "c1":"#c7ccd2", "c2":"#68717c"},
    {"name":"Lada Priora", "value":24000, "rarity":"Обычная", "c1":"#9ea8b4", "c2":"#47515d"},
    {"name":"BMW E36", "value":42000, "rarity":"Необычная", "c1":"#8cc7ff", "c2":"#194b76"},
    {"name":"Mercedes W124", "value":65000, "rarity":"Необычная", "c1":"#e2e8ee", "c2":"#5a6572"},
    {"name":"BMW E46", "value":95000, "rarity":"Необычная", "c1":"#252c35", "c2":"#06080b"},
    {"name":"BMW M3 E46", "value":145000, "rarity":"Эпическая", "c1":"#60aaff", "c2":"#17477c"},
    {"name":"Nissan GT-R R35", "value":320000, "rarity":"Эпическая", "c1":"#ee4e5d", "c2":"#681822"},
    {"name":"Porsche 911 Turbo", "value":780000, "rarity":"Легендарная", "c1":"#f5f5f5", "c2":"#717780"},
    {"name":"Lamborghini Huracán", "value":1500000, "rarity":"Легендарная", "c1":"#ffe052", "c2":"#956100"},
    {"name":"Bugatti Chiron", "value":3500000, "rarity":"Мифическая", "c1":"#6fc7fa", "c2":"#153c65"},
    {"name":"Koenigsegg Jesko", "value":5200000, "rarity":"Мифическая", "c1":"#dadbe0", "c2":"#4a5058"},
]

CONTAINERS = {
    "standard": {"name":"Стандартный", "price":10000, "weights":[68,24,6,1.7,.3]},
    "premium": {"name":"Премиум", "price":25000, "weights":[43,34,16,6,.9]},
    "rare": {"name":"Редкий", "price":50000, "weights":[20,35,28,15,2]},
    "legend": {"name":"Легенда", "price":100000, "weights":[6,22,34,29,9]},
}


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(connect()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                first_name TEXT NOT NULL,
                coins INTEGER NOT NULL DEFAULT 100000,
                xp INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                value INTEGER NOT NULL,
                rarity TEXT NOT NULL,
                c1 TEXT NOT NULL,
                c2 TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES players(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cars_user ON cars(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transfers_sender ON transfers(sender_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transfers_receiver ON transfers(receiver_id)")
        conn.commit()


def register_user(user_id: int, username: str | None, first_name: str):
    normalized = username.lower().lstrip("@") if username else None
    with closing(connect()) as conn:
        conn.execute("""
            INSERT INTO players(user_id, username, first_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              username=excluded.username,
              first_name=excluded.first_name
        """, (user_id, normalized, first_name or "Игрок", int(time.time())))
        conn.commit()


def validate_init_data(init_data: str):
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN не задан")

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        auth_date = int(pairs.get("auth_date", "0"))
        if not received_hash:
            raise ValueError("hash missing")
        # Telegram recommends checking auth_date to avoid stale init data.
        if abs(int(time.time()) - auth_date) > 86400:
            raise ValueError("stale initData")

        data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret_key = hmac.new(
            b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        calc_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calc_hash, received_hash):
            raise ValueError("bad hash")

        if "user" not in pairs:
            raise ValueError("user missing")
        user = json.loads(pairs["user"])
        if "id" not in user:
            raise ValueError("user id missing")
        return user
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Неверная авторизация Telegram") from exc


def current_user(init_data: str):
    user = validate_init_data(init_data)
    user_id = int(user["id"])
    register_user(user_id, user.get("username"), user.get("first_name", "Игрок"))
    return user


def level_from_xp(xp: int) -> int:
    return xp // 500 + 1


def money(n: int) -> str:
    return f"{int(n):,}".replace(",", " ") + " ₽"


def weighted_car(container_key: str):
    container = CONTAINERS[container_key]
    rarity = random.choices(RARITY_ORDER, weights=container["weights"], k=1)[0]
    choices = [c for c in CARS if c["rarity"] == rarity]
    return random.choice(choices)


def public_car(row):
    return {
        "id": row["id"] if isinstance(row, sqlite3.Row) and "id" in row.keys() else None,
        "name": row["name"],
        "value": row["value"],
        "rarity": row["rarity"],
        "c1": row["c1"],
        "c2": row["c2"],
    }


class InitPayload(BaseModel):
    initData: str


class OpenPayload(BaseModel):
    initData: str
    container: str


class TransferPayload(BaseModel):
    initData: str
    username: str
    amount: int


class SellPayload(BaseModel):
    initData: str
    car_id: int


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {
        "containers": [
            {"key": k, "name": v["name"], "price": v["price"], "weights": v["weights"]}
            for k, v in CONTAINERS.items()
        ],
        "rarities": RARITIES,
    }


@app.post("/api/me")
def me(payload: InitPayload):
    user = current_user(payload.initData)
    with closing(connect()) as conn:
        p = conn.execute("SELECT * FROM players WHERE user_id=?", (user["id"],)).fetchone()
        cars = conn.execute(
            "SELECT id,name,value,rarity,c1,c2 FROM cars WHERE user_id=? ORDER BY id DESC",
            (user["id"],)
        ).fetchall()
    return {
        "player": {
            "id": p["user_id"],
            "username": p["username"],
            "first_name": p["first_name"],
            "coins": p["coins"],
            "xp": p["xp"],
            "level": level_from_xp(p["xp"]),
        },
        "cars": [public_car(c) for c in cars],
    }


@app.post("/api/open")
def open_container(payload: OpenPayload):
    user = current_user(payload.initData)
    container = CONTAINERS.get(payload.container)
    if not container:
        raise HTTPException(status_code=400, detail="Неизвестный контейнер")

    car = weighted_car(payload.container)
    xp_gain = RARITIES[car["rarity"]]["xp"]

    with closing(connect()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            player = conn.execute(
                "SELECT coins,xp FROM players WHERE user_id=?", (user["id"],)
            ).fetchone()
            if not player or player["coins"] < container["price"]:
                conn.rollback()
                raise HTTPException(status_code=400, detail="Недостаточно монет")

            conn.execute(
                "UPDATE players SET coins=coins-?, xp=xp+? WHERE user_id=?",
                (container["price"], xp_gain, user["id"])
            )
            cur = conn.execute("""
                INSERT INTO cars(user_id,name,value,rarity,c1,c2,created_at)
                VALUES(?,?,?,?,?,?,?)
            """, (user["id"], car["name"], car["value"], car["rarity"],
                  car["c1"], car["c2"], int(time.time())))
            car_id = cur.lastrowid
            conn.commit()
        except HTTPException:
            raise
        except Exception:
            conn.rollback()
            raise HTTPException(status_code=500, detail="Не удалось открыть контейнер")

        p = conn.execute("SELECT coins,xp FROM players WHERE user_id=?", (user["id"],)).fetchone()

    return {
        "car": {**car, "id": car_id},
        "coins": p["coins"],
        "xp": p["xp"],
        "level": level_from_xp(p["xp"]),
        "xp_gain": xp_gain,
    }


@app.post("/api/sell")
def sell(payload: SellPayload):
    user = current_user(payload.initData)
    with closing(connect()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT name,value FROM cars WHERE id=? AND user_id=?",
                (payload.car_id, user["id"])
            ).fetchone()
            if not row:
                conn.rollback()
                raise HTTPException(status_code=404, detail="Машина не найдена")
            price = int(row["value"] * 0.70)
            conn.execute("DELETE FROM cars WHERE id=? AND user_id=?", (payload.car_id, user["id"]))
            conn.execute("UPDATE players SET coins=coins+? WHERE user_id=?", (price, user["id"]))
            conn.commit()
        except HTTPException:
            raise
        except Exception:
            conn.rollback()
            raise HTTPException(status_code=500, detail="Не удалось продать машину")
        p = conn.execute("SELECT coins FROM players WHERE user_id=?", (user["id"],)).fetchone()
    return {"ok": True, "sold": row["name"], "coins": p["coins"], "price": price}


@app.post("/api/transfer")
def transfer(payload: TransferPayload):
    user = current_user(payload.initData)
    username = payload.username.strip().lstrip("@").lower()

    if not username or payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Укажи корректные ник и сумму")
    if len(username) > 32:
        raise HTTPException(status_code=400, detail="Некорректный ник")
    if payload.amount > 10_000_000:
        raise HTTPException(status_code=400, detail="Слишком большая сумма")

    with closing(connect()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            sender = conn.execute(
                "SELECT coins,first_name FROM players WHERE user_id=?", (user["id"],)
            ).fetchone()
            receiver = conn.execute(
                "SELECT user_id,first_name,username FROM players WHERE username=?",
                (username,)
            ).fetchone()

            if not receiver:
                conn.rollback()
                raise HTTPException(
                    status_code=404,
                    detail="Игрок не найден. Получатель должен сначала открыть бота и нажать /start."
                )
            if receiver["user_id"] == user["id"]:
                conn.rollback()
                raise HTTPException(status_code=400, detail="Нельзя переводить монеты самому себе")
            if sender["coins"] < payload.amount:
                conn.rollback()
                raise HTTPException(status_code=400, detail="Недостаточно монет")

            conn.execute(
                "UPDATE players SET coins=coins-? WHERE user_id=?",
                (payload.amount, user["id"])
            )
            conn.execute(
                "UPDATE players SET coins=coins+? WHERE user_id=?",
                (payload.amount, receiver["user_id"])
            )
            conn.execute("""
                INSERT INTO transfers(sender_id,receiver_id,amount,created_at)
                VALUES(?,?,?,?)
            """, (user["id"], receiver["user_id"], payload.amount, int(time.time())))
            conn.commit()
        except HTTPException:
            raise
        except Exception:
            conn.rollback()
            raise HTTPException(status_code=500, detail="Перевод не выполнен")

        sender_after = conn.execute(
            "SELECT coins FROM players WHERE user_id=?", (user["id"],)
        ).fetchone()

    return {
        "ok": True,
        "receiver": receiver["first_name"],
        "amount": payload.amount,
        "coins": sender_after["coins"],
    }


def transfer_coins_cli(sender_id: int, username: str, amount: int):
    username = username.strip().lstrip("@").lower()
    if not username or amount <= 0:
        raise ValueError("Укажи корректные ник и сумму.")
    with closing(connect()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            sender = conn.execute(
                "SELECT coins FROM players WHERE user_id=?", (sender_id,)
            ).fetchone()
            receiver = conn.execute(
                "SELECT user_id,first_name FROM players WHERE username=?",
                (username,)
            ).fetchone()
            if not receiver:
                conn.rollback()
                raise ValueError(
                    "Игрок не найден. Получатель должен сначала открыть бота и нажать /start."
                )
            if receiver["user_id"] == sender_id:
                conn.rollback()
                raise ValueError("Нельзя переводить монеты самому себе.")
            if sender["coins"] < amount:
                conn.rollback()
                raise ValueError("Недостаточно монет.")
            conn.execute("UPDATE players SET coins=coins-? WHERE user_id=?", (amount, sender_id))
            conn.execute("UPDATE players SET coins=coins+? WHERE user_id=?", (amount, receiver["user_id"]))
            conn.execute(
                "INSERT INTO transfers(sender_id,receiver_id,amount,created_at) VALUES(?,?,?,?)",
                (sender_id, receiver["user_id"], amount, int(time.time()))
            )
            conn.commit()
            return receiver["first_name"], amount
        except ValueError:
            raise
        except Exception as exc:
            conn.rollback()
            raise ValueError("Перевод не выполнен.") from exc
