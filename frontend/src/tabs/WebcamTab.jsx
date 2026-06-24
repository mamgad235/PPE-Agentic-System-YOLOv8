import React, { useState, useRef, useEffect, useCallback } from "react"
import { VIOLATION_CLASSES, isViolation } from "../config"
import { drawBoxes, buildSummary } from "../utils"
import { Icon, StatCard, DetectionList } from "../components/SharedUI"
import { RecentIncidentsStrip } from "./IncidentsTab"

const WS_URL = "ws://127.0.0.1:8000/ws/detect"

export default function WebcamTab({ onResult }) {
  const [active,     setActive]     = useState(false)
  const [detections, setDetections] = useState([])
  const [summary,    setSummary]    = useState(null)
  const [fps,        setFps]        = useState(0)
  const [error,      setError]      = useState(null)
  const [incidentCount, setIncidentCount] = useState(0)
  
  const videoRef         = useRef(null)
  const hiddenCanvasRef  = useRef(null)
  const overlayCanvasRef = useRef(null)
  const streamRef        = useRef(null)
  const wsRef            = useRef(null)
  const loopRef          = useRef(null)
  const fpsRef           = useRef(0)
  const fpsTimerRef      = useRef(null)
  const activeRef        = useRef(false) 
  
  const rawBufferRef = useRef([])

  const sessionStatsRef = useRef({ 
    frames: 0, max_det: 0, max_ppe: 0, incidentCount: 0, 
    types: new Set(), typeCounts: {}, historyBuffer: [] 
  })

  const stop = useCallback(() => {
    if (activeRef.current && sessionStatsRef.current.frames > 0) {
      const stats = sessionStatsRef.current
      onResult({
        source: "Live Camera Session",
        summary: {
          total_detections: stats.max_det,
          ppe_worn_count: stats.max_ppe,
          violation_count: stats.incidentCount,
          is_compliant: stats.incidentCount === 0,
          violations_found: Array.from(stats.types),
          violation_counts: stats.typeCounts
        },
        time: new Date().toLocaleString()
      })
    }

    activeRef.current = false
    setActive(false)
    clearInterval(loopRef.current)
    clearInterval(fpsTimerRef.current)
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.close()
    }
    wsRef.current = null
    if (streamRef.current) { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null }
    if (videoRef.current) videoRef.current.srcObject = null
    setDetections([]); setSummary(null); setFps(0); setIncidentCount(0)
  }, [onResult])

  const start = useCallback(async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width:{ideal:1280}, height:{ideal:720} } })
      streamRef.current = stream
      videoRef.current.srcObject = stream
      await videoRef.current.play()
      activeRef.current = true
      setActive(true)
      
      rawBufferRef.current = []
      sessionStatsRef.current = { frames: 0, max_det: 0, max_ppe: 0, incidentCount: 0, types: new Set(), typeCounts: {}, historyBuffer: [] }
      setIncidentCount(0)

      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onerror = () => {
        if (!activeRef.current) return
        setError("Connection to detection server lost. Is the backend running?")
        stop()
      }

      ws.onclose = () => {
        if (!activeRef.current) return
        setError("WebSocket closed unexpectedly. Is the backend running?")
        stop()
      }

      ws.onmessage = (event) => {
        if (!activeRef.current) return
        try {
          const data = JSON.parse(event.data)
          const dets = data.detections || []
          const sum  = data.summary    || buildSummary(dets)
          
          setDetections(dets); setSummary(sum); fpsRef.current++
          const now = Date.now()

          const rawCounts = {}
          dets.forEach(d => {
            if (isViolation(d.class)) {
              rawCounts[d.class] = (rawCounts[d.class] || 0) + 1
            }
          })

          rawBufferRef.current.push(rawCounts)
          if (rawBufferRef.current.length > 4) rawBufferRef.current.shift()

          const currentCounts = {}
          if (rawBufferRef.current.length === 4) {
            Array.from(VIOLATION_CLASSES).forEach(v => {
              currentCounts[v] = Math.min(...rawBufferRef.current.map(frame => frame[v] || 0))
            })
          } else {
            Object.assign(currentCounts, rawCounts)
          }
          
          sessionStatsRef.current.frames++
          sessionStatsRef.current.max_det = Math.max(sessionStatsRef.current.max_det, sum.total_detections)
          sessionStatsRef.current.max_ppe = Math.max(sessionStatsRef.current.max_ppe, sum.ppe_worn_count)
          
          sessionStatsRef.current.historyBuffer.push({ time: now, counts: currentCounts })
          sessionStatsRef.current.historyBuffer = sessionStatsRef.current.historyBuffer.filter(entry => now - entry.time <= 5000)

          const maxInWindow = {}
          sessionStatsRef.current.historyBuffer.forEach(entry => {
            if (entry.time === now) return
            Object.keys(entry.counts).forEach(v => {
              maxInWindow[v] = Math.max(maxInWindow[v] || 0, entry.counts[v])
            })
          })

          Object.keys(currentCounts).forEach(v => {
            const currentN = currentCounts[v]
            const stableN = maxInWindow[v] || 0

            if (currentN > stableN) {
              const newInstances = currentN - stableN
              sessionStatsRef.current.incidentCount += newInstances
              sessionStatsRef.current.typeCounts[v] = (sessionStatsRef.current.typeCounts[v] || 0) + newInstances
              sessionStatsRef.current.types.add(v)
              setIncidentCount(sessionStatsRef.current.incidentCount)
            }
          })

          const video   = videoRef.current
          const overlay = overlayCanvasRef.current
          if (overlay && video && video.videoWidth > 0) {
            overlay.width  = video.offsetWidth
            overlay.height = video.offsetHeight
            const fakeImg = { width:overlay.width, height:overlay.height, naturalWidth:video.videoWidth, naturalHeight:video.videoHeight }
            drawBoxes(overlay, fakeImg, dets)
          }
        } catch {}
      }

      fpsTimerRef.current = setInterval(() => { setFps(fpsRef.current); fpsRef.current = 0 }, 1000)

      loopRef.current = setInterval(() => {
        const video  = videoRef.current
        const hidden = hiddenCanvasRef.current
        if (!video || !hidden || video.readyState < 2) return
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
        hidden.width  = video.videoWidth
        hidden.height = video.videoHeight
        hidden.getContext("2d").drawImage(video, 0, 0)
        hidden.toBlob(blob => {
          if (!blob || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
          blob.arrayBuffer().then(buf => {
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) wsRef.current.send(buf)
          })
        }, "image/jpeg", 0.8)
      }, 200)
    } catch (e) {
      if (e.name === "NotAllowedError") setError("Camera access denied. Please allow camera permissions in your browser settings.")
      else if (e.name === "NotFoundError") setError("No camera found. Please connect a camera and try again.")
      else setError(`Camera error: ${e.message}`)
    }
  }, [stop])

  useEffect(() => () => stop(), [stop])

  return (
    <div>
      {/* Phase-5 quick view: recent incident history pulled from /agent/incidents.
          Polls every few seconds — independent of whether the camera is running. */}
      <RecentIncidentsStrip />

      <div className="webcam-bar">
        {!active
          ? <button className="btn-primary" onClick={start}>
              <Icon path="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" size={14} color="#fff" />
              Start Camera
            </button>
          : <button className="btn-outline btn-danger" onClick={stop}>
              <Icon path="M21 12a9 9 0 11-18 0 9 9 0 0118 0z M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" size={14} color="#DC2626" />
              Stop Camera
            </button>
        }
        {active && <span className="fps-badge">{fps} fps</span>}
        {active && summary && (
          <span className={`hs-status ${incidentCount === 0?"safe":"danger"}`} style={{ marginLeft:"auto" }}>
            {incidentCount === 0 ? "All clear" : `${incidentCount} distinct event${incidentCount!==1?"s":""} recorded`}
          </span>
        )}
      </div>

      {error && <div className="alert error"><Icon path="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" size={15} color="#DC2626" />{error}</div>}

      {active && summary && (
        <div className="stats-row" style={{ marginBottom:14 }}>
          <StatCard label="Live Objects" value={summary.total_detections} sub="currently on screen" />
          <StatCard label="Live Incidents" value={incidentCount} color={incidentCount>0?"#DC2626":"#059669"} sub="unique rule breaks" />
          <StatCard label="Current Status" value={summary.violation_count > 0 ? "Violation" : "Clear"} color={summary.violation_count>0?"#DC2626":"#059669"} sub="real-time safety" />
        </div>
      )}

      <div className="webcam-container" style={{ display: active ? "block" : "none" }}>
        <video ref={videoRef} muted playsInline autoPlay style={{ width:"100%", display:"block", minHeight:240 }} />
        <canvas ref={overlayCanvasRef} className="overlay-canvas" />
      </div>
      <canvas ref={hiddenCanvasRef} style={{ display:"none" }} />

      {!active && !error && (
        <div className="empty-state">
          <div className="empty-icon"><Icon path="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" size={22} color="#94A3B8" /></div>
          <div className="empty-title">Camera inactive</div>
          <div className="empty-sub">Click Start Camera to begin live PPE monitoring</div>
        </div>
      )}

      {active && detections.length > 0 && <DetectionList detections={detections} />}
    </div>
  )
}