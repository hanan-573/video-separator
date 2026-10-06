<!-- ============================================================
     VIDEO SEPARATOR - README
     ============================================================ -->

<div align="center">

# 🎬 Video Separator

### Extract high-quality audio from any video — in seconds.

A professional, network-accessible web tool that extracts the audio track from any video file and saves it as a standalone **MP3 (320 kbps)** or **WAV (lossless)** file — named identically to the source video.

<!-- ==================== SHIELDS ==================== -->
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0.0-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Node.js](https://img.shields.io/badge/Node.js-16%2B-339933?style=for-the-badge&logo=node.js&logoColor=white)](https://nodejs.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Required-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![Conda](https://img.shields.io/badge/Conda-Environment-44A833?style=for-the-badge&logo=anaconda&logoColor=white)](https://docs.conda.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-blue?style=for-the-badge)]()
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge)]()

<!-- ==================== QUICK LINKS ==================== -->
[Features](#-features) •
[Requirements](#-requirements) •
[Installation](#-installation-conda-only) •
[Usage](#-how-to-start) •
[API](#-api-reference) •
[Troubleshooting](#-troubleshooting) •
[Docker](#-docker-optional)

</div>

---

## 📖 Table of Contents

- [✨ Features](#-features)
- [🧰 Requirements](#-requirements)
- [⚙️ Installation (Conda only)](#-installation-conda-only)
- [🚀 How to Start](#-how-to-start)
- [🛑 How to Stop](#-how-to-stop)
- [💻 Access from Another Computer](#-access-from-another-computer)
- [📱 Access from a Phone](#-access-from-a-phone)
- [🎞️ Supported Formats](#️-supported-video-formats)
- [🎵 Output Audio Formats](#-output-audio-formats)
- [🏗️ Architecture](#️-architecture)
- [🔌 API Reference](#-api-reference)
- [🐳 Docker (optional)](#-docker-optional)
- [🛠️ Troubleshooting](#️-troubleshooting)
- [📄 License](#-license)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📤 **Drag & Drop Upload** | Drop a video file or click to browse |
| 🎞️ **Wide Format Support** | MP4, MKV, AVI, MOV, WMV, FLV, WEBM, M4V, TS, 3GP |
| 🎵 **Dual Output** | **MP3 (320 kbps)** or **WAV (lossless PCM)** |
| 📛 **Smart Naming** | Output keeps the **same base name** as the video (`holiday.mp4 → holiday.mp3`) |
| 📡 **Live Progress (SSE)** | Real-time Server-Sent Events for extraction status |
| 📋 **Output List** | Size, status, timestamp, and download button per file |
| 🔄 **One-Click Refresh** | Resync task list without reloading the page |
| 📲 **Mobile Access** | Fully responsive UI (desktop, tablet, Android, iPhone) |
| 🌊 **Animated Background** | Subtle, project-related audio-wave animation |
| 🔐 **Safe Uploads** | Filename sanitisation + safe subprocess handling |
| 🌐 **LAN-Ready** | Accessible from any device on the same Wi-Fi/LAN |
| ⚡ **Single Command** | `python start.py` — that's it |

---

## 🧰 Requirements

<div align="center">

| Tool | Version | Purpose |
|:-----|:--------|:--------|
| 🐍 **Python** | **3.10 or 3.11** (via **Conda** — *not* venv) | Backend logic & audio extraction |
| 🧪 **Conda** | Latest (Miniconda or Anaconda) | Python environment isolation |
| 🟩 **Node.js** | **16+** with npm | Frontend server & proxy |
| 🎬 **FFmpeg** | Latest | Audio extraction engine |
| 🌐 **Browser** | Modern (Chrome, Firefox, Edge, Safari) | User interface |

</div>

> ⚠️ **Important:** This project uses **Conda exclusively** for Python environment isolation. Virtual environments (`venv`, `.venv`, `virtualenv`) are **not supported**.

---

## ⚙️ Installation (Conda only)

### 1️⃣ Create and activate the Conda environment

```bash
conda create -n video_separator python=3.11 -y
conda activate video_separator