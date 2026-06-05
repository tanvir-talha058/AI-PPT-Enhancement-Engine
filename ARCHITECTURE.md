# ArcSlide Studio: Layout-Aware Architecture

## Overview

This document describes the enhanced layout-aware architecture that enables intelligent, context-aware PowerPoint refinement with two processing modes: **Safe Mode** (structure-preserving) and **Creative Mode** (intelligent restructuring).

## Core Components

### 1. Enhanced Parser (`parser.py`)

**Responsibilities:**
- Extracts text from PPTX files
- Analyzes layout metadata: font sizes, positions, element types
- Classifies slide types (title, body, agenda, closing)
- Builds structural understanding of presentations

**Key Features:**
```python
# Extract with layout metadata
slides = extract_ppt(file_path)
# Result includes:
# - text content
# - font_size for each element
# - position (left, top, width, height)
# - element_type (title, heading, body, bullet)
# - slide_type (title, agenda, body, closing)
```

**Element Classification:**
- **Title**: Font size >= 40pt OR first shape on first slide
- **Heading**: Font size 28-39pt OR 4-8 words at size >= 20pt
- **Subheading**: Font size 18-27pt
- **Bullet**: 5-8 words
- **Body**: Longer text or default

### 2. Vision Analyzer (`vision_analyzer.py`)

**Responsibilities:**
- Analyzes slides using vision models (OpenRouter)
- Extracts visual hierarchy and design intent
- Detects element prominence and reading order
- Merges visual analysis with text extraction

**Features:**
- Uses OpenRouter's vision models for layout analysis
- Supports slide type detection (title, agenda, body, closing, divider)
- Analyzes visual prominence (high/medium/low)
- Determines element positions (top/center/bottom)
- Currently optional (requires external image conversion)

**Fallback Behavior:**
- If vision analysis fails, system continues using text-based heuristics
- No vision dependency in core pipeline

### 3. Enhanced AI Engine (`ai_engine.py`)

**Dual-Mode Architecture:**

#### Safe Mode
```
System Prompt: "Preserve the same number of bullets/paragraphs"
- Maintains 1-to-1 text mapping
- Structure never changes
- Safe fallback for all content
- Returns JSON with slide-aligned arrays
```

#### Creative Mode
```
System Prompt: "Intelligently restructure for better flow"
- May reorder bullets
- May merge bullets
- May split long bullets
- Optimizes for narrative and visual hierarchy
- Still preserves core meaning
```

**Enriched Context:**
```python
enriched_data = {
    "slide_1": {
        "text": ["...", "..."],
        "layout": {
            "slide_type": "body",
            "element_types": ["heading", "bullet", "bullet"],
            "font_sizes": [28, 14, 14]
        }
    }
}
```

**Layout Guidance Generation:**
```python
# Deck-level guidance
- "The deck contains X slides and Y text segments"
- "Many lines are headline-like, prefer tight phrasing"
- "Preserve all numbers and quantitative statements"

# Slide-level guidance
- "Maintain crisp bullet cadence" (if 3+ bullets)
- "Keep metrics and figures unchanged" (if numeric content)
- "Compress long sentences" (if any sentence > 18 words)
- "Treat lines like headlines" (if all sentences <= 8 words)

# Layout guidance (enhanced)
- Title slides: "Maximize impact with sharp language"
- Agenda slides: "Keep items parallel and scannable"
- Closing slides: "End with memorable language"
- Body slides with headings: "Lead with strong heading, body supports"
```

### 4. Smart Replacer (`replacer.py`)

**Safe Mode Behavior:**
```python
# Enforces 1-to-1 mapping
# If replacements.length != original.length:
#   Skip replacement (safety fallback)
# Else:
#   Replace each paragraph in-place, preserve formatting
```

**Creative Mode Behavior:**
```python
# Allows structure changes
# Redistributes text to main content area
# Clears secondary shapes that had original content
# Preserves formatting where possible
# Handles bullet count changes gracefully
```

### 5. Processing Pipeline (`tasks.py`)

**Enhanced Workflow:**
```
1. Extract slides with layout metadata (parser.py)
2. Optional: Vision analysis for layout awareness (vision_analyzer.py)
3. Build structured data and enriched context
4. Check cache (MD5 of content)
5. Call AI with mode-specific prompt + layout guidance
6. Replace text using mode-appropriate strategy
7. Return output file + preview
```

**Mode Flow:**
```python
process_ppt(file_path, mode="safe", enable_vision=False)
# Returns: {
#   "output_path": "path/to/enhanced.pptx",
#   "preview": {"slide_key": "slide_1", "before": [...], "after": [...]},
#   "mode": "safe"
# }
```

### 6. API Layer (`app.py`)

**New Endpoints:**

#### `POST /upload`
- Accepts optional `mode` form parameter ("safe" or "creative")
- Validates mode against `ALLOW_CREATIVE_MODE` config
- Returns job ID with processing_mode in response

```json
{
  "job_id": "abc123...",
  "mode": "redis",              // queue type
  "processing_mode": "creative", // enhancement mode
  "can_cancel": true
}
```

#### `GET /config/features`
- Returns available processing modes
- Reports feature flags (vision analysis, layout awareness)
- Specifies default mode

```json
{
  "processing_modes": {
    "safe": {"label": "Safe Mode", "enabled": true},
    "creative": {"label": "Creative Mode", "enabled": true}
  },
  "features": {
    "vision_analysis": false,
    "layout_awareness": true
  },
  "default_mode": "safe"
}
```

## Configuration

### Environment Variables

