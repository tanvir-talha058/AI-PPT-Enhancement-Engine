"""AI provider integration with layout-aware prompting and dual modes."""

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
    """Validate which AI providers are configured and available."""
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
        logger.warning("No external AI providers configured; using local fallback mode")
        logger.warning("  Set GEMINI_API_KEY, OPENROUTER_API_KEY, or HF_API_KEY for full AI enhancement")
        available.append("LocalFallback")

    return available


SYSTEM_PROMPT_SAFE = """You are a professional presentation expert.

Task (SAFE MODE - Structure Preserved):
- Rewrite each slide's text to sound sharper, clearer, and more executive-ready
- Keep the meaning unchanged
- **Preserve the same number of bullets or paragraphs** for each slide (critical)
- Keep the output length close to the original (+/- 20%)
- Keep numbers, percentages, dates, named entities, and factual claims intact
- Return concise presentation-ready copy, not explanations

Deck guidance:
{deck_guidance}

Slide guidance:
{slide_guidance}

Layout guidance:
{layout_guidance}

Return only valid JSON: {{"slide_1": ["...", "..."]}}
"""

SYSTEM_PROMPT_CREATIVE = """You are a professional presentation expert and design strategist.

Task (CREATIVE MODE - Intelligent Restructuring Allowed):
- Improve the presentation narrative, clarity, and visual hierarchy
- You may reorder, merge, or split bullets if it creates better flow
- You may adjust emphasis based on the slide's visual hierarchy
- Preserve the core meaning but optimize for impact
- Keep the total content within +/- 30% of original length
- Keep numbers, percentages, dates, named entities intact
- Return concise presentation-ready copy optimized for the slide's design

Deck guidance:
{deck_guidance}

Slide guidance:
{slide_guidance}

Layout guidance:
{layout_guidance}

Return valid JSON: {{"slide_1": ["...", "..."]}}

When restructuring: explain your reasoning in a comment after the JSON.
"""


def build_context(slides: list[dict]) -> dict[str, list[str]]:
    """Convert raw slide data into structured format for AI."""
    context = {}
    for index, slide in enumerate(slides, start=1):
        context[f"slide_{index}"] = [paragraph["text"] for paragraph in slide["paragraphs"]]
    return context


def build_enriched_context(slides: list[dict]) -> dict[str, dict[str, Any]]:
    """Build context with layout metadata for layout-aware prompting."""
    enriched = {}
    for index, slide in enumerate(slides, start=1):
        slide_key = f"slide_{index}"
        enriched[slide_key] = {
            "text": [p["text"] for p in slide["paragraphs"]],
            "layout": {
                "slide_type": slide.get("slide_type", "body"),
                "element_types": [p.get("element_type", "body") for p in slide["paragraphs"]],
                "font_sizes": [p.get("font_size", 12) for p in slide["paragraphs"]],
            },
        }
    return enriched


