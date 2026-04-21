import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
GUILD_ID: int = int(os.getenv("GUILD_ID", "0") or "0")
PREFIX: str = os.getenv("PREFIX", "!")
DB_PATH: str = os.getenv("DB_PATH", "./data/cypher.db")

LOG_CHANNEL_ID: int = int(os.getenv("LOG_CHANNEL_ID", "0") or "0")
RANKUP_CHANNEL_ID: int = int(os.getenv("RANKUP_CHANNEL_ID", "0") or "0")
WELCOME_CHANNEL_ID: int = int(os.getenv("WELCOME_CHANNEL_ID", "0") or "0")

MSG_XP_MIN: int = int(os.getenv("MSG_XP_MIN", "15"))
MSG_XP_MAX: int = int(os.getenv("MSG_XP_MAX", "25"))
VOICE_XP_RATE: int = int(os.getenv("VOICE_XP_RATE", "5"))

DAILY_CREDITS: int = int(os.getenv("DAILY_CREDITS", "150"))
MSG_CREDITS_PER_MSG: int = int(os.getenv("MSG_CREDITS_PER_MSG", "5"))
VOICE_CREDITS_PER_HOUR: int = int(os.getenv("VOICE_CREDITS_PER_HOUR", "30"))

# Rank tiers: level -> (name, xp_threshold)
RANK_THRESHOLDS: dict[int, tuple[str, int]] = {
    0: ("New Signal", 0),
    1: ("Data Runner", 500),
    2: ("Code Walker", 1500),
    3: ("Neon Operative", 4000),
    4: ("Cypher Elite", 9000),
    5: ("System Architect", 18000),
    6: ("The Overclocked", 35000),
}

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")

CONFIG_DEFAULTS: dict[str, str] = {
    "log_channel_id": str(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else "",
    "rankup_channel_id": str(RANKUP_CHANNEL_ID) if RANKUP_CHANNEL_ID else "",
    "welcome_channel_id": str(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else "",
    "prefix": PREFIX,
    "xp_multiplier": "1.0",
    "daily_amount": str(DAILY_CREDITS),
    "voice_xp_rate": str(VOICE_XP_RATE),
    "msg_xp_min": str(MSG_XP_MIN),
    "msg_xp_max": str(MSG_XP_MAX),
    "event_bonus_active": "false",
    "mod_role_id": "",
    "admin_role_id": "",
}
