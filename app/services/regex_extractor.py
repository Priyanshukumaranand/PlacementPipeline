"""
Regex-based Extractor for Placement Drive Fields.

Extracts structured data from email text using pattern matching.
Works WITHOUT any LLM/API - pure regex extraction.
"""

import re
from typing import Dict, Any, Optional, List
from datetime import datetime


def extract_company_from_subject(subject: str) -> Optional[str]:
    """
    Extract company name from email subject.
    
    Common patterns:
    - "Campus Recruitment Drive || Company Name || ..."
    - "Company Name - Campus Drive"
    - "Placement Drive: Company Name"
    - "Flipkart Campus Drive _2026" (Company at start)
    """
    if not subject:
        return None
    
    # Pattern 1: "|| Company Name ||" or "|| Company Name"
    match = re.search(r'\|\|\s*([^|]+?)\s*(?:\|\||$)', subject)
    if match:
        company = match.group(1).strip()
        # Clean up common suffixes
        company = re.sub(r'\s*(Pvt\.?\s*Ltd\.?|Private\s*Limited|Inc\.?|LLC|LLP)$', '', company, flags=re.IGNORECASE)
        if company:
            return company.strip()
    
    # Pattern 2: "Company Name Campus Drive" - Company at START of subject
    # Matches: "Flipkart Campus Drive", "Mindfire Solution Internship Drive"
    match = re.search(r'^(Re:\s*)?([A-Z][A-Za-z0-9\s\.]+?)\s+(?:Campus|Internship|Placement|Recruitment|FTE)\s+(?:Drive|Test|Program)', subject, re.IGNORECASE)
    if match:
        company = match.group(2).strip()
        if company and len(company) > 2:
            return company
    
    # Pattern 3: "Company Name - Campus Drive"
    match = re.search(r'^([A-Z][A-Za-z0-9\s]+?)\s*[-–]\s*(?:Campus|Placement)', subject)
    if match:
        return match.group(1).strip()
    
    # Pattern 4: "Placement Drive: Company Name"
    match = re.search(r'(?:Drive|Recruitment)\s*[:\-]\s*([A-Z][A-Za-z0-9\s&.]+)', subject)
    if match:
        return match.group(1).strip()
    
    # Pattern 5: "Campus drive by Company Name" or "drive by Company Name"
    match = re.search(r'(?:drive|recruitment)\s+by\s+([A-Za-z][A-Za-z0-9\s&.]+?)(?:\s*[_\-]|$)', subject, re.IGNORECASE)
    if match:
        company = match.group(1).strip()
        # Clean up common suffixes
        company = re.sub(r'\s*(Pvt\.?\s*Ltd\.?|Private\s*Limited|Inc\.?|LLC|LLP)$', '', company, flags=re.IGNORECASE)
        if company and len(company) > 2:
            return company.strip()
    
    # Pattern 6: Look for company names in subject with common patterns
    match = re.search(r'(?:for|from|at)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\s*[\-_|]|$)', subject, re.IGNORECASE)
    if match:
        company = match.group(1).strip()
        if company and len(company) > 2:
            return company
    
    return None


def extract_role(text: str) -> Optional[str]:
    """Extract job role/position from text."""
    # Common role patterns
    role_patterns = [
        r'(?:role|position|profile)\s*[:\-]?\s*([A-Za-z\s]+(?:Engineer|Developer|Analyst|Intern|Manager|Executive|Trainee)[A-Za-z\s]*)',
        r'(?:hiring\s+for|looking\s+for|opening\s+for)\s+([A-Za-z\s]+(?:Engineer|Developer|Analyst|Intern)[A-Za-z\s]*)',
        r'((?:Software|Frontend|Backend|Full[\s-]?Stack|Data|ML|AI|QA|Test|DevOps)\s*(?:Engineer|Developer|Analyst|Intern))',
        r'(SDE|SWE|MTS|SET)\s*(?:Intern|I|II|III)?',
    ]
    
    for pattern in role_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            role = match.group(1).strip()
            if len(role) > 3:  # Avoid too short matches
                return role.title()
    
    return None


