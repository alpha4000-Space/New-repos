
CURRENCIES = [
    {"id": "uzcard",      "name": "UZCARD",        "icon": "💎", "type": "card"},
    {"id": "humo",        "name": "HUMO",           "icon": "💎", "type": "card"},
    {"id": "usdt_trc20",  "name": "USDT (Trc20)",   "icon": "💎", "type": "crypto"},
    {"id": "usdt_bep20",  "name": "USDT (Bep20)",   "icon": "💎", "type": "crypto"},
    {"id": "binance_p2p", "name": "Binance P2P",    "icon": "💎", "type": "crypto"},
    {"id": "tron",        "name": "Tron (TRX)",     "icon": "💎", "type": "crypto"},
    {"id": "sui",         "name": "Sui (SUI)",      "icon": "💎", "type": "crypto"},
    {"id": "bnb",         "name": "Bnb (BNB)",      "icon": "💎", "type": "crypto"},
    {"id": "polygon",     "name": "POLYGON",        "icon": "💎", "type": "crypto"},
    {"id": "solana",      "name": "SOLANA",         "icon": "💎", "type": "crypto"},
    {"id": "litecoin",    "name": "LITECOIN",       "icon": "💎", "type": "crypto"},
    {"id": "dogecoin",    "name": "DOGECOIN",       "icon": "💎", "type": "crypto"},
    {"id": "toncoin",     "name": "TONCOIN",        "icon": "💎", "type": "crypto"},
]
DEFAULT_RATES = {
    "uzcard:usdt_trc20":  {"rate": 0.000075, "min": 100000,  "max": 500000000, "commission": 1.0},
    "usdt_trc20:uzcard":  {"rate": 12800,    "min": 1,       "max": 10000,     "commission": 1.0},
    "humo:usdt_trc20":    {"rate": 0.000075, "min": 100000,  "max": 500000000, "commission": 1.0},
    "usdt_trc20:humo":    {"rate": 12800,    "min": 1,       "max": 10000,     "commission": 1.0},
    "uzcard:humo":        {"rate": 1.0,      "min": 10000,   "max": 50000000,  "commission": 0.5},
    "humo:uzcard":        {"rate": 1.0,      "min": 10000,   "max": 50000000,  "commission": 0.5},
    "uzcard:usdt_bep20":  {"rate": 0.000075, "min": 100000,  "max": 500000000, "commission": 1.0},
    "usdt_trc20:usdt_bep20": {"rate": 1.0,  "min": 1,       "max": 10000,     "commission": 0.5},
}

PAYMENT_CARDS = {
    "uzcard": "8600 1666 0393 7029",
    "humo":   "9860 0000 0000 0000",
}

def get_currency_by_id(currency_id: str) -> dict | None:
    for c in CURRENCIES:
        if c["id"] == currency_id:
            return c
    return None

def get_rate_key(from_id: str, to_id: str) -> str:
    return f"{from_id}:{to_id}"
