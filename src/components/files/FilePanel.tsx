"use client";
import React from "react";
import type { UploadedFile, FileAnalysisResult } from "@/lib/api";
import { InsightBlock } from "@/components/charts/InsightBlock";

const MAX_FILE_BYTES = 50 * 1024 * 1024;
const ALLOWED_EXT_LIST = ["csv", "xlsx", "xls"];

function fmtSize(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

export function FilePanel({
  provider,
  model,
  apiKey,
  connected,
  onAnalysis,
}: {
  provider: string;
  model: string;
  apiKey: string;
  connected: boolean;
  onAnalysis: (
    result: FileAnalysisResult,
    fileName: string,
    prompt: string
  ) => void;
}) {
  const [files, setFiles] = React.useState<UploadedFile[]>([]);
  const [selected, setSelected] = React.useState<number | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [analyzing, setAnalyzing] = React.useState(false);
  const [prompt, setPrompt] = React.useState("");
  const [error, setError] = React.useState("");
  const [uploadMsg, setUploadMsg] = React.useState("");
  const [dragging, setDragging] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!connected) return;
    import("@/lib/api").then(({ listFiles }) => {
      listFiles()
        .then((r) => setFiles(r.files))
        .catch(() => {});
    });
  }, [connected]);

  const selectedFile = files.find((f) => f.id === selected);

  async function handleUpload(file: File) {
    setError("");
    setUploadMsg("");
    const ext = file.name.toLowerCase().split(".").pop() ?? "";
    if (!ALLOWED_EXT_LIST.includes(ext)) {
      setError("Only CSV and Excel (.xlsx) files are supported.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(
        `File too large. Max size is 50 MB. Your file: ${fmtSize(file.size)}`
      );
      return;
    }
    setUploading(true);
    try {
      const { uploadFile, listFiles } = await import("@/lib/api");
      const result = await uploadFile(file);
      setUploadMsg(
        result.cached
          ? "⚡ File already cached — no re-upload needed!"
          : "✅ File uploaded successfully!"
      );
      const refreshed = await listFiles();
      setFiles(refreshed.files);
      setSelected(result.file_id);
      setTimeout(() => setUploadMsg(""), 4000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleAnalyze() {
    if (!selected || !prompt.trim()) return;
    setError("");
    setAnalyzing(true);
    try {
      const { analyzeFile } = await import("@/lib/api");
      const result = await analyzeFile({
        file_id: selected,
        prompt: prompt.trim(),
        provider,
        model,
        api_key: provider !== "Ollama" ? apiKey : undefined,
        base_url: "http://localhost:11434",
      });
      onAnalysis(result, result.file_name, prompt.trim());
      setPrompt("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleDelete(fileId: number) {
    try {
      const { deleteFile, listFiles } = await import("@/lib/api");
      await deleteFile(fileId);
      const refreshed = await listFiles();
      setFiles(refreshed.files);
      if (selected === fileId) setSelected(null);
    } catch {
      // swallow
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div
        style={{
          padding: "16px 20px 12px",
          borderBottom: "1px solid #e5e3dc",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 4,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: "#1a1a18" }}>
            📁 File Analysis
          </div>
          <div style={{ fontSize: 11, color: "#888780" }}>
            {files.length}/5 files · Max 50 MB each
          </div>
        </div>
        <div style={{ fontSize: 11, color: "#888780" }}>
          Upload CSV or Excel files and ask questions about your data
        </div>
      </div>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "16px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {files.length < 5 && (
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
              if (f) handleUpload(f);
            }}
            onClick={() => fileRef.current?.click()}
            style={{
              border: `2px dashed ${dragging ? "#185FA5" : "#d3d1c7"}`,
              borderRadius: 10,
              padding: "20px 16px",
              textAlign: "center",
              cursor: "pointer",
              background: dragging ? "#E6F1FB" : "#fafaf9",
              transition: "all 0.15s",
            }}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f);
                e.target.value = "";
              }}
            />
            {uploading ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                }}
              >
                <div
                  style={{
                    width: 16,
                    height: 16,
                    border: "2px solid #d3d1c7",
                    borderTopColor: "#185FA5",
                    borderRadius: "50%",
                    animation: "spin 0.7s linear infinite",
                  }}
                />
                <span style={{ fontSize: 13, color: "#888780" }}>
                  Uploading…
                </span>
              </div>
            ) : (
              <>
                <div style={{ fontSize: 24, marginBottom: 6 }}>📂</div>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 500,
                    color: "#1a1a18",
                    marginBottom: 2,
                  }}
                >
                  Drop a file or click to browse
                </div>
                <div style={{ fontSize: 11, color: "#888780" }}>
                  CSV, XLSX · Max 50 MB
                </div>
              </>
            )}
          </div>
        )}

        {uploadMsg && (
          <div
            style={{
              fontSize: 12,
              color: "#27500A",
              background: "#EAF3DE",
              border: "1px solid #97C459",
              borderRadius: 6,
              padding: "8px 12px",
            }}
          >
            {uploadMsg}
          </div>
        )}
        {error && (
          <div
            style={{
              fontSize: 12,
              color: "#791F1F",
              background: "#FCEBEB",
              border: "1px solid #F09595",
              borderRadius: 6,
              padding: "8px 12px",
            }}
          >
            {error}
          </div>
        )}

        {files.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "#888780",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Your files ({files.length}/5)
            </div>
            {files.map((f) => (
              <div
                key={f.id}
                onClick={() => setSelected(f.id === selected ? null : f.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 12px",
                  borderRadius: 8,
                  cursor: "pointer",
                  border:
                    f.id === selected
                      ? "1.5px solid #185FA5"
                      : "1.5px solid #e5e3dc",
                  background: f.id === selected ? "#E6F1FB" : "#fff",
                  transition: "all 0.12s",
                }}
              >
                <div style={{ fontSize: 20, flexShrink: 0 }}>
                  {f.file_type === "csv" ? "📄" : "📊"}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#1a1a18",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {f.file_name}
                  </div>
                  <div style={{ fontSize: 10, color: "#888780" }}>
                    {f.row_count?.toLocaleString()} rows · {f.col_count} cols ·{" "}
                    {fmtSize(f.file_size)}
                  </div>
                  {f.sheet_name && (
                    <div
                      style={{ fontSize: 9, color: "#378ADD", fontWeight: 500 }}
                    >
                      📋 {f.sheet_name}
                    </div>
                  )}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(f.id);
                  }}
                  title="Remove file"
                  style={{
                    flexShrink: 0,
                    background: "none",
                    border: "none",
                    color: "#b4b2a9",
                    cursor: "pointer",
                    padding: 4,
                    borderRadius: 4,
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.color = "#791F1F")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.color = "#b4b2a9")
                  }
                >
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                  >
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6l-1 14H6L5 6" />
                    <path d="M10 11v6M14 11v6" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {selectedFile && (
          <div
            style={{
              background: "#f5f5f4",
              borderRadius: 8,
              padding: "10px 12px",
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "#888780",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                marginBottom: 6,
              }}
            >
              Columns in {selectedFile.file_name}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {selectedFile.columns.map((c) => (
                <span
                  key={c}
                  style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: "#E6F1FB",
                    color: "#0C447C",
                    fontWeight: 500,
                  }}
                >
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}

        {selectedFile && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "#888780",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Ask about {selectedFile.file_name}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) handleAnalyze();
                }}
                placeholder="e.g. What are the top 5 products by revenue?"
                disabled={analyzing}
                style={{
                  flex: 1,
                  height: 36,
                  borderRadius: 8,
                  border: "1.5px solid #d3d1c7",
                  background: "#fff",
                  fontSize: 12,
                  padding: "0 10px",
                  fontFamily: "inherit",
                  outline: "none",
                }}
              />
              <button
                onClick={handleAnalyze}
                disabled={!prompt.trim() || analyzing}
                style={{
                  height: 36,
                  padding: "0 14px",
                  borderRadius: 8,
                  border: "none",
                  background:
                    prompt.trim() && !analyzing ? "#185FA5" : "#d3d1c7",
                  color: "#fff",
                  fontSize: 12,
                  fontWeight: 500,
                  cursor:
                    prompt.trim() && !analyzing ? "pointer" : "not-allowed",
                  fontFamily: "inherit",
                  flexShrink: 0,
                }}
              >
                {analyzing ? (
                  <div
                    style={{
                      width: 14,
                      height: 14,
                      border: "2px solid rgba(255,255,255,0.3)",
                      borderTopColor: "#fff",
                      borderRadius: "50%",
                      animation: "spin 0.65s linear infinite",
                    }}
                  />
                ) : (
                  "Analyse"
                )}
              </button>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {[
                "Summarize this data",
                "What are the key trends?",
                "Show top 5 by value",
                "Find anomalies or outliers",
                "What insights can you find?",
              ].map((s) => (
                <button
                  key={s}
                  onClick={() => setPrompt(s)}
                  style={{
                    fontSize: 10,
                    padding: "3px 8px",
                    borderRadius: 4,
                    border: "1px solid #d3d1c7",
                    background: "#f5f5f4",
                    color: "#5f5e5a",
                    cursor: "pointer",
                    fontFamily: "inherit",
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {files.length === 0 && !uploading && (
          <div
            style={{
              textAlign: "center",
              paddingTop: 8,
              fontSize: 12,
              color: "#888780",
              lineHeight: 1.8,
            }}
          >
            <div style={{ fontSize: 32, marginBottom: 8 }}>📊</div>
            Upload a CSV or Excel file to start analysing your own data with
            AI.
            <br />
            Files are cached — re-uploading the same file is instant.
          </div>
        )}
      </div>
    </div>
  );
}
