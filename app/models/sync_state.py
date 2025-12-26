"""
SyncState model for storing persistent sync metadata.

Used to store:
- gmail_history_id: Last processed Gmail historyId for incremental sync
"""

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.database import Base


class SyncState(Base):
    """
    Key-value store for sync state metadata.
    
    Persists across server restarts, unlike in-memory variables.
    """
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    value = Column(String(255))
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SyncState(key={self.key}, value={self.value})>"
