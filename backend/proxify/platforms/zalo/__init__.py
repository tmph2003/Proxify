"""
Zalo Platform Package — export singleton `zalo_db`.

Usage:
    from proxify.platforms.zalo import zalo_db

    zalo_db.groups.upsert(...)
    zalo_db.users.upsert(...)
    zalo_db.jobs.create(...)
    stats = zalo_db.get_stats()
"""

from .database import ZaloDatabase

# Singleton instance
zalo_db = ZaloDatabase()

__all__ = ["zalo_db", "ZaloDatabase"]
