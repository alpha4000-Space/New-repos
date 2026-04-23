from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, Contact, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from datetime import datetime

from config import ADMIN_IDS
from database import get_user, save_user, get_channels, add_channel, remove_channel, get_all_users, load_db, save_db
from keyboards import (
    lang_keyboard, subscribe_keyboard, phone_keyboard,
    main_menu_keyboard, settings_keyboard, settings_inline_keyboard,
    settings_info_text, admin_keyboard, back_keyboard, referral_inline_keyboard, partners_keyboard
)
from states import RegisterState, AdminState, SettingsState, ReferralState, PartnersState, SupportState
from texts import t, TEXTS
from exchange_config import CURRENCIES
from referral_service import (
    parse_referrer_from_start_text,
    apply_referred_by_for_new_user,
    ensure_user_referral_fields_by_id,
    get_referrals_count,
    format_money,
    create_withdraw_request,
    update_referral_card,
    approve_withdraw_request,
    reject_withdraw_request,
)

router = Router()
REFERRAL_CARD_BUTTONS = ["💳 Kartani qo'shish/yangilash", "💳 Добавить/обновить карту"]
REFERRAL_WITHDRAW_BUTTONS = ["💰 Bonusni yechib olish", "💰 Вывести бонус"]
REFERRAL_HOME_BUTTONS = ["🏠 Bosh menyu", "🏠 Главное меню"]
PARTNERS_ADD_BUTTONS = ["✏️ Qo'shish / o'zgartirish", "✏️ Добавить / изменить"]
PARTNERS_DELETE_BUTTONS = ["❌ O'chirish", "❌ Удалить"]
SUPPORT_MENU_TEXTS = [
    "💱 Valyuta ayirboshlash", "💱 Обмен валют",
    "📊 Kurs", "📊 Курс",
    "👥 Hamyonlar", "👥 Партнёры",
    "👥 Referal", "👥 Реферал",
    "⚙️ Sozlamalar", "⚙️ Настройки",
    "📞 Qayta aloqa", "📞 Обратная связь",
    "🔄 Almashuvlar", "🔄 Переводы",
    "📖 Qo`llanma", "📖 Руководство",
    "🔙 Orqaga", "🔙 Назад",
]


def referral_withdraw_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"RWD_OK_{req_id}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"RWD_NO_{req_id}")],
    ])


def support_admin_reply_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Javob yozish", callback_data=f"SUP_REPLY_{user_id}")]
    ])


def _support_header_text(message: Message) -> str:
    user_id = message.from_user.id
    user = get_user(user_id) or {}
    full_name = f"{user.get('name', '')} {user.get('surname', '')}".strip() or message.from_user.full_name
    username = f"@{user.get('username')}" if user.get("username") else "—"
    phone = user.get("phone", "—")
    created = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    return (
        "📞 Qayta aloqa xabari\n\n"
        f"👤 {full_name} ({username})\n"
        f"🆔 {user_id}\n"
        f"📞 {phone}\n"
        f"🕐 {created}"
    )


async def _send_support_to_admins(message: Message, bot: Bot):
    header = _support_header_text(message)
    uid = message.from_user.id
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, header, reply_markup=support_admin_reply_kb(uid))
            await bot.copy_message(aid, message.chat.id, message.message_id)
        except Exception:
            pass


async def send_referral_panel(message: Message, bot: Bot):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    user = ensure_user_referral_fields_by_id(user_id) or get_user(user_id) or {}
    me = await bot.get_me()
    username = me.username or "bot"
    link = f"https://t.me/{username}?start=ref_{user_id}"
    referrals = get_referrals_count(user_id)
    bonus = format_money(user.get("referral_bonus", 0.0))
    card = (user.get("referral_card") or "kiritilmagan") if lang == "uz" else (user.get("referral_card") or "не указана")

    if lang == "ru":
        text = (
            "👥 Ваш реферальный раздел\n\n"
            f"🔗 Ссылка: {link}\n\n"
            f"👤 Кол-во рефералов: {referrals}\n"
            f"💰 Бонусный баланс: {bonus} сум\n"
            f"💳 Карта: {card}"
        )
    else:
        text = (
            "👥 Sizning referal bo'limingiz\n\n"
            f"🔗 Havola: {link}\n\n"
            f"👤 Referallar soni: {referrals}\n"
            f"💰 Bonus balansi: {bonus} so'm\n"
            f"💳 Karta: {card}"
        )
    await message.answer(text, reply_markup=referral_inline_keyboard(lang))


def _currency_help_text() -> str:
    lines = [f"• {c['name']} ({c['id']})" for c in CURRENCIES]
    return "\n".join(lines)


