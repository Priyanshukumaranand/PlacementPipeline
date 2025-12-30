"""
Text Cleaning Module for Email Processing Pipeline.

Handles:
1. HTML → Plain Text conversion
2. Noise removal (signatures, disclaimers, reply history)
3. Token safety (trimming to max tokens)
4. Section extraction (URLs, dates, numbers)
"""

import re
from bs4 import BeautifulSoup
from typing import Tuple, List

# Maximum tokens before trimming (1 token ≈ 4 chars)
MAX_CHARS = 12000  # ~3000 tokens

# Keywords to preserve when trimming
PRESERVE_KEYWORDS = [
    'apply', 'deadline', 'role', 'position', 'ctc', 'stipend',
    'eligibility', 'batch', 'branch', 'location', 'link',
    'cgpa', 'salary', 'lpa', 'package', 'register', 'date'
]

# Patterns for noise removal
SIGNATURE_PATTERNS = [
    r'thanks\s*(&|and)?\s*regards?.*$',
    r'best\s*regards?.*$',
    r'warm\s*regards?.*$',
    r'kind\s*regards?.*$',
    r'regards,?\s*$',
    r'thanking\s*you.*$',
    r'sincerely.*$',
    r'cheers.*$',
]

DISCLAIMER_PATTERNS = [
    r'this\s*(e-?mail|message)\s*(is\s*)?(intended|confidential).*',
    r'disclaimer.*$',
    r'this\s*communication\s*is\s*confidential.*',
    r'if\s*you\s*are\s*not\s*the\s*intended\s*recipient.*',
    r'privileged\s*and\s*confidential.*',
]

REPLY_PATTERNS = [
    r'^on\s+.+wrote:.*$',
    r'^from:\s+.+$',
    r'^sent:\s+.+$',
    r'^to:\s+.+$',
    r'^cc:\s+.+$',
    r'^subject:\s+.+$',
    r'^>+\s*.*$',  # Quoted text
    r'^-{3,}.*original\s*message.*-{3,}$',
]

NOISE_PATTERNS = [
    r'\[image:.*?\]',
    r'\[cid:.*?\]',
    r'<https?://[^\s]+>',  # Angle-bracket URLs
    r'sent\s*from\s*(my\s*)?(iphone|android|mobile).*$',
    r'get\s*outlook\s*for.*$',
]


def html_to_text(raw_html: str) -> str:
    """
    Convert HTML email content to clean plain text.
    
    Args:
        raw_html: Raw HTML string from email body
        
    Returns:
        Plain text with normalized whitespace
    """
    if not raw_html:
        return ""
    
    soup = BeautifulSoup(raw_html, "html.parser")
    
    # Remove script, style, and head tags
    for tag in soup(['script', 'style', 'head', 'meta', 'link']):
        tag.decompose()
    
    # Convert links to text with URL
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        text = a.get_text(strip=True)
        if href and text:
            a.replace_with(f"{text} ({href})")
        elif href:
            a.replace_with(href)
    
    # Convert <br> and </p> to newlines
    for br in soup.find_all('br'):
        br.replace_with('\n')
    for p in soup.find_all('p'):
        p.insert_after('\n')
    
    # Get text
    text = soup.get_text(separator=' ')
    
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces to single
    text = re.sub(r'\n\s*\n', '\n\n', text)  # Multiple newlines to double
    text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newlines
    
    return text.strip()


def remove_noise(text: str) -> str:
    """
    Remove signatures, disclaimers, reply history, and other noise.
    
    Args:
        text: Plain text email content
        
    Returns:
        Cleaned text with noise removed
    """
    if not text:
        return ""
    
    lines = text.split('\n')
    cleaned_lines = []
    in_quoted_section = False
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Skip empty lines in quoted section
        if in_quoted_section and not line.strip():
            continue
        
        # Detect start of quoted/reply section
        if any(re.match(pattern, line_lower, re.IGNORECASE) for pattern in REPLY_PATTERNS):
            in_quoted_section = True
            continue
        
        # Skip if we're in quoted section
        if in_quoted_section:
            # Check if line starts with '>' (quoted)
            if line.strip().startswith('>'):
                continue
            # Reset if we hit a line that doesn't look quoted
            if len(line.strip()) > 50 and not line.strip().startswith('>'):
                in_quoted_section = False
        
        # Skip signatures
        if any(re.match(pattern, line_lower, re.IGNORECASE) for pattern in SIGNATURE_PATTERNS):
            break  # Stop processing after signature
        
        # Skip disclaimers
        if any(re.search(pattern, line_lower, re.IGNORECASE) for pattern in DISCLAIMER_PATTERNS):
            continue
        
        # Skip other noise
        if any(re.search(pattern, line_lower, re.IGNORECASE) for pattern in NOISE_PATTERNS):
            continue
        
        cleaned_lines.append(line)
    
    result = '\n'.join(cleaned_lines)
    
    # Final cleanup
    result = re.sub(r'\n{3,}', '\n\n', result)  # Max 2 newlines
    result = re.sub(r'[ \t]+', ' ', result)  # Multiple spaces to single
    
    return result.strip()


