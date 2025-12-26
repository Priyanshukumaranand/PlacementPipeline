"""
Email extraction utilities for placement information.

This module provides functions to:
- Clean HTML email content to plain text
- Identify placement-related emails using keywords
- Extract company and batch from subject lines
- Extract dates from email bodies
- Orchestrate the full extraction pipeline
"""

from bs4 import BeautifulSoup
import re

# Keywords that indicate a placement-related email
PLACEMENT_KEYWORDS = [
    "placement", "recruitment", "campus",
    "drive", "hiring", "intern",
    "full time", "fte"
]

# Date patterns to match common formats
DATE_PATTERNS = [
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",  # 12/01/2026 or 12-01-2026
    r"\b\d{1,2}(st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\b",  # 12th Jan 2026
    r"\b[A-Za-z]+\s+\d{1,2},\s*\d{4}\b"  # January 12, 2026
]


def clean_email_text(raw_html: str) -> str:
    """
    Convert HTML email content to clean plain text.

    Args:
        raw_html: Raw HTML string from email body

    Returns:
        Cleaned plain text with normalized whitespace
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script and style tags
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Extract text with space separators
    text = soup.get_text(separator=" ")

    # Normalize multiple spaces to single space
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def is_placement_mail(subject: str, body: str) -> bool:
    """
    Determine if an email is placement-related based on keywords.

    Args:
        subject: Email subject line
        body: Email body text (cleaned)

    Returns:
        True if email contains placement keywords, False otherwise
    """
    # Combine subject and body, convert to lowercase
    text = f"{subject} {body}".lower()

    # Check if any keyword is present
    return any(keyword in text for keyword in PLACEMENT_KEYWORDS)


def extract_from_subject(subject: str) -> dict:
    """
    Extract company and batch from standardized subject format.

    Expected format: "Campus Recruitment Drive || Company || Batch"

    Args:
        subject: Email subject line

    Returns:
        Dictionary with 'company' and 'batch' keys (None if not found)
    """
    # Split by || delimiter and strip whitespace
    parts = [p.strip() for p in subject.split("||")]

    data = {
        "company": None,
        "batch": None
    }

    # Extract company (2nd part)
    if len(parts) >= 2:
        data["company"] = parts[1]

    # Extract batch (3rd part)
    if len(parts) >= 3:
        data["batch"] = parts[2]

    return data


def extract_dates(text: str) -> list:
    """
    Extract all dates from text using regex patterns.

    Args:
        text: Plain text to search for dates

    Returns:
        List of date strings found (may be empty)
    """
    dates = []

    # Apply each date pattern
    for pattern in DATE_PATTERNS:
        matches = re.findall(pattern, text)
        dates.extend(matches)

    return dates


def extract_placement_info(subject: str, raw_body: str) -> dict:
    """
    Main extraction pipeline for placement information.

    Args:
        subject: Email subject line
        raw_body: Raw email body (HTML or plain text)

    Returns:
        Dictionary with extracted placement info, or empty dict if not placement email
    """
    # Step 1: Clean HTML to plain text
    clean_body = clean_email_text(raw_body)

    # Step 2: Filter non-placement emails
    if not is_placement_mail(subject, clean_body):
        return {}

    # Step 3: Extract from subject line
    data = extract_from_subject(subject)

    # Step 4: Extract dates from body
    data["dates_found"] = extract_dates(clean_body)

    # Step 5: Add metadata
    data["source"] = "email"

    return data
