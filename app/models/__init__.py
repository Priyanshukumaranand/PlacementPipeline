"""
SQLAlchemy models for the placement pipeline.

This package contains:
- Email: Raw email storage (internal, not exposed to dashboard)
- PlacementDrive: Student-facing placement info (dashboard data)

Note: Company info is embedded directly in PlacementDrive for simplicity.
"""

from app.models.email import Email
from app.models.placement_drive import PlacementDrive

__all__ = ["Email", "PlacementDrive"]
