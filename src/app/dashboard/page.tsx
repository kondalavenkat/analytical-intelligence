"use client";
import React, { useState, useRef, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/useAuth";
import {
  runQuery,
  fetchStats,
  deleteCacheEntry,
  flushCache,
  logout,
  type QueryResult,
  type CacheEntry,
  type DBStats,
  type Table,
  type SheetInfo,
} from "@/lib/api";
import { useRouter } from "next/navigation";

// ── Split components (each in its own file → code-split by Next.js) ──────────
import { MessageBubble } from "@/components/chat/MessageBubble";
import { SheetPickerModal } from "@/components/modals/SheetPickerModal";
import { FileUploadPanel } from "@/components/files/FileUploadPanel";
import { FilePanel } from "@/components/files/FilePanel";
import { DataLineagePanel } from "@/components/files/DataLineagePanel";
import { parseQueryError } from "@/components/chat/ErrorCard";

// ── Types ─────────────────────────────────────────────────────────────────────
interface Session {
  id: string;
  dbId?: number;
  title: string;
  createdAt: string;
  messages: Message[];
}
interface Message {
  id:        string;
  role:      "user" | "assistant";
  content:   string;
  result?:   QueryResult;
  loading?:  boolean;
  errorInfo?: import("@/lib/types").MessageErrorInfo;
}
interface AttachedFile {
  id: number;
  name: string;
  type: string;
  category: "structured" | "document" | "image_ocr" | "unknown"; // drives render mode
  rowCount: number;
  colCount: number;
  columns: string[];
  sheetName: string | null;
  imagePreviewUrl?: string;  // for image files only
}
interface SheetPickerData {
  fileName: string;
  sheets: SheetInfo[];
}
type SheetPickerQueue = SheetPickerData[];

// ── Helpers ───────────────────────────────────────────────────────────────────
function uid() { return Math.random().toString(36).slice(2); }
function fmtDate(iso: string) {
  const d = new Date(iso), today = new Date();
  if (d.toDateString() === today.toDateString()) return "Today";
  const yest = new Date(today); yest.setDate(today.getDate() - 1);
  if (d.toDateString() === yest.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}
function truncate(s: string, n = 40) { return s.length > n ? s.slice(0, n) + "…" : s; }

const QUICK_PROMPTS = [
  { icon: "📊", label: "Data patterns",  q: "Show me patterns in the data with counts and categories" },
  { icon: "👥", label: "Top customers",  q: "Analyze customer demographics and top customers by value" },
  { icon: "💰", label: "Revenue trends", q: "Show revenue by category and time periods with trends" },
  { icon: "📈", label: "Sales insights", q: "Analyze sales trends and key performance metrics" },
  { icon: "🗂️", label: "Table summary",  q: "Give me a summary of all tables and their row counts" },
  { icon: "🔍", label: "Latest data",    q: "Show me the most recently added or modified records" },
];

const MAX_ATTACHED    = 50;
const FILE_SIZE_LIMIT = 50 * 1024 * 1024;

// ── Dashboard ─────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const enableVoice = process.env.NEXT_PUBLIC_ENABLE_VOICE !== "false";
  const { user, loading } = useAuth();
  const router = useRouter();

  // ── AI provider ──────────────────────────────────────────────────────────
  const [provider, setProvider]             = useState("OpenAI");
  const [model, setModel]                   = useState("gpt-4o-mini");
  const [apiKey, setApiKey]                 = useState("");
  const [simThreshold, setSimThreshold]     = useState(0.85);
  const [ollamaModels, setOllamaModels]     = useState<import("@/lib/api").OllamaModel[]>([]);
  const [ollamaFetching, setOllamaFetching] = useState(false);
  const [ollamaError, setOllamaError]       = useState("");


  // ── DB connection ─────────────────────────────────────────────────────────
  const [connected, setConnected]   = useState(false);
  const [database, setDatabase]     = useState("");
  const [server, setServer]         = useState("");
  const [dbName, setDbName]         = useState("");
  const [username, setUsername]     = useState("");
  const [password, setPassword]     = useState("");
  const [winAuth, setWinAuth]       = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [connError, setConnError]   = useState("");
  const [stats, setStats]           = useState<DBStats | null>(null);
  const [tables, setTables]         = useState<Table[]>([]);

  // ── Chat ──────────────────────────────────────────────────────────────────
  const [sessions, setSessions]                   = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId]     = useState<string | null>(null);
  const [historyLoaded, setHistoryLoaded]         = useState(false);
  const [input, setInput]                         = useState("");
  const [sending, setSending]                     = useState(false);

  // ── Voice ─────────────────────────────────────────────────────────────────
  const [isRecording, setIsRecording]       = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [voiceError, setVoiceError]         = useState("");
  const [interimText, setInterimText]       = useState(""); // live preview while speaking
  const recognitionRef                      = useRef<SpeechRecognition | null>(null);
  const finalTranscriptRef                  = useRef<string>("");  // accumulates confirmed words
  const voiceStartTimeRef                   = useRef<number>(0);

  // ── File attachments ──────────────────────────────────────────────────────
  const [attachedFiles, setAttachedFiles]       = useState<AttachedFile[]>([]);
  const [uploadingFile, setUploadingFile]       = useState(false);
  const [uploadingLabel, setUploadingLabel]     = useState("");  // shows filename while uploading
  const [sheetPickerOpen, setSheetPickerOpen]   = useState(false);
  const [sheetPickerQueue, setSheetPickerQueue] = useState<SheetPickerQueue>([]);
  const [sheetPickerTotal, setSheetPickerTotal] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── UI panels ─────────────────────────────────────────────────────────────
  const [chatSearchText, setChatSearchText] = useState("");
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renameText, setRenameText] = useState("");
  const [language, setLanguage] = useState("en-US");
  const [sidebarOpen, setSidebarOpen]   = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cachePanel, setCachePanel]     = useState(false);
  const [cacheEntries, setCacheEntries] = useState<CacheEntry[]>([]);
  const [filesPanel, setFilesPanel]     = useState(false);
  const [filePanelOpen, setFilePanelOpen] = useState(false);
  const [lineagePanel, setLineagePanel]   = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef   = useRef<HTMLTextAreaElement>(null);
  const activeSession = sessions.find(s => s.id === activeSessionId) ?? null;

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [activeSession?.messages]);

  // ── Keyboard shortcut: Ctrl+Shift+M → toggle voice recording ─────────────
  useEffect(() => {
    if (!enableVoice) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.code === "KeyM") {
        e.preventDefault();
        if (isRecording) stopRecording();
        else if (connected && !isTranscribing) startRecording();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isRecording, isTranscribing, connected, enableVoice]);

  // ── Ctrl+V paste → attach image directly into chat input ─────────────────
  useEffect(() => {
    const handlePaste = async (e: ClipboardEvent) => {
      if (!connected) return;
      
      // FIX: If the clipboard contains plain text, let it paste normally.
      // (Rich text from Word/Excel often bundles an image with the text, which used to block pasting)
      if (e.clipboardData?.getData("text/plain")?.trim()) {
        return;
      }
      
      const item = Array.from(e.clipboardData?.items ?? []).find(i => i.type.startsWith("image/"));
      if (!item) return;
      e.preventDefault();
      const blob = item.getAsFile();
      if (!blob) return;
      // Create a local preview URL immediately so the user sees it right away
      const previewUrl = URL.createObjectURL(blob);
      const tempId = Date.now();
      // Show a pending image preview pill
      setAttachedFiles(prev => [...prev, {
        id: tempId,
        name: `clipboard_${new Date().toLocaleTimeString()}.png`,
        type: "png",
        category: "image_ocr",
        rowCount: 0, colCount: 0, columns: [], sheetName: null,
        imagePreviewUrl: previewUrl,
      }]);
      setUploadingFile(true);
      setUploadingLabel("clipboard image");
      try {
        const { uploadClipboardImage } = await import("@/lib/api");
        const buf = await blob.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let binary = "";
        bytes.forEach(b => (binary += String.fromCharCode(b)));
        const b64 = btoa(binary);
        const res = await uploadClipboardImage(b64, `clipboard_${Date.now()}.png`);
        // Replace the temp preview entry with the real uploaded file
        setAttachedFiles(prev => prev.map(f =>
          f.id === tempId
            ? {
                id: res.file_id,
                name: res.file_name,
                type: res.file_type,
                category: res.category ?? "image_ocr",  // from upload response
                rowCount: res.row_count,
                colCount: res.col_count,
                columns: res.columns,
                sheetName: null,
                imagePreviewUrl: previewUrl,
              }
            : f
        ));
        // Focus the textarea so user can type their question right away
        inputRef.current?.focus();
      } catch {
        setAttachedFiles(prev => prev.filter(f => f.id !== tempId));
        URL.revokeObjectURL(previewUrl);
      } finally {
        setUploadingFile(false);
        setUploadingLabel("");
      }
    };
    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, [connected]);

  // ── Auto-reconnect ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!user?.email || connected) return;
    const saved = localStorage.getItem("sql_analyst_conn");
    if (!saved) return;
    try {
      const conn = JSON.parse(saved);
      if (!conn.server || !conn.database) return;
      import("@/lib/api").then(({ connectDB }) => {
        connectDB(conn).then(res => {
          setServer(conn.server); setDbName(conn.database);
          setUsername(conn.username || ""); setPassword(conn.password || "");
          setWinAuth(conn.windows_auth);
          setConnected(true); setDatabase(res.database); setHistoryLoaded(false);
        }).catch(() => localStorage.removeItem("sql_analyst_conn"));
      });
    } catch { /* ignore */ }
  }, [user?.email, connected]);

  // ── Load chat history ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!connected || historyLoaded) return;
    setHistoryLoaded(true);
    import("@/lib/api").then(({ listSessions }) => {
      listSessions().then(({ sessions: db }) => {
        if (!db.length) return;
        setSessions(db.slice(0, 50).map(s => ({
          id: String(s.id), dbId: s.id, title: s.title,
          createdAt: s.created_at, messages: [],
        })));
      }).catch(() => {});
    });
  }, [connected, historyLoaded]);

  // ── Load stats + schema ───────────────────────────────────────────────────
  useEffect(() => {
    if (!connected) return;
    fetchStats().then(setStats).catch(() => {});
    import("@/lib/api").then(({ fetchSchema }) => {
      fetchSchema().then(r => setTables(r.tables)).catch(() => {});
    });
  }, [connected]);

  // ── Ollama model detection ────────────────────────────────────────────────
  useEffect(() => {
    if (provider !== "Ollama") return;
    setOllamaFetching(true); setOllamaError("");
    import("@/lib/api").then(({ fetchOllamaModels }) =>
      fetchOllamaModels()
        .then(res => {
          setOllamaModels(res.models);
          if (res.models.length) setModel(res.models[0].name);
          else setOllamaError("No models found. Run: ollama pull llama3");
        })
        .catch(e => setOllamaError(e instanceof Error ? e.message : "Cannot reach Ollama"))
        .finally(() => setOllamaFetching(false))
    );
  }, [provider]);

  // ── SQL + Fintech grammar fix (client-side, instant) ─────────────────────
  function applyGrammarFixes(text: string): string {
    const fixes: [RegExp, string][] = [
      // SQL aggregations
      [/\bsum of\b/gi,          "SUM"],
      [/\bcount of\b/gi,        "COUNT"],
      [/\bcount star\b/gi,      "COUNT(*)"],
      [/\baverage of\b/gi,      "AVG"],
      [/\bmaximum of\b/gi,      "MAX"],
      [/\bminimum of\b/gi,      "MIN"],
      [/\bgroup bye\b/gi,       "GROUP BY"],
      [/\bgroup by\b/gi,        "GROUP BY"],
      [/\border bye\b/gi,       "ORDER BY"],
      [/\border by\b/gi,        "ORDER BY"],
      [/\bhaving clause\b/gi,   "HAVING"],
      [/\bwhere clause\b/gi,    "WHERE"],
      [/\binner join\b/gi,      "INNER JOIN"],
      [/\bleft join\b/gi,       "LEFT JOIN"],
      [/\bright join\b/gi,      "RIGHT JOIN"],
      [/\bdistinct\b/gi,        "DISTINCT"],
      // Comparisons
      [/\bgreater than or equal\b/gi, ">="],
      [/\bless than or equal\b/gi,    "<="],
      [/\bgreater than\b/gi,          ">"],
      [/\bless than\b/gi,             "<"],
      [/\bnot equal\b/gi,             "!="],
      [/\bis null\b/gi,               "IS NULL"],
      [/\bis not null\b/gi,           "IS NOT NULL"],
      // Number words → digits (Indian + Western)
      [/\bone crore\b/gi,             "10000000"],
      [/\bten lakh[s]?\b/gi,          "1000000"],
      [/\bone lakh\b/gi,              "100000"],
      [/\bfifty thousand\b/gi,        "50000"],
      [/\btwenty.?five thousand\b/gi, "25000"],
      [/\bten thousand\b/gi,          "10000"],
      [/\bfive thousand\b/gi,         "5000"],
      [/\bone thousand\b/gi,          "1000"],
      [/\bone hundred\b/gi,           "100"],
      [/\bninety\b/gi,                "90"],
      [/\beighty\b/gi,                "80"],
      [/\bseventy\b/gi,               "70"],
      [/\bsixty\b/gi,                 "60"],
      [/\bfifty\b/gi,                 "50"],
      [/\bforty\b/gi,                 "40"],
      [/\bthirty\b/gi,                "30"],
      [/\btwenty\b/gi,                "20"],
      [/\bfifteen\b/gi,               "15"],
      [/\bten\b/gi,                   "10"],
      [/\bfive\b/gi,                  "5"],
      // Fintech / domain terms
      [/\btrans action\b/gi,    "transaction"],
      [/\bcustomer i d\b/gi,    "customer_id"],
      [/\bproduct i d\b/gi,     "product_id"],
      [/\border i d\b/gi,       "order_id"],
      [/\buser i d\b/gi,        "user_id"],
      [/\btime stamp\b/gi,      "timestamp"],
      [/\bprofit margin\b/gi,   "profit_margin"],
      [/\bsales amount\b/gi,    "sales_amount"],
      [/\bcredit score\b/gi,    "credit_score"],
      // Cleanup
      [/\s{2,}/g, " "],
    ];
    let result = text;
    for (const [pattern, replacement] of fixes) {
      result = result.replace(pattern, replacement);
    }
    return result.trim();
  }

  // ── Voice recording — Web Speech API (live text as you speak) ────────────
  const startRecording = () => {
    setVoiceError("");
    setInterimText("");
    finalTranscriptRef.current = "";

    // @ts-ignore — webkit prefix for older Chrome
    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) {
      setVoiceError("Live voice not supported in this browser. Use Chrome or Edge.");
      return;
    }

    const recognition: SpeechRecognition = new SpeechRecognitionAPI();
    recognition.continuous      = true;   // keep listening until user stops
    recognition.interimResults  = true;   // fire onresult for every word
    recognition.lang            = language;
    recognition.maxAlternatives = 1;
    recognitionRef.current = recognition;

    recognition.onstart = () => {
      setIsRecording(true);
      voiceStartTimeRef.current = Date.now();
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          // Confirmed word(s) — apply grammar fixes immediately
          finalTranscriptRef.current += applyGrammarFixes(transcript) + " ";
        } else {
          // Still being spoken — show as-is
          interim = transcript;
        }
      }
      setInterimText(interim);
      // Paste live into input box: confirmed words + what's being spoken now
      setInput((finalTranscriptRef.current + interim).trimStart());
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === "no-speech") return; // ignore silence
      setVoiceError(`Voice error: ${event.error}. Check microphone permissions.`);
      setIsRecording(false);
      setInterimText("");
    };

    recognition.onend = () => {
      setIsRecording(false);
      setInterimText("");
      const finalText = applyGrammarFixes(finalTranscriptRef.current);
      if (finalText) {
        setInput(finalText);
        import("@/lib/api").then(({ logVoiceTranscript }) => {
          logVoiceTranscript({
            raw_text: finalTranscriptRef.current.trim(),
            clean_text: finalText,
            latency_ms: Date.now() - voiceStartTimeRef.current,
            language: language,
            lang_prob: 1.0,
          }).catch(() => {});
        });
      }
    };

    recognition.start();
  };

  const stopRecording = () => {
    recognitionRef.current?.stop();
  };


  // ── New session ───────────────────────────────────────────────────────────
  async function newSession() {
    try {
      const { createSession } = await import("@/lib/api");
      const { session_id } = await createSession();
      const s: Session = { id: String(session_id), dbId: session_id, title: "New chat", createdAt: new Date().toISOString(), messages: [] };
      setSessions(prev => [s, ...prev]); setActiveSessionId(s.id); setInput("");
    } catch {
      const s: Session = { id: uid(), title: "New chat", createdAt: new Date().toISOString(), messages: [] };
      setSessions(prev => [s, ...prev]); setActiveSessionId(s.id); setInput("");
    }
  }

  // ── Send SQL query ────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (text: string, cutoffMsgId?: string) => {
    const q = text.trim();
    if (!q || sending) return;
    if (!connected) { alert("Connect to a database first."); return; }
    if (!apiKey && provider !== "Ollama") { alert("Enter an API key first."); return; }

    let sid = activeSessionId;
    let dbSessionId: number | undefined;

    if (!sid) {
      try {
        const { createSession } = await import("@/lib/api");
        const { session_id } = await createSession();
        dbSessionId = session_id;
        const s: Session = { id: String(session_id), dbId: session_id, title: truncate(q, 32), createdAt: new Date().toISOString(), messages: [] };
        setSessions(prev => [s, ...prev]); setActiveSessionId(s.id); sid = s.id;
      } catch {
        const s: Session = { id: uid(), title: truncate(q, 32), createdAt: new Date().toISOString(), messages: [] };
        setSessions(prev => [s, ...prev]); setActiveSessionId(s.id); sid = s.id;
      }
    } else {
      dbSessionId = sessions.find(s => s.id === sid)?.dbId;
    }

    const userMsg: Message = { id: uid(), role: "user", content: q };
    const loadMsg: Message = { id: uid(), role: "assistant", content: "", loading: true };
    setSessions(prev => prev.map(s => {
      if (s.id !== sid) return s;
      const msgs = cutoffMsgId ? s.messages.slice(0, s.messages.findIndex(m => m.id === cutoffMsgId)) : s.messages;
      return { ...s, title: msgs.length === 0 ? truncate(q, 32) : s.title, messages: [...msgs, userMsg, loadMsg] };
    }));
    setInput(""); setSending(true);

    try {
      const result = await runQuery({ question: q, provider, model, api_key: provider !== "Ollama" ? apiKey : undefined, similarity_threshold: simThreshold, session_id: dbSessionId });
      const summary = result.row_count === 0
        ? "The query returned no results."
        : result.source === "cache"
          ? `Retrieved from cache in ${Number(result.timing.cache_ms ?? 0).toFixed(0)} ms (${String(result.timing.match_type)} match, ${(Number(result.timing.similarity ?? 1) * 100).toFixed(0)}% similar). Found ${result.row_count.toLocaleString()} records.`
          : `Query executed in ${Number(result.timing.model_ms).toFixed(0)} ms. Found ${result.row_count.toLocaleString()} records across ${result.columns.length} columns.`;
      const assistantMsg: Message = { id: loadMsg.id, role: "assistant", content: summary, result };
      setSessions(prev => prev.map(s => s.id === sid ? { ...s, messages: s.messages.map(m => m.id === loadMsg.id ? assistantMsg : m) } : s));
    } catch (e: unknown) {
      const rawMsg = e instanceof Error ? e.message : "Query failed";
      const errInfo = { ...parseQueryError(rawMsg), question: q };
      const errMsg: Message = {
        id:        loadMsg.id,
        role:      "assistant",
        content:   "I encountered an error running that query.",
        errorInfo: errInfo,
      };
      setSessions(prev => prev.map(s => s.id === sid ? { ...s, messages: s.messages.map(m => m.id === loadMsg.id ? errMsg : m) } : s));
    } finally { setSending(false); }
  }, [activeSessionId, connected, apiKey, provider, model, simThreshold, sending, sessions]);

  // ── File analysis ─────────────────────────────────────────────────────────
  async function handleFileAnalysis(prompt: string) {
    // NOTE: No !connected guard — file analysis uses auth DB, not the user query DB
    if (attachedFiles.length === 0 || !prompt.trim()) return;
    if (!apiKey && provider !== "Ollama") { alert("Enter an API key first."); return; }
    const q = prompt.trim();
    const qLower = q.toLowerCase();

    let targetFiles = attachedFiles;
    if (attachedFiles.length > 1) {
      const compareKeywords = ["compare", "comparison", "vs ", " vs.", "versus", "between", "difference", "differences", "both ", "all files", "each file", "which platform", "which file", "which one", "which has", "higher", "lower", "more than", "less than", "across the files", "across files"];
      const wantsCompare = compareKeywords.some(k => qLower.includes(k));
      if (!wantsCompare) {
        const matched = attachedFiles.filter(f => {
          const [rawFile, rawSheet] = f.name.includes(" · ") ? f.name.split(" · ") : [f.name, null];
          const baseName = rawFile.replace(/\.[^.]+$/, "").toLowerCase();
          const sheetLower = rawSheet?.toLowerCase() ?? "";
          const parts = baseName.split(/[\-_\.\s]+/).filter(p => p.length > 3);
          return qLower.includes(baseName) || parts.some(p => qLower.includes(p)) || (sheetLower && qLower.includes(sheetLower));
        });
        targetFiles = matched.length >= 1 ? matched : attachedFiles;
      }
    }
    const isCompare = targetFiles.length > 1;

    let sid = activeSessionId;
    let dbSessionId: number | undefined;
    if (!sid) {
      try {
        const { createSession } = await import("@/lib/api");
        const { session_id } = await createSession();
        dbSessionId = session_id;
        const s: Session = { id: String(session_id), dbId: session_id, title: truncate(q, 32), createdAt: new Date().toISOString(), messages: [] };
        setSessions(prev => [s, ...prev]); setActiveSessionId(s.id); sid = s.id;
      } catch {
        const s: Session = { id: uid(), title: truncate(q, 32), createdAt: new Date().toISOString(), messages: [] };
        setSessions(prev => [s, ...prev]); setActiveSessionId(s.id); sid = s.id;
      }
    } else {
      dbSessionId = sessions.find(s => s.id === sid)?.dbId;
    }


    const fileLabels = attachedFiles.map(f => `📎 ${f.name}`).join("\n");
    const userMsg: Message = { id: uid(), role: "user", content: `${fileLabels}\n${q}` };
    const loadMsg: Message = { id: uid(), role: "assistant", content: "", loading: true };
    setSessions(prev => prev.map(s => s.id === sid
      ? { ...s, title: s.messages.length === 0 ? truncate(q, 32) : s.title, messages: [...s.messages, userMsg, loadMsg] }
      : s
    ));
    setInput(""); setSending(true);

    try {
      let analysisText = ""; let cached = false; let summaryText = "";
      let chartCols: string[] = []; let chartRows: unknown[][] = [];
      let execMs = 0; let cacheMs = 0;
      const totalRows = targetFiles.reduce((s, f) => s + f.rowCount, 0);

      if (isCompare) {
        const { compareFiles } = await import("@/lib/api");
        const result = await compareFiles({ file_ids: targetFiles.map(f => f.id), prompt: q, provider, model, api_key: provider !== "Ollama" ? apiKey : undefined, base_url: "http://localhost:11434", session_id: dbSessionId });
        analysisText = result.analysis; cached = result.cached;
        execMs = result.execution_time_ms ?? 0; cacheMs = result.cache_ms ?? 0;
        const labels = targetFiles.map(f => f.name).join(", ");
        summaryText = `${cached ? "⚡ Cached · " : ""}Compared ${result.file_count} file${result.file_count !== 1 ? "s" : ""} — ${labels}`;
        chartCols = result.chart_data?.columns ?? []; chartRows = result.chart_data?.rows ?? [];
      } else {
        const { analyzeFile } = await import("@/lib/api");
        const result = await analyzeFile({ file_id: targetFiles[0].id, prompt: q, provider, model, api_key: provider !== "Ollama" ? apiKey : undefined, base_url: "http://localhost:11434", session_id: dbSessionId });
        analysisText = result.analysis; cached = result.cached;
        execMs = result.execution_time_ms ?? 0; cacheMs = result.cache_ms ?? 0;
        chartCols = result.chart_data?.columns ?? []; chartRows = result.chart_data?.rows ?? [];

        // Dynamic summary — depends on what the AI actually returned, not file type
        const hasTable = chartCols.length > 0 && chartRows.length > 0;
        const f0 = targetFiles[0];
        if (hasTable) {
          summaryText = `${cached ? "⚡ Cached · " : ""}Analysed ${f0.name} — found ${chartRows.length.toLocaleString()} row${chartRows.length !== 1 ? "s" : ""}`;
        } else if (f0.category === "structured" && f0.rowCount > 0) {
          summaryText = `${cached ? "⚡ Cached · " : ""}Analysed ${f0.name} (${f0.rowCount.toLocaleString()} rows) — direct answer below`;
        } else {
          // Document / image / text content — no rows to show
          summaryText = `${cached ? "⚡ Cached · " : ""}Analysed ${f0.name}`;
        }
      }

      const assistantMsg: Message = {
        id: loadMsg.id, role: "assistant", content: summaryText,
        result: {
          question: q, sql_query: "", analysis: analysisText,
          // Only pass columns+rows if the AI actually returned chart data.
          // Never fall back to file column headers — that causes empty tables.
          columns: chartCols,
          rows: chartRows,
          row_count: chartRows.length,
          source: cached ? "cache" : "model",
          timing: cached ? { cache_ms: cacheMs, first_exec_ms: execMs, match_type: "exact", similarity: 1.0, model_ms: execMs } : { model_ms: execMs },
          asked_at: new Date().toISOString(), completed_at: new Date().toISOString(),
        }
      };
      setSessions(prev => prev.map(s => s.id === sid ? { ...s, messages: s.messages.map(m => m.id === loadMsg.id ? assistantMsg : m) } : s));
    } catch (e: unknown) {
      const rawMsg = e instanceof Error ? e.message : "Analysis failed";
      const { parseQueryError } = await import("@/components/chat/ErrorCard");
      const errInfo = { ...parseQueryError(rawMsg), question: q };
      const errMsg: Message = { id: loadMsg.id, role: "assistant", content: "I encountered an error analysing that file.", errorInfo: errInfo };
      setSessions(prev => prev.map(s => s.id === sid ? { ...s, messages: s.messages.map(m => m.id === loadMsg.id ? errMsg : m) } : s));
    } finally { setSending(false); }
  }

  async function handleConnect() {
    if (!server || !dbName) { setConnError("Server and database required."); return; }
    setConnecting(true); setConnError("");
    try {
      const { connectDB } = await import("@/lib/api");
      const res = await connectDB({ server, database: dbName, username: winAuth ? undefined : username, password: winAuth ? undefined : password, windows_auth: winAuth });
      setConnected(true); setDatabase(res.database); setSettingsOpen(false); setHistoryLoaded(false);
      localStorage.setItem("sql_analyst_conn", JSON.stringify({ server, database: dbName, username: winAuth ? "" : username, password: winAuth ? "" : password, windows_auth: winAuth }));
    } catch (e: unknown) { setConnError(e instanceof Error ? e.message : "Connection failed"); }
    finally { setConnecting(false); }
  }

  function handleLogout() { logout(); router.push("/login"); }

  if (loading) return <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "#888780", fontSize: 14 }}>Loading…</div>;
  if (!user) return null;

  const roleBg:    Record<string, string> = { Admin: "#E6F1FB", Analyst: "#EAF3DE", Viewer: "#FAEEDA" };
  const roleColor: Record<string, string> = { Admin: "#0C447C", Analyst: "#27500A", Viewer: "#633806" };
  const filteredSessions = chatSearchText 
    ? sessions.filter(s => s.title.toLowerCase().includes(chatSearchText.toLowerCase()))
    : sessions;
  const grouped: Record<string, Session[]> = {};
  filteredSessions.forEach(s => { const k = fmtDate(s.createdAt); grouped[k] = [...(grouped[k] ?? []), s]; });

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "var(--font)", background: "#fafaf9", overflow: "hidden" }}>

      {/* Sheet Picker Modal */}
      {sheetPickerOpen && sheetPickerQueue.length > 0 && (
        <SheetPickerModal
          key={sheetPickerQueue[0].fileName}
          data={sheetPickerQueue[0]}
          queuePosition={sheetPickerTotal > 1 ? { current: sheetPickerTotal - sheetPickerQueue.length + 1, total: sheetPickerTotal } : undefined}
          onSelect={(sheets) => {
            const currentFile = sheetPickerQueue[0];
            setAttachedFiles(prev => {
              const next = [...prev];
              for (const s of sheets) {
                if (next.some(p => p.name === `${currentFile.fileName} · ${s.sheet_name}`)) continue;
                const stableId = (s.file_id != null && s.file_id > 0)
                  ? s.file_id
                  : -(currentFile.fileName + s.sheet_name).split("").reduce((a, c) => a + c.charCodeAt(0), 0);
                next.push({ id: stableId, name: `${currentFile.fileName} · ${s.sheet_name}`, type: "xlsx", rowCount: s.row_count ?? 0, colCount: s.col_count ?? 0, columns: s.columns ?? [], sheetName: s.sheet_name });
              }
              return next.slice(0, MAX_ATTACHED);
            });
            const remaining = sheetPickerQueue.slice(1);
            if (remaining.length > 0) { setSheetPickerQueue(remaining); }
            else { setSheetPickerOpen(false); setSheetPickerQueue([]); setSheetPickerTotal(0); }
          }}
          onClose={() => {
            const remaining = sheetPickerQueue.slice(1);
            if (remaining.length > 0) { setSheetPickerQueue(remaining); }
            else { setSheetPickerOpen(false); setSheetPickerQueue([]); setSheetPickerTotal(0); }
          }}
        />
      )}

      {/* ══════════ SIDEBAR ══════════ */}
      <aside style={{ width: sidebarOpen ? 260 : 0, minWidth: sidebarOpen ? 260 : 0, background: "#111827", display: "flex", flexDirection: "column", transition: "width 0.25s ease,min-width 0.25s ease", overflow: "hidden", flexShrink: 0 }}>
        <div style={{ width: 260, display: "flex", flexDirection: "column", height: "100%" }}>

          {/* Logo + new chat */}
          <div style={{ padding: "18px 16px 14px", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <div style={{ width: 32, height: 32, background: "#185FA5", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#E6F1FB" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" />
                    <circle cx="17.5" cy="17.5" r="3.5" /><line x1="17.5" y1="15.5" x2="17.5" y2="19.5" /><line x1="15.5" y1="17.5" x2="19.5" y2="17.5" />
                  </svg>
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#f0ede8" }}>SQL Analyst</div>
                  <div style={{ fontSize: 10, color: "#8b9cb8", letterSpacing: "0.05em", textTransform: "uppercase" }}>AI-Powered</div>
                </div>
              </div>
              <button onClick={newSession} title="New chat" style={{ width: 28, height: 28, borderRadius: 6, background: "rgba(255,255,255,0.07)", border: "1px solid rgba(255,255,255,0.1)", color: "#8b9cb8", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
              </button>
            </div>
          </div>

          {/* Connection status */}
          <div style={{ padding: "10px 16px" }}>
            {connected ? (
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#97c459", background: "rgba(99,153,34,0.12)", border: "1px solid rgba(99,153,34,0.2)", borderRadius: 6, padding: "5px 10px" }}>
                <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#639922" }} />{database}
                {stats && <span style={{ marginLeft: "auto", color: "#8b9cb8" }}>{stats.table_count} tables</span>}
              </div>
            ) : (
              <button onClick={() => setSettingsOpen(true)} style={{ width: "100%", padding: "6px 10px", fontSize: 11, borderRadius: 6, border: "1px dashed rgba(255,255,255,0.15)", background: "transparent", color: "#8b9cb8", cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>+ Connect to database</button>
            )}
          </div>

          {/* Search Chat */}
          <div style={{ padding: "0 16px 10px" }}>
            <input 
              type="text" 
              placeholder="Search chats..." 
              value={chatSearchText} 
              onChange={e => setChatSearchText(e.target.value)} 
              style={{ width: "100%", padding: "6px 10px", fontSize: 11, borderRadius: 6, border: "1px solid rgba(255,255,255,0.1)", background: "rgba(0,0,0,0.2)", color: "#e3e9f0", fontFamily: "inherit", outline: "none" }} 
            />
          </div>

          {/* Session list */}
          <div style={{ flex: 1, overflowY: "auto", padding: "0 8px" }}>
            {filteredSessions.length === 0 ? (
              <div style={{ padding: "20px 8px", fontSize: 12, color: "#4a6a8a", textAlign: "center", lineHeight: 1.6 }}>No chats yet.<br />Ask a question to start.</div>
            ) : (
              Object.entries(grouped).map(([date, grp]) => (
                <div key={date}>
                  <div style={{ fontSize: 10, color: "#e3e9f0", letterSpacing: "0.06em", textTransform: "uppercase", padding: "10px 8px 4px", fontWeight: 600 }}>{date}</div>
                  {grp.map(s => (
                    <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 2, marginBottom: 2 }}>
                      <button onClick={async () => {
                        setActiveSessionId(s.id);
                        if (s.dbId && s.messages.length === 0) {
                          try {
                            const { getSessionMessages } = await import("@/lib/api");
                            const { messages } = await getSessionMessages(s.dbId);
                            const expanded: Message[] = [];
                            for (const m of messages) {
                              expanded.push({ id: `u-${m.id}`, role: "user", content: m.question });
                              const summary = m.error ? `❌ ${m.error}` : m.source === "cache" ? `Retrieved from cache. Found ${(m.row_count ?? 0).toLocaleString()} records.` : `Query executed in ${(m.exec_ms ?? 0).toFixed(0)} ms. Found ${(m.row_count ?? 0).toLocaleString()} records.`;
                              expanded.push({ id: `a-${m.id}`, role: "assistant", content: summary, result: (m.sql_query || m.analysis || (Array.isArray(m.columns) && m.columns.length > 0)) ? { question: m.question, sql_query: m.sql_query, analysis: m.analysis, columns: Array.isArray(m.columns) ? m.columns : [], rows: [], row_count: m.row_count ?? 0, source: (m.source ?? "model") as "cache" | "model", timing: { model_ms: m.exec_ms ?? 0 }, asked_at: m.created_at, completed_at: m.created_at } : undefined });
                            }
                            setSessions(prev => prev.map(x => x.id === s.id ? { ...x, messages: expanded } : x));
                          } catch { /* ignore */ }
                        }
                      }} style={{ flex: 1, textAlign: "left", padding: "7px 10px", borderRadius: 7, background: s.id === activeSessionId ? "rgba(55,138,221,0.15)" : "transparent", border: s.id === activeSessionId ? "1px solid rgba(55,138,221,0.25)" : "1px solid transparent", color: s.id === activeSessionId ? "#B5D4F4" : "#8b9cb8", fontSize: 12, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" style={{ flexShrink: 0 }}><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /></svg>
                        {renamingSessionId === s.id ? (
                          <input 
                            autoFocus 
                            value={renameText} 
                            onChange={e => setRenameText(e.target.value)}
                            onClick={e => e.stopPropagation()}
                            onKeyDown={async e => {
                              if (e.key === "Enter" && s.dbId) {
                                try {
                                  const { renameSession } = await import("@/lib/api");
                                  await renameSession(s.dbId, renameText);
                                  setSessions(prev => prev.map(x => x.id === s.id ? { ...x, title: renameText } : x));
                                } catch {}
                                setRenamingSessionId(null);
                              } else if (e.key === "Escape") {
                                setRenamingSessionId(null);
                              }
                            }}
                            onBlur={() => setRenamingSessionId(null)}
                            style={{ flex: 1, background: "rgba(0,0,0,0.2)", border: "1px solid rgba(255,255,255,0.2)", color: "#f0ede8", fontSize: 11, outline: "none", fontFamily: "inherit", padding: "2px 4px", borderRadius: 4 }} 
                          />
                        ) : (
                          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</span>
                        )}
                        <span style={{ fontSize: 10, color: "#4a6a8a", flexShrink: 0 }}>{s.messages.filter(m => m.role === "user").length}</span>
                      </button>
                      {renamingSessionId !== s.id && (
                        <button onClick={(e) => { e.stopPropagation(); setRenameText(s.title); setRenamingSessionId(s.id); }} title="Rename chat" style={{ flexShrink: 0, width: 22, height: 22, borderRadius: 5, background: "transparent", border: "none", color: "#4a6a8a", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: s.id === activeSessionId ? 1 : 0 }} onMouseEnter={e => (e.currentTarget.style.opacity = "1")} onMouseLeave={e => (e.currentTarget.style.opacity = s.id === activeSessionId ? "1" : "0")}>
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                        </button>
                      )}
                      <button onClick={async (e) => {
                        e.stopPropagation();
                        if (s.dbId) { try { const { deleteSessionById } = await import("@/lib/api"); await deleteSessionById(s.dbId); } catch { /* ignore */ } }
                        setSessions(prev => prev.filter(x => x.id !== s.id));
                        if (activeSessionId === s.id) setActiveSessionId(null);
                      }} title="Delete chat" style={{ flexShrink: 0, width: 22, height: 22, borderRadius: 5, background: "transparent", border: "none", color: "#4a6a8a", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", opacity: s.id === activeSessionId ? 1 : 0 }}
                        onMouseEnter={e => (e.currentTarget.style.opacity = "1")}
                        onMouseLeave={e => (e.currentTarget.style.opacity = s.id === activeSessionId ? "1" : "0")}>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6M14 11v6" /><path d="M9 6V4h6v2" /></svg>
                      </button>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>

          {/* Sidebar footer */}
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.07)", padding: "12px 16px" }}>
            {stats && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 10 }}>
                {[{ label: "Tables", value: stats.table_count }, { label: "Cached", value: stats.cached_queries }, { label: "Records", value: stats.total_rows > 999 ? `${(stats.total_rows / 1000).toFixed(0)}k` : stats.total_rows }, { label: "Hits", value: stats.total_hits }].map(m => (
                  <div key={m.label} style={{ background: "rgba(255,255,255,0.04)", borderRadius: 6, padding: "6px 8px" }}>
                    <div style={{ fontSize: 10, color: "#8b9cb8", textTransform: "uppercase", letterSpacing: "0.05em" }}>{m.label}</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: "#B5D4F4", fontFamily: "var(--mono)" }}>{m.value}</div>
                  </div>
                ))}
              </div>
            )}
            <button onClick={() => setSettingsOpen(v => !v)} style={{ width: "100%", padding: "8px 10px", borderRadius: 7, marginBottom: 8, background: settingsOpen ? "rgba(55,138,221,0.12)" : "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", color: "#8b9cb8", fontSize: 12, cursor: "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", gap: 8 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" /></svg>
              Settings &amp; Connection
            </button>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#185FA5", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 600, color: "#E6F1FB", flexShrink: 0 }}>{user.display_name.charAt(0).toUpperCase()}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 500, color: "#f0ede8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.display_name}</div>
                <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: roleBg[user.role] ?? "#f5f5f4", color: roleColor[user.role] ?? "#5f5e5a", fontWeight: 600 }}>{user.role}</span>
              </div>
              <button onClick={handleLogout} title="Sign out" style={{ background: "none", border: "none", color: "#4a6a8a", cursor: "pointer", padding: 4 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></svg>
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* ══════════ MAIN ══════════ */}
      <div style={{ flex: 1, display: "flex", minWidth: 0 }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>

          {/* Top bar */}
          <div style={{ height: 52, background: "#fff", borderBottom: "1px solid #e5e3dc", display: "flex", alignItems: "center", padding: "0 16px", gap: 10, flexShrink: 0 }}>
            <button onClick={() => setSidebarOpen(v => !v)} style={{ background: "none", border: "none", cursor: "pointer", color: "#888780", padding: 6, borderRadius: 6, display: "flex" }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
            </button>
            <div style={{ flex: 1, fontSize: 14, fontWeight: 500, color: "#1a1a18" }}>{activeSession ? truncate(activeSession.title, 50) : "SQL Analyst"}</div>
            {connected && (
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => { setLineagePanel(v => !v); setCachePanel(false); }} style={{ fontSize: 12, padding: "5px 12px", borderRadius: 6, border: "1px solid #e5e3dc", background: lineagePanel ? "#E6F1FB" : "#fff", color: lineagePanel ? "#0C447C" : "#5f5e5a", cursor: "pointer", fontFamily: "inherit" }}>🔗 Lineage</button>
                <button onClick={() => { setCachePanel(v => !v); setLineagePanel(false); if (!cachePanel) import("@/lib/api").then(({ fetchCache }) => fetchCache().then(r => setCacheEntries(r.entries as CacheEntry[]))); }} style={{ fontSize: 12, padding: "5px 12px", borderRadius: 6, border: "1px solid #e5e3dc", background: cachePanel ? "#E6F1FB" : "#fff", color: cachePanel ? "#0C447C" : "#5f5e5a", cursor: "pointer", fontFamily: "inherit" }}>🗃️ Cache</button>
                {activeSession && <button onClick={newSession} style={{ fontSize: 12, padding: "5px 12px", borderRadius: 6, border: "1px solid #e5e3dc", background: "#fff", color: "#5f5e5a", cursor: "pointer", fontFamily: "inherit" }}>+ New chat</button>}
              </div>
            )}
          </div>

          {/* Settings panel */}
          {settingsOpen && (
            <div style={{ position: "absolute", top: 52, left: 0, right: 0, zIndex: 30, background: "#fff", borderBottom: "1px solid #e5e3dc", padding: "20px 24px", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20, boxShadow: "0 4px 20px rgba(0,0,0,0.08)" }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#888780", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>AI Provider</div>
                <select value={provider} onChange={e => { const p = e.target.value; setProvider(p); if (p === "OpenAI") setModel("gpt-4o-mini"); if (p === "Gemini") setModel("gemini-1.5-flash"); if (p === "Ollama") setModel(""); }} style={{ width: "100%", height: 34, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 13, padding: "0 8px", marginBottom: 8, fontFamily: "inherit" }}>
                  <option>OpenAI</option><option>Gemini</option><option>Ollama</option>
                </select>
                {provider !== "Ollama" && <>
                  <input type="password" placeholder={provider === "OpenAI" ? "sk-..." : "AIza..."} value={apiKey} onChange={e => setApiKey(e.target.value)} style={{ width: "100%", height: 34, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 13, padding: "0 10px", fontFamily: "inherit", marginBottom: 8 }} />
                  <select value={model} onChange={e => setModel(e.target.value)} style={{ width: "100%", height: 34, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 13, padding: "0 8px", fontFamily: "inherit" }}>
                    {provider === "OpenAI" ? ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"].map(m => <option key={m}>{m}</option>) : ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"].map(m => <option key={m}>{m}</option>)}
                  </select>
                </>}
                {provider === "Ollama" && (
                  ollamaFetching
                    ? <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", background: "#f5f5f4", borderRadius: 6, border: "1px solid #d3d1c7" }}><div style={{ width: 14, height: 14, border: "2px solid #d3d1c7", borderTopColor: "#185FA5", borderRadius: "50%", animation: "spin 0.7s linear infinite", flexShrink: 0 }} /><span style={{ fontSize: 12, color: "#888780" }}>Detecting Ollama models…</span></div>
                    : ollamaError
                      ? <div style={{ padding: "8px 10px", background: "#FCEBEB", border: "1px solid #F09595", borderRadius: 6, fontSize: 12, color: "#791F1F" }}>{ollamaError}<button onClick={() => { setOllamaFetching(true); setOllamaError(""); import("@/lib/api").then(({ fetchOllamaModels }) => fetchOllamaModels().then(r => { setOllamaModels(r.models); if (r.models.length) setModel(r.models[0].name); else setOllamaError("No models found."); }).catch(e => setOllamaError(e instanceof Error ? e.message : "Error")).finally(() => setOllamaFetching(false))); }} style={{ marginLeft: 8, fontSize: 11, color: "#185FA5", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit", textDecoration: "underline" }}>Retry</button></div>
                      : ollamaModels.length === 0
                        ? <div style={{ padding: "8px 10px", background: "#FAEEDA", border: "1px solid #FAC775", borderRadius: 6, fontSize: 12, color: "#633806" }}>No models. Make sure Ollama is running.</div>
                        : <><select value={model} onChange={e => setModel(e.target.value)} style={{ width: "100%", height: 36, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 13, padding: "0 8px", fontFamily: "inherit", marginBottom: 8 }}>{ollamaModels.map(m => <option key={m.name} value={m.name}>{m.name}{m.size_gb > 0 ? ` (${m.size_gb} GB)` : ""}</option>)}</select><button onClick={() => { setOllamaFetching(true); setOllamaError(""); import("@/lib/api").then(({ fetchOllamaModels }) => fetchOllamaModels().then(r => { setOllamaModels(r.models); if (r.models.length) setModel(r.models[0].name); }).catch(e => setOllamaError(e instanceof Error ? e.message : "Error")).finally(() => setOllamaFetching(false))); }} style={{ fontSize: 11, color: "#888780", background: "none", border: "1px solid #d3d1c7", borderRadius: 5, padding: "4px 10px", cursor: "pointer", fontFamily: "inherit" }}>↻ Refresh</button></>
                )}
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#888780", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>SQL Server {connected && <span style={{ color: "#639922", marginLeft: 6 }}>✓ {database}</span>}</div>
                <input placeholder="Server" value={server} onChange={e => setServer(e.target.value)} style={{ width: "100%", height: 34, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 13, padding: "0 10px", fontFamily: "inherit", marginBottom: 6 }} />
                <input placeholder="Database name" value={dbName} onChange={e => setDbName(e.target.value)} style={{ width: "100%", height: 34, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 13, padding: "0 10px", fontFamily: "inherit", marginBottom: 8 }} />
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#5f5e5a", marginBottom: 6, cursor: "pointer" }}><input type="checkbox" checked={winAuth} onChange={e => setWinAuth(e.target.checked)} style={{ accentColor: "#185FA5" }} />Windows authentication</label>
                {!winAuth && <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 6 }}>
                  <input placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} style={{ height: 32, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 12, padding: "0 8px", fontFamily: "inherit" }} />
                  <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} style={{ height: 32, borderRadius: 6, border: "1px solid #d3d1c7", background: "#f5f5f4", fontSize: 12, padding: "0 8px", fontFamily: "inherit" }} />
                </div>}
                {connError && <div style={{ fontSize: 11, color: "#791F1F", marginBottom: 6 }}>{connError}</div>}
                <button onClick={handleConnect} disabled={connecting} style={{ width: "100%", height: 34, borderRadius: 6, background: "#185FA5", color: "#E6F1FB", border: "none", fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "inherit" }}>{connecting ? "Connecting…" : connected ? "Reconnect" : "Connect"}</button>
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#888780", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>Semantic Cache</div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}><span style={{ fontSize: 12, color: "#5f5e5a" }}>Similarity threshold</span><span style={{ fontSize: 12, fontWeight: 600, fontFamily: "var(--mono)" }}>{simThreshold.toFixed(2)}</span></div>
                <input type="range" min={0.70} max={1.00} step={0.01} value={simThreshold} onChange={e => setSimThreshold(parseFloat(e.target.value))} style={{ width: "100%", accentColor: "#185FA5", marginBottom: 4 }} />
                <div style={{ fontSize: 11, color: "#888780" }}>{simThreshold >= 0.95 ? "🔴 Very strict" : simThreshold >= 0.85 ? "🟡 Balanced" : "🟢 Aggressive"}</div>
                {tables.length > 0 && <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#888780", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Tables ({tables.length})</div>
                  <div style={{ maxHeight: 100, overflowY: "auto", fontSize: 11, color: "#5f5e5a" }}>
                    {tables.map(t => <div key={t.full_name} style={{ padding: "2px 0", display: "flex", justifyContent: "space-between" }}><span>{t.full_name}</span><span style={{ color: "#888780" }}>{t.row_count.toLocaleString()}</span></div>)}
                  </div>
                </div>}
              </div>
            </div>
          )}



          {/* Chat messages */}
          <div style={{ flex: 1, overflowY: "auto", padding: "24px 0" }}>
            <div style={{ maxWidth: 820, margin: "0 auto", padding: "0 24px" }}>

              {/* Empty state */}
              {(!activeSession || activeSession.messages.length === 0) && (
                <div style={{ textAlign: "center", paddingTop: 60 }}>
                  <div style={{ width: 56, height: 56, background: "#E6F1FB", borderRadius: 16, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#185FA5" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" />
                      <circle cx="17.5" cy="17.5" r="3.5" /><line x1="17.5" y1="15.5" x2="17.5" y2="19.5" /><line x1="15.5" y1="17.5" x2="19.5" y2="17.5" />
                    </svg>
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 600, color: "#1a1a18", marginBottom: 8 }}>{connected ? `Connected to ${database}` : "SQL Analyst"}</div>
                  <div style={{ fontSize: 14, color: "#888780", marginBottom: 32, lineHeight: 1.6 }}>{connected ? "Ask any question about your data in plain English, or attach a CSV / Excel file" : "Connect to your SQL Server database to get started"}</div>
                  {!connected && <button onClick={() => setSettingsOpen(true)} style={{ padding: "10px 24px", borderRadius: 8, background: "#185FA5", color: "#E6F1FB", border: "none", fontSize: 14, fontWeight: 500, cursor: "pointer", fontFamily: "inherit", marginBottom: 32 }}>Connect database</button>}
                  {connected && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, maxWidth: 620, margin: "0 auto" }}>
                      {QUICK_PROMPTS.map(p => (
                        <button key={p.q} onClick={() => sendMessage(p.q)} style={{ padding: "12px 14px", borderRadius: 10, border: "1px solid #e5e3dc", background: "#fff", cursor: "pointer", fontFamily: "inherit", textAlign: "left", transition: "border-color 0.15s,box-shadow 0.15s" }}
                          onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#B5D4F4"; (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 2px 8px rgba(24,95,165,0.1)"; }}
                          onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = "#e5e3dc"; (e.currentTarget as HTMLButtonElement).style.boxShadow = "none"; }}>
                          <div style={{ fontSize: 18, marginBottom: 4 }}>{p.icon}</div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#1a1a18", marginBottom: 2 }}>{p.label}</div>
                          <div style={{ fontSize: 11, color: "#888780", lineHeight: 1.4 }}>{truncate(p.q, 44)}</div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Messages */}
              {activeSession?.messages.map((msg, index) => (
                <MessageBubble 
                  key={msg.id} 
                  msg={msg} 
                  onEdit={(text) => setInput(text)} 
                  onRetry={(text) => sendMessage(text, msg.id)} 
                  onDelete={() => setSessions(prev => prev.map(s => {
                    if (s.id !== activeSessionId) return s;
                    const idx = s.messages.findIndex(m => m.id === msg.id);
                    if (idx === -1) return s;
                    const newMsgs = [...s.messages];
                    newMsgs.splice(idx, msg.role === "user" ? 2 : 1);
                    return { ...s, messages: newMsgs };
                  }))}
                />
              ))}
              <div ref={chatEndRef} />
            </div>
          </div>

          {/* Input bar */}
          <div style={{ background: "#fff", borderTop: "1px solid #e5e3dc", padding: "12px 24px 16px", flexShrink: 0 }}>
            <div style={{ maxWidth: 820, margin: "0 auto" }}>

              {/* Attachments preview area — images as thumbnails, docs as chips */}
              {(attachedFiles.length > 0 || uploadingFile) && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10, alignItems: "flex-end" }}>

                  {/* Uploading indicator */}
                  {uploadingFile && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "6px 12px", borderRadius: 10,
                      background: "#f5f5f4", border: "1px dashed #d3d1c7",
                      fontSize: 11, color: "#888780",
                    }}>
                      <div style={{ width: 12, height: 12, border: "2px solid #d3d1c7", borderTopColor: "#185FA5", borderRadius: "50%", animation: "spin 0.7s linear infinite", flexShrink: 0 }} />
                      Uploading {uploadingLabel || "file"}…
                    </div>
                  )}

                  {/* Render each attachment */}
                  {attachedFiles.map(f => {
                    const isImage = !!f.imagePreviewUrl;
                    const [displayFile, displaySheet] = f.name.includes(" · ") ? f.name.split(" · ") : [f.name, null];
                    const fileIcon = ["csv","tsv"].includes(f.type) ? "📄" : ["xlsx","xls"].includes(f.type) ? "📊" : ["pdf"].includes(f.type) ? "📕" : ["doc","docx"].includes(f.type) ? "📝" : ["ppt","pptx"].includes(f.type) ? "📋" : ["png","jpg","jpeg","webp","bmp","tiff"].includes(f.type) ? "🖼️" : "📎";

                    if (isImage) {
                      // ── Image thumbnail (like Claude / ChatGPT) ──────────────
                      return (
                        <div key={f.id} style={{ position: "relative", flexShrink: 0 }}>
                          <img
                            src={f.imagePreviewUrl}
                            alt={f.name}
                            style={{
                              width: 72, height: 72, objectFit: "cover",
                              borderRadius: 10, border: "1.5px solid #d3d1c7",
                              display: "block",
                            }}
                          />
                          <button
                            onClick={() => { setAttachedFiles(prev => prev.filter(x => x.id !== f.id)); if (f.imagePreviewUrl) URL.revokeObjectURL(f.imagePreviewUrl); }}
                            style={{
                              position: "absolute", top: -6, right: -6,
                              width: 18, height: 18, borderRadius: "50%",
                              background: "#1a1a18", border: "2px solid #fff",
                              cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                              color: "#fff", padding: 0, lineHeight: 1,
                            }}
                          >
                            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                          </button>
                        </div>
                      );
                    }

                    // ── Document / data chip ──────────────────────────────────
                    return (
                      <div key={f.id} style={{
                        display: "flex", alignItems: "center", gap: 6,
                        padding: "6px 10px", background: "#E6F1FB",
                        borderRadius: 10, border: "1px solid #B5D4F4", maxWidth: 240,
                      }}>
                        <span style={{ fontSize: 14, flexShrink: 0 }}>{fileIcon}</span>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontSize: 11, fontWeight: 600, color: "#0C447C", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{displayFile}</div>
                          {displaySheet && <div style={{ fontSize: 9, color: "#378ADD", fontWeight: 500 }}>📋 {displaySheet}</div>}
                          {f.rowCount > 0 && <div style={{ fontSize: 9, color: "#378ADD" }}>{f.rowCount.toLocaleString()} rows × {f.colCount} cols</div>}
                          {f.rowCount === 0 && f.columns.length === 0 && <div style={{ fontSize: 9, color: "#888780" }}>{f.type.toUpperCase()}</div>}
                        </div>
                        <button
                          onClick={() => setAttachedFiles(prev => prev.filter(x => x.id !== f.id))}
                          style={{ background: "none", border: "none", cursor: "pointer", color: "#378ADD", padding: 1, flexShrink: 0, borderRadius: 4 }}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                      </div>
                    );
                  })}

                  {/* Comparison mode label */}
                  {attachedFiles.filter(f => !f.imagePreviewUrl).length > 1 && (
                    <div style={{ fontSize: 11, color: "#0C447C", fontWeight: 600, padding: "2px 4px", alignSelf: "center" }}>
                      🔀 Compare mode
                    </div>
                  )}
                </div>
              )}

              {/* Input box */}
              <div style={{ display: "flex", alignItems: "flex-end", gap: 8, background: "#f5f5f4", border: "1.5px solid #d3d1c7", borderRadius: 14, padding: "8px 10px", transition: "border-color 0.15s" }} onClick={() => inputRef.current?.focus()}>

                {/* Hidden file input */}
                <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls,.json,.tsv,.txt,.pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.webp,.bmp,.tiff" style={{ display: "none" }} multiple
                  onChange={async e => {
                    const files = Array.from(e.target.files || []);
                    if (files.length === 0 || !connected) return;
                    e.target.value = "";
                    if (attachedFiles.length + files.length > MAX_ATTACHED) { alert(`Maximum ${MAX_ATTACHED} files at once. Currently attached: ${attachedFiles.length}`); return; }
                    const IMAGE_EXTS = ["png","jpg","jpeg","webp","bmp","tiff"];
                    setUploadingFile(true);
                    try {
                      const { uploadFile, uploadClipboardImage } = await import("@/lib/api");
                      const toQueue: SheetPickerData[] = [];
                      for (const file of files) {
                        const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
                        setUploadingLabel(file.name);
                        const isImg = IMAGE_EXTS.includes(ext);
                        if (isImg) {
                          // Show instant local preview
                          const previewUrl = URL.createObjectURL(file);
                          const tempId = Date.now() + Math.random();
                          setAttachedFiles(prev => [...prev, { id: tempId, name: file.name, type: ext, rowCount: 0, colCount: 0, columns: [], sheetName: null, imagePreviewUrl: previewUrl }]);
                          // Upload as clipboard image (base64)
                          const buf = await file.arrayBuffer();
                          const bytes = new Uint8Array(buf);
                          let binary = ""; bytes.forEach(b => (binary += String.fromCharCode(b)));
                          const b64 = btoa(binary);
                          const res = await uploadClipboardImage(b64, file.name);
                          setAttachedFiles(prev => prev.map(f => f.id === tempId
                            ? { id: res.file_id, name: res.file_name, type: res.file_type, rowCount: res.row_count, colCount: res.col_count, columns: res.columns, sheetName: null, imagePreviewUrl: previewUrl }
                            : f
                          ));
                        } else {
                          const res = await uploadFile(file);
                          if (res.is_multi_sheet && res.sheets && res.sheets.length > 0) {
                            toQueue.push({ fileName: res.file_name, sheets: res.sheets });
                          } else {
                            setAttachedFiles(prev => {
                              if (prev.some(p => p.id === res.file_id)) return prev;
                              return [...prev, { id: res.file_id, name: res.file_name, type: res.file_type, rowCount: res.row_count, colCount: res.col_count, columns: res.columns, sheetName: res.sheet_names?.[0] ?? null }];
                            });
                          }
                        }
                      }
                      if (toQueue.length > 0) { setSheetPickerQueue(toQueue); setSheetPickerTotal(toQueue.length); setSheetPickerOpen(true); }
                    } catch (err: unknown) {
                      alert(err instanceof Error ? err.message : "Upload failed");
                    } finally { setUploadingFile(false); setUploadingLabel(""); }
                  }}
                />

                {/* Attach button */}
                <button onClick={() => fileInputRef.current?.click()} disabled={!connected || uploadingFile} title={connected ? "Attach file or image (CSV, Excel, PDF, DOCX, PNG…)" : "Connect to a database first"}
                  style={{ flexShrink: 0, width: 32, height: 32, borderRadius: 8, border: "none", background: "transparent", cursor: connected ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", color: "#888780", transition: "background 0.1s" }}
                  onMouseEnter={e => { if (connected) (e.currentTarget as HTMLButtonElement).style.background = "#e5e3dc"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}>
                  {uploadingFile
                    ? <div style={{ width: 14, height: 14, border: "2px solid #d3d1c7", borderTopColor: "#185FA5", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
                    : <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" /></svg>
                  }
                </button>

                {/* Mic button */}
                {enableVoice && (
                  <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                    <select 
                      value={language}
                      onChange={e => setLanguage(e.target.value)}
                      title="Select voice language"
                      style={{ background: "transparent", border: "none", color: "#888780", fontSize: 11, cursor: "pointer", outline: "none", padding: "0 2px", fontFamily: "inherit" }}
                    >
                      <option value="en-US">EN</option>
                      <option value="hi-IN">HI</option>
                      <option value="es-ES">ES</option>
                      <option value="fr-FR">FR</option>
                    </select>
                    <button onClick={isRecording ? stopRecording : startRecording} disabled={!connected || isTranscribing} title={connected ? (isRecording ? "Stop recording — Ctrl+Shift+M" : "Voice query — Ctrl+Shift+M") : "Connect to a database first"}
                      style={{ flexShrink: 0, width: 44, height: 44, borderRadius: 8, border: "none", background: isRecording ? "#FCEBEB" : "transparent", cursor: connected && !isTranscribing ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", color: isRecording ? "#D92D20" : "#888780", transition: "background 0.1s, color 0.1s" }}
                      onMouseEnter={e => { if (connected && !isRecording && !isTranscribing) (e.currentTarget as HTMLButtonElement).style.background = "#e5e3dc"; }}
                      onMouseLeave={e => { if (!isRecording) (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}>
                      {isTranscribing
                        ? <div style={{ width: 14, height: 14, border: "2px solid #d3d1c7", borderTopColor: "#185FA5", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
                        : isRecording
                          ? <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
                          : <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 00-3 3v7a3 3 0 006 0V5a3 3 0 00-3-3z" /><path d="M19 10v2a7 7 0 01-14 0v-2" /><line x1="12" y1="19" x2="12" y2="22" /><line x1="8" y1="22" x2="16" y2="22" /></svg>
                      }
                    </button>
                    {/* Live recording badge with pulse dot */}
                    {isRecording && (
                      <div style={{ position: "absolute", top: -28, left: "50%", transform: "translateX(-50%)", background: "#D92D20", color: "#fff", fontSize: 10, padding: "3px 8px", borderRadius: 4, whiteSpace: "nowrap", fontWeight: 700, zIndex: 10, display: "flex", alignItems: "center", gap: 5 }}>
                        <div style={{ width: 6, height: 6, background: "#fff", borderRadius: "50%", animation: "pulse 1s ease-in-out infinite" }} />
                        REC — click to stop
                      </div>
                    )}
                    {/* Live waveform bars while recording */}
                    {isRecording && (
                      <div style={{ position: "absolute", top: -32, left: "50%", transform: "translateX(-50%)", background: "#D92D20", color: "#fff", fontSize: 10, padding: "4px 10px", borderRadius: 4, whiteSpace: "nowrap", fontWeight: 700, zIndex: 10, display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                          {[0.4, 0.8, 1, 0.6, 0.9, 0.5, 0.7].map((h, i) => (
                            <div key={i} style={{ width: 2, height: 12 * h, background: "rgba(255,255,255,0.9)", borderRadius: 2, animation: `pulse ${0.6 + i * 0.1}s ease-in-out infinite alternate` }} />
                          ))}
                        </div>
                        Speaking — click to stop
                      </div>
                    )}
                  </div>
                )}

                {/* Textarea */}
                <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      if (!isRecording) {
                        if (attachedFiles.length > 0 && input.trim()) handleFileAnalysis(input.trim());
                        else sendMessage(input);
                      }
                    }
                  }}
                  placeholder={
                    isRecording
                      ? "🎤 Speak now…"
                      : attachedFiles.length === 1 ? `Ask about ${attachedFiles[0].name}…`
                      : attachedFiles.length > 1 ? `Compare ${attachedFiles.length} files/sheets…`
                      : connected ? "Ask a question, use voice (🎤), or attach a file (📎)…"
                      : "Connect to a database first"
                  }
                  disabled={!connected || sending || uploadingFile} rows={1}
                  style={{
                    flex: 1, background: "transparent", border: "none", outline: "none",
                    fontSize: 14,
                    // Confirmed text = normal dark, interim text (still being spoken) = slightly lighter blue
                    color: isRecording && interimText && input.endsWith(interimText)
                      ? "#378ADD"
                      : "#1a1a18",
                    fontFamily: "inherit", lineHeight: 1.5, maxHeight: 140, overflowY: "auto", paddingTop: 4,
                    transition: "color 0.15s",
                  }}
                  onInput={e => { const t = e.target as HTMLTextAreaElement; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 140) + "px"; }}
                />

                {/* Send button */}
                <button onClick={() => { if (attachedFiles.length > 0 && input.trim()) handleFileAnalysis(input.trim()); else sendMessage(input); }}
                  disabled={!input.trim() || sending || !connected}
                  style={{ width: 34, height: 34, borderRadius: 9, flexShrink: 0, background: input.trim() && connected && !sending ? "#185FA5" : "#d3d1c7", border: "none", cursor: input.trim() && connected ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", transition: "background 0.15s" }}>
                  {sending
                    ? <div style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.65s linear infinite" }} />
                    : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="19" x2="12" y2="5" /><polyline points="5 12 12 5 19 12" /></svg>
                  }
                </button>
              </div>

              {/* Voice error message */}
              {voiceError && (
                <div style={{ fontSize: 12, color: "#791F1F", background: "#FCEBEB", border: "0.5px solid #F09595", borderRadius: 8, padding: "7px 12px", marginTop: 6, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <span>🎤 {voiceError}</span>
                  <button onClick={() => setVoiceError("")} style={{ background: "none", border: "none", cursor: "pointer", color: "#791F1F", fontSize: 14, lineHeight: 1, padding: 0 }}>×</button>
                </div>
              )}

              <div style={{ fontSize: 11, color: "#b4b2a9", textAlign: "center", marginTop: 6 }}>
                Enter to send · 📎 Attach · 🎤 Voice: <kbd style={{ fontFamily: "monospace", background: "#efefed", border: "1px solid #d3d1c7", borderRadius: 3, padding: "1px 5px", fontSize: 10, color: "#5f5e5a", letterSpacing: "0.02em" }}>Ctrl+Shift+M</kbd> · Multi-sheet Excel supported
              </div>
            </div>
          </div>
        </div>{/* end inner flex column */}

        {/* File Panel — right side */}
        {filePanelOpen && connected && (
          <div style={{ width: 320, borderLeft: "1px solid #e5e3dc", background: "#fff", display: "flex", flexDirection: "column", flexShrink: 0, overflow: "hidden" }}>
            <FilePanel
              provider={provider} model={model} apiKey={apiKey} connected={connected}
              onAnalysis={(result, fileName, prompt) => {
                setFilePanelOpen(false);
                const summaryText = (result.cached ? "⚡ Cached · " : "") + `Analysed ${fileName} (${result.row_count?.toLocaleString()} rows)`;
                const assistantMsg: Message = {
                  id: uid(), role: "assistant", content: summaryText,
                  result: {
                    question: prompt, sql_query: "", analysis: result.analysis,
                    columns: result.chart_data?.columns ?? [],
                    rows: result.chart_data?.rows ?? [],
                    row_count: result.row_count,
                    source: result.cached ? "cache" : "model",
                    timing: result.cached ? { cache_ms: result.cache_ms ?? 0, first_exec_ms: result.execution_time_ms ?? 0, match_type: "exact", similarity: 1.0, model_ms: result.execution_time_ms ?? 0 } : { model_ms: result.execution_time_ms ?? 0 },
                    asked_at: new Date().toISOString(), completed_at: new Date().toISOString(),
                  }
                };
                setSessions(prev => prev.map(s => s.id === activeSessionId ? { ...s, messages: [...s.messages, assistantMsg] } : s));
              }}
            />
          </div>
        )}

        {/* Data Lineage Drawer — right side */}
        {lineagePanel && (
          <div style={{ width: 380, flexShrink: 0, overflow: "hidden", borderLeft: "1px solid #e5e3dc", background: "#fff", zIndex: 10 }}>
            <DataLineagePanel 
              onClose={() => setLineagePanel(false)}
              onAttachFile={(table) => {
                if (attachedFiles.some(f => f.id === table.file_id)) return;
                const ext = table.file_name.toLowerCase().split('.').pop() || "unknown";
                let category = "structured";
                if (["pdf", "docx", "doc", "pptx", "ppt", "txt", "md"].includes(ext)) category = "document";
                else if (["png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif"].includes(ext)) category = "image_ocr";
                
                setAttachedFiles(prev => [...prev, {
                  id: table.file_id!,
                  name: table.file_name,
                  type: ext,
                  category: category as any,
                  rowCount: table.row_count ?? 0,
                  colCount: table.col_count ?? 0,
                  columns: table.columns ?? [],
                  sheetName: null,
                }]);
              }} 
            />
          </div>
        )}
        {/* Semantic Cache Drawer — right side */}
        {cachePanel && (
          <div style={{ width: 420, flexShrink: 0, display: "flex", flexDirection: "column", borderLeft: "1px solid #e5e3dc", background: "#fafaf9", zIndex: 10 }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px", background: "#fff", borderBottom: "1px solid #e5e3dc", flexShrink: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#1a1a18" }}>🗃️ Semantic Cache ({cacheEntries.length})</div>
              <div style={{ display: "flex", gap: 8 }}>
                {user.role === "Admin" && <button onClick={async () => { await flushCache(); setCacheEntries([]); }} style={{ fontSize: 11, padding: "4px 10px", borderRadius: 5, border: "1px solid #F09595", color: "#791F1F", background: "#FCEBEB", cursor: "pointer", fontFamily: "inherit" }}>Flush all</button>}
                <button onClick={() => setCachePanel(false)} style={{ background: "none", border: "none", cursor: "pointer", color: "#888780", padding: 4, display: "flex" }}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
              </div>
            </div>
            {/* Body */}
            <div style={{ flex: 1, overflowY: "auto", padding: "16px" }}>
              {cacheEntries.length === 0 ? <div style={{ fontSize: 13, color: "#888780", textAlign: "center", marginTop: 40 }}>No cached queries yet.</div> : (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {cacheEntries.map(e => (
                    <div key={e.id} style={{ background: "#fff", border: "1px solid #e5e3dc", borderRadius: 10, padding: 12, position: "relative", boxShadow: "0 1px 3px rgba(0,0,0,0.02)" }}>
                      {user.role === "Admin" && (
                        <button onClick={async () => { await deleteCacheEntry(e.id); setCacheEntries(p => p.filter(x => x.id !== e.id)); }} style={{ position: "absolute", top: 12, right: 12, fontSize: 11, color: "#b4b2a9", background: "none", border: "none", cursor: "pointer" }} onMouseEnter={ev => (ev.currentTarget.style.color = "#D92D20")} onMouseLeave={ev => (ev.currentTarget.style.color = "#b4b2a9")}>✕</button>
                      )}
                      <div style={{ fontSize: 13, fontWeight: 500, color: "#1a1a18", marginBottom: 12, paddingRight: 20 }}>"{e.user_question}"</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, fontSize: 11, color: "#5f5e5a" }}>
                        <div style={{ background: "#f5f5f4", padding: "3px 8px", borderRadius: 4 }}>🤖 {e.provider}</div>
                        <div style={{ background: "#E6F1FB", color: "#0C447C", padding: "3px 8px", borderRadius: 4 }}>🎯 {e.hit_count} hits</div>
                        <div style={{ background: "#EAF3DE", color: "#27500A", padding: "3px 8px", borderRadius: 4 }}>⚡ {e.first_exec_ms?.toFixed(0)} ms</div>
                      </div>
                      <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #f0ede8", fontSize: 10, color: "#888780" }}>
                        Last accessed: {e.last_accessed ? new Date(e.last_accessed).toLocaleDateString() : "—"}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>{/* end outer flex row */}
    </div>
  );
}