```bash
# Processing modes
DEFAULT_PROCESSING_MODE=safe          # safe or creative
ALLOW_CREATIVE_MODE=true              # enable/disable creative mode
ENABLE_VISION_ANALYSIS=false          # enable/disable vision models

# Vision model (if enabled)
OPENROUTER_API_KEY=your_key          # required for vision analysis
```

### Frontend Integration

**Mode Selection:**
```html
<select id="processing-mode">
  <option value="safe">Safe Mode (preserve structure)</option>
  <option value="creative" disabled={!ALLOW_CREATIVE_MODE}>
    Creative Mode (intelligent restructuring)
  </option>
</select>
```

**Upload Form:**
```javascript
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("mode", selectedMode); // "safe" or "creative"

fetch("/upload", { method: "POST", body: formData });
```

## Usage Examples

### Safe Mode (Default)
```python
# User uploads presentation
# System extracts text, analyzes fonts/positions
# AI refines text within structural constraints
# Result: sharper language, same bullets/paragraphs
```

**Example:**
```
Before:
- We need to improve the onboarding process for new enterprise clients
- There are a lot of delays in the approval workflow

After (Safe Mode):
- Improve onboarding for new enterprise clients
- Approval workflow delays slowing execution
# ✓ Still 2 bullets, structure preserved
```

### Creative Mode (Layout-Aware)
```python
# User uploads presentation, selects "Creative Mode"
# System extracts text AND analyzes visual hierarchy
# AI understands slide design intent
# AI may merge/reorder/split bullets if it improves narrative
# Result: optimized flow while respecting visual hierarchy
```

**Example:**
```
Before:
- We identified that there are many delays in approval
- This impacts our ability to service clients quickly
- The delays happen at multiple workflow stages

After (Creative Mode):
- Approval delays prevent fast client service
- Multi-stage workflow bottlenecks must be addressed
# ✓ Still meaningful, but merged for flow
# (Vision analysis would show these were secondary points)
```

## Data Flow

```
User Upload
    ↓
[parser.py] Extract text + layout metadata
    ↓
[Optional: vision_analyzer.py] Analyze visual hierarchy
    ↓
[ai_engine.py] Build enriched context + layout guidance
    ↓
[AI Model] Process with mode-specific constraints
    ↓
[replacer.py] Apply changes (mode-aware strategy)
    ↓
[Output] Enhanced PPTX + preview
```

## Design Decisions

### Why Dual Mode?
1. **Safety First**: Safe mode guarantees structure preservation
2. **Creative Freedom**: Creative mode optimizes narrative flow
3. **User Choice**: Let users pick based on their needs
4. **Production Ready**: Safe mode can be production default

### Why Layout-Aware?
1. **Better Decisions**: AI understands visual hierarchy, not just text
2. **Design Respect**: Doesn't override intentional design choices
3. **Smarter Restructuring**: Can reorder based on visual prominence
4. **Slide-Type Awareness**: Title slides get different guidance than body slides

### Why Vision Is Optional?
1. **Text-Based Fallbacks**: Font sizes + positions work without vision
2. **Performance**: Vision analysis slower; text analysis is instant
3. **Flexibility**: Users can enable when needed
4. **No External Dependencies**: Core works without image conversion

### Cache Strategy
- **Key**: MD5 of original text content
- **Scope**: In-memory only (session-based)
- **Invalidation**: Automatic on new content
- **Benefit**: Fast re-processing of identical decks

## Extension Points

### Adding a New Processing Mode
1. Create prompt template in `ai_engine.py`
2. Add mode validation in `app.py` upload endpoint
3. Update `/config/features` response
4. Update replacer strategy in `replacer.py`

### Integrating Vision Models
1. Implement slide-to-image conversion in `vision_analyzer.py`
2. Test OpenRouter vision models
3. Merge results with text analysis
4. Update layout guidance in `ai_engine.py`

### Custom LLM Providers
1. Add provider function to `ai_engine.py` (e.g., `_call_claude`)
2. Add to provider fallback chain in `call_ai()`
3. Configure via environment variables
4. Test rate-limit handling

## Testing Strategy

### Unit Tests
```python
# parser.py
test_extract_ppt_with_layout()
test_classify_element_type()
test_classify_slide_type()

# ai_engine.py
test_safe_mode_preserves_count()
test_creative_mode_allows_restructuring()
test_layout_guidance_generation()

# replacer.py
test_safe_replacement_validates_count()
test_creative_replacement_handles_changes()
```

### Integration Tests
```python
# Full pipeline
test_safe_mode_full_pipeline()
test_creative_mode_full_pipeline()
test_vision_analysis_optional()
test_cache_behavior()
```

### Manual Testing
1. Upload same PPTX in both modes, compare results
2. Test vision analysis on/off behavior
3. Verify creative mode respects slide types
4. Check cache hit detection

## Performance Characteristics

| Component | Time | Scaling |
|-----------|------|---------|
| Text extraction | 100ms | O(slides) |
| Font size analysis | 50ms | O(paragraphs) |
| Vision analysis | 3-5s/slide | Optional |
| AI processing | 2-10s | O(tokens) |
| Text replacement | 200ms | O(paragraphs) |
| Total (safe) | ~3-15s | O(tokens) |
| Total (creative + vision) | ~15-40s | O(tokens + slides) |

## Future Enhancements

1. **Multi-Slide Context**: Consider neighboring slides for better decisions
2. **Chart/Image Awareness**: Analyze text alongside visual content
3. **Brand Consistency**: Maintain style guides across deck
4. **A/B Testing**: Compare mode outputs before committing
5. **Feedback Loop**: Learn from user edits
6. **Parallel Processing**: Process multiple slides concurrently
7. **Streaming Results**: Show changes as they arrive (websocket)
