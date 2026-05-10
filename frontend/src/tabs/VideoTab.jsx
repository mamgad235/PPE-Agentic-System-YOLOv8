import React, { useState, useRef } from "react"
import { API } from "../config"
import { Icon } from "../components/SharedUI"

export default function VideoTab({ onResult }) {
  const [loading,   setLoading]   = useState(false)
  const [videoUrl,  setVideoUrl]  = useState(null)
  const [progress,  setProgress]  = useState("")
  const [url,       setUrl]       = useState("")
  const [error,     setError]     = useState(null)
  const fileRef = useRef(null)

  const processVideo = async (file, source) => {
    setError(null); setVideoUrl(null); setLoading(true)
    setProgress("Uploading and processing video…")

    try {
      const fd = new FormData(); fd.append("file", file)
      const res = await fetch(`${API}/detect_video/`, { method:"POST", body:fd })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)

      setProgress("Downloading annotated video…")
      
      const summaryStr = res.headers.get("X-Video-Summary")
      let summary = null
      let totalFrames = 0
      
      if (summaryStr) {
        const parsed = JSON.parse(summaryStr)
        totalFrames = parsed.total_frames
        summary = {
          total_detections: parsed.max_det,
          ppe_worn_count: parsed.max_ppe,
          violation_count: parsed.incident_count,
          is_compliant: parsed.incident_count === 0,
          violations_found: parsed.violations_found,
          violation_counts: parsed.violation_counts
        }
      }

      const blob = await res.blob()
      const finalUrl = URL.createObjectURL(blob)
      setVideoUrl(finalUrl)
      setProgress(`Done — ${totalFrames} frames processed`)

      onResult({ source, summary, time: new Date().toLocaleString() })
    } catch (e) {
      setError(`Video processing failed: ${e.message}`)
      setProgress("")
    }
    setLoading(false)
  }

  const handleUrl = async () => {
    if (!url.trim()) return
    setError(null); setVideoUrl(null); setLoading(true)
    setProgress("Downloading video from URL…")
    try {
      const res = await fetch(`${API}/detect_video_url/`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ url })
      })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)

      const summaryStr = res.headers.get("X-Video-Summary")
      let summary = null
      let totalFrames = 0
      
      if (summaryStr) {
        const parsed = JSON.parse(summaryStr)
        totalFrames = parsed.total_frames
        summary = {
          total_detections: parsed.max_det,
          ppe_worn_count: parsed.max_ppe,
          violation_count: parsed.incident_count,
          is_compliant: parsed.incident_count === 0,
          violations_found: parsed.violations_found,
          violation_counts: parsed.violation_counts
        }
      }

      const blob = await res.blob()
      const finalUrl = URL.createObjectURL(blob)
      setVideoUrl(finalUrl)
      setProgress(`Done — ${totalFrames} frames processed`)

      onResult({ source: "Video URL", summary, time: new Date().toLocaleString() })
    } catch (e) {
      setError(`Failed: ${e.message}`); setProgress("")
    }
    setLoading(false)
  }

  return (
    <div>
      <div className="controls">
        <button className="btn-primary" onClick={() => fileRef.current?.click()} disabled={loading}>
          <Icon path="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" size={14} color="#fff" />
          Upload Video
        </button>
        <input ref={fileRef} type="file" accept="video/*" style={{ display:"none" }}
          onChange={e => processVideo(e.target.files[0], e.target.files[0].name)} />
        <input className="text-input" value={url} onChange={e => setUrl(e.target.value)}
          placeholder="Or paste a video URL…" />
        <button className="btn-outline" disabled={!url.trim()||loading} onClick={handleUrl}>Analyze</button>
      </div>

      {error && <div className="alert error"><Icon path="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" size={15} color="#DC2626" />{error}</div>}

      {loading && (
        <div className="loading">
          <div className="spinner" />
          <div style={{ fontSize:13, color:"#94A3B8", fontWeight:500, textAlign:"center" }}>{progress}</div>
          <div style={{ fontSize:11, color:"#CBD5E1", marginTop: 8 }}>This may take a few minutes depending on video size</div>
        </div>
      )}

      {progress && !loading && !error && (
        <div className="alert success">
          <Icon path="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" size={15} color="#15803D" />
          {progress}
        </div>
      )}

      {videoUrl && (
        <>
          <video src={videoUrl} controls autoPlay className="video-player" />
          <div style={{ display:"flex", justifyContent:"flex-end", marginTop:10 }}>
            <a href={videoUrl} download="ppe_annotated.webm">
              <button className="btn-outline" style={{ fontSize:12 }}>
                <Icon path="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" size={13} />
                Download annotated video
              </button>
            </a>
          </div>
        </>
      )}

      {!videoUrl && !loading && (
        <div className="empty-state">
          <div className="empty-icon"><Icon path="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.89L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" size={22} color="#94A3B8" /></div>
          <div className="empty-title">No video selected</div>
          <div className="empty-sub">Upload a video file to run frame-by-frame PPE detection</div>
        </div>
      )}
    </div>
  )
}