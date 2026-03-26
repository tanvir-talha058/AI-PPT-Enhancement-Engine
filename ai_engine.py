"""AI provider integration and prompt management."""

import json
import re
import time
from typing import Any

import requests
from requests import Response

from config import (
    GEMINI_API_KEY,
    GEMINI_MAX_RETRIES,
    GEMINI_MODEL,
    GEMINI_RETRY_DELAY_SECONDS,
    GEMINI_URL,
    HF_API_KEY,
    HF_MODEL,
    HF_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_URL,
    REQUEST_TIMEOUT,
    setup_logging,
)

logger = setup_logging(__name__)


def validate_providers() -> list[str]:
    """
    Validate which AI providers are configured and available.
    
    Returns:
        List of available provider names
    """
    available = []
    
    if GEMINI_API_KEY:
        available.append("Gemini")
        logger.info(f"Gemini configured: {GEMINI_MODEL}")
    else:
        logger.warning("Gemini not configured (GEMINI_API_KEY missing)")
    
    if OPENROUTER_API_KEY:
        available.append("OpenRouter")
        logger.info(f"OpenRouter configured: {OPENROUTER_MODEL}")
    else:
        logger.warning("OpenRouter not configured (OPENROUTER_API_KEY missing)")
    
    if HF_API_KEY:
        available.append("HuggingFace")
        logger.info(f"HuggingFace configured: {HF_MODEL}")
    else:
        logger.warning("HuggingFace not configured (HF_API_KEY missing)")
    
    if not available:
        logger.error("ERROR: No AI providers configured! Set at least one:")
        logger.error("  - GEMINI_API_KEY (recommended)")
        logger.error("  - OPENROUTER_API_KEY (reliable fallback)")
        logger.error("  - HF_API_KEY (free tier available)")
    
    return available


SYSTEM_PROMPT_TEMPLATE = """You are a professional presentation expert.

Task:
- Rewrite each slide's text to sound sharper, clearer, and more executive-ready
- Keep the meaning unchanged
- Preserve the same number of bullets or paragraphs for each slide
- Keep the output length close to the original (+/- 20%)
- Keep numbers, percentages, dates, named entities, and factual claims intact unless grammar requires tiny edits
- Return concise presentation-ready copy, not explanations

Deck guidance:
{deck_guidance}

Slide guidance:
{slide_guidance}

Return only valid JSON in this exact shape:
{{
  "slide_1": ["...", "..."]
}}
"""


def _gemini_model_path(model_name: str) -> str:
    """Format Gemini model name with proper path prefix."""
    return model_name if model_name.startswith("models/") else f"models/{model_name}"


def build_context(slides: list[dict]) -> dict[str, list[str]]:
    """
    Convert raw slide data into structured format for AI.
    
    Args:
        slides: List of slide dictionaries from parser
        
    Returns:
        dict mapping slide keys to lists of paragraph text
    """
    context = {}
    for index, slide in enumerate(slides, start=1):
        context[f"slide_{index}"] = [paragraph["text"] for paragraph in slide["paragraphs"]]
    return context


