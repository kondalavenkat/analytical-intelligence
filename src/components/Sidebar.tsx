"use client";
// src/components/Sidebar.tsx

import { useState } from "react";
import { connectDB, logout, type User } from "@/lib/api";
import { useRouter } from "next/navigation";

interface Props {
  user:         User;
  onConnected:  (database: string) => void;
  connected:    boolean;
  database:     string;
  provider:     string;
  setProvider:  (v: string) => void;
  model:        string;
  setModel:     (v: string) => void;
  apiKey:       string;
  setApiKey:    (v: string) => void;
  ollamaUrl:    string;
  setOllamaUrl: (v: string) => void;
  simThreshold: number;
  setSimThreshold: (v: number) => void;
}

const MODELS: Record<string, string[]> = {
  OpenAI: ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
  Gemini: ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"],
  Ollama: [],
};

const s: Record<string, React.CSSProperties> = {
  sidebar: { width: 260, background: "#fff", borderRight: "0.5px solid rgba(0,0,0,0.09)", height: "100vh", overflowY: "auto", display: "flex", flexDirection: "column", padding: "20px 16px", gap: 0 },
  brand:   { display: "flex", alignItems: "center", gap: 10, marginBottom: 24, paddingBottom: 20, borderBottom: "0.5px solid rgba(0,0,0,0.09)" },
  section: { marginBottom: 20 },
  heading: { fontSize: 10, fontWeight: 600, color: "#888780", letterSpacing: "0.07em", textTransform: "uppercase" as const, marginBottom: 10 },
  label:   { fontSize: 11, color: "#5f5e5a", marginBottom: 4, display: "block" },
  input:   { width: "100%", height: 34, borderRadius: 6, border: "0.5px solid rgba(0,0,0,0.16)", background: "#f5f5f4", color: "#1a1a18", fontSize: 13, padding: "0 10px", outline: "none", fontFamily: "inherit" },
  select:  { width: "100%", height: 34, borderRadius: 6, border: "0.5px solid rgba(0,0,0,0.16)", background: "#f5f5f4", color: "#1a1a18", fontSize: 13, padding: "0 10px", outline: "none", fontFamily: "inherit" },
  btn:     { width: "100%", height: 34, borderRadius: 6, background: "#185FA5", color: "#E6F1FB", border: "none", fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "inherit" },
  btnSec:  { width: "100%", height: 34, borderRadius: 6, background: "transparent", color: "#5f5e5a", border: "0.5px solid rgba(0,0,0,0.16)", fontSize: 13, cursor: "pointer", fontFamily: "inherit" },
  divider: { height: "0.5px", background: "rgba(0,0,0,0.09)", margin: "16px 0" },
  badge:   { fontSize: 10, fontWeight: 500, padding: "2px 7px", borderRadius: 4, letterSpacing: "0.04em", textTransform: "uppercase" as const },
  row:     { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 },
};

