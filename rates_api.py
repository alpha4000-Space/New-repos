
import aiohttp
import logging
from datetime import datetime
from database import load_db, save_db

log = logging.getLogger(__name__)
BINANCE_SYMBOLS = {
    "usdt_trc20":  "USDTUSDT",   # 1:1
    "usdt_bep20":  "USDTUSDT",   # 1:1
    "binance_p2p": "BNBUSDT",
    "tron":        "TRXUSDT",
    "sui":         "SUIUSDT",
    "bnb":         "BNBUSDT",
    "polygon":     "MATICUSDT",
    "solana":      "SOLUSDT",
    "litecoin":    "LTCUSDT",
    "dogecoin":    "DOGEUSDT",
    "toncoin":     "TONUSDT",
}

# USDT narxi har doim 1 USD
FIXED_USD = {
    "usdt_trc20": 1.0,
    "usdt_bep20": 1.0,
}


async def fetch_usd_uzs() -> float:
    try:
        url = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json(content_type=None)
                for item in data:
                    if item.get("Ccy") == "USD":
                        val = float(item["Rate"])
                        log.info(f"CBU USD/UZS: {val}")
                        return val
    except Exception as e:
        log.warning(f"CBU xato: {e}")
    return 12700.0   # fallback


async def fetch_binance_prices() -> dict:
    try:
        # Barcha ticker narxlarini bir so'rovda olamiz
        url = "https://api.binance.com/api/v3/ticker/price"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    log.warning(f"Binance status: {r.status}")
                    return {}
                data = await r.json()
                # {symbol: price} dict
                prices = {item["symbol"]: float(item["price"]) for item in data}
                log.info(f"Binance narxlar olindi: {len(prices)} ta")
                return prices
    except Exception as e:
        log.warning(f"Binance API xato: {e}")
        return {}


