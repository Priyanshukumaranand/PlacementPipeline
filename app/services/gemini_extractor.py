"""
Gemini Extractor Module for Email Processing Pipeline.

Uses LangChain + Gemini 1.5 Flash for cleaner structured extraction.
Maintains backwards compatibility with existing function signatures.
"""

import os
import re
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

# LangChain imports
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False


class PlacementInfo(BaseModel):
    """Pydantic model for structured placement extraction."""
    company_name: Optional[str] = Field(None, description="Company name from subject/body")
    role: Optional[str] = Field(None, description="Job roles, comma-separated if multiple")
    drive_type: Optional[str] = Field(None, description="internship, fte, or both")
    batch: Optional[str] = Field(None, description="Target graduation year like 2025, 2026")
    drive_date: Optional[str] = Field(None, description="Drive date in YYYY-MM-DD format")
    registration_deadline: Optional[str] = Field(None, description="Last date to apply YYYY-MM-DD")
    eligible_branches: Optional[str] = Field(None, description="Branch codes like CSE, IT, ECE")
    min_cgpa: Optional[float] = Field(None, description="Minimum CGPA requirement")
    ctc_or_stipend: Optional[str] = Field(None, description="Compensation like ₹12 LPA")
    job_location: Optional[str] = Field(None, description="City name, Remote, or Hybrid")
    registration_link: Optional[str] = Field(None, description="Full URL to apply")


EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert at extracting structured placement drive information.
Extract ONLY explicit information from the email. Use null for missing fields.
Return valid JSON matching this schema: {format_instructions}"""),
    ("human", """Subject: {subject}

Email Content:
{email_content}

Extract placement details as JSON:""")
])


def _get_llm(api_key: str) -> "ChatGoogleGenerativeAI":
    """Get configured Gemini LLM instance."""
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=api_key,
        temperature=0.1,
        max_output_tokens=1024,
    )


def extract_with_gemini(
    email_content: str,
    subject: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract structured data from email using Gemini 1.5 Flash.
    
    Args:
        email_content: Cleaned email text (with excerpts prepended)
        subject: Email subject line
        api_key: Optional Gemini API key
        
    Returns:
        Dictionary with extracted fields (None for missing)
    """
    default_response = {
        "company_name": None,
        "role": None,
        "drive_type": None,
        "batch": None,
        "drive_date": None,
        "registration_deadline": None,
        "eligible_branches": None,
        "min_cgpa": None,
        "ctc_or_stipend": None,
        "job_location": None,
        "registration_link": None,
        "confidence_score": 0.0,
        "extraction_error": None
    }
    
    if not LANGCHAIN_AVAILABLE:
        default_response["extraction_error"] = "LangChain not installed"
        return default_response
    
    key = api_key or os.getenv("GOOGLE_API_KEY")
    if not key:
        default_response["extraction_error"] = "GOOGLE_API_KEY not configured"
        return default_response
    
    try:
        # Build chain: Prompt -> LLM -> JSON Parser
        parser = JsonOutputParser(pydantic_object=PlacementInfo)
        llm = _get_llm(key)
        chain = EXTRACTION_PROMPT | llm | parser
        
        # Invoke chain
        extracted = chain.invoke({
            "subject": subject,
            "email_content": email_content[:8000],
            "format_instructions": parser.get_format_instructions()
        })
        
        # Merge with defaults
        result = default_response.copy()
        for k, v in extracted.items():
            if k in result and v is not None:
                result[k] = v
        
        # Calculate confidence
        non_null = sum(1 for k, v in result.items() 
                      if k not in ['confidence_score', 'extraction_error'] and v is not None)
        result['confidence_score'] = min(non_null / 8.0, 1.0)
        
        return result
        
    except Exception as e:
        default_response["extraction_error"] = f"Gemini error: {str(e)}"
        return default_response


def validate_extracted_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize extracted data.
    
    Args:
        data: Extracted data dictionary
        
    Returns:
        Validated data with needs_review flag if issues found
    """
    result = data.copy()
    result['needs_review'] = False
    validation_errors = []
    
    # Required field check
    if not result.get('company_name'):
        result['needs_review'] = True
        validation_errors.append("Missing company_name")
    
    # Normalize company name
    if result.get('company_name'):
        result['company_name'] = result['company_name'].strip().title()
    
    # Validate CGPA
    if result.get('min_cgpa') is not None:
        try:
            cgpa = float(result['min_cgpa'])
            if cgpa < 0 or cgpa > 10:
                result['min_cgpa'] = None
                validation_errors.append("Invalid CGPA range")
        except (ValueError, TypeError):
            result['min_cgpa'] = None
    
    # Validate URLs
    if result.get('registration_link'):
        url = result['registration_link']
        if not url.startswith(('http://', 'https://')):
            result['registration_link'] = None
            validation_errors.append("Invalid registration link")
    
    # Normalize drive_type
    if result.get('drive_type'):
        dt = result['drive_type'].lower().strip()
        if dt not in ['internship', 'fte', 'both']:
            if 'intern' in dt:
                result['drive_type'] = 'internship'
            elif 'full' in dt or 'fte' in dt:
                result['drive_type'] = 'fte'
            else:
                result['drive_type'] = None
    
    # Normalize role
    if result.get('role'):
        result['role'] = result['role'].strip()
    
    # Normalize branches
    if result.get('eligible_branches'):
        branches = result['eligible_branches'].upper()
        branches = branches.replace('COMPUTER SCIENCE', 'CSE')
        branches = branches.replace('INFORMATION TECHNOLOGY', 'IT')
        branches = branches.replace('ELECTRONICS', 'ECE')
        result['eligible_branches'] = branches
    
    result['validation_errors'] = validation_errors
    return result


def check_duplicate(
    extracted: Dict[str, Any],
    existing_drives: list
) -> bool:
    """
    Check if this placement drive already exists.
    
    Args:
        extracted: Newly extracted data
        existing_drives: List of existing drive dicts from DB
        
    Returns:
        True if duplicate exists
    """
    if not extracted.get('company_name'):
        return False
    
    new_company = extracted['company_name'].lower().strip()
    new_role = (extracted.get('role') or '').lower().strip()
    new_deadline = extracted.get('registration_deadline')
    
    for drive in existing_drives:
        existing_company = (drive.get('company_name') or '').lower().strip()
        existing_role = (drive.get('role') or '').lower().strip()
        existing_deadline = drive.get('registration_deadline')
        
        if existing_company == new_company:
            if existing_role == new_role or not new_role or not existing_role:
                if existing_deadline == new_deadline or not new_deadline:
                    return True
    
    return False
