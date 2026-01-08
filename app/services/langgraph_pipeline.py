"""
LangGraph Email Processing Pipeline (Refactored).

Streamlined 6-node pipeline with conditional routing:
1. Filter Sender → Only TPO emails about placements
2. Process Text → HTML→Text, noise removal, token trim, extract sections
3. Extract & Validate → Regex + Gemini extraction + validation
4. Deduplicate → Check for existing drives
5. Save to DB → Persist email and drive
6. END
"""

from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime
import os
from langgraph.graph import StateGraph, START, END
from sqlalchemy.orm import Session

from app.services.text_cleaner import process_email_text
from app.services.regex_extractor import extract_all_fields
from app.services.gemini_extractor import (
    extract_with_gemini,
    validate_extracted_data,
    check_duplicate
)

# Allowed senders
ALLOWED_SENDERS = [
    'navanita@iiit-bh.ac.in',
    'rajashree@iiit-bh.ac.in',
    'placement@iiit-bh.ac.in',
]

# Placement keywords
PLACEMENT_KEYWORDS = [
    "campus drive", "recruitment drive", "campus recruitment",
    "placement drive", "pool campus", "hiring drive",
    "internship drive", "fte drive", "full time drive",
    "campus hiring", "off campus", "on campus", "placement opportunity",
    "online test", "aptitude test", "coding test", "technical test",
    "company visit", "company drive", "batch 202", "passing out"
]


class PipelineState(TypedDict):
    """State that flows through the LangGraph pipeline."""
    # Input
    email_id: str
    gmail_message_id: str
    sender: str
    subject: str
    raw_body: str
    
    # Processing
    clean_text: str
    excerpts: List[str]
    
    # Extraction
    extracted_data: Dict[str, Any]
    
    # Status
    status: str  # pending, filtered, extracted, duplicate, saved, failed
    error_message: Optional[str]
    
    # Config
    api_key: Optional[str]
    use_gemini: bool
    existing_drives: List[Dict]
    
    # Database (optional, for internal save)
    db: Optional[Any]
    saved_email_id: Optional[int]
    saved_drive_id: Optional[int]


# ============ NODE FUNCTIONS ============

def filter_sender_node(state: PipelineState) -> dict:
    """Node 1: Filter by sender AND placement keywords."""
    sender_lower = state["sender"].lower()
    sender_email = sender_lower.split('<')[-1].split('>')[0].strip()
    
    # Check sender
    is_allowed = (
        any(allowed in sender_lower or allowed in sender_email for allowed in ALLOWED_SENDERS)
        or '@iiit-bh.ac.in' in sender_email
    )
    
    if not is_allowed:
        return {"status": "filtered", "error_message": f"Sender not allowed: {state['sender']}"}
    
    # Check placement keywords
    combined = f"{state.get('subject', '').lower()} {(state.get('raw_body', '')[:500] or '').lower()}"
    if not any(kw in combined for kw in PLACEMENT_KEYWORDS):
        return {"status": "filtered", "error_message": f"Not a placement email: {state.get('subject', '')[:50]}"}
    
    return {"status": "pending"}


def process_text_node(state: PipelineState) -> dict:
    """Node 2: Full text processing (HTML→Text, noise, trim, excerpts)."""
    try:
        _, clean_text, excerpts = process_email_text(state["raw_body"])
        return {"clean_text": clean_text, "excerpts": excerpts}
    except Exception as e:
        return {"status": "failed", "error_message": f"Text processing failed: {e}"}


def extract_and_validate_node(state: PipelineState) -> dict:
    """Node 3: Extract fields (regex + optional Gemini) and validate."""
    try:
        # Regex extraction (always)
        data = extract_all_fields(
            text=state.get("clean_text", ""),
            subject=state.get("subject", "")
        )
        
        # Gemini enhancement (if enabled)
        api_key = state.get("api_key") or os.getenv("GOOGLE_API_KEY")
        if state.get("use_gemini", True) and api_key:
            try:
                excerpts_text = "\n".join(state.get("excerpts", []))
                llm_input = f"EXTRACTED:\n{excerpts_text}\n\nEMAIL:\n{state.get('clean_text', '')}"
                gemini_data = extract_with_gemini(llm_input, state.get("subject", ""), api_key)
                
                # Merge: Gemini fills gaps
                for k, v in gemini_data.items():
                    if v is not None and k not in ["extraction_error", "confidence_score"]:
                        data[k] = v
                if not gemini_data.get("extraction_error"):
                    data["confidence_score"] = max(data.get("confidence_score", 0), gemini_data.get("confidence_score", 0))
                    data["extraction_method"] = "regex+gemini"
            except Exception:
                pass  # Gemini failed, use regex data
        
        # Validate
        validated = validate_extracted_data(data)
        
        # Set defaults
        if not validated.get("status"):
            validated["status"] = "upcoming"
        if not validated.get("official_source"):
            validated["official_source"] = "TPO Email"
        
        return {
            "extracted_data": validated,
            "status": "needs_review" if validated.get("needs_review") else "extracted"
        }
    except Exception as e:
        return {"status": "failed", "error_message": f"Extraction failed: {e}"}


def deduplication_node(state: PipelineState) -> dict:
    """Node 4: Check for duplicates."""
    try:
        is_dup = check_duplicate(
            state.get("extracted_data", {}),
            state.get("existing_drives", [])
        )
        if is_dup:
            return {"status": "duplicate"}
        return {}
    except Exception:
        return {}


