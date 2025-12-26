"""
Gmail Push Notification Webhook

This endpoint receives real-time notifications from Google Cloud Pub/Sub
whenever Gmail detects changes in the mailbox.

Pipeline:
1. Receive push notification with historyId
2. Fetch new emails from Gmail API
3. Extract placement info
4. Save to database
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
import base64
import json

from app.database import get_db
from app.services.gmail_service import get_gmail_service, get_full_message
from app.services.email_extractor import extract_placement_info
from app.services import db_service

router = APIRouter(prefix="/gmail", tags=["Gmail Push"])

# Store last processed history_id in memory (TODO: persist in Redis/DB)
last_history_id = None


@router.post("/events")
async def gmail_events(request: Request, db: Session = Depends(get_db)):
    """
    Webhook endpoint for Gmail push notifications via Pub/Sub.

    When Gmail detects mailbox changes, it publishes to Pub/Sub,
    which pushes to this endpoint.

    Payload structure:
    {
      "message": {
        "data": "base64-encoded-json",
        "messageId": "...",
        "publishTime": "..."
      },
      "subscription": "..."
    }

    Decoded data contains:
    {
      "emailAddress": "user@gmail.com",
      "historyId": "12345678"
    }

    Returns:
        dict: Processing result with extracted drive info
    """
    global last_history_id
    
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
    history_id = payload.get("historyId")

    print(f"📧 Gmail notification received:")
    print(f"   Email: {email_address}")
    print(f"   History ID: {history_id}")

    # Process new emails
    processed_drives = []
    
    try:
        # Get Gmail service
        service = get_gmail_service()
        
        # Fetch history changes since last known historyId
        # For now, we'll fetch recent messages instead
        # TODO: Use history.list for incremental sync
        
        results = service.users().messages().list(
            userId="me",
            maxResults=5,
            q="is:unread"  # Only unread emails
        ).execute()
        
        messages = results.get("messages", [])
        
        for msg_meta in messages:
            msg_id = msg_meta["id"]
            
            # Fetch full message
            full_msg = get_full_message(service, msg_id)
            
            # Extract placement info
            extracted = extract_placement_info(
                subject=full_msg["subject"],
                raw_body=full_msg["body"]
            )
            
            if extracted and extracted.get("company"):
                # Save to database using the pipeline
                drive = db_service.process_email_to_db(
                    db=db,
                    gmail_message_id=msg_id,
                    sender=full_msg["from"],
                    subject=full_msg["subject"],
                    raw_body=full_msg["body"],
                    extracted_info=extracted
                )
                
                if drive:
                    processed_drives.append({
                        "drive_id": drive.id,
                        "company": extracted["company"],
                        "batch": extracted.get("batch")
                    })
                    print(f"   ✅ Saved drive: {extracted['company']}")
        
        # Update last history ID
        last_history_id = history_id
        
    except Exception as e:
        print(f"   ❌ Error processing: {str(e)}")
        return {
            "status": "error",
            "reason": str(e),
            "historyId": history_id
        }

    return {
        "status": "processed",
        "email": email_address,
        "historyId": history_id,
        "drives_saved": len(processed_drives),
        "drives": processed_drives
    }
