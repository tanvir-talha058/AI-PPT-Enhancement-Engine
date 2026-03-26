import json
import re
from typing import Any

import requests

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_URL,
    HF_API_KEY,
    HF_MODEL,
    HF_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_URL,
    REQUEST_TIMEOUT,
)


SYSTEM_PROMPT = """You are a professional presentation expert.

Rules:
- Improve clarity and impact
- Keep meaning unchanged
- Preserve the same number of bullets or paragraphs
- Keep output length close to the original (+/- 20%)
- Do not change structure

Return only valid JSON in this format:
{
  "slide_1": ["...", "..."]
}
"""


def _gemini_model_path(model_name: str) -> str:
    return model_name if model_name.startswith("models/") else f"models/{model_name}"


def build_context(slides: list[dict]) -> dict[str, list[str]]:
    context = {}
    for index, slide in enumerate(slides, start=1):
        context[f"slide_{index}"] = [paragraph["text"] for paragraph in slide["paragraphs"]]
    return context


def call_ai(structured_data: dict[str, list[str]]) -> dict[str, list[str]]:
    errors = []

    for provider in (_call_gemini, _call_openrouter, _call_huggingface):
        try:
            return provider(structured_data)
        except Exception as exc:
            errors.append(f"{provider.__name__}: {exc}")

    return _local_fallback(structured_data, errors)


def _call_gemini(structured_data: dict[str, list[str]]) -> dict[str, list[str]]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"{SYSTEM_PROMPT}\n\nInput JSON:\n{json.dumps(structured_data, ensure_ascii=True)}"
                    }
                ]
            }
        ]
    }
    response = requests.post(
        f"{GEMINI_URL}/{_gemini_model_path(GEMINI_MODEL)}:generateContent?key={GEMINI_API_KEY}",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _normalize_ai_output(_extract_json_object(text), structured_data)


def _call_openrouter(structured_data: dict[str, list[str]]) -> dict[str, list[str]]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
    return _normalize_ai_output(_extract_json_object(text), structured_data)


def _call_huggingface(structured_data: dict[str, list[str]]) -> dict[str, list[str]]:
    if not HF_API_KEY:
        raise RuntimeError("HF_API_KEY is not configured")

    prompt = f"{SYSTEM_PROMPT}\n\nInput JSON:\n{json.dumps(structured_data, ensure_ascii=True)}"
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

    return _normalize_ai_output(_extract_json_object(text), structured_data)


def _extract_json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise RuntimeError("Model response did not contain JSON")
    return json.loads(match.group(0))


def _normalize_ai_output(ai_output: dict[str, Any], original: dict[str, list[str]]) -> dict[str, list[str]]:
    normalized = {}
    for slide_key, paragraphs in original.items():
        candidate = ai_output.get(slide_key, paragraphs)
        if not isinstance(candidate, list):
            candidate = paragraphs

        cleaned = [str(item).strip() for item in candidate if str(item).strip()]
        if len(cleaned) != len(paragraphs):
            cleaned = paragraphs
        normalized[slide_key] = cleaned
    return normalized


def _local_fallback(structured_data: dict[str, list[str]], errors: list[str]) -> dict[str, list[str]]:
    output = {}
    for slide_key, paragraphs in structured_data.items():
        output[slide_key] = [_polish_sentence(paragraph) for paragraph in paragraphs]

    if errors:
        output["_meta"] = [f"AI providers unavailable. Fallback used: {' | '.join(errors)}"]

    return output


def _polish_sentence(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return text

    bullet_match = re.match(r"^(\s*[-*•]\s+)(.*)$", compact)
    prefix = bullet_match.group(1) if bullet_match else ""
    body = bullet_match.group(2) if bullet_match else compact

    if body.isupper() and len(body.split()) <= 8:
        polished = body.title()
    else:
        polished = _rewrite_phrase(body)

    if prefix:
        return f"{prefix}{polished}"
    return polished


def _rewrite_phrase(text: str) -> str:
    sentence = text.strip()
    if not sentence:
        return text

    sentence = sentence.rstrip(" .;:")
    sentence = re.sub(r"\s+", " ", sentence)
    sentence = _convert_weak_openings(sentence)

    replacements = [
        (r"\bwe should\b", "Prioritize"),
        (r"\bin order to\b", "to"),
        (r"\ba lot of\b", "many"),
        (r"\bvery important\b", "critical"),
        (r"\bmake sure\b", "ensure"),
        (r"\bhas the ability to\b", "can"),
        (r"\bis able to\b", "can"),
        (r"\bthe purpose of this is to\b", "This helps"),
        (r"\bdue to the fact that\b", "because"),
        (r"\bfor the purpose of\b", "for"),
        (r"\bimprove\b", "strengthen"),
        (r"\butilize\b", "use"),
        (r"\bleverage\b", "use"),
    ]

    for pattern, replacement in replacements:
        sentence = re.sub(pattern, replacement, sentence, flags=re.IGNORECASE)

    sentence = _tighten_opening(sentence)
    sentence = _finalize_sentence(sentence)
    return sentence


def _convert_weak_openings(sentence: str) -> str:
    patterns = [
        (r"^we need to\s+improve\b", "Improve"),
        (r"^we need to\s+increase\b", "Increase"),
        (r"^we need to\s+reduce\b", "Reduce"),
        (r"^we need to\s+build\b", "Build"),
        (r"^we need to\s+create\b", "Create"),
        (r"^we need to\s+develop\b", "Develop"),
        (r"^we need to\s+", ""),
        (r"^we want to\s+improve\b", "Improve"),
        (r"^we want to\s+increase\b", "Increase"),
        (r"^we want to\s+reduce\b", "Reduce"),
        (r"^we want to\s+", ""),
    ]

    for pattern, replacement in patterns:
        updated = re.sub(pattern, replacement, sentence, flags=re.IGNORECASE)
        if updated != sentence:
            return updated

    return sentence


def _tighten_opening(sentence: str) -> str:
    lower = sentence.lower()

    openings = [
        ("this slide talks about ", ""),
        ("this slide is about ", ""),
        ("the goal is to ", "Goal: "),
        ("our goal is to ", "Goal: "),
        ("we are trying to ", ""),
        ("we want to ", ""),
        ("there is ", ""),
        ("there are ", ""),
    ]

    for source, target in openings:
        if lower.startswith(source):
            sentence = target + sentence[len(source):]
            break

    if sentence.lower().startswith("goal: "):
        return sentence

    words = sentence.split()
    if len(words) <= 8 and not re.search(r"[.!?]$", sentence):
        return sentence.capitalize()

    return sentence


def _finalize_sentence(sentence: str) -> str:
    sentence = sentence.strip(" -")
    if not sentence:
        return sentence

    sentence = sentence[0].upper() + sentence[1:]

    if len(sentence.split()) <= 8 and ":" not in sentence and sentence[-1].isalnum():
        sentence = sentence.rstrip(".")
        return sentence

    if sentence[-1] not in ".!?":
        sentence = f"{sentence}."

    return sentence
