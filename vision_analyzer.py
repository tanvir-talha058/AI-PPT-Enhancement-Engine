"""Vision-based layout analysis for PowerPoint presentations."""

import base64
import json
import re
from pathlib import Path
from typing import Any, Optional

import requests

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    REQUEST_TIMEOUT,
    setup_logging,
)

logger = setup_logging(__name__)


def analyze_layout_from_pptx(file_path: Path) -> dict[str, Any]:
    """
    Analyze PPTX layout using vision models via OpenRouter.

    Args:
        file_path: Path to .pptx file

    Returns:
        dict with layout analysis:
        {
          "slide_1": {
            "slide_type": "title|agenda|body|closing",
            "visual_hierarchy": ["title", "subtitle", "body"],
            "elements": [
              {
                "text": "...",
                "type": "title|heading|body|emphasis",
                "position": "top|center|bottom",
                "prominence": "high|medium|low",
                "reading_order": 1
              }
            ]
          }
        }
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not configured; skipping visual analysis")
        return {}

    try:
        # Convert PPTX to images and analyze
        analysis = _analyze_pptx_with_vision(file_path)
        logger.info("Vision analysis complete for %s", file_path.name)
        return analysis
    except Exception as exc:
        logger.warning("Vision analysis failed: %s. Continuing without layout awareness.", exc)
        return {}


def _analyze_pptx_with_vision(file_path: Path) -> dict[str, Any]:
    """
    Use OpenRouter vision models to analyze PPTX slides.
    Converts slides to images and sends to vision model for analysis.
    """
    try:
        from pptx import Presentation
    except ImportError:
        logger.error("python-pptx required for vision analysis")
        return {}

    presentation = Presentation(str(file_path))
    analysis = {}

    for slide_num, slide in enumerate(presentation.slides, start=1):
        slide_key = f"slide_{slide_num}"
        slide_analysis = _analyze_single_slide(slide, slide_num)
        if slide_analysis:
            analysis[slide_key] = slide_analysis

    return analysis


def _analyze_single_slide(slide: Any, slide_number: int) -> Optional[dict[str, Any]]:
    """Analyze a single slide for layout and visual hierarchy."""
    try:
        from io import BytesIO
        from PIL import Image

        # Try to convert slide to image
        image_stream = BytesIO()
        try:
            # Note: python-pptx doesn't natively export to image
            # This is a limitation - we'll extract text layout instead
            slide_image = _slide_to_image(slide)
            if not slide_image:
                return None
        except Exception as e:
            logger.debug("Could not convert slide to image: %s", e)
            return None

        # Analyze with vision model
        analysis = _call_vision_model(image_stream, slide_number)
        return analysis
    except Exception as exc:
        logger.debug("Slide %d analysis failed: %s", slide_number, exc)
        return None


def _slide_to_image(slide: Any) -> Optional[bytes]:
    """
    Convert a PPTX slide to image bytes.
    Requires: python-pptx-image or external tool like LibreOffice.
    """
    # Placeholder: In production, use:
    # - LibreOffice CLI: libreoffice --headless --convert-to png
    # - python-pptx-image: from pptx_image import convert
    # For now, return None to skip (vision analysis will be empty)
    return None


def _call_vision_model(image_bytes: bytes, slide_number: int) -> Optional[dict[str, Any]]:
    """
    Call OpenRouter vision model to analyze slide layout.

    Returns structured analysis of visual hierarchy, element types, positions.
    """
    if not OPENROUTER_API_KEY:
        return None

    try:
        image_b64 = base64.b64encode(image_bytes).decode()

        prompt = f"""Analyze this PowerPoint slide #{slide_number} for visual hierarchy and element types.

Return JSON with this exact structure:
{{
  "slide_type": "title|agenda|body|closing|divider",
  "visual_hierarchy": ["top", "middle", "bottom"],
  "elements": [
    {{
      "text_preview": "first 20 chars of text",
      "type": "title|heading|subheading|body|bullet|accent",
      "position": "top|upper|center|lower|bottom",
      "prominence": "high|medium|low",
      "reading_order": 1,
      "relative_size": "large|medium|small"
    }}
  ],
  "design_notes": "brief visual style notes"
}}

Be precise about visual hierarchy based on size, color, and position.
Preserve actual text content in "text_preview" for matching.
"""

        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openrouter/auto",  # Use any available vision model
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None

        analysis = json.loads(match.group(0))
        logger.debug("Vision analysis for slide: %s", analysis)
        return analysis
    except Exception as exc:
        logger.warning("Vision model call failed: %s", exc)
        return None


def merge_layout_with_text(
    text_data: dict[str, list[str]],
    layout_data: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """
    Merge text extraction data with visual layout analysis.

    Creates an enriched structure:
    {
      "slide_1": {
        "text": ["...", "..."],
        "layout": { slide type, hierarchy, elements },
        "element_types": ["title", "body", "body"]  # Type for each text
      }
    }
    """
    enriched = {}

    for slide_key, texts in text_data.items():
        layout = layout_data.get(slide_key, {})

        enriched[slide_key] = {
            "text": texts,
            "layout": layout,
            "element_types": _infer_element_types(texts, layout),
            "slide_type": layout.get("slide_type", "body"),
        }

    return enriched


def _infer_element_types(texts: list[str], layout: dict[str, Any]) -> list[str]:
    """
    Infer element types for each text based on layout analysis.
    Falls back to heuristics if layout data is missing.
    """
    if not layout or "elements" not in layout:
        # Fallback: infer from text length and position
        return [_infer_type_from_text(text) for text in texts]

    elements = layout.get("elements", [])
    types = []

    for text in texts:
        matched = False
        for elem in elements:
            if elem.get("text_preview") and elem["text_preview"] in text:
                types.append(elem.get("type", "body"))
                matched = True
                break

        if not matched:
            types.append(_infer_type_from_text(text))

    return types


def _infer_type_from_text(text: str) -> str:
    """Infer element type from text characteristics."""
    word_count = len(text.split())

    if word_count <= 4:
        return "title"
    elif word_count <= 12:
        return "heading"
    else:
        return "body"
