export const API = "http://127.0.0.1:8000"

export const CLASS_COLORS = {
  "Hardhat":        "#2563EB",
  "Mask":           "#059669",
  "Safety Vest":    "#0891B2",
  "Safety Cone":    "#D97706",
  "Person":         "#7C3AED",
  "machinery":      "#0F766E",
  "vehicle":        "#92400E",
  "NO-Hardhat":     "#DC2626",
  "NO-Mask":        "#DC2626",
  "NO-Safety Vest": "#DC2626",
}

export const CLASS_BG = {
  "Hardhat":        "#EFF6FF",
  "Mask":           "#ECFDF5",
  "Safety Vest":    "#ECFEFF",
  "Safety Cone":    "#FFFBEB",
  "Person":         "#F5F3FF",
  "machinery":      "#F0FDFA",
  "vehicle":        "#FEF3C7",
  "NO-Hardhat":     "#FEF2F2",
  "NO-Mask":        "#FEF2F2",
  "NO-Safety Vest": "#FEF2F2",
}

export const VIOLATION_CLASSES = new Set(["NO-Hardhat", "NO-Mask", "NO-Safety Vest"])
export const WEARABLE_PPE      = new Set(["Hardhat", "Mask", "Safety Vest"]) 

export const isViolation = cls => VIOLATION_CLASSES.has(cls)
export const formatConf  = v   => `${Math.round(v * 100)}%`

export const TABS = [
  { id: 0, label: "Image Detection", icon: "M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" },
  { id: 1, label: "Video Analysis",  icon: "M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.89L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" },
  { id: 2, label: "Live Camera",     icon: "M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" },
]

export const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard",    icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
  { id: "detection", label: "Detection",    icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" },
  { id: "agent",     label: "Safety Agent", icon: "M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" },
  { id: "history",   label: "History",      icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
  { id: "system",    label: "System Info",  icon: "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" }
]

// The Incidents browser now lives as a collapsible section *inside* the
// Safety Agent screen (see AgentTab.jsx), so there's no standalone nav
// entry for it. IncidentsTab.jsx still exports a default component for
// any deep-link compatibility, but no nav route surfaces it.

export const PAGE_META = {
  dashboard: { title: "Dashboard",      sub: "Overview of all detection sessions" },
  detection: { title: "PPE Detection",  sub: "Upload images, videos or use live camera to detect PPE compliance" },
  agent:     { title: "Safety Agent",   sub: "Review incidents and ask natural-language questions about violations, zones and policy" },
  history:   { title: "History",        sub: "All recorded detection sessions" },
  system:    { title: "System Architecture", sub: "Neural network specifications, datasets, and performance metrics" }
}