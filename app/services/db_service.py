"""
Database service layer for placement pipeline.

This module provides CRUD operations with smart upsert logic:
- save_email: Insert or update email by gmail_message_id
- upsert_placement_drive: Smart upsert for placement drives
- process_email_to_db: Full pipeline orchestration
- Dashboard queries with filtering
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, or_
from datetime import datetime
from typing import Optional

from app.models.email import Email
from app.models.placement_drive import PlacementDrive


# ============ EMAIL OPERATIONS ============

def save_email(
    db: Session,
    gmail_message_id: str,
    sender: str,
    subject: str,
    raw_body: str,
    received_at: datetime = None
) -> Email:
    """
    Save email with upsert logic.
    
    If email with same gmail_message_id exists, return existing.
    Otherwise, create new email record.
    
    Args:
        db: Database session
        gmail_message_id: Unique Gmail message ID
        sender: Sender email address
        subject: Email subject line
        raw_body: Full email body (HTML or text)
        received_at: When Gmail received the email
        
    Returns:
        Email: Existing or newly created email record
    """
    # Check if email already exists (deduplication)
    existing = db.query(Email).filter(
        Email.gmail_message_id == gmail_message_id
    ).first()
    
    if existing:
        return existing
    
    # Create new email record
    email = Email(
        gmail_message_id=gmail_message_id,
        sender=sender,
        subject=subject,
        raw_body=raw_body,
        received_at=received_at or datetime.utcnow()
    )
    
    db.add(email)
    
    try:
        db.commit()
        db.refresh(email)
        return email
    except IntegrityError:
        # Race condition - another request created it
        db.rollback()
        return db.query(Email).filter(
            Email.gmail_message_id == gmail_message_id
        ).first()


# ============ PLACEMENT DRIVE OPERATIONS ============

def upsert_placement_drive(
    db: Session,
    company_name: str,
    source_email_id: int = None,
    company_logo: str = None,
    role: str = None,
    drive_type: str = None,
    batch: str = None,
    drive_date: datetime = None,
    registration_deadline: datetime = None,
    eligible_branches: str = None,
    min_cgpa: float = None,
    eligibility_text: str = None,
    ctc_or_stipend: str = None,
    job_location: str = None,
    registration_link: str = None,
    status: str = "upcoming",
    confidence_score: float = 1.0,
    official_source: str = "TPO Email"
) -> PlacementDrive:
    """
    Insert or update placement drive.
    
    Upsert logic:
    - If drive with same (company_name, batch, role) exists → update
    - Otherwise → create new drive
    
    This prevents duplicate drives from re-processed emails.
    """
    # Normalize company name
    normalized_company = company_name.strip().title()
    
    # Look for existing drive with same company + batch + role
    existing = db.query(PlacementDrive).filter(
        func.lower(PlacementDrive.company_name) == normalized_company.lower(),
        PlacementDrive.batch == batch,
        PlacementDrive.role == role
    ).first()
    
    if existing:
        # Update existing drive with new info (only non-null values)
        existing.source_email_id = source_email_id or existing.source_email_id
        existing.company_logo = company_logo or existing.company_logo
        existing.drive_type = drive_type or existing.drive_type
        existing.drive_date = drive_date or existing.drive_date
        existing.registration_deadline = registration_deadline or existing.registration_deadline
        existing.eligible_branches = eligible_branches or existing.eligible_branches
        existing.min_cgpa = min_cgpa if min_cgpa is not None else existing.min_cgpa
        existing.eligibility_text = eligibility_text or existing.eligibility_text
        existing.ctc_or_stipend = ctc_or_stipend or existing.ctc_or_stipend
        existing.job_location = job_location or existing.job_location
        existing.registration_link = registration_link or existing.registration_link
        existing.status = status
        existing.confidence_score = confidence_score
        existing.official_source = official_source
        # last_updated auto-updates via onupdate
        
        db.commit()
        db.refresh(existing)
        return existing
    
    # Create new drive
    drive = PlacementDrive(
        company_name=normalized_company,
        source_email_id=source_email_id,
        company_logo=company_logo,
        role=role,
        drive_type=drive_type,
        batch=batch,
        drive_date=drive_date,
        registration_deadline=registration_deadline,
        eligible_branches=eligible_branches,
        min_cgpa=min_cgpa,
        eligibility_text=eligibility_text,
        ctc_or_stipend=ctc_or_stipend,
        job_location=job_location,
        registration_link=registration_link,
        status=status,
        confidence_score=confidence_score,
        official_source=official_source
    )
    
    db.add(drive)
    db.commit()
    db.refresh(drive)
    return drive


# ============ FULL PIPELINE ============

def process_email_to_db(
    db: Session,
    gmail_message_id: str,
    sender: str,
    subject: str,
    raw_body: str,
    extracted_info: dict,
    received_at: datetime = None
) -> Optional[PlacementDrive]:
    """
    Full pipeline: Save email → Create/update placement drive.
    
    This is the main entry point for the Gmail → DB pipeline.
    
    Args:
        db: Database session
        gmail_message_id: Unique Gmail message ID
        sender: Sender email
        subject: Email subject
        raw_body: Full email body
        extracted_info: Dict with extracted fields:
            - company: Company name (required)
            - role, batch, drive_type, etc.
        received_at: When email was received
        
    Returns:
        PlacementDrive if created/updated, None if extraction was empty
    """
    # Skip if no extracted info or no company
    if not extracted_info or not extracted_info.get("company"):
        return None
    
    # Step 1: Save raw email (internal only)
    email = save_email(
        db=db,
        gmail_message_id=gmail_message_id,
        sender=sender,
        subject=subject,
        raw_body=raw_body,
        received_at=received_at
    )
    
    # Step 2: Create/update placement drive
    drive = upsert_placement_drive(
        db=db,
        company_name=extracted_info["company"],
        source_email_id=email.id,
        company_logo=extracted_info.get("company_logo"),
        role=extracted_info.get("role"),
        drive_type=extracted_info.get("drive_type"),
        batch=extracted_info.get("batch"),
        drive_date=extracted_info.get("drive_date"),
        registration_deadline=extracted_info.get("registration_deadline"),
        eligible_branches=extracted_info.get("eligible_branches"),
        min_cgpa=extracted_info.get("min_cgpa"),
        eligibility_text=extracted_info.get("eligibility_text"),
        ctc_or_stipend=extracted_info.get("ctc_or_stipend"),
        job_location=extracted_info.get("job_location"),
        registration_link=extracted_info.get("registration_link"),
        status=extracted_info.get("status", "upcoming"),
        confidence_score=extracted_info.get("confidence", 1.0),
        official_source="TPO Email"
    )
    
    return drive


# ============ DASHBOARD QUERIES ============

def get_all_drives(
    db: Session,
    skip: int = 0,
    limit: int = 50,
    batch: str = None,
    company_name: str = None,
    status: str = None,
    drive_type: str = None
) -> list[PlacementDrive]:
    """
    Get placement drives with optional filtering.
    
    Args:
        db: Database session
        skip: Offset for pagination
        limit: Max results (default 50)
        batch: Filter by batch (e.g., "2026")
        company_name: Filter by company name (partial match)
        status: Filter by status (upcoming, open, closed)
        drive_type: Filter by type (internship, fte, both)
        
    Returns:
        List of PlacementDrive objects
    """
    query = db.query(PlacementDrive)
    
    # Apply filters
    if batch:
        query = query.filter(PlacementDrive.batch == batch)
    
    if company_name:
        query = query.filter(
            PlacementDrive.company_name.ilike(f"%{company_name}%")
        )
    
    if status:
        query = query.filter(PlacementDrive.status == status)
    
    if drive_type:
        query = query.filter(PlacementDrive.drive_type == drive_type)
    
    # Order by most recent first
    query = query.order_by(PlacementDrive.last_updated.desc())
    
    return query.offset(skip).limit(limit).all()


def get_drives_count(
    db: Session,
    batch: str = None,
    company_name: str = None,
    status: str = None,
    drive_type: str = None
) -> int:
    """Get total count of drives for pagination."""
    query = db.query(func.count(PlacementDrive.id))
    
    if batch:
        query = query.filter(PlacementDrive.batch == batch)
    if company_name:
        query = query.filter(PlacementDrive.company_name.ilike(f"%{company_name}%"))
    if status:
        query = query.filter(PlacementDrive.status == status)
    if drive_type:
        query = query.filter(PlacementDrive.drive_type == drive_type)
    
    return query.scalar()


def get_drive_by_id(db: Session, drive_id: int) -> Optional[PlacementDrive]:
    """Get a single placement drive by ID."""
    return db.query(PlacementDrive).filter(
        PlacementDrive.id == drive_id
    ).first()


def get_unique_companies(db: Session) -> list[str]:
    """Get list of unique company names for filters."""
    results = db.query(PlacementDrive.company_name).distinct().order_by(
        PlacementDrive.company_name
    ).all()
    return [r[0] for r in results]


def get_unique_batches(db: Session) -> list[str]:
    """Get list of unique batches for filters."""
    results = db.query(PlacementDrive.batch).distinct().order_by(
        PlacementDrive.batch.desc()
    ).all()
    return [r[0] for r in results if r[0]]
