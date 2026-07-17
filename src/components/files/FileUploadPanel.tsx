"use client";
import React from "react";
import type { UploadedFile } from "@/lib/api";
import { InsightBlock } from "@/components/charts/InsightBlock";

const MAX_FILES_PANEL = 50;
const MAX_FILE_BYTES = 50 * 1024 * 1024;
const ALLOWED_EXT_LIST = [
  // Structured
  "csv", "xlsx", "xls", "json", "tsv",
  // Documents
  "txt", "pdf", "doc", "docx", "ppt", "pptx",
  // Images
  "png", "jpg", "jpeg", "webp", "bmp", "tiff",
];

const ALLOWED_ACCEPT = [
  ".csv",".xlsx",".xls",".json",".tsv",
  ".txt",".pdf",".doc",".docx",".ppt",".pptx",
  ".png",".jpg",".jpeg",".webp",".bmp",".tiff",
].join(",");

type GovernanceResult = {
  business_type: string | null;
  confidence:    number | null;
  flagged:       boolean;
  flag_reason:   string | null;
  policy_action: string | null;
  ocr_used:      boolean;
  columns:       string[];
  preview:       string[][];
  sql_table:     string | null;
  file_id:       number;
};

function fmtSize(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

export function FileUploadPanel({
  provider,
  model,
  apiKey,
  baseUrl,
  onAnalysis,
  onOpenPanel,
}: {
  provider: string;
  model: string;
  apiKey: string;
  baseUrl: string;
  onAnalysis: (text: string) => void;
  onOpenPanel?: () => void;
}) {
  const [files, setFiles] = React.useState<UploadedFile[]>([]);
  const [uploading, setUploading] = React.useState(false);
  const [uploadProgress, setUploadProgress] = React.useState<{stage: string; details: string} | null>(null);
  const [analysing, setAnalysing] = React.useState<number | null>(null);
  const [prompt, setPrompt] = React.useState("");
  const [activeFile, setActiveFile] = React.useState<number | null>(null);
  const [analysis, setAnalysis] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState("");
  const [dragging, setDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Governance / Review state
  const [govResult, setGovResult] = React.useState<GovernanceResult | null>(null);
  const [showSchemaPreview, setShowSchemaPreview] = React.useState(false);
  const [showManualReview, setShowManualReview] = React.useState(false);
  const [pendingApproval, setPendingApproval] = React.useState<GovernanceResult | null>(null);

  // Ctrl+V paste handler
  React.useEffect(() => {
    const handlePaste = async (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items ?? []).find(
        (i) => i.type.startsWith("image/")
      );
      if (!item) return;
      e.preventDefault();
      const blob = item.getAsFile();
      if (!blob) return;
      if (onOpenPanel) onOpenPanel();
      await uploadClipboard(blob);
    };
    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, [files.length]);

  React.useEffect(() => {
    import("@/lib/api").then(({ listFiles }) => {
      listFiles()
        .then((r) => {
          if (r.files) setFiles(r.files.slice(0, MAX_FILES_PANEL));
        })
        .catch(() => {});
    });
  }, []);

  async function uploadFile(file: File) {
    if (files.length >= MAX_FILES_PANEL) { setError(`Max ${MAX_FILES_PANEL} files allowed.`); return; }
    if (file.size > MAX_FILE_BYTES) { setError(`File too large. Max 50 MB.`); return; }
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!ALLOWED_EXT_LIST.includes(ext)) {
      setError(`Unsupported file type (.${ext}). Supported: CSV, Excel, PDF, DOCX, PPTX, TXT, JSON, Images.`);
      return;
    }
    setUploading(true); setError(""); setUploadProgress(null);
    try {
      const { uploadFile: apiUpload, listFiles } = await import("@/lib/api");
      const data = await apiUpload(file, (stage, details) => setUploadProgress({ stage, details }));
      const refreshed = await listFiles();
      setFiles(refreshed.files.slice(0, MAX_FILES_PANEL));
      setActiveFile(data.file_id);
      handleGovernanceResponse(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally { setUploading(false); setUploadProgress(null); }
  }

  async function uploadClipboard(blob: Blob) {
    if (files.length >= MAX_FILES_PANEL) { setError(`Max ${MAX_FILES_PANEL} files allowed.`); return; }
    setUploading(true); setError(""); setUploadProgress(null);
    try {
      const { uploadClipboardImage, listFiles } = await import("@/lib/api");
      // Convert blob to base64
      const buf    = await blob.arrayBuffer();
      const bytes  = new Uint8Array(buf);
      let binary   = "";
      bytes.forEach((b) => (binary += String.fromCharCode(b)));
      const b64    = btoa(binary);
      const data   = await uploadClipboardImage(b64, `clipboard_${Date.now()}.png`, (stage, details) => setUploadProgress({ stage, details }));
      const refreshed = await listFiles();
      setFiles(refreshed.files.slice(0, MAX_FILES_PANEL));
      setActiveFile(data.file_id);
      handleGovernanceResponse(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Clipboard upload failed");
    } finally { setUploading(false); setUploadProgress(null); }
  }

  function handleGovernanceResponse(data: import("@/lib/api").FileUploadResult) {
    const gov: GovernanceResult = {
      business_type: data.business_type ?? null,
      confidence:    data.confidence ?? null,
      flagged:       data.flagged ?? false,
      flag_reason:   data.flag_reason ?? null,
      policy_action: data.policy_action ?? null,
      ocr_used:      data.ocr_used ?? false,
      columns:       data.columns ?? [],
      preview:       data.preview ?? [],
      sql_table:     data.sql_table ?? null,
      file_id:       data.file_id,
    };
    setGovResult(gov);
    if (data.policy_action === "manual_review") {
      setPendingApproval(gov);
      setShowManualReview(true);
    } else if (data.flagged && data.policy_action === "warn") {
      setPendingApproval(gov);
      setShowSchemaPreview(true);
    }
  }

  async function runAnalysis() {
    if (!activeFile || !prompt.trim()) return;
    setAnalysing(activeFile);
    setError("");
    try {
      const { analyzeFile } = await import("@/lib/api");
      const data = await analyzeFile({
        file_id: activeFile,
        prompt: prompt.trim(),
        provider,
        model,
        api_key: apiKey || undefined,
        base_url: baseUrl,
      });
      const fileCategory = (data as { file_category?: string }).file_category ?? "unknown";
      const hasTable = (data.chart_data?.columns?.length ?? 0) > 0 && (data.chart_data?.rows?.length ?? 0) > 0;
      let summary = "";
      if (hasTable) {
        summary = `${data.cached ? "⚡ Cached" : "🧠 AI"} analysis of **${data.file_name}** — found ${(data.chart_data?.rows?.length ?? 0).toLocaleString()} rows`;
      } else if (fileCategory === "structured" && (data.row_count ?? 0) > 0) {
        summary = `${data.cached ? "⚡ Cached" : "🧠 AI"} analysis of **${data.file_name}** (${(data.row_count ?? 0).toLocaleString()} rows)`;
      } else {
        // Document / image / text — no row count
        summary = `${data.cached ? "⚡ Cached" : "🧠 AI"} analysis of **${data.file_name}**`;
      }
      setAnalysis((prev) => ({ ...prev, [String(activeFile)]: data.analysis }));
      onAnalysis(summary + ":\n\n" + data.analysis);

    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalysing(null);
    }
  }

  async function deleteFile(id: number) {
    const { deleteFile: apiDelete, listFiles } = await import("@/lib/api");
    await apiDelete(id);
    const refreshed = await listFiles();
    setFiles(refreshed.files.slice(0, MAX_FILES_PANEL));
    if (activeFile === id) setActiveFile(null);
    const a = { ...analysis };
    delete a[String(id)];
    setAnalysis(a);
  }

  const active = files.find((f) => f.id === activeFile);

  return (
    <>
    <div
      style={{
        border: "1px solid #e5e3dc",
        borderRadius: 12,
        overflow: "hidden",
        background: "#fff",
        marginBottom: 16,
      }}
    >
      <div
        style={{
          background: "#f5f5f4",
          padding: "10px 16px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderBottom: "1px solid #e5e3dc",
        }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#185FA5"
          strokeWidth="2"
          strokeLinecap="round"
        >
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="12" y1="18" x2="12" y2="12" />
          <line x1="9" y1="15" x2="15" y2="15" />
        </svg>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#1a1a18" }}>
          File Analysis
        </span>
        <span style={{ fontSize: 11, color: "#888780" }}>
          {files.length}/{MAX_FILES_PANEL} files · Max 50 MB each
        </span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 60,
              height: 4,
              borderRadius: 2,
              background: "#e5e3dc",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${(files.length / MAX_FILES_PANEL) * 100}%`,
                height: "100%",
                background:
                  files.length >= MAX_FILES_PANEL ? "#F09595" : "#185FA5",
                transition: "width 0.3s",
              }}
            />
          </div>
          <span style={{ fontSize: 10, color: "#888780" }}>
            {files.length}/{MAX_FILES_PANEL}
          </span>
        </div>
      </div>

      <div style={{ padding: 16 }}>
        {/* Drop zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files[0];
            if (f) uploadFile(f);
          }}
          onClick={() =>
            !uploading &&
            files.length < MAX_FILES_PANEL &&
            inputRef.current?.click()
          }
          style={{
            border: `2px dashed ${dragging ? "#185FA5" : "#d3d1c7"}`,
            borderRadius: 8,
            padding: "16px 12px",
            textAlign: "center",
            cursor:
              files.length >= MAX_FILES_PANEL ? "not-allowed" : "pointer",
            background: dragging
              ? "#E6F1FB"
              : files.length >= MAX_FILES_PANEL
              ? "#f9f9f8"
              : "#fafaf9",
            transition: "all 0.15s",
            marginBottom: 12,
          }}
        >
          <input
            ref={inputRef}
            type="file"
          accept={ALLOWED_ACCEPT}
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) uploadFile(f);
              e.target.value = "";
            }}
          />
          {uploading ? (
            <UploadProgressDisplay progress={uploadProgress} />
          ) : files.length >= MAX_FILES_PANEL ? (
            <span style={{ fontSize: 12, color: "#888780" }}>
              File limit reached. Delete a file to upload more.
            </span>
          ) : (
            <div>
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#888780"
                strokeWidth="1.5"
                strokeLinecap="round"
                style={{ marginBottom: 6 }}
              >
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <div style={{ fontSize: 12, color: "#5f5e5a", marginBottom: 2 }}>
                Drop any file here, or <strong>Ctrl+V</strong> to paste a screenshot
              </div>
              <div style={{ fontSize: 11, color: "#888780" }}>
                CSV · Excel · PDF · DOCX · PPTX · TXT · JSON · Images · Max 50 MB
              </div>
            </div>
          )}
        </div>

        {error && (
          <div
            style={{
              fontSize: 11,
              color: "#791F1F",
              background: "#FCEBEB",
              border: "1px solid #F09595",
              borderRadius: 6,
              padding: "6px 10px",
              marginBottom: 10,
            }}
          >
            {error}
          </div>
        )}

        {files.length > 0 && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              marginBottom: 12,
            }}
          >
            {files.map((f) => (
              <div
                key={f.id}
                onClick={() => setActiveFile(f.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  borderRadius: 7,
                  cursor: "pointer",
                  background: f.id === activeFile ? "#E6F1FB" : "#f5f5f4",
                  border:
                    f.id === activeFile
                      ? "1px solid #B5D4F4"
                      : "1px solid transparent",
                  transition: "all 0.15s",
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 6,
                    background:
                      f.file_type === "csv" ? "#EAF3DE" : "#E6F1FB",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      color: f.file_type === "csv" ? "#27500A" : "#0C447C",
                    }}
                  >
                    {f.file_type.toUpperCase()}
                  </span>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: 500,
                      color: "#1a1a18",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {f.file_name}
                  </div>
                  <div style={{ fontSize: 10, color: "#888780" }}>
                    {f.category === "structured"
                      ? `${f.row_count?.toLocaleString() ?? 0} rows · ${f.col_count ?? 0} cols · ${fmtSize(f.file_size)}`
                      : f.category === "document"
                      ? `Document · ${fmtSize(f.file_size)}`
                      : f.category === "image_ocr"
                      ? `Image (OCR) · ${fmtSize(f.file_size)}`
                      : fmtSize(f.file_size)}
                  </div>

                  {f.sheet_name && (
                    <div style={{ fontSize: 9, color: "#378ADD", fontWeight: 500 }}>
                      📋 {f.sheet_name}
                    </div>
                  )}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteFile(f.id);
                  }}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "#888780",
                    padding: 2,
                    flexShrink: 0,
                    borderRadius: 4,
                  }}
                  title="Remove file"
                >
                  <svg
                    width="11"
                    height="11"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  >
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {active && (
          <div>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 4,
                marginBottom: 10,
              }}
            >
              {active.columns.slice(0, 12).map((c) => (
                <span
                  key={c}
                  style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: "#f5f5f4",
                    border: "1px solid #e5e3dc",
                    color: "#5f5e5a",
                  }}
                >
                  {c}
                </span>
              ))}
              {active.columns.length > 12 && (
                <span style={{ fontSize: 10, color: "#888780" }}>
                  +{active.columns.length - 12} more
                </span>
              )}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    runAnalysis();
                  }
                }}
                placeholder={`Ask about ${active.file_name}… e.g. "What are the top trends?"`}
                style={{
                  flex: 1,
                  height: 34,
                  borderRadius: 7,
                  border: "1px solid #d3d1c7",
                  background: "#f5f5f4",
                  fontSize: 12,
                  padding: "0 10px",
                  fontFamily: "inherit",
                  outline: "none",
                }}
              />
              <button
                onClick={runAnalysis}
                disabled={!prompt.trim() || !!analysing}
                style={{
                  padding: "0 14px",
                  height: 34,
                  borderRadius: 7,
                  background:
                    prompt.trim() && !analysing ? "#185FA5" : "#d3d1c7",
                  color: "#fff",
                  border: "none",
                  fontSize: 12,
                  fontWeight: 500,
                  cursor:
                    prompt.trim() && !analysing ? "pointer" : "not-allowed",
                  fontFamily: "inherit",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  flexShrink: 0,
                }}
              >
                {analysing ? (
                  <>
                    <div
                      style={{
                        width: 11,
                        height: 11,
                        border: "2px solid rgba(255,255,255,0.3)",
                        borderTopColor: "#fff",
                        borderRadius: "50%",
                        animation: "spin 0.65s linear infinite",
                      }}
                    />{" "}
                    Analysing…
                  </>
                ) : (
                  "Analyse"
                )}
              </button>
            </div>
            {analysis[String(active.id)] && (
              <InsightBlock analysis={analysis[String(active.id)]} />
            )}
          </div>
        )}

        {files.length === 0 && !uploading && (
          <div
            style={{
              fontSize: 11,
              color: "#888780",
              textAlign: "center",
              paddingTop: 4,
            }}
          >
          Upload any supported file or paste a screenshot (Ctrl+V) to analyse with AI
        </div>
        )}
      </div>
    </div>

    {/* ── Schema Preview Modal ─────────────────────────────────────── */}
    {showSchemaPreview && pendingApproval && (
      <div style={{
        position: "fixed", inset: 0, zIndex: 999,
        background: "rgba(0,0,0,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <div style={{
          background: "#fff", borderRadius: 12, padding: 28,
          width: 480, maxWidth: "95vw", boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <span style={{ fontSize: 20 }}>⚠️</span>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Schema Preview</h3>
            <span style={{
              marginLeft: "auto", fontSize: 11, padding: "2px 8px",
              borderRadius: 99, background: "#FFF3CD", color: "#856404", fontWeight: 600,
            }}>
              {pendingApproval.confidence !== null
                ? `${Math.round(pendingApproval.confidence * 100)}% Confidence`
                : "Warning"}
            </span>
          </div>
          <p style={{ fontSize: 12, color: "#666", margin: "0 0 16px 0" }}>
            Confidence is slightly below the required threshold for{" "}
            <strong>{pendingApproval.business_type ?? "this document type"}</strong>.
            Please review the detected schema before proceeding.
          </p>
          {pendingApproval.flag_reason && (
            <p style={{ fontSize: 11, color: "#856404", background: "#FFF3CD",
              padding: "8px 12px", borderRadius: 6, margin: "0 0 16px 0" }}>
              {pendingApproval.flag_reason}
            </p>
          )}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#444", marginBottom: 6 }}>Detected Table</div>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 10 }}>
              {pendingApproval.sql_table ?? "(not yet stored)"}
            </div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#444", marginBottom: 6 }}>Detected Columns</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {pendingApproval.columns.map((c) => (
                <span key={c} style={{
                  fontSize: 11, padding: "3px 8px",
                  background: "#f0f4ff", color: "#185FA5",
                  borderRadius: 4, fontFamily: "monospace",
                }}>{c}</span>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button onClick={() => { setShowSchemaPreview(false); }}
              style={{ padding: "7px 16px", borderRadius: 6, border: "1px solid #e0e0e0",
                background: "#fff", fontSize: 12, cursor: "pointer" }}>
              Dismiss
            </button>
            <button onClick={() => { setShowSchemaPreview(false); }}
              style={{ padding: "7px 16px", borderRadius: 6, border: "none",
                background: "#185FA5", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              ✔ Approve & Continue
            </button>
          </div>
        </div>
      </div>
    )}

    {/* ── Manual Review Modal ──────────────────────────────────────── */}
    {showManualReview && pendingApproval && (
      <div style={{
        position: "fixed", inset: 0, zIndex: 999,
        background: "rgba(0,0,0,0.5)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <div style={{
          background: "#fff", borderRadius: 12, padding: 28,
          width: 520, maxWidth: "95vw", boxShadow: "0 8px 40px rgba(0,0,0,0.22)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <span style={{ fontSize: 20 }}>🔍</span>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Manual Review Required</h3>
            <span style={{
              marginLeft: "auto", fontSize: 11, padding: "2px 8px",
              borderRadius: 99, background: "#FDECEA", color: "#C62828", fontWeight: 600,
            }}>
              {pendingApproval.confidence !== null
                ? `${Math.round(pendingApproval.confidence * 100)}% Confidence`
                : "Low Confidence"}
            </span>
          </div>
          <p style={{ fontSize: 12, color: "#666", margin: "0 0 12px 0" }}>
            This document did not meet the automatic processing threshold for{" "}
            <strong>{pendingApproval.business_type ?? "this document type"}</strong>.
            Please review the extraction result.
          </p>
          {pendingApproval.flag_reason && (
            <div style={{ fontSize: 11, color: "#C62828", background: "#FDECEA",
              padding: "8px 12px", borderRadius: 6, margin: "0 0 16px 0" }}>
              {pendingApproval.flag_reason}
            </div>
          )}
          {pendingApproval.ocr_used && (
            <div style={{ fontSize: 11, color: "#856404", background: "#FFF3CD",
              padding: "6px 12px", borderRadius: 6, margin: "0 0 16px 0" }}>
              📷 OCR was used to read this document. Accuracy may vary.
            </div>
          )}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#444", marginBottom: 6 }}>Detected Data (Editable)</div>
            <VirtualizedGrid 
              columns={pendingApproval.columns} 
              data={pendingApproval.preview} 
              onDataChange={(newData) => {
                setPendingApproval({ ...pendingApproval, preview: newData });
              }}
            />
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button onClick={() => { setShowManualReview(false); setActiveFile(null); }}
              style={{ padding: "7px 16px", borderRadius: 6, border: "1px solid #FDECEA",
                background: "#FDECEA", color: "#C62828", fontSize: 12, cursor: "pointer" }}>
              ❌ Reject
            </button>
            <button onClick={() => setShowManualReview(false)}
              style={{ padding: "7px 16px", borderRadius: 6, border: "none",
                background: "#185FA5", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              ✔ Approve Anyway
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

// ── Virtualized Grid Component ──────────────────────────────────────────────
import { useVirtualizer } from "@tanstack/react-virtual";

function VirtualizedGrid({ columns, data, onDataChange }: { 
  columns: string[]; 
  data: string[][];
  onDataChange: (newData: string[][]) => void;
}) {
  const parentRef = React.useRef<HTMLDivElement>(null);
  
  // Create a local copy to allow fast inline edits
  const [gridData, setGridData] = React.useState<string[][]>(data);
  const [editingCell, setEditingCell] = React.useState<{row: number, col: number} | null>(null);

  const rowVirtualizer = useVirtualizer({
    count: gridData.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 32, // row height
    overscan: 5,
  });

  const columnVirtualizer = useVirtualizer({
    horizontal: true,
    count: columns.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 120, // default column width
    overscan: 2,
  });

  const handleCellEdit = (rIndex: number, cIndex: number, newVal: string) => {
    const newData = [...gridData];
    newData[rIndex] = [...newData[rIndex]];
    newData[rIndex][cIndex] = newVal;
    setGridData(newData);
    onDataChange(newData);
  };

  if (!columns.length) return <div style={{ fontSize: 11, color: "#888" }}>No data to display.</div>;

  return (
    <div 
      ref={parentRef} 
      style={{ 
        height: 250, 
        width: "100%", 
        overflow: "auto", 
        border: "1px solid #e0e0e0", 
        borderRadius: 6,
        background: "#fafaf9",
        position: "relative"
      }}
    >
      <div
        style={{
          height: `${rowVirtualizer.getTotalSize()}px`,
          width: `${columnVirtualizer.getTotalSize()}px`,
          position: "relative",
        }}
      >
        {rowVirtualizer.getVirtualItems().map((virtualRow) => (
          <React.Fragment key={virtualRow.key}>
            {columnVirtualizer.getVirtualItems().map((virtualColumn) => {
              const isEditing = editingCell?.row === virtualRow.index && editingCell?.col === virtualColumn.index;
              const val = gridData[virtualRow.index]?.[virtualColumn.index] ?? "";
              return (
                <div
                  key={`${virtualRow.key}-${virtualColumn.key}`}
                  onDoubleClick={() => setEditingCell({ row: virtualRow.index, col: virtualColumn.index })}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: `${virtualColumn.size}px`,
                    height: `${virtualRow.size}px`,
                    transform: `translateX(${virtualColumn.start}px) translateY(${virtualRow.start}px)`,
                    borderRight: "1px solid #e0e0e0",
                    borderBottom: "1px solid #e0e0e0",
                    padding: "0 6px",
                    display: "flex",
                    alignItems: "center",
                    fontSize: 11,
                    color: "#333",
                    background: "#fff",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    cursor: "cell",
                  }}
                >
                  {isEditing ? (
                    <input 
                      autoFocus
                      defaultValue={val}
                      onBlur={(e) => {
                        handleCellEdit(virtualRow.index, virtualColumn.index, e.target.value);
                        setEditingCell(null);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          handleCellEdit(virtualRow.index, virtualColumn.index, e.currentTarget.value);
                          setEditingCell(null);
                        }
                      }}
                      style={{ 
                        width: "100%", height: "100%", border: "1px solid #185FA5", 
                        outline: "none", fontSize: 11, padding: 0, margin: 0 
                      }}
                    />
                  ) : (
                    val
                  )}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
      
      {/* Sticky Header Overlay */}
      <div style={{ position: "sticky", top: 0, zIndex: 2, height: 32, background: "#f5f5f4", borderBottom: "1px solid #d3d1c7", width: `${columnVirtualizer.getTotalSize()}px` }}>
        {columnVirtualizer.getVirtualItems().map((virtualColumn) => (
          <div
            key={virtualColumn.key}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: `${virtualColumn.size}px`,
              height: 32,
              transform: `translateX(${virtualColumn.start}px)`,
              borderRight: "1px solid #d3d1c7",
              padding: "0 6px",
              display: "flex",
              alignItems: "center",
              fontSize: 11,
              fontWeight: 600,
              color: "#5f5e5a",
              background: "#f5f5f4",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {columns[virtualColumn.index]}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Upload Progress Display ─────────────────────────────────────────────────
const PIPELINE_STAGES = [
  { key: "routing",        label: "Routing",        icon: "🔀" },
  { key: "extraction",     label: "Extracting",     icon: "📑" },
  { key: "classification", label: "Classifying",    icon: "🏷️" },
  { key: "normalization",  label: "Normalizing",    icon: "🔧" },
  { key: "policy",         label: "Validating",     icon: "✅" },
  { key: "error",          label: "Error",          icon: "⚠️" },
];

function UploadProgressDisplay({ progress }: { progress: { stage: string; details: string } | null }) {
  const currentIdx = progress
    ? PIPELINE_STAGES.findIndex((s) => s.key === progress.stage)
    : -1;

  return (
    <div style={{ width: "100%", padding: "4px 0" }}>
      {/* Stage pipeline */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 0, marginBottom: 8 }}>
        {PIPELINE_STAGES.filter(s => s.key !== "error").map((stage, idx) => {
          const isDone    = currentIdx > idx;
          const isActive  = currentIdx === idx;
          const isPending = currentIdx < idx;
          return (
            <React.Fragment key={stage.key}>
              <div style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 3,
                minWidth: 48,
              }}>
                <div style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 13,
                  background: isDone ? "#EAF3DE" : isActive ? "#E6F1FB" : "#f5f5f4",
                  border: `2px solid ${isDone ? "#639922" : isActive ? "#185FA5" : "#d3d1c7"}`,
                  transition: "all 0.3s ease",
                  boxShadow: isActive ? "0 0 0 3px rgba(24,95,165,0.15)" : "none",
                  animation: isActive ? "pulse 1.5s ease-in-out infinite" : "none",
                }}>
                  {isDone ? "✓" : stage.icon}
                </div>
                <span style={{
                  fontSize: 9,
                  fontWeight: isActive ? 700 : 500,
                  color: isDone ? "#639922" : isActive ? "#185FA5" : "#888780",
                  textAlign: "center",
                  transition: "all 0.3s ease",
                }}>
                  {stage.label}
                </span>
              </div>
              {idx < PIPELINE_STAGES.filter(s => s.key !== "error").length - 1 && (
                <div style={{
                  flex: 1,
                  height: 2,
                  marginBottom: 16,
                  background: isDone ? "#639922" : "#e5e3dc",
                  transition: "background 0.5s ease",
                }} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Current details */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
        {progress?.stage !== "error" && (
          <div style={{
            width: 12, height: 12,
            border: "2px solid #B5D4F4",
            borderTopColor: "#185FA5",
            borderRadius: "50%",
            animation: "spin 0.7s linear infinite",
            flexShrink: 0,
          }} />
        )}
        <span style={{
          fontSize: 11,
          color: progress?.stage === "error" ? "#791F1F" : "#5f5e5a",
          textAlign: "center",
        }}>
          {progress?.details ?? "Preparing…"}
        </span>
      </div>
    </div>
  );
}
