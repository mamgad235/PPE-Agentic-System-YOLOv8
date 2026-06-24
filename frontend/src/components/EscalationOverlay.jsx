import React, { useEffect, useRef, useState } from "react"
import { API } from "../config"

// Phase 3 — global escalation overlay.
// Subscribes to /ws/agent_events and renders red banners for active incidents.
// Speaks audible warnings via window.speechSynthesis. Reconnects on drop.
// Mounted once in App.jsx at the root so it persists across tab navigation.

function toWsUrl(api) {
  try {
    const u = new URL(api)
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:"
    return u.origin + "/ws/agent_events"
  } catch {
    const scheme = api.startsWith("https") ? "wss://" : "ws://"
    return scheme + api.replace(/^https?:\/\//, "") + "/ws/agent_events"
  }
}

export default function EscalationOverlay() {
  // { [incident_id]: { type, violation_type, zone_name, severity, repeat_count,
  //                    warned: bool, escalated: bool, opened_at: ms } }
  const [incidents, setIncidents] = useState({})
  const wsRef     = useRef(null)
  const spokenRef = useRef(new Set())     // dedupe TTS per (incident_id, kind)

  useEffect(() => {
    let cancelled    = false
    let retryHandle  = null

    const connect = () => {
      if (cancelled) return
      const ws = new WebSocket(toWsUrl(API))
      wsRef.current = ws
      ws.onclose = () => {
        if (!cancelled) retryHandle = setTimeout(connect, 2000)
      }
      ws.onerror = () => { try { ws.close() } catch {} }
      ws.onmessage = (evt) => {
        try { handleEvent(JSON.parse(evt.data)) } catch {}
      }
    }
    connect()
    return () => {
      cancelled = true
      if (retryHandle) clearTimeout(retryHandle)
      try { wsRef.current?.close() } catch {}
    }
  }, [])

  function handleEvent(ev) {
    if (!ev || ev.type === "hello") return
    const id = ev.incident_id
    if (id == null) return

    if (ev.type === "dashboard_notify") {
      setIncidents(prev => ({
        ...prev,
        [id]: { ...ev, warned: false, escalated: false, opened_at: Date.now() },
      }))
    } else if (ev.type === "audible_warning") {
      // Speak once per incident. Browser may swallow speech if the tab has
      // never received a user gesture — that's expected; banner still flashes.
      const key = `${id}:audible`
      if (!spokenRef.current.has(key)) {
        spokenRef.current.add(key)
        speak(
          `P P E violation. Please put on your ${ev.violation_type.replace(/^NO-/, "").toLowerCase()} ` +
          `in the ${ev.zone_name || "general site area"}.`
        )
      }
      setIncidents(prev => ({
        ...prev,
        [id]: { ...(prev[id] || {}), ...ev, warned: true },
      }))
    } else if (ev.type === "supervisor_alert") {
      const key = `${id}:supervisor`
      if (!spokenRef.current.has(key)) {
        spokenRef.current.add(key)
        speak("Supervisor alert dispatched. Repeat violation threshold exceeded.")
      }
      setIncidents(prev => ({
        ...prev,
        [id]: { ...(prev[id] || {}), ...ev, escalated: true },
      }))
    } else if (ev.type === "incident_closed") {
      setIncidents(prev => {
        const copy = { ...prev }
        delete copy[id]
        return copy
      })
      spokenRef.current.delete(`${id}:audible`)
      spokenRef.current.delete(`${id}:supervisor`)
    }
  }

  function speak(text) {
    try {
      if (!("speechSynthesis" in window)) return
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 1.0
      u.pitch = 1.0
      u.volume = 1.0
      window.speechSynthesis.speak(u)
    } catch (e) {
      console.warn("[escalation] TTS failed:", e)
    }
  }

  const dismiss = (id) => setIncidents(prev => {
    const copy = { ...prev }
    delete copy[id]
    return copy
  })

  const sorted = Object.values(incidents).sort((a, b) => b.incident_id - a.incident_id)
  // Cap the visible stack so a brief ID-churn storm can't take over the
  // screen. The newest few stay; older ones get collapsed into a counter.
  const MAX_VISIBLE = 4
  const list   = sorted.slice(0, MAX_VISIBLE)
  const hidden = Math.max(0, sorted.length - MAX_VISIBLE)

  return (
    <>
      {/* Pulse keyframes — injected once via inline <style> */}
      <style>{`
        @keyframes ppe-escalation-pulse {
          0%, 100% { box-shadow: 0 6px 24px rgba(220,38,38,0.35), 0 0 0 0 rgba(220,38,38,0.55); }
          50%      { box-shadow: 0 6px 24px rgba(220,38,38,0.55), 0 0 0 10px rgba(220,38,38,0.0); }
        }
      `}</style>

      {sorted.length > 0 && (
        <div style={stackStyle}>
          {list.map(inc => (
            <div key={inc.incident_id} style={bannerStyle(inc)}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 18, lineHeight: 1 }}>{"⚠"}</span>
                <strong style={{ fontSize: 14 }}>
                  {inc.violation_type?.replace(/^NO-/, "Missing ") || "Violation"}
                </strong>
                <span style={{ marginLeft: "auto", fontSize: 11, opacity: 0.85 }}>
                  Incident #{inc.incident_id}
                </span>
                <button onClick={() => dismiss(inc.incident_id)}
                  title="Dismiss locally (does not close the incident)"
                  style={dismissBtnStyle}>{"×"}</button>
              </div>
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.92)" }}>
                Zone: <strong>{inc.zone_name || "Unzoned"}</strong>
                {inc.severity && <span> {"·"} Severity: <strong>{inc.severity}</strong></span>}
                {inc.repeat_count > 1 && (
                  <span> {"·"} Repeat #{inc.repeat_count}</span>
                )}
              </div>
              <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                <span style={chipStyle(true)}>Dashboard</span>
                <span style={chipStyle(inc.warned)}>{inc.warned ? "Audible ✓" : "Audible …"}</span>
                <span style={chipStyle(inc.escalated)}>{inc.escalated ? "Supervisor ✓" : "Supervisor —"}</span>
              </div>
            </div>
          ))}
          {hidden > 0 && (
            <div style={moreBadgeStyle}
                 onClick={() => setIncidents({})}
                 title="Click to clear all banners locally (does not close incidents)">
              +{hidden} more incident{hidden === 1 ? "" : "s"} (click to clear)
            </div>
          )}
        </div>
      )}
    </>
  )
}

