"""
Gmail Watch Management

Endpoints to register and manage Gmail push notification watches.
"""

from fastapi import APIRouter, HTTPException
from app.services.gmail_service import get_gmail_service, register_gmail_watch
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/gmail", tags=["Gmail Watch"])


@router.post("/watch/start")
def start_gmail_watch():
    """
    Register Gmail push notifications (watch).

    This tells Gmail to send real-time notifications to your Pub/Sub topic
    whenever mailbox changes occur.

    Prerequisites:
    1. Pub/Sub topic created: gmail-placement-events
    2. Gmail publisher permission granted
    3. Push subscription created with your webhook URL
    4. GCP_PROJECT_ID set in .env

    Returns:
        dict: Watch registration details including baseline historyId and expiration

    Important:
    - Watch expires in ~7 days and must be renewed
    - Save the returned historyId as your baseline
    - Use historyId to fetch only new emails
    """
    # Get project ID from environment
    project_id = os.getenv("GCP_PROJECT_ID")

    if not project_id or project_id == "YOUR_PROJECT_ID_HERE":
        raise HTTPException(
            status_code=500,
            detail="GCP_PROJECT_ID not configured in .env file"
        )

    try:
        # Get authenticated Gmail service
        service = get_gmail_service()

        # Register the watch
        response = register_gmail_watch(service, project_id)

        history_id = response.get("historyId")
        expiration = response.get("expiration")

        # Convert expiration from ms to human-readable
        import datetime
        expiration_date = datetime.datetime.fromtimestamp(int(expiration) / 1000)

        return {
            "status": "success",
            "message": "Gmail watch registered successfully",
            "historyId": history_id,
            "expiration": expiration,
            "expiration_date": expiration_date.isoformat(),
            "note": "SAVE this historyId - it's your baseline for fetching new emails"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register Gmail watch: {str(e)}"
        )


@router.post("/watch/stop")
def stop_gmail_watch():
    """
    Stop Gmail push notifications.

    This cancels the active watch and stops receiving notifications.

    Returns:
        dict: Confirmation of watch cancellation
    """
    try:
        service = get_gmail_service()

        # Stop the watch
        service.users().stop(userId="me").execute()

        return {
            "status": "success",
            "message": "Gmail watch stopped successfully"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop Gmail watch: {str(e)}"
        )
