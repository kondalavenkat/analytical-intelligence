"use client";
import React from "react";
import type { Message } from "@/lib/types";
import { ResultBlock } from "@/components/charts/ResultBlock";
import { InsightBlock } from "@/components/charts/InsightBlock";
import { ShareModal } from "@/components/modals/ShareModal";
import { ActionBtn, CopyBtn } from "@/components/chat/ActionBtn";
import { ErrorCard } from "@/components/chat/ErrorCard";

function LoadingIndicator() {
  const [step, setStep] = React.useState(0);
  const steps = [
    "Analyzing request...",
    "Generating SQL query...",
    "Executing database query...",
    "Formatting results..."
  ];

  React.useEffect(() => {
    const timer = setInterval(() => {
      setStep((s) => Math.min(s + 1, steps.length - 1));
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div
      style={{
        background: "#f5f5f4",
        borderRadius: "4px 18px 18px 18px",
        padding: "10px 16px",
        display: "flex",
        gap: 10,
        alignItems: "center",
      }}
    >
      <div style={{ display: "flex", gap: 4 }}>
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: "#185FA5",
              animation: `bounce 1.2s ${i * 0.2}s infinite`,
            }}
          />
        ))}
      </div>
      <div style={{ fontSize: 13, color: "#5f5e5a", fontWeight: 500 }}>
        {steps[step]}
      </div>
    </div>
  );
}

