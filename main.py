import asyncio
import logging
import sys
from decimal import Decimal

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from aiocryptopay import AioCryptoPay

# --- НАСТРОЙКИ ---
API_TOKEN = '8717755678:AAFxBTzyDghHPLYOstlvkeNsUjgBStP3KHg'
CRYPTO_TOKEN = '553031:AAYPKOXkV5DTYcbIKdQYUlhLFwrI9Ah0YYG' # <-- ТВОЙ НОВЫЙ ТОКЕН
ADMIN_IDS = [8209617821, 8384467554] 
DATABASE_URL = 'postgresql://bothost_db_29f14895d3aa:tbdVGmS3JoNrcauznAFgzNTJgefFJE3xE33flLLZY5M@node1.pghost.ru:32854/bothost_db_29f14895d3aa'
ACC_PRICE = Decimal('0.20') 

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
# Используем твой токен в основной сети (mainnet)
crypto = AioCryptoPay(token=CRYPTO_TOKEN, network='mainnet')

class ShopStates(StatesGroup):
    waiting_for_amount = State()
    adding_accounts = State()

db_pool = None

async def get_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return db_pool

async def get_user_balance(user_id):
    pool = await get_db_pool()
    val = await pool.fetchval("SELECT balance FROM users WHERE user_id = $1", user_id)
    if val is None:
        await pool.execute("INSERT INTO users (user_id, balance) VALUES ($1, 0.00) ON CONFLICT DO NOTHING", user_id)
        return Decimal('0.00')
    return Decimal(str(val))

def main_kb(user_id):
    builder = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🛒 Купить аккаунт")],
            [types.KeyboardButton(text="📊 Наличие"), types.KeyboardButton(text="💎 Баланс")],
            [types.KeyboardButton(text="🆘 Поддержка")]
        ],
        resize_keyboard=True
    )
    if user_id in ADMIN_IDS:
        builder.keyboard.append([types.KeyboardButton(text="➕ Добавить базу")])
    return builder

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "🤖 <b>Система готова к работе.</b>\n\nВыберите нужное действие в меню ниже:",
        reply_markup=main_kb(message.from_user.id),
        parse_mode="HTML"
    )

@dp.message(F.text == "💎 Баланс")
async def balance_menu(message: types.Message):
    balance = await get_user_balance(message.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="💵 Пополнить баланс", callback_data="deposit"))
    await message.answer(
        f"💰 Ваш текущий баланс: <b>{balance:.2f} $</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "deposit")
async def deposit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ShopStates.waiting_for_amount)
    await callback.message.answer("⌨️ Введите сумму пополнения в <b>USD</b> (например: 1.0):", parse_mode="HTML")
    await callback.answer()

@dp.message(ShopStates.waiting_for_amount)
async def create_invoice(message: types.Message, state: FSMContext):
    try:
        # Очистка и проверка ввода
        amount_input = message.text.replace(',', '.').strip()
        amount = float(amount_input)
        
        if amount < 0.1:
            await message.answer("❌ Минимальная сумма пополнения — 0.1 $")
            return

        # Создание инвойса через CryptoBot
        invoice = await crypto.create_invoice(asset='USDT', amount=amount)
        
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="🔗 Оплатить через CryptoBot", url=invoice.pay_url))
        builder.row(types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{invoice.invoice_id}_{amount}"))
        
        await message.answer(
            f"🚀 <b>Счет на {amount}$ создан!</b>\n\nОплатите его в CryptoBot и нажмите кнопку проверки.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Ошибка! Введите число (например: 0.5 или 2)")
    except Exception as e:
        logging.error(f"CryptoPay Error: {e}")
        await message.answer("❌ Произошла ошибка при создании счета. Попробуйте позже или обратитесь в поддержку.")

@dp.callback_query(F.data.startswith("check_"))
async def check_pay(callback: types.CallbackQuery):
    _, inv_id, amount = callback.data.split("_")
    try:
        invoices = await crypto.get_invoices(invoice_ids=inv_id)
        if invoices and invoices[0].status == 'paid':
            pool = await get_db_pool()
            await pool.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", Decimal(amount), callback.from_user.id)
            await callback.message.edit_text(f"✅ Баланс успешно пополнен на <b>{amount} $</b>!", parse_mode="HTML")
            
            for admin_id in ADMIN_IDS:
                try: await bot.send_message(admin_id, f"💰 <b>Новое пополнение!</b>\nЮзер: @{callback.from_user.username}\nСумма: {amount}$")
                except: pass
        else:
            await callback.answer("⚠️ Оплата не найдена. Сначала оплатите счет в CryptoBot!", show_alert=True)
    except Exception as e:
        logging.error(f"Check Pay Error: {e}")
        await callback.answer("❌ Ошибка при проверке. Попробуйте снова.")

@dp.message(F.text == "📊 Наличие")
async def stock(message: types.Message):
    pool = await get_db_pool()
    count = await pool.fetchval("SELECT COUNT(*) FROM accounts")
    await message.answer(f"📦 Сейчас в наличии: <b>{count} шт.</b> почт.", parse_mode="HTML")

@dp.message(F.text == "🛒 Купить аккаунт")
async def buy(message: types.Message):
    user_id = message.from_user.id
    balance = await get_user_balance(user_id)
    
    if balance < ACC_PRICE:
        await message.answer(f"❌ Недостаточно средств.\nЦена почты: {ACC_PRICE}$\nВаш баланс: {balance}$")
        return

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("DELETE FROM accounts WHERE id = (SELECT id FROM accounts ORDER BY id ASC LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING data")
            if row:
                await conn.execute("UPDATE users SET balance = balance - $1 WHERE user_id = $2", ACC_PRICE, user_id)
                await message.answer(f"✅ <b>Ваш аккаунт:</b>\n<code>{row['data']}</code>", parse_mode="HTML")
            else:
                await message.answer("❌ Товар закончился. Зайдите позже!")

@dp.message(F.text == "➕ Добавить базу")
async def add_base(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.set_state(ShopStates.adding_accounts)
    await message.answer("📥 Пришлите список почт (каждая с новой строки):")

@dp.message(ShopStates.adding_accounts)
async def process_add(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    accounts = [a.strip() for a in message.text.split('\n') if a.strip()]
    pool = await get_db_pool()
    added = 0
    async with pool.acquire() as conn:
        for acc in accounts:
            try:
                await conn.execute("INSERT INTO accounts (data) VALUES ($1) ON CONFLICT DO NOTHING", acc)
                added += 1
            except: pass
    await state.clear()
    await message.answer(f"✅ Успешно добавлено {added} шт.")

@dp.message(F.text == "🆘 Поддержка")
async def support(message: types.Message):
    await message.answer("👨‍💻 По всем вопросам и проблемам: @ramaz666")

async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute('CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, data TEXT UNIQUE)')
        await conn.execute('CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, balance DECIMAL(10,2) DEFAULT 0.00)')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
