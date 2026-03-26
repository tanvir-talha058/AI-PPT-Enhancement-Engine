from pathlib import Path
from uuid import uuid4

from ai_engine import build_context, call_ai
from config import OUTPUT_FOLDER, ensure_directories
from parser import extract_ppt
from replacer import replace_text


def process_ppt(file_path: str) -> dict:
    ensure_directories()

    source_path = Path(file_path)
    slides = extract_ppt(source_path)
    structured_data = build_context(slides)
    ai_output = call_ai(structured_data)

    output_name = f"{source_path.stem}_enhanced_{uuid4().hex[:8]}.pptx"
    output_path = OUTPUT_FOLDER / output_name
    replace_text(source_path, output_path, ai_output)

    return {
        "output_path": str(output_path),
        "preview": _build_preview(structured_data, ai_output),
    }


def _build_preview(original: dict[str, list[str]], enhanced: dict[str, list[str]]) -> dict:
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
