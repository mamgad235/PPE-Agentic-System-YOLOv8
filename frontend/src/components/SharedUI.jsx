import React from "react"
import { isViolation, CLASS_COLORS, CLASS_BG, formatConf } from "../config"

export const Icon = ({ path, size = 16, color = "currentColor", strokeWidth = 1.75 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
    <path d={path} />
  </svg>
)

export function StatCard({ label, value, sub, color }) {
  return (
    <div className="stat-card">
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value" style={{ "--sv": color || "#0F172A" }}>{value}</div>
      {sub && <div className="stat-card-sub">{sub}</div>}
    </div>
  )
}

export function DetectionList({ detections }) {
  if (!detections?.length) return null
  const violations = detections.filter(d => isViolation(d.class))
  const safe       = detections.filter(d => !isViolation(d.class))
  return (
    <div className="det-list">
      <div className="det-list-header">{detections.length} detection{detections.length !== 1 ? "s" : ""}</div>
      {violations.map((d, i) => (
        <div key={`v${i}`} className="det-item" style={{ "--item-bg": "#FEF2F2", "--dot-color": CLASS_COLORS[d.class] }}>
          <div className="det-item-left">
            <span className="det-dot" /><span className="det-name">{d.class}</span>
            <span className="det-viol-badge">Violation</span>
          </div>
          <span className="det-conf">{formatConf(d.confidence)}</span>
        </div>
      ))}
      {violations.length > 0 && safe.length > 0 && <div style={{ height: 4 }} />}
      {safe.map((d, i) => (
        <div key={`s${i}`} className="det-item" style={{ "--item-bg": CLASS_BG[d.class] || "#F8FAFC", "--dot-color": CLASS_COLORS[d.class] || "#94A3B8" }}>
          <div className="det-item-left">
            <span className="det-dot" /><span className="det-name">{d.class}</span>
          </div>
          <span className="det-conf">{formatConf(d.confidence)}</span>
        </div>
      ))}
    </div>
  )
}

export function HistorySidebar({ history, onClear }) {
  const violations = history.filter(h => !h.summary.is_compliant).length
  return (
    <div className="history-sidebar">
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
        <div>
          <div className="hs-title">Detection History</div>
          <div className="hs-sub">{history.length} session{history.length!==1?"s":""} · {violations} with violations</div>
        </div>
        {history.length > 0 && <button className="hs-clear" onClick={onClear}>Clear all</button>}
      </div>
      {history.length === 0
        ? <div className="hs-empty">No sessions yet.<br />Run a detection to see history.</div>
        : (
          <div className="hs-list">
            {history.slice().reverse().map((h, i) => (
              <div key={i} className="hs-item">
                <div className="hs-item-top">
                  <div>
                    <div className="hs-source">{h.source}</div>
                    <div className="hs-time">{h.time}</div>
                  </div>
                  <span className={`hs-status ${h.summary.is_compliant ? "safe" : "danger"}`}>
                    {h.summary.is_compliant ? "Compliant" : `${h.summary.violation_count} violation${h.summary.violation_count!==1?"s":""}`}
                  </span>
                </div>
                {h.summary.violations_found?.length > 0 && (
                  <div className="hs-viols">
                    {h.summary.violations_found.map((v, j) => {
                      const count = h.summary.violation_counts?.[v]
                      return <span key={j} className="hs-viol-chip">{count > 1 ? `${v} (${count})` : v}</span>
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        )
      }
    </div>
  )
}