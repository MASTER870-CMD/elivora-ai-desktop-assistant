# ELIVORA — Real-Time AI Voice & Vision Desktop Assistant

**Repo name:** `elivora-ai-desktop-assistant`

**Short description (for GitHub "About" box):**
> ELIVORA is a real-time, voice-controlled AI desktop assistant built in Python using Google's Gemini Live API. It sees your screen/camera, hears your voice, opens and closes apps, sends WhatsApp messages, writes files, and answers questions — all through natural conversation.

---

## 🧠 What is ELIVORA?

ELIVORA is a **JARVIS-style AI assistant** that runs locally on your Windows PC. It combines real-time voice conversation, live camera/screen vision, and system-level automation into a single desktop application — built entirely in Python.

Unlike simple chatbot wrappers, ELIVORA can **take real actions on your computer**: opening and closing applications, sending targeted WhatsApp messages, creating files, checking the weather, and searching the web — all triggered through natural spoken conversation, in any language.

## ✨ Key Features

| Feature | Description |
|---|---|
| 🎙️ Real-time voice conversation | Streams live audio to Google Gemini's multimodal Live API and speaks responses back naturally |
| 👁️ Live vision | Reads your webcam or screen share in real time and can answer questions about what it sees |
| 🖥️ App control | Opens and closes any installed Windows application by voice command (`open_application`, `close_application`) |
| 💬 WhatsApp automation | Sends WhatsApp messages to a specific contact via GUI automation, triggered by voice |
| 📝 File creation | Creates and writes files on demand through natural language |
| 🌦️ Live tool calling | Fetches real-time weather and runs web searches via Gemini function calling |
| 🌐 Multi-language | Understands and responds in multiple languages with natural, emotionally aware tone |
| 🔑 Key rotation | Automatically rotates across multiple API keys to avoid quota interruptions |
| 🖼️ Desktop UI | Runs as a standalone desktop app using `pywebview`, not just a terminal script |

## 🏗️ Tech Stack

- **Language:** Python 3
- **AI Model:** Google Gemini Live API (`gemini-live` multimodal streaming)
- **Async architecture:** `asyncio` with `TaskGroup` for concurrent audio, video, and text streams
- **Audio I/O:** `PyAudio`
- **Vision:** `OpenCV` (`cv2`), `Pillow`
- **System automation:** `pyautogui`, `psutil`, Windows `subprocess`/PowerShell for app discovery
- **Desktop UI:** `pywebview` + local HTTP server (`http.server`)
- **Function calling / tool use:** Gemini native tool-calling for weather, search, app control, file creation, WhatsApp

## 📂 How It Works (Architecture)

1. A local web server + `pywebview` window renders the desktop UI.
2. Background threads continuously scan installed apps, capture camera/screen frames, and measure latency.
3. An async `AudioLoop` streams microphone audio and video frames to Gemini's Live API in real time.
4. When the AI decides an action is needed (open an app, send a WhatsApp message, create a file, check weather), it triggers a **function call**, which is executed locally and the result is sent back into the conversation — so the AI can respond naturally about what it just did.
5. Audio responses are streamed back and played instantly, creating a natural back-and-forth conversation.

## 🚀 Getting Started

### Prerequisites
```bash
pip install pyaudio opencv-python pillow psutil pywebview numpy pyautogui google-genai
```

### Setup
1. Clone the repo:
   ```bash
   git clone https://github.com/MASTER870-CMD/elivora-ai-desktop-assistant.git
   cd elivora-ai-desktop-assistant
   ```
2. Create a `.env` file in the project root (see `.env.example`):
   ```
   GEMINI_API_KEY_1=your_key_here
   GEMINI_API_KEY_2=your_key_here
   GEMINI_API_KEY_3=your_key_here
   ```
3. Run it:
   ```bash
   python ap.py
   ```

> ⚠️ Never commit your real `.env` file or API keys. This repo's `.gitignore` excludes them by default.

## 🎯 Use Cases

- Hands-free desktop control for accessibility
- Voice-first productivity assistant
- Demonstration of real-time multimodal AI (voice + vision + tool use) in a working desktop app
- Foundation for building custom AI copilots / automation agents

## 🗺️ Roadmap

- [ ] Cross-platform support (macOS/Linux app control)
- [ ] Plugin system for custom voice commands
- [ ] Persistent conversation memory
- [ ] Packaged installer (.exe)

## 👤 About the Author

Built by **Shashank Gowda** — Diploma in Computer Technology & IT Infrastructure (NTTF), Bengaluru.
CCNA (Networking, Switching/Routing, Enterprise Security & Automation) | AWS Academy Cloud Operations | Cybersecurity & Endpoint Security certified.

- 🌐 Portfolio: [shashankgowdanb.netlify.app](https://shashankgowdanb.netlify.app/)
- 💻 GitHub: [@MASTER870-CMD](https://github.com/MASTER870-CMD)

---

### Keywords
`python ai assistant` · `gemini live api` · `voice controlled desktop app` · `real-time multimodal ai` · `whatsapp automation python` · `system automation python` · `jarvis clone python` · `ai agent function calling` · `pyautogui automation` · `bangalore python developer portfolio`
