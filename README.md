# SQL Data Analysis Agent

An intelligent, AI-powered SQL analytics dashboard built with Next.js and FastAPI. It allows users to chat with their SQL Server databases, generate dynamic reports, upload and compare CSV/Excel files, and perform natural-language voice queries using a fully local Whisper model.

## Features
- **Natural Language to SQL**: Converts typed questions into accurate SQL queries using LLMs.
- **Voice Queries (Local Whisper)**: Speak your queries naturally. Uses `faster-whisper` running locally for privacy-preserving, lightning-fast transcription with automatic grammar correction, number normalization, and date-range mapping.
- **File Analysis**: Upload `.csv` or `.xlsx` files and instantly chat with them, generate charts, and compare multiple files simultaneously.
- **Dynamic Charts & PDF Export**: Results are automatically graphed and can be exported as branded PDF reports.
- **Semantic Caching**: Previous complex queries are cached using sentence-transformers (all-MiniLM-L6-v2) for instant sub-100ms retrieval of similar questions.

---

## 🏗 Setup & Installation

### 1. Backend (FastAPI + Python)
The backend manages the database connections, LLM prompt generation, and the local Whisper ML model.

```bash
cd backend
python -m venv .venv
# Activate venv (Windows: .venv\Scripts\activate | Mac/Linux: source .venv/bin/activate)

pip install -r requirements.txt

# Start the server (runs on port 8000)
uvicorn main:app --reload --port 8000
```
*Note: The first time the backend starts, it will automatically download the `tiny.en` Whisper model and `all-MiniLM-L6-v2` embedding model (~200MB total).*

### 2. Frontend (Next.js)
The frontend is a modern Next.js 15 application utilizing React 19.

```bash
# Install dependencies
npm install

# Start the development server (runs on port 3000)
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🎤 Voice Integration Architecture
The application features a deeply integrated, privacy-focused voice pipeline:
- **Streaming WebSockets**: Audio is streamed in chunks to the backend while you speak to reduce latency.
- **VAD (Voice Activity Detection)**: Automatically filters out silence.
- **INT8 Quantization**: The Whisper model runs completely in RAM via CTranslate2, using INT8 precision to maximize CPU speed.
- **Rate Limiting & Tracing**: Voice endpoints are protected by `slowapi` and tracked via UUID headers for observability.
- **Custom SQL Grammar Fixes**: Common phonetic mistakes by Whisper (e.g., "group bye") are mapped to proper SQL terms before being sent to the LLM.

## 🛠 Tech Stack
- **Frontend**: Next.js (App Router), React, Recharts (lazy-loaded), jsPDF (lazy-loaded).
- **Backend**: FastAPI, SQLAlchemy, faster-whisper, sentence-transformers, slowapi, prometheus-client.
- **Databases**: Microsoft SQL Server (via pyodbc).
