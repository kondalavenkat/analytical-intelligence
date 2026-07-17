"use client";
import React, { useState } from "react";
import type { MessageErrorInfo } from "@/lib/types";

// ── Icon helpers ───────────────────────────────────────────────────────────────
function WarningTriangle({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
      <line x1="12" y1="9" x2="12" y2="13"/>
      <line x1="12" y1="17" x2="12.01" y2="17"/>
    </svg>
  );
}

function DatabaseIcon({ size = 14, color = "#7C1C1C" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3"/>
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
    </svg>
  );
}

function RetryIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="1 4 1 10 7 10"/>
      <path d="M3.51 15a9 9 0 102.13-9.36L1 10"/>
    </svg>
  );
}

function ChevronDown({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9"/>
    </svg>
  );
}

function ChevronUp({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="18 15 12 9 6 15"/>
    </svg>
  );
}

// ── Error type metadata ────────────────────────────────────────────────────────
const ERROR_META: Record<string, { title: string; icon: React.ReactNode; badge: string }> = {
  SQL_EXECUTION: { title: "SQL Execution Error",   icon: <DatabaseIcon color="#7C1C1C" />, badge: "SQL_EXECUTION" },
  SQL_SYNTAX:    { title: "SQL Syntax Error",       icon: <DatabaseIcon color="#7C1C1C" />, badge: "SQL_SYNTAX"    },
  PERMISSION:    { title: "Permission Denied",      icon: <DatabaseIcon color="#4C1D95" />, badge: "PERMISSION"    },
  TIMEOUT:       { title: "Query Timeout",          icon: <DatabaseIcon color="#92400E" />, badge: "TIMEOUT"       },
  NETWORK:       { title: "Connection Error",       icon: <DatabaseIcon color="#1E3A8A" />, badge: "NETWORK"       },
  AI_PROVIDER:   { title: "AI Provider Error",      icon: <DatabaseIcon color="#1E3A8A" />, badge: "AI_PROVIDER"   },
  UNKNOWN:       { title: "Query Error",            icon: <DatabaseIcon color="#374151" />, badge: "UNKNOWN"       },
};

// ── Classify error type from message string ────────────────────────────────────
function classifyError(msg: string): { type: string; rootCause: string } {
  const m = msg.toLowerCase();
  if (m.includes("invalid object name") || m.includes("invalid column name")) {
    const match = msg.match(/['"]([^'"]+)['"]/);
    const ref   = match ? match[1] : "a table or column";
    return {
      type: "SQL_EXECUTION",
      rootCause: `The AI generated SQL that referenced a non-existent column or table: '${ref}'. An automatic fix was attempted but also failed. Try rephrasing your question using exact column names.`,
    };
  }
  if (m.includes("syntax error") || m.includes("incorrect syntax")) {
    return {
      type: "SQL_SYNTAX",
      rootCause: "The generated SQL contains a syntax error. This can happen with complex queries. Try simplifying your question or adding more context.",
    };
  }
  if (m.includes("permission") || m.includes("access denied") || m.includes("unauthorized")) {
    return {
      type: "PERMISSION",
      rootCause: "You do not have permission to access the requested data. Contact your database administrator.",
    };
  }
  if (m.includes("timeout") || m.includes("timed out")) {
    return {
      type: "TIMEOUT",
      rootCause: "The query took too long to execute. Try narrowing your question (e.g., add a date range or TOP N limit).",
    };
  }
  if (m.includes("connection") || m.includes("network") || m.includes("unreachable")) {
    return {
      type: "NETWORK",
      rootCause: "Could not reach the database server. Check your connection settings and try again.",
    };
  }
  if (m.includes("api") || m.includes("openai") || m.includes("gemini") || m.includes("ollama")) {
    return {
      type: "AI_PROVIDER",
      rootCause: "The AI provider returned an error. Check your API key or model selection, then retry.",
    };
  }
  return {
    type: "UNKNOWN",
    rootCause: "An unexpected error occurred. Please try again or rephrase your question.",
  };
}

// ── Hint text per error type ───────────────────────────────────────────────────
function hintFor(type: string): string {
  switch (type) {
    case "SQL_EXECUTION":
    case "SQL_SYNTAX":
      return "The generated SQL was invalid. Try rephrasing, or check that the data you're asking about exists in this database.";
    case "PERMISSION":
      return "Your account does not have access to this table or schema. Contact your DB admin.";
    case "TIMEOUT":
      return "Add a TOP N limit or date filter to reduce query size.";
    case "NETWORK":
      return "Make sure your database connection is still active (reconnect if needed).";
    case "AI_PROVIDER":
      return "Check your API key and model settings in the sidebar.";
    default:
      return "If this keeps happening, try reconnecting to the database or switching AI provider.";
  }
}

