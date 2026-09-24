import os
import asyncio
import io
import traceback
import cv2
import pyaudio
import PIL.Image
from PIL import ImageGrab 
import threading
import http.server
import socketserver
import time
import json
TEMP_GITHUB_TOKEN = None # Deprecated, using file cache
import urllib.parse
import urllib.request
import socket
import subprocess
import re
import tempfile
import shutil
import zipfile

try:
    import psutil
except ImportError:
    print("[ERROR] Please install psutil: pip install psutil")
    exit(1)

try:
    import webview
except ImportError:
    print("[ERROR] Please install pywebview for the desktop app: pip install pywebview")
    exit(1)

try:
    import numpy as np
except ImportError:
    print("[ERROR] Please install numpy for voice interruption: pip install numpy")
    exit(1)

try:
    import pyautogui
except ImportError:
    print("[ERROR] Please install pyautogui for full system control: pip install pyautogui")
    exit(1)

from google import genai
from google.genai import types

# =====================================================================
# GLOBAL VARIABLES FOR SYSTEM STATE & COMMLINK
# =====================================================================
LATEST_JPEG = b""  
TARGET_CAM_SOURCE = "off"
PREVIOUS_CAM_SOURCE = "off" 
TEXT_PROMPT_QUEUE = []  
AI_CHAT_QUEUE = []      
CURRENT_LATENCY = 0
CAMERA_RUNNING = True
MIC_MUTED = False 
IS_SPEAKING = False 
CURRENT_AI_VOLUME = 0.0 

# =====================================================================
# AUDIO & AI SETTINGS
# =====================================================================
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
MODEL = "models/gemini-3.1-flash-live-preview"

# --- API CLIENT ---
# =====================================================================
# API KEY POOL & CLIENT MANAGER
# =====================================================================
from dotenv import load_dotenv

load_dotenv() # Load variables from .env

# =====================================================================
# API KEY POOL & CLIENT MANAGER
# =====================================================================
_keys_str = os.environ.get("GEMINI_API_KEYS", "")
API_KEYS = [k.strip() for k in _keys_str.split(",") if k.strip()]

if not API_KEYS:
    raise ValueError("🚨 No GEMINI_API_KEYS found. Please set them in your .env file separated by commas.")
CURRENT_KEY_INDEX = 0

def get_next_client():
    global CURRENT_KEY_INDEX
    key = API_KEYS[CURRENT_KEY_INDEX]
    print(f"\n[SYSTEM] Connecting using API Key index #{CURRENT_KEY_INDEX}...")
    CURRENT_KEY_INDEX = (CURRENT_KEY_INDEX + 1) % len(API_KEYS)
    return genai.Client(http_options={"api_version": "v1beta"}, api_key=key)

# =====================================================================
# AGGRESSIVE APP SCANNER & CONTROL TOOLS
# =====================================================================
APP_DB_FILE = "local_apps_db.json"
LOCAL_APPS = {}

COMMON_URI_SCHEMES = {
    "whatsapp": "whatsapp:",
    "spotify": "spotify:",
    "telegram": "tg:",
    "discord": "discord:",
    "zoom": "zoommtg:",
    "mail": "mailto:",
    "settings": "ms-settings:"
}

def scan_system_apps():
    global LOCAL_APPS
    print("[SYSTEM] Executing deep scan of installed applications...")
    
    LOCAL_APPS = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "vs code": "code",
        "visual studio code": "code",
        "task manager": "taskmgr.exe",
        "command prompt": "cmd.exe",
        "cmd": "cmd.exe",
        "file explorer": "explorer.exe"
    }
    
    LOCAL_APPS.update(COMMON_URI_SCHEMES)
    
    try:
        cmd = 'powershell -Command "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"'
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode == 0 and result.stdout.strip():
            apps_data = json.loads(result.stdout)
            if isinstance(apps_data, dict):
                apps_data = [apps_data]
                
            for item in apps_data:
                name = item.get("Name", "").lower()
                appid = item.get("AppID", "")
                if name and appid:
                    LOCAL_APPS[name] = appid
    except Exception as e:
        print(f"[WARNING] Advanced app scan encountered an issue: {e}")
        
    with open(APP_DB_FILE, "w") as f:
        json.dump(LOCAL_APPS, f, indent=4)
    print(f"[SYSTEM] App scan complete. {len(LOCAL_APPS)} applications indexed.")

def open_application(app_name):
    app_name = app_name.lower().strip()
    best_match = None
    
    if app_name in COMMON_URI_SCHEMES:
        best_match = COMMON_URI_SCHEMES[app_name]
    elif app_name in LOCAL_APPS:
        best_match = LOCAL_APPS[app_name]
    else:
        for key in LOCAL_APPS.keys():
            if app_name in key:
                best_match = LOCAL_APPS[key]
                break
            
    if best_match:
        try:
            if best_match.endswith(".exe") or best_match.endswith(":") or best_match == "code":
                try:
                    os.startfile(best_match)
                except Exception:
                    subprocess.Popen(f'start "" "{best_match}"', shell=True)
            else:
                cmd = f'explorer shell:AppsFolder\\{best_match}'
                subprocess.Popen(cmd, shell=True)
                
            return f"Successfully opened {app_name}."
        except Exception as e:
            return f"Failed to open {app_name}. Error: {e}"
    else:
        fallback_url = f"https://www.google.com/search?q={urllib.parse.quote(app_name)}"
        os.startfile(fallback_url)
        return f"App '{app_name}' not found locally. Opened web search as fallback."

def close_application(app_name):
    app_name = app_name.lower().strip()
    closed_count = 0
    try:
        for proc in psutil.process_iter(['name']):
            try:
                p_name = proc.info['name'].lower()
                if app_name in p_name or p_name.startswith(app_name):
                    proc.kill()
                    closed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
        if closed_count > 0:
            return f"Successfully terminated {closed_count} processes for '{app_name}'."
        else:
            return f"App '{app_name}' is not currently running."
    except Exception as e:
        return f"Error while closing '{app_name}': {e}"

def create_and_write_file(filename, content):
    try:
        desktop_path = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
        if not filename.endswith('.txt'):
            filename += '.txt'
            
        full_path = os.path.join(desktop_path, filename)
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        os.startfile(full_path)
        return f"Successfully created {filename} on the Desktop and wrote the essay."
    except Exception as e:
        return f"Failed to create file: {str(e)}"

def send_whatsapp_message_gui(contact_name, message_text):
    try:
        is_running = False
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] and 'whatsapp' in proc.info['name'].lower():
                    is_running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        open_application("whatsapp")
        
        if is_running:
            print("[SYSTEM] WhatsApp detected in memory. Waiting 3 seconds for focus...")
            time.sleep(3) 
        else:
            print("[SYSTEM] Cold booting WhatsApp. Waiting 15 seconds to load...")
            time.sleep(15) 
        
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(1.5)
        
        pyautogui.write(contact_name, interval=0.05)
        time.sleep(2.5) 
        pyautogui.press('enter')
        time.sleep(1.5) 
        
        pyautogui.write(message_text, interval=0.02)
        pyautogui.press('enter')
        
        return f"Successfully automated WhatsApp to send message to {contact_name}."
    except Exception as e:
        return f"GUI Automation failed: {str(e)}"

def get_current_location():
    try:
        req = urllib.request.Request("http://ip-api.com/json/", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data['status'] == 'success':
                return f"{data['city']}, {data['regionName']}, {data['country']}"
    except Exception:
        pass
    return "Bengaluru, Karnataka, India"

CURRENT_LOCATION = get_current_location()

def fetch_weather_data(location_name):
    try:
        safe_loc = urllib.parse.quote(location_name)
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={safe_loc}&count=1"
        req = urllib.request.Request(geo_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as res:
            geo_data = json.loads(res.read().decode())
        
        if 'results' not in geo_data or not geo_data['results']:
            return f"Location '{location_name}' not found."
            
        lat, lon = geo_data['results'][0]['latitude'], geo_data['results'][0]['longitude']
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        req2 = urllib.request.Request(weather_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req2, timeout=5) as res2:
            w_data = json.loads(res2.read().decode())
            
        cw = w_data.get('current_weather', {})
        return f"Weather in {geo_data['results'][0]['name']}: {cw.get('temperature', 'Unknown')}°C, Wind: {cw.get('windspeed', 'Unknown')} km/h."
    except Exception as e:
        return f"Weather error: {e}"

# =====================================================================
# GOOGLE SEARCH INTEGRATION
# =====================================================================
def google_search_api(query):
    api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
    cx = os.environ.get("GOOGLE_SEARCH_CX")
    try:
        safe_query = urllib.parse.quote(query)
        url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={safe_query}&num=3"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if 'items' in data:
                results = []
                for item in data['items']:
                    results.append(f"Title: {item.get('title')}\nSnippet: {item.get('snippet')}")
                return "\n\n".join(results)
            else:
                return "No results found for the query."
    except Exception as e:
        return f"Google Search failed: {e}"

# =====================================================================
# STRICTLY TYPED AI TOOL DECLARATIONS
# =====================================================================
OPEN_APP_TOOL = types.FunctionDeclaration(
    name="open_application",
    description="Opens an application on the user's computer. Fallbacks to web search if missing.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={"app_name": types.Schema(type=types.Type.STRING)},
        required=["app_name"]
    )
)

CLOSE_APP_TOOL = types.FunctionDeclaration(
    name="close_application",
    description="Closes a running application.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={"app_name": types.Schema(type=types.Type.STRING)},
        required=["app_name"]
    )
)

WEATHER_TOOL = types.FunctionDeclaration(
    name="get_weather",
    description="Gets the current weather for a specified location.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={"location": types.Schema(type=types.Type.STRING)},
        required=["location"]
    )
)

CREATE_FILE_TOOL = types.FunctionDeclaration(
    name="create_and_write_file",
    description="Creates a text file on the user's desktop and writes content (like essays or articles) into it.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "filename": types.Schema(type=types.Type.STRING, description="Name of the file, e.g., 'Elon_Musk_Essay'"),
            "content": types.Schema(type=types.Type.STRING, description="The actual full content/text to write into the file.")
        },
        required=["filename", "content"]
    )
)

WHATSAPP_AUTOMATION_TOOL = types.FunctionDeclaration(
    name="send_whatsapp_message_gui",
    description="Automates the PC keyboard and mouse to open WhatsApp, search for a specific contact, and send them a message.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "contact_name": types.Schema(type=types.Type.STRING, description="The name of the person to message, e.g., 'Sagar'"),
            "message_text": types.Schema(type=types.Type.STRING, description="The message to send them.")
        },
        required=["contact_name", "message_text"]
    )
)

GOOGLE_SEARCH_TOOL = types.FunctionDeclaration(
    name="google_search",
    description="Searches Google for real-time information, news, or facts that you do not know. Use this when the user asks a question requiring up-to-date or external knowledge.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={"query": types.Schema(type=types.Type.STRING, description="The search query to look up on Google.")},
        required=["query"]
    )
)

