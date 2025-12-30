"""
LangGraph Email Processing Pipeline.

Implements the 10-step pipeline:
1. Filter Sender → Only TPO coordinators
2. HTML → Text → Clean HTML to plain text  
3. Remove Noise → Signatures, disclaimers, replies
4. Token Trim → Limit to ~3000 tokens
5. Extract Sections → URLs, dates, numbers
6. Regex Extract → Pattern-based field extraction
7. Gemini Enhance → Optional AI enhancement
8. Validate → Normalize and verify data
9. Dedup Check → Prevent duplicates
10. Map to Model → PlacementDrive fields
"""

from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END

from app.services.text_cleaner import (
    html_to_text,
    remove_noise,
    trim_to_token_limit,
    extract_important_sections
)
from app.services.regex_extractor import extract_all_fields
from app.services.gemini_extractor import (
    extract_with_gemini,
    validate_extracted_data,
    check_duplicate
)

# Allowed senders - ONLY process emails from these
ALLOWED_SENDERS = [
    'navanita@iiit-bh.ac.in',
    'rajashree@iiit-bh.ac.in',
    'placement@iiit-bh.ac.in',
]


class PipelineState(TypedDict):
    """State that flows through the LangGraph pipeline."""
    # Input
    email_id: str
    gmail_message_id: str
    sender: str
    subject: str
    raw_body: str
    
    # Processing outputs
    is_allowed_sender: bool
    plain_text: str
    clean_text: str
    trimmed_text: str
    excerpts: List[str]
    
    # Extraction outputs
    regex_data: Dict[str, Any]      # From regex extraction
    gemini_data: Dict[str, Any]     # From Gemini (if available)
    extracted_data: Dict[str, Any]  # Merged result
    validated_data: Dict[str, Any]  # After validation
    
    # Status
    status: str
    is_duplicate: bool
    error_message: Optional[str]
    
    # Config
    api_key: Optional[str]
    use_gemini: bool
    existing_drives: List[Dict]


# ============ NODE FUNCTIONS ============

def filter_sender_node(state: PipelineState) -> dict:
    """Node 1: Filter by allowed senders AND campus drive keywords in subject."""
    sender_lower = state["sender"].lower()
    is_allowed = any(allowed in sender_lower for allowed in ALLOWED_SENDERS)
    
    if not is_allowed:
        return {
            "is_allowed_sender": False,
            "status": "filtered",
            "error_message": f"Sender not allowed: {state['sender']}"
        }
    
    # Check if subject contains campus/recruitment drive keywords
    subject_lower = state.get("subject", "").lower()
    drive_keywords = ["campus drive", "recruitment drive", "campus recruitment", 
                      "placement drive", "pool campus", "hiring drive",
                      "internship drive", "fte drive", "online test"]
    is_drive_email = any(kw in subject_lower for kw in drive_keywords)
    
    if not is_drive_email:
        return {
            "is_allowed_sender": True,
            "status": "filtered",
            "error_message": f"Not a campus drive email: {state.get('subject', '')[:50]}"
        }
    
    return {
        "is_allowed_sender": True,
        "status": "pending"
    }


def html_to_text_node(state: PipelineState) -> dict:
    """Node 2: Convert HTML to plain text."""
    if state.get("status") == "filtered":
        return {}
    
    try:
        plain_text = html_to_text(state["raw_body"])
        return {"plain_text": plain_text}
    except Exception as e:
        return {
            "status": "failed",
            "error_message": f"HTML conversion failed: {str(e)}"
        }


def remove_noise_node(state: PipelineState) -> dict:
    """Node 3: Remove signatures, disclaimers, reply history."""
    if state.get("status") in ["filtered", "failed"]:
        return {}
    
    try:
        clean_text = remove_noise(state.get("plain_text", ""))
        return {"clean_text": clean_text}
    except Exception as e:
        return {
            "status": "failed",
            "error_message": f"Noise removal failed: {str(e)}"
        }


