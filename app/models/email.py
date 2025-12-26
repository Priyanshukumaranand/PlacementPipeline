"""
Email model for storing raw Gmail messages (internal use only).

This is NOT exposed to the dashboard - it's for:
- Audit trail and debugging
- Reprocessing if extraction logic improves
- Deduplication via unique gmail_message_id
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from app.database import Base


class Email(Base):
    """
    Raw email storage - internal, not exposed to students.
    
    Stores original email data from Gmail for traceability
    and potential reprocessing.
    """
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True)
    
    # Gmail identifier (unique - prevents duplicates)
    gmail_message_id = Column(String(64), unique=True, nullable=False, index=True)
    
    # Email metadata
    subject = Column(String(512))
    sender = Column(String(255), index=True)  # renamed from from_email for clarity
    
    # Full content for reprocessing
    raw_body = Column(Text)
    
    # Timestamps
    received_at = Column(DateTime)  # When Gmail received it
    created_at = Column(DateTime, server_default=func.now())  # When we stored it

    def __repr__(self):
        return f"<Email(id={self.id}, sender={self.sender}, subject={self.subject[:30] if self.subject else ''})>"