def _resolve_currency(text: str | None) -> dict | None:
    raw = (text or "").strip().lower()
    if not raw:
        return None
    compact = raw.replace(" ", "").replace("-", "").replace("_", "").replace("(", "").replace(")", "")
    for cur in CURRENCIES:
        if raw == cur["id"].lower():
            return cur
        if raw == cur["name"].lower():
            return cur
        cur_compact = cur["name"].lower().replace(" ", "").replace("-", "").replace("_", "").replace("(", "").replace(")", "")
        if compact == cur_compact:
            return cur
    return None


def _get_user_wallets(user_id: int) -> dict:
    user = get_user(user_id) or {}
    wallets = user.get("wallets", {})
    return wallets if isinstance(wallets, dict) else {}


def _save_user_wallet(user_id: int, cur_id: str, value: str) -> bool:
    db = load_db()
    users = db.get("users", {})
    user = users.get(str(user_id))
    if not user:
        return False
    wallets = user.get("wallets", {})
    if not isinstance(wallets, dict):
        wallets = {}
    wallets[cur_id] = value.strip()
    user["wallets"] = wallets
    save_db(db)
    return True


def _delete_user_wallet(user_id: int, cur_id: str) -> bool:
    db = load_db()
    users = db.get("users", {})
    user = users.get(str(user_id))
    if not user:
        return False
    wallets = user.get("wallets", {})
    if not isinstance(wallets, dict):
        wallets = {}
    existed = cur_id in wallets
    wallets.pop(cur_id, None)
    user["wallets"] = wallets
    save_db(db)
    return existed


def _partners_text(user_id: int, lang: str) -> str:
    wallets = _get_user_wallets(user_id)
    empty = "пусто" if lang == "ru" else "bo'sh"
    title = "📁 Список ваших кошельков:" if lang == "ru" else "📁 Sizning hamyonlaringiz:"
    lines = [title, ""]
    for cur in CURRENCIES:
        val = wallets.get(cur["id"], empty)
        lines.append(f"💸 {cur['name']}: {val}")
    return "\n".join(lines)


async def send_partners_panel(message: Message):
    lang = get_lang(message.from_user.id)
    await message.answer(_partners_text(message.from_user.id, lang), reply_markup=partners_keyboard(lang))


def _mask_payment_value(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "—"
    digits_only = "".join(ch for ch in raw if ch.isdigit())
    if len(digits_only) >= 12:
        tail = digits_only[-4:]
        return f"**** **** **** {tail}"
    if len(raw) <= 8:
        return raw
    return f"{raw[:6]}...{raw[-4:]}"


def _normalize_created_at(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return "—"
    from datetime import datetime as _dt
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = _dt.strptime(v, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return v


def _order_status_label(status: str, lang: str) -> str:
    st = (status or "").strip()
    if st in ("pending_payment", "receipt_sent"):
        return "New"
    if st == "completed":
        return "Tasdiqlangan" if lang == "uz" else "Подтверждено"
    if st == "cancelled":
        return "Bekor qilingan" if lang == "uz" else "Отменено"
    return st or ("Noma'lum" if lang == "uz" else "Неизвестно")


def _get_user_orders(user_id: int) -> list[dict]:
    db = load_db()
    orders = list(db.get("orders", {}).values())
    result = []
    for o in orders:
        try:
            if int(o.get("user_id", 0)) == int(user_id):
                result.append(o)
        except Exception:
            continue
    result.sort(key=lambda x: int(x.get("order_id", 0)), reverse=True)
    return result


def _format_order_block(order: dict, lang: str) -> str:
    send_amount = order.get("send_amount", 0)
    recv_amount = order.get("recv_amount", order.get("receive_amount", 0))
    sender = _mask_payment_value(order.get("sender_card", ""))
    receiver = _mask_payment_value(order.get("receiver_card", ""))
    status = _order_status_label(order.get("status", ""), lang)
    created_at = _normalize_created_at(order.get("created_at", ""))
    return (
        f"🆔 ID: {order.get('order_id', '—')}\n"
        f"🔁 {order.get('from_name', '—')} → {order.get('to_name', '—')}\n"
        f"💰 {send_amount} → {recv_amount}\n"
        f"📤 Yuboruvchi: {sender}\n"
        f"📥 Qabul qiluvchi: {receiver}\n"
        f"📅 Yaratilgan: {created_at}\n"
        f"📌 {status}"
    )


def _transfers_inline_kb(lang: str) -> InlineKeyboardMarkup:
    text = "📣 Barcha almashuvlarni ko'rish" if lang == "uz" else "📣 Показать все обмены"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="TR_ALL")]
    ])


