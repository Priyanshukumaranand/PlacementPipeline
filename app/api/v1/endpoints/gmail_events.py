"""
Gmail Push Notification Webhook (Refactored).

Streamlined endpoints using the refactored LangGraph pipeline.
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
import base64
import json
import os
from typing import List, Dict

from app.database import get_db
from app.services.gmail_service import get_gmail_service, get_full_message, get_history_since
from app.services.langgraph_pipeline import run_langgraph_pipeline
from app.services import db_service
from app.models.email import Email

router = APIRouter(prefix="/gmail", tags=["Gmail Push"])
HISTORY_ID_KEY = "gmail_history_id"


def _get_existing_drives(db: Session) -> List[Dict]:
    """Get existing drives for deduplication."""
    drives = db_service.get_all_drives(db, limit=1000)
    return [
        {
            "company_name": d.company_name,
            "role": d.role,
            "registration_deadline": d.registration_deadline.isoformat() if d.registration_deadline else None,
            "batch": d.batch
        }
        for d in drives
    ]


def _process_message(db: Session, service, msg_id: str, existing_drives: List[Dict]) -> Dict:
    """Process a single Gmail message through the LangGraph pipeline."""
    # Check if already processed
    if db.query(Email).filter(Email.gmail_message_id == msg_id).first():
        return {"status": "skipped", "reason": "already_processed"}
    
    # Fetch full message
    msg = get_full_message(service, msg_id)
    
    # Run pipeline (now handles DB save internally)
    result = run_langgraph_pipeline(
        email_id=str(msg_id),
        gmail_message_id=msg_id,
        sender=msg["from"],
        subject=msg["subject"],
        raw_body=msg["body"],
        existing_drives=existing_drives,
        api_key=os.getenv("GOOGLE_API_KEY"),
        use_gemini=True,
        db=db
    )
    
    return {
        "status": result.get("status"),
        "company": result.get("extracted_data", {}).get("company_name"),
        "role": result.get("extracted_data", {}).get("role"),
        "drive_id": result.get("saved_drive_id"),
        "error": result.get("error_message")
    }


@router.post("/events")
async def gmail_events(request: Request, db: Session = Depends(get_db)):
    """Webhook for Gmail push notifications via Pub/Sub."""
    body = await request.json()
    
    if "message" not in body:
        return {"status": "ignored", "reason": "no message field"}
    
    data = body["message"].get("data")
    if not data:
        return {"status": "ignored", "reason": "no data field"}
    
    try:
        payload = json.loads(base64.b64decode(data).decode("utf-8"))
    except Exception as e:
        return {"status": "error", "reason": f"decode failed: {e}"}
    
    email_address = payload.get("emailAddress")
    new_history_id = payload.get("historyId")
    print(f"📧 Gmail notification: {email_address}, historyId: {new_history_id}")
    
    last_history_id = db_service.get_sync_state(db, HISTORY_ID_KEY)
    results = {"saved": [], "filtered": 0, "errors": []}
    
    try:
        service = get_gmail_service()
        existing_drives = _get_existing_drives(db)
        
        # Get messages to process
        if last_history_id:
            message_ids = get_history_since(service, last_history_id)
        else:
            resp = service.users().messages().list(userId="me", maxResults=10, q="is:unread").execute()
            message_ids = [m["id"] for m in resp.get("messages", [])]
        
        print(f"   📬 Processing {len(message_ids)} messages")
        
        for msg_id in message_ids:
            try:
                result = _process_message(db, service, msg_id, existing_drives)
                
                if result["status"] == "saved":
                    results["saved"].append({"company": result["company"], "drive_id": result["drive_id"]})
                elif result["status"] == "filtered":
                    results["filtered"] += 1
                elif result.get("error"):
                    results["errors"].append({"id": msg_id, "error": result["error"]})
            except Exception as e:
                results["errors"].append({"id": msg_id, "error": str(e)})
        
        if new_history_id:
            db_service.set_sync_state(db, HISTORY_ID_KEY, new_history_id)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "reason": str(e)}
    
    return {
        "status": "processed",
        "email": email_address,
        "historyId": new_history_id,
        "drives_saved": len(results["saved"]),
        "filtered": results["filtered"],
        "errors": len(results["errors"]),
        "drives": results["saved"],
        "error_details": results["errors"][:5]
    }


@router.post("/process-now")
async def process_emails_now(db: Session = Depends(get_db)):
    """Manually trigger email processing."""
    print("🔄 Manual email processing triggered")
    
    results = {"saved": [], "filtered": 0, "errors": []}
    
    try:
        service = get_gmail_service()
        existing_drives = _get_existing_drives(db)
        
        resp = service.users().messages().list(userId="me", maxResults=20, labelIds=["INBOX"]).execute()
        messages = resp.get("messages", [])
        print(f"📬 Found {len(messages)} emails to process")
        
        for msg_meta in messages:
            try:
                result = _process_message(db, service, msg_meta["id"], existing_drives)
                
                if result["status"] == "saved":
                    results["saved"].append(result["company"])
                elif result["status"] in ("filtered", "duplicate"):
                    results["filtered"] += 1
                elif result.get("error"):
                    results["errors"].append({"id": msg_meta["id"], "error": result["error"]})
            except Exception as e:
                results["errors"].append({"id": msg_meta["id"], "error": str(e)})
        
        return {
            "status": "success",
            "emails_processed": len(results["saved"]),
            "filtered": results["filtered"],
            "drives_created": len(results["saved"]),
            "errors": len(results["errors"]),
            "companies": results["saved"]
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "reason": str(e)}