def token_safety_node(state: PipelineState) -> dict:
    """Node 4: Trim to ~3000 tokens."""
    if state.get("status") in ["filtered", "failed"]:
        return {}
    
    try:
        trimmed_text = trim_to_token_limit(state.get("clean_text", ""), max_chars=12000)
        return {
            "trimmed_text": trimmed_text,
            "status": "cleaned"
        }
    except Exception as e:
        return {
            "status": "failed",
            "error_message": f"Token trimming failed: {str(e)}"
        }


def extract_sections_node(state: PipelineState) -> dict:
    """Node 5: Extract important sections (URLs, dates)."""
    if state.get("status") in ["filtered", "failed"]:
        return {}
    
    try:
        excerpts_str, excerpts_list = extract_important_sections(state.get("clean_text", ""))
        return {"excerpts": excerpts_list}
    except Exception:
        return {"excerpts": []}


def regex_extract_node(state: PipelineState) -> dict:
    """Node 6: Regex-based field extraction (ALWAYS runs)."""
    if state.get("status") in ["filtered", "failed"]:
        return {}
    
    try:
        regex_data = extract_all_fields(
            text=state.get("trimmed_text", ""),
            subject=state.get("subject", "")
        )
        return {
            "regex_data": regex_data,
            "extracted_data": regex_data.copy(),  # Use as base
            "status": "extracted"
        }
    except Exception as e:
        return {
            "status": "failed",
            "error_message": f"Regex extraction failed: {str(e)}"
        }


def gemini_enhance_node(state: PipelineState) -> dict:
    """Node 7: Optional Gemini enhancement (if enabled and API key available)."""
    if state.get("status") in ["filtered", "failed"]:
        return {}
    
    # Skip if Gemini not requested
    if not state.get("use_gemini", True):
        return {}
    
    api_key = state.get("api_key")
    if not api_key:
        return {}  # Silently skip, regex data is already there
    
    try:
        # Build LLM input with excerpts
        excerpts = state.get("excerpts", [])
        excerpts_text = "\n".join(excerpts) if excerpts else ""
        llm_input = f"EXTRACTED INFO:\n{excerpts_text}\n\nEMAIL:\n{state.get('trimmed_text', '')}"
        
        gemini_data = extract_with_gemini(
            email_content=llm_input,
            subject=state.get("subject", ""),
            api_key=api_key
        )
        
        # Merge with regex data (Gemini overrides nulls)
        merged = state.get("extracted_data", {}).copy()
        for key, value in gemini_data.items():
            if value is not None and key not in ["extraction_error", "confidence_score"]:
                merged[key] = value
        
        # Higher confidence if Gemini succeeded
        if not gemini_data.get("extraction_error"):
            merged["confidence_score"] = max(
                merged.get("confidence_score", 0),
                gemini_data.get("confidence_score", 0)
            )
            merged["extraction_method"] = "regex+gemini"
        
        return {
            "gemini_data": gemini_data,
            "extracted_data": merged
        }
    except Exception:
        # Gemini failed, but regex data still valid
        return {}


def validation_node(state: PipelineState) -> dict:
    """Node 8: Validate and normalize extracted data."""
    if state.get("status") in ["filtered", "failed"]:
        return {}
    
    try:
        validated = validate_extracted_data(state.get("extracted_data", {}))
        status = "needs_review" if validated.get("needs_review") else "validated"
        
        return {
            "validated_data": validated,
            "status": status
        }
    except Exception as e:
        return {
            "status": "failed",
            "error_message": f"Validation failed: {str(e)}"
        }


def deduplication_node(state: PipelineState) -> dict:
    """Node 9: Check for duplicates."""
    if state.get("status") in ["filtered", "failed"]:
        return {}
    
    try:
        is_dup = check_duplicate(
            state.get("validated_data", {}),
            state.get("existing_drives", [])
        )
        
        if is_dup:
            return {
                "is_duplicate": True,
                "status": "duplicate"
            }
        return {"is_duplicate": False}
    except Exception:
        return {"is_duplicate": False}


