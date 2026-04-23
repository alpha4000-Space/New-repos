from datetime import datetime
from typing import Tuple

from database import load_db, save_db


DEFAULT_REFERRAL_SETTINGS = {
    "bonus_per_completed_order": 3000.0,
    "min_withdraw": 10000.0,
}


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _to_int(v, default=0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def format_money(amount: float) -> str:
    return f"{_to_float(amount):.2f}"


def get_referral_settings(db: dict | None = None) -> dict:
    local_db = db or load_db()
    settings = local_db.setdefault("referral_settings", {})
    changed = False
    for key, value in DEFAULT_REFERRAL_SETTINGS.items():
        if key not in settings:
            settings[key] = value
            changed = True
    if changed and db is None:
        save_db(local_db)
    return settings


def ensure_user_referral_fields(user: dict) -> bool:
    changed = False
    defaults = {
        "referred_by": None,
        "referral_bonus": 0.0,
        "referral_pending": 0.0,
        "referral_earned_total": 0.0,
        "referral_card": "",
    }
    for key, value in defaults.items():
        if key not in user:
            user[key] = value
            changed = True
    return changed


def ensure_user_referral_fields_by_id(user_id: int) -> dict | None:
    db = load_db()
    user = db.get("users", {}).get(str(user_id))
    if not user:
        return None
    changed = ensure_user_referral_fields(user)
    if changed:
        save_db(db)
    return user


def parse_referrer_from_start_text(start_text: str, current_user_id: int) -> int | None:
    parts = (start_text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    arg = parts[1].strip()
    if not arg.startswith("ref_"):
        return None
    raw_id = arg[4:]
    if not raw_id.isdigit():
        return None
    referrer_id = int(raw_id)
    if referrer_id == current_user_id:
        return None
    db = load_db()
    if str(referrer_id) not in db.get("users", {}):
        return None
    return referrer_id


def apply_referred_by_for_new_user(user_data: dict, referred_by: int | None):
    if not referred_by:
        return
    if referred_by == user_data.get("user_id"):
        return
    user_data["referred_by"] = referred_by


def get_referrals_count(referrer_id: int) -> int:
    users = load_db().get("users", {})
    count = 0
    for user in users.values():
        referred_by = user.get("referred_by")
        if _to_int(referred_by, 0) == referrer_id:
            count += 1
    return count


def award_referral_bonus_for_order(order_id: int) -> dict | None:
    db = load_db()
    orders = db.get("orders", {})
    users = db.get("users", {})
    order = orders.get(str(order_id))
    if not order:
        return None
    if order.get("status") != "completed":
        return None
    if order.get("ref_bonus_processed"):
        return None

    buyer_id = _to_int(order.get("user_id"), 0)
    buyer = users.get(str(buyer_id))
    if not buyer:
        return None
    ensure_user_referral_fields(buyer)

    referrer_id = _to_int(buyer.get("referred_by"), 0)
    if not referrer_id or referrer_id == buyer_id:
        order["ref_bonus_processed"] = True
        save_db(db)
        return None

    referrer = users.get(str(referrer_id))
    if not referrer:
        order["ref_bonus_processed"] = True
        save_db(db)
        return None
    ensure_user_referral_fields(referrer)

    settings = get_referral_settings(db)
    bonus = _to_float(settings.get("bonus_per_completed_order"), DEFAULT_REFERRAL_SETTINGS["bonus_per_completed_order"])
    if bonus <= 0:
        order["ref_bonus_processed"] = True
        save_db(db)
        return None

    referrer["referral_bonus"] = round(_to_float(referrer.get("referral_bonus"), 0.0) + bonus, 2)
    referrer["referral_earned_total"] = round(_to_float(referrer.get("referral_earned_total"), 0.0) + bonus, 2)

    order["ref_bonus_processed"] = True
    order["ref_bonus_amount"] = bonus
    order["ref_bonus_referrer"] = referrer_id
    order["ref_bonus_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    save_db(db)

    return {
        "referrer_id": referrer_id,
        "bonus_amount": bonus,
        "new_balance": referrer.get("referral_bonus", 0.0),
        "buyer_id": buyer_id,
    }


def update_referral_card(user_id: int, card: str) -> bool:
    db = load_db()
    user = db.get("users", {}).get(str(user_id))
    if not user:
        return False
    ensure_user_referral_fields(user)
    user["referral_card"] = (card or "").strip()
    save_db(db)
    return True


def create_withdraw_request(user_id: int) -> Tuple[dict | None, str | None]:
    db = load_db()
    users = db.get("users", {})
    user = users.get(str(user_id))
    if not user:
        return None, "not_found"
    ensure_user_referral_fields(user)

    settings = get_referral_settings(db)
    min_withdraw = _to_float(settings.get("min_withdraw"), DEFAULT_REFERRAL_SETTINGS["min_withdraw"])
    bonus_balance = round(_to_float(user.get("referral_bonus"), 0.0), 2)
    referral_card = (user.get("referral_card") or "").strip()

    if not referral_card:
        return None, "no_card"
    if bonus_balance <= 0:
        return None, "zero"
    if bonus_balance < min_withdraw:
        return None, "min"

    withdrawals = db.setdefault("referral_withdrawals", {})
    for item in withdrawals.values():
        if _to_int(item.get("user_id"), 0) == user_id and item.get("status") == "pending":
            return None, "pending"

    next_id = _to_int(db.get("referral_last_withdraw_id"), 0) + 1
    db["referral_last_withdraw_id"] = next_id

    user["referral_bonus"] = 0.0
    user["referral_pending"] = round(_to_float(user.get("referral_pending"), 0.0) + bonus_balance, 2)

    req = {
        "id": next_id,
        "user_id": user_id,
        "amount": bonus_balance,
        "card": referral_card,
        "status": "pending",
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    withdrawals[str(next_id)] = req
    save_db(db)
    return req, None


def admin_adjust_referral_bonus(user_id: int, amount: float, mode: str = "add") -> Tuple[dict | None, str | None]:
    db = load_db()
    user = db.get("users", {}).get(str(user_id))
    if not user:
        return None, "not_found"
    ensure_user_referral_fields(user)

    amount = round(_to_float(amount), 2)
    if amount <= 0:
        return None, "bad_amount"

    current = round(_to_float(user.get("referral_bonus"), 0.0), 2)
    if mode == "sub":
        if current < amount:
            return None, "insufficient"
        user["referral_bonus"] = round(current - amount, 2)
    else:
        user["referral_bonus"] = round(current + amount, 2)
        user["referral_earned_total"] = round(_to_float(user.get("referral_earned_total"), 0.0) + amount, 2)

    logs = db.setdefault("referral_admin_logs", [])
    logs.append({
        "user_id": user_id,
        "mode": mode,
        "amount": amount,
        "at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    })
    save_db(db)
    return user, None


def get_pending_withdrawals(limit: int | None = None) -> list[dict]:
    db = load_db()
    withdrawals = db.get("referral_withdrawals", {})
    pending = [w for w in withdrawals.values() if w.get("status") == "pending"]
    pending.sort(key=lambda x: _to_int(x.get("id"), 0), reverse=True)
    if limit is not None:
        return pending[:limit]
    return pending


def get_withdraw_request(req_id: int) -> dict | None:
    db = load_db()
    return db.get("referral_withdrawals", {}).get(str(req_id))


def approve_withdraw_request(req_id: int, admin_id: int) -> Tuple[dict | None, dict | None, str | None]:
    db = load_db()
    req = db.get("referral_withdrawals", {}).get(str(req_id))
    if not req:
        return None, None, "not_found"
    if req.get("status") != "pending":
        return req, None, "already_processed"

    user = db.get("users", {}).get(str(req.get("user_id")))
    if not user:
        req["status"] = "approved"
        req["processed_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        req["processed_by"] = admin_id
        save_db(db)
        return req, None, None

    ensure_user_referral_fields(user)
    amount = _to_float(req.get("amount"), 0.0)
    user["referral_pending"] = round(max(0.0, _to_float(user.get("referral_pending"), 0.0) - amount), 2)

    req["status"] = "approved"
    req["processed_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    req["processed_by"] = admin_id
    save_db(db)
    return req, user, None


def reject_withdraw_request(req_id: int, admin_id: int) -> Tuple[dict | None, dict | None, str | None]:
    db = load_db()
    req = db.get("referral_withdrawals", {}).get(str(req_id))
    if not req:
        return None, None, "not_found"
    if req.get("status") != "pending":
        return req, None, "already_processed"

    user = db.get("users", {}).get(str(req.get("user_id")))
    if user:
        ensure_user_referral_fields(user)
        amount = _to_float(req.get("amount"), 0.0)
        user["referral_pending"] = round(max(0.0, _to_float(user.get("referral_pending"), 0.0) - amount), 2)
        user["referral_bonus"] = round(_to_float(user.get("referral_bonus"), 0.0) + amount, 2)

    req["status"] = "rejected"
    req["processed_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    req["processed_by"] = admin_id
    save_db(db)
    return req, user, None
