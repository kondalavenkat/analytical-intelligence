"use client";
// ChartRenderer — all recharts usage is isolated here.
// ResultBlock imports this via next/dynamic({ ssr: false }) so recharts
// is excluded from the server bundle and the initial client chunk.

import React from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const COLORS = [
  "#185FA5",
  "#378ADD",
  "#0F6E56",
  "#1D9E75",
  "#BA7517",
  "#EF9F27",
  "#993C1D",
  "#534AB7",
];

interface ChartDef {
  type: string;
  title: string;
  data: object[];
  xKey: string;
  yKey: string;
  currency: boolean;
}

export function ChartRenderer({ charts }: { charts: ChartDef[] }) {
  if (charts.length === 0) {
    return (
      <div
        style={{
          padding: "32px",
          textAlign: "center",
          color: "#888780",
          fontSize: 13,
          background: "#f5f5f4",
          borderRadius: 8,
        }}
      >
        No chart available
      </div>
    );
  }

  return (
    <div
      id="charts-section"
      style={{
        display: "grid",
        gridTemplateColumns: charts.length > 1 ? "1fr 1fr" : "1fr",
        gap: 16,
      }}
    >
      {charts.map((chart, i) => {
        const fmtTick = (v: unknown) =>
          chart.currency
            ? `$${Number(v).toLocaleString()}`
            : Number(v).toLocaleString();
        const fmtTip = (v: unknown) =>
          chart.currency
            ? `$${Number(v).toLocaleString()}`
            : String(Number(v).toLocaleString());

        return (
          <div
            key={i}
            style={{
              background: "#fff",
              border: "1px solid #e5e3dc",
              borderRadius: 12,
              padding: "18px 14px",
              boxShadow: "0 1px 4px rgba(0,0,0,0.04)",
            }}
          >
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: "#1a1a18",
                marginBottom: 14,
              }}
            >
              {chart.type === "bar"
                ? "📊 "
                : chart.type === "pie"
                ? "🥧 "
                : chart.type === "hbar"
                ? "📉 "
                : "📈 "}
              {chart.title}
            </div>
            <ResponsiveContainer width="100%" height={220}>
              {chart.type === "bar" ? (
                <BarChart
                  data={chart.data}
                  margin={{ top: 4, right: 8, left: 8, bottom: 48 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#f0ede8"
                    vertical={false}
                  />
                  <XAxis
                    dataKey={chart.xKey}
                    tick={{ fontSize: 10, fill: "#888780" }}
                    angle={-35}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#888780" }}
                    tickFormatter={fmtTick}
                    width={70}
                  />
                  <Tooltip
                    contentStyle={{
                      fontSize: 12,
                      borderRadius: 8,
                      border: "1px solid #e5e3dc",
                    }}
                    formatter={(v: unknown) => [fmtTip(v), chart.yKey]}
                  />
                  <Bar dataKey={chart.yKey} radius={[4, 4, 0, 0]}>
                    {chart.data.map((_, idx) => (
                      <Cell
                        key={idx}
                        fill={COLORS[idx % COLORS.length]}
                      />
                    ))}
                  </Bar>
                </BarChart>
              ) : chart.type === "hbar" ? (
                <BarChart
                  layout="vertical"
                  data={chart.data}
                  margin={{ top: 4, right: 40, left: 8, bottom: 4 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#f0ede8"
                    horizontal={false}
                  />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 10, fill: "#888780" }}
                    tickFormatter={fmtTick}
                  />
                  <YAxis
                    type="category"
                    dataKey={chart.xKey}
                    tick={{ fontSize: 10, fill: "#888780" }}
                    width={100}
                  />
                  <Tooltip
                    contentStyle={{
                      fontSize: 12,
                      borderRadius: 8,
                      border: "1px solid #e5e3dc",
                    }}
                    formatter={(v: unknown) => [fmtTip(v), chart.yKey]}
                  />
                  <Bar dataKey={chart.yKey} radius={[0, 4, 4, 0]}>
                    {chart.data.map((_, idx) => (
                      <Cell
                        key={idx}
                        fill={COLORS[idx % COLORS.length]}
                      />
                    ))}
                  </Bar>
                </BarChart>
              ) : chart.type === "line" ? (
                <LineChart
                  data={chart.data}
                  margin={{ top: 4, right: 8, left: 8, bottom: 48 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#f0ede8"
                    vertical={false}
                  />
                  <XAxis
                    dataKey={chart.xKey}
                    tick={{ fontSize: 10, fill: "#888780" }}
                    angle={-35}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#888780" }}
                    tickFormatter={fmtTick}
                    width={70}
                  />
                  <Tooltip
                    contentStyle={{
                      fontSize: 12,
                      borderRadius: 8,
                      border: "1px solid #e5e3dc",
                    }}
                    formatter={(v: unknown) => [fmtTip(v), chart.yKey]}
                  />
                  <Line
                    type="monotone"
                    dataKey={chart.yKey}
                    stroke="#E74C3C"
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: "#E74C3C" }}
                  />
                </LineChart>
              ) : (
                <PieChart>
                  <Pie
                    data={chart.data}
                    dataKey={chart.yKey}
                    nameKey={chart.xKey}
                    cx="50%"
                    cy="50%"
                    outerRadius={85}
                    innerRadius={30}
                    label={({ name, percent }) =>
                      `${String(name).slice(0, 12)} ${(percent * 100).toFixed(0)}%`
                    }
                    labelLine
                  >
                    {chart.data.map((_, idx) => (
                      <Cell
                        key={idx}
                        fill={COLORS[idx % COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      fontSize: 12,
                      borderRadius: 8,
                      border: "1px solid #e5e3dc",
                    }}
                    formatter={(v: unknown) => [fmtTip(v), chart.yKey]}
                  />
                  <Legend iconSize={10} wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              )}
            </ResponsiveContainer>
          </div>
        );
      })}
    </div>
  );
}
