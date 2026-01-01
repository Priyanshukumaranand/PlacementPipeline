"""
Gemini Extractor Module for Email Processing Pipeline.

Uses Gemini 1.5 Flash to extract structured placement data from emails.
"""

import os
import json
import re
from typing import Optional, Dict, Any

# Try new SDK first, fall back to old
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
    NEW_SDK = True
except ImportError:
    try:
        import google.generativeai as genai
        GEMINI_AVAILABLE = True
        NEW_SDK = False
    except ImportError:
        GEMINI_AVAILABLE = False
        NEW_SDK = False

# JSON schema for extraction (compact)
EXTRACTION_SCHEMA = {
    "company_name": "str|null",
    "role": "str|null - comma-sep if multiple",
    "drive_type": "internship|fte|both|null",
    "batch": "str|null - year",
    "drive_date": "YYYY-MM-DD|null",
    "registration_deadline": "YYYY-MM-DD|null",
    "eligible_branches": "str|null - CSE,IT format",
    "min_cgpa": "float|null",
    "ctc_or_stipend": "str|null",
    "job_location": "str|null",
    "registration_link": "url|null",
}

EXTRACTION_PROMPT = """You are an expert at extracting structured placement drive information from emails.

Extract ONLY explicit information from the email. Use null for any missing fields. Return valid JSON only.

Subject: {subject}
Email: {email_content}

Extraction Rules:
1. company_name: Extract the company name from subject or body. Clean up suffixes like "Pvt Ltd", "Inc", etc.
2. role: Job roles/positions (e.g., "SDE Intern", "Software Engineer"). Use comma-separated if multiple.
3. drive_type: "internship", "fte", or "both" based on what's mentioned.
4. batch: Target graduation year (e.g., "2025", "2026", "2027").
5. drive_date: When the drive/interview happens (YYYY-MM-DD format).
6. registration_deadline: Last date to apply/register (YYYY-MM-DD format).
7. eligible_branches: Branch codes like "CSE, IT, ECE" or "All Branches".
8. min_cgpa: Minimum CGPA requirement as a number (e.g., 7.0, 8.5).
9. ctc_or_stipend: Compensation in format like "₹12 LPA" or "₹40,000/month".
10. job_location: City name or "Remote" or "Hybrid".
11. registration_link: Full URL to application/registration form.

Return JSON with these fields. Use null for missing values.

Fields: {schema}"""


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
        Dictionary with extracted fields (null for missing)
    """
    # Default response with all nulls
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
    
    if not GEMINI_AVAILABLE:
        default_response["extraction_error"] = "Gemini library not installed"
        return default_response
    
    key = api_key or os.getenv("GOOGLE_API_KEY")
    if not key:
        default_response["extraction_error"] = "GOOGLE_API_KEY not configured"
        return default_response
    
    try:
        # Build prompt
        schema_str = json.dumps(EXTRACTION_SCHEMA, indent=2)
        prompt = EXTRACTION_PROMPT.format(
            email_content=email_content[:8000],  # Safety limit
            subject=subject,
            schema=schema_str
        )
        
        if NEW_SDK:
            # New google-genai SDK
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1024,
                )
            )
            response_text = response.text.strip()
        else:
            # Old google-generativeai SDK
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    top_p=0.95,
                    max_output_tokens=1024,
                )
            )
            response_text = response.text.strip()
        
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text
        
        # Parse JSON
        extracted = json.loads(json_str)
        
        # Merge with defaults (ensure all fields present)
        result = default_response.copy()
        for key in extracted:
            if key in result:
                result[key] = extracted[key]
        
        # Calculate confidence score based on fields extracted
        non_null_fields = sum(1 for k, v in result.items() 
                            if k not in ['confidence_score', 'extraction_error'] and v is not None)
        result['confidence_score'] = min(non_null_fields / 8.0, 1.0)  # 8 key fields
        
        return result
        
    except json.JSONDecodeError as e:
        default_response["extraction_error"] = f"JSON parse error: {str(e)}"
        return default_response
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
            # Try to infer
            if 'intern' in dt:
                result['drive_type'] = 'internship'
            elif 'full' in dt or 'fte' in dt:
                result['drive_type'] = 'fte'
            else:
                result['drive_type'] = None
    
    # Normalize role
    if result.get('role'):
        result['role'] = result['role'].strip()
    
    # Normalize eligible_branches
    if result.get('eligible_branches'):
        branches = result['eligible_branches'].upper()
        # Clean up common variations
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
        
        # Match by company + role + deadline
        if existing_company == new_company:
            if existing_role == new_role or not new_role or not existing_role:
                if existing_deadline == new_deadline or not new_deadline:
                    return True
    
    return False
