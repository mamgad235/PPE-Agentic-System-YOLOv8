import React from "react"
import { Icon } from "../components/SharedUI"

export default function SystemInfo() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "10px", maxWidth: "1000px", margin: "0 auto" }}>
      
      {/* ── Architecture Overview ── */}
      <div className="det-panel">
        <div className="det-panel-body" style={{ padding: "12px 16px", display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", minWidth: "240px" }}>
            <div style={{ width: 36, height: 36, borderRadius: 8, background: "#EFF6FF", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <Icon path="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" size={18} color="#2563EB" />
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#0F172A" }}>Asymmetric Deployment</div>
              <div style={{ fontSize: 11, color: "#64748B", marginTop: 2 }}>Dual YOLOv8 routing engine</div>
            </div>
          </div>
          <p style={{ fontSize: 12, color: "#475569", lineHeight: 1.4, margin: 0, flex: 1, minWidth: "300px", borderLeft: "2px solid #F1F5F9", paddingLeft: "16px" }}>
            Live webcam streams route to a generalized edge model with lightweight spatial filtering (person validation + IoSA de-duplication) and temporal smoothing, while static uploads process through a highly-tuned core model utilizing full anatomical heuristics to combat Domain Shift.
          </p>
        </div>
      </div>

      {/* ── Model Specifications Grid ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "12px" }}>
        
        {/* Core Model Card */}
        <div className="det-panel" style={{ borderTop: "3px solid #059669" }}>
          <div className="det-panel-body" style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#059669", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 4 }}>Static / Video Engine</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#0F172A", marginBottom: 12 }}>YOLOv8m (Core Model)</div>
            
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <SpecRow label="Split Ratio" value="85 / 15 / 5" />
              <SpecRow label="Hyperparameter Tuning" value="Enabled (Heavy)" />
              <SpecRow label="Parameter Count" value="~25.9 Million" />
              <SpecRow label="Test mAP50" value="89.1% (Blind)" highlight />
              <SpecRow label="Inference Speed" value="High-Throughput (Batch)" />
              <SpecRow label="Spatial Logic" value="Nested Box IoSA + NMS" />
              <SpecRow label="Tracking Logic" value="Python Sliding Window" />
              <SpecRow label="Primary Target" value="Images & Pre-recorded Video" />
            </div>
          </div>
        </div>

        {/* Edge Model Card */}
        <div className="det-panel" style={{ borderTop: "3px solid #2563EB" }}>
          <div className="det-panel-body" style={{ padding: "12px 16px" }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#2563EB", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 4 }}>Live Stream Engine</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: "#0F172A", marginBottom: 12 }}>YOLOv8s (Edge Model)</div>
            
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <SpecRow label="Split Ratio" value="93 / 4 / 3" />
              <SpecRow label="Hyperparameter Tuning" value="Disabled (Generalized)" />
              <SpecRow label="Parameter Count" value="~11.2 Million" />
              <SpecRow label="Test mAP50" value="86.1% (Blind) | 92.9% (Ext)" highlight />
              <SpecRow label="Inference Speed" value="Ultra-Low Latency" />
              <SpecRow label="Spatial Logic" value="Person Filter + IoSA Dedup (Light)" />
              <SpecRow label="Tracking Logic" value="React Temporal Min-Filter" />
              <SpecRow label="Primary Target" value="Real-Time WebSockets" />
            </div>
          </div>
        </div>
      </div>

      {/* ── Dataset Information ── */}
      <div className="det-panel">
        <div className="det-panel-body" style={{ padding: "12px 16px" }}>
          
          <div style={{ fontSize: 14, fontWeight: 600, color: "#0F172A", marginBottom: "12px" }}>Dataset Specifications</div>
          
          <div style={{ display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap" }}>
            {/* Numbers on the Left */}
            <div style={{ display: "flex", gap: "16px", minWidth: "240px" }}>
              <div>
                <div style={{ fontSize: 10, color: "#64748B", textTransform: "uppercase", fontWeight: 600, marginBottom: 2 }}>Images</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: "#0F172A" }}>2,801</div>
              </div>
              <div style={{ width: "1px", background: "#E2E8F0" }}></div>
              <div>
                <div style={{ fontSize: 10, color: "#64748B", textTransform: "uppercase", fontWeight: 600, marginBottom: 2 }}>Classes</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: "#0F172A" }}>10</div>
              </div>
              <div style={{ width: "1px", background: "#E2E8F0" }}></div>
              <div>
                <div style={{ fontSize: 10, color: "#DC2626", textTransform: "uppercase", fontWeight: 600, marginBottom: 2 }}>Rules</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: "#B91C1C" }}>3 Strict</div>
              </div>
            </div>

            {/* Chips on the Right */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px", borderLeft: "2px solid #F1F5F9", paddingLeft: "16px", minWidth: "280px" }}>
              <div style={{ fontSize: 10, color: "#64748B", textTransform: "uppercase", fontWeight: 600 }}>Tracking Classes</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {["Hardhat", "Mask", "Safety Vest", "Person", "Safety Cone", "machinery", "vehicle"].map(c => (
                  <span key={c} style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", background: "#F8FAFC", color: "#475569", borderRadius: "4px", border: "1px solid #E2E8F0" }}>{c}</span>
                ))}
                {["NO-Hardhat", "NO-Mask", "NO-Safety Vest"].map(c => (
                  <span key={c} style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", background: "#FEF2F2", color: "#DC2626", borderRadius: "4px", border: "1px solid #FECACA" }}>{c}</span>
                ))}
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

function SpecRow({ label, value, highlight }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingBottom: "4px", borderBottom: "1px solid #F1F5F9" }}>
      <span style={{ fontSize: 11, color: "#64748B", fontWeight: 500 }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: highlight ? 700 : 600, color: highlight ? "#059669" : "#1E293B" }}>{value}</span>
    </div>
  )
}