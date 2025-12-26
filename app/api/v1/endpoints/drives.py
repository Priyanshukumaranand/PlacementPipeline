"""
Dashboard API endpoints for placement drives.

Designed for iiit-bbsr-network.vercel.app/placement

Card View: company_name, logo, role, batch, deadline, status
Expanded View: eligibility, CTC, location, apply link
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional

from app.database import get_db
from app.services import db_service


router = APIRouter(prefix="/drives", tags=["Dashboard"])


# ============ Response Schemas ============

class DriveCardResponse(BaseModel):
    """Minimal drive data for card view."""
    id: int
    company_name: str
    company_logo: Optional[str]
    role: Optional[str]
    drive_type: Optional[str]
    batch: Optional[str]
    registration_deadline: Optional[datetime]
    status: Optional[str]
    
    class Config:
        from_attributes = True


class DriveFullResponse(BaseModel):
    """Complete drive data for expanded view."""
    id: int
    
    # Card view fields
    company_name: str
    company_logo: Optional[str]
    role: Optional[str]
    drive_type: Optional[str]
    batch: Optional[str]
    registration_deadline: Optional[datetime]
    status: Optional[str]
    
    # Expanded view fields
    drive_date: Optional[date]
    eligible_branches: Optional[str]
    min_cgpa: Optional[float]
    eligibility_text: Optional[str]
    ctc_or_stipend: Optional[str]
    job_location: Optional[str]
    registration_link: Optional[str]
    
    # Metadata
    confidence_score: Optional[float]
    official_source: Optional[str]
    last_updated: Optional[datetime]
    
    class Config:
        from_attributes = True


class DrivesListResponse(BaseModel):
    """Paginated list of placement drives."""
    total: int
    skip: int
    limit: int
    drives: list[DriveCardResponse]


class FiltersResponse(BaseModel):
    """Available filter options for the dashboard."""
    companies: list[str]
    batches: list[str]
    statuses: list[str]
    drive_types: list[str]


# ============ LIST ENDPOINTS ============

@router.get("", response_model=DrivesListResponse)
def list_drives(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    batch: Optional[str] = Query(None, description="Filter by batch, e.g. '2026'"),
    company: Optional[str] = Query(None, description="Filter by company name (partial match)"),
    status: Optional[str] = Query(None, description="Filter by status: upcoming, open, closed"),
    drive_type: Optional[str] = Query(None, description="Filter by type: internship, fte, both"),
    db: Session = Depends(get_db)
):
    """
    List placement drives with optional filtering.
    
    **Query Parameters:**
    - `skip`: Offset for pagination (default 0)
    - `limit`: Max results per page (default 50, max 100)
    - `batch`: Filter by exact batch (e.g., "2026")
    - `company`: Filter by company name (partial match, case-insensitive)
    - `status`: Filter by status (upcoming, open, closed)
    - `drive_type`: Filter by drive type (internship, fte, both)
    
    **Example:**
    ```
    GET /api/v1/drives?batch=2026&status=open
    ```
    """
    drives = db_service.get_all_drives(
        db=db,
        skip=skip,
        limit=limit,
        batch=batch,
        company_name=company,
        status=status,
        drive_type=drive_type
    )
    
    total = db_service.get_drives_count(
        db=db,
        batch=batch,
        company_name=company,
        status=status,
        drive_type=drive_type
    )
    
    return DrivesListResponse(
        total=total,
        skip=skip,
        limit=limit,
        drives=drives
    )


# ============ SINGLE DRIVE ============

@router.get("/{drive_id}", response_model=DriveFullResponse)
def get_drive(drive_id: int, db: Session = Depends(get_db)):
    """
    Get a single placement drive by ID (expanded view).
    
    Returns all fields including eligibility, CTC, location, etc.
    
    **Path Parameters:**
    - `drive_id`: The ID of the placement drive
    
    **Returns:**
    - 200: Complete drive details
    - 404: Drive not found
    """
    drive = db_service.get_drive_by_id(db, drive_id)
    
    if not drive:
        raise HTTPException(
            status_code=404,
            detail=f"Placement drive with ID {drive_id} not found"
        )
    
    return drive


# ============ FILTER OPTIONS ============

@router.get("/filters/options", response_model=FiltersResponse)
def get_filter_options(db: Session = Depends(get_db)):
    """
    Get available filter options for the dashboard.
    
    Returns unique values for:
    - Companies (for dropdown)
    - Batches (for dropdown)
    - Statuses (fixed list)
    - Drive types (fixed list)
    """
    return FiltersResponse(
        companies=db_service.get_unique_companies(db),
        batches=db_service.get_unique_batches(db),
        statuses=["upcoming", "open", "closed", "cancelled"],
        drive_types=["internship", "fte", "both"]
    )