export function MessageBubble({
  msg,
  onEdit,
  onRetry,
  onDelete,
}: {
  msg: Message;
  onEdit?: (text: string) => void;
  onRetry?: (text: string) => void;
  onDelete?: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [editText, setEditText] = React.useState(msg.content);
  const [hovered, setHovered] = React.useState(false);
  const [shareOpen, setShareOpen] = React.useState(false);

  // ── User bubble ────────────────────────────────────────────────────────────
  if (msg.role === "user") {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          marginBottom: 16,
          animation: "fadeUp 0.2s ease",
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {editing ? (
          <div style={{ maxWidth: "72%", width: "100%" }}>
            <textarea
              autoFocus
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (editText.trim() && onRetry) {
                    onRetry(editText.trim());
                    setEditing(false);
                  }
                }
                if (e.key === "Escape") {
                  setEditing(false);
                  setEditText(msg.content);
                }
              }}
              style={{
                width: "100%",
                padding: "10px 14px",
                fontSize: 14,
                lineHeight: 1.5,
                borderRadius: "12px 12px 4px 12px",
                border: "2px solid #185FA5",
                background: "#E6F1FB",
                color: "#1a1a18",
                fontFamily: "inherit",
                resize: "none",
                outline: "none",
                minHeight: 60,
              }}
            />
            <div
              style={{
                display: "flex",
                gap: 6,
                justifyContent: "flex-end",
                marginTop: 6,
              }}
            >
              <button
                onClick={() => {
                  setEditing(false);
                  setEditText(msg.content);
                }}
                style={{
                  padding: "5px 12px",
                  borderRadius: 6,
                  border: "1px solid #d3d1c7",
                  background: "#fff",
                  fontSize: 12,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  color: "#5f5e5a",
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (editText.trim() && onRetry) {
                    onRetry(editText.trim());
                    setEditing(false);
                  }
                }}
                style={{
                  padding: "5px 12px",
                  borderRadius: 6,
                  border: "none",
                  background: "#185FA5",
                  color: "#fff",
                  fontSize: 12,
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                Send
              </button>
            </div>
          </div>
        ) : (
          <div
            style={{
              maxWidth: "70%",
              background: "#185FA5",
              color: "#E6F1FB",
              borderRadius: "18px 18px 4px 18px",
              padding: "10px 16px",
              fontSize: 14,
              lineHeight: 1.5,
            }}
          >
            {msg.content}
          </div>
        )}
        {!editing && hovered && (
          <div style={{ display: "flex", gap: 2, marginTop: 4 }}>
            <ActionBtn
              title="Edit and resend"
              onClick={() => {
                setEditing(true);
                setEditText(msg.content);
              }}
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Edit
            </ActionBtn>
            <ActionBtn title="Retry this query" onClick={() => onRetry?.(msg.content)}>
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="1 4 1 10 7 10" />
                <path d="M3.51 15a9 9 0 102.13-9.36L1 10" />
              </svg>
              Retry
            </ActionBtn>
            <CopyBtn text={msg.content} />
            {onDelete && (
              <ActionBtn title="Delete this message" onClick={onDelete}>
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3 6h18" />
                  <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                </svg>
                Delete
              </ActionBtn>
            )}
          </div>
        )}
      </div>
    );
  }

  // ── Loading bubble ─────────────────────────────────────────────────────────
  if (msg.loading) {
    return (
      <div
        style={{
          display: "flex",
          gap: 10,
          marginBottom: 16,
          alignItems: "flex-start",
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            background: "#042C53",
            borderRadius: "50%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#E6F1FB"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <ellipse cx="12" cy="12" rx="10" ry="10" />
            <path d="M12 6v6l4 2" />
          </svg>
        </div>
        <LoadingIndicator />
      </div>
    );
  }

  // ── Assistant bubble ───────────────────────────────────────────────────────
  const copyText = [
    msg.content,
    msg.result?.sql_query ? `\nSQL:\n${msg.result.sql_query}` : "",
    msg.result?.analysis ? `\nInsights:\n${msg.result.analysis}` : "",
  ].join("");

  return (
    <>
      {shareOpen && msg.result && (
        <ShareModal
          result={msg.result}
          question={msg.result.question || msg.content}
          onClose={() => setShareOpen(false)}
        />
      )}
      <div
        style={{
          display: "flex",
          gap: 10,
          marginBottom: 20,
          alignItems: "flex-start",
          animation: "fadeUp 0.2s ease",
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div
          style={{
            width: 28,
            height: 28,
            background: "#042C53",
            borderRadius: "50%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            marginTop: 2,
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#E6F1FB"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
            <circle cx="17.5" cy="17.5" r="3.5" />
            <line x1="17.5" y1="15.5" x2="17.5" y2="19.5" />
            <line x1="15.5" y1="17.5" x2="19.5" y2="17.5" />
          </svg>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              background: "#f5f5f4",
              borderRadius: "4px 18px 18px 18px",
              padding: "12px 16px",
              fontSize: 14,
              color: "#1a1a18",
              lineHeight: 1.6,
              marginBottom: msg.result ? 4 : 0,
            }}
          >
            {msg.content}
          </div>
          {msg.result && (
            <div style={{ marginTop: 6 }}>
              {(msg.result.sql_query || (msg.result.columns && msg.result.columns.length > 0)) && (
                <ResultBlock result={msg.result} />
              )}
              {msg.result.analysis && (
                <InsightBlock analysis={msg.result.analysis} />
              )}
            </div>
          )}
          {msg.sources && msg.sources.length > 0 && (
            <div style={{ marginTop: 8, padding: "8px 12px", background: "#f0f2f5", borderRadius: 8, border: "1px solid #e1e4e8", fontSize: 12 }}>
              <div style={{ fontWeight: 600, color: "#185FA5", marginBottom: 4 }}>Evidence Sources:</div>
              <ul style={{ margin: 0, paddingLeft: 20, color: "#4a4c50", display: "flex", flexDirection: "column", gap: 3 }}>
                {msg.sources.map((src, i) => (
                  <li key={i}>{src}</li>
                ))}
              </ul>
            </div>
          )}
          {/* Rich error card — shown when the query failed */}
          {msg.errorInfo && (
            <ErrorCard
              info={msg.errorInfo}
              onRetry={onRetry ? (question: string) => onRetry(question) : undefined}
            />
          )}
          {hovered && (
            <div style={{ display: "flex", gap: 2, marginTop: 6 }}>
              <CopyBtn text={copyText} label="Copy response" />
              {msg.result?.sql_query && (
                <CopyBtn text={msg.result.sql_query} label="Copy SQL" />
              )}
              {msg.result && (
                <ActionBtn
                  title="Share via Teams or Outlook"
                  onClick={() => setShareOpen(true)}
                >
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <circle cx="18" cy="5" r="3" />
                    <circle cx="6" cy="12" r="3" />
                    <circle cx="18" cy="19" r="3" />
                    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                    <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                  </svg>
                  Share
                </ActionBtn>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
