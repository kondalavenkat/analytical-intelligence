"use client";
// src/app/login/page.tsx

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [remember, setRemember] = useState(false);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");
  const [success,  setSuccess]  = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!email)               { setError("Please enter your email address."); return; }
    if (!email.includes("@")) { setError("Please enter a valid email address."); return; }
    if (!password)            { setError("Please enter your password."); return; }

    setLoading(true);
    try {
      await login(email.trim().toLowerCase(), password);
      setSuccess(true);
      setTimeout(() => router.push("/dashboard"), 1200);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
      setPassword("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "340px 1fr",
      height: "100vh", width: "100vw",
      fontFamily: "'Space Grotesk', system-ui, sans-serif",
      overflow: "hidden",
    }}>

      {/* ── Left dark panel ───────────────────────────────────────── */}
      <div style={{ background: "#042C53", padding: "48px 36px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <div>
          <div style={{ width: 44, height: 44, background: "#185FA5", borderRadius: 11, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#E6F1FB" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/><circle cx="17.5" cy="17.5" r="3.5"/>
              <line x1="17.5" y1="15.5" x2="17.5" y2="19.5"/><line x1="15.5" y1="17.5" x2="19.5" y2="17.5"/>
            </svg>
          </div>
          <div style={{ fontSize: 16, fontWeight: 600, color: "#E6F1FB", letterSpacing: "-0.01em" }}>SQL Analyst</div>
          <div style={{ fontSize: 10, color: "#85B7EB", letterSpacing: "0.07em", textTransform: "uppercase", marginTop: 3 }}>AI-Powered · Semantic Cache</div>
        </div>

        <div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#E6F1FB", letterSpacing: "-0.02em", lineHeight: 1.3, marginBottom: 12 }}>
            Ask questions,<br/>get <span style={{ color: "#378ADD" }}>instant answers</span><br/>from your data
          </div>
          <div style={{ fontSize: 13, color: "#85B7EB", lineHeight: 1.65, marginBottom: 32 }}>
            Connect your SQL Server and start asking in plain English.
          </div>
          {[
            "Natural language to SQL — no query knowledge needed",
            "Semantic cache — similar questions answered instantly",
            "Auto visualizations — charts generated from results",
            "Multi-provider — OpenAI, Gemini, or local Ollama",
          ].map((f) => (
            <div key={f} style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "flex-start" }}>
              <div style={{ width: 5, height: 5, background: "#378ADD", borderRadius: "50%", marginTop: 7, flexShrink: 0 }}/>
              <div style={{ fontSize: 13, color: "#B5D4F4", lineHeight: 1.55 }}>{f}</div>
            </div>
          ))}
        </div>

        <div style={{ fontSize: 11, color: "#4a6a8a" }}>© 2025 Quinte Financial Technologies</div>
      </div>

      {/* ── Center login form ─────────────────────────────────────── */}
      <div style={{ background: "#fff", borderLeft: "0.5px solid rgba(0,0,0,0.10)", borderRight: "0.5px solid rgba(0,0,0,0.10)", display: "flex", flexDirection: "column", justifyContent: "center", padding: "64px 72px" }}>
        <div style={{ fontSize: 26, fontWeight: 700, color: "#1a1a18", letterSpacing: "-0.02em", marginBottom: 6 }}>Welcome back</div>
        <div style={{ fontSize: 14, color: "#5f5e5a", marginBottom: 36 }}>Sign in to access your analytics workspace</div>

        <form onSubmit={handleSubmit}>
          {/* Email */}
          <div style={{ marginBottom: 18 }}>
            <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: "#888780", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 7 }}>
              Email address
            </label>
            <input
              type="text" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="analyst@yourcompany.com" autoComplete="username"
              style={{ width: "100%", height: 42, borderRadius: 8, border: "0.5px solid rgba(0,0,0,0.18)", background: "#f5f5f4", color: "#1a1a18", fontFamily: "inherit", fontSize: 14, padding: "0 14px", outline: "none" }}
              onFocus={e => { e.target.style.borderColor = "#378ADD"; e.target.style.boxShadow = "0 0 0 3px rgba(55,138,221,0.12)"; }}
              onBlur={e  => { e.target.style.borderColor = "rgba(0,0,0,0.18)"; e.target.style.boxShadow = "none"; }}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: 18 }}>
            <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: "#888780", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 7 }}>
              Password
            </label>
            <div style={{ position: "relative" }}>
              <input
                type={showPass ? "text" : "password"} value={password} onChange={e => setPassword(e.target.value)}
                placeholder="Enter your password" autoComplete="current-password"
                style={{ width: "100%", height: 42, borderRadius: 8, border: "0.5px solid rgba(0,0,0,0.18)", background: "#f5f5f4", color: "#1a1a18", fontFamily: "inherit", fontSize: 14, padding: "0 42px 0 14px", outline: "none" }}
                onFocus={e => { e.target.style.borderColor = "#378ADD"; e.target.style.boxShadow = "0 0 0 3px rgba(55,138,221,0.12)"; }}
                onBlur={e  => { e.target.style.borderColor = "rgba(0,0,0,0.18)"; e.target.style.boxShadow = "none"; }}
              />
              <button type="button" onClick={() => setShowPass(v => !v)}
                style={{ position: "absolute", right: 11, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "#888780", display: "flex", alignItems: "center", padding: 3 }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  {showPass
                    ? <><line x1="1" y1="1" x2="23" y2="23"/><path d="M10.73 10.73A2 2 0 0013.27 13.27M6.11 6.11A10.56 10.56 0 002 12s4 8 10 8a10.54 10.54 0 005.89-1.89M9.9 4.24A10.56 10.56 0 0112 4c6 0 10 8 10 8a18.5 18.5 0 01-2.16 3.19"/></>
                    : <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>
                  }
                </svg>
              </button>
            </div>
          </div>

          {/* Options row */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer" }}>
              <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)}
                style={{ width: 14, height: 14, accentColor: "#185FA5", cursor: "pointer" }}/>
              <span style={{ fontSize: 13, color: "#5f5e5a" }}>Remember me</span>
            </label>
            <a href="#" style={{ fontSize: 13, color: "#378ADD", textDecoration: "none" }}>Forgot password?</a>
          </div>

          {/* Submit */}
          <button type="submit" disabled={loading || success}
            style={{ width: "100%", height: 42, background: "#185FA5", color: "#E6F1FB", border: "none", borderRadius: 8, fontFamily: "inherit", fontSize: 14, fontWeight: 600, cursor: loading ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, opacity: loading ? 0.75 : 1, transition: "background 0.15s" }}
            onMouseEnter={e => { if (!loading) (e.target as HTMLButtonElement).style.background = "#378ADD"; }}
            onMouseLeave={e => { (e.target as HTMLButtonElement).style.background = "#185FA5"; }}>
            {loading && <div style={{ width: 16, height: 16, border: "2px solid rgba(230,241,251,0.3)", borderTopColor: "#E6F1FB", borderRadius: "50%", animation: "spin 0.7s linear infinite" }}/>}
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {/* Error */}
        {error && (
          <div style={{ fontSize: 13, color: "#791F1F", background: "#FCEBEB", border: "0.5px solid #F09595", borderRadius: 8, padding: "10px 14px", marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            {error}
          </div>
        )}

        {/* Success */}
        {success && (
          <div style={{ fontSize: 13, color: "#27500A", background: "#EAF3DE", border: "0.5px solid #97C459", borderRadius: 8, padding: "10px 14px", marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            Authenticated — redirecting to your workspace…
          </div>
        )}

        <div style={{ marginTop: 28, paddingTop: 20, borderTop: "0.5px solid rgba(0,0,0,0.10)", fontSize: 12, color: "#888780", display: "flex", justifyContent: "space-between" }}>
          <span>No account? <a href="#" style={{ color: "#378ADD" }}>Request access</a></span>
          <a href="#" style={{ color: "#378ADD" }}>Privacy policy</a>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}