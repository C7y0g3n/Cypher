from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    user_id: int
    guild_id: int
    xp: int = 0
    level: int = 0
    credits: int = 0
    total_earned: int = 0
    last_daily: Optional[str] = None
    daily_streak: int = 0
    last_xp_msg: Optional[str] = None
    voice_joined_at: Optional[str] = None
    created_at: str = ""
