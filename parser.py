"""PPT text extraction using python-pptx library."""

from pathlib import Path

from pptx import Presentation


def extract_ppt(file_path: Path) -> list[dict]:
    """
    Extract text and metadata from a PowerPoint presentation.
    
    Args:
        file_path: Path to .pptx file
        
    Returns:
        List of slide dictionaries containing:
        - slide_id: Unique slide identifier
        - slide_index: Zero-based slide number
        - paragraphs: List of paragraph objects with text and shape info
    """
    presentation = Presentation(str(file_path))
    extracted = []

    for slide_index, slide in enumerate(presentation.slides):
        paragraphs = []
        for shape_index, shape in enumerate(slide.shapes):
            if not hasattr(shape, "text_frame") or shape.text_frame is None:
                continue

            for paragraph_index, paragraph in enumerate(shape.text_frame.paragraphs):
                text = paragraph.text.strip()
                if not text:
                    continue

                paragraphs.append(
                    {
                        "shape_id": shape.shape_id,
                        "shape_index": shape_index,
                        "paragraph_index": paragraph_index,
                        "text": text,
                    }
                )

        if paragraphs:
            extracted.append(
                {
                    "slide_id": slide.slide_id,
                    "slide_index": slide_index,
                    "paragraphs": paragraphs,
                }
            )

    return extracted
