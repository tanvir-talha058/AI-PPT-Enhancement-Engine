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

    return {"output_path": str(output_path)}