def _paginate_order_blocks(blocks: list[str], lang: str, first_title: str) -> list[str]:
    if not blocks:
        return [first_title]
    sep = "\n\n——————————\n\n"
    pages: list[str] = []
    current_blocks: list[str] = []
    current_len = 0
    limit = 3800
    for block in blocks:
        add = len(block) + (len(sep) if current_blocks else 0)
        if current_blocks and (current_len + add) > limit:
            prefix = first_title if not pages else ("🔄 Davomi:" if lang == "uz" else "🔄 Продолжение:")
            pages.append(prefix + "\n\n" + sep.join(current_blocks))
            current_blocks = [block]
            current_len = len(block)
        else:
            current_blocks.append(block)
            current_len += add
    if current_blocks:
        prefix = first_title if not pages else ("🔄 Davomi:" if lang == "uz" else "🔄 Продолжение:")
        pages.append(prefix + "\n\n" + sep.join(current_blocks))
    return pages



async def check_subscriptions(bot: Bot, user_id: int) -> bool:
    """Check if user is subscribed to all required channels"""
    channels = get_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except Exception:
            return False
    return True


def get_lang(user_id: int) -> str:
    user = get_user(user_id)
    if user and "lang" in user:
        return user["lang"]
    return "uz"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    referred_by = parse_referrer_from_start_text(message.text or "", user_id)
    if referred_by:
        await state.update_data(referred_by=referred_by)

    # Admin check
    if user_id in ADMIN_IDS:
        user = get_user(user_id)
        if user and user.get("registered"):
            lang = user.get("lang", "uz")
            await message.answer("👨‍💼 Xush kelibsiz, Admin!", reply_markup=main_menu_keyboard(lang))
            return

    user = get_user(user_id)

    if user and user.get("registered"):
        lang = user.get("lang", "uz")
        await message.answer(t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang))
        return

    channels = get_channels()
    if channels:
        subscribed = await check_subscriptions(bot, user_id)
        if not subscribed:
            await message.answer(
                t("uz", "subscribe_required"),
                reply_markup=subscribe_keyboard(channels)
            )
            return

    # Ask language
    await state.set_state(RegisterState.choosing_lang)
    await message.answer(t("uz", "choose_lang"), reply_markup=lang_keyboard())



@router.callback_query(F.data == "check_subscribe")
async def check_subscribe_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    subscribed = await check_subscriptions(bot, user_id)

    if not subscribed:
        channels = get_channels()
        await callback.answer(t("uz", "not_subscribed"), show_alert=True)
        return

    await callback.message.delete()

    user = get_user(user_id)
    if user and user.get("registered"):
        lang = user.get("lang", "uz")
        await callback.message.answer(t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang))
        return

    await state.set_state(RegisterState.choosing_lang)
    await callback.message.answer(t("uz", "choose_lang"), reply_markup=lang_keyboard())

@router.callback_query(RegisterState.choosing_lang, F.data.startswith("lang_"))
async def choose_language(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]  # "uz" or "ru"

    await state.update_data(lang=lang)
    await callback.message.delete()
    await callback.answer(t(lang, "lang_selected"))

    await state.set_state(RegisterState.entering_name)
    await callback.message.answer(t(lang, "enter_name"))


# =================== REGISTRATION ===================

@router.message(RegisterState.entering_name)
async def enter_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")

    name = message.text.strip()
    if not name or len(name) < 2:
        await message.answer("❌ Iltimos, to'g'ri ism kiriting (kamida 2 ta harf):")
        return

    await state.update_data(name=name)
    await state.set_state(RegisterState.entering_surname)
    await message.answer(t(lang, "enter_surname"))


