"""
Gmail Push Notification Webhook

This endpoint receives real-time notifications from Google Cloud Pub/Sub
whenever Gmail detects changes in the mailbox.

Pipeline:
1. Receive push notification with historyId
2. Fetch new emails using Gmail History API (incremental sync)
3. Extract placement info
4. Save to database with deduplication
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
import base64
import json

from app.database import get_db
from app.services.gmail_service import get_gmail_service, get_full_message, get_history_since
from app.services.email_extractor import extract_placement_info
from app.services import db_service

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
    
    try:
        # Get Gmail service
        service = get_gmail_service()
        
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
        
        # Process each message
        for msg_id in message_ids:
            # Fetch full message
            full_msg = get_full_message(service, msg_id)
            
            # Save email to database (always, for audit trail)
            email = db_service.save_email(
                db=db,
                gmail_message_id=msg_id,
                sender=full_msg["from"],
                subject=full_msg["subject"],
                raw_body=full_msg["body"]
            )
            emails_saved += 1
            print(f"   💾 Saved email: {full_msg['subject'][:50]}...")
            
            # Extract placement info
            extracted = extract_placement_info(
                subject=full_msg["subject"],
                raw_body=full_msg["body"]
            )
            
            # If placement email, create/update drive
            if extracted and extracted.get("company"):
                drive = db_service.upsert_placement_drive(
                    db=db,
                    company_name=extracted["company"],
                    source_email_id=email.id,
                    role=extracted.get("role"),
                    drive_type=extracted.get("drive_type"),
                    batch=extracted.get("batch"),
                    official_source="TPO Email"
                )
                
                processed_drives.append({
                    "drive_id": drive.id,
                    "company": extracted["company"],
                    "batch": extracted.get("batch")
                })
                print(f"   ✅ Saved drive: {extracted['company']}")
        
        # Update historyId in database for next sync
        db_service.set_sync_state(db, HISTORY_ID_KEY, new_history_id)
        print(f"   📝 Updated historyId to: {new_history_id}")
        
    except Exception as e:
        print(f"   ❌ Error processing: {str(e)}")
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
        "drives_saved": len(processed_drives),
        "drives": processed_drives
    }


@router.post("/process-now")
async def process_emails_now(db: Session = Depends(get_db)):
    """
    Manually trigger email processing.
    
    Useful for:
    - Initial data load
    - Testing the pipeline
    - Catching up after downtime
    """
    print("🔄 Manual email processing triggered")
    
    emails_saved = 0
    drives_saved = []
    
    try:
        service = get_gmail_service()
        
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
            
            # Check if already processed
            existing = db.query(db_service.Email).filter(
                db_service.Email.gmail_message_id == msg_id
            ).first()
            
            if existing:
                continue  # Skip already processed
            
            # Fetch and process
            full_msg = get_full_message(service, msg_id)
            
            # Save email
            email = db_service.save_email(
                db=db,
                gmail_message_id=msg_id,
                sender=full_msg["from"],
                subject=full_msg["subject"],
                raw_body=full_msg["body"]
            )
            emails_saved += 1
            
            # Extract and save placement
            extracted = extract_placement_info(
                subject=full_msg["subject"],
                raw_body=full_msg["body"]
            )
            
            if extracted and extracted.get("company"):
                drive = db_service.upsert_placement_drive(
                    db=db,
                    company_name=extracted["company"],
                    source_email_id=email.id,
                    role=extracted.get("role"),
                    batch=extracted.get("batch"),
                    official_source="TPO Email"
                )
                drives_saved.append(extracted["company"])
        
        return {
            "status": "success",
            "emails_processed": emails_saved,
            "drives_created": len(drives_saved),
            "companies": drives_saved
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "reason": str(e)}
