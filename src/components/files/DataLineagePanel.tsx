"use client";
import React from "react";
import { fetchMetadataTables, MetadataTable } from "@/lib/api";

export function DataLineagePanel({
  onAttachFile,
  onClose,
}: {
  onAttachFile?: (file: MetadataTable) => void;
  onClose?: () => void;
} = {}) {
  const [tables, setTables] = React.useState<MetadataTable[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [refreshKey, setRefreshKey] = React.useState(0);

  React.useEffect(() => {
    setLoading(true);
    setError("");
    fetchMetadataTables()
      .then((res) => setTables(res.tables))
      .catch((err: Error) => setError(err.message ?? "Failed to load lineage"))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  return (
    <div style={{
      background: "#fff",
      height: "100%",
      display: "flex",
      flexDirection: "column",
      borderLeft: "1px solid #e5e3dc",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 24px", borderBottom: "1px solid #e5e3dc" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#1a1a18", flex: 1 }}>🔗 Data Lineage &amp; AI Metadata</div>
        <button
          onClick={() => setRefreshKey(k => k + 1)}
          style={{
            fontSize: 11, padding: "4px 10px", borderRadius: 5,
            border: "1px solid #d3d1c7", background: "#f5f5f4",
            color: "#5f5e5a", cursor: "pointer", fontFamily: "inherit",
          }}
        >
          ↻ Refresh
        </button>
        {onClose && (
          <button
            onClick={onClose}
            style={{
              fontSize: 11, padding: "4px 10px", borderRadius: 5,
              border: "1px solid #d3d1c7", background: "#fff",
              color: "#5f5e5a", cursor: "pointer", fontFamily: "inherit",
            }}
          >
            Close
          </button>
        )}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "16px 24px" }}>

      {/* States */}
      {loading && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#888780", fontSize: 12, padding: "8px 0" }}>
          <div style={{ width: 12, height: 12, border: "2px solid #d3d1c7", borderTopColor: "#185FA5", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
          Loading lineage data…
        </div>
      )}
      {!loading && error && (
        <div style={{ fontSize: 12, color: "#791F1F", background: "#FCEBEB", border: "1px solid #F09595", borderRadius: 6, padding: "8px 12px" }}>
          {error}
        </div>
      )}
      {!loading && !error && tables.length === 0 && (
        <div style={{ textAlign: "center", padding: "20px 0", color: "#888780" }}>
          <div style={{ fontSize: 24, marginBottom: 6 }}>📂</div>
          <div style={{ fontSize: 12 }}>No data ingested yet. Upload a file to see its AI processing trail here.</div>
        </div>
      )}

      {/* Lineage timeline */}
      {!loading && !error && tables.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {tables.map((table, tIdx) => (
            <div
              key={table.id}
              style={{
                display: "flex", gap: 12, alignItems: "flex-start",
                background: "#f9f9f8", padding: "11px 14px",
                borderRadius: 8, border: "1px solid #e5e3dc",
                animation: "fadeIn 0.3s ease forwards",
              }}
            >
              {/* Timeline indicator */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 3 }}>
                <div style={{
                  width: 12, height: 12, borderRadius: "50%", flexShrink: 0,
                  background: table.flagged ? "#FDECEA" : "#EAF3DE",
                  border: `2px solid ${table.flagged ? "#C62828" : "#639922"}`,
                }} />
                {tIdx < tables.length - 1 && (
                  <div style={{ width: 1, flex: 1, minHeight: 28, background: "#e5e3dc", marginTop: 3 }} />
                )}
              </div>

              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 6, marginBottom: 5 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#1a1a18" }}>{table.table_name}</div>
                  <div style={{ fontSize: 10, color: "#888780", marginLeft: "auto" }}>
                    {new Date(table.uploaded_at).toLocaleString()}
                  </div>
                </div>

                {/* Badges */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
                  <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "#fff", border: "1px solid #d3d1c7", color: "#5f5e5a" }}>
                    📄 {table.file_name}
                  </span>
                  {table.business_type && (
                    <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "#E6F1FB", color: "#0C447C", fontWeight: 500 }}>
                      🏷️ {table.business_type}
                    </span>
                  )}
                  {table.confidence !== null && (
                    <span style={{
                      fontSize: 10, padding: "2px 7px", borderRadius: 4, fontWeight: 500,
                      background: table.confidence >= 0.8 ? "#EAF3DE" : table.confidence >= 0.6 ? "#FFF3CD" : "#FDECEA",
                      color: table.confidence >= 0.8 ? "#27500A" : table.confidence >= 0.6 ? "#856404" : "#C62828",
                    }}>
                      🤖 {(table.confidence * 100).toFixed(0)}% confidence
                    </span>
                  )}
                  {table.flagged && (
                    <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "#FDECEA", color: "#C62828", fontWeight: 500 }}>
                      ⚠️ Flagged for review
                    </span>
                  )}
                  {!table.flagged && (
                    <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 4, background: "#EAF3DE", color: "#27500A", fontWeight: 500 }}>
                      ✅ Auto-processed
                    </span>
                  )}
                </div>

                {/* Stats */}
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ fontSize: 10, color: "#888780" }}>
                    {table.row_count?.toLocaleString() ?? "?"} rows · {table.col_count ?? "?"} columns
                    {table.columns?.length > 0 && (
                      <span> · <span style={{ fontFamily: "monospace", color: "#5f5e5a" }}>{table.columns.slice(0, 4).join(", ")}{table.columns.length > 4 ? ` +${table.columns.length - 4} more` : ""}</span></span>
                    )}
                  </div>
                  {table.file_id && onAttachFile && (
                    <button
                      onClick={() => onAttachFile(table)}
                      style={{
                        fontSize: 10, color: "#185FA5", background: "#E6F1FB", border: "1px solid #B6D4F0",
                        borderRadius: 4, padding: "2px 8px", cursor: "pointer", fontFamily: "inherit"
                      }}
                    >
                      💬 Chat
                    </button>
                  )}
                  {table.file_id && (
                    <button
                      onClick={async () => {
                        if (confirm(`Are you sure you want to delete ${table.file_name}?`)) {
                          try {
                            const { deleteFile } = await import("@/lib/api");
                            await deleteFile(table.file_id!);
                            setRefreshKey(k => k + 1);
                          } catch (err: any) {
                            alert(err.message ?? "Failed to delete file");
                          }
                        }
                      }}
                      style={{
                        fontSize: 10, color: "#791F1F", background: "#FCEBEB", border: "1px solid #F09595",
                        borderRadius: 4, padding: "2px 8px", cursor: "pointer", fontFamily: "inherit"
                      }}
                    >
                      Delete File
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      </div>
    </div>
  );
}
