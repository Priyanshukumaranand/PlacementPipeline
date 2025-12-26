import os
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify"
]


def get_gmail_service():
    """
    Creates and returns an authenticated Gmail API service instance.

    On first run, opens browser for OAuth authentication and saves token.
    Subsequent runs use cached token with automatic refresh if expired.
    """
    creds = None

    # Load existing token if available
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # If no valid credentials, authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Refresh expired token
            creds.refresh(Request())
        else:
            # Run OAuth flow (opens browser)
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    # Build and return Gmail service
    service = build("gmail", "v1", credentials=creds)
    return service


def get_full_message(service, message_id: str) -> dict:
    """
    Fetch full email message including body content.

    Args:
        service: Authenticated Gmail API service
        message_id: Gmail message ID

    Returns:
        Dictionary with 'subject', 'from', and 'body' keys
    """
    # Get full message with body
    msg = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full"
    ).execute()

    # Extract headers
    headers = msg["payload"]["headers"]
    subject = sender = None

    for h in headers:
        if h["name"] == "Subject":
            subject = h["value"]
        if h["name"] == "From":
            sender = h["value"]

    # Extract body (handles multipart and simple messages)
    body = ""

    def get_body_from_parts(parts):
        """Recursively extract body from message parts."""
        body_text = ""
        for part in parts:
            mime_type = part.get("mimeType", "")

            # If part has nested parts, recurse
            if "parts" in part:
                body_text += get_body_from_parts(part["parts"])
            # Extract text/html or text/plain
            elif mime_type in ["text/html", "text/plain"]:
                data = part.get("body", {}).get("data", "")
                if data:
                    # Decode base64url
                    decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    body_text += decoded

        return body_text

    # Handle multipart messages
    if "parts" in msg["payload"]:
        body = get_body_from_parts(msg["payload"]["parts"])
    # Handle simple messages
    elif "body" in msg["payload"] and "data" in msg["payload"]["body"]:
        data = msg["payload"]["body"]["data"]
        body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    return {
        "subject": subject or "",
        "from": sender or "",
        "body": body
    }


def register_gmail_watch(service, project_id: str) -> dict:
    """
    Register Gmail push notifications via Cloud Pub/Sub.

    This tells Gmail to send real-time notifications whenever mailbox changes occur.
    Watch expires after ~7 days and must be renewed.

    Args:
        service: Authenticated Gmail API service
        project_id: Google Cloud Project ID

    Returns:
        Dictionary with 'historyId' (baseline) and 'expiration' (timestamp in ms)
    """
    request_body = {
        "topicName": f"projects/{project_id}/topics/gmail-placement-events",
        "labelIds": ["INBOX"]
    }

    response = service.users().watch(
        userId="me",
        body=request_body
    ).execute()

    return response
