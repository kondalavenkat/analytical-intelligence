"use client";
import React from "react";
import type { QueryResult } from "@/lib/api";

function truncate(s: string, n = 40) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

export function ShareModal({
  result,
  question,
  onClose,
}: {
  result: QueryResult;
  question: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = React.useState(false);
  const [teamsCopied, setTeamsCopied] = React.useState(false);
  const subject = encodeURIComponent("SQL Analyst: " + question.slice(0, 60));
  const plainText = [
    "📊 SQL Analyst Report",
    "",
    "Question: " + question,
    "Result: " +
      result.row_count.toLocaleString() +
      " rows × " +
      result.columns.length +
      " columns",
    "Source: " + (result.source === "cache" ? "Cache Hit" : "AI Generated"),
    "",
    result.sql_query ? "SQL Query:\n" + result.sql_query : "",
    "",
    result.analysis
      ? "Insights:\n" +
        result.analysis.replace(/`/g, "").replace(/\*\*/g, "").trim()
      : "",
  ]
    .filter(Boolean)
    .join("\n");
  const encodedBody = encodeURIComponent(plainText);

  const shareViaOutlook = () => {
    window.location.href = "mailto:?subject=" + subject + "&body=" + encodedBody;
  };

  const shareViaTeams = () => {
    const msg =
      "📊 SQL Analyst Report\n\nQuestion: " +
      question +
      "\n\nResult: " +
      result.row_count.toLocaleString() +
      " rows × " +
      result.columns.length +
      " columns" +
      (result.sql_query
        ? "\n\nSQL Query:\n" + result.sql_query.slice(0, 400)
        : "") +
      (result.analysis
        ? "\n\nInsights:\n" +
          result.analysis
            .replace(/`{3}[\s\S]*?`{3}/g, "")
            .replace(/\*{2}(.*?)\*{2}/g, "$1")
            .trim()
            .slice(0, 600)
        : "");
    navigator.clipboard.writeText(msg).then(() => {
      setTeamsCopied(true);
      const a = document.createElement("a");
      a.href = "msteams://";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => {
        if (!document.hidden) window.open("https://teams.microsoft.com", "_blank");
      }, 1000);
      setTimeout(() => setTeamsCopied(false), 4000);
    });
  };

  const copyToClipboard = () => {
    navigator.clipboard
      .writeText(plainText)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        background: "rgba(0,0,0,0.4)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 16,
          padding: 28,
          width: 420,
          boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 20,
          }}
        >
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#1a1a18" }}>
              Share Result
            </div>
            <div style={{ fontSize: 12, color: "#888780", marginTop: 2 }}>
              {truncate(question, 50)}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "#888780",
              padding: 4,
              borderRadius: 6,
            }}
          >
            <svg
              width="18"
              height="18"
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

        <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
          {[
            {
              label: "Rows",
              value: result.row_count.toLocaleString(),
            },
            { label: "Columns", value: String(result.columns.length) },
            {
              label: "Source",
              value: result.source === "cache" ? "Cache Hit" : "AI",
            },
          ].map((s) => (
            <div
              key={s.label}
              style={{
                flex: 1,
                background: "#f5f5f4",
                borderRadius: 8,
                padding: "8px 10px",
                textAlign: "center",
              }}
            >
              <div
                style={{
                  fontSize: 9,
                  color: "#888780",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                {s.label}
              </div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: "#185FA5",
                  marginTop: 2,
                }}
              >
                {s.value}
              </div>
            </div>
          ))}
        </div>

        <div
          style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}
        >
          {/* Teams */}
          <button
            onClick={shareViaTeams}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "14px 16px",
              borderRadius: 10,
              border: teamsCopied ? "1.5px solid #6264A7" : "1.5px solid #e5e3dc",
              background: teamsCopied ? "#f0f0fa" : "#fff",
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "all 0.15s",
            }}
          >
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
              <rect
                width="32"
                height="32"
                rx="8"
                fill={teamsCopied ? "#27a060" : "#6264A7"}
              />
              {teamsCopied ? (
                <polyline
                  points="8 17 13 22 24 11"
                  stroke="white"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                />
              ) : (
                <text
                  x="16"
                  y="22"
                  textAnchor="middle"
                  fill="white"
                  fontSize="14"
                  fontWeight="bold"
                  fontFamily="sans-serif"
                >
                  T
                </text>
              )}
            </svg>
            <div style={{ textAlign: "left" }}>
              {teamsCopied ? (
                <>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#27a060" }}>
                    Copied! Teams is opening…
                  </div>
                  <div style={{ fontSize: 11, color: "#6264A7", fontWeight: 500 }}>
                    Press{" "}
                    <kbd
                      style={{
                        background: "#e8e8f5",
                        border: "1px solid #c0c0e0",
                        borderRadius: 3,
                        padding: "1px 5px",
                        fontSize: 10,
                        fontFamily: "monospace",
                      }}
                    >
                      Ctrl+V
                    </kbd>{" "}
                    in any Teams chat
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#1a1a18" }}>
                    Microsoft Teams
                  </div>
                  <div style={{ fontSize: 11, color: "#888780" }}>
                    Copies report + opens Teams — press Ctrl+V to paste
                  </div>
                </>
              )}
            </div>
          </button>

          {/* Outlook */}
          <button
            onClick={shareViaOutlook}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "14px 16px",
              borderRadius: 10,
              border: "1.5px solid #e5e3dc",
              background: "#fff",
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "border-color 0.15s, box-shadow 0.15s",
            }}
          >
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="8" fill="#0078D4" />
              <text
                x="16"
                y="22"
                textAnchor="middle"
                fill="white"
                fontSize="14"
                fontWeight="bold"
                fontFamily="sans-serif"
              >
                O
              </text>
            </svg>
            <div style={{ textAlign: "left" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#1a1a18" }}>
                Outlook / Email
              </div>
              <div style={{ fontSize: 11, color: "#888780" }}>
                Opens your default mail app with report pre-filled
              </div>
            </div>
            <svg
              style={{ marginLeft: "auto", flexShrink: 0 }}
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#888780"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
          </button>

          {/* Copy */}
          <button
            onClick={copyToClipboard}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "14px 16px",
              borderRadius: 10,
              border: "1.5px solid #e5e3dc",
              background: "#fff",
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "border-color 0.15s",
            }}
          >
            <div
              style={{
                width: 32,
                height: 32,
                background: copied ? "#EAF3DE" : "#f5f5f4",
                borderRadius: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "background 0.2s",
              }}
            >
              {copied ? (
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#27a060"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              ) : (
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#5f5e5a"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                >
                  <rect x="9" y="9" width="13" height="13" rx="2" />
                  <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                </svg>
              )}
            </div>
            <div style={{ textAlign: "left" }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: copied ? "#27a060" : "#1a1a18",
                }}
              >
                {copied ? "Copied!" : "Copy to clipboard"}
              </div>
              <div style={{ fontSize: 11, color: "#888780" }}>
                Paste into any app — Teams, Slack, Notion…
              </div>
            </div>
          </button>
        </div>

        <div
          style={{
            background: "#f5f5f4",
            borderRadius: 8,
            padding: "10px 14px",
            fontSize: 11,
            color: "#888780",
            lineHeight: 1.6,
          }}
        >
          <strong style={{ color: "#5f5e5a" }}>Includes:</strong> question,{" "}
          {result.sql_query ? "SQL query, " : ""}result summary
          {result.analysis ? ", AI insights" : ""}
        </div>
      </div>
    </div>
  );
}
