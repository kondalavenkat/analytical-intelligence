"use client";
// src/components/ResultCard.tsx

import { useState } from "react";
import type { QueryResult } from "@/lib/api";

interface Props { result: QueryResult; index: number; }

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function downloadCSV(result: QueryResult) {
  const header = result.columns.join(",");
  const rows   = result.rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob   = new Blob([header + "\n" + rows], { type: "text/csv" });
  const url    = URL.createObjectURL(blob);
  const a      = document.createElement("a");
  a.href = url; a.download = `query_${result.asked_at.slice(0,19).replace(/[T:]/g,"_")}.csv`;
  a.click(); URL.revokeObjectURL(url);
}

const cell: React.CSSProperties = { padding: "8px 12px", fontSize: 13, color: "#1a1a18", borderBottom: "0.5px solid rgba(0,0,0,0.07)", whiteSpace: "nowrap", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" };
const hcell: React.CSSProperties = { ...cell, fontWeight: 600, fontSize: 11, color: "#888780", letterSpacing: "0.04em", textTransform: "uppercase", background: "#f5f5f4", borderBottom: "0.5px solid rgba(0,0,0,0.12)" };

export default function ResultCard({ result, index }: Props) {
  const [showSQL, setShowSQL]     = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);

  const isCache  = result.source === "cache";
  const timing   = result.timing;

  return (
    <div className="fade-in" style={{ background: "#fff", border: "0.5px solid rgba(0,0,0,0.09)", borderRadius: 12, marginBottom: 16, overflow: "hidden", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" }}>

      {/* Header */}
      <div style={{ padding: "14px 18px", borderBottom: "0.5px solid rgba(0,0,0,0.07)", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 11, color: "#888780", marginBottom: 3 }}>#{index + 1} · Asked at {formatTime(result.asked_at)}</div>
          <div style={{ fontSize: 15, fontWeight: 500, color: "#1a1a18" }}>💬 {result.question}</div>
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}>
          {/* Source badge */}
          <span style={{ fontSize: 11, fontWeight: 500, padding: "3px 8px", borderRadius: 4, textTransform: "uppercase", letterSpacing: "0.04em", background: isCache ? "#EAF3DE" : "#E6F1FB", color: isCache ? "#27500A" : "#0C447C", border: `0.5px solid ${isCache ? "#97C459" : "#B5D4F4"}` }}>
            {isCache ? "⚡ Cache" : "🧠 Model"}
          </span>
        </div>
      </div>

      {/* Timing metrics */}
      <div style={{ padding: "12px 18px", borderBottom: "0.5px solid rgba(0,0,0,0.07)", display: "flex", gap: 24, flexWrap: "wrap" }}>
        {isCache ? (
          <>
            <Metric label="Match type"    value={String(timing.match_type ?? "exact").charAt(0).toUpperCase() + String(timing.match_type ?? "exact").slice(1)}/>
            <Metric label="Similarity"    value={`${(Number(timing.similarity ?? 1) * 100).toFixed(1)}%`}/>
            <Metric label="Lookup"        value={`${Number(timing.cache_lookup_ms ?? timing.cache_ms ?? 0).toFixed(1)} ms`}/>
            <Metric label="SQL Re-run"    value={`${Number(timing.sql_rerun_ms ?? 0).toFixed(1)} ms`}/>
            <Metric label="Total cached"  value={`${Number(timing.cached_exec_ms ?? timing.cache_ms ?? 0).toFixed(1)} ms`}/>
            <Metric label="Speedup vs AI" value={`${Math.max(0, Number(timing.first_exec_ms ?? 0) - Number(timing.cached_exec_ms ?? timing.cache_ms ?? 0)).toFixed(0)} ms`}/>
            <Metric label="Hit count"     value={String(Number(timing.hit_count ?? 0) + 1)}/>
          </>
        ) : (
          <Metric label="Model time" value={`${Number(timing.model_ms ?? 0).toFixed(0)} ms`}/>
        )}
        {isCache && timing.matched_question && timing.match_type === "semantic" && (
          <div style={{ width: "100%", fontSize: 12, color: "#5f5e5a", marginTop: -8 }}>
            Matched: <em>"{timing.matched_question}"</em>
          </div>
        )}
      </div>

      {/* Results table */}
      <div style={{ padding: "14px 18px" }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "#1a1a18", marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span>📊 Results <span style={{ fontWeight: 400, color: "#888780", fontSize: 12 }}>· {result.row_count.toLocaleString()} rows × {result.columns.length} cols · completed {formatTime(result.completed_at)}</span></span>
          {result.row_count > 0 && (
            <button onClick={() => downloadCSV(result)}
              style={{ fontSize: 12, color: "#185FA5", background: "none", border: "0.5px solid rgba(24,95,165,0.3)", borderRadius: 6, padding: "4px 10px", cursor: "pointer", fontFamily: "inherit" }}>
              📥 CSV
            </button>
          )}
        </div>

        {result.row_count > 0 ? (
          <div style={{ overflowX: "auto", borderRadius: 8, border: "0.5px solid rgba(0,0,0,0.09)" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 400 }}>
              <thead>
                <tr>{result.columns.map(c => <th key={c} style={hcell}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {result.rows.slice(0, 100).map((row, ri) => (
                  <tr key={ri} style={{ background: ri % 2 === 0 ? "#fff" : "#fafaf9" }}>
                    {(row as unknown[]).map((v, ci) => <td key={ci} style={cell}>{String(v ?? "")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            {result.row_count > 100 && (
              <div style={{ padding: "8px 12px", fontSize: 12, color: "#888780", background: "#f5f5f4", borderTop: "0.5px solid rgba(0,0,0,0.07)" }}>
                Showing 100 of {result.row_count.toLocaleString()} rows — download CSV for full results
              </div>
            )}
          </div>
        ) : (
          <div style={{ fontSize: 13, color: "#888780", padding: "16px 0" }}>Query returned no results.</div>
        )}

        {/* SQL toggle */}
        <button onClick={() => setShowSQL(v => !v)}
          style={{ marginTop: 12, fontSize: 12, color: "#5f5e5a", background: "none", border: "0.5px solid rgba(0,0,0,0.14)", borderRadius: 6, padding: "5px 10px", cursor: "pointer", fontFamily: "inherit" }}>
          {showSQL ? "▲ Hide SQL" : "▼ Show SQL"}
        </button>

        {showSQL && (
          <pre style={{ marginTop: 10, background: "#1a1a18", color: "#B5D4F4", borderRadius: 8, padding: "14px 16px", fontSize: 12, overflowX: "auto", lineHeight: 1.6, fontFamily: "'IBM Plex Mono', monospace" }}>
            {result.sql_query}
          </pre>
        )}

        {/* Analysis toggle */}
        {result.analysis && (
          <>
            <button onClick={() => setShowAnalysis(v => !v)}
              style={{ marginTop: 8, fontSize: 12, color: "#5f5e5a", background: "none", border: "0.5px solid rgba(0,0,0,0.14)", borderRadius: 6, padding: "5px 10px", cursor: "pointer", fontFamily: "inherit" }}>
              {showAnalysis ? "▲ Hide AI insights" : "▼ Show AI insights"}
            </button>
            {showAnalysis && (
              <div style={{ marginTop: 10, background: "#f5f5f4", borderRadius: 8, padding: "14px 16px", fontSize: 13, color: "#1a1a18", lineHeight: 1.7 }}>
                {result.analysis}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "#888780", letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: "#1a1a18", fontFamily: "'IBM Plex Mono', monospace" }}>{value}</div>
    </div>
  );
}