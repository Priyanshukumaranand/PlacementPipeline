"""
Debug endpoints for testing Gmail integration and extraction pipeline.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.services.gmail_service import get_gmail_service, get_full_message
from app.services.email_extractor import extract_placement_info
from app.services import db_service
from app.database import get_db

router = APIRouter(prefix="/debug", tags=["Debug"])


@router.get("/gmail")
def test_gmail_read():
    """
    Test endpoint to verify Gmail API integration.

    Fetches the 5 most recent emails and returns basic metadata.
    On first request, triggers OAuth flow (browser opens for authentication).

    Returns:
        dict: Count and list of emails with ID, sender, and subject
    """
    # Get authenticated Gmail service
    service = get_gmail_service()

    # List most recent messages
    results = service.users().messages().list(
        userId="me",
        maxResults=5
    ).execute()

    messages = results.get("messages", [])

    response = []

    # Fetch metadata for each message
    for msg in messages:
        data = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata"
        ).execute()

        # Extract headers
        headers = data["payload"]["headers"]
        subject = sender = None

        for h in headers:
            if h["name"] == "Subject":
                subject = h["value"]
            if h["name"] == "From":
                sender = h["value"]

        response.append({
            "id": msg["id"],
            "from": sender,
            "subject": subject
        })

    return {
        "count": len(response),
        "emails": response
    }


@router.get("/gmail/sample")
def get_sample_email(db: Session = Depends(get_db)):
    """
    Get one sample email to see the full data structure.
    
    This is for TESTING ONLY - shows how email data is stored.
    Returns the first email from the database with full body content.
    """
    from app.models import Email
    
    email = db.query(Email).first()
    if not email:
        return {"error": "No emails stored in database"}
    
    return {
        "id": email.id,
        "gmail_message_id": email.gmail_message_id,
        "sender": email.sender,
        "subject": email.subject,
        "raw_body": email.raw_body[:3000] + "..." if email.raw_body and len(email.raw_body) > 3000 else email.raw_body,
        "body_length": len(email.raw_body) if email.raw_body else 0,
        "created_at": email.created_at.isoformat() if email.created_at else None
    }



@router.get("/gmail/extract")
def extract_from_latest(db: Session = Depends(get_db), batch_size: int = 50):
    """
    Extract placement information from ALL emails sent by placement coordinators
    and SAVE them to the database.

    Uses pagination to avoid timeout. Run multiple times to process all emails.

    Args:
        batch_size: Number of emails to process per request (default 50)

    Returns:
        dict: Summary of extraction with saved companies
    """
    # Get authenticated Gmail service
    service = get_gmail_service()

    # Gmail query to filter placement coordinator emails
    query = (
        "from:(navanita@iiit-bh.ac.in OR "
        "rajashree@iiit-bh.ac.in OR "
        "placement@iiit-bh.ac.in)"
    )

    # Search for messages matching the query
    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=batch_size
    ).execute()

    messages = results.get("messages", [])
    
    emails_saved = 0
    new_emails = 0
    drives_saved = []
    skipped = 0

    # Process each message
    for msg in messages:
        msg_id = msg["id"]
        
        # Check if already processed
        from app.models import Email
        existing = db.query(Email).filter(Email.gmail_message_id == msg_id).first()
        if existing:
            skipped += 1
            continue
        
        # Get full message with body content
        mail = get_full_message(service, msg_id)

        # Save email to database
        email = db_service.save_email(
            db=db,
            gmail_message_id=msg_id,
            sender=mail["from"],
            subject=mail["subject"],
            raw_body=mail["body"]
        )
        new_emails += 1
        emails_saved += 1

        # Extract placement information
        info = extract_placement_info(mail["subject"], mail["body"])

        # Only save if extraction was successful AND has company name
        if info and info.get("company"):
            drive = db_service.upsert_placement_drive(
                db=db,
                company_name=info["company"],
                source_email_id=email.id,
                role=info.get("role"),
                batch=info.get("batch"),
                official_source="TPO Email"
            )
            
            if info["company"] not in drives_saved:
                drives_saved.append(info["company"])

    return {
        "total_found": len(messages),
        "already_processed": skipped,
        "new_emails_saved": new_emails,
        "placements_saved": len(drives_saved),
        "companies": drives_saved
    }


@router.get("/db/stats")
def get_db_stats(db: Session = Depends(get_db)):
    """Get database statistics with full drive details for dashboard."""
    from app.models import Email, PlacementDrive
    
    email_count = db.query(Email).count()
    drive_count = db.query(PlacementDrive).count()
    
    # Get unique companies
    companies = db.query(PlacementDrive.company_name).distinct().all()
    
    # Get full drive details for scatter plot, ordered by created_at
    drives = db.query(PlacementDrive).order_by(PlacementDrive.created_at.asc()).all()
    
    drives_data = []
    for drive in drives:
        drives_data.append({
            "id": drive.id,
            "company_name": drive.company_name,
            "role": drive.role,
            "ctc_or_stipend": drive.ctc_or_stipend,
            "drive_date": drive.drive_date.isoformat() if drive.drive_date else None,
            "created_at": drive.created_at.isoformat() if drive.created_at else None,
            "status": drive.status,
            "batch": drive.batch
        })
    
    return {
        "emails_stored": email_count,
        "placement_drives": drive_count,
        "unique_companies": [c[0] for c in companies],
        "drives": drives_data
    }


@router.get("/gmail/extract-all")
def extract_all_emails(db: Session = Depends(get_db)):
    """
    Extract ALL placement emails with automatic pagination.
    
    This processes all emails from placement coordinators,
    skipping already-processed ones.
    """
    service = get_gmail_service()
    
    query = (
        "from:(navanita@iiit-bh.ac.in OR "
        "rajashree@iiit-bh.ac.in OR "
        "placement@iiit-bh.ac.in)"
    )
    
    all_messages = []
    page_token = None
    
    # Fetch all message IDs with pagination
    print("📧 Fetching all placement emails...")
    while True:
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=100,
            pageToken=page_token
        ).execute()
        
        messages = results.get("messages", [])
        all_messages.extend(messages)
        
        page_token = results.get("nextPageToken")
        if not page_token:
            break
    
    print(f"📬 Found {len(all_messages)} total emails")
    
    # Process each message
    from app.models import Email
    new_emails = 0
    drives_saved = []
    
    for i, msg in enumerate(all_messages):
        msg_id = msg["id"]
        
        # Skip if already processed
        existing = db.query(Email).filter(Email.gmail_message_id == msg_id).first()
        if existing:
            continue
        
        # Fetch and save
        mail = get_full_message(service, msg_id)
        
        email = db_service.save_email(
            db=db,
            gmail_message_id=msg_id,
            sender=mail["from"],
            subject=mail["subject"],
            raw_body=mail["body"]
        )
        new_emails += 1
        
        # Extract placement info
        info = extract_placement_info(mail["subject"], mail["body"])
        
        if info and info.get("company"):
            db_service.upsert_placement_drive(
                db=db,
                company_name=info["company"],
                source_email_id=email.id,
                role=info.get("role"),
                batch=info.get("batch"),
                official_source="TPO Email"
            )
            if info["company"] not in drives_saved:
                drives_saved.append(info["company"])
                print(f"   ✅ New company: {info['company']}")
        
        # Progress log every 10 emails
        if (i + 1) % 10 == 0:
            print(f"   Processed {i + 1}/{len(all_messages)}")
    
    return {
        "total_emails_found": len(all_messages),
        "new_emails_saved": new_emails,
        "new_companies": len(drives_saved),
        "companies": drives_saved
    }
