"""Main processing pipeline for PPT enhancement."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from ai_engine import build_context, call_ai
from config import OUTPUT_FOLDER, ensure_directories, setup_logging
from parser import extract_ppt
from replacer import replace_text

logger = setup_logging(__name__)

# Simple in-memory cache for AI results
_ai_cache: dict[str, dict] = {}


def _get_cache_key(structured_data: dict[str, list[str]]) -> str:
    """Generate a cache key from structured data."""
    json_str = json.dumps(structured_data, sort_keys=True, ensure_ascii=True)
    return hashlib.md5(json_str.encode()).hexdigest()


def process_ppt(file_path: str) -> dict:
    """
    Process a PowerPoint file: extract text, enhance via AI, and save.
    
    Args:
        file_path: Path to the input .pptx file
        
    Returns:
        dict with 'output_path' and 'preview' keys
    """
    ensure_directories()

    source_path = Path(file_path)
    logger.info(f"Processing PPT: {source_path.name}")
    
    slides = extract_ppt(source_path)
    structured_data = build_context(slides)
    
    # Check cache
    cache_key = _get_cache_key(structured_data)
    if cache_key in _ai_cache:
        logger.info(f"Using cached AI results for {source_path.name}")
        ai_output = _ai_cache[cache_key]
    else:
        logger.info(f"Calling AI for {source_path.name}")
        ai_output = call_ai(structured_data)
        _ai_cache[cache_key] = ai_output
        logger.info(f"Cached AI results with key {cache_key}")

    output_name = f"{source_path.stem}_enhanced_{uuid4().hex[:8]}.pptx"
    output_path = OUTPUT_FOLDER / output_name
    replace_text(source_path, output_path, ai_output)
    
    logger.info(f"PPT processing complete: {output_path.name}")

    return {
        "output_path": str(output_path),
        "preview": _build_preview(structured_data, ai_output),
    }


def _build_preview(original: dict[str, list[str]], enhanced: dict[str, list[str]]) -> dict:
    """
    Build a preview showing before/after text from the first slide.
    
    Args:
        original: Original structured data
        enhanced: AI-enhanced structured data
        
    Returns:
        dict with preview data for UI display
    """
    slide_key = next((key for key in original if original.get(key)), None)
    if slide_key is None:
        return {
            "slide_key": None,
            "before": [],
            "after": [],
        }

    before = [text.strip() for text in original.get(slide_key, []) if str(text).strip()][:3]
    after = [text.strip() for text in enhanced.get(slide_key, []) if str(text).strip()][:3]

    while len(after) < len(before):
        after.append(before[len(after)])

    return {
        "slide_key": slide_key,
        "before": before,
        "after": after[: len(before)] if before else after,
    }
