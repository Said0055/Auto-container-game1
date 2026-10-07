import asyncio
import os

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo, Message

from app import register_user, init_db, transfer_coins_cli

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚗 ИГРАТЬ",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [InlineKeyboardButton(text="💸 Как перевести ₽", callback_data="transfer_help")],
    ])
    await message.answer(
        "🚗 <b>АВТО КОНТЕЙНЕРЫ</b>\n\n"
        "Твой стартовый баланс — <b>100 000 ₽</b>.\n"
        "Открывай контейнеры, собирай машины и прокачивай уровень.",
        reply_markup=kb
    )


@router.message(Command("send"))
async def send_cmd(message: Message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name)
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Формат: <code>/send @username 5000</code>")
        return
    try:
        amount = int(parts[2])
    except ValueError:
        await message.answer("Сумма должна быть целым числом.")
        return
    try:
        receiver_name, sent = transfer_coins_cli(user.id, parts[1], amount)
        await message.answer(
            f"✅ Перевод выполнен.\n"
            f"Получатель: <b>{receiver_name}</b>\n"
            f"Сумма: <b>{sent:,} ₽</b>".replace(",", " ")
        )
    except ValueError as e:
        await message.answer("❌ " + str(e))


@router.callback_query(F.data == "transfer_help")
async def transfer_help(call):
    await call.answer()
    await call.message.answer(
        "💸 Передача валюты:\n\n"
        "<code>/send @username 5000</code>\n\n"
        "Получатель должен сначала открыть бота и нажать /start."
    )


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")
    if not WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL не задан")

    init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Играть",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
