"use client";
import React from "react";

interface InsightSection {
  label: string;
  icon: string;
  color: string;
  bg: string;
  border: string;
  items: string[];
}

export function InsightBlock({ analysis }: { analysis: string }) {
  const cleaned = analysis
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`[^`]*`/g, "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .trim();

  const summaryMatch = cleaned.match(
    /SUMMARY:\s*(.+?)(?=\n\n|KEY FINDINGS|$)/si
  );
  const findingsMatch = cleaned.match(
    /KEY FINDINGS:\s*([\s\S]+?)(?=\n\nOPPORTUNITIES|\n\nRISK FLAGS|$)/si
  );
  const oppsMatch = cleaned.match(
    /OPPORTUNITIES:\s*([\s\S]+?)(?=\n\nRISK FLAGS|$)/si
  );
  const risksMatch = cleaned.match(/RISK FLAGS:\s*([\s\S]+?)$/si);

  const parseItems = (t: string) =>
    t
      .split("\n")
      .map((l) =>
        l
          .trim()
          .replace(/^\d+\.\s*/, "")
          .trim()
      )
      .filter((l) => l.length > 10);

  const sections: InsightSection[] = [];
  if (findingsMatch)
    sections.push({
      label: "Key findings",
      icon: "📊",
      color: "#0C447C",
      bg: "#E6F1FB",
      border: "#B5D4F4",
      items: parseItems(findingsMatch[1]),
    });
  if (oppsMatch)
    sections.push({
      label: "Opportunities",
      icon: "🚀",
      color: "#27500A",
      bg: "#EAF3DE",
      border: "#97C459",
      items: parseItems(oppsMatch[1]),
    });
  if (risksMatch)
    sections.push({
      label: "Risk flags",
      icon: "⚠️",
      color: "#633806",
      bg: "#FAEEDA",
      border: "#FAC775",
      items: parseItems(risksMatch[1]),
    });

  const fallback =
    sections.length === 0
      ? cleaned
          .split("\n")
          .map((l) =>
            l
              .trim()
              .replace(/^\d+\.\s*/, "")
              .trim()
          )
          .filter((l) => l.length > 10)
      : [];

  return (
    <div style={{ marginTop: 12 }}>
      {summaryMatch && (
        <div
          style={{
            background: "#042C53",
            color: "#B5D4F4",
            borderRadius: "10px 10px 0 0",
            padding: "10px 16px",
            fontSize: 13,
            lineHeight: 1.5,
            fontWeight: 500,
          }}
        >
          💡 {summaryMatch[1].trim()}
        </div>
      )}
      <div
        style={{
          background: sections.length > 0 ? "#f8fbff" : "transparent",
          border: sections.length > 0 ? "1px solid #B5D4F4" : "none",
          borderRadius: summaryMatch ? "0 0 10px 10px" : 10,
          padding: sections.length > 0 ? "14px 16px" : "4px 0",
        }}
      >
        {sections.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {sections.map((sec, si) => (
              <div key={si}>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: sec.color,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    marginBottom: 8,
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                  }}
                >
                  {sec.icon} {sec.label}
                </div>
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 6 }}
                >
                  {sec.items.map((item, ii) => (
                    <div
                      key={ii}
                      style={{
                        display: "flex",
                        gap: 10,
                        alignItems: "flex-start",
                        background: sec.bg,
                        border: `1px solid ${sec.border}`,
                        borderRadius: 7,
                        padding: "8px 12px",
                      }}
                    >
                      <span
                        style={{
                          flexShrink: 0,
                          width: 20,
                          height: 20,
                          minWidth: 20,
                          background: sec.color,
                          color: "#fff",
                          borderRadius: "50%",
                          fontSize: 10,
                          fontWeight: 700,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                        }}
                      >
                        {ii + 1}
                      </span>
                      <span
                        style={{
                          fontSize: 13,
                          color: "#1a1a18",
                          lineHeight: 1.6,
                        }}
                      >
                        {item}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ whiteSpace: "pre-wrap", color: "#1a1a18", fontSize: 14, lineHeight: 1.6 }}>
            {cleaned}
          </div>
        )}
      </div>
    </div>
  );
}
