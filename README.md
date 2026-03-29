# ArcSlide Studio: AI PPT Enhancement Engine 🚀

**ArcSlide Studio** is a premium, AI-powered PowerPoint enhancement platform designed to transform rough presentation drafts into executive-ready decks. By leveraging state-of-the-art Large Language Models (LLMs), the engine refines slide content, tightens messaging, and improves structural flow—all while maintaining 100% layout fidelity.

![ArcSlide Studio Preview](https://via.placeholder.com/800x400/0f172a/f8fafc?text=ArcSlide+Studio+Premium+Interface)

## ✨ Core Features

-   **AI-Powered Refinement**: Automatically improves wording, executive tone, and structural clarity using Gemini 2.0, OpenRouter, or Hugging Face.
-   **Layout Preservation**: Advanced parsing logic ensures that your design, branding, and formatting remain untouched. Only the text is enhanced.
-   **Industry-Grade UI**: A high-performance, responsive interface featuring glassmorphism, fluid typography, and premium micro-animations.
-   **Intelligent Queue Management**: Supports both high-concurrency Redis-backed queues and lightweight local threading for smaller deployments.
-   **Deep Dark Mode**: Full support for system-preference and manual dark mode toggling with a custom-tailored elite color palette.
-   **Real-time Monitoring**: Live status tracking with progress bars and toast notifications.

## 🛠️ Technology Stack

-   **Backend**: Python, Flask, Redis, RQ (Redis Queue)
-   **Frontend**: Modern HTML5, Vanilla CSS (Premium System), Intersection Observer API
-   **AI Integration**: Google Gemini 2.0 Flash, OpenRouter (GPT-4o), Hugging Face Inference API
-   **Database**: SQLite (Job Tracking)

## 🚀 Getting Started

### Prerequisites

-   Python 3.9+
-   Redis (Optional, recommended for production-grade queuing)
-   API Key for a supported AI provider (Gemini recommended)

### Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/your-repo/AI-PPT-Enhancement-Engine.git
    cd AI-PPT-Enhancement-Engine
    ```

2.  **Setup Virtual Environment**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment**
    Copy `.env.example` to `.env` and add your API keys:
    ```bash
    cp .env.example .env
    ```

### Running the Application

**Local Threaded Mode (Development):**
```bash
python app.py
```

**Production Mode (Redis Queue):**
1. Ensure Redis is running (`redis-server`).
2. Start the worker:
   ```bash
   python worker.py
   ```
3. Start the Flask server:
   ```bash
   python app.py
   ```

## ⚙️ Configuration (.env)

| Variable | Description | Default |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Your Google Gemini API Key | Required (for Gemini) |
| `OPENROUTER_API_KEY` | OpenRouter API Key | Optional |
| `USE_REDIS` | Set to `true` to enable Redis queuing | `auto` |
| `MAX_FILE_SIZE_MB` | Maximum allowed PPTX size | `50` |
| `RATE_LIMIT` | Max uploads per hour per IP | `100` |

## 📐 Project Architecture

```text
├── app.py              # Flask API & Route Handlers
├── ai_engine.py        # LLM Integration & Prompt Engineering
├── tasks.py             # PPTX Processing Logic
├── config.py           # Configuration & Env Management
├── jobs_db.py          # SQLite Job Persistence
├── static/             # Premium CSS & Frontend Assets
├── templates/          # HTML Templates (Jinja2)
└── worker.py           # Redis Queue Worker (Optional)
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

> [!TIP]
> **Pro Tip**: For the best results, ensure your slides have clear structural headings. The AI engine uses hierarchical context to refine bullet points more effectively.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