def extract_batch(text: str, subject: str = "") -> Optional[str]:
    """Extract target batch year."""
    combined = f"{subject} {text}"
    
    # Pattern: 2025, 2026, 2027 batch
    match = re.search(r'\b(202[4-7])\s*(?:batch|passout|graduating|pass[\s-]?out)?', combined, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Pattern: Batch 2025
    match = re.search(r'batch\s*[:\-]?\s*(202[4-7])', combined, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return None


def extract_drive_type(text: str, subject: str = "") -> Optional[str]:
    """Extract drive type: internship, fte, or both."""
    combined = f"{subject} {text}".lower()
    
    has_intern = bool(re.search(r'\bintern(?:ship)?\b', combined))
    has_fte = bool(re.search(r'\b(?:fte|full[\s-]?time|permanent|ppo)\b', combined))
    
    if has_intern and has_fte:
        return "both"
    elif has_intern:
        return "internship"
    elif has_fte:
        return "fte"
    
    # Check for B.Tech/M.Tech mentions (usually FTE)
    if re.search(r'\bb\.?\s*tech\b.*\bm\.?\s*tech\b', combined):
        return "fte"
    
    return None


def extract_dates(text: str) -> Dict[str, Optional[str]]:
    """
    Extract drive date and registration deadline.
    Returns dates in YYYY-MM-DD format.
    """
    result = {"drive_date": None, "registration_deadline": None}
    
    # Date patterns
    date_patterns = [
        # DD/MM/YYYY or DD-MM-YYYY
        (r'(\d{1,2})[/\-](\d{1,2})[/\-](20\d{2})', lambda m: f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"),
        # 11th December 2025
        (r'(\d{1,2})(?:st|nd|rd|th)?\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})', 
         lambda m: _month_to_date(m.group(1), m.group(2), m.group(3))),
        # December 11, 2025
        (r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(20\d{2})',
         lambda m: _month_to_date(m.group(2), m.group(1), m.group(3))),
    ]
    
    # Find deadline first
    deadline_patterns = [
        r'(?:deadline|last\s*date|apply\s*by|register\s*by|before)\s*[:\-]?\s*',
        r'(?:registration|application)\s*(?:deadline|closes?)\s*[:\-]?\s*',
    ]
    
    for deadline_prefix in deadline_patterns:
        for pattern, converter in date_patterns:
            full_pattern = deadline_prefix + pattern
            match = re.search(full_pattern, text, re.IGNORECASE)
            if match:
                try:
                    result["registration_deadline"] = converter(match)
                    break
                except:
                    pass
        if result["registration_deadline"]:
            break
    
    # Find drive date
    drive_patterns = [
        r'(?:drive\s*date|interview\s*date|scheduled\s*on|on\s*date)\s*[:\-]?\s*',
    ]
    
    for drive_prefix in drive_patterns:
        for pattern, converter in date_patterns:
            full_pattern = drive_prefix + pattern
            match = re.search(full_pattern, text, re.IGNORECASE)
            if match:
                try:
                    result["drive_date"] = converter(match)
                    break
                except:
                    pass
        if result["drive_date"]:
            break
    
    # If no deadline found but we have dates, use the first one
    if not result["registration_deadline"]:
        for pattern, converter in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    result["registration_deadline"] = converter(match)
                    break
                except:
                    pass
    
    return result


def _month_to_date(day: str, month: str, year: str) -> str:
    """Convert month name to date string."""
    months = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
        'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
        'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
    }
    month_num = months.get(month[:3].lower(), '01')
    return f"{year}-{month_num}-{day.zfill(2)}"


def extract_branches(text: str) -> Optional[str]:
    """Extract eligible branches."""
    # Common branch patterns
    branch_pattern = r'\b(CSE|CS|IT|ECE|EE|EEE|MECH|ME|CIVIL|CE|AI|ML|DS|AIML)\b'
    matches = re.findall(branch_pattern, text.upper())
    
    if matches:
        # Deduplicate and normalize
        unique_branches = list(dict.fromkeys(matches))
        return ", ".join(unique_branches)
    
    # Check for "All branches"
    if re.search(r'all\s*branch(?:es)?', text, re.IGNORECASE):
        return "All Branches"
    
    return None


def extract_cgpa(text: str) -> Optional[float]:
    """Extract minimum CGPA requirement."""
    patterns = [
        r'(?:cgpa|cg|gpa)\s*[:\-]?\s*(\d+\.?\d*)\s*(?:and\s*above|above|\+)?',
        r'minimum\s*(?:cgpa|cg|gpa)\s*[:\-]?\s*(\d+\.?\d*)',
        r'(\d+\.?\d*)\s*(?:cgpa|cg|gpa)\s*(?:and\s*above|above|\+)?',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                cgpa = float(match.group(1))
                if 0 < cgpa <= 10:  # Valid CGPA range
                    return cgpa
            except ValueError:
                pass
    
    return None


def extract_ctc(text: str) -> Optional[str]:
    """Extract CTC or stipend information."""
    patterns = [
        # CTC: 12 LPA or Package: 12 LPA (with keyword prefix)
        r'(?:ctc|package|salary|compensation)\s*[:\-]?\s*(₹?\s*\d+(?:\.\d+)?(?:\s*[-–]\s*(?:₹?\s*)?\d+(?:\.\d+)?)?\s*(?:lpa|lakhs?)?)',
        # ₹12 LPA, 12 LPA, 12LPA, 4.5-6 LPA (must have LPA)
        r'(₹?\s*\d+(?:\.\d+)?(?:\s*[-–]\s*(?:₹?\s*)?\d+(?:\.\d+)?)?\s*(?:lpa|lakhs?\s*per\s*annum|l\.?p\.?a\.?))',
        # Stipend: ₹18,000 per month or ₹75,000/Month
        r'(?:stipend)\s*[:\-]?\s*(₹?\s*\d+(?:,\d+)*\s*(?:per\s*month|\/\s*month|p\.?m\.?))',
        # ₹X per month or X/month (must have per month)
        r'(₹?\s*\d+(?:,\d+)*\s*(?:per\s*month|\/\s*month))',
        # ₹18,000/month without keyword
        r'(₹\s*\d+(?:,\d+)*\s*\/\s*month)',
    ]
    
    all_matches = []
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            ctc = match.group(1).strip()
            # Normalize
            ctc = re.sub(r'\s+', ' ', ctc)
            all_matches.append(ctc)
    
    # Prefer LPA over monthly if both found
    for m in all_matches:
        if 'lpa' in m.lower() or 'lakhs' in m.lower():
            return m
    return all_matches[0] if all_matches else None


def extract_location(text: str) -> Optional[str]:
    """Extract job location."""
    # Common Indian cities
    cities = [
        'Bangalore', 'Bengaluru', 'Hyderabad', 'Chennai', 'Mumbai', 'Delhi',
        'Pune', 'Noida', 'Gurgaon', 'Gurugram', 'Kolkata', 'Ahmedabad',
        'Bhubaneswar', 'Jaipur', 'Kochi', 'Thiruvananthapuram', 'Coimbatore',
        'Chandigarh', 'Lucknow', 'Indore', 'Nagpur', 'Visakhapatnam'
    ]
    
    # Check for city names FIRST (most reliable)
    for city in cities:
        if re.search(rf'\b{city}\b', text, re.IGNORECASE):
            return city
    
    # Check for remote/WFH
    if re.search(r'\b(remote|work\s*from\s*home|wfh|hybrid)\b', text, re.IGNORECASE):
        return "Remote"
    
    # Pattern: Location: City or Work Location: City (only if city wasn't found)
    match = re.search(r'(?:job\s*location|work\s*location|location)\s*[:\-]\s*([A-Za-z][A-Za-z\s,]{2,30})', text, re.IGNORECASE)
    if match:
        loc = match.group(1).strip()
        # Filter out common false positives
        if loc.lower() not in ['ment officer', 'ment offers', 'placement']:
            return loc.title()
    
    return None


def extract_registration_link(text: str) -> Optional[str]:
    """Extract registration/application link."""
    # Find URLs
    url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+'
    urls = re.findall(url_pattern, text, re.IGNORECASE)
    
    # Filter out common non-registration URLs
    excluded_domains = ['linkedin.com/in/', 'twitter.com', 'facebook.com', 'instagram.com']
    
    for url in urls:
        is_excluded = any(domain in url.lower() for domain in excluded_domains)
        if not is_excluded:
            # Prefer URLs with registration-related keywords
            if any(kw in url.lower() for kw in ['register', 'apply', 'form', 'career', 'job', 'recruit']):
                return url
    
    # Return first non-excluded URL
    for url in urls:
        is_excluded = any(domain in url.lower() for domain in excluded_domains)
        if not is_excluded:
            return url
    
    return None


def extract_all_fields(text: str, subject: str = "") -> Dict[str, Any]:
    """
    Extract all PlacementDrive fields from email text.
    
    Args:
        text: Cleaned email body text
        subject: Email subject line
        
    Returns:
        Dictionary with all extracted fields (None for missing)
    """
    dates = extract_dates(text)
    
    result = {
        "company_name": extract_company_from_subject(subject),
        "role": extract_role(text),
        "drive_type": extract_drive_type(text, subject),
        "batch": extract_batch(text, subject),
        "drive_date": dates.get("drive_date"),
        "registration_deadline": dates.get("registration_deadline"),
        "eligible_branches": extract_branches(text),
        "min_cgpa": extract_cgpa(text),
        "ctc_or_stipend": extract_ctc(text),
        "job_location": extract_location(text),
        "registration_link": extract_registration_link(text),
        "confidence_score": 0.0,
        "extraction_method": "regex"
    }
    
    # Calculate confidence based on fields extracted
    non_null = sum(1 for k, v in result.items() 
                   if k not in ['confidence_score', 'extraction_method'] and v is not None)
    result["confidence_score"] = min(non_null / 8.0, 1.0)
    
    return result
