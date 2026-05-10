import React, { useState, useCallback, useEffect } from "react"
import "./App.css"
import { NAV_ITEMS, PAGE_META, TABS, API } from "./config"
import { exportHistoryCSV } from "./utils"
import { Icon, StatCard, HistorySidebar } from "./components/SharedUI"
import ImageTab from "./tabs/ImageTab"
import VideoTab from "./tabs/VideoTab"
import WebcamTab from "./tabs/WebcamTab"
import SystemInfo from "./tabs/SystemInfo"

export default function App() {
  const [activeNav,    setActiveNav]    = useState("detection")
  const [tab,          setTab]          = useState(0)
  const [showHistory,   setShowHistory]   = useState(false)
  const [historyFilter, setHistoryFilter] = useState("all") 
  const [isOnline,     setIsOnline]     = useState(false)

  useEffect(() => {
    const pingServer = async () => {
      try {
        const res = await fetch(API + "/")
        setIsOnline(res.ok)
      } catch (err) {
        setIsOnline(false)
      }
    }
    pingServer()
    const interval = setInterval(pingServer, 10000) 
    return () => clearInterval(interval)
  }, [])

  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem("ppe_history") || "[]") } catch { return [] }
  })

  const addToHistory = useCallback(entry => {
    const enriched = { ...entry, datetime: new Date().toLocaleString() }
    setHistory(h => {
      const updated = [...h.slice(-49), enriched]
      localStorage.setItem("ppe_history", JSON.stringify(updated))
      return updated
    })
  }, [])

  const clearHistory = useCallback(() => {
    setHistory([])
    localStorage.removeItem("ppe_history")
  }, [])

  const totalViolations = history.filter(h => !h.summary.is_compliant).length
  const totalSessions   = history.length
  const complianceRate  = totalSessions > 0
    ? Math.round(history.filter(h => h.summary.is_compliant).length / totalSessions * 100) : null

  const meta = PAGE_META[activeNav]

  return (
    <div className="app">

      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-wrap">
            <div className="logo-mark">
              <Icon path="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" size={16} color="#fff" strokeWidth={2} />
            </div>
            <div>
              <div className="logo-name">PPE Guard</div>
              <div className="logo-tagline">Safety Detection System</div>
            </div>
          </div>
        </div>

        <nav className="sidebar-nav">
          <div className="nav-section-label">Navigation</div>
          {NAV_ITEMS.map(item => (
            <button key={item.id} className={`nav-item ${activeNav===item.id?"active":""}`}
              onClick={() => setActiveNav(item.id)}>
              <Icon path={item.icon} size={15} color="currentColor" />
              {item.label}
            </button>
          ))}

          {totalSessions > 0 && (
            <>
              <div className="nav-section-label" style={{ marginTop:12 }}>Overview</div>
              <div style={{ padding:"6px 10px" }}>
                {[
                  ["Sessions",   totalSessions,  null],
                  ["Violations", totalViolations, totalViolations>0?"#FCA5A5":"#6EE7B7"],
                  complianceRate!==null ? ["Compliance", `${complianceRate}%`, complianceRate>=80?"#6EE7B7":"#FCA5A5"] : null,
                ].filter(Boolean).map(([label, value, color]) => (
                  <div key={label} style={{ display:"flex", justifyContent:"space-between", marginBottom:8 }}>
                    <span style={{ fontSize:12, color:"rgba(248,250,252,0.4)" }}>{label}</span>
                    <span style={{ fontSize:12, fontWeight:600, color: color||"rgba(248,250,252,0.7)" }}>{value}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </nav>

        <div className="sidebar-footer">
          <div className={`status-pill ${isOnline ? "" : "offline"}`}>
            <span className={isOnline ? "status-dot-green" : "status-dot-red"} />
            <span className="status-text" style={{ color: isOnline ? "#6EE7B7" : "#FCA5A5" }}>
              {isOnline ? "System Online" : "System Offline"}
            </span>
          </div>
        </div>
      </aside>

      <div className="main">

        <div className="topbar">
          <div className="topbar-left">
            <div className="page-title">{meta.title}</div>
            <div className="page-sub">{meta.sub}</div>
          </div>
          <div className="topbar-right">
            {complianceRate !== null && (
              <div className={`compliance-chip ${complianceRate<80?"warn":""}`}>
                <Icon path={complianceRate>=80?"M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z":"M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"} size={13} color={complianceRate>=80?"#15803D":"#DC2626"} />
                {complianceRate}% compliance
              </div>
            )}
            <button className={`history-toggle ${showHistory?"active":""}`} onClick={() => setShowHistory(v=>!v)}>
              <Icon path="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" size={13} />
              History
              {totalViolations > 0 && <span className="badge-red">{totalViolations>9?"9+":totalViolations}</span>}
            </button>
          </div>
        </div>

        <div className="body">
          <div className="content">

            {activeNav==="dashboard" && (() => {
              const violTypeCounts = {}
              history.forEach(h => {
                (h.summary.violations_found || []).forEach(v => {
                  if (v === "See annotated video") return;
                  const count = h.summary.violation_counts?.[v] || 1;
                  violTypeCounts[v] = (violTypeCounts[v] || 0) + count
                })
              })
              const violTypes = Object.entries(violTypeCounts).sort((a,b) => b[1]-a[1])
              const maxViol   = violTypes[0]?.[1] || 1
              
              return (
                <div>
                  <div className="stats-row">
                    <StatCard label="Total Sessions"  value={totalSessions}   sub="all time" />
                    <StatCard label="Violations Found" value={totalViolations} sub="sessions with issues"     color={totalViolations>0?"#DC2626":undefined} />
                    <StatCard label="Compliance Rate"  value={complianceRate!==null?`${complianceRate}%`:"—"} sub="sessions without violations" color={complianceRate!==null?(complianceRate>=80?"#059669":"#DC2626"):undefined} />
                    <StatCard label="Safe Sessions"    value={history.filter(h=>h.summary.is_compliant).length} sub="fully compliant" color="#059669" />
                  </div>
                  <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
                    <div className="det-panel">
                      <div className="det-panel-body">
                        {history.length === 0 ? (
                          <div className="empty-state">
                            <div className="empty-icon"><Icon path="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" size={22} color="#94A3B8" /></div>
                            <div className="empty-title">No data yet</div>
                            <div className="empty-sub">Run your first detection to see analytics here</div>
                          </div>
                        ) : (
                          <div>
                            <div style={{ fontSize:13, fontWeight:600, color:"#374151", marginBottom:12 }}>Recent Sessions</div>
                            
                            {/* REPLACED: Updated mapping block with flexbox fixes for truncation */}
                            <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
                              {history.slice(-5).reverse().map((h,i) => (
                                <div key={i} style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"10px 14px", background:"#F8FAFC", borderRadius:8, border:"1px solid #F1F5F9", gap:"12px" }}>
                                  <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{ fontSize:13, fontWeight:500, color:"#1E293B", whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{h.source}</div>
                                    <div style={{ fontSize:11, color:"#94A3B8", marginTop:2 }}>{h.datetime || h.time}</div>
                                  </div>
                                  <span className={`hs-status ${h.summary.is_compliant?"safe":"danger"}`} style={{ flexShrink: 0 }}>
                                    {h.summary.is_compliant?"Compliant":`${h.summary.violation_count} violation${h.summary.violation_count!==1?"s":""}`}
                                  </span>
                                </div>
                              ))}
                            </div>
                            {/* ------------------------------------------------------------- */}

                          </div>
                        )}
                      </div>
                    </div>
                    <div className="det-panel">
                      <div className="det-panel-body">
                        {violTypes.length === 0 ? (
                          <div className="empty-state">
                            <div className="empty-icon"><Icon path="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" size={22} color="#94A3B8" /></div>
                            <div className="empty-title">No violations recorded</div>
                            <div className="empty-sub">All sessions compliant</div>
                          </div>
                        ) : (
                          <div className="viol-breakdown">
                            <div className="viol-breakdown-title">Total Number of Incidents (All Time)</div>
                            {violTypes.map(([type, count]) => (
                              <div key={type} className="viol-bar-row">
                                <span className="viol-bar-label">{type}</span>
                                <div className="viol-bar-track">
                                  <div className="viol-bar-fill" style={{ width:`${(count/maxViol)*100}%` }} />
                                </div>
                                <span className="viol-bar-count">{count}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })()}

            {activeNav==="detection" && (
              <div className="det-panel">
                <div className="det-panel-header">
                  {TABS.map(t => (
                    <button key={t.id} className={`tab-btn ${tab===t.id?"active":""}`} onClick={() => setTab(t.id)}>
                      <Icon path={t.icon} size={14} color="currentColor" />
                      {t.label}
                    </button>
                  ))}
                </div>
                <div className="det-panel-body">
                  {tab===0 && <ImageTab onResult={addToHistory} />}
                  {tab===1 && <VideoTab onResult={addToHistory} />}
                  {tab===2 && <WebcamTab onResult={addToHistory} />}
                </div>
              </div>
            )}

            {activeNav==="history" && (() => {
              const filtered = history.filter(h =>
                historyFilter === "all"        ? true :
                historyFilter === "violations" ? !h.summary.is_compliant :
                                                 h.summary.is_compliant
              )
              return (
                <div className="det-panel">
                  <div className="det-panel-body">
                    {history.length === 0 ? (
                      <div className="empty-state">
                        <div className="empty-icon"><Icon path="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" size={22} color="#94A3B8" /></div>
                        <div className="empty-title">No history yet</div>
                        <div className="empty-sub">Run a detection session to see history here</div>
                      </div>
                    ) : (
                      <div>
                        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:16, flexWrap:"wrap", gap:10 }}>
                          <div style={{ display:"flex", alignItems:"center", gap:12 }}>
                            <span style={{ fontSize:13, color:"#64748B" }}>{filtered.length} of {history.length} session{history.length!==1?"s":""}</span>
                            <div className="filter-chips">
                              {[["all","All"],["violations","Violations"],["compliant","Compliant"]].map(([f,label]) => (
                                <button key={f} className={`filter-chip ${historyFilter===f?"active":""} ${historyFilter===f&&f==="violations"?"danger":""}`}
                                  onClick={() => setHistoryFilter(f)}>{label}</button>
                              ))}
                            </div>
                          </div>
                          <div style={{ display:"flex", gap:8 }}>
                            <button className="btn-outline" style={{ fontSize:12, padding:"6px 12px" }} onClick={() => exportHistoryCSV(history)}>
                              <Icon path="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" size={13} color="#374151" />
                              Export CSV
                            </button>
                            <button className="btn-outline" style={{ fontSize:12, padding:"6px 12px" }} onClick={clearHistory}>Clear all</button>
                          </div>
                        </div>
                        <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
                          {filtered.slice().reverse().map((h,i) => (
                            <div key={i} className="hs-item">
                              <div className="hs-item-top">
                                <div>
                                  <div className="hs-source">{h.source}</div>
                                  <div className="hs-time">{h.datetime || h.time}</div>
                                  <div className="hs-det-count">{h.summary.total_detections} detection{h.summary.total_detections!==1?"s":""} · {h.summary.ppe_worn_count} PPE worn</div>
                                </div>
                                <span className={`hs-status ${h.summary.is_compliant?"safe":"danger"}`}>
                                  {h.summary.is_compliant?"Compliant":`${h.summary.violation_count} violation${h.summary.violation_count!==1?"s":""}`}
                                </span>
                              </div>
                              {h.summary.violations_found?.length > 0 && (
                                <div className="hs-viols">
                                  {h.summary.violations_found.map((v,j) => {
                                    const count = h.summary.violation_counts?.[v]
                                    return <span key={j} className="hs-viol-chip">{count > 1 ? `${v} (${count})` : v}</span>
                                  })}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )
            })()}

            {activeNav === "system" && <SystemInfo />}

          </div>

          {showHistory && <HistorySidebar history={history} onClear={clearHistory} />}
        </div>
      </div>
    </div>
  )
}