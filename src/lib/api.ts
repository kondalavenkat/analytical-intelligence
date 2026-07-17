// src/lib/api.ts

const BASE = "/api";
// WebSocket connects directly to the FastAPI server (Next.js rewrites don't proxy WS upgrades).
// Reads NEXT_PUBLIC_WS_BACKEND_URL or defaults to ws://localhost:8000.
const WS_BASE = typeof window !== "undefined"
  ? (process.env.NEXT_PUBLIC_WS_BACKEND_URL ?? "ws://localhost:8000")
  : "ws://localhost:8000";

/** Small helper: wait until a WebSocket is in OPEN state (or give up after timeout). */
function waitForWsOpen(ws: WebSocket, timeoutMs = 3000): Promise<void> {
  return new Promise((resolve, reject) => {
    if (ws.readyState === WebSocket.OPEN) { resolve(); return; }
    const timer = setTimeout(() => reject(new Error("WS open timeout")), timeoutMs);
    ws.onopen = () => { clearTimeout(timer); resolve(); };
    ws.onerror = (err) => { clearTimeout(timer); reject(err); };
  });
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("sql_analyst_token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface User {
  email:        string;
  role:         "Admin" | "Analyst" | "Viewer";
  display_name: string;
  token:        string;
  user_id:      number;
}

export interface Column { name: string; type: string; nullable: boolean; }
export interface Table  { schema: string; name: string; full_name: string; row_count: number; columns: Column[]; }

export interface QueryResult {
  question:     string;
  asked_at:     string;
  completed_at: string;
  sql_query:    string;
  source:       "cache" | "model";
  timing:       Record<string, number | string>;
  analysis:     string | null;
  columns:      string[];
  rows:         unknown[][];
  row_count:    number;
}

export interface CacheEntry {
  id:             number;
  user_question:  string;
  provider:       string;
  model:          string;
  hit_count:      number;
  first_exec_ms:  number;
  cached_exec_ms: number;
  created_at:     string;
  last_accessed:  string;
}

export interface DBStats {
  table_count:    number;
  total_rows:     number;
  cached_queries: number;
  total_hits:     number;
  database:       string;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string): Promise<User> {
  const data = await request<User>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  localStorage.setItem("sql_analyst_token", data.token);
  localStorage.setItem("sql_analyst_user",  JSON.stringify(data));
  return data;
}

export function logout() {
  localStorage.removeItem("sql_analyst_token");
  localStorage.removeItem("sql_analyst_user");
}

export function getCurrentUser(): User | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("sql_analyst_user");
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

// ── DB ────────────────────────────────────────────────────────────────────────

export interface ConnectParams {
  server:       string;
  database:     string;
  username?:    string;
  password?:    string;
  windows_auth: boolean;
}

export async function connectDB(params: ConnectParams) {
  return request<{ status: string; database: string }>("/db/connect", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ── Schema ────────────────────────────────────────────────────────────────────

export async function fetchSchema(): Promise<{ tables: Table[]; database: string }> {
  return request("/schema");
}

// ── Query ─────────────────────────────────────────────────────────────────────

export interface QueryParams {
  question:              string;
  provider:              string;
  model:                 string;
  api_key?:              string;
  base_url?:             string;
  similarity_threshold?: number;
  session_id?:           number;
}

export async function runQuery(params: QueryParams): Promise<QueryResult> {
  return request("/query", { method: "POST", body: JSON.stringify(params) });
}

// ── Cache ─────────────────────────────────────────────────────────────────────

export async function fetchCache(): Promise<{ entries: CacheEntry[] }> {
  return request("/cache");
}

export async function deleteCacheEntry(id: number) {
  return request(`/cache/${id}`, { method: "DELETE" });
}

export async function flushCache() {
  return request("/cache", { method: "DELETE" });
}

// ── Stats ─────────────────────────────────────────────────────────────────────

export async function fetchStats(): Promise<DBStats> {
  return request("/stats");
}

// ── Ollama ────────────────────────────────────────────────────────────────────

export interface OllamaModel {
  name:        string;
  size_gb:     number;
  modified_at: string;
  family:      string;
}

export async function fetchOllamaModels(): Promise<{ status: string; models: OllamaModel[]; count: number }> {
  return request("/ollama/models");
}

// ── Chat Sessions ─────────────────────────────────────────────────────────────

export interface ChatSession {
  id:            number;
  title:         string;
  created_at:    string;
  updated_at:    string;
  message_count: number;
}

export interface ChatMessage {
  id:         number;
  question:   string;
  sql_query:  string;
  analysis:   string;
  row_count:  number;
  columns:    string[];
  source:     string;
  provider:   string;
  model:      string;
  exec_ms:    number;
  error:      string;
  created_at: string;
}

export async function createSession(): Promise<{ session_id: number }> {
  return request("/sessions", { method: "POST" });
}

export async function listSessions(): Promise<{ sessions: ChatSession[] }> {
  return request("/sessions");
}

export async function getSessionMessages(sessionId: number): Promise<{ messages: ChatMessage[]; session_id: number }> {
  return request(`/sessions/${sessionId}/messages`);
}

export async function deleteSessionById(sessionId: number): Promise<void> {
  return request(`/sessions/${sessionId}`, { method: "DELETE" });
}

export async function deleteSession(sessionId: number): Promise<void> {
  return request(`/sessions/${sessionId}`, { method: "DELETE" });
}

export async function renameSession(sessionId: number, title: string): Promise<{status: string, session_id: number}> {
  return request(`/sessions/${sessionId}`, { method: "PUT", body: JSON.stringify({ title }) });
}

// ── File Upload ───────────────────────────────────────────────────────────────

export interface UploadedFile {
  id:          number;
  file_name:   string;
  file_size:   number;
  file_type:   string;
  category:    "structured" | "document" | "image_ocr" | "unknown"; // NEW
  row_count:   number;
  col_count:   number;
  columns:     string[];
  uploaded_at: string;
  last_used:   string | null;
  sheet_name:  string | null;
}

export interface SheetInfo {
  file_id:    number | null;
  sheet_name: string;
  row_count:  number;
  col_count:  number;
  columns:    string[];
  preview:    string[][];
}

export interface FileUploadResult {
  file_id:        number;
  file_name:      string;
  file_size:      number;
  file_type:      string;
  category:       "structured" | "document" | "image_ocr" | "unknown"; // NEW
  row_count:      number;
  col_count:      number;
  columns:        string[];
  preview:        string[][];
  cached:         boolean;
  message:        string;
  is_multi_sheet: boolean;
  sheet_names:    string[] | null;
  sheets:         SheetInfo[] | null;
  // Universal intake governance fields
  business_type:  string | null;
  confidence:     number | null;
  flagged:        boolean;
  flag_reason:    string | null;
  policy_action:  string | null;
  ocr_used:       boolean;
  sql_table:      string | null;
}

// ── Voice ─────────────────────────────────────────────────────────────────────

export interface VoiceLogData {
  raw_text: string;
  clean_text: string;
  latency_ms: number;
  language?: string;
  lang_prob?: number;
}

export async function logVoiceTranscript(data: VoiceLogData): Promise<void> {
  return request("/voice/log", { method: "POST", body: JSON.stringify(data) });
}

export interface FileAnalysisResult {
  analysis:           string;
  cached:             boolean;
  hit_count?:         number;
  file_name:          string;
  row_count:          number;
  col_count:          number;
  file_category:      "structured" | "document" | "image_ocr" | "unknown"; // NEW — drives render mode
  chart_data?:        { columns: string[]; rows: (string | number)[][] };
  execution_time_ms?: number;
  cache_ms?:          number;
}

export async function uploadFile(
  file: File,
  onProgress?: (stage: string, details: string) => void
): Promise<FileUploadResult> {
  const token = getToken();
  const form  = new FormData();
  form.append("file", file);

  let ws: WebSocket | null = null;
  let uploadId = "";
  if (onProgress) {
    uploadId = crypto.randomUUID();
    ws = new WebSocket(`${WS_BASE}/files/ws/progress/${uploadId}`);
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.stage && data.details) onProgress(data.stage, data.details);
      } catch {}
    };
    // Wait for WS connection to open before starting upload so no progress events are missed.
    try { await waitForWsOpen(ws); } catch { /* continue even if WS fails — non-fatal */ }
  }

  try {
    const res = await fetch(`${BASE}/files/upload${uploadId ? `?upload_id=${uploadId}` : ""}`, {
      method:  "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body:    form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail ?? "Upload failed");
    }
    return res.json();
  } finally {
    if (ws) ws.close();
  }
}

export async function listFiles(): Promise<{ files: UploadedFile[]; count: number; limit: number }> {
  return request("/files");
}

// IMPORTANT: /files/analyse — British spelling — matches @app.post("/files/analyse") in main.py
export async function analyzeFile(params: {
  file_id:   number;
  prompt:    string;
  provider:  string;
  model:     string;
  api_key?:  string;
  base_url?: string;
  session_id?: string;
}): Promise<FileAnalysisResult> {
  return request("/files/analyse", { method: "POST", body: JSON.stringify(params) });
}

export async function compareFiles(params: {
  file_ids:  number[];
  prompt:    string;
  provider:  string;
  model:     string;
  api_key?:  string;
  base_url?: string;
  session_id?: string;
}): Promise<{
  analysis:          string;
  cached:            boolean;
  file_count:        number;
  hit_count?:        number;
  chart_data?:       { columns: string[]; rows: (string | number)[][] };
  execution_time_ms?: number;
  cache_ms?:         number;
}> {
  return request("/files/compare", { method: "POST", body: JSON.stringify(params) });
}

export async function deleteFile(fileId: number): Promise<void> {
  return request(`/files/${fileId}`, { method: "DELETE" });
}

// ── Clipboard Upload ──────────────────────────────────────────────────────────

export async function uploadClipboardImage(
  base64Data: string,
  filename: string = "clipboard.png",
  onProgress?: (stage: string, details: string) => void
): Promise<FileUploadResult> {
  const token = getToken();
  let ws: WebSocket | null = null;
  let uploadId = "";

  if (onProgress) {
    uploadId = crypto.randomUUID();
    ws = new WebSocket(`${WS_BASE}/files/ws/progress/${uploadId}`);
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.stage && data.details) onProgress(data.stage, data.details);
      } catch {}
    };
    // Wait for WS connection to open before starting upload so no progress events are missed.
    try { await waitForWsOpen(ws); } catch { /* continue even if WS fails — non-fatal */ }
  }

  const payload = {
    image_data: base64Data,
    filename: filename,
    upload_id: uploadId || undefined
  };

  try {
    const res = await fetch(`${BASE}/files/upload-clipboard`, {
      method:  "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail ?? "Clipboard upload failed");
    }
    return res.json();
  } finally {
    if (ws) ws.close();
  }
}

// ── Metadata Repository ───────────────────────────────────────────────────────

export interface MetadataTable {
  id:            number;
  file_name:     string;
  business_type: string | null;
  table_name:    string;
  columns:       string[];
  row_count:     number | null;
  col_count:     number | null;
  confidence:    number | null;
  flagged:       boolean;
  uploaded_at:   string;
  file_id:       number | null;
}

export async function fetchMetadataTables(): Promise<{ tables: MetadataTable[]; count: number }> {
  return request("/metadata/tables");
}