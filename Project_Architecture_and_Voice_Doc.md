# Project Architecture & Documentation

## 1. Project Overview
The **SQL Data Analysis Agent** is an intelligent, full-stack web application designed to allow users to interact with their SQL Server databases and uploaded data files (CSV/Excel) using natural language. 

Users can type or speak their data questions. The system translates these questions into SQL queries, executes them securely, and returns the results along with AI-generated analysis and dynamic charts. It also features semantic caching to answer repeated questions instantly.

---

## 2. Frontend Architecture
The frontend is the user-facing interface, responsible for chat interactions, rendering charts, file uploads, and capturing voice input.

### Key Technologies & Libraries
- **Framework**: [Next.js 15](https://nextjs.org/) (using the App Router).
- **UI Library**: [React 19](https://react.dev/).
- **Styling**: Vanilla CSS (`globals.css`) with modern micro-animations and responsive design, avoiding heavy CSS frameworks for performance.
- **Data Visualization**: [Recharts](https://recharts.org/) (Lazy-loaded via `next/dynamic` to keep the initial page load fast).
- **Exporting**: [jsPDF](https://github.com/parallax/jsPDF) and [html2canvas](https://html2canvas.hertzen.com/) (Dynamically imported only when a user clicks the "Export PDF" button).
- **Icons**: SVG icons and Lucide-React.

### Core Structure
- `src/app/dashboard/page.tsx`: The main orchestrator. It manages the chat state, WebSocket connections, and UI layout.
- `src/components/`: Modularized components like `MessageBubble.tsx` (chat), `ChartRenderer.tsx` (graphs), and `FilePanel.tsx` (file analysis).

---

## 3. Backend Architecture
The backend is the engine of the application. It handles AI prompt generation, database connections, semantic caching, and machine learning inference for voice.

### Key Technologies & Libraries
- **API Framework**: [FastAPI](https://fastapi.tiangolo.com/) (High-performance asynchronous Python web framework).
- **Database ORM/Connector**: [SQLAlchemy](https://www.sqlalchemy.org/) and `pyodbc` (Specifically for connecting to Microsoft SQL Server).
- **AI / LLM Integration**: `openai` (For generating SQL and analyzing data), with fallback support for local LLMs via `Ollama`.
- **Semantic Caching**: `sentence-transformers` (Using `all-MiniLM-L6-v2` to convert text into vector embeddings for similarity searches).
- **Data Processing**: `pandas` (For parsing and comparing uploaded CSV/Excel files).
- **Rate Limiting & Metrics**: `slowapi` (API abuse prevention) and `prometheus-client` (System health monitoring).

### Core Structure
- `backend/main.py`: The FastAPI entry point containing all HTTP and WebSocket routes.
- `backend/app_core.py`: The core logic for AI SQL generation, file parsing, and cache retrieval.
- `backend/voice.py` & `backend/voice_grammar.py`: The machine learning pipeline for voice transcription.

---

## 4. Voice Integration Deep Dive
The voice feature allows users to click a microphone and speak their SQL queries naturally. Instead of relying on a paid cloud service (like Google Cloud Speech or OpenAI API), transcription happens **100% locally on the backend server** for maximum privacy and zero recurring costs.

### Technologies Used for Voice
- **`faster-whisper`**: A heavily optimized reimplementation of OpenAI's Whisper model using CTranslate2.
- **WebSockets (`fastapi.WebSocket`)**: For real-time, bidirectional audio streaming.
- **Web `MediaRecorder` API**: Native browser API to capture the user's microphone.

### How it Works (The Pipeline)
1. **Capture**: The user clicks the mic in the browser. The `MediaRecorder` captures audio in `.webm` format.
2. **Stream**: Audio chunks are sent to the backend over a WebSocket (`ws://localhost:8000/voice/stream`) every 250 milliseconds.
3. **Filter**: The backend uses **VAD (Voice Activity Detection)** to strip out long pauses of silence.
4. **Transcribe**: The audio is passed to the `tiny.en` Whisper model (running in INT8 precision in RAM) to convert speech to text.
5. **Grammar Correction**: The raw text runs through `voice_grammar.py` which applies Regex to fix phonetic mistakes (e.g., "group bye" → "GROUP BY"), normalizes numbers ("twenty three" → "23"), and formats date expressions.
6. **Return**: The cleaned text is sent back via WebSocket and auto-pastes into the user's chat box.

---

## 5. Recent Voice Updates (What, Why, and Where)

To optimize the voice feature for production, several major updates were recently applied across the codebase. Here is a detailed breakdown:

### A. Frontend File Updates
**File modified:** `src/app/dashboard/page.tsx`

| What was done | Why we did it (Purpose) |
| :--- | :--- |
| **Swapped HTTP POST for WebSockets** | Previously, the browser waited until the user stopped speaking to upload a large audio file. Now, chunks stream in the background while speaking, drastically reducing wait times. |
| **Added `Ctrl+Space` Shortcut** | Improves accessibility and speed for power users who don't want to use the mouse to click the microphone. |
| **Added "🔒 Local Voice" Badge** | Visually reassures the user that their voice data is secure and not being sent to third-party cloud servers. |
| **Mobile Responsiveness** | Increased the microphone button dimensions (44x44px) so it is easier to tap accurately on mobile screens. |
| **Added `NEXT_PUBLIC_ENABLE_VOICE` Flag** | Allows administrators to easily toggle the voice feature on or off via environment variables without changing code. |

### B. Backend File Updates
**File modified:** `backend/voice.py`

| What was done | Why we did it (Purpose) |
| :--- | :--- |
| **Enabled VAD Filtering** | Added `vad_filter=True` to the `faster-whisper` transcription call. This strips out silent pauses, which significantly speeds up transcription time because the ML model processes less raw audio. |

**File modified:** `backend/main.py`

| What was done | Why we did it (Purpose) |
| :--- | :--- |
| **Added WebSocket Route (`/voice/stream`)** | To receive the real-time audio chunks sent from the frontend `page.tsx` update. |
| **Added UUID Tracing Middleware** | Generates a unique `X-Request-ID` for every incoming request. This makes debugging much easier by tracking a single request through logs. |
| **Configured `slowapi` Rate Limiting** | Added `@limiter.limit("10/minute")` to prevent malicious users from spamming the ML model and crashing the server's CPU. |
| **Added Prometheus `/metrics` Endpoint** | Tracks `voice_requests_total` and `voice_latency_seconds` so server admins can monitor ML performance in tools like Grafana. |

**File modified:** `backend/requirements.txt`

| What was done | Why we did it (Purpose) |
| :--- | :--- |
| **Added `slowapi` & `prometheus-client`** | Installed the necessary Python dependencies to support the Rate Limiting and Metrics features added in `main.py`. |

### C. Documentation Updates
| File | What was done |
| :--- | :--- |
| `README.md` | Rewrote the standard Next.js template to properly explain the project, how to start the Python backend, and the voice integration architecture. |
| `TROUBLESHOOTING.md` | Created a brand new file detailing solutions for common issues like microphone permissions, WebSocket disconnects, and ML model loading failures. |
