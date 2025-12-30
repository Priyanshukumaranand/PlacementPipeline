"""
LangGraph Email Processing Pipeline.

Orchestrates the full email processing flow:
1. HTML → Text
2. Noise Removal
3. Token Safety
4. Gemini Extraction
5. Validation
6. Deduplication
7. Database Insert
"""

from typing import TypedDict, Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

# Import our modules
from app.services.text_cleaner import process_email_text, html_to_text, remove_noise
from app.services.gemini_extractor import (
    extract_with_gemini, 
    validate_extracted_data,
    check_duplicate
)

# Allowed senders (only process emails from these)
ALLOWED_SENDERS = [
    'navanita@iiit-bh.ac.in',
    'rajashree@iiit-bh.ac.in',
    'placement@iiit-bh.ac.in',
]


class ProcessingStatus(str, Enum):
    """Status of email processing."""
    PENDING = "pending"
    FILTERED = "filtered"  # Not from allowed sender
    CLEANED = "cleaned"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    DUPLICATE = "duplicate"
    INSERTED = "inserted"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


@dataclass
class PipelineState:
    """State object passed through pipeline stages."""
    # Input
    email_id: str
    gmail_message_id: str
    sender: str
    subject: str
    raw_body: str
    received_at: Optional[str] = None
    
    # Processing stages
    status: ProcessingStatus = ProcessingStatus.PENDING
    plain_text: str = ""
    clean_text: str = ""
    llm_input: str = ""
    excerpts: List[str] = None
    
    # Extraction results
    extracted_data: Dict[str, Any] = None
    validated_data: Dict[str, Any] = None
    
    # Metadata
    is_duplicate: bool = False
    db_record_id: Optional[int] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.excerpts is None:
            self.excerpts = []
        if self.extracted_data is None:
            self.extracted_data = {}
        if self.validated_data is None:
            self.validated_data = {}


def filter_sender(state: PipelineState) -> PipelineState:
    """
    Node 1: Filter emails by allowed senders.
    
    Only process emails from TPO/placement coordinators.
    """
    sender_lower = state.sender.lower()
    
    # Check if sender is in allowed list
    is_allowed = any(
        allowed in sender_lower 
        for allowed in ALLOWED_SENDERS
    )
    
    if not is_allowed:
        state.status = ProcessingStatus.FILTERED
        state.error_message = f"Sender not in allowed list: {state.sender}"
    
    return state


def clean_text_node(state: PipelineState) -> PipelineState:
    """
    Node 2: HTML → Text + Noise Removal + Token Safety.
    
    Applies full text cleaning pipeline.
    """
    if state.status == ProcessingStatus.FILTERED:
        return state
    
    try:
        # Run full text processing
        llm_input, clean_text, excerpts = process_email_text(state.raw_body)
        
        state.plain_text = html_to_text(state.raw_body)
        state.clean_text = clean_text
        state.llm_input = llm_input
        state.excerpts = excerpts
        state.status = ProcessingStatus.CLEANED
        
    except Exception as e:
        state.status = ProcessingStatus.FAILED
        state.error_message = f"Text cleaning failed: {str(e)}"
    
    return state


def extract_node(state: PipelineState, api_key: Optional[str] = None) -> PipelineState:
    """
    Node 3: Gemini extraction.
    
    Uses Gemini 1.5 Flash to extract structured data.
    """
    if state.status != ProcessingStatus.CLEANED:
        return state
    
    try:
        extracted = extract_with_gemini(
            email_content=state.llm_input,
            subject=state.subject,
            api_key=api_key
        )
        
        state.extracted_data = extracted
        
        if extracted.get('extraction_error'):
            state.status = ProcessingStatus.FAILED
            state.error_message = extracted['extraction_error']
        else:
            state.status = ProcessingStatus.EXTRACTED
            
    except Exception as e:
        state.status = ProcessingStatus.FAILED
        state.error_message = f"Extraction failed: {str(e)}"
    
    return state


def validate_node(state: PipelineState) -> PipelineState:
    """
    Node 4: Validation and normalization.
    
    Validates extracted data and flags issues.
    """
    if state.status != ProcessingStatus.EXTRACTED:
        return state
    
    try:
        validated = validate_extracted_data(state.extracted_data)
        state.validated_data = validated
        
        if validated.get('needs_review'):
            state.status = ProcessingStatus.NEEDS_REVIEW
        else:
            state.status = ProcessingStatus.VALIDATED
            
    except Exception as e:
        state.status = ProcessingStatus.FAILED
        state.error_message = f"Validation failed: {str(e)}"
    
    return state