async def update_live_rates() -> dict:

    db       = load_db()
    settings = db.get("rate_settings", {})
    old_live = db.get("live_rates", {})

    # 1. USD/UZS
    usd_uzs = await fetch_usd_uzs()

    # 2. Binance narxlari
    binance = await fetch_binance_prices()

    live_rates = {}

    for cur_id, symbol in BINANCE_SYMBOLS.items():
        # USD narxini aniqlash
        if cur_id in FIXED_USD:
            usd_price = FIXED_USD[cur_id]
        elif symbol in binance:
            usd_price = binance[symbol]
        else:
            # Eski narxni saqlash
            if cur_id in old_live:
                live_rates[cur_id] = old_live[cur_id]
                log.warning(f"{cur_id}: Binance da topilmadi, eski narx saqlandi")
            continue

        # 1 kripto = ? so'm (xom, foizsiz)
        raw_uzs = usd_price * usd_uzs

        # Admin foizlari
        sell_markup = float(settings.get(f"{cur_id}_sell_markup", 0.0))
        buy_markup  = float(settings.get(f"{cur_id}_buy_markup",  0.0))
        sell_rate = round(raw_uzs * (1 - buy_markup  / 100))

        buy_rate  = round(raw_uzs * (1 + sell_markup / 100))

        live_rates[cur_id] = {
            "usd_price": round(usd_price, 8),
            "usd_uzs":   round(usd_uzs,   2),
            "raw_uzs":   round(raw_uzs),
            "sell_rate": sell_rate,
            "buy_rate":  buy_rate,
        }

    db["live_rates"]       = live_rates
    db["last_rate_update"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    save_db(db)
    log.info(f"Kurslar yangilandi: {len(live_rates)} ta | USD/UZS: {usd_uzs}")
    return live_rates


def get_live_rates() -> dict:
    return load_db().get("live_rates", {})


def get_rates_text(lang: str = "uz") -> str:

    db       = load_db()
    live     = db.get("live_rates", {})
    last_upd = db.get("last_rate_update", "—")

    if not live:
        return "⏳ Kurslar yuklanmoqda..." if lang == "uz" else "⏳ Загрузка курсов..."

    from exchange_config import CURRENCIES

    sell_lines = []
    buy_lines  = []

    for cur in CURRENCIES:
        cid = cur["id"]
        if cid in ("uzcard", "humo"):
            continue
        r = live.get(cid)
        if not r:
            continue
        sell_lines.append(f"1 {cur['name']} = {r['sell_rate']:,} SO'M")
        buy_lines.append( f"1 {cur['name']} = {r['buy_rate']:,} SO'M")

    sell_block = "\n".join(sell_lines) or "—"
    buy_block  = "\n".join(buy_lines)  or "—"

    if lang == "uz":
        return (
            f"📈 Sotish kurslari\n"
            f"{sell_block}\n\n"
            f"📉 Sotib olish kurslari\n"
            f"{buy_block}\n\n"
            f"🕐 Yangilangan: {last_upd}"
        )
    else:
        return (
            f"📈 Курсы продажи\n"
            f"{sell_block}\n\n"
            f"📉 Курсы покупки\n"
            f"{buy_block}\n\n"
            f"🕐 Обновлено: {last_upd}"
        )


def get_effective_rate(from_id: str, to_id: str) -> dict | None:
    db       = load_db()
    live     = db.get("live_rates", {})
    settings = db.get("rate_settings", {})

    def s_min(cid):  return int(settings.get(f"{cid}_min",  10000 if cid in ("uzcard","humo") else 1))
    def s_max(cid):  return int(settings.get(f"{cid}_max",  500_000_000 if cid in ("uzcard","humo") else 100_000))
    def s_comm(cid): return float(settings.get(f"{cid}_commission", 1.0))
    def s_sell(cid): return float(settings.get(f"{cid}_sell_markup", 0.0))
    def s_buy(cid):  return float(settings.get(f"{cid}_buy_markup",  0.0))

    from exchange_config import get_currency_by_id, DEFAULT_RATES
    def cn(cid):
        c = get_currency_by_id(cid)
        return c["name"] if c else cid

    # ── MANUAL KURS — BIRINCHI TEKSHIRILADI ──
    manual = db.get("manual_rates", {})
    key    = f"{from_id}:{to_id}"
    info   = manual.get(key) or DEFAULT_RATES.get(key)
    if info:
        rate = float(info["rate"])
        if rate >= 1:
            disp = f"1 {cn(from_id)} = {round(rate):,} {cn(to_id)}"
        else:
            disp = f"1 {cn(to_id)} = {round(1/rate):,} {cn(from_id)}" if rate > 0 else f"{rate}"
        return {
            "rate":         rate,
            "rate_display": disp,
            "min":          info.get("min",  s_min(from_id)),
            "max":          info.get("max",  s_max(from_id)),
            "commission":   info.get("commission", s_comm(from_id)),
        }

    # ── KARTA → KRIPTO ──
    if from_id in ("uzcard", "humo") and to_id in live:
        base_buy_uzs = float(live[to_id]["buy_rate"])
        # Karta bo'yicha qo'shimcha sotish foizi (user so'm beradi, kripto oladi)
        buy_uzs = base_buy_uzs * (1 + s_sell(from_id) / 100)
        if buy_uzs <= 0:
            return None
        rate = 1 / buy_uzs
        return {
            "rate":         rate,
            "rate_display": f"1 {cn(to_id)} = {round(buy_uzs):,} SO'M",
            "min":          s_min(from_id),
            "max":          s_max(from_id),
            "commission":   s_comm(to_id),
        }

    # ── KRIPTO → KARTA ──
    if from_id in live and to_id in ("uzcard", "humo"):
        base_sell_uzs = float(live[from_id]["sell_rate"])
        # Karta bo'yicha qo'shimcha sotib olish foizi (user kripto beradi, so'm oladi)
        sell_uzs = base_sell_uzs * (1 - s_buy(to_id) / 100)
        if sell_uzs <= 0:
            return None
        return {
            "rate":         sell_uzs,
            "rate_display": f"1 {cn(from_id)} = {round(sell_uzs):,} SO'M",
            "min":          s_min(from_id),
            "max":          s_max(from_id),
            "commission":   s_comm(from_id),
        }

    # ── KRIPTO → KRIPTO ──
    if from_id in live and to_id in live:
        f_usd = live[from_id]["usd_price"]
        t_usd = live[to_id]["usd_price"]
        if t_usd == 0:
            return None
        rate = f_usd / t_usd
        return {
            "rate":         rate,
            "rate_display": f"1 {cn(from_id)} ≈ {round(rate, 6)} {cn(to_id)}",
            "min":          s_min(from_id),
            "max":          s_max(from_id),
            "commission":   s_comm(from_id),
        }

    return None
