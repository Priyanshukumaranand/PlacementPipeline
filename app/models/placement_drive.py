"""
PlacementDrive model - the main dashboard-facing table.

This stores student-friendly, actionable placement information.
Designed for direct rendering on iiit-bbsr-network.vercel.app/placement

Card View Fields:
- company_name, company_logo, role, batch, deadline badge, status badge

Expanded View Fields:
- eligibility, CTC/stipend, location, apply link, source info
"""

from sqlalchemy import (
    Column, Integer, String, Date, Float, Text,
    ForeignKey, DateTime, Index, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class DriveStatus(str, enum.Enum):
    """Status of a placement drive."""
    UPCOMING = "upcoming"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class DriveType(str, enum.Enum):
    """Type of placement opportunity."""
    INTERNSHIP = "internship"
    FTE = "fte"
    BOTH = "both"


class PlacementDrive(Base):
    """
    Student-facing placement drive information.
    
    This is the primary table for dashboard rendering.
    Each row = one placement card on the website.
    """
    __tablename__ = "placement_drives"

    id = Column(Integer, primary_key=True)

    # ============ COMPANY INFO (Card Header) ============
    company_name = Column(String(255), nullable=False, index=True)
    company_logo = Column(String(512))  # URL to logo image
    
    # ============ ROLE & TYPE ============
    role = Column(String(255))  # e.g., "SDE Intern" or "SDE, Data Analyst" for multiple
    drive_type = Column(String(50))  # "internship", "fte", "both"
    
    # ============ TARGETING ============
    batch = Column(String(20), index=True)  # e.g., "2026", "2025"
    
    # ============ DATES (Badge Display) ============
    drive_date = Column(Date)  # When drive happens
    registration_deadline = Column(DateTime)  # Deadline for applications
    
    # ============ ELIGIBILITY (Expanded View) ============
    eligible_branches = Column(String(512))  # e.g., "CSE, IT, ECE"
    min_cgpa = Column(Float)  # e.g., 7.0
    eligibility_text = Column(Text)  # Full eligibility criteria text
    
    # ============ COMPENSATION ============
    ctc_or_stipend = Column(String(255))  # e.g., "₹12 LPA" or "₹40K/month"
    
    # ============ LOCATION & APPLY ============
    job_location = Column(String(255))  # e.g., "Bangalore, India"
    registration_link = Column(String(512))  # URL to apply
    
    # ============ STATUS & METADATA ============
    status = Column(String(20), default="upcoming", index=True)  # upcoming, open, closed, cancelled
    confidence_score = Column(Float, default=1.0)  # 0.0-1.0 extraction confidence
    official_source = Column(String(255))  # e.g., "TPO Email", "Company Portal"
    
    # ============ INTERNAL TRACKING ============
    source_email_id = Column(Integer, ForeignKey("emails.id"))
    created_at = Column(DateTime, server_default=func.now())
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationship to source email (internal use only)
    email = relationship("Email")

    # Indexes for common dashboard queries
    __table_args__ = (
        Index("ix_drives_batch_status", "batch", "status"),
        Index("ix_drives_company_batch", "company_name", "batch"),
        Index("ix_drives_deadline", "registration_deadline"),
    )

    def __repr__(self):
        return f"<PlacementDrive(id={self.id}, company={self.company_name}, role={self.role})>"
    
    def to_card_dict(self) -> dict:
        """Return fields needed for card view."""
        return {
            "id": self.id,
            "company_name": self.company_name,
            "company_logo": self.company_logo,
            "role": self.role,
            "drive_type": self.drive_type,
            "batch": self.batch,
            "registration_deadline": self.registration_deadline.isoformat() if self.registration_deadline else None,
            "status": self.status
        }
    
    def to_full_dict(self) -> dict:
        """Return all fields for expanded view."""
        return {
            **self.to_card_dict(),
            "drive_date": self.drive_date.isoformat() if self.drive_date else None,
            "eligible_branches": self.eligible_branches,
            "min_cgpa": self.min_cgpa,
            "eligibility_text": self.eligibility_text,
            "ctc_or_stipend": self.ctc_or_stipend,
            "job_location": self.job_location,
            "registration_link": self.registration_link,
            "confidence_score": self.confidence_score,
            "official_source": self.official_source,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
        }
