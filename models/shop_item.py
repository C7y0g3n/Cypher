from dataclasses import dataclass
from typing import Optional


@dataclass
class ShopItem:
    item_id: int
    guild_id: int
    name: str
    type: str
    cost: int
    role_id: Optional[int] = None
    duration_days: Optional[int] = None
    stock: Optional[int] = None
    active: bool = True