// ── Theme colours per error type ───────────────────────────────────────────────
function themeFor(type: string) {
  const themes: Record<string, { cardBg: string; cardBorder: string; leftBar: string; badgeBg: string; badgeColor: string; labelColor: string; msgBg: string; msgBorder: string; msgText: string; rootText: string }> = {
    SQL_EXECUTION: { cardBg: "#FFF5F5", cardBorder: "#FECACA", leftBar: "#DC2626", badgeBg: "#1a1a18", badgeColor: "#f5f5f4", labelColor: "#B91C1C", msgBg: "#FEE2E2", msgBorder: "#FCA5A5", msgText: "#7C1C1C", rootText: "#991B1B" },
    SQL_SYNTAX:    { cardBg: "#FFFBEB", cardBorder: "#FDE68A", leftBar: "#D97706", badgeBg: "#1a1a18", badgeColor: "#f5f5f4", labelColor: "#92400E", msgBg: "#FEF3C7", msgBorder: "#FCD34D", msgText: "#78350F", rootText: "#92400E" },
    PERMISSION:    { cardBg: "#F5F3FF", cardBorder: "#C4B5FD", leftBar: "#7C3AED", badgeBg: "#1a1a18", badgeColor: "#f5f5f4", labelColor: "#4C1D95", msgBg: "#EDE9FE", msgBorder: "#C4B5FD", msgText: "#4C1D95", rootText: "#5B21B6" },
    TIMEOUT:       { cardBg: "#FFFBEB", cardBorder: "#FDE68A", leftBar: "#D97706", badgeBg: "#1a1a18", badgeColor: "#f5f5f4", labelColor: "#92400E", msgBg: "#FEF3C7", msgBorder: "#FCD34D", msgText: "#78350F", rootText: "#92400E" },
    NETWORK:       { cardBg: "#EFF6FF", cardBorder: "#BFDBFE", leftBar: "#2563EB", badgeBg: "#1a1a18", badgeColor: "#f5f5f4", labelColor: "#1E3A8A", msgBg: "#DBEAFE", msgBorder: "#93C5FD", msgText: "#1E3A8A", rootText: "#1D4ED8" },
    AI_PROVIDER:   { cardBg: "#EFF6FF", cardBorder: "#BFDBFE", leftBar: "#2563EB", badgeBg: "#1a1a18", badgeColor: "#f5f5f4", labelColor: "#1E3A8A", msgBg: "#DBEAFE", msgBorder: "#93C5FD", msgText: "#1E3A8A", rootText: "#1D4ED8" },
    UNKNOWN:       { cardBg: "#F9FAFB", cardBorder: "#E5E7EB", leftBar: "#6B7280", badgeBg: "#1a1a18", badgeColor: "#f5f5f4", labelColor: "#374151", msgBg: "#F3F4F6", msgBorder: "#D1D5DB", msgText: "#374151", rootText: "#374151" },
  };
  return themes[type] ?? themes.UNKNOWN;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main ErrorCard component
// ─────────────────────────────────────────────────────────────────────────────
interface ErrorCardProps {
  info:     MessageErrorInfo;
  onRetry?: (question: string) => void;
}

export function ErrorCard({ info, onRetry }: ErrorCardProps) {
  const [showSQL, setShowSQL] = useState(false);

  const classified = classifyError(info.message);
  const errorType  = info.error_type !== "UNKNOWN" ? info.error_type : classified.type;
  const rootCause  = info.root_cause && info.root_cause !== info.message
    ? info.root_cause
    : classified.rootCause;
  const hint   = hintFor(errorType);
  const hasSql = !!(info.sql_query);
  const meta   = ERROR_META[errorType] ?? ERROR_META.UNKNOWN;
  const t      = themeFor(errorType);

  return (
    // Outer wrapper: warning triangle on the far left + card
    <div style={{ display: "flex", gap: 10, marginTop: 6, alignItems: "flex-start", animation: "fadeUp 0.2s ease" }}>

      {/* Left warning badge */}
      <div style={{
        flexShrink: 0,
        width: 32, height: 32,
        borderRadius: "50%",
        background: t.leftBar,
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#fff",
        marginTop: 2,
        boxShadow: `0 2px 8px ${t.leftBar}55`,
      }}>
        <WarningTriangle size={15} />
      </div>

      {/* Card */}
      <div style={{
        flex: 1,
        border: `1px solid ${t.cardBorder}`,
        borderLeft: `3px solid ${t.leftBar}`,
        borderRadius: 10,
        background: t.cardBg,
        overflow: "hidden",
        fontFamily: "inherit",
      }}>

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "11px 16px",
          borderBottom: `1px solid ${t.cardBorder}`,
          gap: 8,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* DB icon in small box */}
            <span style={{
              width: 22, height: 22,
              borderRadius: 5,
              background: t.msgBg,
              border: `1px solid ${t.msgBorder}`,
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}>
              {meta.icon}
            </span>
            <span style={{ fontWeight: 700, fontSize: 14, color: t.msgText }}>
              {meta.title}
            </span>
          </div>

          {/* Dark monospace badge — matches screenshot exactly */}
          <span style={{
            fontSize: 10,
            fontWeight: 700,
            padding: "3px 9px",
            borderRadius: 5,
            letterSpacing: "0.07em",
            textTransform: "uppercase" as const,
            background: t.badgeBg,
            color: t.badgeColor,
            fontFamily: "'IBM Plex Mono', monospace",
            flexShrink: 0,
          }}>
            {meta.badge.replace(/_/g, "_")}
          </span>
        </div>

        {/* ── Body ────────────────────────────────────────────────────────── */}
        <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>

          {/* ERROR MESSAGE */}
          <div>
            <div style={{
              fontSize: 10, fontWeight: 700, color: t.labelColor,
              letterSpacing: "0.09em", marginBottom: 6, textTransform: "uppercase",
            }}>
              Error Message
            </div>
            <div style={{
              background: t.msgBg,
              border: `1px solid ${t.msgBorder}`,
              borderRadius: 6,
              padding: "9px 12px",
              fontSize: 12.5,
              color: t.msgText,
              fontFamily: "'IBM Plex Mono', monospace",
              lineHeight: 1.55,
              wordBreak: "break-word",
            }}>
              {info.message}
            </div>
          </div>

          {/* ROOT CAUSE */}
          <div>
            <div style={{
              fontSize: 10, fontWeight: 700, color: t.labelColor,
              letterSpacing: "0.09em", marginBottom: 6, textTransform: "uppercase",
            }}>
              Root Cause
            </div>
            <div style={{ fontSize: 13, color: t.rootText, lineHeight: 1.65 }}>
              {rootCause}
            </div>
          </div>

          {/* HINT BOX */}
          <div style={{
            background: "#FEFCE8",
            border: "0.5px solid #FDE047",
            borderRadius: 6,
            padding: "9px 12px",
            display: "flex",
            gap: 8,
            alignItems: "flex-start",
          }}>
            <span style={{ fontSize: 15, flexShrink: 0, marginTop: 0 }}>💡</span>
            <span style={{ fontSize: 12.5, color: "#713F12", lineHeight: 1.55 }}>{hint}</span>
          </div>

          {/* SHOW FAILED SQL */}
          {hasSql && (
            <div>
              <button
                onClick={() => setShowSQL(v => !v)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 5,
                  fontSize: 12, color: t.msgText,
                  background: "#fff", border: `1px solid ${t.msgBorder}`,
                  borderRadius: 6, padding: "5px 11px",
                  cursor: "pointer", fontFamily: "inherit", fontWeight: 500,
                  transition: "background 0.1s",
                }}
                onMouseEnter={e => (e.currentTarget.style.background = t.msgBg)}
                onMouseLeave={e => (e.currentTarget.style.background = "#fff")}
              >
                {showSQL ? <ChevronUp /> : <ChevronDown />}
                {showSQL ? "Hide failed SQL" : "Show failed SQL"}
              </button>
              {showSQL && (
                <pre style={{
                  marginTop: 8,
                  background: "#1a1a18",
                  color: "#FCA5A5",
                  borderRadius: 8,
                  padding: "12px 14px",
                  fontSize: 12,
                  overflowX: "auto",
                  lineHeight: 1.6,
                  fontFamily: "'IBM Plex Mono', monospace",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}>
                  {info.sql_query}
                </pre>
              )}
            </div>
          )}

          {/* RETRY BUTTON */}
          {onRetry && (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button
                onClick={() => onRetry(info.question ?? info.message)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 7,
                  fontSize: 13, fontWeight: 600,
                  background: t.leftBar, color: "#fff",
                  border: "none", borderRadius: 8,
                  padding: "8px 18px",
                  cursor: "pointer", fontFamily: "inherit",
                  boxShadow: `0 2px 8px ${t.leftBar}44`,
                  transition: "opacity 0.15s ease",
                }}
                onMouseEnter={e => (e.currentTarget.style.opacity = "0.88")}
                onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
              >
                <RetryIcon />
                Retry
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Helper: parse an error message string into a MessageErrorInfo ──────────────
export function parseQueryError(rawMessage: string, sqlQuery?: string): import("@/lib/types").MessageErrorInfo {
  const { type, rootCause } = classifyError(rawMessage);
  return {
    message:    rawMessage,
    error_type: type,
    root_cause: rootCause,
    sql_query:  sqlQuery,
  };
}