def map_to_model_node(state: PipelineState) -> dict:
    """Node 10: Map to PlacementDrive model fields."""
    if state.get("status") in ["filtered", "failed", "duplicate"]:
        return {}
    
    model_fields = [
        "company_name", "company_logo", "role", "drive_type", "batch",
        "drive_date", "registration_deadline", "eligible_branches",
        "min_cgpa", "eligibility_text", "ctc_or_stipend", "job_location",
        "registration_link", "status", "confidence_score", "official_source"
    ]
    
    validated = state.get("validated_data", {})
    placement_dict = {}
    
    for field in model_fields:
        placement_dict[field] = validated.get(field)
    
    # Set defaults
    if not placement_dict.get("status"):
        placement_dict["status"] = "upcoming"
    if not placement_dict.get("official_source"):
        placement_dict["official_source"] = "TPO Email"
    
    return {
        "validated_data": placement_dict,
        "status": "ready"
    }


# ============ BUILD PIPELINE ============

def build_pipeline() -> StateGraph:
    """Build and compile the LangGraph pipeline."""
    workflow = StateGraph(PipelineState)
    
    # Add all nodes
    workflow.add_node("filter_sender", filter_sender_node)
    workflow.add_node("html_to_text", html_to_text_node)
    workflow.add_node("remove_noise", remove_noise_node)
    workflow.add_node("token_safety", token_safety_node)
    workflow.add_node("extract_sections", extract_sections_node)
    workflow.add_node("regex_extract", regex_extract_node)
    workflow.add_node("gemini_enhance", gemini_enhance_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("deduplication", deduplication_node)
    workflow.add_node("map_to_model", map_to_model_node)
    
    # Linear flow
    workflow.add_edge(START, "filter_sender")
    workflow.add_edge("filter_sender", "html_to_text")
    workflow.add_edge("html_to_text", "remove_noise")
    workflow.add_edge("remove_noise", "token_safety")
    workflow.add_edge("token_safety", "extract_sections")
    workflow.add_edge("extract_sections", "regex_extract")
    workflow.add_edge("regex_extract", "gemini_enhance")
    workflow.add_edge("gemini_enhance", "validation")
    workflow.add_edge("validation", "deduplication")
    workflow.add_edge("deduplication", "map_to_model")
    workflow.add_edge("map_to_model", END)
    
    return workflow.compile()


# Compiled pipeline instance
pipeline = build_pipeline()


def run_langgraph_pipeline(
    email_id: str,
    gmail_message_id: str,
    sender: str,
    subject: str,
    raw_body: str,
    existing_drives: List[Dict] = None,
    api_key: str = None,
    use_gemini: bool = True
) -> Dict[str, Any]:
    """
    Run the full LangGraph email processing pipeline.
    
    Returns the final state with all extracted fields.
    """
    if existing_drives is None:
        existing_drives = []
    
    initial_state: PipelineState = {
        "email_id": email_id,
        "gmail_message_id": gmail_message_id,
        "sender": sender,
        "subject": subject,
        "raw_body": raw_body,
        "is_allowed_sender": False,
        "plain_text": "",
        "clean_text": "",
        "trimmed_text": "",
        "excerpts": [],
        "regex_data": {},
        "gemini_data": {},
        "extracted_data": {},
        "validated_data": {},
        "status": "pending",
        "is_duplicate": False,
        "error_message": None,
        "api_key": api_key,
        "use_gemini": use_gemini,
        "existing_drives": existing_drives,
    }
    
    final_state = pipeline.invoke(initial_state)
    return final_state


def pipeline_result_to_json(state: Dict[str, Any]) -> Dict[str, Any]:
    """Convert pipeline state to JSON for API response."""
    return {
        "email_id": state.get("email_id"),
        "gmail_message_id": state.get("gmail_message_id"),
        "sender": state.get("sender"),
        "subject": state.get("subject"),
        "status": state.get("status"),
        "is_duplicate": state.get("is_duplicate", False),
        "error_message": state.get("error_message"),
        "excerpts": state.get("excerpts", []),
        "extraction_method": state.get("extracted_data", {}).get("extraction_method", "regex"),
        "extracted_data": state.get("extracted_data", {}),
        "validated_data": state.get("validated_data", {}),
        "clean_text_preview": (state.get("clean_text", ""))[:500] + "..." if len(state.get("clean_text", "")) > 500 else state.get("clean_text", "")
    }
