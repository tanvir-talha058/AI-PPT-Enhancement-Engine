"""Main processing pipeline for PPT enhancement with layout awareness."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from ai_engine import build_context, build_enriched_context, call_ai
from config import OUTPUT_FOLDER, ensure_directories, setup_logging
from parser import extract_ppt
from replacer import replace_text
from vision_analyzer import analyze_layout_from_pptx, merge_layout_with_text

logger = setup_logging(__name__)

_ai_cache: dict[str, dict] = {}


def _get_cache_key(structured_data: dict[str, list[str]]) -> str:
    """Generate a cache key from structured data."""
    json_str = json.dumps(structured_data, sort_keys=True, ensure_ascii=True)
    return hashlib.md5(json_str.encode()).hexdigest()


def process_ppt(file_path: str, mode: str = "safe", enable_vision: bool = False) -> dict:
    """
    Process a PowerPoint file: extract text, enhance via AI, and save.

    Args:
        file_path: Path to the input .pptx file
        mode: "safe" (preserve structure) or "creative" (allow restructuring)
        enable_vision: Whether to use vision analysis for layout awareness

    Returns:
        dict with 'output_path' and 'preview' keys
    """
    ensure_directories()

    source_path = Path(file_path)
    logger.info(f"Processing PPT (mode={mode}): {source_path.name}")

    # Extract text and layout metadata
    slides = extract_ppt(source_path)
    structured_data = build_context(slides)

    # Optional: Vision-based layout analysis
    vision_analysis = {}
    if enable_vision:
        logger.info("Running vision analysis for %s", source_path.name)
        vision_analysis = analyze_layout_from_pptx(source_path)

    # Check cache
    cache_key = _get_cache_key(structured_data)
    if cache_key in _ai_cache:
        logger.info(f"Using cached AI results for {source_path.name}")
        ai_output = _ai_cache[cache_key]
    else:
        logger.info(f"Calling AI (mode={mode}) for {source_path.name}")
        enriched_data = build_enriched_context(slides) if vision_analysis else None
        ai_output = call_ai(structured_data, mode=mode, enriched_data=enriched_data)
        _ai_cache[cache_key] = ai_output
        logger.info(f"Cached AI results with key {cache_key}")

    # Use short output name to avoid Windows 260-char path limit
    output_name = f"enhanced_{uuid4().hex[:8]}.pptx"
    output_path = OUTPUT_FOLDER / output_name
    replace_text(source_path, output_path, ai_output, mode=mode)

    logger.info(f"PPT processing complete (mode={mode}): {output_path.name}")

    return {
        "output_path": str(output_path),
        "preview": _build_preview(structured_data, ai_output),
        "mode": mode,
    }


def _build_preview(original: dict[str, list[str]], enhanced: dict[str, list[str]]) -> dict:
    """Build a preview showing before/after text from the first slide."""
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
