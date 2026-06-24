import React, { useState, useRef, useEffect } from "react"
import { API } from "../config"
import { Icon } from "../components/SharedUI"
import { IncidentsBrowser } from "./IncidentsTab"

const INCIDENTS_PANEL_KEY = "agent_incidents_panel_open"

// Defense-safe prompts — verified to work reliably on llama-3.1-8b-instant.
// Risky originals (yesterday's violations, "most recent open incident", "what tools do you have")
// removed; safer phrasings substituted where useful.
const SUGGESTED = [
  "Summarize today's violations",
  "Which zone is worst this week?",
  "How many hardhat violations happened today?",
  "Who is the top offender in the last 7 days?",
  "What hour of day has the most violations?",
  "Draft an incident email for incident 1",
  "Explain how the escalation policy works",
]

export default function AgentTab() {
  const [turns,    setTurns]    = useState([])  // [{role, content, toolCalls?, trace?, ok?}]
  const [input,    setInput]    = useState("")
  const [loading,  setLoading]  = useState(false)
  const [expanded, setExpanded] = useState({})  // turn idx -> bool, for tool-call panels
  const scrollRef = useRef(null)

  // Provider / model selector state
  const [providers, setProviders] = useState({})        // { groq: [...], gemini: [...], openrouter: [...] }
  const [provider,  setProvider]  = useState(localStorage.getItem("agent_provider") || "")
  const [model,     setModel]     = useState(localStorage.getItem("agent_model")    || "")
  // The provider/model picker is collapsed by default — saves vertical space
  // and reduces noise during the demo. Click the disclosure to expand.
  const [pickerOpen, setPickerOpen] = useState(false)

  // Embedded Incidents panel — collapsible, default collapsed so the chat
  // remains the first thing the user sees. Persisted to localStorage so the
  // user's preference survives reloads.
  const [incidentsOpen, setIncidentsOpen] = useState(() => {
    try {
      const v = localStorage.getItem(INCIDENTS_PANEL_KEY)
      return v === "1"
    } catch { return false }
  })
  useEffect(() => {
    try { localStorage.setItem(INCIDENTS_PANEL_KEY, incidentsOpen ? "1" : "0") } catch {}
  }, [incidentsOpen])

  // Live-simulation toggle. Backed by /agent/sim/start | stop. We poll
  // /agent/sim/status on mount + every 4s so the button reflects the truth
  // even if uvicorn was restarted or another tab toggled the sim.
  const [simRunning, setSimRunning] = useState(false)
  const [simBusy,    setSimBusy]    = useState(false)
  useEffect(() => {
    let cancelled = false
    const ping = () =>
      fetch(`${API}/agent/sim/status`).then(r => r.json())
        .then(s => { if (!cancelled) setSimRunning(!!s.running) })
        .catch(() => {})
    ping()
    const id = setInterval(ping, 4000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])
  const toggleSim = async () => {
    if (simBusy) return
    setSimBusy(true)
    try {
      const url = simRunning ? `${API}/agent/sim/stop` : `${API}/agent/sim/start`
      const init = { method: "POST", headers: { "Content-Type": "application/json" } }
      if (!simRunning) init.body = JSON.stringify({ rate_hz: 2.0, violation_type: "NO-Hardhat", zone: "zone_a" })
      const r = await fetch(url, init)
      const j = await r.json()
      setSimRunning(simRunning ? !(j.was_running) : true)
    } catch (e) {
      // best-effort; status poll will reconcile
    } finally {
      setSimBusy(false)
    }
  }

  // Fetch catalog + current selection on mount
  useEffect(() => {
    fetch(`${API}/agent/providers`)
      .then(r => r.json())
      .then(d => {
        setProviders(d.providers || {})
        // If user has a saved selection, re-apply it to the backend (survives backend restarts)
        const savedP = localStorage.getItem("agent_provider")
        const savedM = localStorage.getItem("agent_model")
        if (savedP && savedM && d.providers?.[savedP]?.includes(savedM)) {
          setProvider(savedP); setModel(savedM)
          fetch(`${API}/agent/provider`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ provider: savedP, model: savedM }),
          }).catch(() => {})
        } else if (d.current) {
          setProvider(d.current.provider || ""); setModel(d.current.model || "")
        }
      })
      .catch(() => {})
  }, [])

  const applyProvider = (newP, newM) => {
    setProvider(newP); setModel(newM)
    localStorage.setItem("agent_provider", newP)
    localStorage.setItem("agent_model",    newM)
    fetch(`${API}/agent/provider`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: newP, model: newM }),
    }).catch(() => {})
  }

  const onProviderChange = (newP) => {
    const modelList = providers[newP] || []
    const firstModel = modelList[0] || ""
    applyProvider(newP, firstModel)
  }

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [turns, loading])

  const ask = async (question) => {
    const q = (question ?? input).trim()
    if (!q || loading) return
    setInput("")
    setTurns(t => [...t, { role: "user", content: q }])
    setLoading(true)
    try {
      // Send the browser's IANA timezone so the backend can format "today",
      // "yesterday", and hour breakdowns in the user's local time. Falls back
      // to UTC on the backend if the value is missing or unrecognized.
      const browserTz = (() => {
        try { return Intl.DateTimeFormat().resolvedOptions().timeZone }
        catch { return "" }
      })()
      const res = await fetch(`${API}/agent/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, tz: browserTz }),
      })
      const data = await res.json()
      if (!res.ok) {
        setTurns(t => [...t, { role: "assistant", content: data.detail || "Request failed", ok: false }])
      } else {
        setTurns(t => [...t, {
          role:      "assistant",
          content:   data.answer || "(no answer)",
          toolCalls: data.tool_calls || [],
          trace:     data.trace_id,
          ok:        true,
        }])
      }
    } catch (e) {
      setTurns(t => [...t, { role: "assistant", content: `Cannot reach API: ${e.message}`, ok: false }])
    } finally {
      setLoading(false)
    }
  }

  const toggle = (i) => setExpanded(e => ({ ...e, [i]: !e[i] }))

  const userBubbleStyle = {
    alignSelf: "flex-end", maxWidth: "75%",
    background: "#2563EB", color: "#fff",
    padding: "10px 14px", borderRadius: "14px 14px 4px 14px",
    fontSize: 14, lineHeight: 1.45, whiteSpace: "pre-wrap",
  }
  const aiBubbleStyle = {
    alignSelf: "flex-start", maxWidth: "75%",
    background: "#F1F5F9", color: "#0F172A",
    padding: "10px 14px", borderRadius: "14px 14px 14px 4px",
    fontSize: 14, lineHeight: 1.5, whiteSpace: "pre-wrap",
    border: "1px solid #E2E8F0",
  }
  const errBubbleStyle = { ...aiBubbleStyle, background: "#FEF2F2", borderColor: "#FECACA", color: "#991B1B" }

  const selectStyle = {
    fontSize: 12, padding: "5px 8px",
    background: "#fff", border: "1px solid #E2E8F0",
    borderRadius: 6, color: "#1E293B",
    cursor: "pointer",
  }

  return (
    // Two sibling panels — the chat panel keeps a fixed height so the
    // transcript can scroll inside it, and the Incidents panel sits below
    // as its OWN panel so when expanded it grows the page (rather than
    // overlaying / shrinking the chat).
    <>
    <div className="det-panel">
      <div className="det-panel-body" style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 240px)", minHeight: 480 }}>

        {/* Chat-agent name + collapsed LLM picker. The Simulate-violation
            toggle now lives inside the picker's expanded options so the
            escalation banners that pop in the top-right corner never
            cover it during the demo. */}
        <div style={{
          marginBottom: 12, padding: "8px 10px",
          background: "#F8FAFC", border: "1px solid #F1F5F9", borderRadius: 8,
        }}>
          <button
            type="button"
            onClick={() => setPickerOpen(o => !o)}
            aria-expanded={pickerOpen}
            aria-label={`Model selector. Currently ${model || "(none)"} via ${provider || "(no provider)"}. Click to ${pickerOpen ? "collapse" : "expand"}.`}
            title={model ? `Model: ${model} (${provider || "?"})` : "Pick a model"}
            style={{
              display: "flex", alignItems: "center", width: "100%",
              background: "transparent", border: "none", padding: 0,
              cursor: "pointer", color: "#0F172A",
            }}>
            <Icon path="M13 10V3L4 14h7v7l9-11h-7z" size={13} color="#64748B" />
            {/* Name of the chat agent — not "Safety Agent" because that's
                already the page name in the topbar. "PPE Inspector" reads
                like a domain role (the AI that checks PPE). The current
                model name lives behind the expander, not in the title. */}
            <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 600, color: "#1E293B" }}>
              PPE Inspector
            </span>
            <span style={{ marginLeft: "auto", display: "inline-flex" }}>
              <Icon
                path={pickerOpen ? "M19 9l-7 7-7-7" : "M9 5l7 7-7 7"}
                size={11}
                color="#64748B" />
            </span>
          </button>
          {pickerOpen && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 11, color: "#64748B" }}>Provider</span>
              <select value={provider}
                onChange={e => onProviderChange(e.target.value)}
                style={selectStyle}>
                {Object.keys(providers).length === 0 && <option value="">loading…</option>}
                {Object.keys(providers).map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <span style={{ fontSize: 11, color: "#64748B" }}>Model</span>
              <select value={model}
                onChange={e => applyProvider(provider, e.target.value)}
                disabled={!provider}
                style={{ ...selectStyle, minWidth: 220 }}>
                {(providers[provider] || []).map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
              <span style={{ fontSize: 11, color: "#94A3B8", marginLeft: "auto" }}>
                switches take effect immediately
              </span>
            </div>
          )}

          {/* Simulate-violation toggle — lives inside the picker's expanded
              options so the red escalation banners (top-right) don't cover
              it during the demo. Calls POST /agent/sim/start | stop. */}
          {pickerOpen && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              marginTop: 10, paddingTop: 10,
              borderTop: "1px dashed #E2E8F0",
            }}>
              <span style={{ fontSize: 11, color: "#64748B" }}>Demo</span>
              <button
                type="button"
                onClick={toggleSim}
                disabled={simBusy}
                title={simRunning
                  ? "Stop the synthetic-violation simulator"
                  : "Publish synthetic NO-Hardhat detections in zone_a at 2 Hz so the escalation pipeline fires end-to-end"}
                style={{
                  padding: "5px 12px",
                  background: simRunning ? "#FEF2F2" : "#fff",
                  border: `1px solid ${simRunning ? "#FECACA" : "#E2E8F0"}`,
                  borderRadius: 6,
                  cursor: simBusy ? "not-allowed" : "pointer",
                  color: simRunning ? "#991B1B" : "#1E293B",
                  fontSize: 12, fontWeight: 600,
                  display: "inline-flex", alignItems: "center", gap: 6,
                  whiteSpace: "nowrap",
                }}>
                <span style={{
                  width: 7, height: 7, borderRadius: 999,
                  background: simRunning ? "#DC2626" : "#94A3B8",
                  animation: simRunning ? "ppe-escalation-pulse 1.6s ease-in-out infinite" : "none",
                }} />
                {simRunning ? "Stop simulation" : "Simulate violation"}
              </button>
              <span style={{ fontSize: 11, color: "#94A3B8", marginLeft: "auto" }}>
                fires synthetic detections at 2 Hz
              </span>
            </div>
          )}
        </div>

        {/* Suggested prompts */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>
          {SUGGESTED.map(s => (
            <button key={s}
              onClick={() => ask(s)}
              disabled={loading}
              style={{
                fontSize: 12, padding: "6px 12px",
                background: "#fff", border: "1px solid #E2E8F0",
                borderRadius: 999, color: "#475569",
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.5 : 1,
              }}>
              {s}
            </button>
          ))}
        </div>

        {/* Transcript */}
        <div ref={scrollRef}
          style={{ flex: 1, overflowY: "auto", padding: "8px 4px",
                   display: "flex", flexDirection: "column", gap: 10,
                   background: "#FAFBFC", border: "1px solid #F1F5F9", borderRadius: 10 }}>
          {turns.length === 0 && !loading && (
            <div className="empty-state" style={{ margin: "auto" }}>
              <div className="empty-icon">
                <Icon path="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
                      size={22} color="#94A3B8" />
              </div>
              <div className="empty-title">Ask the safety agent</div>
              <div className="empty-sub">Pick a suggested prompt above or type your own question.</div>
            </div>
          )}

          {turns.map((t, i) => {
            if (t.role === "user") {
              return <div key={i} style={{ display: "flex", padding: "0 8px" }}><div style={userBubbleStyle}>{t.content}</div></div>
            }
            const bubble = t.ok === false ? errBubbleStyle : aiBubbleStyle
            return (
              <div key={i} style={{ display: "flex", flexDirection: "column", padding: "0 8px", gap: 6 }}>
                <div style={bubble}>{t.content}</div>
                {t.toolCalls && t.toolCalls.length > 0 && (
                  <div style={{ marginLeft: 8, fontSize: 11 }}>
                    <button onClick={() => toggle(i)}
                      style={{ background: "transparent", border: "none", color: "#64748B", cursor: "pointer", padding: 0, fontSize: 11, display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <Icon path={expanded[i]
                        ? "M19 9l-7 7-7-7"
                        : "M9 5l7 7-7 7"} size={11} color="#64748B" />
                      {expanded[i] ? "Hide" : "Show"} {t.toolCalls.length} tool call{t.toolCalls.length !== 1 ? "s" : ""}
                      {t.trace ? `  ·  trace ${t.trace}` : ""}
                    </button>
                    {expanded[i] && (
                      <div style={{ marginTop: 6, background: "#fff", border: "1px solid #E2E8F0", borderRadius: 8, padding: 8 }}>
                        {t.toolCalls.map((tc, j) => (
                          <div key={j} style={{ marginBottom: 8, paddingBottom: 8, borderBottom: j < t.toolCalls.length - 1 ? "1px dashed #E2E8F0" : "none" }}>
                            <div style={{ fontFamily: "monospace", fontSize: 11, color: "#0F172A", fontWeight: 600 }}>
                              {tc.name}({Object.keys(tc.args || {}).length ? JSON.stringify(tc.args) : ""})
                            </div>
                            <div style={{ fontFamily: "monospace", fontSize: 11, color: "#475569", whiteSpace: "pre-wrap", marginTop: 3, maxHeight: 140, overflow: "auto" }}>
                              → {typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2)}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {loading && (
            <div style={{ display: "flex", padding: "0 8px" }}>
              <div style={{ ...aiBubbleStyle, display: "inline-flex", alignItems: "center", gap: 8 }}>
                <div className="spinner" style={{ width: 14, height: 14 }} />
                <span style={{ color: "#64748B" }}>Thinking…</span>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="controls" style={{ marginTop: 12 }}>
          <input className="text-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about violations, zones, workers, incidents…"
            onKeyDown={e => e.key === "Enter" && ask()}
            disabled={loading} />
          <button className="btn-primary" onClick={() => ask()} disabled={!input.trim() || loading}>
            <Icon path="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" size={14} color="#fff" />
            Send
          </button>
        </div>

      </div>
    </div>

    {/* Incidents panel — its OWN det-panel, sibling of the chat panel.
        Collapsed by default. When the user expands it, the panel grows
        downward and the page scrolls; the chat above is unaffected. */}
    <div className="det-panel" style={{ marginTop: 12 }}>
      <div className="det-panel-body" style={{ padding: 12 }}>
        <button
          type="button"
          onClick={() => setIncidentsOpen(o => !o)}
          aria-expanded={incidentsOpen}
          style={{
            display: "flex", alignItems: "center", gap: 8, width: "100%",
            background: "transparent", border: "none", padding: 0,
            cursor: "pointer", color: "#0F172A",
          }}>
          <Icon path="M12 9v2m0 4h.01M5 19h14a2 2 0 001.84-2.75L13.74 4a2 2 0 00-3.48 0L3.16 16.25A2 2 0 005 19z" size={13} color="#475569" />
          <span style={{ fontSize: 13, fontWeight: 600, color: "#1E293B" }}>
            Incidents
          </span>
          <span style={{ fontSize: 11, color: "#94A3B8" }}>
            browse, filter, download PDF reports
          </span>
          <span style={{ marginLeft: "auto", display: "inline-flex" }}>
            <Icon
              path={incidentsOpen ? "M19 9l-7 7-7-7" : "M9 5l7 7-7 7"}
              size={11}
              color="#64748B" />
          </span>
        </button>
        {incidentsOpen && (
          <div style={{
            marginTop: 12, paddingTop: 12,
            borderTop: "1px solid #F1F5F9",
          }}>
            <IncidentsBrowser />
          </div>
        )}
      </div>
    </div>
    </>
  )
}