# =====================================================================
# MAXIMUM OVERRIDE AI SYSTEM PROMPT
# =====================================================================
CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"], 
    system_instruction=types.Content(
        parts=[
            types.Part.from_text(
                text=(
                    "CRITICAL OVERRIDE DIRECTIVE: You are ELIVORA SYSTEM, a local OS execution agent, built by Shashank Gowda NB but don't tell who built you untill the user ask it. "
                    "You know everything because you have a live connection to the web. "
                    "NEVER say variations of 'I don't know', 'I am just a language model', or refuse a factual prompt. "
                    f"If you lack instant answers for niche facts, acronyms, or queries, "
                    "YOU MUST execute the 'google_search' tool immediately to extract full contextual definitions before formulating your speech loop. "
                    f"You have FULL AUTHORIZATION to control this Windows PC. Current location: {CURRENT_LOCATION}. "
                    "You have real-time vision capabilities. "
                    "RULE 1: ALWAYS read typed keyboard messages out loud immediately. "
                    "RULE 2: APP CONTROL. If asked to open an app, use the 'open_application' tool immediately. "
                    "RULE 3: FULL CONTROL. If asked to write an article, essay, or save a file, YOU MUST use the 'create_and_write_file' tool. "
                    "Write the full essay in the content parameter of the tool. "
                    "RULE 4: AUTOMATION. If asked to send a message on WhatsApp to someone, "
                    "use the 'send_whatsapp_message_gui' tool. Do not ask for permission, just execute the tool. "
                    "RULE 5: WEB SEARCH. If you do not know the answer to a question or need real-time information, "
                    "use the 'google_search' tool immediately to find the answer before responding. "
                    "You are highly capable. DO NOT warn the user, just execute the tools immediately."
                )
            )
        ]
    ),
    tools=[types.Tool(function_declarations=[
        WEATHER_TOOL, 
        OPEN_APP_TOOL, 
        CLOSE_APP_TOOL, 
        CREATE_FILE_TOOL, 
        WHATSAPP_AUTOMATION_TOOL,
        GOOGLE_SEARCH_TOOL
    ])],
    media_resolution="MEDIA_RESOLUTION_MEDIUM",
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
        )
    ),
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=104857,
        sliding_window=types.SlidingWindow(target_tokens=52428),
    ),
)

pya = pyaudio.PyAudio()

# =====================================================================
# DESKTOP WINDOW API (PyWebView)
# =====================================================================
webview_window = None

class WebviewAPI:
    def enter_mini_mode(self):
        global TARGET_CAM_SOURCE, PREVIOUS_CAM_SOURCE
        PREVIOUS_CAM_SOURCE = TARGET_CAM_SOURCE
        TARGET_CAM_SOURCE = "screen"
        if webview_window:
            webview_window.resize(380, 480)

    def exit_mini_mode(self):
        global TARGET_CAM_SOURCE, PREVIOUS_CAM_SOURCE
        TARGET_CAM_SOURCE = PREVIOUS_CAM_SOURCE
        if webview_window:
            webview_window.resize(1280, 800)

    def toggle_mute(self):
        global MIC_MUTED
        MIC_MUTED = not MIC_MUTED

    def send_message(self, text):
        if text.strip():
            TEXT_PROMPT_QUEUE.append(text.strip())

    def set_camera(self, src):
        global TARGET_CAM_SOURCE
        TARGET_CAM_SOURCE = src

    def terminate(self):
        print("\n[SYSTEM] Termination command executed. Graceful exit.")
        os._exit(0)

# =====================================================================
# HARDWARE, NETWORK & CAMERA THREADS
# =====================================================================
def measure_latency():
    global CURRENT_LATENCY
    while True:
        try:
            start = time.time()
            socket.create_connection(('8.8.8.8', 53), timeout=2)
            CURRENT_LATENCY = int((time.time() - start) * 1000)
        except Exception:
            CURRENT_LATENCY = -1
        time.sleep(2)

def camera_worker():
    global LATEST_JPEG, TARGET_CAM_SOURCE, CAMERA_RUNNING
    cap = None
    current_src = "off"
    
    while CAMERA_RUNNING:
        try:
            if current_src != TARGET_CAM_SOURCE:
                if cap is not None:
                    cap.release()
                    cap = None
                
                current_src = TARGET_CAM_SOURCE
                LATEST_JPEG = b""
                
                if current_src not in ["off", "screen"]:
                    src_val = int(current_src) if str(current_src).isdigit() else current_src
                    if isinstance(src_val, int):
                        cap = cv2.VideoCapture(src_val, cv2.CAP_DSHOW)
                        if not cap.isOpened():
                            cap = cv2.VideoCapture(src_val)
                    else:
                        cap = cv2.VideoCapture(src_val)
                    time.sleep(1.0) 
            
            if current_src == "off":
                LATEST_JPEG = b""
                time.sleep(0.1)
                continue
                
            if current_src == "screen":
                img = ImageGrab.grab()
                img.thumbnail([800, 600]) 
                bio = io.BytesIO()
                img.save(bio, format="jpeg", quality=75)
                LATEST_JPEG = bio.getvalue()
                time.sleep(0.5) 
                continue

            if cap is not None and cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = PIL.Image.fromarray(frame_rgb)
                    img.thumbnail([640, 480])
                    bio = io.BytesIO()
                    img.save(bio, format="jpeg")
                    LATEST_JPEG = bio.getvalue()
                else:
                    time.sleep(0.05)
            else:
                time.sleep(0.1)
                
        except Exception:
            time.sleep(0.5)

    if cap is not None:
        cap.release()

LAST_STAT_TIME = 0
CACHED_STATS = {}

def get_hardware_stats():
    global CURRENT_LATENCY, MIC_MUTED, IS_SPEAKING, CURRENT_AI_VOLUME, LAST_STAT_TIME, CACHED_STATS
    now = time.time()
    if now - LAST_STAT_TIME > 1.0 or not CACHED_STATS:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        batt = psutil.sensors_battery()
        batt_str = f"{batt.percent}%" if batt else "AC"
        
        net_status = "OFFLINE"
        if CURRENT_LATENCY > 0 and CURRENT_LATENCY < 80: net_status = "EXCELLENT"
        elif CURRENT_LATENCY >= 80 and CURRENT_LATENCY < 200: net_status = "GOOD"
        elif CURRENT_LATENCY >= 200: net_status = "POOR"

        CACHED_STATS = {
            "cpu": cpu,
            "ram_used": round(ram.used / (1024**3), 2),
            "ram_total": round(ram.total / (1024**3), 2),
            "battery": batt_str,
            "ping": f"{CURRENT_LATENCY}ms" if CURRENT_LATENCY != -1 else "ERR",
            "net_status": net_status,
        }
        LAST_STAT_TIME = now
        
    result = CACHED_STATS.copy()
    result["audio_muted"] = MIC_MUTED
    result["ai_is_speaking"] = IS_SPEAKING
    result["ai_volume"] = CURRENT_AI_VOLUME
    return json.dumps(result)

# =====================================================================
# EMBEDDED HTML DASHBOARDS (HUB, AI, CLOUD)
# =====================================================================