def extract_important_sections(text: str) -> Tuple[str, List[str]]:
    """
    Extract important lines (URLs, dates, numbers) to prepend.
    
    Args:
        text: Cleaned email text
        
    Returns:
        Tuple of (excerpts_string, list_of_excerpts)
    """
    excerpts = []
    
    # URL pattern
    url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+' 
    urls = re.findall(url_pattern, text, re.IGNORECASE)
    for url in urls[:3]:  # Max 3 URLs
        excerpts.append(f"URL: {url}")
    
    # Date patterns
    date_patterns = [
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
        r'\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
    ]
    for pattern in date_patterns:
        dates = re.findall(pattern, text, re.IGNORECASE)
        for date in dates[:2]:
            excerpt = f"DATE: {date}"
            if excerpt not in excerpts:
                excerpts.append(excerpt)
    
    # CTC/Salary patterns
    money_patterns = [
        r'\b\d+(?:\.\d+)?\s*(?:lpa|lakhs?|lac)\b',
        r'₹\s*\d+(?:,\d+)*(?:\.\d+)?(?:\s*(?:lpa|lakh|k|per\s*month))?',
        r'\b(?:ctc|salary|stipend|package)\s*[:=]?\s*₹?\s*\d+(?:\.\d+)?[^\n]{0,20}',
    ]
    for pattern in money_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches[:2]:
            excerpt = f"COMPENSATION: {match.strip()}"
            if excerpt not in excerpts:
                excerpts.append(excerpt)
    
    # CGPA patterns
    cgpa_pattern = r'\b(?:cgpa|cg|gpa)\s*[:=]?\s*\d+(?:\.\d+)?(?:\s*(?:and\s*above|above|\+))?\b'
    cgpas = re.findall(cgpa_pattern, text, re.IGNORECASE)
    for cgpa in cgpas[:1]:
        excerpts.append(f"CGPA: {cgpa}")
    
    if excerpts:
        excerpts_str = "IMPORTANT EXCERPTS:\n" + "\n".join(f"- {e}" for e in excerpts) + "\n\n"
    else:
        excerpts_str = ""
    
    return excerpts_str, excerpts


def trim_to_token_limit(text: str, max_chars: int = MAX_CHARS) -> str:
    """
    Trim text to stay within token limit while preserving important content.
    
    Args:
        text: Text to trim
        max_chars: Maximum characters (default ~3000 tokens)
        
    Returns:
        Trimmed text that fits within limit
    """
    if len(text) <= max_chars:
        return text
    
    # Find sections with keywords to preserve
    lines = text.split('\n')
    important_lines = []
    other_lines = []
    
    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in PRESERVE_KEYWORDS):
            important_lines.append(line)
        else:
            other_lines.append(line)
    
    # Build result: important lines first, then fill with others
    important_text = '\n'.join(important_lines)
    remaining_chars = max_chars - len(important_text) - 100  # Buffer
    
    if remaining_chars > 0:
        other_text = '\n'.join(other_lines)[:remaining_chars]
        result = important_text + '\n\n' + other_text
    else:
        result = important_text[:max_chars]
    
    return result.strip()


def process_email_text(raw_html: str) -> Tuple[str, str, List[str]]:
    """
    Full text processing pipeline.
    
    Args:
        raw_html: Raw HTML email body
        
    Returns:
        Tuple of (final_text_for_llm, clean_text, excerpts_list)
    """
    # Step 1: HTML → Text
    plain_text = html_to_text(raw_html)
    
    # Step 2: Remove noise
    clean_text = remove_noise(plain_text)
    
    # Step 3: Token safety
    trimmed_text = trim_to_token_limit(clean_text)
    
    # Step 4: Extract important sections
    excerpts_str, excerpts_list = extract_important_sections(trimmed_text)
    
    # Combine excerpts with text for LLM
    final_text = excerpts_str + trimmed_text
    
    return final_text, clean_text, excerpts_list
