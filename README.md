# 🧠 SQL Data Analysis Agent

An intelligent, AI-powered SQL analytics platform built with **Next.js 15** and **FastAPI**. It empowers users to seamlessly chat with their SQL Server databases, generate dynamic interactive reports, upload and compare diverse file types (Data, Documents, Images), and perform hands-free natural-language queries using a fully local **Whisper** model.

![Dashboard Preview](https://via.placeholder.com/1000x500?text=SQL+Data+Analysis+Dashboard)

## ✨ Key Features

- **🗣️ Voice-to-SQL (Local Whisper)**: Speak your queries naturally. Uses `faster-whisper` running locally for privacy-preserving, lightning-fast transcription with automatic grammar correction, number normalization, and date-range mapping.
- **📊 Universal Data Intake**: Upload `.csv`, `.xlsx`, `.json`, or even unstructured `.pdf`, `.docx`, and images (`.png`, `.jpg`). The agent automatically extracts data, OCRs images, and generates insights.
- **⚡ Semantic Caching**: Complex queries are cached using `sentence-transformers` (all-MiniLM-L6-v2) for instant sub-100ms retrieval of similar questions without re-triggering the LLM.
- **📈 Dynamic Charting**: Query results are automatically graphed into interactive Recharts visualizations (Bar, Line, Pie, Scatter).
- **🗂️ Data Lineage & DB Health**: View active schemas, table metadata, and cached query metrics directly from the UI.
- **🔀 Multi-File Comparison**: Upload up to 50 files and have the AI compare them side-by-side or join their insights dynamically.

---

## 🏗 Setup & Installation

### 1. Backend (FastAPI + Python)
The backend manages the database connections, universal file extraction, LLM prompt generation, and the local Whisper ML model.

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
- **INT8 Quantization**: The Whisper model runs completely in RAM via CTranslate2, using INT8 precision to maximize CPU speed on machines without GPUs.
- **Custom SQL Grammar Fixes**: Common phonetic mistakes by Whisper (e.g., "group bye") are mapped to proper SQL terms before being sent to the LLM.

---

## 🚀 Usage Guide

1. **Connect to your Database**: Use the top-left settings gear to connect to your SQL Server (Windows Authentication is supported).
2. **Type or Speak**: Ask a question like *"Show me the top 5 highest grossing products"* using the microphone or keyboard.
3. **Analyze Files**: Drag and drop a CSV or an Image. The AI will ingest it dynamically. Type a prompt referencing the file, or use the multi-file compare feature.
4. **View Cache**: As you query, the Semantic Cache will build up. Ask similar questions to see responses return in milliseconds!

## 🛠 Tech Stack
- **Frontend**: Next.js (App Router), React 19, Recharts (lazy-loaded).
- **Backend**: FastAPI, SQLAlchemy, Pandas, faster-whisper, sentence-transformers, slowapi.
- **Databases**: Microsoft SQL Server (via pyodbc).

## 🔒 Security & Privacy
This platform is designed for enterprise data security:
- **No Data Leakage**: All ML models (Whisper, Embeddings) run **100% locally**. 
- **Database Safety**: SQL Server connections use Trusted Connection (Windows Auth) by default, and raw data is never exposed.
- **Universal Intake Validation**: Uploaded files are rigorously validated, hashed, and categorized before parsing.
