// src/lib/csv.ts — lightweight CSV export helper (no heavy deps)

import type { QueryResult } from "@/lib/api";

export function downloadCSV(result: QueryResult) {
  const header = result.columns.join(",");
  const rows = result.rows
    .map((r) =>
      (r as unknown[])
        .map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`)
        .join(",")
    )
    .join("\n");
  const blob = new Blob([header + "\n" + rows], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `query_${Date.now()}.csv`;
  a.click();
}
