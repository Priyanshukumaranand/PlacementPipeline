"""
Debug endpoints for testing Gmail integration and extraction pipeline.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.services.gmail_service import get_gmail_service, get_full_message
from app.services.email_extractor import extract_placement_info
from app.services import db_service
from app.database import get_db
import os

router = APIRouter(prefix="/debug", tags=["Debug"])


@router.get("/gmail")
def test_gmail_read():
    """
    Test endpoint to verify Gmail API integration.

    Fetches the 5 most recent emails and returns metadata WITH BODY.
    On first request, triggers OAuth flow (browser opens for authentication).

    Returns:
        dict: Count and list of emails with ID, sender, subject and body
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

    # Fetch full message for each
    for msg in messages:
        mail = get_full_message(service, msg["id"])
        
        response.append({
            "id": msg["id"],
            "from": mail.get("from"),
            "subject": mail.get("subject"),
            "body": mail.get("body", "")[:2000] + "..." if mail.get("body") and len(mail.get("body", "")) > 2000 else mail.get("body")
        })

    return {
        "count": len(response),
        "emails": response
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
    """Get database statistics."""
    from app.models import Email, PlacementDrive
    
    email_count = db.query(Email).count()
    drive_count = db.query(PlacementDrive).count()
    
    # Get unique companies
    companies = db.query(PlacementDrive.company_name).distinct().all()
    
    return {
        "emails_stored": email_count,
        "placement_drives": drive_count,
        "unique_companies": [c[0] for c in companies]
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


@router.get("/gmail/process-pipeline")
def process_with_pipeline(
    db: Session = Depends(get_db),
    batch_size: int = Query(default=1, description="Number of emails to process"),
    use_gemini: bool = Query(default=True, description="Use Gemini for enhanced extraction"),
    save_to_db: bool = Query(default=False, description="Whether to save to database"),
):
    """
    Process emails through the full LangGraph pipeline.
    
    Pipeline nodes (10 steps):
    1. filter_sender - Only TPO coordinators
    2. html_to_text - Clean HTML to plain text
    3. remove_noise - Remove signatures, disclaimers, replies
    4. token_safety - Trim to ~3000 tokens
    5. extract_sections - URLs, dates, numbers
    6. regex_extract - Pattern-based field extraction (ALWAYS runs)
    7. gemini_enhance - Optional AI enhancement (if use_gemini=true)
    8. validation - Normalize and verify data
    9. deduplication - Prevent duplicates
    10. map_to_model - PlacementDrive fields
    
    Returns JSON with extracted fields for each email.
    """
    from app.services.langgraph_pipeline import (
        run_langgraph_pipeline,
        pipeline_result_to_json,
    )
    from app.models import PlacementDrive

    # Gmail query limited to allowed senders
    query = (
        "from:(navanita@iiit-bh.ac.in OR "
        "rajashree@iiit-bh.ac.in OR "
        "placement@iiit-bh.ac.in)"
    )

    service = get_gmail_service()
    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=batch_size,
    ).execute()
    messages = results.get("messages", [])

    if not messages:
        return {
            "status": "no_emails",
            "message": "No emails found from allowed senders",
            "processed": []
        }

    # Step 1: Store all emails from TPO senders in Email table
    from app.models import Email
    emails_stored = 0
    for msg in messages:
        # Check if already stored
        existing = db.query(Email).filter(Email.gmail_message_id == msg["id"]).first()
        if not existing:
            mail = get_full_message(service, msg["id"])
            email_record = Email(
                gmail_message_id=msg["id"],
                subject=mail.get("subject", ""),
                sender=mail.get("from", ""),
                raw_body=mail.get("body", ""),
            )
            db.add(email_record)
            emails_stored += 1
    db.commit()

    # Step 2: Get all stored placement emails and process with LangGraph
    from app.models import PlacementDrive
    stored_emails = db.query(Email).filter(
        Email.sender.ilike("%navanita@iiit-bh.ac.in%") |
        Email.sender.ilike("%rajashree@iiit-bh.ac.in%") |
        Email.sender.ilike("%placement@iiit-bh.ac.in%")
    ).all()

    # Existing drives for deduplication
    existing_drives_query = db.query(PlacementDrive).all()
    existing_drives = [
        {
            "company_name": d.company_name,
            "role": d.role,
            "registration_deadline": d.registration_deadline.isoformat() if d.registration_deadline else None,
        }
        for d in existing_drives_query
    ]

    api_key = os.getenv("GOOGLE_API_KEY")
    processed_results = []
    
    for email in stored_emails:
        # Run LangGraph pipeline on stored emails
        final_state = run_langgraph_pipeline(
            email_id=str(email.id),
            gmail_message_id=email.gmail_message_id,
            sender=email.sender or "",
            subject=email.subject or "",
            raw_body=email.raw_body or "",
            existing_drives=existing_drives,
            api_key=api_key,
            use_gemini=use_gemini,
        )
        
        # Skip filtered emails
        if final_state.get("status") == "filtered":
            continue
        
        processed_results.append(pipeline_result_to_json(final_state))

    # Merge results from same company for most accurate data
    def merge_company_results(results):
        """Combine results from multiple emails of same company."""
        company_map = {}
        
        for result in results:
            company = result.get("validated_data", {}).get("company_name")
            if not company:
                continue
            
            company_key = company.lower().strip()
            
            if company_key not in company_map:
                company_map[company_key] = result.copy()
            else:
                # Merge: fill in nulls from other emails
                existing = company_map[company_key]
                for field in ["role", "drive_type", "batch", "drive_date", 
                              "registration_deadline", "eligible_branches",
                              "min_cgpa", "eligibility_text", "ctc_or_stipend",
                              "job_location", "registration_link"]:
                    existing_val = existing.get("validated_data", {}).get(field)
                    new_val = result.get("validated_data", {}).get(field)
                    if not existing_val and new_val:
                        existing["validated_data"][field] = new_val
                        existing["extracted_data"][field] = new_val
                
                # Take higher confidence
                existing_conf = existing.get("validated_data", {}).get("confidence_score", 0)
                new_conf = result.get("validated_data", {}).get("confidence_score", 0)
                if new_conf > existing_conf:
                    existing["validated_data"]["confidence_score"] = new_conf
        
        return list(company_map.values())
    
    merged_results = merge_company_results(processed_results)

    # Save to database if requested
    saved_count = 0
    # Filter out fake company names before saving
    def is_valid_company(name):
        """Check if company_name looks like a real company."""
        if not name or len(name) < 3:
            return False
        name_lower = name.lower()
        # Blacklist generic phrases
        blacklist = [
            "campus drive", "recruitment drive", "placement", "important notice",
            "batch", "welcome", "continued participation", "students", "reminder",
            "absentees", "shortlist", "interview", "test result", "announcement",
            "registration", "urgent", "follow up", "the batch", "all students",
            "assessment", "online test", "technical round", "hr round",
            "internship program", "session 2025", "session 2026", "passout",
            "software developer", "software engineer", "associate system", "intern"
        ]
        if any(bl in name_lower for bl in blacklist):
            return False
        # Must have at least one capital letter (proper noun)
        if not any(c.isupper() for c in name):
            return False
        # Too long is suspicious
        if len(name) > 50:
            return False
        return True
    
    if save_to_db:
        from datetime import datetime
        for result in merged_results:
            vd = result.get("validated_data", {})
            company_name = vd.get("company_name")
            
            # Validate company name
            if not company_name or not is_valid_company(company_name):
                continue
            
            # Check if already exists (by company + batch)
            existing = db.query(PlacementDrive).filter(
                PlacementDrive.company_name == company_name,
                PlacementDrive.batch == vd.get("batch")
            ).first()
            
            if existing:
                # Update existing record with new data
                for field in ["role", "drive_type", "drive_date", "registration_deadline",
                              "eligible_branches", "min_cgpa", "eligibility_text",
                              "ctc_or_stipend", "job_location", "registration_link"]:
                    new_val = vd.get(field)
                    if new_val and not getattr(existing, field, None):
                        setattr(existing, field, new_val)
                # Update confidence if higher
                if vd.get("confidence_score", 0) > (existing.confidence_score or 0):
                    existing.confidence_score = vd.get("confidence_score")
            else:
                # Create new record
                drive = PlacementDrive(
                    company_name=company_name,
                    role=vd.get("role"),
                    drive_type=vd.get("drive_type"),
                    batch=vd.get("batch"),
                    eligible_branches=vd.get("eligible_branches"),
                    min_cgpa=vd.get("min_cgpa"),
                    eligibility_text=vd.get("eligibility_text"),
                    ctc_or_stipend=vd.get("ctc_or_stipend"),
                    job_location=vd.get("job_location"),
                    registration_link=vd.get("registration_link"),
                    status=vd.get("status", "upcoming"),
                    confidence_score=vd.get("confidence_score", 0.5),
                    official_source="TPO Email"
                )
                # Parse dates if present
                if vd.get("registration_deadline"):
                    try:
                        drive.registration_deadline = datetime.strptime(
                            vd["registration_deadline"], "%Y-%m-%d"
                        )
                    except: pass
                if vd.get("drive_date"):
                    try:
                        from datetime import date
                        drive.drive_date = datetime.strptime(
                            vd["drive_date"], "%Y-%m-%d"
                        ).date()
                    except: pass
                
                db.add(drive)
                saved_count += 1
        
        db.commit()

    return {
        "status": "completed",
        "emails_stored": emails_stored,
        "total_stored_emails": len(stored_emails),
        "total_emails_processed": len(processed_results),
        "unique_companies": len(merged_results),
        "saved_to_db": saved_count if save_to_db else 0,
        "api_key_configured": bool(api_key),
        "use_gemini": use_gemini,
        "pipeline": "LangGraph",
        "nodes": [
            "filter_sender", "html_to_text", "remove_noise", "token_safety",
            "extract_sections", "regex_extract", "gemini_enhance",
            "validation", "deduplication", "map_to_model"
        ],
        "merged_results": merged_results,
    }

