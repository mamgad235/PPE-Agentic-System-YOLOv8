import { isViolation, WEARABLE_PPE, CLASS_COLORS, formatConf } from "./config"

export function buildSummary(detections) {
  const violations = detections.filter(d => isViolation(d.class))
  const ppe        = detections.filter(d => WEARABLE_PPE.has(d.class)) 
  
  const vCounts = {}
  violations.forEach(d => { vCounts[d.class] = (vCounts[d.class] || 0) + 1 })
  
  return {
    total_detections : detections.length,
    ppe_worn_count   : ppe.length,
    violation_count  : violations.length,
    is_compliant     : violations.length === 0,
    violations_found : Object.keys(vCounts),
    violation_counts : vCounts
  }
}

export function enrichBackendSummary(backendSummary, detections) {
  if (!backendSummary) return buildSummary(detections)
  const vCounts = {}
  ;(backendSummary.violations_found || []).forEach(v => {
    vCounts[v] = backendSummary.class_counts?.[v] || 1
  })
  return { ...backendSummary, violation_counts: vCounts }
}

export function drawBoxes(canvas, img, detections) {
  if (!canvas || !img) return
  const ctx = canvas.getContext("2d")
  canvas.width  = img.width
  canvas.height = img.height
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  const sx = img.width  / img.naturalWidth
  const sy = img.height / img.naturalHeight
  detections.forEach(d => {
    const [x1, y1, x2, y2] = d.box
    const color = CLASS_COLORS[d.class] || "#2563EB"
    const bx = x1*sx, by = y1*sy, bw = (x2-x1)*sx, bh = (y2-y1)*sy
    ctx.strokeStyle = color; ctx.lineWidth = 2
    ctx.strokeRect(bx, by, bw, bh)
    const label = `${d.class}  ${formatConf(d.confidence)}`
    ctx.font = "600 11px Inter, sans-serif"
    const tw = ctx.measureText(label).width
    const lbg = isViolation(d.class) ? "#DC2626" : color
    const lx = bx, ly = Math.max(by - 22, 0), lw = tw + 12, lh = 20, rr = 4
    ctx.fillStyle = lbg
    ctx.beginPath()
    ctx.moveTo(lx+rr, ly); ctx.lineTo(lx+lw-rr, ly)
    ctx.quadraticCurveTo(lx+lw, ly, lx+lw, ly+rr)
    ctx.lineTo(lx+lw, ly+lh-rr)
    ctx.quadraticCurveTo(lx+lw, ly+lh, lx+lw-rr, ly+lh)
    ctx.lineTo(lx+rr, ly+lh)
    ctx.quadraticCurveTo(lx, ly+lh, lx, ly+lh-rr)
    ctx.lineTo(lx, ly+rr)
    ctx.quadraticCurveTo(lx, ly, lx+rr, ly)
    ctx.closePath(); ctx.fill()
    ctx.fillStyle = "#fff"
    ctx.fillText(label, lx+6, ly+13)
  })
}

export function exportHistoryCSV(history) {
  const header = ["Datetime", "Source", "Total Detections", "PPE Worn", "Violations", "Compliant", "Violation Types"]
  const rows   = history.map(h => [
    h.datetime || h.time,
    h.source,
    h.summary.total_detections,
    h.summary.ppe_worn_count,
    h.summary.violation_count,
    h.summary.is_compliant ? "Yes" : "No",
    (h.summary.violations_found || []).map(v => {
      const c = h.summary.violation_counts?.[v]
      return c && c > 1 ? `${v} (${c})` : v
    }).join("; "),
  ])
  const csv  = [header, ...rows].map(r => r.map(v => `"${v}"`).join(",")).join("\n")
  const blob = new Blob([csv], { type: "text/csv" })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement("a")
  a.href = url; a.download = "ppe_detection_log.csv"; a.click()
  URL.revokeObjectURL(url)
}