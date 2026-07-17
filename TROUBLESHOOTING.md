# Troubleshooting Guide

This guide covers common issues and their solutions when running the SQL Data Analysis Agent, specifically related to the voice and ML integrations.

---

## 🎙️ Voice & Microphone Issues

### 1. "Microphone permission denied or unavailable"
**Symptom**: Clicking the microphone button shows an alert and doesn't turn red.
**Cause**: The browser is blocking microphone access, or no microphone is connected.
**Fix**:
- Ensure you are accessing the frontend via `http://localhost:3000` or a secure `https://` connection (browsers block microphone access on non-secure connections).
- Click the lock icon 🔒 in your browser's address bar and ensure "Microphone" is set to "Allow".
- Check your OS settings to ensure the browser has permission to access the microphone.

### 2. "Failed to connect to voice stream" (WebSocket Error)
**Symptom**: The UI alerts immediately after clicking record.
**Cause**: The WebSocket connection to the FastAPI backend failed.
**Fix**:
- Ensure the FastAPI backend is running on `http://localhost:8000`.
- Check the terminal where `uvicorn` is running for any traceback errors during the WebSocket handshake.
- Ensure the auth token is valid. Try logging out and logging back in.

---

## 🤖 Backend & ML Model Issues

### 1. `faster-whisper` fails to load or crashes on startup
**Symptom**: The FastAPI backend crashes immediately with a CTranslate2 error.
**Cause**: Missing system dependencies or incompatible Python version.
**Fix**:
- Ensure you are using a 64-bit version of Python (3.9 - 3.12).
- If on Windows, ensure the Visual C++ Redistributable is installed.
- Try re-installing the ML libraries: `pip install --force-reinstall faster-whisper ctranslate2`.

### 2. Rate Limit Exceeded (HTTP 429)
**Symptom**: Voice transcription fails, and the network tab shows a `429 Too Many Requests` error.
**Cause**: You have exceeded the hardcoded limit of `10 voice requests per minute`.
**Fix**:
- Wait 60 seconds before trying again.
- If you are an administrator testing the system, you can increase the `@limiter.limit("10/minute")` decorator limit in `backend/main.py`.

### 3. High Latency (>2 seconds) for Voice Transcriptions
**Symptom**: The "Transcribing..." spinner takes a long time.
**Cause**: The CPU is struggling to run the Whisper model in real-time.
**Fix**:
- Ensure `compute_type="int8"` is preserved in `backend/voice.py`.
- Close other CPU-intensive applications.

---

## 📊 Database Connectivity Issues

### 1. "Auth DB not connected"
**Symptom**: The backend prints `❌ Auth DB failed` on startup.
**Cause**: SQL Server is unreachable using the credentials in `backend/main.py`.
**Fix**:
- Verify that `AUTH_DB_SERVER`, `AUTH_DB_NAME`, `AUTH_DB_USER`, and `AUTH_DB_PASSWORD` are correct in `main.py` or `.env`.
- Ensure SQL Server is running and allows SQL Server Authentication (not just Windows Authentication).
- Ensure TCP/IP is enabled in SQL Server Configuration Manager.