def dedup_node(state: PipelineState, existing_drives: List[Dict]) -> PipelineState:
    """
    Node 5: Deduplication check.
    
    Checks if company + role + deadline already exists.
    """
    if state.status not in [ProcessingStatus.VALIDATED, ProcessingStatus.NEEDS_REVIEW]:
        return state
    
    try:
        is_dup = check_duplicate(state.validated_data, existing_drives)
        state.is_duplicate = is_dup
        
        if is_dup:
            state.status = ProcessingStatus.DUPLICATE
            
    except Exception as e:
        # Don't fail on dedup error, proceed with insert
        pass
    
    return state


def prepare_db_record(state: PipelineState) -> Optional[Dict[str, Any]]:
    """
    Node 6: Prepare database record.
    
    Returns dict ready for PlacementDrive insert (or None if not ready).
    """
    if state.status == ProcessingStatus.DUPLICATE:
        return None
    
    if state.status not in [ProcessingStatus.VALIDATED, ProcessingStatus.NEEDS_REVIEW]:
        return None
    
    data = state.validated_data
    
    # Only insert if we have company name
    if not data.get('company_name'):
        return None
    
    record = {
        'company_name': data.get('company_name'),
        'role': data.get('role'),
        'drive_type': data.get('drive_type'),
        'batch': data.get('batch'),
        'drive_date': data.get('drive_date'),
        'registration_deadline': data.get('registration_deadline'),
        'eligible_branches': data.get('eligible_branches'),
        'min_cgpa': data.get('min_cgpa'),
        'ctc_or_stipend': data.get('ctc_or_stipend'),
        'job_location': data.get('job_location'),
        'registration_link': data.get('registration_link'),
        'status': 'upcoming',  # Default status
        'confidence_score': data.get('confidence_score', 0.5),
        'official_source': 'TPO Email',
        # Source email ID will be set by caller
    }
    
    return record


# New node: map validated data to PlacementDrive fields

def map_to_placement_drive(state: PipelineState) -> PipelineState:
    """
    Node 6: Convert validated_data into a dict matching the PlacementDrive model.
    Any missing fields are left as None (or appropriate default).
    """
    if state.status not in [ProcessingStatus.VALIDATED, ProcessingStatus.NEEDS_REVIEW]:
        return state
    # Ensure all model fields are present
    model_fields = [
        "company_name",
        "company_logo",
        "role",
        "drive_type",
        "batch",
        "drive_date",
        "registration_deadline",
        "eligible_branches",
        "min_cgpa",
        "eligibility_text",
        "ctc_or_stipend",
        "job_location",
        "registration_link",
        "status",
        "confidence_score",
        "official_source",
    ]
    placement_dict = {}
    for field in model_fields:
        placement_dict[field] = state.validated_data.get(field)
    # Add a placeholder for any extra fields we might want later
    state.validated_data = placement_dict
    return state

# Update run_pipeline to include the new node
def run_pipeline(
    email_id: str,
    gmail_message_id: str,
    sender: str,
    subject: str,
    raw_body: str,
    existing_drives: List[Dict] = None,
    api_key: Optional[str] = None,
    received_at: Optional[str] = None
) -> PipelineState:
    """
    Run the full email processing pipeline.
    
    Args:
        email_id: Internal email ID
        gmail_message_id: Gmail message ID
        sender: Email sender
        subject: Email subject
        raw_body: Raw HTML body
        existing_drives: List of existing drives for dedup check
        api_key: Gemini API key
        received_at: Email received timestamp
        
    Returns:
        PipelineState with processing results
    """
    if existing_drives is None:
        existing_drives = []
    
    # Initialize state
    state = PipelineState(
        email_id=str(email_id),
        gmail_message_id=gmail_message_id,
        sender=sender,
        subject=subject,
        raw_body=raw_body,
        received_at=received_at
    )
    
    # Run pipeline stages
    state = filter_sender(state)
    state = clean_text_node(state)
    state = extract_node(state, api_key)
    state = validate_node(state)
    state = dedup_node(state, existing_drives)
    # New mapping node
    state = map_to_placement_drive(state)
    
    return state


def pipeline_result_to_dict(state: PipelineState) -> Dict[str, Any]:
    """Convert pipeline state to JSON-serializable dict."""
    return {
        'email_id': state.email_id,
        'gmail_message_id': state.gmail_message_id,
        'sender': state.sender,
        'subject': state.subject,
        'status': state.status.value,
        'is_duplicate': state.is_duplicate,
        'error_message': state.error_message,
        'excerpts': state.excerpts,
        'extracted_data': state.extracted_data,
        'validated_data': state.validated_data,
        'clean_text_preview': state.clean_text[:500] + '...' if len(state.clean_text) > 500 else state.clean_text
    }
