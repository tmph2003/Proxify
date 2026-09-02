"""
Zalo Data Models — dataclasses cho các entity trong schema `zalo`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ZaloGroup:
    """Một nhóm Zalo."""
    group_id: str
    display_name: str = ""
    total_member: int = 0
    avatar: str = ""
    raw_data: dict = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    db_member_count: int = 0  # computed field (from JOIN)


@dataclass
class ZaloUser:
    """Một user Zalo."""
    user_id: str
    global_id: str = ""
    display_name: str = ""
    avatar: str = ""
    phone: str = ""
    raw_data: dict = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ZaloScanJob:
    """Một job quét nhóm (từ UI)."""
    id: Optional[int] = None
    link: str = ""
    group_id: Optional[str] = None
    status: str = "pending"
    members_found: int = 0
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Serialize thành dict (cho JSON response)."""
        result = {}
        for key in (
            "id", "link", "group_id", "status",
            "members_found", "error_message",
            "created_at", "started_at", "completed_at",
        ):
            val = getattr(self, key, None)
            if isinstance(val, datetime):
                val = val.isoformat()
            result[key] = val
        return result
