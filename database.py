import json
import os
from config import DB_FILE

def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "channels": []}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(user_id: int):
    db = load_db()
    return db["users"].get(str(user_id))

def save_user(user_id: int, user_data: dict):
    db = load_db()
    db["users"][str(user_id)] = user_data
    save_db(db)

def get_channels():
    db = load_db()
    return db.get("channels", [])

def add_channel(channel_id: int, channel_link: str, channel_name: str):
    db = load_db()
    # Check if already exists
    for ch in db["channels"]:
        if ch["channel_id"] == channel_id:
            return False
    db["channels"].append({
        "channel_id": channel_id,
        "channel_link": channel_link,
        "channel_name": channel_name
    })
    save_db(db)
    return True

def remove_channel(channel_id: int):
    db = load_db()
    before = len(db["channels"])
    db["channels"] = [ch for ch in db["channels"] if ch["channel_id"] != channel_id]
    save_db(db)
    return len(db["channels"]) < before

def get_all_users():
    db = load_db()
    return db["users"]