@router.message(RegisterState.entering_surname)
async def enter_surname(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")

    surname = message.text.strip()
    if not surname or len(surname) < 2:
        await message.answer("❌ Iltimos, to'g'ri familiya kiriting (kamida 2 ta harf):")
        return

    await state.update_data(surname=surname)
    await state.set_state(RegisterState.entering_phone)
    await message.answer(t(lang, "enter_phone"), reply_markup=phone_keyboard(lang))


@router.message(RegisterState.entering_phone, F.contact)
async def enter_phone_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    contact: Contact = message.contact
    phone = contact.phone_number

    await finish_registration(message, state, data, phone, lang)


@router.message(RegisterState.entering_phone, F.text)
async def enter_phone_text(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    phone = message.text.strip()

    # Basic phone validation
    cleaned = phone.replace("+", "").replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) < 9:
        await message.answer("❌ Iltimos, to'g'ri telefon raqam kiriting:")
        return

    await finish_registration(message, state, data, phone, lang)


async def finish_registration(message: Message, state: FSMContext, data: dict, phone: str, lang: str):
    user_id = message.from_user.id
    name = data.get("name")
    surname = data.get("surname")
    referred_by = data.get("referred_by")

    user_data = {
        "user_id": user_id,
        "username": message.from_user.username,
        "lang": lang,
        "name": name,
        "surname": surname,
        "phone": phone,
        "registered": True
    }
    apply_referred_by_for_new_user(user_data, referred_by)
    save_user(user_id, user_data)
    ensure_user_referral_fields_by_id(user_id)

    await state.clear()
    await message.answer(
        t(lang, "registration_done", name=name, surname=surname, phone=phone),
        reply_markup=main_menu_keyboard(lang)
    )

@router.message(F.text.in_(["💱 Valyuta ayirboshlash", "💱 Обмен валют"]))
async def menu_exchange(message: Message):
    lang = get_lang(message.from_user.id)
    await message.answer(t(lang, "exchange_menu"))


@router.message(F.text.in_(["📊 Kurs", "📊 Курс"]))
async def menu_rates(message: Message, bot: Bot):
    lang = get_lang(message.from_user.id)
    try:
        from rates_api import get_rates_text, update_live_rates, get_live_rates
        # Kurslar DB da yo'q bo'lsa yangilaydi
        if not get_live_rates():
            wait_msg = await message.answer("⏳ Kurslar yuklanmoqda...")
            await update_live_rates()
            try:
                await wait_msg.delete()
            except:
                pass
        text = get_rates_text(lang)
        if not text or text.startswith("⏳"):
            text = "❌ Kurs ma'lumotlari hali yuklanmagan. Keyinroq urinib ko'ring." if lang == "uz" else "❌ Данные курсов ещё не загружены. Попробуйте позже."
    except Exception as e:
        import logging;
        logging.getLogger(__name__).warning(f"Kurs handler xato: {e}")
        text = "❌ Kurs ma'lumotlari yuklanmadi. Qayta urinib ko'ring." if lang == "uz" else "❌ Не удалось загрузить курсы. Попробуйте ещё раз."
    await message.answer(text)


@router.message(F.text.in_(["👥 Hamyonlar", "👥 Партнёры"]))
async def menu_partners(message: Message):
    await send_partners_panel(message)


@router.message(F.text.in_(PARTNERS_ADD_BUTTONS))
async def partners_add_start(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.set_state(PartnersState.waiting_currency_add)
    if lang == "ru":
        await message.answer("✏️ Какую валюту хотите добавить/изменить?\n\n" + _currency_help_text())
    else:
        await message.answer("✏️ Qaysi valyuta hamyonini qo'shmoqchi/o'zgartirmoqchisiz?\n\n" + _currency_help_text())


@router.message(PartnersState.waiting_currency_add)
async def partners_add_currency(message: Message, state: FSMContext):
    cur = _resolve_currency(message.text)
    lang = get_lang(message.from_user.id)
    if not cur:
        if lang == "ru":
            await message.answer("❌ Валюта не найдена. Повторите:\n\n" + _currency_help_text())
        else:
            await message.answer("❌ Valyuta topilmadi. Qayta kiriting:\n\n" + _currency_help_text())
        return
    await state.update_data(partners_currency=cur["id"])
    await state.set_state(PartnersState.waiting_wallet_add)
    if lang == "ru":
        await message.answer(f"💳 {cur['name']} для вашего кошелька:\n\nВведите номер карты/адрес:")
    else:
        await message.answer(f"💳 {cur['name']} uchun hamyon manzilini kiriting:")


@router.message(PartnersState.waiting_wallet_add)
async def partners_add_wallet(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if len(value) < 4:
        await message.answer("❌ Qiymat juda qisqa. Qayta kiriting:")
        return
    data = await state.get_data()
    cur_id = data.get("partners_currency")
    if not cur_id:
        await state.clear()
        await message.answer("❌ Jarayon tugadi. Qaytadan urinib ko'ring.")
        return
    ok = _save_user_wallet(message.from_user.id, cur_id, value)
    await state.clear()
    if not ok:
        await message.answer("❌ Saqlashda xatolik bo'ldi.")
        return
    await message.answer("✅ Hamyon saqlandi.")
    await send_partners_panel(message)


@router.message(F.text.in_(PARTNERS_DELETE_BUTTONS))
async def partners_delete_start(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.set_state(PartnersState.waiting_currency_delete)
    if lang == "ru":
        await message.answer("❌ Какую валюту удалить?\n\n" + _currency_help_text())
    else:
        await message.answer("❌ Qaysi valyuta hamyonini o'chirmoqchisiz?\n\n" + _currency_help_text())


@router.message(PartnersState.waiting_currency_delete)
async def partners_delete_currency(message: Message, state: FSMContext):
    cur = _resolve_currency(message.text)
    lang = get_lang(message.from_user.id)
    if not cur:
        if lang == "ru":
            await message.answer("❌ Валюта не найдена. Повторите:\n\n" + _currency_help_text())
        else:
            await message.answer("❌ Valyuta topilmadi. Qayta kiriting:\n\n" + _currency_help_text())
        return
    existed = _delete_user_wallet(message.from_user.id, cur["id"])
    await state.clear()
    if existed:
        await message.answer(f"✅ {cur['name']} hamyoni o'chirildi.")
    else:
        await message.answer(f"ℹ️ {cur['name']} uchun saqlangan hamyon topilmadi.")
    await send_partners_panel(message)


@router.message(F.text.in_(["👥 Referal", "👥 Реферал"]))
async def menu_referral(message: Message, bot: Bot):
    await send_referral_panel(message, bot)


@router.callback_query(F.data == "REF_CARD")
async def referral_card_start_cb(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(callback.from_user.id)
    await state.set_state(ReferralState.waiting_card)
    await callback.answer()
    if lang == "ru":
        await callback.message.answer("💳 Введите номер карты для вывода бонуса:")
    else:
        await callback.message.answer("💳 Bonus yechish uchun kartangizni kiriting:")


@router.callback_query(F.data == "REF_WITHDRAW")
async def referral_withdraw_start_cb(callback: CallbackQuery, bot: Bot):
    lang = get_lang(callback.from_user.id)
    req, err = create_withdraw_request(callback.from_user.id)
    if err == "no_card":
        await callback.answer("Avval kartani kiriting", show_alert=True)
        return
    if err == "zero":
        await callback.answer("Bonus balansi 0", show_alert=True)
        return
    if err == "min":
        await callback.answer("Minimal summa hali yetarli emas", show_alert=True)
        return
    if err == "pending":
        await callback.answer("Kutilayotgan so'rov mavjud", show_alert=True)
        return
    if not req:
        await callback.answer("Xatolik", show_alert=True)
        return

    user = get_user(callback.from_user.id) or {}
    full_name = f"{user.get('name', '')} {user.get('surname', '')}".strip() or callback.from_user.full_name
    username = f"@{user.get('username')}" if user.get("username") else "—"
    phone = user.get("phone", "—")

    admin_text = (
        f"💸 Referral bonus yechish so'rovi #{req['id']}\n\n"
        f"👤 {full_name} ({username})\n"
        f"🆔 {req['user_id']}\n"
        f"📞 {phone}\n\n"
        f"💰 Miqdor: {format_money(req['amount'])} so'm\n"
        f"💳 Karta: {req['card']}\n"
        f"🕐 {req['created_at']}"
    )

    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, admin_text, reply_markup=referral_withdraw_kb(req["id"]))
        except Exception:
            pass

    if lang == "ru":
        await callback.message.answer("✅ Запрос отправлен админу. Ожидайте подтверждения.")
    else:
        await callback.message.answer("✅ So'rovingiz adminga yuborildi. Tasdiqlanishini kuting.")
    await callback.answer("✅")


@router.callback_query(F.data == "REF_HOME")
async def referral_home_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = get_lang(callback.from_user.id)
    await callback.message.answer(t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang))
    await callback.answer()


@router.message(F.text.in_(REFERRAL_CARD_BUTTONS))
async def referral_card_start(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.set_state(ReferralState.waiting_card)
    if lang == "ru":
        await message.answer("💳 Введите номер карты для вывода бонуса:")
    else:
        await message.answer("💳 Bonus yechish uchun kartangizni kiriting:")


@router.message(ReferralState.waiting_card)
async def referral_card_save(message: Message, state: FSMContext, bot: Bot):
    if (message.text or "").strip() in REFERRAL_HOME_BUTTONS:
        await state.clear()
        lang = get_lang(message.from_user.id)
        await message.answer(t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang))
        return
    if (message.text or "").strip() in ["🔙 Orqaga", "🔙 Назад"]:
        await state.clear()
        await send_referral_panel(message, bot)
        return

    card = (message.text or "").replace(" ", "")
    if not card or len(card) < 8:
        await message.answer("❌ Karta raqamini to'g'ri kiriting.")
        return
    ok = update_referral_card(message.from_user.id, card)
    await state.clear()
    if not ok:
        await message.answer("❌ Saqlashda xatolik bo'ldi.")
        return
    await message.answer("✅ Karta saqlandi.")
    await send_referral_panel(message, bot)


@router.message(F.text.in_(REFERRAL_WITHDRAW_BUTTONS))
async def referral_withdraw_start(message: Message, bot: Bot):
    lang = get_lang(message.from_user.id)
    req, err = create_withdraw_request(message.from_user.id)
    if err == "no_card":
        await message.answer("❌ Avval kartani kiriting.")
        return
    if err == "zero":
        await message.answer("❌ Bonus balansi 0.")
        return
    if err == "min":
        await message.answer("❌ Bonus yechish uchun minimal summa hali yetarli emas.")
        return
    if err == "pending":
        await message.answer("⏳ Sizda allaqachon kutilayotgan bonus yechish so'rovi bor.")
        return
    if not req:
        await message.answer("❌ So'rov yuborilmadi. Qayta urinib ko'ring.")
        return

    user = get_user(message.from_user.id) or {}
    full_name = f"{user.get('name', '')} {user.get('surname', '')}".strip() or message.from_user.full_name
    username = f"@{user.get('username')}" if user.get("username") else "—"
    phone = user.get("phone", "—")

    admin_text = (
        f"💸 Referral bonus yechish so'rovi #{req['id']}\n\n"
        f"👤 {full_name} ({username})\n"
        f"🆔 {req['user_id']}\n"
        f"📞 {phone}\n\n"
        f"💰 Miqdor: {format_money(req['amount'])} so'm\n"
        f"💳 Karta: {req['card']}\n"
        f"🕐 {req['created_at']}"
    )

    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, admin_text, reply_markup=referral_withdraw_kb(req["id"]))
        except Exception:
            pass

    if lang == "ru":
        await message.answer("✅ Запрос отправлен админу. Ожидайте подтверждения.")
    else:
        await message.answer("✅ So'rovingiz adminga yuborildi. Tasdiqlanishini kuting.")


@router.message(F.text.in_(REFERRAL_HOME_BUTTONS))
async def referral_go_home(message: Message, state: FSMContext):
    await state.clear()
    lang = get_lang(message.from_user.id)
    await message.answer(t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang))


@router.callback_query(F.data.startswith("RWD_OK_"))
async def referral_withdraw_approve(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return
    try:
        req_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("❌ Xato", show_alert=True)
        return

    req, user, err = approve_withdraw_request(req_id, callback.from_user.id)
    if err == "not_found":
        await callback.answer("❌ So'rov topilmadi", show_alert=True)
        return
    if err == "already_processed":
        await callback.answer("⚠️ So'rov avval qayta ishlangan", show_alert=True)
        return

    if req:
        uid = req.get("user_id")
        if uid:
            try:
                await bot.send_message(uid, f"✅ Referral bonusingiz chiqarildi.\n💸 {format_money(req.get('amount', 0))} so'm")
            except Exception:
                pass
    await callback.message.edit_text(f"✅ Referral so'rov #{req_id} tasdiqlandi.")
    await callback.answer("✅")


@router.callback_query(F.data.startswith("RWD_NO_"))
async def referral_withdraw_reject(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return
    try:
        req_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("❌ Xato", show_alert=True)
        return

    req, user, err = reject_withdraw_request(req_id, callback.from_user.id)
    if err == "not_found":
        await callback.answer("❌ So'rov topilmadi", show_alert=True)
        return
    if err == "already_processed":
        await callback.answer("⚠️ So'rov avval qayta ishlangan", show_alert=True)
        return

    if req:
        uid = req.get("user_id")
        if uid:
            try:
                await bot.send_message(uid, "❌ Referral bonus yechish so'rovi bekor qilindi. Bonus balansga qaytarildi.")
            except Exception:
                pass
    await callback.message.edit_text(f"❌ Referral so'rov #{req_id} bekor qilindi.")
    await callback.answer("❌")


@router.message(F.text.in_(["📞 Qayta aloqa", "📞 Обратная связь"]))
async def menu_callback(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.set_state(SupportState.user_writing)
    if lang == "ru":
        await message.answer("✍️ Пожалуйста, напишите ваше сообщение для админов:")
    else:
        await message.answer("✍️ Iltimos, adminlarga yuborish uchun xabaringizni yozing:")


@router.message(SupportState.user_writing, F.text & ~F.text.in_(SUPPORT_MENU_TEXTS))
async def support_user_text(message: Message, bot: Bot):
    lang = get_lang(message.from_user.id)
    await _send_support_to_admins(message, bot)
    if lang == "ru":
        await message.answer("✅ Сообщение отправлено админам.")
    else:
        await message.answer("✅ Xabaringiz adminlarga yuborildi.")


@router.message(SupportState.user_writing, F.photo | F.document | F.video | F.voice | F.audio | F.sticker)
async def support_user_media(message: Message, bot: Bot):
    lang = get_lang(message.from_user.id)
    await _send_support_to_admins(message, bot)
    if lang == "ru":
        await message.answer("✅ Сообщение отправлено админам.")
    else:
        await message.answer("✅ Xabaringiz adminlarga yuborildi.")


@router.callback_query(F.data.startswith("SUP_REPLY_"))
async def support_admin_reply_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return
    try:
        uid = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("❌ Xato", show_alert=True)
        return

    user = get_user(uid)
    if not user:
        await callback.answer("❌ User topilmadi", show_alert=True)
        return

    await state.set_state(SupportState.admin_replying)
    await state.update_data(support_uid=uid)
    await callback.answer()
    await callback.message.answer(
        f"✍️ User {uid} ga yuboriladigan javobni yozing.\n"
        f"Bekor qilish uchun: ❌ Bekor"
    )


@router.message(SupportState.admin_replying, F.text)
async def support_admin_reply_text(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return
    text = (message.text or "").strip()
    if text == "❌ Bekor":
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
        return

    data = await state.get_data()
    uid = data.get("support_uid")
    if not uid:
        await state.clear()
        await message.answer("❌ Session tugagan, qayta urinib ko'ring.")
        return

    try:
        await bot.send_message(int(uid), f"👨‍💼 Admin javobi:\n\n{text}")
        await message.answer("✅ Javob yuborildi.")
    except Exception:
        await message.answer("❌ Javob yuborilmadi.")
    await state.clear()


@router.message(SupportState.admin_replying, F.photo | F.document | F.video | F.voice | F.audio | F.sticker)
async def support_admin_reply_media(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = await state.get_data()
    uid = data.get("support_uid")
    if not uid:
        await state.clear()
        await message.answer("❌ Session tugagan, qayta urinib ko'ring.")
        return

    try:
        await bot.send_message(int(uid), "👨‍💼 Admindan media xabar:")
        await bot.copy_message(int(uid), message.chat.id, message.message_id)
        await message.answer("✅ Javob yuborildi.")
    except Exception:
        await message.answer("❌ Javob yuborilmadi.")
    await state.clear()


@router.message(F.text.in_(["🔄 Almashuvlar", "🔄 Переводы"]))
async def menu_transfers(message: Message):
    lang = get_lang(message.from_user.id)
    orders = _get_user_orders(message.from_user.id)
    if lang == "ru":
        title = "🔄 Ваши обмены:"
        empty = "📭 У вас пока нет обменов."
    else:
        title = "🔄 Sizning almashuvlaringiz:"
        empty = "📭 Sizda hali almashuvlar yo'q."

    if not orders:
        await message.answer(f"{title}\n\n{empty}")
        return

    blocks = [_format_order_block(o, lang) for o in orders[:2]]
    pages = _paginate_order_blocks(blocks, lang, title)
    for idx, page_text in enumerate(pages):
        if idx == 0:
            await message.answer(page_text, reply_markup=_transfers_inline_kb(lang))
        else:
            await message.answer(page_text)


@router.callback_query(F.data == "TR_ALL")
async def menu_transfers_all(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    orders = _get_user_orders(callback.from_user.id)
    if not orders:
        await callback.answer("📭 Almashuv yo'q", show_alert=True)
        return
    title = "🔄 Barcha almashuvlaringiz:" if lang == "uz" else "🔄 Все ваши обмены:"
    blocks = [_format_order_block(o, lang) for o in orders]
    pages = _paginate_order_blocks(blocks, lang, title)
    for page_text in pages:
        await callback.message.answer(page_text)
    await callback.answer()


@router.message(F.text.in_(["📖 Qo`llanma", "📖 Руководство"]))
async def menu_guide(message: Message):
    lang = get_lang(message.from_user.id)
    await message.answer(t(lang, "guide_menu"))

@router.message(F.text.in_(["⚙️ Sozlamalar", "⚙️ Настройки"]))
async def menu_settings(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    user = get_user(user_id)
    await state.set_state(SettingsState.in_settings)
    text = settings_info_text(user, lang)
    await message.answer(text, reply_markup=settings_inline_keyboard(lang))


@router.callback_query(F.data == "settings_lang")
async def settings_change_lang(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegisterState.choosing_lang)
    await state.update_data(changing_lang=True)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("uz", "choose_lang"), reply_markup=lang_keyboard())
    await callback.answer()


@router.callback_query(F.data == "settings_name")
async def settings_change_name_cb(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(callback.from_user.id)
    await state.set_state(SettingsState.changing_name)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t(lang, "enter_name"))
    await callback.answer()


@router.callback_query(F.data == "settings_phone")
async def settings_change_phone_cb(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(callback.from_user.id)
    await state.set_state(SettingsState.changing_phone)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t(lang, "enter_phone"), reply_markup=phone_keyboard(lang))
    await callback.answer()


@router.message(SettingsState.changing_name)
async def change_name_finish(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    name = message.text.strip()

    if not name or len(name) < 2:
        await message.answer("❌ Iltimos, to'g'ri ism kiriting:")
        return

    user = get_user(user_id)
    user["name"] = name
    save_user(user_id, user)

    await state.clear()
    text = settings_info_text(get_user(user_id), lang)
    await message.answer(text, reply_markup=settings_inline_keyboard(lang))


@router.message(SettingsState.changing_phone, F.contact)
async def change_phone_contact(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    user = get_user(user_id)
    user["phone"] = message.contact.phone_number
    save_user(user_id, user)
    await state.clear()
    text = settings_info_text(get_user(user_id), lang)
    await message.answer(text, reply_markup=settings_inline_keyboard(lang))


@router.message(SettingsState.changing_phone, F.text)
async def change_phone_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    phone = message.text.strip()
    cleaned = phone.replace("+", "").replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) < 9:
        await message.answer("❌ Iltimos, to'g'ri telefon raqam kiriting:")
        return
    user = get_user(user_id)
    user["phone"] = phone
    save_user(user_id, user)
    await state.clear()
    text = settings_info_text(get_user(user_id), lang)
    await message.answer(text, reply_markup=settings_inline_keyboard(lang))


@router.message(F.text.in_(["🔙 Orqaga", "🔙 Назад"]))
async def go_back(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.clear()
    await message.answer(t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang))


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("👨‍💼 Admin panel", reply_markup=admin_keyboard())


@router.message(F.text == "➕ Kanal qo'shish")
async def admin_add_channel_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.waiting_channel_id)
    await message.answer("Kanal ID sini kiriting (masalan: -1001234567890):\n\n💡 Botni kanalga admin qilib qo'shing!")


@router.message(AdminState.waiting_channel_id)
async def admin_add_channel_id(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        channel_id = int(message.text.strip())
        await state.update_data(channel_id=channel_id)
        await state.set_state(AdminState.waiting_channel_link)
        await message.answer("Kanal havolasini kiriting (masalan: https://t.me/kanalim):")
    except ValueError:
        await message.answer("❌ Noto'g'ri format! ID son bo'lishi kerak:")


@router.message(AdminState.waiting_channel_link)
async def admin_add_channel_link(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    link = message.text.strip()
    await state.update_data(channel_link=link)
    await state.set_state(AdminState.waiting_channel_name)
    await message.answer("Kanal nomini kiriting:")


@router.message(AdminState.waiting_channel_name)
async def admin_add_channel_name(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    name = message.text.strip()

    result = add_channel(data["channel_id"], data["channel_link"], name)
    await state.clear()

    if result:
        await message.answer(f"✅ Kanal qo'shildi!\n📢 {name}\n🔗 {data['channel_link']}", reply_markup=admin_keyboard())
    else:
        await message.answer("❌ Bu kanal allaqachon mavjud!", reply_markup=admin_keyboard())


@router.message(F.text == "➖ Kanal o'chirish")
async def admin_remove_channel_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    from database import get_channels
    channels = get_channels()
    if not channels:
        await message.answer("📭 Kanallar yo'q!")
        return

    text = "📋 Mavjud kanallar:\n\n"
    for ch in channels:
        text += f"• {ch['channel_name']} | ID: {ch['channel_id']}\n"
    text += "\nO'chirmoqchi bo'lgan kanal ID sini kiriting:"

    await state.set_state(AdminState.waiting_remove_id)
    await message.answer(text)


@router.message(AdminState.waiting_remove_id)
async def admin_remove_channel(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        channel_id = int(message.text.strip())
        result = remove_channel(channel_id)
        await state.clear()
        if result:
            await message.answer("✅ Kanal o'chirildi!", reply_markup=admin_keyboard())
        else:
            await message.answer("❌ Kanal topilmadi!", reply_markup=admin_keyboard())
    except ValueError:
        await message.answer("❌ Noto'g'ri format!")


@router.message(F.text == "📋 Kanallar ro'yxati")
async def admin_list_channels(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    from database import get_channels
    channels = get_channels()
    if not channels:
        await message.answer("📭 Hech qanday kanal qo'shilmagan!")
        return

    text = "📋 Kanallar ro'yxati:\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch['channel_name']}\n   🔗 {ch['channel_link']}\n   🆔 {ch['channel_id']}\n\n"
    await message.answer(text)


@router.message(F.text == "👥 Foydalanuvchilar")
async def admin_users_count(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    users = get_all_users()
    await message.answer(f"👥 Jami foydalanuvchilar: {len(users)} ta")


@router.message(F.text == "📨 Hammaga xabar")
async def admin_broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.waiting_broadcast)
    await message.answer("Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:")


@router.message(AdminState.waiting_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return

    users = get_all_users()
    count = 0
    for user_id_str in users:
        try:
            await bot.send_message(int(user_id_str), message.text)
            count += 1
        except Exception:
            pass

    await state.clear()
    await message.answer(f"✅ Xabar {count} ta foydalanuvchiga yuborildi!", reply_markup=admin_keyboard())


@router.callback_query(F.data.startswith("lang_"))
async def handle_lang_callback(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    user_id = callback.from_user.id

    current_state = await state.get_state()
    data = await state.get_data()

    if current_state == RegisterState.choosing_lang:
        if data.get("changing_lang"):
            # Just updating language
            user = get_user(user_id)
            if user:
                user["lang"] = lang
                save_user(user_id, user)
            await state.clear()
            await callback.message.delete()
            await callback.answer(f"✅ Til o'zgartirildi!")
            await callback.message.answer(t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang))
        else:
            await state.update_data(lang=lang)
            await callback.message.delete()
            await callback.answer(t(lang, "lang_selected"))
            await state.set_state(RegisterState.entering_name)
            await callback.message.answer(t(lang, "enter_name"))
