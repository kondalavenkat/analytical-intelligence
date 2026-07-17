"use client";
import React, { useState } from "react";
import dynamic from "next/dynamic";
import type { QueryResult } from "@/lib/api";
import { downloadCSV } from "@/lib/csv";

// ── Lazy-load recharts — excluded from initial bundle ────────────────────────
const ChartRenderer = dynamic(
  () =>
    import("@/components/charts/ChartRenderer").then((m) => m.ChartRenderer),
  {
    ssr: false,
    loading: () => (
      <div
        style={{
          height: 220,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#888780",
          fontSize: 13,
        }}
      >
        Loading charts…
      </div>
    ),
  }
);

// ── Helpers ──────────────────────────────────────────────────────────────────
function isNumeric(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

function buildCharts(result: QueryResult) {
  const { columns, rows } = result;
  if (!rows.length) return [];
  const numCols = columns.filter((_, i) =>
    rows.slice(0, 8).every((r) => isNumeric((r as unknown[])[i]))
  );
  const strCols = columns.filter((_, i) =>
    rows.slice(0, 8).some((r) => !isNumeric((r as unknown[])[i]))
  );
  const dateCols = columns.filter((c) =>
    /date|time|month|year|period/i.test(c)
  );
  const isCurrency = (k: string) =>
    /total|revenue|sales|amount|price|cost/i.test(k);
  type C = {
    type: string;
    title: string;
    data: object[];
    xKey: string;
    yKey: string;
    currency: boolean;
  };
  const charts: C[] = [];
  if (strCols.length && numCols.length) {
    const xKey = strCols[0],
      yKey = numCols[0],
      xi = columns.indexOf(xKey),
      yi = columns.indexOf(yKey);
    const data = rows
      .slice(0, 12)
      .map((r) => ({
        [xKey]: String((r as unknown[])[xi] ?? "").slice(0, 20),
        [yKey]: Number((r as unknown[])[yi]) || 0,
      }));
    charts.push({
      type: "bar",
      title: `Top ${xKey} by ${yKey}`,
      data,
      xKey,
      yKey,
      currency: isCurrency(yKey),
    });
    if (rows.length >= 3)
      charts.push({
        type: "pie",
        title: `${yKey} by ${xKey}`,
        data: data.slice(0, 8),
        xKey,
        yKey,
        currency: isCurrency(yKey),
      });
    if (data.length >= 4)
      charts.push({
        type: "hbar",
        title: `Horizontal: ${yKey} by ${xKey}`,
        data: [...data].reverse(),
        xKey,
        yKey,
        currency: isCurrency(yKey),
      });
  }
  if (dateCols.length && numCols.length) {
    const xKey = dateCols[0],
      yKey = numCols[0],
      xi = columns.indexOf(xKey),
      yi = columns.indexOf(yKey);
    charts.push({
      type: "line",
      title: `Trend: ${yKey} over time`,
      data: rows
        .slice(0, 24)
        .map((r) => ({
          [xKey]: String((r as unknown[])[xi] ?? "").slice(0, 10),
          [yKey]: Number((r as unknown[])[yi]) || 0,
        })),
      xKey,
      yKey,
      currency: isCurrency(yKey),
    });
  }
  return charts;
}

// ── ResultBlock ───────────────────────────────────────────────────────────────
export function ResultBlock({ result }: { result: QueryResult }) {
  const [tab, setTab] = useState<"table" | "charts" | "sql">("table");
  const charts = buildCharts(result);
  const isCache = result.source === "cache";
  const timing = result.timing;

  const handleDownloadPDF = async () => {
    const { downloadPDF } = await import("@/lib/pdf");
    await downloadPDF(result);
  };

  return (
    <div style={{ marginTop: 12 }}>
      {/* Meta row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 10,
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            padding: "3px 9px",
            borderRadius: 20,
            background: isCache ? "#EAF3DE" : "#E6F1FB",
            color: isCache ? "#27500A" : "#0C447C",
            border: `1px solid ${isCache ? "#97C459" : "#B5D4F4"}`,
          }}
        >
          {isCache ? "⚡ Cache hit" : "🧠 AI generated"}
        </span>
        {isCache && (
          <span style={{ fontSize: 11, color: "#888780" }}>
            {String(timing.match_type) === "semantic"
              ? `Semantic (${(Number(timing.similarity) * 100).toFixed(0)}%)`
              : "Exact"}{" "}
            · {Number(timing.cache_ms ?? 0).toFixed(0)} ms
            {timing.first_exec_ms ? ` (orig. ${Number(timing.first_exec_ms).toFixed(0)} ms)` : ""}
          </span>
        )}
        {!isCache && (
          <span style={{ fontSize: 11, color: "#888780" }}>
            {Number(timing.model_ms).toFixed(0)} ms
          </span>
        )}
        <span style={{ fontSize: 11, color: "#888780", marginLeft: "auto" }}>
          {result.row_count.toLocaleString()} rows × {result.columns.length} cols
        </span>
      </div>

      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          gap: 2,
          marginBottom: 12,
          borderBottom: "1px solid #e5e3dc",
          alignItems: "center",
        }}
      >
        {(["table", "charts", "sql"] as const)
          .filter((t) => t !== "sql" || result.sql_query)
          .map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: tab === t ? 600 : 400,
                color: tab === t ? "#185FA5" : "#888780",
                background: "none",
                border: "none",
                cursor: "pointer",
                borderBottom: tab === t ? "2px solid #185FA5" : "2px solid transparent",
                fontFamily: "inherit",
              }}
            >
              {t === "table"
                ? "📊 Results"
                : t === "charts"
                ? `📈 Charts (${charts.length})`
                : "🔍 SQL"}
            </button>
          ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button
            onClick={() => downloadCSV(result)}
            style={{
              padding: "5px 10px",
              fontSize: 11,
              borderRadius: 6,
              border: "1px solid #d3d1c7",
              background: "#f5f5f4",
              color: "#5f5e5a",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            ↓ CSV
          </button>
          <button
            onClick={handleDownloadPDF}
            title={
              tab === "charts"
                ? "Export PDF with charts"
                : "Switch to Charts tab first to include charts"
            }
            style={{
              padding: "5px 10px",
              fontSize: 11,
              borderRadius: 6,
              border: "1px solid #d3d1c7",
              background: "#f5f5f4",
              color: "#5f5e5a",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            ↓ PDF{tab === "charts" ? " ✓" : ""}
          </button>
        </div>
      </div>

      {/* Table */}
      {tab === "table" && (
        <div
          style={{
            overflowX: "auto",
            borderRadius: 8,
            border: "1px solid #e5e3dc",
            maxHeight: 340,
            overflowY: "auto",
          }}
        >
          <table
            style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}
          >
            <thead style={{ position: "sticky", top: 0 }}>
              <tr>
                {result.columns.map((c) => (
                  <th
                    key={c}
                    style={{
                      padding: "8px 12px",
                      textAlign: "left",
                      fontWeight: 600,
                      fontSize: 11,
                      color: "#888780",
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                      background: "#f5f5f4",
                      borderBottom: "1px solid #e5e3dc",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.length === 0 && result.row_count > 0 ? (
                <tr>
                  <td
                    colSpan={Math.max(1, result.columns.length)}
                    style={{
                      padding: "24px 12px",
                      fontSize: 13,
                      color: "#888780",
                      textAlign: "center",
                    }}
                  >
                    Data is not stored in history to save space.<br />
                    Click <strong>Retry</strong> on the message above to re-run the query and view the results.
                  </td>
                </tr>
              ) : (
                result.rows.slice(0, 100).map((row, ri) => (
                  <tr
                    key={ri}
                    style={{ background: ri % 2 === 0 ? "#fff" : "#fafaf9" }}
                  >
                    {(row as unknown[]).map((v, ci) => (
                      <td
                        key={ci}
                        style={{
                          padding: "7px 12px",
                          fontSize: 13,
                          color: "#1a1a18",
                          borderBottom: "1px solid #f0ede8",
                          whiteSpace: "nowrap",
                          maxWidth: 200,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {String(v ?? "")}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {result.row_count > 100 && (
            <div
              style={{
                padding: "8px 12px",
                fontSize: 11,
                color: "#888780",
                background: "#f5f5f4",
                borderTop: "1px solid #e5e3dc",
              }}
            >
              Showing 100 of {result.row_count.toLocaleString()} rows
            </div>
          )}
        </div>
      )}

      {/* Charts — lazy loaded */}
      {tab === "charts" && <ChartRenderer charts={charts} />}

      {/* SQL */}
      {tab === "sql" && (
        <pre
          style={{
            background: "#1a1a18",
            color: "#B5D4F4",
            borderRadius: 8,
            padding: "14px 16px",
            fontSize: 12,
            overflowX: "auto",
            lineHeight: 1.7,
            fontFamily: "'IBM Plex Mono',monospace",
            margin: 0,
          }}
        >
          {result.sql_query}
        </pre>
      )}
    </div>
  );
}
