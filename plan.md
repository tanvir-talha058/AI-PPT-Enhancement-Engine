# AI PPT Enhancement Engine

## 🎯 Objective

Enhance PPT content using AI while preserving layout.

---

## 🧠 ARCHITECTURE

Backend:

* Flask (API layer)
* Redis (Queue + Cache)
* RQ Worker (Background processing)

AI Layer:

* Gemini (Primary - free tier)
* OpenRouter (Fallback)
* HuggingFace (Fallback)

---

## 📦 PROJECT STRUCTURE

project/
│
├── app.py                # Flask API
├── worker.py             # Background worker
├── tasks.py              # Processing logic
├── parser.py             # PPT extraction
├── ai_engine.py          # LLM calls
├── replacer.py           # Inject text back
├── config.py             # API keys + settings
├── requirements.txt
│
├── uploads/
├── outputs/

---

## ⚙️ FLASK API (app.py)

Endpoints:

POST /upload

* Upload PPT
* Push job to Redis queue
* Return job_id

GET /status/<job_id>

* Return job status

GET /download/<job_id>

* Return processed PPT

---

## 🔁 REDIS QUEUE (RQ)

Use RQ (Redis Queue)

Queue name: ppt_tasks

Flow:
upload → enqueue(process_ppt) → worker executes

---

## 🧠 TASK PIPELINE (tasks.py)

function process_ppt(file_path):

```
slides = extract_ppt(file_path)

structured_data = build_context(slides)

ai_output = call_ai(structured_data)

new_ppt = replace_text(file_path, ai_output)

save output

return output_path
```

---

## 🧩 PPT PARSER (parser.py)

* Use python-pptx
* Extract:

  * slide_id
  * shape_id
  * paragraph_index
  * text

---
## 🤖 AI ENGINE (ai_engine.py)

### API PRIORITY

1. Gemini (Primary)
2. OpenRouter
3. HuggingFace

---

### GEMINI CALL

* Model: gemini-pro
* Use structured prompt

---

### FALLBACK LOGIC

try Gemini
except:
try OpenRouter
except:
use HuggingFace

---

## 🧠 PROMPT TEMPLATE

SYSTEM:

You are a professional presentation expert.

Rules:

* Improve clarity and impact
* Keep meaning unchanged
* Same number of bullets
* Similar length (±20%)
* No structure change

OUTPUT JSON:

{
"slide_1": ["...", "..."]
}

---

## 🔧 REPLACER (replacer.py)

* Iterate shapes
* Replace paragraph.text

STRICT:

* No layout change
* No shape change

---

## ⚡ REDIS CONFIG

Redis used for:

* Queue
* Job tracking
* Caching AI responses

---

## 🧪 TEST FLOW

1. Upload PPT
2. Get job_id
3. Poll status
4. Download result

---

## 🚀 RUN INSTRUCTIONS

1. Start Redis
2. Run Flask app
3. Run worker

---

END