const stackStyle = {
  position: "fixed", top: 80, right: 20, zIndex: 9999,
  display: "flex", flexDirection: "column", gap: 8,
  maxWidth: 380, pointerEvents: "auto",
}

function bannerStyle(inc) {
  const bg = inc.escalated ? "#7F1D1D"
           : inc.warned    ? "#991B1B"
                           : "#DC2626"
  return {
    background: bg,
    color: "#fff",
    border: "1px solid rgba(0,0,0,0.2)",
    borderRadius: 10,
    padding: "10px 12px",
    animation: "ppe-escalation-pulse 1.8s ease-in-out infinite",
  }
}

function chipStyle(active) {
  return {
    fontSize: 10,
    padding: "2px 8px",
    borderRadius: 999,
    background: active ? "rgba(255,255,255,0.32)" : "rgba(255,255,255,0.12)",
    border: "1px solid rgba(255,255,255,0.3)",
    color: "#fff",
    fontWeight: active ? 600 : 400,
  }
}

const moreBadgeStyle = {
  background:    "rgba(127, 29, 29, 0.95)",
  color:         "#fff",
  border:        "1px solid rgba(255,255,255,0.2)",
  borderRadius:  10,
  padding:       "6px 10px",
  fontSize:      11,
  textAlign:     "center",
  cursor:        "pointer",
  userSelect:    "none",
}

const dismissBtnStyle = {
  background: "transparent",
  border: "none",
  color: "rgba(255,255,255,0.85)",
  fontSize: 18,
  lineHeight: 1,
  cursor: "pointer",
  padding: 0,
  marginLeft: 4,
}