def call_ai(structured_data: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Call AI providers in priority order: Gemini → OpenRouter → HuggingFace.
    
    Args:
        structured_data: Structured slide data from build_context
        
    Returns:
        dict of enhanced text per slide
        
    Raises:
        RuntimeError: If all providers fail
    """
    errors = []
    system_prompt = _build_system_prompt(structured_data)
    
    available = validate_providers()
    if not available:
        msg = (
            "No AI providers configured. Please set environment variables:\n"
            "  GEMINI_API_KEY = https://ai.google.dev\n"
            "  OPENROUTER_API_KEY = https://openrouter.ai\n"
            "  HF_API_KEY = https://huggingface.co/settings/tokens"
        )
        logger.error(msg)
        raise RuntimeError(msg)
    
    logger.info(f"Available providers: {', '.join(available)}")
    logger.info("Attempting AI providers in order: Gemini, OpenRouter, HuggingFace")

    for provider in (_call_gemini, _call_openrouter, _call_huggingface):
        try:
            logger.info(f"Trying {provider.__name__}...")
            result = provider(structured_data, system_prompt)
            logger.info(f"{provider.__name__} succeeded")
            return result
        except Exception as exc:
            error_msg = f"{provider.__name__}: {exc}"
            errors.append(error_msg)
            logger.warning(error_msg)

    error_summary = " | ".join(errors)
    logger.error(f"All AI providers failed: {error_summary}")
    
    guidance = (
        "All configured AI providers failed. Solutions:\n"
        "1. Gemini free tier exhausted: Enable paid tier or configure backup providers\n"
        "2. Missing OpenRouter: Set OPENROUTER_API_KEY (https://openrouter.ai)\n"
        "3. HuggingFace error: Use supported model (mistralai/Mistral-7B-Instruct-v0.1)\n"
        "\nError details: " + error_summary
    )
    raise RuntimeError(guidance)


def _call_gemini(structured_data: dict[str, list[str]], system_prompt: str) -> dict[str, list[str]]:
    """Call Gemini API with rate-limit retry logic."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"{system_prompt}\n\nInput JSON:\n{json.dumps(structured_data, ensure_ascii=True)}"
                    }
                ]
            }
        ]
    }
    response = _post_with_rate_limit_retry(
        f"{GEMINI_URL}/{_gemini_model_path(GEMINI_MODEL)}:generateContent?key={GEMINI_API_KEY}",
        payload,
        max_retries=GEMINI_MAX_RETRIES,
        retry_delay_seconds=GEMINI_RETRY_DELAY_SECONDS,
    )
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    logger.debug("Gemini response received and parsed")
    return _normalize_ai_output(_extract_json_object(text), structured_data)


def _call_openrouter(structured_data: dict[str, list[str]], system_prompt: str) -> dict[str, list[str]]:
    """Call OpenRouter API with JSON mode."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(structured_data, ensure_ascii=True)},
        ],
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    logger.debug("OpenRouter response received and parsed")
    return _normalize_ai_output(_extract_json_object(text), structured_data)


def _call_huggingface(structured_data: dict[str, list[str]], system_prompt: str) -> dict[str, list[str]]:
    """Call HuggingFace Inference API."""
    if not HF_API_KEY:
        raise RuntimeError("HF_API_KEY is not configured")

    prompt = f"{system_prompt}\n\nInput JSON:\n{json.dumps(structured_data, ensure_ascii=True)}"
    response = requests.post(
        f"{HF_URL}/{HF_MODEL}",
        headers={"Authorization": f"Bearer {HF_API_KEY}"},
        json={"inputs": prompt},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, list) and data and "generated_text" in data[0]:
        text = data[0]["generated_text"]
    else:
        raise RuntimeError(f"Unexpected HuggingFace response: {data}")

    logger.debug("HuggingFace response received and parsed")
    return _normalize_ai_output(_extract_json_object(text), structured_data)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract JSON object from text (handles markdown code blocks, etc)."""
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise RuntimeError("Model response did not contain JSON")
    return json.loads(match.group(0))


