import React, { useState, useRef, useEffect } from "react"
import { API } from "../config"
import { drawBoxes, enrichBackendSummary } from "../utils"
import { Icon, StatCard, DetectionList } from "../components/SharedUI"

export default function ImageTab({ onResult }) {
  const [loading,    setLoading]    = useState(false)
  const [preview,    setPreview]    = useState(null)
  const [detections, setDetections] = useState(null)
  const [summary,    setSummary]    = useState(null)
  const [url,        setUrl]        = useState("")
  const [error,      setError]      = useState(null)
  const imgRef    = useRef(null)
  const canvasRef = useRef(null)
  const fileRef   = useRef(null)

  useEffect(() => {
    if (detections && imgRef.current?.complete)
      drawBoxes(canvasRef.current, imgRef.current, detections)
  }, [detections, preview])

  const process = async (fetchFn, source) => {
    setError(null); setDetections(null); setSummary(null); setLoading(true)
    try {
      const data = await fetchFn()
      if (data.detail) throw new Error(data.detail)
      const sum = enrichBackendSummary(data.summary, data.detections)
      setDetections(data.detections); setSummary(sum)
      onResult({ source, summary: sum, time: new Date().toLocaleString() })
    } catch (e) { setError(e.message || "Cannot reach API. Make sure the backend is running.") }
    setLoading(false)
  }

  const handleFile = file => {
    if (!file) return
    setPreview(URL.createObjectURL(file))
    process(async () => {
      const fd = new FormData(); fd.append("file", file)
      return (await fetch(`${API}/detect/`, { method:"POST", body:fd })).json()
    }, file.name)
  }

  const handleUrl = () => {
    if (!url.trim()) return
    setPreview(url)
    process(async () => (await fetch(`${API}/detect_url/`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ url })
    })).json(), "Image URL")
  }

  return (
    <div>
      <div className="controls">
        <button className="btn-primary" onClick={() => fileRef.current?.click()}>
          <Icon path="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" size={14} color="#fff" />
          Upload Image
        </button>
        <input ref={fileRef} type="file" accept="image/*" style={{ display:"none" }}
          onChange={e => handleFile(e.target.files[0])} />
        <input className="text-input" value={url} onChange={e => setUrl(e.target.value)}
          placeholder="Or paste an image URL…" onKeyDown={e => e.key==="Enter" && handleUrl()} />
        <button className="btn-outline" onClick={handleUrl} disabled={!url.trim()||loading}>Analyze</button>
      </div>

      {error   && <div className="alert error"><Icon path="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" size={15} color="#DC2626" />{error}</div>}
      {loading && <div className="loading"><div className="spinner" /><div style={{fontSize:13,color:"#94A3B8",fontWeight:500}}>Analyzing image…</div></div>}

      {preview && !loading && (
        <>
          {summary && (
            <div className="stats-row" style={{ marginBottom:14 }}>
              <StatCard label="Detections" value={summary.total_detections} sub="objects found" />
              <StatCard label="PPE Worn"   value={summary.ppe_worn_count}   sub="compliant items" color="#059669" />
              <StatCard label="Violations" value={summary.violation_count}  sub="missing PPE"    color={summary.violation_count>0?"#DC2626":"#059669"} />
              <StatCard label="Status"     value={summary.is_compliant?"Safe":"Alert"} sub={summary.is_compliant?"No violations":"Action needed"} color={summary.is_compliant?"#059669":"#DC2626"} />
            </div>
          )}
          <div className="img-wrapper">
            <img ref={imgRef} src={preview} alt="detection"
              onLoad={() => detections && drawBoxes(canvasRef.current, imgRef.current, detections)} />
            <canvas ref={canvasRef} />
          </div>
          <DetectionList detections={detections} />
        </>
      )}

      {!preview && !loading && (
        <div className="empty-state">
          <div className="empty-icon"><Icon path="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" size={22} color="#94A3B8" /></div>
          <div className="empty-title">No image selected</div>
          <div className="empty-sub">Upload an image or paste a URL to begin detection</div>
        </div>
      )}
    </div>
  )
}