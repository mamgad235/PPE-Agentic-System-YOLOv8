# 🏗️ PPE Detection for Construction Site Safety using YOLOv8

![Project Status](https://img.shields.io/badge/Status-Active-success)
![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![React](https://img.shields.io/badge/React-18-blue)
![YOLOv8](https://img.shields.io/badge/Model-YOLOv8-orange)

A real-time, web-based Deep Learning system designed to monitor safety compliance on construction sites. This project utilizes a custom-trained YOLOv8 architecture deployed across a dual-engine FastAPI backend to detect Personal Protective Equipment (PPE) in both static images and live video feeds.

## 📸 Application Interface

### Analytics Dashboard
Aggregates statistics across all sessions, tracking total incidents and overall site safety metrics.
> <img width="1894" height="905" alt="webapp_dashboard" src="https://github.com/user-attachments/assets/a7807fac-8a42-447d-a895-d3c21778dbff" />

### Image Detection (Static Analysis)
High-accuracy processing of uploaded images powered by the YOLOv8m Core Engine, providing instant visual feedback that separates "Safe" compliance from "Alert" violations.
> <img width="1899" height="908" alt="webapp_safe" src="https://github.com/user-attachments/assets/59d84945-55ae-4f6a-8317-5578edace747" />

> <img width="1900" height="905" alt="webapp_alert" src="https://github.com/user-attachments/assets/4ab0cbe3-2a60-4d33-ad57-69426f273404" />

### Session History
A searchable, filterable log of all detected individuals and compliance events.
> <img width="1899" height="905" alt="webapp_history" src="https://github.com/user-attachments/assets/0764fd92-e189-44f2-b427-dfdff018e924" />

---

## 🌐 Interactive Web Application Features
The system features a fully responsive React frontend designed for safety managers to monitor compliance in real-time:
* **Live Detection Hub:** View webcam streams or upload static images, with instant visual feedback separating "Safe" compliance from "Alert" violations.
* **Session History:** A searchable log of all detected individuals, filterable by Compliant vs. Violation statuses.
* **Analytics Dashboard:** Aggregate statistics and charts tracking total incidents and overall site safety metrics.

## 🧠 System Architecture
This system utilizes an **Asymmetric Deployment** routing engine to balance latency and accuracy:
* **Core Engine (Static/Video):** Powered by `YOLOv8m`. Highly tuned on an 80/15/5 split using a custom nested-box Intersection over Smaller Area (IoSA) logic. Optimized for high-throughput batch processing of static uploads.
* **Edge Engine (Live Stream):** Powered by `YOLOv8s`. A lightweight, latency-optimized model running via WebSockets with React temporal min-filtering for real-time webcam streams.

### Target Classes
Detects 10 specific classes across 3 strict compliance rules:
* **Compliant:** `Hardhat`, `Mask`, `Safety Vest`
* **Violations:** `NO-Hardhat`, `NO-Mask`, `NO-Safety Vest`
* **Contextual:** `Person`, `Safety Cone`, `machinery`, `vehicle`

## 🚀 Quick Start Guide

### 1. Backend Setup (FastAPI)
Navigate to the backend directory, initialize a virtual environment, and install dependencies:

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**Run the Backend Server:**

```bash
fastapi dev main.py
```
*The API will be available at http://127.0.0.1:8000*

### 2. Frontend Setup (React)
Open a new terminal, navigate to the frontend directory, and install the Node modules:

```bash
cd frontend
npm install
```

**Run the Frontend Development Server:**

```bash
npm run dev
```
*The web application will launch at http://localhost:5173*