def _normalize_ai_output(ai_output: dict[str, Any], original: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Normalize AI output to match input structure.
    Falls back to original if structure mismatch detected.
    """
    normalized = {}
    for slide_key, paragraphs in original.items():
        candidate = ai_output.get(slide_key, paragraphs)
        if not isinstance(candidate, list):
            candidate = paragraphs

        cleaned = [str(item).strip() for item in candidate if str(item).strip()]
        if len(cleaned) != len(paragraphs):
            logger.warning(f"Output mismatch for {slide_key}: expected {len(paragraphs)}, got {len(cleaned)}")
            cleaned = paragraphs
        normalized[slide_key] = cleaned
    return normalized


def _post_with_rate_limit_retry(
    url: str,
    payload: dict[str, Any],
    *,
    max_retries: int,
    retry_delay_seconds: float,
) -> Response:
    """
    POST with automatic rate-limit (429) retry handling.
    
    Args:
        url: Target URL
        payload: JSON payload
        max_retries: Maximum retry attempts
        retry_delay_seconds: Base delay between retries (exponential backoff)
        
    Returns:
        Response object
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429:
                if attempt >= max_retries:
                    raise RuntimeError(_build_rate_limit_message(response))

                delay = _next_retry_delay(response, retry_delay_seconds, attempt)
                logger.warning(f"Rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response
        except requests.HTTPError as exc:
            last_error = exc
            if exc.response is not None and exc.response.status_code == 429:
                if attempt >= max_retries:
                    raise RuntimeError(_build_rate_limit_message(exc.response)) from exc

                delay = _next_retry_delay(exc.response, retry_delay_seconds, attempt)
                logger.warning(f"Rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue

            raise
        except requests.RequestException as exc:
            last_error = exc
            raise RuntimeError(f"Request failed: {exc}") from exc

    if last_error is not None:
        raise RuntimeError(str(last_error)) from last_error

    raise RuntimeError("Request failed without a response")


def _next_retry_delay(response: Response, base_delay: float, attempt: int) -> float:
    retry_after_header = response.headers.get("Retry-After", "").strip()
    if retry_after_header.isdigit():
        return max(float(retry_after_header), 1.0)
    return max(base_delay * (2**attempt), 1.0)


def _build_rate_limit_message(response: Response) -> str:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = (
                payload.get("error", {}).get("message")
                if isinstance(payload.get("error"), dict)
                else payload.get("message", "")
            )
    except ValueError:
        detail = response.text.strip()

    suffix = f" Details: {detail}" if detail else ""
    return (
        "Gemini API rate limit reached. Wait a moment and retry, "
        "or configure OPENROUTER_API_KEY / HF_API_KEY as a backup provider."
        + suffix
    )


def _build_system_prompt(structured_data: dict[str, list[str]]) -> str:
    deck_guidance = _build_deck_guidance(structured_data)
    slide_guidance = _build_slide_guidance(structured_data)
    return SYSTEM_PROMPT_TEMPLATE.format(
        deck_guidance=deck_guidance,
        slide_guidance=slide_guidance,
    )


def _build_deck_guidance(structured_data: dict[str, list[str]]) -> str:
    slide_count = len(structured_data)
    paragraph_count = sum(len(paragraphs) for paragraphs in structured_data.values())
    short_lines = 0
    numeric_lines = 0

    for paragraphs in structured_data.values():
        for paragraph in paragraphs:
            text = str(paragraph).strip()
            if not text:
                continue
            if len(text.split()) <= 8:
                short_lines += 1
            if re.search(r"\d", text):
                numeric_lines += 1

    guidance = [
        f"- The deck contains {slide_count} slides and {paragraph_count} text segments.",
        "- Keep the wording confident and presentation-ready.",
    ]

    if short_lines >= max(2, paragraph_count // 3):
        guidance.append("- Many lines are headline-like or bullet-like, so prefer tight phrasing over full prose.")
    if numeric_lines:
        guidance.append("- Preserve all numbers and quantitative statements exactly.")

    return "\n".join(guidance)


def _build_slide_guidance(structured_data: dict[str, list[str]]) -> str:
    guidance = []
    for slide_key, paragraphs in structured_data.items():
        non_empty = [str(paragraph).strip() for paragraph in paragraphs if str(paragraph).strip()]
        if not non_empty:
            guidance.append(f"- {slide_key}: leave empty strings untouched.")
            continue

        traits = []
        if len(non_empty) >= 3:
            traits.append("maintain a crisp bullet cadence")
        if any(re.search(r"\d", text) for text in non_empty):
            traits.append("keep metrics and figures unchanged")
        if any(len(text.split()) > 18 for text in non_empty):
            traits.append("compress long sentences without losing meaning")
        if all(len(text.split()) <= 8 for text in non_empty):
            traits.append("treat lines like headlines or punchy bullets")

        if not traits:
            traits.append("improve clarity while preserving structure")

        guidance.append(f"- {slide_key}: " + "; ".join(traits) + ".")

    return "\n".join(guidance)