def call_ai(
    structured_data: dict[str, list[str]],
    mode: str = "safe",
    enriched_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """
    Call AI providers in priority order: Gemini → OpenRouter → HuggingFace.

    Args:
        structured_data: Structured slide data from build_context
        mode: "safe" (preserve structure) or "creative" (allow restructuring)
        enriched_data: Optional layout-aware data for better prompting

    Returns:
        dict of enhanced text per slide

    Raises:
        RuntimeError: If all providers fail
    """
    errors = []
    system_prompt = _build_system_prompt(
        structured_data, mode=mode, enriched_data=enriched_data
    )

    available = validate_providers()

    logger.info(f"Available providers: {', '.join(available)}")
    logger.info("Attempting AI providers in order: Gemini, OpenRouter, HuggingFace")

    for provider in (_call_gemini, _call_openrouter, _call_huggingface):
        try:
            logger.info(f"Trying {provider.__name__} (mode={mode})...")
            result = provider(structured_data, system_prompt)
            logger.info(f"{provider.__name__} succeeded")
            return result
        except Exception as exc:
            error_msg = f"{provider.__name__}: {exc}"
            errors.append(error_msg)
            logger.warning(error_msg)

    error_summary = " | ".join(errors)
    logger.error(f"All AI providers failed: {error_summary}")
    logger.warning("Falling back to local text refinement")
    return _call_local_fallback(structured_data)


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
    Falls back to original if structure mismatch detected (for safe mode).
    """
    normalized = {}
    for slide_key, paragraphs in original.items():
        candidate = ai_output.get(slide_key, paragraphs)
        if not isinstance(candidate, list):
            candidate = paragraphs

        cleaned = [str(item).strip() for item in candidate if str(item).strip()]
        if len(cleaned) != len(paragraphs):
            logger.warning(
                f"Output mismatch for {slide_key}: expected {len(paragraphs)}, got {len(cleaned)}"
            )
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
    """POST with automatic rate-limit (429) retry handling."""
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
                logger.warning(
                    f"Rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                )
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
                logger.warning(
                    f"Rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                )
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


def _build_system_prompt(
    structured_data: dict[str, list[str]],
    mode: str = "safe",
    enriched_data: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Build system prompt with mode and layout guidance."""
    base_template = SYSTEM_PROMPT_SAFE if mode == "safe" else SYSTEM_PROMPT_CREATIVE

    deck_guidance = _build_deck_guidance(structured_data)
    slide_guidance = _build_slide_guidance(structured_data, enriched_data)
    layout_guidance = _build_layout_guidance(enriched_data) if enriched_data else ""

    return base_template.format(
        deck_guidance=deck_guidance,
        slide_guidance=slide_guidance,
        layout_guidance=layout_guidance,
    )


def _call_local_fallback(structured_data: dict[str, list[str]]) -> dict[str, list[str]]:
    """Apply lightweight local rewrites when external AI providers are unavailable."""
    return {
        slide_key: [_refine_text(text) for text in paragraphs]
        for slide_key, paragraphs in structured_data.items()
    }


def _refine_text(text: str) -> str:
    """Make small, deterministic wording improvements without changing meaning."""
    original = str(text).strip()
    if not original:
        return original

    refined = original
    replacements = [
        (r"\bwe need to\b", ""),
        (r"\bthere are a lot of\b", "many"),
        (r"\ba lot of\b", "many"),
        (r"\bin order to\b", "to"),
        (r"\bdue to the fact that\b", "because"),
        (r"\bthis slide talks about\b", "this slide highlights"),
        (r"\bimprove onboarding process for\b", "improve onboarding for"),
        (r"\bvery\b", ""),
        (r"\breally\b", ""),
        (r"\bjust\b", ""),
    ]

    for pattern, replacement in replacements:
        refined = re.sub(pattern, replacement, refined, flags=re.IGNORECASE)

    refined = re.sub(r"\s+", " ", refined).strip()
    refined = re.sub(r"^we\s+need\s+to\s+", "", refined, flags=re.IGNORECASE)
    refined = refined[0].upper() + refined[1:] if refined else refined

    if not refined.endswith((".", "!", "?")) and len(refined.split()) > 6:
        refined += "."

    return refined


def _build_deck_guidance(structured_data: dict[str, list[str]]) -> str:
    """Build deck-level guidance."""
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
        guidance.append("- Many lines are headline-like or bullet-like, so prefer tight phrasing.")
    if numeric_lines:
        guidance.append("- Preserve all numbers and quantitative statements exactly.")

    return "\n".join(guidance)


def _build_slide_guidance(
    structured_data: dict[str, list[str]],
    enriched_data: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Build slide-level guidance."""
    guidance = []
    for slide_key, paragraphs in structured_data.items():
        non_empty = [str(p).strip() for p in paragraphs if str(p).strip()]
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


def _build_layout_guidance(enriched_data: dict[str, dict[str, Any]] | None) -> str:
    """Build layout-aware guidance based on visual hierarchy."""
    if not enriched_data:
        return ""

    guidance = []
    for slide_key, data in enriched_data.items():
        layout = data.get("layout", {})
        slide_type = layout.get("slide_type", "body")
        element_types = layout.get("element_types", [])

        if slide_type == "title":
            guidance.append(
                f"- {slide_key} (Title): Prioritize compelling, concise messaging. "
                "Maximize impact with sharp language."
            )
        elif slide_type == "agenda":
            guidance.append(
                f"- {slide_key} (Agenda): Keep items parallel and scannable. "
                "Use consistent phrasing."
            )
        elif slide_type == "closing":
            guidance.append(
                f"- {slide_key} (Closing): End with memorable language. "
                "Reinforce key takeaways or call-to-action."
            )
        else:
            # Analyze element type distribution
            has_title = "title" in element_types or "heading" in element_types
            if has_title:
                guidance.append(
                    f"- {slide_key}: Lead with a strong heading. "
                    "Body text should support and expand."
                )

    return "\n".join(guidance) if guidance else "No specific layout guidance."


def _gemini_model_path(model_name: str) -> str:
    """Format Gemini model name with proper path prefix."""
    return model_name if model_name.startswith("models/") else f"models/{model_name}"