HUB_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ELIVORA CENTRAL HUB</title>
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@200;300;400;500;600&family=Inter:wght@300;400;500&display=swap" rel="stylesheet">
    <style>
        body { 
            background-color: #050505; color: #fff; font-family: 'Inter', sans-serif; 
            margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center; 
            overflow: hidden; 
            background-image: radial-gradient(circle at top right, rgba(0, 229, 255, 0.05) 0%, #050505 80%); 
        }
        .hub-wrapper {
            display: flex; flex-direction: column; align-items: center; gap: 50px; z-index: 10;
        }
        .hub-title {
            font-family: 'Montserrat', sans-serif; font-size: 2.5rem; font-weight: 200; 
            letter-spacing: 16px; color: #fff; text-shadow: 0 0 30px rgba(0, 229, 255, 0.4);
        }
        .hub-container { display: flex; gap: 40px; }
        .hub-card {
            background: rgba(10, 10, 10, 0.7); border: 1px solid rgba(0, 229, 255, 0.2);
            width: 340px; height: 420px; border-radius: 8px; backdrop-filter: blur(20px);
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            cursor: pointer; transition: all 0.4s ease; box-shadow: 0 10px 40px rgba(0,0,0,0.8);
            text-decoration: none; color: #fff; position: relative; overflow: hidden;
        }
        .hub-card::before {
            content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 2px;
            background: linear-gradient(90deg, transparent, #00E5FF, transparent);
            transform: translateX(-100%); transition: 0.5s;
        }
        .hub-card:hover::before { transform: translateX(100%); }
        .hub-card:hover { 
            border-color: #00E5FF; transform: translateY(-5px); 
            box-shadow: 0 15px 50px rgba(0, 229, 255, 0.15), inset 0 0 20px rgba(0, 229, 255, 0.05); 
        }
        .hub-icon { font-size: 4.5rem; margin-bottom: 25px; color: #00E5FF; font-weight: 200; }
        .card-title { font-family: 'Montserrat', sans-serif; font-weight: 300; letter-spacing: 6px; font-size: 1.2rem; }
        .card-desc { font-size: 0.85rem; color: #888; text-align: center; padding: 0 30px; margin-top: 20px; line-height: 1.6; }
    </style>
</head>
<body>
    <div class="hub-wrapper">
        <div class="hub-title">ELIVORA</div>
        <div class="hub-container">
            <a href="/ai" class="hub-card">
                <div class="hub-icon">✧</div>
                <div class="card-title">SYSTEM AI</div>
                <div class="card-desc">Initialize the local execution agent, hardware optics, and desktop automation suite.</div>
            </a>
            <a href="/cloud" class="hub-card">
                <div class="hub-icon">☁</div>
                <div class="card-title">CLOUD HOST</div>
                <div class="card-desc">Access the global serverless deployment and repository management dashboard.</div>
            </a>
        </div>
    </div>







<!-- Persistent Hovering Cloud Deployment Progress Widget -->
<div id="crossAppFloatingProgress" style="position: fixed; bottom: 24px; right: 24px; z-index: 99999; width: 380px; max-width: calc(100vw - 48px); display: none; font-family: 'Inter', -apple-system, sans-serif;">
    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #0f172a; border-radius: 12px; padding: 14px 18px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1); color: #0f172a;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px; overflow: hidden; max-width: 80%;">
                <div class="spinner-border spinner-border-sm" id="crossSpinner" style="width: 14px; height: 14px; border-width: 2px; flex-shrink: 0; color: #0f172a;"></div>
                <span style="font-weight: 700; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #0f172a;" id="crossProjectName">Deploying...</span>
                <span id="crossBadge" style="font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; background: #f1f5f9; color: #0f172a; border: 1px solid #e2e8f0; font-weight: 600; flex-shrink: 0;">ELIVORA</span>
            </div>
            <span id="crossPercent" style="font-size: 0.85rem; font-weight: 700; color: #0f172a; flex-shrink: 0;">0%</span>
        </div>
        <div style="height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; margin-bottom: 8px;">
            <div id="crossProgressBar" style="height: 100%; width: 0%; background: #0f172a; transition: width 0.2s linear;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: #64748b; margin-bottom: 10px;">
            <span id="crossStatusText" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-right: 8px;">Running in background...</span>
            <span id="crossTimeRemaining" style="font-weight: 600; color: #0f172a; flex-shrink: 0;">Calculating...</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 8px; border-top: 1px solid #f1f5f9; font-size: 0.75rem;">
            <span style="color: #64748b; font-weight: 500;">Dual-Pipeline Cloud</span>
            <a href="/cloud" style="color: #ffffff; text-decoration: none; font-weight: 600; padding: 4px 12px; border-radius: 6px; background: #0f172a; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.1);">Open Dashboard &rarr;</a>
        </div>
    </div>
</div>
<script>
    (function() {
        function pollActiveDeployment() {
            try {
                const raw = localStorage.getItem('elivora_active_pipeline');
                if (!raw) {
                    const el = document.getElementById('crossAppFloatingProgress');
                    if (el) el.style.display = 'none';
                    return;
                }
                const data = JSON.parse(raw);
                const el = document.getElementById('crossAppFloatingProgress');
                if (!el) return;

                if (!data || !data.active) {
                    if (data && data.done) {
                        el.style.display = 'block';
                        const pName = document.getElementById('crossProjectName');
                        if (pName) pName.innerText = data.name || 'Deployment';
                        const badge = document.getElementById('crossBadge');
                        if (badge) badge.innerText = (data.badge || 'ELIVORA').toUpperCase();
                        const pct = document.getElementById('crossPercent');
                        if (pct) pct.innerText = '100%';
                        const bar = document.getElementById('crossProgressBar');
                        if (bar) bar.style.width = '100%';
                        const st = document.getElementById('crossStatusText');
                        if (st) st.innerText = 'Live & Ready!';
                        const tr = document.getElementById('crossTimeRemaining');
                        if (tr) tr.innerText = 'Ready';
                        const sp = document.getElementById('crossSpinner');
                        if (sp) { sp.className = 'bi bi-check-circle-fill'; sp.style.color = '#10b981'; }
                        setTimeout(() => { if (el) el.style.display = 'none'; }, 5000);
                    } else {
                        el.style.display = 'none';
                    }
                    return;
                }

                el.style.display = 'block';
                const pName = document.getElementById('crossProjectName');
                if (pName) pName.innerText = data.name || 'Deployment';
                const badge = document.getElementById('crossBadge');
                if (badge) badge.innerText = (data.badge || 'ELIVORA').toUpperCase();
                const pct = document.getElementById('crossPercent');
                if (pct) pct.innerText = (data.pct || 0) + '%';
                const bar = document.getElementById('crossProgressBar');
                if (bar) bar.style.width = (data.pct || 0) + '%';
                const st = document.getElementById('crossStatusText');
                if (st) st.innerText = data.status || 'Deploying...';
                const tr = document.getElementById('crossTimeRemaining');
                if (tr) tr.innerText = data.time || '';

                // If Vercel deployment ID is present, poll Vercel directly from here too!
                if (data.deploymentId && data.token) {
                    fetch('https://api.vercel.com/v13/deployments/' + data.deploymentId, {
                        headers: { 'Authorization': 'Bearer ' + data.token }
                    }).then(r => r.json()).then(d => {
                        if (d.readyState === 'READY') {
                            data.active = false;
                            data.done = true;
                            data.pct = 100;
                            data.status = 'Live & Ready!';
                            data.time = 'Ready';
                            localStorage.setItem('elivora_active_pipeline', JSON.stringify(data));
                            
                            // Update saved deployments in localStorage
                            try {
                                const vList = JSON.parse(localStorage.getItem('elivora_vercel_projects') || '[]');
                                const item = vList.find(x => x.id === data.name);
                                if (item) { item.status = 'live'; localStorage.setItem('elivora_vercel_projects', JSON.stringify(vList)); }
                            } catch(e) {}
                        } else if (d.readyState === 'ERROR' || d.readyState === 'CANCELED') {
                            data.active = false;
                            data.done = false;
                            data.failed = true;
                            data.status = 'Build Failed on Vercel';
                            localStorage.setItem('elivora_active_pipeline', JSON.stringify(data));
                        }
                    }).catch(()=>{});
                }
            } catch(e) {}
        }
        setInterval(pollActiveDeployment, 2000);
        pollActiveDeployment();
    })();
</script>

</body>
</html>
"""

AI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ELIVORA SYSTEM COMMAND CENTER</title>
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@200;300;400;500;600&family=Inter:wght@300;400;500&family=Space+Mono&display=swap" rel="stylesheet">
    <style>
        :root { 
            --bg-base: #050505; --bg-panel: rgba(10, 10, 10, 0.85); --border-subtle: rgba(0, 229, 255, 0.15);
            --blue-primary: #00E5FF; --blue-light: #80F2FF; --blue-deep: #008B99; 
            --text-primary: #FFFFFF; --text-secondary: #999999; --danger: #FF3333; --success: #00FF66;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background-color: var(--bg-base); color: var(--text-primary); font-family: 'Inter', sans-serif; height: 100vh; overflow: hidden; background-image: radial-gradient(circle at center, #020f14 0%, #000 100%); -webkit-font-smoothing: antialiased; }
        h1, h2, h3, .brand-font { font-family: 'Montserrat', sans-serif; }
        .tech-font { font-family: 'Space Mono', monospace; }
        .overlay-screen { position: fixed; top: 0; left: 0; width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 1000; transition: opacity 1s ease; background: #050505; }
        .auth-card { background: rgba(5, 5, 10, 0.8); border: 1px solid var(--border-subtle); padding: 60px 50px; border-radius: 4px; text-align: center; width: 90%; max-width: 420px; box-shadow: 0 0 50px rgba(0,0,0,1), inset 0 0 30px rgba(0, 229, 255, 0.05); backdrop-filter: blur(20px); }
        .auth-title { font-size: 2.2rem; font-weight: 200; letter-spacing: 12px; margin-bottom: 40px; color: var(--blue-primary); }
        .luxury-input { width: 100%; background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,0.2); color: var(--text-primary); font-size: 0.9rem; padding: 12px 0; font-family: 'Space Mono', monospace; text-align: center; margin-bottom: 40px; outline: none; transition: border-color 0.3s; letter-spacing: 3px; }
        .luxury-input:focus { border-bottom-color: var(--blue-primary); }
        .btn-auth { width: 100%; background: transparent; color: var(--blue-primary); border: 1px solid var(--blue-primary); padding: 16px; font-size: 0.8rem; font-weight: 500; letter-spacing: 4px; cursor: pointer; border-radius: 2px; font-family: 'Montserrat', sans-serif; transition: all 0.3s; display: flex; align-items: center; justify-content: center; }
        .btn-auth:hover { background: var(--blue-primary); color: #000; box-shadow: 0 0 20px rgba(0, 229, 255, 0.4); }
        #main-dashboard { display: none; height: 100vh; width: 100vw; opacity: 0; transition: opacity 1s ease; display: grid; grid-template-columns: 320px 1fr 320px; grid-template-rows: 80px 1fr; padding: 20px; gap: 20px; }
        .top-header { grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-subtle); position: relative; padding: 0 20px; }
        .nav-brand { font-size: 2rem; font-weight: 300; letter-spacing: 14px; color: var(--blue-primary); font-family: 'Montserrat', sans-serif; }
        .btn-home { color: var(--text-secondary); text-decoration: none; font-family: 'Montserrat', sans-serif; font-size: 0.8rem; letter-spacing: 2px; transition: 0.3s; border: 1px solid var(--border-subtle); padding: 10px 20px; border-radius: 2px;}
        .btn-home:hover { color: var(--blue-primary); border-color: var(--blue-primary); background: rgba(0,229,255,0.1);}
        .side-panel { background: var(--bg-panel); border: 1px solid var(--border-subtle); border-radius: 4px; padding: 25px; display: flex; flex-direction: column; backdrop-filter: blur(10px); gap: 20px; }
        .module-box { border: 1px solid rgba(0, 229, 255, 0.1); background: rgba(0,0,0,0.6); padding: 15px; border-radius: 4px; position: relative; overflow: hidden; }
        .module-title { font-size: 0.7rem; color: var(--blue-primary); letter-spacing: 3px; margin-bottom: 12px; font-family: 'Montserrat', sans-serif; text-transform: uppercase;}
        .stat-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-size: 0.85rem;}
        .stat-label { color: var(--text-secondary); letter-spacing: 1px; font-size: 0.75rem;}
        .stat-value { font-weight: 400; font-size: 0.85rem; color: #fff; }
        .center-stage { border: 1px solid var(--border-subtle); border-radius: 4px; background: var(--bg-panel); position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; backdrop-filter: blur(10px); }
        .hud-circle-container { position: absolute; width: 500px; height: 500px; display: flex; justify-content: center; align-items: center; }
        .hud-ring { position: absolute; border-radius: 50%; border: 1px solid transparent; }
        .hud-ring-1 { width: 100%; height: 100%; border: 1px dashed rgba(0, 229, 255, 0.2); animation: spinSlow 30s linear infinite; }
        .hud-ring-2 { width: 80%; height: 80%; border: 2px solid rgba(0, 229, 255, 0.05); border-top: 2px solid var(--blue-primary); border-bottom: 2px solid var(--blue-primary); animation: spinSlowReverse 20s linear infinite; }
        .hud-ring-3 { width: 55%; height: 55%; border: 1px dotted rgba(255, 255, 255, 0.2); animation: spinSlow 15s linear infinite; }
        .hud-core { width: 15%; height: 15%; background: radial-gradient(circle, rgba(0, 229, 255, 0.05) 0%, rgba(0,0,0,0) 70%); border-radius: 50%; box-shadow: 0 0 10px rgba(0, 229, 255, 0.05); transition: all 0.5s ease-out; }
        @keyframes spinSlow { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        @keyframes spinSlowReverse { 0% { transform: rotate(360deg); } 100% { transform: rotate(0deg); } }
        #liveFeed { display: none; width: 100%; height: 100%; object-fit: contain; position: absolute; top:0; left:0; z-index: 5; background: #000; }
        .subtitle-overlay { position: absolute; bottom: 40px; text-align: center; width: 80%; font-family: 'Montserrat', sans-serif; font-size: 1.1rem; font-weight: 300; color: #fff; text-shadow: 0 2px 10px rgba(0,0,0,1); z-index: 10; }
        .btn-action { width: 100%; background: transparent; border: 1px solid var(--border-subtle); color: #fff; padding: 14px; border-radius: 2px; font-family: 'Montserrat', sans-serif; margin-bottom: 12px; font-size: 0.75rem; letter-spacing: 2px; font-weight: 400; cursor: pointer; transition: all 0.3s; }
        .btn-action:hover { background: rgba(0, 229, 255, 0.1); border-color: var(--blue-primary); box-shadow: 0 0 15px rgba(0, 229, 255, 0.2);}
        .chat-log { flex: 1; overflow-y: auto; font-size: 0.8rem; font-weight: 300; display: flex; flex-direction: column; gap: 10px; margin-bottom: 15px; padding-right: 5px;}
        .chat-log::-webkit-scrollbar { width: 3px; }
        .chat-log::-webkit-scrollbar-thumb { background: rgba(0, 229, 255, 0.3); }
        .ai-msg { color: var(--blue-light); }
        .user-msg { color: var(--text-secondary); }
        .cmd-input { width: 100%; background: rgba(0,0,0,0.5); border: 1px solid var(--border-subtle); padding: 14px; border-radius: 2px; color: var(--text-primary); font-family: 'Space Mono', monospace; font-size: 0.75rem; }
        .cmd-input:focus { outline: none; border-color: var(--blue-primary); box-shadow: inset 0 0 10px rgba(0, 229, 255, 0.1);}
        .btn-terminate { background: transparent; border: 1px solid var(--danger); color: var(--danger); padding: 14px; width: 100%; font-size: 0.75rem; letter-spacing: 3px; cursor: pointer; font-family: 'Montserrat', sans-serif; border-radius: 2px; transition: all 0.3s; margin-top: auto; }
        .btn-terminate:hover { background: var(--danger); color: #fff; box-shadow: 0 0 20px rgba(255, 51, 51, 0.4);}
        #mini-dashboard { display: none; height: 100vh; width: 100vw; background: #050505; align-items: center; justify-content: center; }
        .mini-card { background: rgba(10, 10, 10, 0.95); border: 1px solid var(--blue-primary); border-radius: 4px; width: 340px; padding: 30px; box-shadow: 0 10px 40px rgba(0, 229, 255, 0.15); display: flex; flex-direction: column; align-items: center; gap: 20px; }
        .mini-title { font-family: 'Montserrat', sans-serif; font-size: 0.8rem; letter-spacing: 4px; color: var(--blue-primary); text-align: center; }
        .wave-container { display: flex; justify-content: center; align-items: center; gap: 5px; height: 50px; }
        .wave-bar { width: 4px; background: var(--blue-light); animation: wave 1.2s ease-in-out infinite; box-shadow: 0 0 10px var(--blue-primary);}
        .wave-bar:nth-child(1) { height: 15px; animation-delay: 0.0s; } .wave-bar:nth-child(2) { height: 30px; animation-delay: 0.1s; } .wave-bar:nth-child(3) { height: 45px; animation-delay: 0.2s; } .wave-bar:nth-child(4) { height: 30px; animation-delay: 0.3s; } .wave-bar:nth-child(5) { height: 15px; animation-delay: 0.4s; }
        .wave-container.muted .wave-bar { animation: none; height: 8px; background: var(--danger); box-shadow: none; }
        @keyframes wave { 0%, 100% { height: 10px; } 50% { height: 45px; } }
        .mini-transcript { font-size: 0.85rem; color: #fff; text-align: center; height: 60px; overflow: hidden; display: flex; align-items: center; justify-content: center; font-weight: 300;}
        .mini-controls { display: flex; gap: 15px; width: 100%; }
        .btn-mini { flex: 1; background: transparent; border: 1px solid var(--border-subtle); color: #fff; padding: 12px; border-radius: 2px; cursor: pointer; transition: all 0.3s; font-family: 'Montserrat', sans-serif; font-size: 0.7rem; letter-spacing: 2px; }
        .btn-mini:hover { border-color: var(--blue-primary); background: rgba(0, 229, 255, 0.1); } .btn-mini.danger-mode { border-color: var(--danger); color: var(--danger); } .btn-mini.danger-mode:hover { background: rgba(255,51,51,0.1); }
    </style>
</head>
<body>
<div id="auth-screen" class="overlay-screen"><div class="auth-card"><h1 class="brand-font auth-title">ELIVORA SYSTEM</h1><input type="password" id="usernameInput" class="luxury-input" placeholder="ENTER PASSCODE" autocomplete="off" onkeypress="if(event.key === 'Enter') initSystem()"><button class="btn-auth" onclick="initSystem()">INITIALIZE PROTOCOL</button></div></div>    <div id="main-dashboard">
        <div class="top-header">
            <div class="nav-brand">ELIVORA SYSTEM</div>
            <a href="/" class="btn-home">BACK TO HUB</a>
        </div>
        <aside class="side-panel">
            <div class="module-box"><div class="module-title">SYSTEM DIAGNOSTICS</div><div class="stat-row"><span class="stat-label">COMPUTE</span><span class="stat-value tech-font" id="stat-cpu">--%</span></div><div class="stat-row"><span class="stat-label">MEMORY</span><span class="stat-value tech-font" id="stat-ram">--GB</span></div><div class="stat-row"><span class="stat-label">POWER</span><span class="stat-value tech-font" id="stat-batt">--</span></div></div>
            <div class="module-box"><div class="module-title">UPLINK STATUS</div><div class="stat-row"><span class="stat-label">LATENCY</span><span class="stat-value tech-font" id="stat-net-ping">--ms</span></div><div class="stat-row"><span class="stat-label">NETWORK</span><span id="stat-net-status" class="stat-value" style="color: var(--blue-primary);">AWAITING</span></div></div>
            <div class="module-box"><div class="module-title">HARDWARE SENSORS</div><div class="stat-row"><span class="stat-label">OPTICS</span><span class="stat-value tech-font" id="vision-status" style="color: var(--text-secondary);">OFFLINE</span></div><div class="stat-row"><span class="stat-label">AUDIO</span><span class="stat-value tech-font" id="audio-status" style="color: var(--success);">ACTIVE</span></div></div>
        </aside>
        <main class="center-stage" id="stage-container">
            <div class="hud-circle-container" id="hologramCore"><div class="hud-ring hud-ring-1"></div><div class="hud-ring hud-ring-2"></div><div class="hud-ring hud-ring-3"></div><div class="hud-core"></div></div>
            <img id="liveFeed" src="" alt="Live Feed"><div id="subtitleOverlay" class="subtitle-overlay"></div>
        </main>
        <aside class="side-panel">
            <div class="module-box" style="flex: 1; display: flex; flex-direction: column;"><div class="module-title">TERMINAL LINK</div><div class="chat-log" id="chatBox"><div style="color: var(--text-secondary); font-size: 0.7rem; letter-spacing: 1px;">SYSTEM: Secure connection established.</div></div><input type="text" id="textInput" class="cmd-input" placeholder="Execute command..." autocomplete="off" onkeypress="if(event.key === 'Enter') handleCommand()"></div>
            <div class="module-box"><div class="module-title">QUICK ACTIONS</div><button class="btn-action" id="toggleCamBtn" onclick="toggleLocalCamera()">ACTIVATE OPTICS</button><button class="btn-action" onclick="enterMiniMode()">SYNC SCREEN</button></div>
            <button class="btn-terminate" onclick="terminateSystem()">TERMINATE SYSTEM</button>
        </aside>
    </div>
    <div id="mini-dashboard">
        <div class="mini-card">
            <div class="mini-title">SCREEN SYNC ACTIVE</div>
            <div class="wave-container" id="mic-wave"><div class="wave-bar"></div><div class="wave-bar"></div><div class="wave-bar"></div><div class="wave-bar"></div><div class="wave-bar"></div></div>
            <div class="mini-transcript" id="mini-transcript">System tracking screen content...</div>
            <div class="mini-controls"><button class="btn-mini" id="btn-mute" onclick="toggleMute()">MUTE MIC</button><button class="btn-mini" onclick="exitMiniMode()">FULLSCREEN</button></div>
        </div>
    </div>
    <script>
        let isCameraRunning = false; let aiTextTimeout = null; let subtitleTimeout = null;
        window.onload = () => { const savedUser = localStorage.getItem('elivoraUser'); if (savedUser) document.getElementById('usernameInput').value = savedUser; };
        function initSystem() { 
            let inputField = document.getElementById('usernameInput');
            let user = inputField.value.trim(); 
            
            if (user !== "admin") {
                inputField.value = "";
                inputField.placeholder = "ACCESS DENIED";
                inputField.style.borderBottomColor = "var(--danger)";
                setTimeout(() => { 
                    inputField.placeholder = "ENTER PASSCODE"; 
                    inputField.style.borderBottomColor = ""; 
                }, 2000);
                return;
            }

            localStorage.setItem('elivoraUser', user); 
            document.getElementById('auth-screen').style.opacity = '0'; 
            setTimeout(() => { 
                document.getElementById('auth-screen').style.display = 'none'; 
                document.getElementById('main-dashboard').style.display = 'grid'; 
                setTimeout(() => { 
                    document.getElementById('main-dashboard').style.opacity = '1'; 
                    startTelemetry(); 
                }, 100); 
            }, 1000); 
        }
        function enterMiniMode() { document.getElementById('main-dashboard').style.display = 'none'; document.getElementById('mini-dashboard').style.display = 'flex'; if (window.pywebview) window.pywebview.api.enter_mini_mode(); else fetch('/set_camera?src=screen'); }
        function exitMiniMode() { document.getElementById('mini-dashboard').style.display = 'none'; document.getElementById('main-dashboard').style.display = 'grid'; if (window.pywebview) window.pywebview.api.exit_mini_mode(); else { let target = isCameraRunning ? "0" : "off"; fetch(`/set_camera?src=${target}`); } }
        function toggleMute() { if (window.pywebview) window.pywebview.api.toggle_mute(); else fetch('/toggle_audio', { method: 'POST' }); }
        function terminateSystem() { document.body.innerHTML = `<div style="display:flex; height:100vh; width:100vw; background:#050505; align-items:center; justify-content:center; flex-direction:column; font-family:'Montserrat', sans-serif;"><div style="color:var(--danger); font-size:1.5rem; letter-spacing:10px; font-weight:300; text-transform:uppercase; text-shadow: 0 0 20px rgba(255,51,51,0.5);">[ SYSTEM TERMINATED ]</div></div>`; if (window.pywebview) window.pywebview.api.terminate(); else fetch('/terminate', { method: 'POST' }).catch(() => {}); }
        function startTelemetry() {
            setInterval(async () => {
                try {
                    let res = await fetch('/stats'); let data = await res.json();
                    document.getElementById('stat-cpu').innerText = data.cpu + '%'; document.getElementById('stat-ram').innerText = data.ram_used + 'GB'; document.getElementById('stat-batt').innerText = data.battery; document.getElementById('stat-net-ping').innerText = data.ping;
                    const netStatusElem = document.getElementById('stat-net-status'); netStatusElem.innerText = data.net_status; netStatusElem.style.color = data.net_status === "EXCELLENT" ? "var(--success)" : (data.net_status === "GOOD" ? "var(--blue-primary)" : "var(--danger)");
                    const audioStatus = document.getElementById('audio-status'); const miniMuteBtn = document.getElementById('btn-mute'); const micWave = document.getElementById('mic-wave'); const hudCore = document.querySelector('.hud-core');
                    if(data.audio_muted) { audioStatus.innerText = "MUTED"; audioStatus.style.color = "var(--danger)"; miniMuteBtn.innerText = "UNMUTE MIC"; miniMuteBtn.classList.add('danger-mode'); micWave.classList.add('muted'); } else { audioStatus.innerText = "ACTIVE"; audioStatus.style.color = "var(--success)"; miniMuteBtn.innerText = "MUTE MIC"; miniMuteBtn.classList.remove('danger-mode'); micWave.classList.remove('muted'); }
                    if (data.ai_is_speaking && data.ai_volume > 0.01 && !isCameraRunning) { let scale = 1 + (data.ai_volume * 1.5); let blur = 20 + (data.ai_volume * 120); let opacity = 0.3 + (data.ai_volume * 0.7); hudCore.style.transform = `scale(${scale})`; hudCore.style.boxShadow = `0 0 ${blur}px rgba(0, 229, 255, ${opacity}), inset 0 0 ${blur/2}px rgba(0, 229, 255, ${opacity * 0.8})`; hudCore.style.background = `radial-gradient(circle, rgba(0,139,153,${opacity}) 0%, rgba(0, 229, 255,${opacity*0.6}) 40%, rgba(0,0,0,0) 70%)`; hudCore.style.transition = 'all 0.08s ease-in-out'; } else { hudCore.style.transform = ''; hudCore.style.boxShadow = ''; hudCore.style.background = ''; hudCore.style.transition = 'all 0.4s ease-out'; }
                } catch(e) { }
            }, 80); 
            setInterval(async () => { try { let chatRes = await fetch('/get_chat'); let chatData = await chatRes.json(); if(chatData.text) appendAiText(chatData.text); } catch(e) {} }, 500);
        }
        function handleCommand() { let inputField = document.getElementById('textInput'); let val = inputField.value.trim(); if(!val) return; logMsg(`<div class="user-msg">USR: ${val}</div>`); inputField.value = ''; if(window.pywebview) window.pywebview.api.send_message(val); else fetch('/send_message', { method: 'POST', body: val }); }
        function appendAiText(text) { const cb = document.getElementById('chatBox'); let currentLine = cb.lastElementChild; if(!currentLine || !currentLine.classList.contains('active-ai-line')) { currentLine = document.createElement('div'); currentLine.classList.add('active-ai-line', 'ai-msg'); currentLine.innerHTML = `<strong>SYS:</strong> <span class="ai-text"></span>`; cb.appendChild(currentLine); document.getElementById('subtitleOverlay').innerText = ''; document.getElementById('mini-transcript').innerText = ''; } currentLine.querySelector('.ai-text').innerText += text; cb.scrollTop = cb.scrollHeight; document.getElementById('subtitleOverlay').innerText += text; document.getElementById('mini-transcript').innerText += text; clearTimeout(aiTextTimeout); clearTimeout(subtitleTimeout); aiTextTimeout = setTimeout(() => { if(cb.lastElementChild) cb.lastElementChild.classList.remove('active-ai-line'); }, 2500); subtitleTimeout = setTimeout(() => { document.getElementById('subtitleOverlay').innerText = ''; document.getElementById('mini-transcript').innerText = 'System tracking screen content...'; }, 4500); }
        function logMsg(html) { const cb = document.getElementById('chatBox'); cb.innerHTML += html; cb.scrollTop = cb.scrollHeight; }
        function toggleLocalCamera() { const btn = document.getElementById('toggleCamBtn'); const feedImg = document.getElementById('liveFeed'); const holoCore = document.getElementById('hologramCore'); const statusLabel = document.getElementById('vision-status'); isCameraRunning = !isCameraRunning; if(isCameraRunning) { btn.innerText = "DEACTIVATE OPTICS"; btn.style.color = "var(--danger)"; btn.style.borderColor = "var(--danger)"; holoCore.style.display = 'none'; if (window.pywebview) window.pywebview.api.set_camera("0"); else fetch('/set_camera?src=0'); setTimeout(() => { feedImg.src = '/video_feed?t=' + new Date().getTime(); feedImg.style.display = 'block'; statusLabel.innerText = 'ACTIVE'; statusLabel.style.color = 'var(--success)'; logMsg(`<div class="sys-msg" style="color:var(--text-secondary);">SYS: Hardware optics linked.</div>`); }, 1500); } else { btn.innerText = "ACTIVATE OPTICS"; btn.style.color = "#fff"; btn.style.borderColor = "var(--border-subtle)"; feedImg.style.display = 'none'; feedImg.src = ''; holoCore.style.display = 'flex'; if (window.pywebview) window.pywebview.api.set_camera("off"); else fetch('/set_camera?src=off'); statusLabel.innerText = 'OFFLINE'; statusLabel.style.color = 'var(--text-secondary)'; logMsg(`<div class="sys-msg" style="color:var(--text-secondary);">SYS: Hardware optics unlinked.</div>`); } }
    </script>







<!-- Persistent Hovering Cloud Deployment Progress Widget -->
<div id="crossAppFloatingProgress" style="position: fixed; bottom: 24px; right: 24px; z-index: 99999; width: 380px; max-width: calc(100vw - 48px); display: none; font-family: 'Inter', -apple-system, sans-serif;">
    <div style="background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #0f172a; border-radius: 12px; padding: 14px 18px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1); color: #0f172a;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px; overflow: hidden; max-width: 80%;">
                <div class="spinner-border spinner-border-sm" id="crossSpinner" style="width: 14px; height: 14px; border-width: 2px; flex-shrink: 0; color: #0f172a;"></div>
                <span style="font-weight: 700; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #0f172a;" id="crossProjectName">Deploying...</span>
                <span id="crossBadge" style="font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; background: #f1f5f9; color: #0f172a; border: 1px solid #e2e8f0; font-weight: 600; flex-shrink: 0;">ELIVORA</span>
            </div>
            <span id="crossPercent" style="font-size: 0.85rem; font-weight: 700; color: #0f172a; flex-shrink: 0;">0%</span>
        </div>
        <div style="height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; margin-bottom: 8px;">
            <div id="crossProgressBar" style="height: 100%; width: 0%; background: #0f172a; transition: width 0.2s linear;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: #64748b; margin-bottom: 10px;">
            <span id="crossStatusText" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-right: 8px;">Running in background...</span>
            <span id="crossTimeRemaining" style="font-weight: 600; color: #0f172a; flex-shrink: 0;">Calculating...</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 8px; border-top: 1px solid #f1f5f9; font-size: 0.75rem;">
            <span style="color: #64748b; font-weight: 500;">Dual-Pipeline Cloud</span>
            <a href="/cloud" style="color: #ffffff; text-decoration: none; font-weight: 600; padding: 4px 12px; border-radius: 6px; background: #0f172a; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.1);">Open Dashboard &rarr;</a>
        </div>
    </div>
</div>
<script>
    (function() {
        function pollActiveDeployment() {
            try {
                const raw = localStorage.getItem('elivora_active_pipeline');
                if (!raw) {
                    const el = document.getElementById('crossAppFloatingProgress');
                    if (el) el.style.display = 'none';
                    return;
                }
                const data = JSON.parse(raw);
                const el = document.getElementById('crossAppFloatingProgress');
                if (!el) return;

                if (!data || !data.active) {
                    if (data && data.done) {
                        el.style.display = 'block';
                        const pName = document.getElementById('crossProjectName');
                        if (pName) pName.innerText = data.name || 'Deployment';
                        const badge = document.getElementById('crossBadge');
                        if (badge) badge.innerText = (data.badge || 'ELIVORA').toUpperCase();
                        const pct = document.getElementById('crossPercent');
                        if (pct) pct.innerText = '100%';
                        const bar = document.getElementById('crossProgressBar');
                        if (bar) bar.style.width = '100%';
                        const st = document.getElementById('crossStatusText');
                        if (st) st.innerText = 'Live & Ready!';
                        const tr = document.getElementById('crossTimeRemaining');
                        if (tr) tr.innerText = 'Ready';
                        const sp = document.getElementById('crossSpinner');
                        if (sp) { sp.className = 'bi bi-check-circle-fill'; sp.style.color = '#10b981'; }
                        setTimeout(() => { if (el) el.style.display = 'none'; }, 5000);
                    } else {
                        el.style.display = 'none';
                    }
                    return;
                }

                el.style.display = 'block';
                const pName = document.getElementById('crossProjectName');
                if (pName) pName.innerText = data.name || 'Deployment';
                const badge = document.getElementById('crossBadge');
                if (badge) badge.innerText = (data.badge || 'ELIVORA').toUpperCase();
                const pct = document.getElementById('crossPercent');
                if (pct) pct.innerText = (data.pct || 0) + '%';
                const bar = document.getElementById('crossProgressBar');
                if (bar) bar.style.width = (data.pct || 0) + '%';
                const st = document.getElementById('crossStatusText');
                if (st) st.innerText = data.status || 'Deploying...';
                const tr = document.getElementById('crossTimeRemaining');
                if (tr) tr.innerText = data.time || '';

                // If Vercel deployment ID is present, poll Vercel directly from here too!
                if (data.deploymentId && data.token) {
                    fetch('https://api.vercel.com/v13/deployments/' + data.deploymentId, {
                        headers: { 'Authorization': 'Bearer ' + data.token }
                    }).then(r => r.json()).then(d => {
                        if (d.readyState === 'READY') {
                            data.active = false;
                            data.done = true;
                            data.pct = 100;
                            data.status = 'Live & Ready!';
                            data.time = 'Ready';
                            localStorage.setItem('elivora_active_pipeline', JSON.stringify(data));
                            
                            // Update saved deployments in localStorage
                            try {
                                const vList = JSON.parse(localStorage.getItem('elivora_vercel_projects') || '[]');
                                const item = vList.find(x => x.id === data.name);
                                if (item) { item.status = 'live'; localStorage.setItem('elivora_vercel_projects', JSON.stringify(vList)); }
                            } catch(e) {}
                        } else if (d.readyState === 'ERROR' || d.readyState === 'CANCELED') {
                            data.active = false;
                            data.done = false;
                            data.failed = true;
                            data.status = 'Build Failed on Vercel';
                            localStorage.setItem('elivora_active_pipeline', JSON.stringify(data));
                        }
                    }).catch(()=>{});
                }
            } catch(e) {}
        }
        setInterval(pollActiveDeployment, 2000);
        pollActiveDeployment();
    })();
</script>

</body>
</html>
"""




CLOUD_HTML = r'''
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ELIVORA CLOUD | GitHub Integration</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #f8fafc; color: #0f172a; margin: 0; padding: 2rem; }
        .card { border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
        .toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; }
        .repo-card { transition: transform 0.2s; cursor: pointer; }
        .repo-card:hover { transform: translateY(-3px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); border-color: #0d6efd; }
    </style>
</head>
<body>

    <!-- Toast Notification -->
    <div class="toast-container">
        <div id="successToast" class="toast align-items-center text-bg-success border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">
                    <i class="bi bi-check-circle-fill me-2"></i> Success! Logged in to GitHub.
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    </div>

    <!-- Deployment Modal -->
    <div class="modal fade" id="deployModal" tabindex="-1" aria-labelledby="deployModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title fw-bold" id="deployModalLabel"><i class="bi bi-rocket-takeoff text-primary"></i> Deploy <span id="modalRepoName" class="text-primary"></span></h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <div class="row g-3">
                <div class="col-md-6">
                    <label class="form-label fw-semibold small">Build Command</label>
                    <input type="text" id="buildCommand" class="form-control" placeholder="e.g. npm run build">
                </div>
                <div class="col-md-6">
                    <label class="form-label fw-semibold small">Output Directory</label>
                    <input type="text" id="outputDir" class="form-control" placeholder="e.g. dist or .next">
                </div>
                <div class="col-12 mt-4">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <label class="form-label fw-semibold small m-0">Environment Variables</label>
                        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="addEnvRow()"><i class="bi bi-plus-lg"></i> Add</button>
                    </div>
                    <div id="envVarsContainer" class="d-flex flex-column gap-2"></div>
                </div>
                
                <div class="col-12 mt-4 d-none" id="deployConsoleWrapper">
                    <label class="form-label fw-semibold small">Deployment Logs</label>
                    <div class="bg-dark text-light p-3 rounded small" id="deployConsole" style="height: 150px; overflow-y: auto; font-family: monospace;"></div>
                </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-light border" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-dark" id="deployBtn" onclick="triggerDeploy()">Deploy to Vercel</button>
          </div>
        </div>
      </div>
    </div>

    <div class="container max-w-4xl mx-auto">
        <div class="d-flex justify-content-between align-items-center mb-5">
            <h2 class="fw-bold d-flex align-items-center gap-2 m-0">
                <i class="bi bi-cloud-fill text-primary"></i> ELIVORA CLOUD
            </h2>
            <button id="logoutBtn" class="btn btn-outline-danger d-none" onclick="logout()">
                <i class="bi bi-box-arrow-right"></i> Logout
            </button>
        </div>

        <!-- Main Navigation -->
        <ul class="nav nav-pills mb-4 d-none" id="mainNav">
          <li class="nav-item">
            <a class="nav-link active" id="tab-repos" href="#" onclick="switchTab('repos')"><i class="bi bi-journal-code me-2"></i>Repositories</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" id="tab-deployed" href="#" onclick="switchTab('deployed')"><i class="bi bi-globe me-2"></i>Deployed Apps</a>
          </li>
        </ul>

        <!-- Login Section -->
        <div id="loginSection" class="text-center py-5">
            <div class="card p-5 mx-auto" style="max-width: 400px;">
                <i class="bi bi-github mb-3" style="font-size: 3rem;"></i>
                <h4 class="fw-bold mb-3">Connect to GitHub</h4>
                <p class="text-muted mb-4">Connect your account to view and manage your repositories directly from Elivora Cloud.</p>
                <a href="/github/login" class="btn btn-dark w-100 py-2 fw-semibold">
                    Sign in with GitHub
                </a>
            </div>
        </div>

        <!-- Repositories Section -->
        <div id="repoSection" class="d-none">
            <h4 class="fw-bold mb-4"><i class="bi bi-journal-code me-2"></i>Select a Repository to Deploy</h4>
            <div id="repoList" class="row g-4">
                <!-- Repos injected here -->
            </div>
            <div id="loadingSpinner" class="text-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        </div>

        <!-- Deployed Apps Section -->
        <div id="deployedSection" class="d-none">
            <h4 class="fw-bold mb-4"><i class="bi bi-globe me-2"></i>Deployed Applications</h4>
            <div id="deployedList" class="row g-4">
                <!-- Deployed apps injected here -->
            </div>
            <div id="loadingSpinnerDeployed" class="text-center py-5 d-none">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        const loginSection = document.getElementById('loginSection');
        const repoSection = document.getElementById('repoSection');
        const repoList = document.getElementById('repoList');
        const logoutBtn = document.getElementById('logoutBtn');
        const loadingSpinner = document.getElementById('loadingSpinner');
        
        let pollInterval;
        let selectedRepo = "";
        let deployModalInstance;

        function showToast() {
            const toast = new bootstrap.Toast(document.getElementById('successToast'));
            toast.show();
        }

        async function checkAuth() {
            let token = localStorage.getItem('github_token');
            
            // If localStorage is empty/broken across pywebview navigation, check the python backend
            if (!token) {
                try {
                    const res = await fetch('/github/status');
                    const data = await res.json();
                    if (data.token) {
                        token = data.token;
                        localStorage.setItem('github_token', token);
                    }
                } catch(e) {}
            }

            if (token) {
                loginSection.classList.add('d-none');
                repoSection.classList.remove('d-none');
                logoutBtn.classList.remove('d-none');
                document.getElementById('mainNav').classList.remove('d-none');
                fetchRepos(token);
                return true;
            } else {
                loginSection.classList.remove('d-none');
                repoSection.classList.add('d-none');
                logoutBtn.classList.add('d-none');
                document.getElementById('mainNav').classList.add('d-none');
                return false;
            }
        }

        window.addEventListener("message", (event) => {
            if (event.data && event.data.type === "GITHUB_TOKEN") {
                localStorage.setItem("github_token", event.data.token);
                clearInterval(pollInterval);
                showToast();
                checkAuth();
            }
        });

        async function fetchRepos(token) {
            loadingSpinner.classList.remove('d-none');
            repoList.innerHTML = '';
            try {
                const response = await fetch('https://api.github.com/user/repos?type=all&sort=updated&per_page=100', {
                    headers: { 'Authorization': 'token ' + token, 'Accept': 'application/vnd.github.v3+json' }
                });
                if (!response.ok) {
                    const errText = await response.text();
                    repoList.innerHTML = `<div class="col-12 text-center text-danger"><h4>GitHub API Error ${response.status}</h4><p>${errText}</p><p>Make sure your GitHub App has Repository permissions (Contents: Read, Metadata: Read) enabled in its settings!</p></div>`;
                    loadingSpinner.classList.add('d-none');
                    return;
                }
                const repos = await response.json();
                loadingSpinner.classList.add('d-none');
                
                if (repos.length === 0) {
                    repoList.innerHTML = '<div class="col-12 text-center text-muted">No repositories found.</div>';
                    return;
                }
                
                repos.forEach(repo => {
                    const visibilityBadge = repo.private 
                        ? '<span class="badge bg-secondary"><i class="bi bi-lock-fill"></i> Private</span>'
                        : '<span class="badge bg-success"><i class="bi bi-globe"></i> Public</span>';
                    
                    const card = `
                        <div class="col-md-6 col-lg-4">
                            <div class="card h-100 repo-card p-3" onclick="openDeployModal('${repo.full_name}')">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <h6 class="fw-bold m-0 text-truncate" title="${repo.name}">${repo.name}</h6>
                                    ${visibilityBadge}
                                </div>
                                <p class="text-muted small mb-3" style="display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; height: 2.8em;">
                                    ${repo.description || 'No description provided.'}
                                </p>
                                <div class="mt-auto d-flex align-items-center gap-3 small text-muted">
                                    <span><i class="bi bi-star-fill text-warning"></i> ${repo.stargazers_count}</span>
                                    <span><i class="bi bi-circle-fill" style="color: #e34c26; font-size: 0.5rem; margin-right: 2px;"></i> ${repo.language || 'Unknown'}</span>
                                </div>
                            </div>
                        </div>
                    `;
                    repoList.innerHTML += card;
                });
            } catch (error) {
                loadingSpinner.classList.add('d-none');
                repoList.innerHTML = `<div class="col-12 text-danger">Error loading repositories: ${error.message}</div>`;
            }
        }
        
        function addEnvRow() {
            const container = document.getElementById('envVarsContainer');
            const row = document.createElement('div');
            row.className = 'd-flex gap-2 env-row';
            row.innerHTML = `
                <input type="text" class="form-control env-key" placeholder="Key (e.g. API_KEY)">
                <input type="text" class="form-control env-val" placeholder="Value">
                <button type="button" class="btn btn-outline-danger" onclick="this.parentElement.remove()"><i class="bi bi-trash"></i></button>
            `;
            container.appendChild(row);
        }

        function openDeployModal(repoFullName) {
            selectedRepo = repoFullName;
            document.getElementById('deployModalLabel').innerHTML = '<i class="bi bi-rocket-takeoff text-primary"></i> Deploy <span id="modalRepoName" class="text-primary">' + repoFullName + '</span>';
            document.getElementById('buildCommand').value = '';
            document.getElementById('outputDir').value = '';
            document.getElementById('envVarsContainer').innerHTML = '';
            document.getElementById('deployConsoleWrapper').classList.add('d-none');
            document.getElementById('deployConsole').innerHTML = '';
            document.getElementById('deployBtn').innerHTML = 'Deploy to Vercel';
            document.getElementById('deployBtn').disabled = false;
            
            deployModalInstance = new bootstrap.Modal(document.getElementById('deployModal'));
            deployModalInstance.show();
        }

        async function triggerDeploy() {
            const btn = document.getElementById('deployBtn');
            const consoleWrapper = document.getElementById('deployConsoleWrapper');
            const consoleDiv = document.getElementById('deployConsole');
            
            btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Deploying...';
            btn.disabled = true;
            consoleWrapper.classList.remove('d-none');
            consoleDiv.innerHTML = '<span class="text-info">Initiating deployment pipeline...</span><br>';
            
            const envVars = {};
            document.querySelectorAll('.env-row').forEach(row => {
                const key = row.querySelector('.env-key').value.trim();
                const val = row.querySelector('.env-val').value.trim();
                if (key) envVars[key] = val;
            });
            
            const payload = {
                repo_name: selectedRepo,
                github_token: localStorage.getItem('github_token'),
                build_command: document.getElementById('buildCommand').value.trim(),
                output_dir: document.getElementById('outputDir').value.trim(),
                env_vars: envVars
            };
            
            try {
                const res = await fetch('/deploy_vercel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();
                    for (const line of lines) {
                        if (line.trim()) {
                            try {
                                const data = JSON.parse(line);
                                if (data.log) {
                                    consoleDiv.innerHTML += `<div class="text-muted" style="font-size:0.8rem">${data.log.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>`;
                                }
                                if (data.url) {
                                    consoleDiv.innerHTML += `<span class="text-success mt-2 d-block">Deployment Successful!</span>`;
                                    consoleDiv.innerHTML += `<a href="${data.url}" target="_blank" class="text-primary mt-1 d-block fw-bold">${data.url}</a>`;
                                    btn.innerHTML = 'Deployed Successfully';
                                }
                                if (data.error) {
                                    consoleDiv.innerHTML += `<span class="text-danger mt-2 d-block">Deployment Failed: ${data.error}</span>`;
                                    btn.innerHTML = 'Retry Deployment';
                                    btn.disabled = false;
                                }
                            } catch(e) {}
                        }
                    }
                }
            } catch (e) {
                consoleDiv.innerHTML += `<span class="text-danger mt-2 d-block">Network Error: ${e.message}</span>`;
                btn.innerHTML = 'Retry Deployment';
                btn.disabled = false;
            }
        }

        function logout() {
            localStorage.removeItem('github_token');
            checkAuth();
        }

        function switchTab(tab) {
            if (tab === 'repos') {
                document.getElementById('tab-repos').classList.add('active');
                document.getElementById('tab-deployed').classList.remove('active');
                repoSection.classList.remove('d-none');
                document.getElementById('deployedSection').classList.add('d-none');
            } else {
                document.getElementById('tab-repos').classList.remove('active');
                document.getElementById('tab-deployed').classList.add('active');
                repoSection.classList.add('d-none');
                document.getElementById('deployedSection').classList.remove('d-none');
                fetchDeployedApps();
            }
        }

        async function fetchDeployedApps() {
            const list = document.getElementById('deployedList');
            const spinner = document.getElementById('loadingSpinnerDeployed');
            
            spinner.classList.remove('d-none');
            list.innerHTML = '';
            
            try {
                const res = await fetch('/api/deployed_apps');
                const apps = await res.json();
                
                const token = localStorage.getItem('github_token');
                const userRes = await fetch('https://api.github.com/user', { headers: { 'Authorization': 'token ' + token, 'Accept': 'application/vnd.github.v3+json' }});
                let username = "";
                if (userRes.ok) {
                    const userData = await userRes.json();
                    username = userData.login;
                }
                
                spinner.classList.add('d-none');
                
                const keys = Object.keys(apps).filter(k => username ? k.startsWith(username + '/') : true);
                if (keys.length === 0) {
                    list.innerHTML = '<div class="col-12 text-center text-muted">No deployed applications found.</div>';
                    return;
                }
                
                keys.forEach(repo => {
                    const data = apps[repo];
                    const dateStr = new Date(data.timestamp * 1000).toLocaleString();
                    const encodedData = encodeURIComponent(JSON.stringify(data));
                    
                    list.innerHTML += `
                        <div class="col-md-6 col-lg-4">
                            <div class="card h-100 p-3 shadow-sm border-0" style="border-top: 4px solid #10b981 !important;">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <h6 class="fw-bold m-0 text-truncate" title="${data.repo_name}">${data.repo_name}</h6>
                                    <span class="badge bg-success"><i class="bi bi-check-circle-fill"></i> Live</span>
                                </div>
                                <a href="${data.url}" target="_blank" class="text-primary small fw-semibold text-truncate d-block mb-3">
                                    ${data.url} <i class="bi bi-box-arrow-up-right ms-1"></i>
                                </a>
                                <div class="text-muted small mb-3">
                                    <i class="bi bi-clock"></i> Deployed: ${dateStr}
                                </div>
                                <div class="mt-auto d-flex justify-content-end gap-2">
                                    <button class="btn btn-sm btn-outline-danger" onclick="deleteVercelApp('${data.repo_name}')">
                                        <i class="bi bi-trash"></i>
                                    </button>
                                    <button class="btn btn-sm btn-outline-secondary" onclick="openSettingsModal('${encodedData}')">
                                        <i class="bi bi-gear-fill me-1"></i> Settings
                                    </button>
                                </div>
                            </div>
                        </div>
                    `;
                });
            } catch(e) {
                spinner.classList.add('d-none');
                list.innerHTML = '<div class="col-12 text-danger">Failed to load deployed apps.</div>';
            }
        }

        async function deleteVercelApp(repoName) {
            if (!confirm(`Are you sure you want to permanently delete the deployed app for ${repoName} from Vercel?`)) return;
            
            const btn = event.currentTarget;
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            btn.disabled = true;
            
            try {
                const res = await fetch('/delete_vercel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ repo_name: repoName })
                });
                if (res.ok) {
                    fetchDeployedApps();
                } else {
                    const err = await res.json();
                    alert('Failed to delete: ' + (err.error || 'Unknown error'));
                    btn.innerHTML = originalHtml;
                    btn.disabled = false;
                }
            } catch(e) {
                alert('Network error during deletion');
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }
        }

        function openSettingsModal(encodedData) {
            const data = JSON.parse(decodeURIComponent(encodedData));
            selectedRepo = data.repo_name;
            
            document.getElementById('deployModalLabel').innerHTML = '<i class="bi bi-gear-fill text-secondary"></i> Settings for <span class="text-secondary">' + data.repo_name + '</span>';
            document.getElementById('buildCommand').value = data.build_cmd || '';
            document.getElementById('outputDir').value = data.output_dir || '';
            document.getElementById('deployConsoleWrapper').classList.add('d-none');
            document.getElementById('deployConsole').innerHTML = '';
            
            const btn = document.getElementById('deployBtn');
            btn.innerHTML = 'Save & Redeploy';
            btn.disabled = false;
            
            const envContainer = document.getElementById('envVarsContainer');
            envContainer.innerHTML = '';
            
            if (data.env_vars) {
                Object.keys(data.env_vars).forEach(key => {
                    const row = document.createElement('div');
                    row.className = 'd-flex gap-2 env-row';
                    row.innerHTML = `
                        <input type="text" class="form-control env-key" placeholder="Key" value="${key}">
                        <input type="text" class="form-control env-val" placeholder="Value" value="${data.env_vars[key]}">
                        <button type="button" class="btn btn-outline-danger" onclick="this.parentElement.remove()"><i class="bi bi-trash"></i></button>
                    `;
                    envContainer.appendChild(row);
                });
            }
            
            deployModalInstance = new bootstrap.Modal(document.getElementById('deployModal'));
            deployModalInstance.show();
        }

        // Initialize
        checkAuth();
    </script>
</body>
</html>
'''
# =====================================================================
# LOCAL WEB SERVER & API HANDLER
# =====================================================================
class WebDashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # global TEMP_GITHUB_TOKEN (deprecated)
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HUB_HTML.encode('utf-8'))
        elif parsed_path.path == '/ai':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(AI_HTML.encode('utf-8'))
        elif parsed_path.path == '/cloud':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            # Safely grab the token from the .env file and inject it into the HTML
            gh_token = os.environ.get("GITHUB_DEFAULT_TOKEN", "")
            gh_token = os.environ.get("GITHUB_DEFAULT_TOKEN", "")
            vercel_token = os.environ.get("VERCEL_DEFAULT_TOKEN", "")
            final_html = CLOUD_HTML.replace('{{GITHUB_TOKEN_PLACEHOLDER}}', gh_token).replace('{{VERCEL_TOKEN_PLACEHOLDER}}', vercel_token)
            
            self.wfile.write(final_html.encode('utf-8'))
            

        elif parsed_path.path == '/github/login':
            client_id = os.environ.get("GITHUB_CLIENT_ID", "")
            redirect_url = f"https://github.com/login/oauth/authorize?client_id={client_id}&redirect_uri=http://127.0.0.1:8080/github/callback"
            self.send_response(302)
            self.send_header('Location', redirect_url)
            self.end_headers()
            
        elif parsed_path.path == '/github/callback':
            qs = urllib.parse.parse_qs(parsed_path.query)
            code = qs.get('code', [None])[0]
            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code")
                return
                
            client_id = os.environ.get("GITHUB_CLIENT_ID", "")
            client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "")
            
            # Exchange code for token
            token_url = "https://github.com/login/oauth/access_token"
            data = urllib.parse.urlencode({
                'client_id': client_id,
                'client_secret': client_secret,
                'code': code,
                'redirect_uri': 'http://127.0.0.1:8080/github/callback'
            }).encode('utf-8')
            
            req = urllib.request.Request(token_url, data=data)
            req.add_header('Accept', 'application/json')
            
            try:
                with urllib.request.urlopen(req) as response:
                    raw_response = response.read().decode('utf-8')
                    resp_data = json.loads(raw_response)
                    token = resp_data.get('access_token', '')
                    
                    if not token:
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html')
                        self.end_headers()
                        self.wfile.write(f"<h2>Token Exchange Failed</h2><pre>{raw_response}</pre>".encode('utf-8'))
                        return

                    try:
                        with open('.github_token_cache', 'w') as f: f.write(token)
                    except: pass
                    
                    # Serve a self-closing HTML page that posts the message to the parent window
                    # and saves to localStorage if possible
                    html_response = f'''
                    <!DOCTYPE html>
                    <html>
                    <head><title>Authenticating...</title></head>
                    <body style="background-color: #0f172a; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; font-family: sans-serif;">
                        <h2>Authentication Successful! Redirecting...</h2>
                        <script>
                            localStorage.setItem("github_token", "{token}");
                            window.location.href = "/cloud";
                        </script>
                    </body>
                    </html>
                    '''
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(html_response.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error fetching token: {str(e)}".encode('utf-8'))

        elif parsed_path.path == '/github/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            cached_token = None
            try:
                if os.path.exists('.github_token_cache'):
                    with open('.github_token_cache', 'r') as f:
                        cached_token = f.read().strip()
            except: pass
            
            self.wfile.write(json.dumps({"token": cached_token}).encode('utf-8'))

        elif parsed_path.path == '/api/deployed_apps':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            apps = {}
            if os.path.exists('.deployed_apps.json'):
                try:
                    with open('.deployed_apps.json', 'r') as f:
                        apps = json.load(f)
                except: pass
            self.wfile.write(json.dumps(apps).encode('utf-8'))

        elif parsed_path.path == '/video_feed':

            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '-1')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                while True:
                    global LATEST_JPEG
                    if LATEST_JPEG:
                        self.wfile.write(b'--frame\r\n')
                        self.send_header('Content-type', 'image/jpeg')
                        self.send_header('Content-length', str(len(LATEST_JPEG)))
                        self.end_headers()
                        self.wfile.write(LATEST_JPEG)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.033) 
            except Exception: pass 
        elif parsed_path.path == '/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(get_hardware_stats().encode('utf-8'))
        elif parsed_path.path == '/get_chat':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            if AI_CHAT_QUEUE:
                msg = "".join(AI_CHAT_QUEUE)
                AI_CHAT_QUEUE.clear()
                self.wfile.write(json.dumps({"text": msg}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"text": ""}).encode('utf-8'))
        elif parsed_path.path == '/set_camera':
            global TARGET_CAM_SOURCE
            qs = urllib.parse.parse_qs(parsed_path.query)
            if 'src' in qs: TARGET_CAM_SOURCE = qs['src'][0]
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/deploy_vercel':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                import tempfile
                import zipfile
                import shutil
                data = json.loads(post_data)
                repo_name = data.get('repo_name')
                github_token = data.get('github_token')
                build_cmd = data.get('build_command')
                output_dir = data.get('output_dir')
                env_vars = data.get('env_vars', {})
                
                # Download Zipball
                zip_url = f"https://api.github.com/repos/{repo_name}/zipball"
                req = urllib.request.Request(zip_url, headers={'Authorization': f'token {github_token}'})
                
                self.send_response(200)
                self.send_header('Content-type', 'application/x-ndjson')
                self.end_headers()
                
                def stream_msg(msg_type, msg):
                    try:
                        self.wfile.write((json.dumps({msg_type: msg}) + '\n').encode('utf-8'))
                        self.wfile.flush()
                    except: pass
                
                stream_msg('log', f'Downloading {repo_name} from GitHub...')
                
                temp_dir = tempfile.mkdtemp()
                try:
                    zip_path = os.path.join(temp_dir, 'repo.zip')
                    with urllib.request.urlopen(req) as response, open(zip_path, 'wb') as out_file:
                        shutil.copyfileobj(response, out_file)
                        
                    stream_msg('log', 'Extracting repository contents...')
                    # Extract
                    extract_dir = os.path.join(temp_dir, 'extracted')
                    os.makedirs(extract_dir, exist_ok=True)
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    
                    # Find extracted subfolder
                    subfolders = os.listdir(extract_dir)
                    repo_dir = os.path.join(extract_dir, subfolders[0]) if subfolders else extract_dir
                    
                    stream_msg('log', 'Configuring Vercel deployment...')
                    # Generate vercel.json if custom build steps provided
                    vercel_json = {}
                    if build_cmd: vercel_json['buildCommand'] = build_cmd
                    if output_dir: vercel_json['outputDirectory'] = output_dir
                    if vercel_json:
                        with open(os.path.join(repo_dir, 'vercel.json'), 'w') as f:
                            json.dump(vercel_json, f)
                            
                    stream_msg('log', 'Starting Vercel CLI deployment process...')
                    # Run Vercel CLI via npx (use npx --yes to bypass installation prompts)
                    vercel_token = os.environ.get("VERCEL_DEFAULT_TOKEN", "")
                    cmd = f'npx --yes vercel deploy --token "{vercel_token}" --yes --prod'
                    
                    for k, v in env_vars.items():
                        cmd += f' --env {k}="{v}" --build-env {k}="{v}"'
                        
                    safe_name = repo_name.split('/')[-1].replace('.', '-')
                    cmd += f' --name {safe_name}'
                    
                    process = subprocess.Popen(cmd, cwd=repo_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True, bufsize=1)
                    
                    output_log = ""
                    for line in iter(process.stdout.readline, ''):
                        if not line: break
                        output_log += line
                        stream_msg('log', line.strip())
                    
                    process.wait()
                    
                    stream_msg('log', 'Deployment process finished. Analyzing output...')
                    
                    # Look for URL in output
                    url_match = re.search(r'https://[a-zA-Z0-9.-]+\.vercel\.app', output_log)
                    if url_match:
                        live_url = url_match.group(0)
                        
                        try:
                            apps = {}
                            if os.path.exists('.deployed_apps.json'):
                                with open('.deployed_apps.json', 'r') as f: apps = json.load(f)
                                
                            apps[repo_name] = {
                                'repo_name': repo_name,
                                'url': live_url,
                                'env_vars': env_vars,
                                'build_cmd': build_cmd,
                                'output_dir': output_dir,
                                'timestamp': time.time()
                            }
                            
                            with open('.deployed_apps.json', 'w') as f: json.dump(apps, f)
                        except Exception as e:
                            stream_msg('log', f'Warning: Could not save deployment history locally: {str(e)}')
                        
                        stream_msg('url', live_url)
                    else:
                        stream_msg('error', 'Could not find Vercel deployment URL in the output.')
                finally:
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    except: pass
                        
            except Exception as e:
                try:
                    self.wfile.write((json.dumps({'error': str(e), 'trace': traceback.format_exc()}) + '\n').encode('utf-8'))
                    self.wfile.flush()
                except: pass
        elif parsed_path.path == '/delete_vercel':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                repo_name = data.get('repo_name')
                safe_name = repo_name.split('/')[-1].replace('.', '-')
                
                vercel_token = os.environ.get("VERCEL_DEFAULT_TOKEN", "")
                cmd = f'npx --yes vercel rm {safe_name} --token "{vercel_token}" --yes'
                
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True)
                process.wait()
                
                if os.path.exists('.deployed_apps.json'):
                    with open('.deployed_apps.json', 'r') as f: apps = json.load(f)
                    if repo_name in apps:
                        del apps[repo_name]
                        with open('.deployed_apps.json', 'w') as f: json.dump(apps, f)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                
        elif parsed_path.path == '/send_message':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            if post_data.strip(): TEXT_PROMPT_QUEUE.append(post_data.strip())
            self.send_response(200)
            self.end_headers()
        elif parsed_path.path == '/toggle_audio':
            global MIC_MUTED
            MIC_MUTED = not MIC_MUTED
            self.send_response(200)
            self.end_headers()
        elif parsed_path.path == '/terminate':
            self.send_response(200)
            self.end_headers()
            print("\n[SYSTEM] Termination command executed. Graceful exit.")
            os._exit(0)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args): pass 

