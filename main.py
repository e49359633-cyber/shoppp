import asyncio
import logging
import sys
from decimal import Decimal

# Импорты библиотек
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import asyncpg
from aiocryptopay import AioCryptoPay  # <-- ИСПРАВЛЕНО ЗДЕСЬ

# --- НАСТРОЙКИ ---
API_TOKEN = '8717755678:AAFxBTzyDghHPLYOstlvkeNsUjgBStP3KHg'
CRYPTO_TOKEN = '552977:AAfr4bS9CTvhbqVU9s27CKLM3Ljjr6wrfLF'
ADMIN_IDS = [8209617821, 8384467554] 
DATABASE_URL = 'postgresql://bothost_db_29f14895d3aa:tbdVGmS3JoNrcauznAFgzNTJgefFJE3xE33flLLZY5M@node1.pghost.ru:32854/bothost_db_29f14895d3aa'
ADMIN_USERNAME = 'ramaz666'
ACC_PRICE = Decimal('0.20') 

# Инициализация
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
crypto = AioCryptoPay(token=CRYPTO_TOKEN, network='mainnet')  # <-- ИСПРАВЛЕНО ЗДЕСЬ

class ShopStates(StatesGroup):
    adding_accounts = State()
    waiting_for_amount = State()

db_pool = None

async def get_db_pool():
    global db_pool
    if db_pool is None:
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
            logging.info("✅ Успешное подключение к базе данных")
        except Exception as e:
            logging.error(f"❌ Ошибка подключения к базе: {e}")
            sys.exit(1)
    return db_pool

async def get_user_balance(user_id):
    pool = await get_db_pool()
    val = await pool.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)
    if val is None:
        await pool.execute("INSERT INTO users (user_id, balance) VALUES ($1, 0.00) ON CONFLICT DO NOTHING", user_id)
        return Decimal('0.00')
    return Decimal(str(val))

def main_kb(user_id):
    kb = [
        [types.KeyboardButton(text="🛒 Купить аккаунт")],
        [types.KeyboardButton(text="📊 Наличие"), types.KeyboardButton(text="💎 Баланс")],
        [types.KeyboardButton(text="🆘 Поддержка")]
    ]
    if user_id in ADMIN_IDS:
        kb.append([types.KeyboardButton(text="➕ Добавить базу")])
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    welcome_text = (
        "🤖 <b>Система инициализирована...</b>\n\n"
        "Добро пожаловать в магазин аккаунтов.\n"
        f"💳 Цена за 1 шт: <b>{ACC_PRICE} $</b>\n"
        f"👤 Ваш ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(welcome_text, reply_markup=main_kb(message.from_user.id), parse_mode="HTML")

@dp.message(F.text == "💎 Баланс")
async def balance_menu(message: types.Message):
    balance = await get_user_balance(message.from_user.id)
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💵 Пополнить баланс", callback_data="deposit")]
    ])
    await message.answer(f"💰 Ваш баланс: <b>{balance:.2f} $</b>", reply_markup=builder, parse_mode="HTML")

@dp.callback_query(F.data == "deposit")
async def deposit_step1(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ShopStates.waiting_for_amount)
    await callback.message.answer("⌨️ Введите сумму в $ (например 1.5):")
    await callback.answer()

@dp.message(ShopStates.waiting_for_amount)
async def deposit_step2(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        invoice = await crypto.create_invoice(asset='USDT', amount=amount)
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔗 Оплатить", url=invoice.pay_url)],
            [types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{invoice.invoice_id}_{amount}")]
        ])
        await message.answer(f"🚀 Счет на {amount} $ создан!", reply_markup=builder)
        await state.clear()
    except Exception as e:
        logging.error(f"Ошибка создания счета: {e}")
        await message.answer("❌ Ошибка! Введите число.")

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    _, inv_id, amount = callback.data.split("_")
    invoices = await crypto.get_invoices(invoice_ids=inv_id)
    if invoices and invoices[0].status == 'paid':
        pool = await get_db_pool()
        await pool.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", Decimal(amount), callback.from_user.id)
        await callback.message.edit_text(f"✅ Зачислено {amount} $!")
    else:
        await callback.answer("⚠️ Оплата не найдена.", show_alert=True)

@dp.message(F.text == "🛒 Купить аккаунт")
async def buy_account(message: types.Message):
    user_id = message.from_user.id
    balance = await get_user_balance(user_id)
    if balance < ACC_PRICE:
        await message.answer(f"❌ Недостаточно средств. Нужно {ACC_PRICE} $")
        return

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("DELETE FROM accounts WHERE id = (SELECT id FROM accounts ORDER BY id ASC LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING data")
            if row:
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", ACC_PRICE, user_id)
                await message.answer(f"✅ <b>Ваш аккаунт:</b>\n<code>{row['data']}</code>", parse_mode="HTML")
            else:
                await message.answer("❌ Аккаунты закончились.")

@dp.message(F.text == "📊 Наличие")
async def check_stock(message: types.Message):
    pool = await get_db_pool()
    count = await pool.fetchval("SELECT COUNT(*) FROM accounts")
    await message.answer(f"📦 В наличии: <b>{count} шт.</b>", parse_mode="HTML")

@dp.message(F.text == "➕ Добавить базу")
async def admin_add(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.set_state(ShopStates.adding_accounts)
    await message.answer("📥 Отправь список почт (каждая с новой строки):")

@dp.message(ShopStates.adding_accounts)
async def process_adding(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    accounts = [a.strip() for a in message.text.split('\n') if a.strip()]
    pool = await get_db_pool()
    added = 0
    async with pool.acquire() as conn:
        for acc in accounts:
            res = await conn.execute("INSERT INTO accounts (data) VALUES ($1) ON CONFLICT DO NOTHING", acc)
            if res == "INSERT 0 1": added += 1
    await state.clear()
    await message.answer(f"✅ Добавлено: {added} аккаунтов.")

@dp.message(F.text == "🆘 Поддержка")
async def support(message: types.Message):
    await message.answer(f"👨‍💻 По всем вопросам: @{ADMIN_USERNAME}")

async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute('CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, data TEXT UNIQUE)')
        await conn.execute('CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance DECIMAL(10,2) DEFAULT 0.00)')
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
