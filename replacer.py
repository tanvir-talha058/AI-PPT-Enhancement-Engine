"""Text replacement in PowerPoint presentations."""

from pathlib import Path

from pptx import Presentation


def replace_text(source_path: Path, output_path: Path, ai_output: dict[str, list[str]]) -> None:
    """
    Replace text in a presentation with AI-enhanced content.
    
    Maintains 1-to-1 paragraph mapping between slides and replacements.
    Only modifies text content, preserves all formatting and shapes.
    
    Args:
        source_path: Path to input .pptx file
        output_path: Path to save output .pptx file
        ai_output: Dict mapping slide keys to lists of replacement text
    """
    presentation = Presentation(str(source_path))

    for slide_number, slide in enumerate(presentation.slides, start=1):
        replacements = ai_output.get(f"slide_{slide_number}")
        if not replacements:
            continue

        replacement_index = 0
        for shape in slide.shapes:
            if not hasattr(shape, "text_frame") or shape.text_frame is None:
                continue

            for paragraph in shape.text_frame.paragraphs:
                if replacement_index >= len(replacements):
                    break

                if not paragraph.text.strip():
                    continue

                new_text = replacements[replacement_index]
                if paragraph.runs:
                    paragraph.runs[0].text = new_text
                    for run in paragraph.runs[1:]:
                        run.text = ""
                else:
                    paragraph.text = new_text
                replacement_index += 1

    presentation.save(str(output_path))
