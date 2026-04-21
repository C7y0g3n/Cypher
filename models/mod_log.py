from dataclasses import dataclass
from typing import Optional


@dataclass
class ModLog:
    log_id: int
    guild_id: int
    target_id: int
    mod_id: int
    action: str
    reason: str
    duration: Optional[int] = None
    created_at: str = ""
