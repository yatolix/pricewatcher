import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.client.proxy import Proxy  # <-- для MTProto
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage

import db
from scraper import fetch_price

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------- Вспомогательная функция ----------
async def process_product_check(product) -> float | None:
    price = await fetch_price(product['url'])
    if price is None or price <= 0:
        return None

    await db.update_price(product['id'], price)
    target = product['target_price']
    notified = bool(product['notified'])

    if price <= target and not notified:
        try:
            await bot.send_message(
                product['user_id'],
                f"🎉 Цена упала!\nТовар: {product['url']}\n"
                f"Текущая цена: {price:.2f} руб (цель ≤ {target:.2f})"
            )
            await db.set_notified(product['id'], True)
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {product['user_id']}: {e}")
    elif price > target and notified:
        await db.set_notified(product['id'], False)

    return price


# ---------- Команды ----------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Бот отслеживания цен с ИИ (локальная LLM + Playwright).\n\n"
        "Команды:\n"
        "/add <ссылка> <желаемая цена> [интервал в минутах] — добавить товар\n"
        "/list — мои товары\n"
        "/delete <id> — удалить\n"
        "/set_interval <id> <минуты> — изменить интервал\n"
        "/check <id> — проверить цену сейчас"
    )


@dp.message(Command("add"))
async def cmd_add(message: Message):
    try:
        parts = message.text.split()
        if len(parts) < 3:
            raise ValueError
        url = parts[1]
        target = float(parts[2])
        interval = int(parts[3]) if len(parts) > 3 else 60
    except:
        await message.reply("❌ Формат: /add <ссылка> <желаемая цена> [интервал в мин]")
        return

    product_id = await db.add_product(message.from_user.id, url, target, interval)
    await message.reply(f"✅ Товар добавлен (ID {product_id}). Проверяю цену...")

    product = await db.get_product_by_id(product_id)
    price = await process_product_check(product)

    if price is not None:
        await message.reply(f"💰 Текущая цена: {price:.2f} руб.")
    else:
        await message.reply("⚠️ Не удалось определить цену. Попробуйте позже или измените интервал.")


@dp.message(Command("list"))
async def cmd_list(message: Message):
    products = await db.get_user_products(message.from_user.id)
    if not products:
        await message.reply("У вас нет отслеживаемых товаров.")
        return
    text = "📋 Ваши товары:\n\n"
    for p in products:
        last_price = f"{p['last_price']:.2f}" if p['last_price'] else "неизвестно"
        text += (
            f"ID: {p['id']}\n"
            f"Ссылка: {p['url']}\n"
            f"Цель: ≤ {p['target_price']} руб.\n"
            f"Интервал: {p['interval_minutes']} мин.\n"
            f"Последняя цена: {last_price}\n\n"
        )
    await message.reply(text)


@dp.message(Command("delete"))
async def cmd_delete(message: Message):
    try:
        product_id = int(message.text.split()[1])
    except:
        await message.reply("❌ Укажите ID: /delete <id>")
        return
    product = await db.get_product_by_id(product_id)
    if not product or product['user_id'] != message.from_user.id:
        await message.reply("❌ Товар не найден или не ваш.")
        return
    await db.delete_product(product_id)
    await message.reply(f"🗑 Товар {product_id} удалён.")


@dp.message(Command("set_interval"))
async def cmd_set_interval(message: Message):
    try:
        product_id = int(message.text.split()[1])
        minutes = int(message.text.split()[2])
    except:
        await message.reply("❌ Используйте: /set_interval <id> <минуты>")
        return
    product = await db.get_product_by_id(product_id)
    if not product or product['user_id'] != message.from_user.id:
        await message.reply("❌ Товар не найден или не ваш.")
        return
    await db.update_interval(product_id, minutes)
    await message.reply(f"⏱ Интервал для товара {product_id} изменён на {minutes} мин.")


@dp.message(Command("check"))
async def cmd_check(message: Message):
    try:
        product_id = int(message.text.split()[1])
    except:
        await message.reply("❌ Укажите ID: /check <id>")
        return
    product = await db.get_product_by_id(product_id)
    if not product or product['user_id'] != message.from_user.id:
        await message.reply("❌ Товар не найден.")
        return

    status_msg = await message.reply(f"🔎 Проверяю цену для товара {product_id}...")
    price = await process_product_check(product)

    if price is not None:
        await status_msg.edit_text(
            f"💰 Товар {product_id}: текущая цена {price:.2f} руб. "
            f"(цель ≤ {product['target_price']:.2f} руб.)"
        )
    else:
        await status_msg.edit_text("⚠️ Не удалось получить цену. Возможно, страница изменилась.")


# ---------- Фоновая проверка ----------
async def scheduler_loop():
    while True:
        try:
            products = await db.get_products_to_check()
            for product in products:
                asyncio.create_task(process_product_check(product))
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")
        await asyncio.sleep(10)


# ---------- Инициализация ----------
async def main():
    global bot, dp

    # MTProto-прокси для обхода блокировки Telegram
    # Параметры: host, port, secret (hex)
    proxy = Proxy(
        host="akkenai.top",      # адрес прокси
        port=853,                   # порт
        secret="ee54ce330e4690cc297d2b031ff3f288b06d742e616b656e61692e636c69636b"  # секрет
    )
    # Если прокси не нужен (например, вы не в РФ), можно закомментировать:
    # proxy = None

    session = None
    bot = Bot(token=BOT_TOKEN, proxy=proxy)
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем хендлеры (команды)
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_add, Command("add"))
    dp.message.register(cmd_list, Command("list"))
    dp.message.register(cmd_delete, Command("delete"))
    dp.message.register(cmd_set_interval, Command("set_interval"))
    dp.message.register(cmd_check, Command("check"))

    await db.init_db()
    asyncio.create_task(scheduler_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())