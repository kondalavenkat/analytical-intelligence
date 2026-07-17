"use client";
import React from "react";
import type { SheetInfo } from "@/lib/api";
import type { SheetPickerData } from "@/lib/types";

export function SheetPickerModal({
  data,
  onSelect,
  onClose,
  queuePosition,
}: {
  data: SheetPickerData;
  onSelect: (sheets: SheetInfo[]) => void;
  onClose: () => void;
  queuePosition?: { current: number; total: number };
}) {
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  function toggle(sheetName: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(sheetName) ? next.delete(sheetName) : next.add(sheetName);
      return next;
    });
  }

  function confirm() {
    const chosen = data.sheets.filter((s) => selected.has(s.sheet_name));
    if (chosen.length === 0) return;
    onSelect(chosen);
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        background: "rgba(0,0,0,0.45)",
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
          padding: 24,
          width: 440,
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 64px rgba(0,0,0,0.22)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            marginBottom: 16,
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#1a1a18" }}>
                📋 Select sheets to attach
              </div>
              {queuePosition && queuePosition.total > 1 && (
                <span
                  style={{
                    fontSize: 11,
                    padding: "2px 8px",
                    borderRadius: 10,
                    background: "#E6F1FB",
                    color: "#0C447C",
                    fontWeight: 600,
                  }}
                >
                  File {queuePosition.current} of {queuePosition.total}
                </span>
              )}
            </div>
            <div style={{ fontSize: 12, color: "#888780", marginTop: 3 }}>
              {data.fileName} · {data.sheets.length} sheet
              {data.sheets.length !== 1 ? "s" : ""} detected
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
              flexShrink: 0,
            }}
          >
            <svg
              width="16"
              height="16"
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

        {/* Select all / none */}
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button
            onClick={() =>
              setSelected(new Set(data.sheets.map((s) => s.sheet_name)))
            }
            style={{
              fontSize: 11,
              padding: "4px 10px",
              borderRadius: 5,
              border: "1px solid #d3d1c7",
              background: "#f5f5f4",
              color: "#5f5e5a",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Select all
          </button>
          <button
            onClick={() => setSelected(new Set())}
            style={{
              fontSize: 11,
              padding: "4px 10px",
              borderRadius: 5,
              border: "1px solid #d3d1c7",
              background: "#f5f5f4",
              color: "#5f5e5a",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Clear
          </button>
          <span
            style={{
              marginLeft: "auto",
              fontSize: 11,
              color: selected.size > 0 ? "#0C447C" : "#888780",
              fontWeight: selected.size > 0 ? 600 : 400,
              alignSelf: "center",
            }}
          >
            {selected.size} of {data.sheets.length} selected
          </span>
        </div>

        {/* Sheet list */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            marginBottom: 16,
          }}
        >
          {data.sheets.map((s, idx) => {
            const isSelected = selected.has(s.sheet_name);
            return (
              <label
                key={s.sheet_name ?? `sheet-${idx}`}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "12px 14px",
                  borderRadius: 9,
                  cursor: "pointer",
                  border: isSelected
                    ? "1.5px solid #185FA5"
                    : "1.5px solid #e5e3dc",
                  background: isSelected ? "#E6F1FB" : "#fafaf9",
                  transition: "all 0.12s",
                }}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggle(s.sheet_name)}
                  style={{
                    accentColor: "#185FA5",
                    width: 15,
                    height: 15,
                    marginTop: 2,
                    flexShrink: 0,
                  }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: "#1a1a18",
                      marginBottom: 2,
                    }}
                  >
                    📋 {s.sheet_name}
                  </div>
                  <div style={{ fontSize: 11, color: "#888780" }}>
                    {s.row_count?.toLocaleString()} rows · {s.col_count} columns
                  </div>
                  {s.columns && s.columns.length > 0 && (
                    <div
                      style={{
                        fontSize: 10,
                        color: "#888780",
                        marginTop: 4,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {s.columns.slice(0, 6).join(", ")}
                      {s.columns.length > 6
                        ? ` … +${s.columns.length - 6} more`
                        : ""}
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            onClick={onClose}
            style={{
              padding: "9px 18px",
              borderRadius: 8,
              border: "1px solid #d3d1c7",
              background: "#fff",
              fontSize: 13,
              cursor: "pointer",
              fontFamily: "inherit",
              color: "#5f5e5a",
            }}
          >
            {queuePosition && queuePosition.total > 1
              ? "Skip this file"
              : "Cancel"}
          </button>
          <button
            onClick={confirm}
            disabled={selected.size === 0}
            style={{
              padding: "9px 18px",
              borderRadius: 8,
              border: "none",
              background: selected.size > 0 ? "#185FA5" : "#d3d1c7",
              color: "#fff",
              fontSize: 13,
              fontWeight: 600,
              cursor: selected.size > 0 ? "pointer" : "not-allowed",
              fontFamily: "inherit",
            }}
          >
            {queuePosition && queuePosition.total > 1
              ? `Attach ${selected.size} sheet${selected.size !== 1 ? "s" : ""} → Next`
              : `Attach ${selected.size > 0 ? selected.size + " " : ""}sheet${selected.size !== 1 ? "s" : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}
