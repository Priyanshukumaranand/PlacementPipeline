from fastapi import APIRouter
from app.services.gmail_service import get_gmail_service, get_full_message
from app.services.email_extractor import extract_placement_info

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


@router.get("/gmail/extract")
def extract_from_latest():
    """
    Extract placement information from ALL emails sent by placement coordinators.

    Filters emails from specific senders, extracts structured placement data
    including company name, batch, and dates. Only returns non-null values.

    Returns:
        list: Extracted placement information (excluding null/empty values)
    """
    # Get authenticated Gmail service
    service = get_gmail_service()

    # Gmail query to filter placement coordinator emails
    query = (
        "from:(navanita@iiit-bh.ac.in OR "
        "rajashree@iiit-bh.ac.in OR "
        "placement@iiit-bh.ac.in)"
    )

    # Search for ALL messages matching the query (no maxResults limit)
    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=500  # Increased to get more emails
    ).execute()

    messages = results.get("messages", [])
    extracted = []

    # Process each message
    for msg in messages:
        # Get full message with body content
        mail = get_full_message(service, msg["id"])

        # Extract placement information
        info = extract_placement_info(mail["subject"], mail["body"])

        # Only include if extraction was successful AND has company name
        if info and info.get("company"):
            # Remove null values from the dictionary
            cleaned_info = {k: v for k, v in info.items() if v is not None and v != [] and v != ""}

            # Only add if we have meaningful data (at least company)
            if cleaned_info:
                extracted.append(cleaned_info)

    return {
        "total_scanned": len(messages),
        "placements_found": len(extracted),
        "data": extracted
    }
