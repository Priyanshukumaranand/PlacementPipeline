"""
Gmail Push Notification Webhook

This endpoint receives real-time notifications from Google Cloud Pub/Sub
whenever Gmail detects changes in the mailbox.

Pipeline:
1. Receive push notification with historyId
2. Fetch new emails using Gmail History API (incremental sync)
3. Process through LangGraph pipeline (10-step extraction)
4. Save to database with deduplication
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
import base64
import json
import os
from datetime import datetime
from typing import List, Dict

from app.database import get_db
from app.services.gmail_service import get_gmail_service, get_full_message, get_history_since
from app.services.langgraph_pipeline import run_langgraph_pipeline
from app.services import db_service
from app.models.email import Email

router = APIRouter(prefix="/gmail", tags=["Gmail Push"])

# Key for storing historyId in database
HISTORY_ID_KEY = "gmail_history_id"


@router.post("/events")
async def gmail_events(request: Request, db: Session = Depends(get_db)):
    """
    Webhook endpoint for Gmail push notifications via Pub/Sub.

    When Gmail detects mailbox changes, it publishes to Pub/Sub,
    which pushes to this endpoint.

    Uses Gmail History API for efficient incremental sync.
    Processes emails through LangGraph pipeline for accurate extraction.
    """
    body = await request.json()

    # Pub/Sub wraps the notification in a 'message' object
    if "message" not in body:
        return {"status": "ignored", "reason": "no message field"}

    message = body["message"]
    data = message.get("data")

    if not data:
        return {"status": "ignored", "reason": "no data field"}

    # Decode base64-encoded JSON payload
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        payload = json.loads(decoded)
    except Exception as e:
        return {"status": "error", "reason": f"decode failed: {str(e)}"}

    # Extract Gmail notification details
    email_address = payload.get("emailAddress")
    new_history_id = payload.get("historyId")

    print(f"📧 Gmail notification received:")
    print(f"   Email: {email_address}")
    print(f"   History ID: {new_history_id}")

    # Get last processed historyId from database
    last_history_id = db_service.get_sync_state(db, HISTORY_ID_KEY)
    
    processed_drives = []
    emails_saved = 0
    filtered_count = 0
    errors = []
    
    try:
        # Get Gmail service
        service = get_gmail_service()
        
        # Get existing drives for deduplication check
        existing_drives_raw = db_service.get_all_drives(db, limit=1000)
        existing_drives: List[Dict] = [
            {
                "company_name": d.company_name,
                "role": d.role,
                "registration_deadline": d.registration_deadline.isoformat() if d.registration_deadline else None,
                "batch": d.batch
            }
            for d in existing_drives_raw
        ]
        
        # Get Gemini API key
        gemini_api_key = os.getenv("GOOGLE_API_KEY")
        
        # Determine which messages to fetch
        if last_history_id:
            # Incremental sync: only new messages since last historyId
            print(f"   📊 Incremental sync from historyId: {last_history_id}")
            message_ids = get_history_since(service, last_history_id)
            print(f"   📬 Found {len(message_ids)} new messages")
        else:
            # First run: fetch recent unread emails
            print(f"   🆕 First run - fetching recent emails")
            results = service.users().messages().list(
                userId="me",
                maxResults=10,
                q="is:unread"
            ).execute()
            message_ids = [m["id"] for m in results.get("messages", [])]
        
        # Process each message through LangGraph pipeline
        for msg_id in message_ids:
            try:
                # Fetch full message
                full_msg = get_full_message(service, msg_id)
                
                # Check if email already processed
                existing_email = db.query(Email).filter(
                    Email.gmail_message_id == msg_id
                ).first()
                
                if existing_email:
                    print(f"   ⏭️  Skipping already processed: {full_msg['subject'][:50]}...")
                    continue
                
                # Run LangGraph pipeline
                pipeline_result = run_langgraph_pipeline(
                    email_id=str(msg_id),  # Temporary ID, will be replaced
                    gmail_message_id=msg_id,
                    sender=full_msg["from"],
                    subject=full_msg["subject"],
                    raw_body=full_msg["body"],
                    existing_drives=existing_drives,
                    api_key=gemini_api_key,
                    use_gemini=True
                )
                
                status = pipeline_result.get("status", "unknown")
                
                # Check if email was filtered (not a placement email)
                if status == "filtered":
                    filtered_count += 1
                    print(f"   🚫 Filtered (not placement): {full_msg['subject'][:50]}...")
                    # Still save email for audit, but don't create drive
                    db_service.save_email(
                        db=db,
                        gmail_message_id=msg_id,
                        sender=full_msg["from"],
                        subject=full_msg["subject"],
                        raw_body=full_msg["body"]
                    )
                    continue
                
                # Check if duplicate
                if pipeline_result.get("is_duplicate"):
                    print(f"   🔄 Duplicate drive: {pipeline_result.get('validated_data', {}).get('company_name', 'Unknown')}")
                    # Still save email for audit
                    db_service.save_email(
                        db=db,
                        gmail_message_id=msg_id,
                        sender=full_msg["from"],
                        subject=full_msg["subject"],
                        raw_body=full_msg["body"]
                    )
                    continue
                
                # Check if extraction failed
                if status in ["failed", "error"]:
                    error_msg = pipeline_result.get("error_message", "Unknown error")
                    print(f"   ❌ Extraction failed: {error_msg}")
                    errors.append({
                        "message_id": msg_id,
                        "subject": full_msg["subject"][:50],
                        "error": error_msg
                    })
                    # Still save email for audit
                    db_service.save_email(
                        db=db,
                        gmail_message_id=msg_id,
                        sender=full_msg["from"],
                        subject=full_msg["subject"],
                        raw_body=full_msg["body"]
                    )
                    continue
                
                # Get validated data
                validated_data = pipeline_result.get("validated_data", {})
                
                # Only proceed if we have company name
                if not validated_data.get("company_name"):
                    print(f"   ⚠️  No company extracted: {full_msg['subject'][:50]}...")
                    # Still save email
                    db_service.save_email(
                        db=db,
                        gmail_message_id=msg_id,
                        sender=full_msg["from"],
                        subject=full_msg["subject"],
                        raw_body=full_msg["body"]
                    )
                    continue
                
                # Save email first
                email = db_service.save_email(
                    db=db,
                    gmail_message_id=msg_id,
                    sender=full_msg["from"],
                    subject=full_msg["subject"],
                    raw_body=full_msg["body"]
                )
                emails_saved += 1
                
                # Parse dates if they're strings
                drive_date = validated_data.get("drive_date")
                registration_deadline = validated_data.get("registration_deadline")
                
                if isinstance(drive_date, str):
                    try:
                        drive_date = datetime.fromisoformat(drive_date.replace('Z', '+00:00')).date()
                    except:
                        drive_date = None
                elif drive_date and isinstance(drive_date, datetime):
                    drive_date = drive_date.date()
                
                if isinstance(registration_deadline, str):
                    try:
                        registration_deadline = datetime.fromisoformat(registration_deadline.replace('Z', '+00:00'))
                    except:
                        registration_deadline = None
                
                # Create/update placement drive
                drive = db_service.upsert_placement_drive(
                    db=db,
                    company_name=validated_data.get("company_name"),
                    source_email_id=email.id,
                    company_logo=validated_data.get("company_logo"),
                    role=validated_data.get("role"),
                    drive_type=validated_data.get("drive_type"),
                    batch=validated_data.get("batch"),
                    drive_date=drive_date,
                    registration_deadline=registration_deadline,
                    eligible_branches=validated_data.get("eligible_branches"),
                    min_cgpa=validated_data.get("min_cgpa"),
                    eligibility_text=validated_data.get("eligibility_text"),
                    ctc_or_stipend=validated_data.get("ctc_or_stipend"),
                    job_location=validated_data.get("job_location"),
                    registration_link=validated_data.get("registration_link"),
                    status=validated_data.get("status", "upcoming"),
                    confidence_score=validated_data.get("confidence_score", 0.5),
                    official_source=validated_data.get("official_source", "TPO Email")
                )
                
                processed_drives.append({
                    "drive_id": drive.id,
                    "company": validated_data.get("company_name"),
                    "batch": validated_data.get("batch"),
                    "role": validated_data.get("role"),
                    "status": status
                })
                print(f"   ✅ Saved drive: {validated_data.get('company_name')} ({status})")
                
            except Exception as e:
                error_msg = str(e)
                print(f"   ❌ Error processing message {msg_id}: {error_msg}")
                import traceback
                traceback.print_exc()
                errors.append({
                    "message_id": msg_id,
                    "error": error_msg
                })
        
        # Update historyId in database for next sync
        if new_history_id:
            db_service.set_sync_state(db, HISTORY_ID_KEY, new_history_id)
            print(f"   📝 Updated historyId to: {new_history_id}")
        
    except Exception as e:
        print(f"   ❌ Fatal error processing: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "reason": str(e),
            "historyId": new_history_id
        }

    return {
        "status": "processed",
        "email": email_address,
        "historyId": new_history_id,
        "emails_saved": emails_saved,
        "filtered": filtered_count,
        "drives_saved": len(processed_drives),
        "errors": len(errors),
        "drives": processed_drives,
        "error_details": errors[:5] if errors else []  # First 5 errors
    }


@router.post("/process-now")
async def process_emails_now(db: Session = Depends(get_db)):
    """
    Manually trigger email processing using LangGraph pipeline.
    
    Useful for:
    - Initial data load
    - Testing the pipeline
    - Catching up after downtime
    """
    print("🔄 Manual email processing triggered")
    
    emails_saved = 0
    drives_saved = []
    filtered_count = 0
    errors = []
    
    try:
        service = get_gmail_service()
        
        # Get existing drives for deduplication
        existing_drives_raw = db_service.get_all_drives(db, limit=1000)
        existing_drives: List[Dict] = [
            {
                "company_name": d.company_name,
                "role": d.role,
                "registration_deadline": d.registration_deadline.isoformat() if d.registration_deadline else None,
                "batch": d.batch
            }
            for d in existing_drives_raw
        ]
        
        # Get Gemini API key
        gemini_api_key = os.getenv("GOOGLE_API_KEY")
        
        # Fetch recent emails (last 20)
        results = service.users().messages().list(
            userId="me",
            maxResults=20,
            labelIds=["INBOX"]
        ).execute()
        
        messages = results.get("messages", [])
        print(f"📬 Found {len(messages)} emails to process")
        
        for msg_meta in messages:
            msg_id = msg_meta["id"]
            
            try:
                # Check if already processed
                existing = db.query(Email).filter(
                    Email.gmail_message_id == msg_id
                ).first()
                
                if existing:
                    continue  # Skip already processed
                
                # Fetch full message
                full_msg = get_full_message(service, msg_id)
                
                # Run LangGraph pipeline
                pipeline_result = run_langgraph_pipeline(
                    email_id=str(msg_id),
                    gmail_message_id=msg_id,
                    sender=full_msg["from"],
                    subject=full_msg["subject"],
                    raw_body=full_msg["body"],
                    existing_drives=existing_drives,
                    api_key=gemini_api_key,
                    use_gemini=True
                )
                
                status = pipeline_result.get("status", "unknown")
                
                # Check if filtered or duplicate
                if status in ["filtered", "duplicate"]:
                    filtered_count += 1
                    continue
                
                # Check if failed
                if status in ["failed", "error"]:
                    errors.append({
                        "message_id": msg_id,
                        "error": pipeline_result.get("error_message", "Unknown error")
                    })
                    continue
                
                # Get validated data
                validated_data = pipeline_result.get("validated_data", {})
                
                if not validated_data.get("company_name"):
                    continue
                
                # Save email
                email = db_service.save_email(
                    db=db,
                    gmail_message_id=msg_id,
                    sender=full_msg["from"],
                    subject=full_msg["subject"],
                    raw_body=full_msg["body"]
                )
                emails_saved += 1
                
                # Parse dates
                drive_date = validated_data.get("drive_date")
                registration_deadline = validated_data.get("registration_deadline")
                
                if isinstance(drive_date, str):
                    try:
                        drive_date = datetime.fromisoformat(drive_date.replace('Z', '+00:00')).date()
                    except:
                        drive_date = None
                elif drive_date and isinstance(drive_date, datetime):
                    drive_date = drive_date.date()
                
                if isinstance(registration_deadline, str):
                    try:
                        registration_deadline = datetime.fromisoformat(registration_deadline.replace('Z', '+00:00'))
                    except:
                        registration_deadline = None
                
                # Create/update drive
                drive = db_service.upsert_placement_drive(
                    db=db,
                    company_name=validated_data.get("company_name"),
                    source_email_id=email.id,
                    company_logo=validated_data.get("company_logo"),
                    role=validated_data.get("role"),
                    drive_type=validated_data.get("drive_type"),
                    batch=validated_data.get("batch"),
                    drive_date=drive_date,
                    registration_deadline=registration_deadline,
                    eligible_branches=validated_data.get("eligible_branches"),
                    min_cgpa=validated_data.get("min_cgpa"),
                    eligibility_text=validated_data.get("eligibility_text"),
                    ctc_or_stipend=validated_data.get("ctc_or_stipend"),
                    job_location=validated_data.get("job_location"),
                    registration_link=validated_data.get("registration_link"),
                    status=validated_data.get("status", "upcoming"),
                    confidence_score=validated_data.get("confidence_score", 0.5),
                    official_source=validated_data.get("official_source", "TPO Email")
                )
                
                drives_saved.append(validated_data.get("company_name"))
                
            except Exception as e:
                errors.append({
                    "message_id": msg_id,
                    "error": str(e)
                })
        
        return {
            "status": "success",
            "emails_processed": emails_saved,
            "filtered": filtered_count,
            "drives_created": len(drives_saved),
            "errors": len(errors),
            "companies": drives_saved
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "reason": str(e)}
