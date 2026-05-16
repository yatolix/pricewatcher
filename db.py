import aiosqlite
import asyncio
from datetime import datetime

DB_PATH = "data/products.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                target_price REAL NOT NULL,
                interval_minutes INTEGER DEFAULT 60,
                last_checked REAL DEFAULT 0,
                last_price REAL,
                notified INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        ''')
        await db.commit()

async def add_product(user_id, url, target_price, interval_minutes=60):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO products (user_id, url, target_price, interval_minutes) VALUES (?, ?, ?, ?)",
            (user_id, url, target_price, interval_minutes)
        )
        await db.commit()
        return cursor.lastrowid

async def get_user_products(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM products WHERE user_id=? AND is_active=1 ORDER BY id",
            (user_id,)
        )
        return await cursor.fetchall()

async def get_product_by_id(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM products WHERE id=?", (product_id,))
        return await cursor.fetchone()

async def delete_product(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE id=?", (product_id,))
        await db.commit()

async def update_interval(product_id, minutes):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE products SET interval_minutes=? WHERE id=?", (minutes, product_id))
        await db.commit()

async def update_price(product_id, price):
    now = datetime.now().timestamp()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE products SET last_price=?, last_checked=? WHERE id=?",
            (price, now, product_id)
        )
        await db.commit()

async def set_notified(product_id, flag: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE products SET notified=? WHERE id=?", (int(flag), product_id))
        await db.commit()

async def get_products_to_check():
    """Возвращает активные товары, у которых подошло время проверки."""
    now = datetime.now().timestamp()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM products WHERE is_active=1 AND (? - last_checked) >= (interval_minutes * 60)",
            (now,)
        )
        return await cursor.fetchall()