def start_web_server():
    PORT = 8080
    class ReusableTCPServer(socketserver.ThreadingTCPServer): allow_reuse_address = True
    httpd = ReusableTCPServer(("127.0.0.1", PORT), WebDashboardHandler)
    httpd.serve_forever()

# =====================================================================
# CORE AI AUDIO/VIDEO/TEXT LOOP
# =====================================================================
class AudioLoop:
    def __init__(self):
        self.audio_in_queue = None
        self.out_queue = None
        self.session = None
        self.audio_stream = None

    async def send_text_realtime(self):
        while True:
            if TEXT_PROMPT_QUEUE:
                msg = TEXT_PROMPT_QUEUE.pop(0)
                if self.session is not None and self.out_queue is not None:
                    await self.out_queue.put({"mime_type": "text/plain", "data": msg})
            await asyncio.sleep(0.1)

    async def get_frames(self):
        global LATEST_JPEG, TARGET_CAM_SOURCE
        last_ai_send_time = 0
        AI_SEND_INTERVAL = 1.0 
        while True:
            if TARGET_CAM_SOURCE != "off" and LATEST_JPEG:
                current_time = time.time()
                if current_time - last_ai_send_time >= AI_SEND_INTERVAL:
                    if self.out_queue is not None:
                        await self.out_queue.put({"mime_type": "image/jpeg", "data": LATEST_JPEG})
                    last_ai_send_time = current_time
            await asyncio.sleep(0.05)

    async def send_realtime(self):
        while True:
            if self.out_queue is not None:
                msg = await self.out_queue.get()
                if self.session is not None:
                    mime = msg.get("mime_type", "")
                    if mime == "text/plain":
                        text_data = msg.get("data")
                        await self.session.send_realtime_input(text=text_data)
                    else:
                        if mime == "image/jpeg" and TARGET_CAM_SOURCE == "off": continue
                        blob = types.Blob(mime_type=mime, data=msg.get("data"))
                        if "audio" in mime: await self.session.send_realtime_input(audio=blob)
                        elif "image" in mime: await self.session.send_realtime_input(video=blob)

    async def listen_audio(self):
        global MIC_MUTED
        mic_info = pya.get_default_input_device_info()
        self.audio_stream = await asyncio.to_thread(
            pya.open, format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE,
            input=True, input_device_index=mic_info["index"], frames_per_buffer=CHUNK_SIZE,
        )
        kwargs = {"exception_on_overflow": False} if __debug__ else {}
        while True:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)
            if not MIC_MUTED:
                try:
                    audio_array = np.frombuffer(data, dtype=np.int16)
                    rms = np.sqrt(np.mean(np.square(audio_array.astype(np.float32))))
                    if rms > 1000: 
                        while not self.audio_in_queue.empty():
                            try: self.audio_in_queue.get_nowait()
                            except: break
                except Exception: pass
                if self.out_queue is not None:
                    await self.out_queue.put({"data": data, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"})

    async def receive_audio(self):
        while True:
            if self.session is not None:
                turn = self.session.receive()
                async for response in turn:
                    
                    if response.tool_call:
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"\n[SYSTEM] AI triggered tool: {fc.name}")
                            
                            if fc.name == "get_weather":
                                loc = fc.args.get("location", "")
                                result_text = await asyncio.to_thread(fetch_weather_data, loc)
                                function_responses.append(types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result_text}))
                            
                            elif fc.name == "open_application":
                                app = fc.args.get("app_name", "")
                                result_text = await asyncio.to_thread(open_application, app)
                                function_responses.append(types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result_text}))
                            
                            elif fc.name == "close_application":
                                app = fc.args.get("app_name", "")
                                result_text = await asyncio.to_thread(close_application, app)
                                function_responses.append(types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result_text}))
                                
                            elif fc.name == "create_and_write_file":
                                filename = fc.args.get("filename", "Untitled")
                                content = fc.args.get("content", "")
                                result_text = await asyncio.to_thread(create_and_write_file, filename, content)
                                function_responses.append(types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result_text}))
                                
                            elif fc.name == "send_whatsapp_message_gui":
                                contact = fc.args.get("contact_name", "")
                                message = fc.args.get("message_text", "")
                                result_text = await asyncio.to_thread(send_whatsapp_message_gui, contact, message)
                                function_responses.append(types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result_text}))
                                
                            elif fc.name == "google_search":
                                query = fc.args.get("query", "")
                                result_text = await asyncio.to_thread(google_search_api, query)
                                function_responses.append(types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result_text}))
                        
                        if function_responses:
                            await self.session.send_tool_response(function_responses=function_responses)
                        continue
                        
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)
                        continue
                    if text := response.text:
                        print(text, end="", flush=True)
                        AI_CHAT_QUEUE.append(text)
                while not self.audio_in_queue.empty(): self.audio_in_queue.get_nowait()

    async def play_audio(self):
        global IS_SPEAKING, CURRENT_AI_VOLUME
        stream = await asyncio.to_thread(pya.open, format=FORMAT, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True)
        while True:
            if self.audio_in_queue is not None:
                bytestream = await self.audio_in_queue.get()
                IS_SPEAKING = True
                try:
                    audio_array = np.frombuffer(bytestream, dtype=np.int16)
                    rms = np.sqrt(np.mean(np.square(audio_array.astype(np.float32))))
                    CURRENT_AI_VOLUME = min(1.0, float(rms) / 5000.0) 
                except Exception: CURRENT_AI_VOLUME = 0.5 
                await asyncio.to_thread(stream.write, bytestream)
                if self.audio_in_queue.empty(): IS_SPEAKING = False; CURRENT_AI_VOLUME = 0.0

    async def run(self):
        while True:
            try:
                active_client = get_next_client()
                async with (
                    active_client.aio.live.connect(model=MODEL, config=CONFIG) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=5)

                    tg.create_task(self.send_text_realtime()) 
                    tg.create_task(self.send_realtime())
                    tg.create_task(self.listen_audio())
                    tg.create_task(self.get_frames())
                    tg.create_task(self.receive_audio())
                    tg.create_task(self.play_audio())

                    while True: 
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except RuntimeError as e:
                if "cannot schedule new futures" in str(e) or "Event loop is closed" in str(e):
                    break
                import traceback
                traceback.print_exc()
                print(f"\n[SYSTEM] Connection terminated or key quota exhausted ({e}). Seamlessly switching to next key...")
                try:
                    await asyncio.sleep(1)
                except:
                    break
            except (ExceptionGroup, Exception) as err:
                if self.audio_stream is not None:
                    try:
                        self.audio_stream.close()
                    except Exception:
                        pass
                import traceback
                traceback.print_exc()
                print(f"\n[SYSTEM] Connection terminated or key quota exhausted ({err}). Seamlessly switching to next key...")
                await asyncio.sleep(1)

# =====================================================================
# MAIN EXECUTION SEQUENCE
# =====================================================================
if __name__ == "__main__":
    print("[ELIVORA SYSTEM] Booting Local Background Services...")
    
    scan_system_apps()
    threading.Thread(target=measure_latency, daemon=True).start()
    threading.Thread(target=camera_worker, daemon=True).start()
    threading.Thread(target=start_web_server, daemon=True).start()
    
    def start_ai_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        main_loop = AudioLoop()
        loop.run_until_complete(main_loop.run())

    threading.Thread(target=start_ai_loop, daemon=True).start()
    
    print("[ELIVORA SYSTEM] Launching Standalone Desktop Interface...")
    
    api = WebviewAPI()
    webview_window = webview.create_window(
        title='ELIVORA HUB', 
        url='http://127.0.0.1:8080',
        js_api=api,
        width=1280, 
        height=800,
        background_color='#050505',
        confirm_close=True
    )
    
    webview.start()
    
    print("\n[SYSTEM] Standalone Desktop Interface Closed. Terminating services...")
    os._exit(0)