export default function Sidebar({ user, onConnected, connected, database, provider, setProvider, model, setModel, apiKey, setApiKey, ollamaUrl, setOllamaUrl, simThreshold, setSimThreshold }: Props) {
  const router = useRouter();
  const [server,   setServer]   = useState("");
  const [dbName,   setDbName]   = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [winAuth,  setWinAuth]  = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [connError,  setConnError]  = useState("");

  const roleBg: Record<string, string> = { Admin: "#E6F1FB", Analyst: "#EAF3DE", Viewer: "#FAEEDA" };
  const roleColor: Record<string, string> = { Admin: "#0C447C", Analyst: "#27500A", Viewer: "#633806" };

  async function handleConnect() {
    if (!server || !dbName) { setConnError("Server and database required."); return; }
    setConnecting(true); setConnError("");
    try {
      const res = await connectDB({ server, database: dbName, username: winAuth ? undefined : username, password: winAuth ? undefined : password, windows_auth: winAuth });
      onConnected(res.database);
    } catch (e: unknown) {
      setConnError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setConnecting(false);
    }
  }

  function handleLogout() {
    logout();
    router.push("/login");
  }

  return (
    <aside style={s.sidebar}>
      {/* Brand */}
      <div style={s.brand}>
        <div style={{ width: 36, height: 36, background: "#185FA5", borderRadius: 9, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#E6F1FB" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/><circle cx="17.5" cy="17.5" r="3.5"/>
            <line x1="17.5" y1="15.5" x2="17.5" y2="19.5"/><line x1="15.5" y1="17.5" x2="19.5" y2="17.5"/>
          </svg>
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#1a1a18" }}>SQL Analyst</div>
          <div style={{ fontSize: 10, color: "#888780", letterSpacing: "0.05em", textTransform: "uppercase" }}>AI-Powered</div>
        </div>
      </div>

      {/* User */}
      <div style={{ ...s.section, background: "#f5f5f4", borderRadius: 8, padding: "10px 12px" }}>
        <div style={s.row}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: "#1a1a18" }}>{user.display_name}</div>
            <div style={{ fontSize: 11, color: "#888780" }}>{user.email}</div>
          </div>
          <span style={{ ...s.badge, background: roleBg[user.role] ?? "#f5f5f4", color: roleColor[user.role] ?? "#5f5e5a" }}>{user.role}</span>
        </div>
        <button style={{ ...s.btnSec, marginTop: 8, height: 28, fontSize: 12 }} onClick={handleLogout}>Sign out</button>
      </div>

      <div style={s.divider}/>

      {/* AI Provider */}
      <div style={s.section}>
        <div style={s.heading}>AI Provider</div>
        <label style={s.label}>Provider</label>
        <select style={{ ...s.select, marginBottom: 8 }} value={provider} onChange={e => { setProvider(e.target.value); setModel(MODELS[e.target.value]?.[0] ?? ""); }}>
          <option>OpenAI</option>
          <option>Gemini</option>
          <option>Ollama</option>
        </select>

        {provider !== "Ollama" && (
          <>
            <label style={s.label}>API Key</label>
            <input style={{ ...s.input, marginBottom: 8 }} type="password" placeholder={provider === "OpenAI" ? "sk-..." : "AIza..."} value={apiKey} onChange={e => setApiKey(e.target.value)}/>
          </>
        )}

        {provider === "Ollama" && (
          <>
            <label style={s.label}>Ollama URL</label>
            <input style={{ ...s.input, marginBottom: 8 }} type="text" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)}/>
          </>
        )}

        <label style={s.label}>Model</label>
        {MODELS[provider]?.length > 0 ? (
          <select style={s.select} value={model} onChange={e => setModel(e.target.value)}>
            {MODELS[provider].map(m => <option key={m}>{m}</option>)}
          </select>
        ) : (
          <input style={s.input} type="text" placeholder="llama3" value={model} onChange={e => setModel(e.target.value)}/>
        )}
      </div>

      <div style={s.divider}/>

      {/* SQL Server */}
      <div style={s.section}>
        <div style={s.heading}>SQL Server</div>

        {connected ? (
          <div style={{ fontSize: 12, color: "#27500A", background: "#EAF3DE", border: "0.5px solid #97C459", borderRadius: 6, padding: "8px 10px", display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#639922", flexShrink: 0 }}/>
            Connected to <strong>{database}</strong>
          </div>
        ) : (
          <>
            <label style={s.label}>Server</label>
            <input style={{ ...s.input, marginBottom: 8 }} placeholder="localhost\\SQLEXPRESS" value={server} onChange={e => setServer(e.target.value)}/>
            <label style={s.label}>Database</label>
            <input style={{ ...s.input, marginBottom: 8 }} placeholder="AdventureWorks2019" value={dbName} onChange={e => setDbName(e.target.value)}/>

            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <input type="checkbox" checked={winAuth} onChange={e => setWinAuth(e.target.checked)} style={{ accentColor: "#185FA5" }}/>
              <span style={{ fontSize: 12, color: "#5f5e5a" }}>Windows authentication</span>
            </div>

            {!winAuth && (
              <>
                <input style={{ ...s.input, marginBottom: 6 }} placeholder="Username" value={username} onChange={e => setUsername(e.target.value)}/>
                <input style={{ ...s.input, marginBottom: 8 }} type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)}/>
              </>
            )}

            {connError && <div style={{ fontSize: 12, color: "#791F1F", marginBottom: 8 }}>{connError}</div>}

            <button style={s.btn} onClick={handleConnect} disabled={connecting}>
              {connecting ? "Connecting…" : "Connect"}
            </button>
          </>
        )}
      </div>

      <div style={s.divider}/>

      {/* Semantic cache */}
      <div style={s.section}>
        <div style={s.heading}>Semantic Cache</div>
        <div style={{ ...s.row, marginBottom: 6 }}>
          <span style={{ fontSize: 12, color: "#5f5e5a" }}>Similarity threshold</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#1a1a18", fontFamily: "monospace" }}>{simThreshold.toFixed(2)}</span>
        </div>
        <input type="range" min={0.70} max={1.00} step={0.01} value={simThreshold}
          onChange={e => setSimThreshold(parseFloat(e.target.value))}
          style={{ width: "100%", accentColor: "#185FA5" }}/>
        <div style={{ fontSize: 11, color: "#888780", marginTop: 4 }}>
          {simThreshold >= 0.95 ? "🔴 Very strict" : simThreshold >= 0.85 ? "🟡 Balanced" : simThreshold >= 0.75 ? "🟢 Aggressive" : "⚠️ Very loose"}
        </div>
      </div>
    </aside>
  );
}