def save_to_db_node(state: PipelineState) -> dict:
    """Node 5: Save email and drive to database (if db session provided)."""
    db = state.get("db")
    if not db:
        return {"status": "ready"}  # No DB, just return ready
    
    try:
        from app.services import db_service
        
        validated = state.get("extracted_data", {})
        if not validated.get("company_name"):
            return {"status": "ready", "error_message": "No company extracted"}
        
        # Save email
        email = db_service.save_email(
            db=db,
            gmail_message_id=state["gmail_message_id"],
            sender=state["sender"],
            subject=state["subject"],
            raw_body=state["raw_body"]
        )
        
        # Parse dates
        drive_date = validated.get("drive_date")
        reg_deadline = validated.get("registration_deadline")
        
        if isinstance(drive_date, str):
            try:
                drive_date = datetime.fromisoformat(drive_date.replace('Z', '+00:00')).date()
            except:
                drive_date = None
        elif drive_date and isinstance(drive_date, datetime):
            drive_date = drive_date.date()
        
        if isinstance(reg_deadline, str):
            try:
                reg_deadline = datetime.fromisoformat(reg_deadline.replace('Z', '+00:00'))
            except:
                reg_deadline = None
        
        # Save drive
        drive = db_service.upsert_placement_drive(
            db=db,
            company_name=validated.get("company_name"),
            source_email_id=email.id,
            company_logo=validated.get("company_logo"),
            role=validated.get("role"),
            drive_type=validated.get("drive_type"),
            batch=validated.get("batch"),
            drive_date=drive_date,
            registration_deadline=reg_deadline,
            eligible_branches=validated.get("eligible_branches"),
            min_cgpa=validated.get("min_cgpa"),
            eligibility_text=validated.get("eligibility_text"),
            ctc_or_stipend=validated.get("ctc_or_stipend"),
            job_location=validated.get("job_location"),
            registration_link=validated.get("registration_link"),
            status=validated.get("status", "upcoming"),
            confidence_score=validated.get("confidence_score", 0.5),
            official_source=validated.get("official_source", "TPO Email")
        )
        
        return {
            "status": "saved",
            "saved_email_id": email.id,
            "saved_drive_id": drive.id
        }
    except Exception as e:
        return {"status": "failed", "error_message": f"DB save failed: {e}"}


# ============ ROUTING ============

def route_after_filter(state: PipelineState) -> str:
    """Route after filter: exit early if filtered."""
    return END if state.get("status") == "filtered" else "process_text"


def route_after_dedup(state: PipelineState) -> str:
    """Route after dedup: exit if duplicate or failed."""
    status = state.get("status", "")
    if status in ("duplicate", "failed"):
        return END
    return "save_to_db"


# ============ BUILD PIPELINE ============

def build_pipeline() -> StateGraph:
    """Build the streamlined LangGraph pipeline."""
    workflow = StateGraph(PipelineState)
    
    # Add nodes
    workflow.add_node("filter_sender", filter_sender_node)
    workflow.add_node("process_text", process_text_node)
    workflow.add_node("extract_validate", extract_and_validate_node)
    workflow.add_node("deduplication", deduplication_node)
    workflow.add_node("save_to_db", save_to_db_node)
    
    # Conditional routing
    workflow.add_edge(START, "filter_sender")
    workflow.add_conditional_edges("filter_sender", route_after_filter)
    workflow.add_edge("process_text", "extract_validate")
    workflow.add_edge("extract_validate", "deduplication")
    workflow.add_conditional_edges("deduplication", route_after_dedup)
    workflow.add_edge("save_to_db", END)
    
    return workflow.compile()


# Compiled pipeline singleton
pipeline = build_pipeline()


def run_langgraph_pipeline(
    email_id: str,
    gmail_message_id: str,
    sender: str,
    subject: str,
    raw_body: str,
    existing_drives: List[Dict] = None,
    api_key: str = None,
    use_gemini: bool = True,
    db: Session = None
) -> Dict[str, Any]:
    """Run the LangGraph email processing pipeline."""
    initial_state: PipelineState = {
        "email_id": email_id,
        "gmail_message_id": gmail_message_id,
        "sender": sender,
        "subject": subject,
        "raw_body": raw_body,
        "clean_text": "",
        "excerpts": [],
        "extracted_data": {},
        "status": "pending",
        "error_message": None,
        "api_key": api_key,
        "use_gemini": use_gemini,
        "existing_drives": existing_drives or [],
        "db": db,
        "saved_email_id": None,
        "saved_drive_id": None,
    }
    
    return pipeline.invoke(initial_state)


def pipeline_result_to_json(state: Dict[str, Any]) -> Dict[str, Any]:
    """Convert pipeline state to JSON response."""
    return {
        "email_id": state.get("email_id"),
        "gmail_message_id": state.get("gmail_message_id"),
        "sender": state.get("sender"),
        "subject": state.get("subject"),
        "status": state.get("status"),
        "error_message": state.get("error_message"),
        "excerpts": state.get("excerpts", []),
        "extraction_method": state.get("extracted_data", {}).get("extraction_method", "regex"),
        "extracted_data": state.get("extracted_data", {}),
        "saved_email_id": state.get("saved_email_id"),
        "saved_drive_id": state.get("saved_drive_id"),
        "clean_text_preview": (state.get("clean_text", "") or "")[:500]
    }
