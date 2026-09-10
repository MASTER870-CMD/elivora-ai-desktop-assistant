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
import urllib.parse
import urllib.request
import socket
import subprocess

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




CLOUD_HTML = r"""
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ELIVORA CLOUD | Dual-Pipeline Serverless Platform</title>
    
    <!-- Modern Typography & Frameworks -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <style>
        /* ==========================================================================
           ORIGINAL HIGH-CONTRAST WHITE & BLACK LIGHT THEME
           STRICT: ZERO PURPLE, ZERO PINK, ZERO NEON ORANGE, ZERO PURPLE-SLATES.
           ========================================================================== */
        :root[data-theme="light"], :root {
            --bg-main: #f8fafc; 
            --bg-sidebar: #ffffff; 
            --bg-card: #ffffff;
            --text-main: #0f172a; 
            --text-muted: #64748b; 
            --border-color: #e2e8f0;
            --primary: #0f172a; 
            --primary-hover: #334155; 
            --primary-light: #f1f5f9;
            --accent-green: #10b981; 
            --accent-green-light: #d1fae5;
            --warning: #f59e0b; 
            --warning-light: #fef3c7;
            --danger: #ef4444; 
            --danger-light: #fee2e2;
            --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            --modal-bg: rgba(255, 255, 255, 0.85);
            --card-overlay: rgba(255, 255, 255, 0.95);
        }

        body { 
            font-family: 'Inter', sans-serif; 
            background-color: var(--bg-main); 
            color: var(--text-main); 
            transition: background-color 0.3s ease; 
            overflow-x: hidden; 
            margin: 0;
            padding: 0;
        }

        #app-container { min-height: 100vh; }
        .sidebar { 
            width: 260px; 
            background: var(--bg-sidebar); 
            border-right: 1px solid var(--border-color); 
            height: 100vh; 
            position: fixed; 
            z-index: 1040; 
            transition: transform 0.3s ease; 
        }
        .main-content { 
            margin-left: 260px; 
            padding: 2rem; 
            padding-bottom: 140px !important; /* Ample bottom clearance so no elements go behind UI / taskbar */
            min-height: 100vh; 
            transition: margin-left 0.3s ease; 
        }

        .nav-link-custom { 
            color: var(--text-muted); 
            padding: 10px 16px; 
            border-radius: 8px; 
            margin-bottom: 4px; 
            display: flex; 
            align-items: center; 
            gap: 12px; 
            text-decoration: none; 
            font-weight: 500; 
            transition: 0.2s; 
            cursor: pointer; 
        }
        .nav-link-custom:hover, .nav-link-custom.active { 
            background-color: var(--primary-light); 
            color: var(--text-main); 
            font-weight: 600; 
        }

        .saas-card { 
            background: var(--bg-card); 
            border: 1px solid var(--border-color); 
            border-radius: 12px; 
            box-shadow: var(--shadow-sm); 
            transition: transform 0.2s ease, box-shadow 0.2s ease; 
            position: relative; 
            z-index: 1; 
            overflow: hidden; 
            will-change: transform; 
            transform: translateZ(0); 
        }
        .saas-card:hover, .saas-card:focus-within { 
            box-shadow: var(--shadow-md); 
            transform: translateY(-2px) translateZ(0); 
            border-color: #cbd5e1; 
            z-index: 10; 
        }
        
        .repo-card-wrapper { transition: opacity 0.3s ease, transform 0.3s ease; transform-origin: top; }

        .card-process-overlay {
            position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background: var(--card-overlay); backdrop-filter: blur(8px);
            z-index: 20; display: flex; flex-direction: column; align-items: center; justify-content: center;
            opacity: 0; pointer-events: none; transition: opacity 0.2s ease;
        }
        .card-process-overlay.active { opacity: 1; pointer-events: auto; }

        .dropdown-menu { 
            background-color: var(--bg-card); 
            border: 1px solid var(--border-color); 
            box-shadow: var(--shadow-lg); 
            z-index: 1050; 
            padding: 8px; 
            border-radius: 12px; 
        }
        .dropdown-item { 
            color: var(--text-main); 
            border-radius: 6px; 
            font-size: 0.9rem; 
            font-weight: 500; 
            padding: 8px 16px; 
            transition: 0.2s; 
            cursor: pointer; 
        }
        .dropdown-item:hover { 
            background-color: var(--primary-light); 
            color: var(--text-main); 
        }

        .preview-wrapper { 
            width: 100%; height: 160px; border-radius: 8px; overflow: hidden; position: relative; 
            margin-bottom: 1rem; display: flex; align-items: center; justify-content: center;
            cursor: pointer; transition: opacity 0.2s ease;
            box-shadow: inset 0 0 0 1px rgba(0,0,0,0.05);
            background: #ffffff;
        }
        .preview-wrapper:hover { opacity: 0.9; }
        .preview-iframe { 
            width: 400%; height: 400%; transform: scale(0.25); transform-origin: top left; 
            border: none; outline: none; position: absolute; top: 0; left: 0; 
            background: #ffffff; pointer-events: none; 
        }
        .preview-shield { 
            position: absolute; top: 0; left: 0; width: 100%; height: 100%; 
            z-index: 5; background: transparent; cursor: pointer; 
        }

        .status-badge { 
            padding: 4px 10px; font-size: 0.75rem; font-weight: 600; 
            border-radius: 50px; display: inline-flex; align-items: center; 
            gap: 6px; letter-spacing: 0.5px; 
        }
        .status-badge.live { background: var(--accent-green-light); color: var(--accent-green); }
        .status-badge.paused { background: var(--warning-light); color: var(--warning); }
        .status-badge.failed { background: var(--danger-light); color: var(--danger); }
        .status-dot { width: 6px; height: 6px; border-radius: 50%; }
        .live .status-dot { background: var(--accent-green); box-shadow: 0 0 6px var(--accent-green); }
        .paused .status-dot { background: var(--warning); }
        .failed .status-dot { background: var(--danger); }

        .form-control-custom { 
            background: var(--bg-main); 
            border: 1px solid var(--border-color); 
            color: var(--text-main); 
            border-radius: 8px; 
            padding: 10px 16px; 
            width: 100%; 
            transition: 0.2s; 
            font-size: 0.95rem;
        }
        .form-control-custom:focus { 
            outline: none; 
            border-color: var(--text-main); 
            box-shadow: 0 0 0 3px var(--primary-light); 
            background: #ffffff;
        }
        .form-control-custom::placeholder {
            color: #94a3b8;
        }

        .btn-primary-custom { 
            background: var(--primary); 
            color: #ffffff; 
            border: none; 
            padding: 10px 20px; 
            border-radius: 8px; 
            font-weight: 600; 
            transition: all 0.2s ease; 
            cursor: pointer;
        }
        .btn-primary-custom:hover { 
            background: var(--primary-hover); 
            color: #ffffff; 
            transform: translateY(-1px); 
        }
        .btn-primary-custom:disabled {
            opacity: 0.65;
            cursor: not-allowed;
            transform: none;
        }
        
        .upload-zone { 
            border: 2px dashed var(--border-color); 
            border-radius: 12px; 
            padding: 32px 24px; 
            text-align: center; 
            background: var(--bg-main); 
            cursor: pointer; 
            transition: all 0.2s ease; 
        }
        .upload-zone:hover, .upload-zone.dragover { 
            border-color: var(--text-main); 
            background: var(--primary-light); 
        }

        .view-section { display: none; animation: fadeIn 0.3s ease; padding-bottom: 40px; }
        .view-section.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

        .elivora-overlay { 
            position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; 
            background: var(--modal-bg); backdrop-filter: blur(5px); 
            z-index: 2000; display: flex; align-items: center; justify-content: center; 
            opacity: 0; pointer-events: none; transition: opacity 0.3s ease; 
        }
        .elivora-overlay.active { opacity: 1; pointer-events: auto; }
        .elivora-modal { 
            background: var(--bg-card); width: 100%; max-width: 520px; 
            border-radius: 16px; border: 1px solid var(--border-color); 
            box-shadow: var(--shadow-lg); transform: translateY(20px) scale(0.95); 
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1); 
            max-height: 90vh;
            overflow-y: auto;
        }
        .elivora-overlay.active .elivora-modal { transform: translateY(0) scale(1); }

        @keyframes subtlePulse { 0% { opacity: 0.3; } 50% { opacity: 1; } 100% { opacity: 0.3; } }
        .sync-indicator { 
            display: inline-block; width: 8px; height: 8px; border-radius: 50%; 
            background: var(--accent-green); margin-left: 8px; animation: subtlePulse 2s infinite; 
        }

        /* Dual-Pipeline Segmented Toggle */
        .pipeline-toggle-pill {
            display: flex;
            background: var(--primary-light);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 4px;
            gap: 4px;
        }
        .pipeline-toggle-item {
            flex: 1;
            padding: 9px 16px;
            border-radius: 7px;
            border: none;
            background: transparent;
            color: var(--text-muted);
            font-size: 0.875rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .pipeline-toggle-item:hover {
            color: var(--text-main);
        }
        .pipeline-toggle-item.active {
            background: var(--bg-card);
            color: var(--text-main);
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--border-color);
        }

        .accordion-header-btn {
            background: transparent;
            border: none;
            padding: 0;
            width: 100%;
            text-align: left;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .toast-container-custom {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 2500;
            display: flex;
            flex-direction: column;
            gap: 8px;
            pointer-events: none;
        }
        .toast-item {
            background: var(--text-main);
            color: #ffffff;
            border-radius: 8px;
            padding: 12px 18px;
            font-size: 0.875rem;
            font-weight: 500;
            box-shadow: var(--shadow-lg);
            display: flex;
            align-items: center;
            gap: 10px;
            pointer-events: auto;
            animation: slideInUp 0.25s ease;
        }
        .toast-item.error { background: var(--danger); }
        .toast-item.success { background: #0f172a; border-left: 4px solid var(--accent-green); }
        .toast-item.warning { background: #0f172a; border-left: 4px solid var(--warning); }
        @keyframes slideInUp { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

        /* Hovering Persistent Background Progress Widget */
        #globalFloatingProgress {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 2200;
            width: 380px;
            max-width: calc(100vw - 48px);
            animation: slideInUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }

        @media (max-width: 991px) {
            .sidebar { transform: translateX(-100%); box-shadow: var(--shadow-md); }
            .sidebar.open { transform: translateX(0); }
            .main-content { margin-left: 0; padding: 1rem; padding-bottom: 140px !important; }
            .sidebar-overlay { display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); z-index: 1030; }
            .sidebar-overlay.show { display: block; }
            #globalFloatingProgress { width: calc(100vw - 32px); bottom: 16px; right: 16px; }
        }
    </style>
</head>
<body>
    <div id="toastContainer" class="toast-container-custom"></div>

    <!-- Persistent Hovering Background Progress Widget -->
    <div id="globalFloatingProgress" class="d-none">
        <div class="saas-card p-3" style="box-shadow: var(--shadow-lg); border-left: 4px solid var(--primary); background: var(--bg-card);">
            <div class="d-flex align-items-center justify-content-between mb-2">
                <div class="d-flex align-items-center gap-2 text-truncate pe-2">
                    <div class="spinner-border spinner-border-sm text-primary flex-shrink-0" id="floatSpinner" style="width: 14px; height: 14px; border-width: 2px;"></div>
                    <span class="fw-bold text-main small text-truncate" id="floatProjectName">deployment</span>
                    <span class="badge bg-light text-dark border flex-shrink-0" id="floatBadge" style="font-size: 0.65rem; border-color: var(--border-color) !important;">ELIVORA</span>
                </div>
                <span class="fw-bold text-primary small flex-shrink-0" id="floatPercent">0%</span>
            </div>
            <div class="progress mb-2" style="height: 6px; background: var(--border-color);">
                <div class="progress-bar progress-bar-striped progress-bar-animated" id="floatProgressBar" style="width: 0%; transition: 0.1s linear; background-color: var(--primary);"></div>
            </div>
            <div class="d-flex justify-content-between align-items-center mb-2" style="font-size: 0.75rem;">
                <span class="text-muted text-truncate me-2" id="floatStatusText">Initializing pipeline...</span>
                <span class="fw-semibold text-main flex-shrink-0" id="floatTimeRemaining">Calculating...</span>
            </div>
            <div class="d-flex justify-content-between align-items-center pt-2 border-top" style="border-color: var(--border-color) !important; font-size: 0.72rem;">
                <span class="text-muted"><i class="bi bi-clock-history me-1"></i>Running in background</span>
                <button type="button" class="btn btn-sm btn-outline-dark py-0 px-2 fw-semibold" style="font-size: 0.72rem; border-radius: 4px;" onclick="switchView('deploy', document.querySelectorAll('.nav-link-custom')[2])">
                    View in Deploy
                </button>
            </div>
        </div>
    </div>

    <!-- Confirm Delete Modal -->
    <div class="elivora-overlay" id="confirmDeleteOverlay">
        <div class="elivora-modal p-4 p-md-5 text-center">
            <div class="rounded-circle d-flex align-items-center justify-content-center mx-auto mb-3" style="width: 60px; height: 60px; background: var(--danger-light); color: var(--danger);">
                <i class="bi bi-exclamation-triangle-fill fs-3"></i>
            </div>
            <h4 class="fw-bold text-main mb-2">Delete Repository?</h4>
            <p class="text-muted small mb-4">Are you sure you want to permanently delete <b class="text-main" id="confirmDeleteName"></b> from your GitHub account? This action cannot be undone.</p>
            <div class="d-flex gap-2 justify-content-center mt-4">
                <button class="btn border form-control-custom w-auto bg-transparent text-main" onclick="closeModals()">Cancel</button>
                <button class="btn btn-danger fw-bold px-4" onclick="executeConfirmedDelete()">Yes, Delete</button>
            </div>
        </div>
    </div>

    <!-- Maintenance / Pause Modal -->
    <div class="elivora-overlay" id="pauseModalOverlay">
        <div class="elivora-modal p-4 p-md-5">
            <h4 class="fw-bold text-main mb-2"><i class="bi bi-pause-fill text-warning me-2"></i>Global Maintenance</h4>
            <p class="text-muted small mb-4">Temporarily replace your live website with a maintenance page globally.</p>
            <input type="hidden" id="pauseProjectId">
            <div class="form-check form-switch mb-3">
                <input class="form-check-input" type="checkbox" id="useCustomHtmlToggle" onchange="toggleCustomHtml()">
                <label class="form-check-label small fw-bold text-main" for="useCustomHtmlToggle">Use Custom Maintenance HTML</label>
            </div>
            <div class="mb-4" id="standardPauseInput">
                <label class="form-label small fw-bold text-main">PUBLIC MAINTENANCE REASON</label>
                <input type="text" id="pauseReasonInput" class="form-control-custom" placeholder="e.g. Undergoing redesign, back soon!">
            </div>
            <div class="mb-4 d-none" id="customPauseInput">
                <label class="form-label small fw-bold text-main">CUSTOM HTML CODE</label>
                <textarea id="pauseCustomHtmlCode" class="form-control-custom font-monospace text-muted small" rows="5" placeholder="<html><body><h1>We are updating!</h1></body></html>"></textarea>
            </div>
            <div class="d-flex gap-2 justify-content-end mt-4">
                <button class="btn border form-control-custom w-auto bg-transparent text-main" onclick="closeModals()">Cancel</button>
                <button class="btn btn-warning text-dark fw-bold px-4 border-0" onclick="executeGlobalPause()">Apply Maintenance</button>
            </div>
        </div>
    </div>

    <!-- Rename Modal -->
    <div class="elivora-overlay" id="renameModalOverlay">
        <div class="elivora-modal p-4 p-md-5">
            <h4 class="fw-bold text-main mb-2"><i class="bi bi-input-cursor-text text-primary me-2"></i>Rename Website</h4>
            <p class="text-muted small mb-4">This will change the repository name and your deployment URL.</p>
            <input type="hidden" id="renameOldName">
            <div class="mb-4">
                <label class="form-label small fw-bold text-main">NEW PROJECT ALIAS</label>
                <div class="d-flex border rounded border-color overflow-hidden">
                    <span class="px-3 py-2 bg-main text-muted border-end border-color">alias/</span>
                    <input type="text" id="renameNewName" class="form-control border-0 shadow-none bg-card text-main" placeholder="new-name">
                </div>
            </div>
            <div class="d-flex gap-2 justify-content-end mt-4">
                <button class="btn border form-control-custom w-auto bg-transparent text-main" onclick="closeModals()">Cancel</button>
                <button class="btn btn-primary-custom" onclick="executeRename()">Save Name</button>
            </div>
        </div>
    </div>

    <!-- Paste .env Modal -->
    <div class="elivora-overlay" id="pasteEnvOverlay">
        <div class="elivora-modal p-4 p-md-5">
            <h5 class="fw-bold text-main mb-1"><i class="bi bi-clipboard-data text-primary me-2"></i>Paste .env Content</h5>
            <p class="text-muted small mb-3">Paste raw <code>KEY=VALUE</code> lines to automatically populate your environment variables.</p>
            <textarea id="pasteEnvTextarea" class="form-control-custom font-monospace small mb-3" rows="8" placeholder="GEMINI_API_KEY=AIzaSy...&#10;AUTH_SECRET=super-secret-key&#10;NODE_ENV=production"></textarea>
            <div class="d-flex justify-content-end gap-2">
                <button type="button" class="btn border form-control-custom w-auto bg-transparent text-main" onclick="closeModals()">Cancel</button>
                <button type="button" class="btn btn-primary-custom" onclick="applyPastedEnv()">Import Variables</button>
            </div>
        </div>
    </div>

    <!-- Vercel Project Settings & Auto Re-Deploy Modal -->
    <div class="elivora-overlay" id="vercelSettingsModalOverlay">
        <div class="elivora-modal p-4 p-md-5">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="fw-bold text-main mb-0"><i class="bi bi-sliders text-dark me-2"></i>Project Engine Settings</h5>
                <button type="button" class="btn-close" onclick="closeModals()"></button>
            </div>
            <p class="text-muted small mb-4">Edit build settings and environment variables stored for this project, and trigger an auto re-deploy.</p>
            <input type="hidden" id="modalVercelProjectId">

            <div class="mb-3">
                <label class="form-label small fw-bold text-main">APPLICATION PRESET</label>
                <select id="modalVercelPreset" class="form-control-custom" onchange="handleModalPresetChange(this.value)">
                    <option value="Other">Other</option>
                    <option value="React">React</option>
                    <option value="Vite">Vite</option>
                    <option value="Next.js">Next.js</option>
                </select>
            </div>

            <div class="mb-3">
                <label class="form-label small fw-bold text-main">ROOT DIRECTORY</label>
                <input type="text" id="modalVercelRootDir" class="form-control-custom" value="./">
            </div>

            <div class="border rounded-3 p-3 mb-3 bg-white" style="border-color: var(--border-color) !important;">
                <label class="form-label small fw-bold text-main text-uppercase mb-2">Build and Output Settings</label>
                <div class="mb-2">
                    <label class="form-label small text-muted mb-1">BUILD COMMAND</label>
                    <input type="text" id="modalVercelBuildCmd" class="form-control-custom" placeholder="npm run build">
                </div>
                <div class="mb-2">
                    <label class="form-label small text-muted mb-1">OUTPUT DIRECTORY</label>
                    <input type="text" id="modalVercelOutputDir" class="form-control-custom" placeholder="dist (leave empty for Next.js)">
                </div>
                <div class="mb-0">
                    <label class="form-label small text-muted mb-1">INSTALL COMMAND</label>
                    <input type="text" id="modalVercelInstallCmd" class="form-control-custom" placeholder="npm install">
                </div>
            </div>

            <!-- Modal Environment Variables -->
            <div class="border rounded-3 p-3 mb-4 bg-white" style="border-color: var(--border-color) !important;">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <div>
                        <div class="fw-bold text-main small text-uppercase">Environment Variables</div>
                        <div class="text-muted small" style="font-size:0.75rem;">Stored locally for this project</div>
                    </div>
                    <div class="d-flex gap-1">
                        <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="triggerModalEnvFileImport()" style="font-size:0.75rem; border-color: var(--border-color) !important;">
                            <i class="bi bi-file-earmark-arrow-up"></i> .env
                        </button>
                        <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="addEnvVariableRow('', '', 'modalEnvRowsContainer')" style="font-size:0.75rem; border-color: var(--border-color) !important;">
                            <i class="bi bi-plus-lg"></i> Add
                        </button>
                    </div>
                </div>
                <input type="file" id="modalEnvFileInput" accept=".env,.env.*,.txt" class="d-none" onchange="handleModalEnvFileSelect(event)">
                <div id="modalEnvRowsContainer" class="d-flex flex-column gap-2 mt-2" style="max-height: 200px; overflow-y: auto;">
                    <!-- Rows populated dynamically -->
                </div>
            </div>

            <div class="d-flex justify-content-end gap-2">
                <button type="button" class="btn border form-control-custom w-auto bg-transparent text-main" onclick="closeModals()">Cancel</button>
                <button type="button" class="btn border form-control-custom w-auto bg-white text-main fw-semibold" onclick="saveVercelModalSettingsOnly()">Save Settings</button>
                <button type="button" class="btn btn-primary-custom d-flex align-items-center gap-1" onclick="saveAndAutoRedeployFromModal()">
                    <i class="bi bi-arrow-repeat"></i> Save & Auto Re-Deploy
                </button>
            </div>
        </div>
    </div>

    <!-- Application Shell -->
    <div id="app-container">
        <div class="sidebar-overlay" onclick="toggleSidebar()"></div>

        <!-- Sidebar Navigation -->
        <nav class="sidebar d-flex flex-column p-3">
            <div class="d-flex align-items-center justify-content-between mb-4 px-2 mt-2">
                <h4 class="fw-bold mb-0 text-main d-flex align-items-center gap-2">
                    <div class="bg-primary rounded text-white d-flex align-items-center justify-content-center" style="width:32px; height:32px;"><i class="bi bi-layers-fill fs-6"></i></div>
                    ELIVORA CLOUD
                </h4>
                <button class="btn d-lg-none text-main border-0 p-1" onclick="toggleSidebar()"><i class="bi bi-x-lg"></i></button>
            </div>
            <div class="d-flex flex-column gap-1 flex-grow-1">
                <span class="text-muted small fw-bold px-2 mt-2 mb-1" style="font-size: 0.7rem; letter-spacing: 0.5px;">PLATFORM</span>
                <a class="nav-link-custom" onclick="switchView('dashboard', this)"><i class="bi bi-grid"></i> Overview</a>
                <a class="nav-link-custom active" onclick="switchView('analytics', this)"><i class="bi bi-bar-chart"></i> Analytics</a>
                <a class="nav-link-custom" onclick="switchView('deploy', this)"><i class="bi bi-cloud-arrow-up"></i> Deployments</a>
                <a class="nav-link-custom" onclick="switchView('github_connect', this)" id="navGithubConnect"><i class="bi bi-github"></i> GitHub Connect <span class="badge bg-success ms-1" style="font-size:0.6rem;" id="ghConnectBadge">NEW</span></a>
                <span class="text-muted small fw-bold px-2 mt-4 mb-1" style="font-size: 0.7rem; letter-spacing: 0.5px;">CONFIGURATION</span>
                <a class="nav-link-custom" onclick="switchView('settings', this)"><i class="bi bi-key"></i> API Config</a>
                <span class="text-muted small fw-bold px-2 mt-4 mb-1" style="font-size: 0.7rem; letter-spacing: 0.5px;">SYSTEM</span>
                <a href="/" class="nav-link-custom text-main"><i class="bi bi-arrow-left-circle"></i> Back to Hub</a>
            </div>
        </nav>

        <!-- Main Content Area -->
        <main class="main-content">
            <header class="d-flex justify-content-between align-items-center mb-4">
                <div class="d-flex align-items-center gap-3">
                    <button class="btn d-lg-none text-main border-0 p-0" onclick="toggleSidebar()"><i class="bi bi-list fs-2"></i></button>
                    <h3 class="fw-bold mb-0 text-main" id="pageTitle">Analytics Dashboard</h3>
                </div>
                <div class="d-flex align-items-center gap-3">
                    <span class="text-muted small fw-bold d-none d-md-flex align-items-center">LIVE SYNC <span class="sync-indicator"></span></span>
                    <button class="btn border form-control-custom w-auto bg-card text-main d-none d-sm-flex align-items-center gap-2" onclick="location.reload()">
                        <i class="bi bi-arrow-clockwise"></i> Refresh
                    </button>
                    <a class="btn btn-primary-custom d-none d-sm-block" onclick="switchView('deploy', document.querySelectorAll('.nav-link-custom')[2])">+ New Project</a>
                </div>
            </header>

            <!-- 1. OVERVIEW / DASHBOARD VIEW -->
            <section id="dashboard" class="view-section">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h5 class="fw-bold text-main m-0 d-none d-md-block">Active Deployments</h5>
                    <div class="position-relative w-100" style="max-width: 320px;">
                        <i class="bi bi-search position-absolute top-50 translate-middle-y ms-3 text-muted"></i>
                        <input type="text" class="form-control-custom ps-5" id="searchInput" placeholder="Search deployments..." onkeyup="filterProjects()">
                    </div>
                </div>
                <div class="row g-4" id="projectGrid"></div>
            </section>

            <!-- 2. ANALYTICS VIEW -->
            <section id="analytics" class="view-section active">
                <div class="row g-3 mb-4">
                    <div class="col-md-6">
                        <div class="saas-card p-4">
                            <p class="text-muted small fw-bold mb-1 text-uppercase">Total Deployments</p>
                            <h2 class="fw-bold text-main m-0" id="statTotal">0</h2>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="saas-card p-4">
                            <p class="text-muted small fw-bold mb-1 text-uppercase">Activity (Last 7 Days)</p>
                            <h2 class="fw-bold text-main m-0" id="statRecent">0</h2>
                        </div>
                    </div>
                </div>
                <div class="saas-card p-4 p-md-5 mb-4">
                    <h5 class="fw-bold text-main mb-1">Deployment Velocity</h5>
                    <p class="text-muted small mb-4">Visual velocity tracking of created deployments across both pipelines.</p>
                    <div style="position: relative; height: 300px; width: 100%;">
                        <canvas id="analyticsChart"></canvas>
                    </div>
                </div>
            </section>

            <!-- 3. DEPLOYMENT VIEW (DUAL-PIPELINE) -->
           <!-- 3. DEPLOYMENT VIEW (DUAL-PIPELINE) -->
            <section id="deploy" class="view-section">
                <div class="row justify-content-center">
                    <div class="col-12 col-lg-9 col-xl-7">
                        <!-- Prominent Pipeline Error Banner -->
                        <div id="pipelineErrorBanner" class="alert alert-danger d-none border-2 shadow-sm mb-4 p-3 rounded-3" role="alert">
                            <div class="d-flex align-items-start justify-content-between">
                                <div class="d-flex align-items-start gap-3">
                                    <i class="bi bi-exclamation-octagon-fill fs-3 text-danger flex-shrink-0 mt-1"></i>
                                    <div>
                                        <h5 class="fw-bold text-danger mb-1" id="pipelineErrorTitle">Deployment Pipeline Error</h5>
                                        <p class="mb-0 text-dark small" id="pipelineErrorMessage">An error occurred during deployment.</p>
                                    </div>
                                </div>
                                <button type="button" class="btn-close" onclick="dismissPipelineError()"></button>
                            </div>
                        </div>

                        <div class="saas-card p-4 p-md-5 mb-5">
                            <h4 class="fw-bold text-main mb-1">Dual-Pipeline Deployment</h4>
                            <p class="text-muted small mb-4">Select your architecture: Static (GitHub Pages) or Node.js Fullstack (Vercel).</p>

                            <!-- Pipeline Toggle Switch -->
                            <div class="mb-4">
                                <label class="form-label small fw-bold text-main text-uppercase mb-2">Select Pipeline</label>
                                <div class="pipeline-toggle-pill">
                                    <button type="button" id="btnModeStatic" class="pipeline-toggle-item active" onclick="switchDeployMode('static')">
                                        <i class="bi bi-file-earmark-code me-1"></i> Static Engine
                                    </button>
                                    <button type="button" id="btnModeVercel" class="pipeline-toggle-item" onclick="switchDeployMode('vercel')">
                                        <i class="bi bi-hdd-network me-1"></i> Node.js Fullstack
                                    </button>
                                </div>
                            </div>

                            <!-- PIPELINE 1: STATIC GITHUB PAGES -->
                            <div id="sectionStaticPipeline">
                                <div class="mb-3">
                                    <label class="form-label small fw-bold text-main">PROJECT ALIAS</label>
                                    <div class="d-flex border rounded-3 overflow-hidden" style="border-color: var(--border-color) !important;">
                                        <span class="px-3 py-2 bg-main text-muted border-end d-none d-sm-block small" style="border-color: var(--border-color) !important;">github.io/</span>
                                        <input type="text" id="staticProjectName" class="form-control border-0 shadow-none text-main" placeholder="my-website" style="background: var(--bg-card); color: var(--text-main);">
                                    </div>
                                </div>

                                <div class="upload-zone mb-3" id="staticDropZone" onclick="document.getElementById('staticFileInput').click()">
                                    <i class="bi bi-folder-zip fs-1 text-main mb-2 d-block"></i>
                                    <h5 class="fw-bold text-main mb-1">Drag & Drop .zip File</h5>
                                    <p class="text-muted small mb-1">Processed instantly in your browser</p>
                                    <p class="text-warning small fw-bold mb-0">Note: Main page must be named index.html</p>
                                    <input type="file" id="staticFileInput" accept=".zip" class="d-none">
                                </div>

                                <div id="staticFileCard" class="d-none mb-3 p-3 rounded-3 border d-flex justify-content-between align-items-center" style="border-color: var(--border-color) !important; background: var(--bg-main);">
                                    <div class="d-flex align-items-center gap-2">
                                        <i class="bi bi-file-earmark-zip text-main fs-4"></i>
                                        <div>
                                            <div class="fw-bold text-main small" id="staticFileNameDisplay">archive.zip</div>
                                            <div class="text-muted small" id="staticFileSizeDisplay">0 KB</div>
                                        </div>
                                    </div>
                                    <button type="button" class="btn btn-sm text-danger border-0 p-1" onclick="clearStaticFile()"><i class="bi bi-x-lg"></i></button>
                                </div>

                                <button type="button" id="staticDeployBtn" class="btn-primary-custom w-100 py-3 fw-bold d-flex align-items-center justify-content-center gap-2" onclick="triggerStaticDeploy()">
                                    <i class="bi bi-cloud-arrow-up-fill"></i> Deploy Static Project
                                </button>

                                <div id="staticProgressContainer" class="mt-4 p-3 border rounded-3 bg-main d-none" style="border-color: var(--border-color) !important;">
                                    <div class="d-flex justify-content-between mb-1">
                                        <span class="fw-bold text-main small" id="staticStatusText">Extracting files...</span>
                                        <span class="fw-bold text-main small" id="staticProgressText">0%</span>
                                    </div>
                                    <div class="progress mb-2" style="height: 6px; background: var(--border-color);">
                                        <div class="progress-bar progress-bar-striped progress-bar-animated" id="staticProgressBar" style="width: 0%; transition: 0.1s linear; background-color: var(--primary);"></div>
                                    </div>
                                    <div class="d-flex justify-content-between text-muted small" style="font-size: 0.75rem;">
                                        <span>Estimated remaining:</span>
                                        <span class="fw-semibold text-main" id="staticTimeRemaining">Calculating...</span>
                                    </div>
                                </div>
                            </div>

                            <!-- PIPELINE 2: NODE.JS VERCEL (MIMICS VERCEL IMPORT DASHBOARD) -->
                            <div id="sectionVercelPipeline" class="d-none">
                                <!-- Project Name -->
                                <div class="mb-3">
                                    <label class="form-label small fw-bold text-main">PROJECT NAME</label>
                                    <div class="d-flex border rounded-3 overflow-hidden" style="border-color: var(--border-color) !important;">
                                        <input type="text" id="vercelProjectName" class="form-control border-0 shadow-none text-main" placeholder="my-app" style="background: var(--bg-card); color: var(--text-main);">
                                        <span class="px-3 py-2 bg-main text-muted border-start d-none d-sm-block small" style="border-color: var(--border-color) !important;">.vercel.app</span>
                                    </div>
                                </div>

                                <!-- Application Preset -->
                                <div class="mb-3">
                                    <label class="form-label small fw-bold text-main">APPLICATION PRESET</label>
                                    <select id="vercelPreset" class="form-control-custom" onchange="handlePresetChange(this.value)">
                                        <option value="Other" selected>Other (Node.js / Custom)</option>
                                        <option value="React">React (Create React App)</option>
                                        <option value="Vite">Vite (React/Vue/Vanilla)</option>
                                        <option value="Next.js">Next.js</option>
                                    </select>
                                </div>

                                <!-- Root Directory -->
                                <div class="mb-3">
                                    <label class="form-label small fw-bold text-main">ROOT DIRECTORY</label>
                                    <input type="text" id="vercelRootDir" class="form-control-custom" value="./" placeholder="./">
                                </div>

                                <!-- Build and Output Settings Accordion -->
                                <div class="border rounded-3 p-3 mb-3 bg-white" style="border-color: var(--border-color) !important;">
                                    <button type="button" class="accordion-header-btn" onclick="toggleBuildSettings()">
                                        <div>
                                            <div class="fw-bold text-main small text-uppercase">Build and Output Settings</div>
                                            <div class="text-muted small">Configure build command, output directory, and install command</div>
                                        </div>
                                        <i class="bi bi-chevron-down text-muted" id="buildChevronIcon" style="transition: transform 0.2s ease;"></i>
                                    </button>
                                    <div id="buildSettingsBody" class="d-none mt-3 pt-3 border-top" style="border-color: var(--border-color) !important;">
                                        <div class="mb-3">
                                            <label class="form-label small fw-bold text-main">BUILD COMMAND</label>
                                            <input type="text" id="vercelBuildCommand" class="form-control-custom" placeholder="npm run build">
                                            <div class="form-text text-muted small mt-1">Default: <code>npm run build</code></div>
                                        </div>
                                        <div class="mb-3">
                                            <label class="form-label small fw-bold text-main">OUTPUT DIRECTORY</label>
                                            <input type="text" id="vercelOutputDir" class="form-control-custom" placeholder="dist (leave empty for Next.js)">
                                            <div class="form-text text-muted small mt-1">Leave empty for Next.js automatic output. Use <code>dist</code> for Vite, <code>build</code> for React.</div>
                                        </div>
                                        <div class="mb-0">
                                            <label class="form-label small fw-bold text-main">INSTALL COMMAND</label>
                                            <input type="text" id="vercelInstallCommand" class="form-control-custom" placeholder="npm install">
                                            <div class="form-text text-muted small mt-1">Default: <code>npm install</code> (safer than <code>npm ci</code> for repos without strict lockfile).</div>
                                        </div>
                                    </div>
                                </div>

                                <!-- Environment Variables -->
                                <div class="border rounded-3 p-3 mb-3 bg-white" style="border-color: var(--border-color) !important;">
                                    <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
                                        <div>
                                            <div class="fw-bold text-main small text-uppercase">Environment Variables</div>
                                            <div class="text-muted small">Key-value parameters injected into build & runtime</div>
                                        </div>
                                        <div class="d-flex gap-2 flex-wrap">
                                            <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="syncEnvFromLocalEnv('envRowsContainer')" title="Auto-load API keys from your workspace .env file">
                                                <i class="bi bi-download me-1"></i> Load from .env
                                            </button>
                                            <input type="file" id="envFileInput" accept=".env,.env.*,.txt" class="d-none" onchange="handleEnvFileSelect(event)">
                                            <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="document.getElementById('envFileInput').click()" title="Upload a .env file">
                                                <i class="bi bi-file-earmark-arrow-up me-1"></i> Import .env
                                            </button>
                                            <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="openPasteEnvModal()" title="Paste raw .env content">
                                                <i class="bi bi-clipboard-plus me-1"></i> Paste .env
                                            </button>
                                            <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="addEnvVariableRow()">
                                                <i class="bi bi-plus-lg me-1"></i> Add More
                                            </button>
                                        </div>
                                    </div>
                                    <div id="envRowsContainer" class="d-flex flex-column gap-2 mt-2">
                                        <!-- Dynamic rows will be inserted here -->
                                    </div>
                                </div>

                                <!-- Upload Zone -->
                                <div class="upload-zone mb-3" id="vercelDropZone" onclick="document.getElementById('vercelFileInput').click()">
                                    <i class="bi bi-cloud-arrow-up fs-1 text-main mb-2 d-block"></i>
                                    <h5 class="fw-bold text-main mb-1">Drag & Drop .zip File</h5>
                                    <p class="text-muted small mb-1">In-browser extraction & automated cloud deployment</p>
                                    <p class="text-muted small mb-0">Supports Next.js, Vite, React, Express, or Node.js</p>
                                    <input type="file" id="vercelFileInput" accept=".zip" class="d-none">
                                </div>

                                <div id="vercelFileCard" class="d-none mb-3 p-3 rounded-3 border d-flex justify-content-between align-items-center" style="border-color: var(--border-color) !important; background: var(--bg-main);">
                                    <div class="d-flex align-items-center gap-2">
                                        <i class="bi bi-file-earmark-zip text-main fs-4"></i>
                                        <div>
                                            <div class="fw-bold text-main small" id="vercelFileNameDisplay">archive.zip</div>
                                            <div class="text-muted small" id="vercelFileSizeDisplay">0 KB</div>
                                        </div>
                                    </div>
                                    <button type="button" class="btn btn-sm text-danger border-0 p-1" onclick="clearVercelFile()"><i class="bi bi-x-lg"></i></button>
                                </div>

                                <!-- Deploy Button -->
                                <button type="button" id="vercelDeployBtn" class="btn-primary-custom w-100 py-3 fw-bold d-flex align-items-center justify-content-center gap-2" onclick="triggerVercelDeploy()">
                                    <i class="bi bi-cloud-arrow-up-fill me-1"></i> Deploy to Elivora Cloud
                                </button>

                                <!-- Progress Container -->
                                <div id="vercelProgressContainer" class="mt-4 p-3 border rounded-3 bg-main d-none" style="border-color: var(--border-color) !important;">
                                    <div class="d-flex justify-content-between mb-1">
                                        <span class="fw-bold text-main small text-truncate pe-2" id="vercelStatusText">Initializing pipeline...</span>
                                        <span class="fw-bold text-main small flex-shrink-0" id="vercelProgressText">0%</span>
                                    </div>
                                    <div class="progress mb-2" style="height: 6px; background: var(--border-color);">
                                        <div class="progress-bar progress-bar-striped progress-bar-animated" id="vercelProgressBar" style="width: 0%; transition: 0.1s linear; background-color: var(--primary);"></div>
                                    </div>
                                    <div class="d-flex justify-content-between text-muted small" style="font-size: 0.75rem;">
                                        <span>Estimated remaining:</span>
                                        <span class="fw-semibold text-main" id="vercelTimeRemaining">Calculating...</span>
                                    </div>
                                </div>
                            </div>

                        </div>
                    </div>
                </div>
            </section>

            <!-- 5. GITHUB CONNECT VIEW -->
            <section id="github_connect" class="view-section">
                <div class="row justify-content-center">
                    <div class="col-12 col-lg-9 col-xl-8">

                        <!-- LOGIN STATE: Not logged in -->
                        <div id="ghLoginPanel" class="saas-card p-5 text-center mb-4">
                            <div class="mb-4">
                                <div class="d-inline-flex align-items-center justify-content-center rounded-circle bg-dark text-white mb-3" style="width:72px;height:72px;">
                                    <i class="bi bi-github" style="font-size:2.2rem;"></i>
                                </div>
                                <h4 class="fw-bold text-main mb-1">Connect Your GitHub Account</h4>
                                <p class="text-muted mb-0">Sign in with GitHub to browse your repos and deploy directly to Elivora Cloud.</p>
                            </div>
                            <button class="btn btn-dark px-5 py-2 fw-semibold d-inline-flex align-items-center gap-2" onclick="loginWithGithub()" id="ghLoginBtn">
                                <i class="bi bi-github"></i> Login with GitHub
                            </button>
                            <p class="text-muted small mt-3 mb-0"><i class="bi bi-shield-lock me-1"></i>Your GitHub token is never stored on our server. Deployment uses our secure backend.</p>
                        </div>

                        <!-- LOGGED IN STATE -->
                        <div id="ghLoggedInPanel" class="d-none">
                            <!-- User Info Bar -->
                            <div class="saas-card p-3 mb-4 d-flex align-items-center justify-content-between flex-wrap gap-3">
                                <div class="d-flex align-items-center gap-3">
                                    <img id="ghUserAvatar" src="" class="rounded-circle" width="40" height="40" style="border:2px solid var(--border-color);">
                                    <div>
                                        <div class="fw-bold text-main small" id="ghUserName">Loading...</div>
                                        <div class="text-muted" style="font-size:0.75rem;" id="ghUserLogin">@username</div>
                                    </div>
                                </div>
                                <div class="d-flex gap-2">
                                    <button class="btn btn-sm border bg-white text-main fw-semibold" onclick="loadUserRepos()">
                                        <i class="bi bi-arrow-clockwise me-1"></i>Refresh Repos
                                    </button>
                                    <button class="btn btn-sm border bg-white text-danger fw-semibold" onclick="logoutGithub()">
                                        <i class="bi bi-box-arrow-right me-1"></i>Logout
                                    </button>
                                </div>
                            </div>

                            <!-- Repo Browser -->
                            <div class="saas-card p-4 mb-4">
                                <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
                                    <div>
                                        <h5 class="fw-bold text-main mb-0">Your Repositories</h5>
                                        <p class="text-muted small mb-0" id="ghRepoCount">Loading...</p>
                                    </div>
                                    <div class="position-relative" style="min-width:220px;">
                                        <i class="bi bi-search position-absolute top-50 translate-middle-y ms-3 text-muted" style="z-index:1;"></i>
                                        <input type="text" class="form-control-custom ps-5" id="ghRepoSearch" placeholder="Search repos..." oninput="filterGhRepos()">
                                    </div>
                                </div>
                                <div id="ghRepoList" class="d-flex flex-column gap-2" style="max-height:400px;overflow-y:auto;">
                                    <div class="text-center text-muted py-5"><i class="bi bi-hourglass-split me-2"></i>Loading your repositories...</div>
                                </div>
                            </div>

                            <!-- Deploy Config Panel (shown after repo selected) -->
                            <div id="ghDeployPanel" class="saas-card p-4 p-md-5 d-none">
                                <div class="d-flex align-items-center gap-2 mb-1">
                                    <i class="bi bi-github fs-5 text-main"></i>
                                    <h5 class="fw-bold text-main mb-0">Deploy: <span id="ghSelectedRepoName">repo-name</span></h5>
                                </div>
                                <p class="text-muted small mb-4">Configure your build settings and environment variables, then deploy.</p>

                                <!-- Branch -->
                                <div class="mb-3">
                                    <label class="form-label small fw-bold text-main">BRANCH</label>
                                    <select id="ghBranchSelect" class="form-control-custom"></select>
                                </div>

                                <!-- Project Name -->
                                <div class="mb-3">
                                    <label class="form-label small fw-bold text-main">PROJECT NAME ON VERCEL</label>
                                    <div class="d-flex border rounded-3 overflow-hidden" style="border-color:var(--border-color)!important;">
                                        <input type="text" id="ghProjectName" class="form-control border-0 shadow-none text-main" placeholder="my-app" style="background:var(--bg-card);">
                                        <span class="px-3 py-2 bg-main text-muted border-start d-none d-sm-block small" style="border-color:var(--border-color)!important;">.vercel.app</span>
                                    </div>
                                </div>

                                <!-- Framework Preset -->
                                <div class="mb-3">
                                    <label class="form-label small fw-bold text-main">FRAMEWORK PRESET</label>
                                    <select id="ghFramework" class="form-control-custom">
                                        <option value="">Other / Node.js</option>
                                        <option value="nextjs">Next.js</option>
                                        <option value="react">Create React App</option>
                                        <option value="vite">Vite</option>
                                        <option value="vue">Vue.js</option>
                                        <option value="nuxtjs">Nuxt.js</option>
                                        <option value="svelte">SvelteKit</option>
                                    </select>
                                </div>

                                <!-- Build Settings Accordion -->
                                <div class="border rounded-3 p-3 mb-3 bg-white" style="border-color:var(--border-color)!important;">
                                    <button type="button" class="accordion-header-btn" onclick="toggleEl('ghBuildSettingsBody','ghBuildChevron')">
                                        <div><div class="fw-bold text-main small text-uppercase">Build & Output Settings</div><div class="text-muted small">Build command, output directory, install command</div></div>
                                        <i class="bi bi-chevron-down text-muted" id="ghBuildChevron" style="transition:transform 0.2s;"></i>
                                    </button>
                                    <div id="ghBuildSettingsBody" class="d-none mt-3 pt-3 border-top" style="border-color:var(--border-color)!important;">
                                        <div class="mb-3"><label class="form-label small fw-bold text-main">BUILD COMMAND</label><input type="text" id="ghBuildCmd" class="form-control-custom" placeholder="npm run build"></div>
                                        <div class="mb-3"><label class="form-label small fw-bold text-main">OUTPUT DIRECTORY</label><input type="text" id="ghOutputDir" class="form-control-custom" placeholder="dist"></div>
                                        <div class="mb-0"><label class="form-label small fw-bold text-main">INSTALL COMMAND</label><input type="text" id="ghInstallCmd" class="form-control-custom" placeholder="npm install"></div>
                                    </div>
                                </div>

                                <!-- Environment Variables -->
                                <div class="border rounded-3 p-3 mb-4 bg-white" style="border-color:var(--border-color)!important;">
                                    <div class="d-flex justify-content-between align-items-center mb-2">
                                        <div><div class="fw-bold text-main small text-uppercase">Environment Variables</div><div class="text-muted small">Injected into build & runtime</div></div>
                                        <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="addGhEnvRow()"><i class="bi bi-plus-lg me-1"></i>Add</button>
                                    </div>
                                    <div id="ghEnvRowsContainer" class="d-flex flex-column gap-2 mt-2"></div>
                                </div>

                                <!-- Auto-redeploy toggle -->
                                <div class="d-flex align-items-center justify-content-between border rounded-3 p-3 mb-4" style="border-color:var(--border-color)!important;">
                                    <div>
                                        <div class="fw-bold text-main small">Auto-Redeploy on Push</div>
                                        <div class="text-muted small">Automatically redeploy when you push to this branch</div>
                                    </div>
                                    <div class="form-check form-switch m-0">
                                        <input class="form-check-input" type="checkbox" id="ghAutoRedeploy" role="switch" style="width:2.5rem;height:1.3rem;cursor:pointer;">
                                    </div>
                                </div>

                                <!-- Deploy Button -->
                                <button type="button" id="ghDeployBtn" class="btn-primary-custom w-100 py-3 fw-bold d-flex align-items-center justify-content-center gap-2" onclick="triggerGithubDeploy()">
                                    <i class="bi bi-rocket-takeoff-fill me-1"></i> Deploy from GitHub
                                </button>

                                <!-- Progress -->
                                <div id="ghDeployProgress" class="mt-4 p-3 border rounded-3 bg-main d-none" style="border-color:var(--border-color)!important;">
                                    <div class="d-flex justify-content-between mb-1">
                                        <span class="fw-bold text-main small text-truncate pe-2" id="ghDeployStatus">Initializing...</span>
                                        <span class="fw-bold text-main small flex-shrink-0" id="ghDeployPct">0%</span>
                                    </div>
                                    <div class="progress mb-2" style="height:6px;background:var(--border-color);">
                                        <div class="progress-bar progress-bar-striped progress-bar-animated" id="ghDeployBar" style="width:0%;background-color:var(--primary);"></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                    </div>
                </div>
            </section>

            <!-- 4. SETTINGS VIEW -->
            <section id="settings" class="view-section">
                <div class="row justify-content-center">
                    <div class="col-12 col-lg-8">
                        <div class="saas-card p-4 p-md-5 mb-5">
                            <div class="d-flex justify-content-between align-items-start mb-3 flex-wrap gap-2">
                                <div>
                                    <h5 class="fw-bold text-main mb-1">API Credentials & Configuration</h5>
                                    <p class="text-muted small mb-0">Authenticate your deployment pipelines for GitHub Pages and Vercel.</p>
                                </div>
                                <div class="d-flex gap-2">
                                    <input type="file" id="apiConfigEnvFileInput" accept=".env,.env.*,.txt" style="display:none;" onchange="handleApiConfigEnvFileSelect(event)">
                                    <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="syncTokensFromLocalEnv()" title="Auto-fill tokens from workspace .env">
                                        <i class="bi bi-arrow-repeat me-1"></i> Sync from .env
                                    </button>
                                    <button type="button" class="btn btn-sm border bg-white text-main fw-semibold px-2 py-1" onclick="document.getElementById('apiConfigEnvFileInput').click()" title="Import tokens from a .env file">
                                        <i class="bi bi-file-earmark-arrow-up me-1"></i> Import .env
                                    </button>
                                </div>
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label small fw-bold text-main">GITHUB USERNAME</label>
                                <input type="text" id="cfgUsername" class="form-control-custom" placeholder="e.g. your-github-handle">
                            </div>
                            
                            <div class="mb-3">
                                <label class="form-label small fw-bold text-main">GITHUB PERSONAL ACCESS TOKEN (PAT)</label>
                                <div class="input-group">
                                    <input type="password" id="cfgToken" class="form-control-custom" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx" style="border-top-right-radius: 0; border-bottom-right-radius: 0;">
                                    <button class="btn border bg-white text-muted" type="button" onclick="toggleSecretVisibility('cfgToken', this)" style="border-color: var(--border-color) !important; border-top-right-radius: 8px; border-bottom-right-radius: 8px;">
                                        <i class="bi bi-eye"></i>
                                    </button>
                                </div>
                                <div class="form-text text-muted small mt-1">Requires <code>repo</code> and <code>workflow</code> scopes.</div>
                            </div>

                            <div class="mb-4">
                                <label class="form-label small fw-bold text-main">VERCEL ACCESS TOKEN</label>
                                <div class="input-group">
                                    <input type="password" id="cfgVercelToken" class="form-control-custom" placeholder="vcp_xxxxxxxxxxxxxxxxxxxx" style="border-top-right-radius: 0; border-bottom-right-radius: 0;">
                                    <button class="btn border bg-white text-muted" type="button" onclick="toggleSecretVisibility('cfgVercelToken', this)" style="border-color: var(--border-color) !important; border-top-right-radius: 8px; border-bottom-right-radius: 8px;">
                                        <i class="bi bi-eye"></i>
                                    </button>
                                </div>
                                <div class="form-text text-muted small mt-1">Generated from your Vercel Account Settings &rarr; Tokens.</div>
                            </div>

                            <div class="d-flex justify-content-end gap-2">
                                <button class="btn-primary-custom px-4" onclick="saveConfig()">
                                    <i class="bi bi-check-lg me-1"></i> Save Configuration
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </section>
        </main>
    </div>

    <!-- Firebase SDK -->
    <script type="module">
        import { initializeApp } from "https://www.gstatic.com/firebasejs/12.18.0/firebase-app.js";
        import { getAuth, GithubAuthProvider, signInWithRedirect, getRedirectResult, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/12.18.0/firebase-auth.js";

        const firebaseConfig = {
            apiKey: "{{FIREBASE_API_KEY}}",
            authDomain: "{{FIREBASE_AUTH_DOMAIN}}",
            projectId: "{{FIREBASE_PROJECT_ID}}",
            storageBucket: "{{FIREBASE_STORAGE_BUCKET}}",
            messagingSenderId: "{{FIREBASE_MESSAGING_SENDER_ID}}",
            appId: "{{FIREBASE_APP_ID}}"
        };
        const fbApp = initializeApp(firebaseConfig);
        const fbAuth = getAuth(fbApp);
        const ghProvider = new GithubAuthProvider();
        ghProvider.addScope('repo');
        ghProvider.addScope('read:user');

        window._fbAuth = fbAuth;
        window._ghProvider = ghProvider;
        window._GithubAuthProvider = GithubAuthProvider;
        window._signInWithRedirect = signInWithRedirect;
        window._signOut = signOut;

        // On page load: check if we just came back from a GitHub redirect login
        getRedirectResult(fbAuth).then((result) => {
            if (result && result.user) {
                const credential = GithubAuthProvider.credentialFromResult(result);
                if (credential && credential.accessToken) {
                    window._lastGhToken = credential.accessToken;
                    window._ghOAuthToken = credential.accessToken;
                    localStorage.setItem('elivora_gh_oauth_token', credential.accessToken);
                }
            }
        }).catch((err) => {
            if (err.code !== 'auth/no-auth-event') {
                console.warn('GitHub redirect result error:', err.message);
                if (window.showToast) showToast('GitHub login error: ' + err.message, 'danger');
            }
        });

        onAuthStateChanged(fbAuth, (user) => {
            if (user) {
                // Restore token from localStorage if redirect result already stored it
                const token = window._ghOAuthToken || localStorage.getItem('elivora_gh_oauth_token');
                if (token) {
                    window._ghOAuthToken = token;
                    localStorage.setItem('elivora_gh_oauth_token', token);
                }
                window._ghUser = user;
                if (window.onGhUserReady) window.onGhUserReady(user);
            } else {
                window._ghUser = null;
                window._ghOAuthToken = null;
                if (window.onGhUserSignedOut) window.onGhUserSignedOut();
            }
        });
    </script>

    <!-- Application JavaScript Engine -->
    <script>
       const CONFIG = {
            USERNAME: localStorage.getItem('elivora_gh_user') || '{{GITHUB_USERNAME_PLACEHOLDER}}',
            TOKEN: localStorage.getItem('elivora_gh_token') || '{{GITHUB_TOKEN_PLACEHOLDER}}',
            VERCEL_TOKEN: localStorage.getItem('elivora_vercel_token') || '{{VERCEL_TOKEN_PLACEHOLDER}}'
        };
        

        let projects = [];
        let activeDeployments = new Set();
        let localStatuses = JSON.parse(localStorage.getItem('elivora_statuses') || '{}');
        let staticSelectedFile = null;
        let vercelSelectedFile = null;
        let currentDeployMode = 'static';
        let analyticsChartInstance = null;

        // Background progress tracking
        let isPipelineActive = false;
        let uploadStartTime = 0;

        function escapeHtml(str) {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        // --- View & Navigation Logic ---
        function switchView(viewId, navEl) {
            document.querySelectorAll('.view-section').forEach(sec => sec.classList.remove('active'));
            const target = document.getElementById(viewId);
            if (target) target.classList.add('active');

            document.querySelectorAll('.nav-link-custom').forEach(link => link.classList.remove('active'));
            if (navEl) navEl.classList.add('active');

            const titleMap = {
                'dashboard': 'Deployments Overview',
                'analytics': 'Analytics Dashboard',
                'deploy': 'Dual-Pipeline Deployment',
                'settings': 'API Credentials & Configuration',
                'github_connect': 'GitHub Connect & Deploy'
            };
            document.getElementById('pageTitle').innerText = titleMap[viewId] || 'Dashboard';
            if (window.innerWidth < 992) toggleSidebar(false);

            if (viewId === 'analytics') {
                setTimeout(renderAnalytics, 100);
            }
        }

        function toggleSidebar(forceState) {
            const sidebar = document.querySelector('.sidebar');
            const overlay = document.querySelector('.sidebar-overlay');
            const shouldOpen = forceState !== undefined ? forceState : !sidebar.classList.contains('open');
            if (shouldOpen) {
                sidebar.classList.add('open');
                overlay.classList.add('show');
            } else {
                sidebar.classList.remove('open');
                overlay.classList.remove('show');
            }
        }

        function toggleSecretVisibility(inputId, btn) {
            const input = document.getElementById(inputId);
            const icon = btn.querySelector('i');
            if (input.type === 'password') {
                input.type = 'text';
                icon.className = 'bi bi-eye-slash';
            } else {
                input.type = 'password';
                icon.className = 'bi bi-eye';
            }
        }

        // --- Pipeline Switch & Preset Management ---
        function switchDeployMode(mode) {
            currentDeployMode = mode;
            const btnStatic = document.getElementById('btnModeStatic');
            const btnVercel = document.getElementById('btnModeVercel');
            const secStatic = document.getElementById('sectionStaticPipeline');
            const secVercel = document.getElementById('sectionVercelPipeline');

            if (mode === 'static') {
                btnStatic.classList.add('active');
                btnVercel.classList.remove('active');
                secStatic.classList.remove('d-none');
                secVercel.classList.add('d-none');
            } else {
                btnStatic.classList.remove('active');
                btnVercel.classList.add('active');
                secStatic.classList.add('d-none');
                secVercel.classList.remove('d-none');
            }
        }

        function handlePresetChange(preset) {
            const buildInput = document.getElementById('vercelBuildCommand');
            const outputInput = document.getElementById('vercelOutputDir');
            const installInput = document.getElementById('vercelInstallCommand');
            
            if (preset === 'Next.js') {
                buildInput.placeholder = 'next build';
                buildInput.value = 'next build';
                outputInput.placeholder = '(handled automatically by Next.js)';
                outputInput.value = '';
                installInput.placeholder = 'npm install';
            } else if (preset === 'Vite') {
                buildInput.placeholder = 'npm run build';
                buildInput.value = 'npm run build';
                outputInput.placeholder = 'dist';
                outputInput.value = 'dist';
                installInput.placeholder = 'npm install';
            } else if (preset === 'React') {
                buildInput.placeholder = 'npm run build';
                buildInput.value = 'npm run build';
                outputInput.placeholder = 'build';
                outputInput.value = 'build';
                installInput.placeholder = 'npm install';
            } else {
                buildInput.placeholder = 'npm run build';
                buildInput.value = '';
                outputInput.placeholder = 'dist';
                outputInput.value = '';
                installInput.placeholder = 'npm install';
            }
        }

        function handleModalPresetChange(preset) {
            const buildInput = document.getElementById('modalVercelBuildCmd');
            const outputInput = document.getElementById('modalVercelOutputDir');
            const installInput = document.getElementById('modalVercelInstallCmd');
            if (preset === 'Next.js') {
                buildInput.value = 'next build';
                outputInput.value = '';
                installInput.value = 'npm install';
            } else if (preset === 'Vite') {
                buildInput.value = 'npm run build';
                outputInput.value = 'dist';
                installInput.value = 'npm install';
            } else if (preset === 'React') {
                buildInput.value = 'npm run build';
                outputInput.value = 'build';
                installInput.value = 'npm install';
            }
        }

        function toggleBuildSettings() {
            const body = document.getElementById('buildSettingsBody');
            const icon = document.getElementById('buildChevronIcon');
            if (body.classList.contains('d-none')) {
                body.classList.remove('d-none');
                icon.style.transform = 'rotate(180deg)';
            } else {
                body.classList.add('d-none');
                icon.style.transform = 'rotate(0deg)';
            }
        }

        // Generic accordion toggle helper
        function toggleEl(bodyId, iconId) {
            const body = document.getElementById(bodyId);
            const icon = document.getElementById(iconId);
            if (!body) return;
            const hidden = body.classList.contains('d-none');
            body.classList.toggle('d-none', !hidden);
            if (icon) icon.style.transform = hidden ? 'rotate(180deg)' : 'rotate(0deg)';
        }

        // =====================================================================
        // GITHUB CONNECT — Firebase OAuth Login + Repo Browser + Vercel Deploy
        // =====================================================================
        let _ghRepos = [];
        let _ghSelectedRepo = null;

        // Auth state callbacks wired to Firebase module
        window.onGhUserReady = function(user) {
            document.getElementById('ghLoginPanel').classList.add('d-none');
            document.getElementById('ghLoggedInPanel').classList.remove('d-none');
            document.getElementById('ghUserName').textContent = user.displayName || user.email || 'GitHub User';
            document.getElementById('ghUserLogin').textContent = '@' + (user.reloadUserInfo?.screenName || user.email?.split('@')[0] || 'user');
            const avatar = user.photoURL;
            if (avatar) document.getElementById('ghUserAvatar').src = avatar;
            // Change badge to connected
            const badge = document.getElementById('ghConnectBadge');
            if (badge) { badge.textContent = 'CONNECTED'; badge.className = 'badge bg-success ms-1'; badge.style.fontSize = '0.6rem'; }
            loadUserRepos();
        };

        window.onGhUserSignedOut = function() {
            document.getElementById('ghLoginPanel').classList.remove('d-none');
            document.getElementById('ghLoggedInPanel').classList.add('d-none');
            document.getElementById('ghDeployPanel').classList.add('d-none');
            const badge = document.getElementById('ghConnectBadge');
            if (badge) { badge.textContent = 'NEW'; badge.className = 'badge bg-success ms-1'; badge.style.fontSize = '0.6rem'; }
        };

        // Check if already logged in on page load
        (function checkGhSession() {
            const savedToken = localStorage.getItem('elivora_gh_oauth_token');
            if (savedToken) window._ghOAuthToken = savedToken;
        })();

        async function loginWithGithub() {
            const btn = document.getElementById('ghLoginBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Redirecting to GitHub...';
            try {
                if (!window._signInWithRedirect || !window._ghProvider) {
                    throw new Error('Firebase not loaded yet. Please wait a moment and try again.');
                }
                // This redirects the entire page to GitHub login, then back to /cloud
                await window._signInWithRedirect(window._fbAuth, window._ghProvider);
            } catch (err) {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-github"></i> Login with GitHub';
                showToast(err.message || 'Login failed. Please try again.', 'danger');
            }
        }

        async function logoutGithub() {
            try {
                await window._signOut(window._fbAuth);
                localStorage.removeItem('elivora_gh_oauth_token');
                window._ghOAuthToken = null;
                _ghRepos = [];
                _ghSelectedRepo = null;
            } catch(e) { showToast('Logout failed: ' + e.message, 'danger'); }
        }

        async function loadUserRepos() {
            const token = window._ghOAuthToken;
            if (!token) { showToast('Not logged in to GitHub', 'warning'); return; }
            const list = document.getElementById('ghRepoList');
            const countEl = document.getElementById('ghRepoCount');
            list.innerHTML = '<div class="text-center text-muted py-5"><span class="spinner-border spinner-border-sm me-2"></span>Fetching repositories...</div>';
            try {
                let allRepos = [];
                let page = 1;
                while (true) {
                    const res = await fetch(`https://api.github.com/user/repos?per_page=100&page=${page}&sort=updated&affiliation=owner,collaborator`, {
                        headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github.v3+json' }
                    });
                    if (!res.ok) throw new Error(`GitHub API error: ${res.status}`);
                    const batch = await res.json();
                    if (!batch.length) break;
                    allRepos = allRepos.concat(batch);
                    page++;
                    if (batch.length < 100) break;
                }
                _ghRepos = allRepos;
                countEl.textContent = `${allRepos.length} repositories found`;
                renderGhRepos(allRepos);
            } catch(e) {
                list.innerHTML = `<div class="alert alert-danger m-0">${e.message}</div>`;
            }
        }

        function renderGhRepos(repos) {
            const list = document.getElementById('ghRepoList');
            if (!repos.length) { list.innerHTML = '<div class="text-center text-muted py-4">No repositories found.</div>'; return; }
            list.innerHTML = repos.map(r => `
                <div class="border rounded-3 p-3 bg-white d-flex align-items-center justify-content-between gap-3 repo-card-wrapper" style="cursor:pointer;border-color:var(--border-color)!important;" onclick="selectGhRepo(${JSON.stringify(JSON.stringify(r))})">
                    <div class="d-flex align-items-center gap-3 overflow-hidden">
                        <i class="bi bi-${r.private ? 'lock-fill text-warning' : 'book text-muted'} flex-shrink-0 fs-5"></i>
                        <div class="overflow-hidden">
                            <div class="fw-bold text-main text-truncate small">${escapeHtml(r.full_name)}</div>
                            <div class="text-muted text-truncate" style="font-size:0.75rem;">${escapeHtml(r.description || 'No description')}</div>
                        </div>
                    </div>
                    <div class="d-flex align-items-center gap-2 flex-shrink-0">
                        ${r.language ? `<span class="badge border text-main" style="font-size:0.65rem;background:var(--bg-main);">${escapeHtml(r.language)}</span>` : ''}
                        <span class="badge border text-muted" style="font-size:0.65rem;background:var(--bg-main);">${r.private ? 'Private' : 'Public'}</span>
                        <button class="btn btn-sm btn-dark px-3 py-1 fw-semibold flex-shrink-0" style="font-size:0.75rem;" onclick="event.stopPropagation();selectGhRepo(${JSON.stringify(JSON.stringify(r))})">Deploy</button>
                    </div>
                </div>`).join('');
        }

        function filterGhRepos() {
            const q = document.getElementById('ghRepoSearch').value.toLowerCase();
            renderGhRepos(_ghRepos.filter(r => r.full_name.toLowerCase().includes(q) || (r.description||'').toLowerCase().includes(q)));
        }

        async function selectGhRepo(repoJsonStr) {
            const repo = JSON.parse(repoJsonStr);
            _ghSelectedRepo = repo;
            document.getElementById('ghSelectedRepoName').textContent = repo.full_name;
            document.getElementById('ghProjectName').value = repo.name.toLowerCase().replace(/[^a-z0-9-]/g,'-').replace(/-+/g,'-').substring(0,50);
            document.getElementById('ghDeployPanel').classList.remove('d-none');
            document.getElementById('ghDeployPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });

            // Load branches
            const branchSel = document.getElementById('ghBranchSelect');
            branchSel.innerHTML = '<option>Loading branches...</option>';
            branchSel.disabled = true;
            try {
                const res = await fetch(`https://api.github.com/repos/${repo.full_name}/branches?per_page=100`, {
                    headers: { 'Authorization': 'Bearer ' + window._ghOAuthToken }
                });
                const branches = await res.json();
                const defaultBranch = repo.default_branch || 'main';
                branchSel.innerHTML = branches.map(b =>
                    `<option value="${escapeHtml(b.name)}" ${b.name===defaultBranch?'selected':''}>${escapeHtml(b.name)}</option>`
                ).join('');
                branchSel.disabled = false;
            } catch(e) {
                branchSel.innerHTML = `<option value="${repo.default_branch||'main'}">${repo.default_branch||'main'}</option>`;
                branchSel.disabled = false;
            }
        }

        function addGhEnvRow(key='', val='') {
            const container = document.getElementById('ghEnvRowsContainer');
            const row = document.createElement('div');
            row.className = 'd-flex gap-2 align-items-center';
            row.innerHTML = `
                <input type="text" class="form-control-custom gh-env-key" placeholder="KEY" value="${escapeHtml(key)}" style="flex:1;">
                <input type="text" class="form-control-custom gh-env-val" placeholder="VALUE" value="${escapeHtml(val)}" style="flex:2;">
                <button type="button" class="btn btn-sm text-danger border-0 p-1" onclick="this.closest('div').remove()"><i class="bi bi-x-lg"></i></button>`;
            container.appendChild(row);
        }

        function getGhEnvVars() {
            const rows = document.querySelectorAll('#ghEnvRowsContainer > div');
            const vars = [];
            rows.forEach(row => {
                const k = row.querySelector('.gh-env-key')?.value?.trim();
                const v = row.querySelector('.gh-env-val')?.value?.trim();
                if (k) vars.push({ key: k, value: v || '', type: 'plain', target: ['production', 'preview', 'development'] });
            });
            return vars;
        }

        function setGhDeployProgress(pct, status) {
            document.getElementById('ghDeployProgress').classList.remove('d-none');
            document.getElementById('ghDeployBar').style.width = pct + '%';
            document.getElementById('ghDeployPct').textContent = pct + '%';
            document.getElementById('ghDeployStatus').textContent = status;
        }

        async function triggerGithubDeploy() {
            if (!_ghSelectedRepo) { showToast('Please select a repository first.', 'warning'); return; }
            const vercelToken = CONFIG.VERCEL_TOKEN;
            if (!vercelToken) { showToast('Vercel token not configured. Go to API Config.', 'warning'); return; }

            const repo = _ghSelectedRepo;
            const branch = document.getElementById('ghBranchSelect').value;
            const projectName = document.getElementById('ghProjectName').value.trim().toLowerCase().replace(/[^a-z0-9-]/g,'-') || repo.name;
            const framework = document.getElementById('ghFramework').value || null;
            const buildCmd = document.getElementById('ghBuildCmd').value.trim() || null;
            const outputDir = document.getElementById('ghOutputDir').value.trim() || null;
            const installCmd = document.getElementById('ghInstallCmd').value.trim() || null;
            const envVars = getGhEnvVars();
            const autoRedeploy = document.getElementById('ghAutoRedeploy').checked;
            const ghToken = window._ghOAuthToken;

            const btn = document.getElementById('ghDeployBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deploying...';

            try {
                setGhDeployProgress(10, 'Creating Vercel project...');

                // Step 1: Create/update Vercel project linked to GitHub repo
                const projPayload = {
                    name: projectName,
                    gitRepository: { type: 'github', repo: repo.full_name },
                };
                if (framework) projPayload.framework = framework;
                if (buildCmd) projPayload.buildCommand = buildCmd;
                if (outputDir) projPayload.outputDirectory = outputDir;
                if (installCmd) projPayload.installCommand = installCmd;

                await fetch('/vercel_api/v11/projects', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${vercelToken}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify(projPayload)
                });

                setGhDeployProgress(30, 'Injecting environment variables...');

                // Step 2: Push env vars
                if (envVars.length > 0) {
                    await fetch(`/vercel_api/v10/projects/${projectName}/env`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${vercelToken}`, 'Content-Type': 'application/json' },
                        body: JSON.stringify(envVars)
                    }).catch(() => {});
                }

                setGhDeployProgress(55, 'Triggering GitHub-linked deployment...');

                // Step 3: Trigger deployment from GitHub source
                const deployPayload = {
                    name: projectName,
                    gitSource: {
                        type: 'github',
                        repoId: String(repo.id),
                        ref: branch
                    },
                    target: 'production'
                };
                if (framework || buildCmd || outputDir || installCmd) {
                    deployPayload.projectSettings = { framework, buildCommand: buildCmd, outputDirectory: outputDir, installCommand: installCmd };
                }

                const deployRes = await fetch('/vercel_api/v13/deployments?skipAutoDetectionConfirmation=1', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${vercelToken}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify(deployPayload)
                });

                if (!deployRes.ok) {
                    const err = await deployRes.json().catch(() => ({}));
                    throw new Error(err.error?.message || `Deploy failed (HTTP ${deployRes.status})`);
                }

                const dData = await deployRes.json();
                const deploymentId = dData.id || '';
                let rawUrl = dData.url || (dData.alias && dData.alias[0]) || `${projectName}.vercel.app`;
                const liveUrl = rawUrl.startsWith('http') ? rawUrl : `https://${rawUrl}`;

                setGhDeployProgress(75, 'Build started on Vercel. Polling status...');

                // Step 4: Setup webhook for auto-redeploy
                if (autoRedeploy && ghToken) {
                    setGhDeployProgress(80, 'Setting up auto-redeploy webhook...');
                    await setupGhWebhook(repo.full_name, branch, projectName, ghToken, vercelToken);
                }

                // Step 5: Poll build status
                setGhDeployProgress(85, 'Waiting for build to complete...');
                await pollGhDeployStatus(deploymentId, projectName, liveUrl, vercelToken);

            } catch(e) {
                showToast('Deploy failed: ' + e.message, 'danger');
                setGhDeployProgress(0, 'Deploy failed: ' + e.message);
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-rocket-takeoff-fill me-1"></i> Deploy from GitHub';
            }
        }

        async function pollGhDeployStatus(deploymentId, projectName, liveUrl, vercelToken) {
            const maxAttempts = 60;
            let attempts = 0;
            const pollInterval = setInterval(async () => {
                attempts++;
                try {
                    const res = await fetch(`/vercel_api/v13/deployments/${deploymentId}`, {
                        headers: { 'Authorization': `Bearer ${vercelToken}` }
                    });
                    if (!res.ok) return;
                    const data = await res.json();
                    const state = data.readyState;

                    if (state === 'READY') {
                        clearInterval(pollInterval);
                        let finalDomain = data.url || (data.alias && data.alias[0]) || `${projectName}.vercel.app`;
                        if (!finalDomain.startsWith('http')) finalDomain = 'https://' + finalDomain;
                        setGhDeployProgress(100, 'Deployed successfully!');

                        // Save to project list
                        const proj = { id: projectName, name: projectName, url: finalDomain, status: 'live', pipeline: 'github', source: _ghSelectedRepo?.full_name || '', createdAt: new Date().toISOString() };
                        saveVercelDeploymentRecord(proj);
                        renderProjects();

                        const btn = document.getElementById('ghDeployBtn');
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-check-circle-fill me-1"></i> Deployed!';
                        showToast(`🚀 Live at: ${finalDomain}`, 'success');
                        setTimeout(() => {
                            btn.innerHTML = '<i class="bi bi-rocket-takeoff-fill me-1"></i> Deploy from GitHub';
                        }, 5000);

                    } else if (state === 'ERROR' || state === 'CANCELED') {
                        clearInterval(pollInterval);
                        const btn = document.getElementById('ghDeployBtn');
                        btn.disabled = false;
                        btn.innerHTML = '<i class="bi bi-rocket-takeoff-fill me-1"></i> Deploy from GitHub';
                        showToast('Build failed on Vercel. Check Vercel dashboard for logs.', 'danger');
                        setGhDeployProgress(0, 'Build failed.');
                    } else {
                        const pct = Math.min(85 + attempts * 0.5, 98);
                        setGhDeployProgress(Math.round(pct), `Building... (${state})`);
                    }
                } catch(e) {}
                if (attempts >= maxAttempts) {
                    clearInterval(pollInterval);
                    setGhDeployProgress(100, 'Deployment submitted (timed out polling - check Vercel dashboard).');
                    const btn = document.getElementById('ghDeployBtn');
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-rocket-takeoff-fill me-1"></i> Deploy from GitHub';
                }
            }, 5000);
        }

        async function setupGhWebhook(fullRepoName, branch, projectName, ghToken, vercelToken) {
            // Create a GitHub webhook that calls our local server's /gh_webhook endpoint
            // Note: For auto-redeploy, we use Vercel's native GitHub integration instead
            // by ensuring the project is linked - Vercel handles pushes automatically when linked
            try {
                // Attempt to link GitHub repo to Vercel project via Vercel API
                await fetch(`/vercel_api/v9/projects/${projectName}/link`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${vercelToken}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: 'github', repo: fullRepoName })
                });
            } catch(e) {}
        }

        // --- Dynamic Environment Variables & .env Importer ---
        function addEnvVariableRow(key = '', val = '', containerId = 'envRowsContainer') {
            const container = document.getElementById(containerId);
            if (!container) return;
            const row = document.createElement('div');
            row.className = 'd-flex gap-2 align-items-center env-row';
            row.innerHTML = `
                <input type="text" class="form-control-custom env-key" placeholder="VARIABLE_KEY" value="${escapeHtml(key)}" style="flex: 1; font-family: monospace;">
                <input type="text" class="form-control-custom env-value" placeholder="value" value="${escapeHtml(val)}" style="flex: 1; font-family: monospace;">
                <button type="button" class="btn btn-sm border bg-transparent text-danger px-3 py-2" style="border-color: var(--border-color) !important;" onclick="this.closest('.env-row').remove()" title="Remove variable">
                    <i class="bi bi-trash3"></i>
                </button>
            `;
            container.appendChild(row);
        }

        function getEnvVariablesFromContainer(containerId = 'envRowsContainer') {
            const rows = document.querySelectorAll(`#${containerId} .env-row`);
            const list = [];
            rows.forEach(r => {
                const k = r.querySelector('.env-key')?.value.trim();
                const v = r.querySelector('.env-value')?.value.trim();
                if (k) {
                    list.push({
                        key: k,
                        value: v || '',
                        type: 'plain',
                        target: ['production', 'preview', 'development']
                    });
                }
            });
            return list;
        }

        function parseAndPopulateEnvLines(rawText, containerId = 'envRowsContainer') {
            const lines = rawText.split(/\r?\n/);
            let importedCount = 0;
            lines.forEach(line => {
                let trimmed = line.trim();
                if (!trimmed || trimmed.startsWith('#')) return;
                if (trimmed.startsWith('export ')) trimmed = trimmed.substring(7).trim();
                const eqIdx = trimmed.indexOf('=');
                if (eqIdx === -1) return;

                const key = trimmed.substring(0, eqIdx).trim();
                let val = trimmed.substring(eqIdx + 1).trim();

                // Strip surrounding quotes
                if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
                    val = val.substring(1, val.length - 1);
                }

                if (key) {
                    addEnvVariableRow(key, val, containerId);
                    importedCount++;
                }
            });

            if (importedCount > 0) {
                showToast(`Successfully imported ${importedCount} keys from .env!`, 'success');
            } else {
                showToast('No valid KEY=VALUE pairs found in .env text', 'warning');
            }
        }

        function handleEnvFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                parseAndPopulateEnvLines(e.target.result, 'envRowsContainer');
                event.target.value = '';
            };
            reader.readAsText(file);
        }

        function triggerModalEnvFileImport() {
            document.getElementById('modalEnvFileInput').click();
        }

        function handleModalEnvFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                parseAndPopulateEnvLines(e.target.result, 'modalEnvRowsContainer');
                event.target.value = '';
            };
            reader.readAsText(file);
        }

        function openPasteEnvModal() {
            document.getElementById('pasteEnvTextarea').value = '';
            document.getElementById('pasteEnvOverlay').classList.add('active');
        }

        function applyPastedEnv() {
            const raw = document.getElementById('pasteEnvTextarea').value;
            closeModals();
            if (raw.trim()) {
                parseAndPopulateEnvLines(raw, 'envRowsContainer');
            }
        }

        // --- Real Time Remaining Calculation Helpers ---
        function calculateRealUploadTimeRemaining(doneIndex, totalCount) {
            if (doneIndex <= 1) return "Estimating...";
            const elapsed = (performance.now() - uploadStartTime) / 1000;
            const rate = doneIndex / Math.max(elapsed, 0.05); // files per second
            const remainingCount = totalCount - doneIndex;
            const secondsLeft = Math.max(1, Math.round(remainingCount / rate));

            if (secondsLeft >= 60) {
                const mins = Math.floor(secondsLeft / 60);
                const secs = secondsLeft % 60;
                return `~${mins}m ${secs}s left (${rate.toFixed(1)} files/s)`;
            }
            return `~${secondsLeft}s left (${rate.toFixed(1)} files/s)`;
        }

        // --- Global Floating Progress Management ---
        
        function handleApiConfigEnvFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                populateApiConfigFromEnvText(e.target.result);
                event.target.value = '';
            };
            reader.readAsText(file);
        }

        function syncTokensFromLocalEnv() {
            fetch('/api/load_env')
                .then(r => r.json())
                .then(data => {
                    if (data && !data.error) {
                        let updated = 0;
                        if (data.GITHUB_DEFAULT_TOKEN || data.GITHUB_TOKEN || data.GH_TOKEN) {
                            const t = data.GITHUB_DEFAULT_TOKEN || data.GITHUB_TOKEN || data.GH_TOKEN;
                            document.getElementById('cfgToken').value = t;
                            CONFIG.TOKEN = t;
                            localStorage.setItem('elivora_gh_token', t);
                            updated++;
                        }
                        if (data.VERCEL_DEFAULT_TOKEN || data.VERCEL_TOKEN) {
                            const vt = data.VERCEL_DEFAULT_TOKEN || data.VERCEL_TOKEN;
                            document.getElementById('cfgVercelToken').value = vt;
                            CONFIG.VERCEL_TOKEN = vt;
                            localStorage.setItem('elivora_vercel_token', vt);
                            updated++;
                        }
                        if (data.GITHUB_USERNAME || data.GH_USER) {
                            const u = data.GITHUB_USERNAME || data.GH_USER;
                            document.getElementById('cfgUsername').value = u;
                            CONFIG.USERNAME = u;
                            localStorage.setItem('elivora_gh_user', u);
                            updated++;
                        }
                        if (updated > 0) {
                            showToast(`Successfully synced ${updated} credentials from .env!`, 'success');
                        } else {
                            showToast('No GitHub or Vercel tokens found in workspace .env', 'warning');
                        }
                    } else {
                        showToast('Unable to read workspace .env. Use "Import .env" button.', 'warning');
                    }
                })
                .catch(() => {
                    showToast('Unable to reach /api/load_env. Use "Import .env" button to select your file.', 'warning');
                });
        }

        function populateApiConfigFromEnvText(raw) {
            const lines = raw.split(/\r?\n/);
            let updated = 0;
            lines.forEach(l => {
                let trimmed = l.trim();
                if (!trimmed || trimmed.startsWith('#')) return;
                if (trimmed.startsWith('export ')) trimmed = trimmed.substring(7).trim();
                const eqIdx = trimmed.indexOf('=');
                if (eqIdx === -1) return;
                const k = trimmed.substring(0, eqIdx).trim();
                let v = trimmed.substring(eqIdx + 1).trim();
                if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
                    v = v.substring(1, v.length - 1);
                }
                if (['GITHUB_DEFAULT_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN', 'PAT'].includes(k)) {
                    document.getElementById('cfgToken').value = v;
                    CONFIG.TOKEN = v;
                    localStorage.setItem('elivora_gh_token', v);
                    updated++;
                }
                if (['VERCEL_DEFAULT_TOKEN', 'VERCEL_TOKEN'].includes(k)) {
                    document.getElementById('cfgVercelToken').value = v;
                    CONFIG.VERCEL_TOKEN = v;
                    localStorage.setItem('elivora_vercel_token', v);
                    updated++;
                }
                if (['GITHUB_USERNAME', 'GH_USER', 'USERNAME'].includes(k) && !k.startsWith('VERCEL')) {
                    document.getElementById('cfgUsername').value = v;
                    CONFIG.USERNAME = v;
                    localStorage.setItem('elivora_gh_user', v);
                    updated++;
                }
            });
            if (updated > 0) {
                showToast(`Imported ${updated} credentials from .env!`, 'success');
            } else {
                showToast('No GITHUB_DEFAULT_TOKEN or VERCEL_DEFAULT_TOKEN found in file.', 'warning');
            }
        }

        function syncEnvFromLocalEnv(containerId = 'envRowsContainer') {
            fetch('/api/load_env')
                .then(r => r.json())
                .then(data => {
                    if (data && !data.error) {
                        let count = 0;
                        for (const [k, v] of Object.entries(data)) {
                            if (k && v !== undefined && !['GITHUB_DEFAULT_TOKEN', 'VERCEL_DEFAULT_TOKEN'].includes(k)) {
                                addEnvVariableRow(k, v, containerId);
                                count++;
                            }
                        }
                        if (count > 0) {
                            showToast(`Imported ${count} keys from workspace .env!`, 'success');
                        } else {
                            showToast('Workspace .env has no additional variables.', 'warning');
                        }
                    } else {
                        showToast('Unable to auto-read workspace .env. Use "Import .env" file button.', 'warning');
                    }
                })
                .catch(() => {
                    showToast('Unable to fetch workspace .env. Use "Import .env" file button.', 'warning');
                });
        }

        function checkActiveFloatingProgress() {
            try {
                const raw = localStorage.getItem('elivora_active_pipeline');
                if (!raw) return;
                const data = JSON.parse(raw);
                if (data && data.active) {
                    setGlobalFloatingProgress({
                        visible: true,
                        name: data.name,
                        badge: data.badge,
                        pct: data.pct,
                        status: data.status,
                        time: data.time,
                        deploymentId: data.deploymentId
                    });
                    if (data.deploymentId && !window.isPollingVercel) {
                        window.isPollingVercel = true;
                        pollVercelBuildStatus(data.deploymentId, data.name);
                    }
                }
            } catch(e) {}
        }

        function setGlobalFloatingProgress(opts) {
            const floatWidget = document.getElementById('globalFloatingProgress');
            if (!opts.visible) {
                if (floatWidget) floatWidget.classList.add('d-none');
                if (!opts.done && !opts.failed) {
                    localStorage.removeItem('elivora_active_pipeline');
                }
                return;
            }
            if (floatWidget) floatWidget.classList.remove('d-none');

            if (opts.name) document.getElementById('floatProjectName').innerText = opts.name;
            if (opts.badge) document.getElementById('floatBadge').innerText = opts.badge;
            if (opts.pct !== undefined) {
                document.getElementById('floatPercent').innerText = `${opts.pct}%`;
                document.getElementById('floatProgressBar').style.width = `${opts.pct}%`;
            }
            if (opts.status) document.getElementById('floatStatusText').innerText = opts.status;
            if (opts.time) document.getElementById('floatTimeRemaining').innerText = opts.time;

            // Persist active state in localStorage so Hub and AI System can hover-track progress
            try {
                const pipelineData = {
                    active: !opts.done && !opts.failed,
                    done: !!opts.done,
                    failed: !!opts.failed,
                    name: opts.name || document.getElementById('floatProjectName').innerText,
                    badge: opts.badge || document.getElementById('floatBadge').innerText,
                    pct: opts.pct !== undefined ? opts.pct : 0,
                    status: opts.status || '',
                    time: opts.time || '',
                    deploymentId: opts.deploymentId || (window.currentVercelDeploymentId || null),
                    token: CONFIG.VERCEL_TOKEN || ''
                };
                localStorage.setItem('elivora_active_pipeline', JSON.stringify(pipelineData));
            } catch(e) {}
            
            const spinner = document.getElementById('floatSpinner');
            if (spinner) {
                if (opts.done) {
                    spinner.className = 'bi bi-check-circle-fill text-success flex-shrink-0';
                    spinner.style.display = 'inline-block';
                } else if (opts.failed) {
                    spinner.className = 'bi bi-exclamation-triangle-fill text-danger flex-shrink-0';
                    spinner.style.display = 'inline-block';
                } else {
                    spinner.className = 'spinner-border spinner-border-sm text-primary flex-shrink-0';
                    spinner.style.display = 'inline-block';
                }
            }
        }

        // --- File Upload Helpers ---
        function formatBytes(bytes) {
            if (!bytes || bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        function setupDragDropZone(zoneId, inputId, onFileSelected) {
            const zone = document.getElementById(zoneId);
            const input = document.getElementById(inputId);

            ['dragenter', 'dragover'].forEach(name => {
                zone.addEventListener(name, (e) => {
                    e.preventDefault(); e.stopPropagation();
                    zone.classList.add('dragover');
                }, false);
            });

            ['dragleave', 'drop'].forEach(name => {
                zone.addEventListener(name, (e) => {
                    e.preventDefault(); e.stopPropagation();
                    zone.classList.remove('dragover');
                }, false);
            });

            zone.addEventListener('drop', (e) => {
                const files = e.dataTransfer.files;
                if (files && files.length > 0) onFileSelected(files[0]);
            });

            input.addEventListener('change', (e) => {
                if (e.target.files && e.target.files.length > 0) onFileSelected(e.target.files[0]);
            });
        }

        function onStaticFileChosen(file) {
            if (!file.name.toLowerCase().endsWith('.zip')) {
                return showToast('Please upload a valid .zip codebase file', 'error');
            }
            staticSelectedFile = file;
            document.getElementById('staticFileNameDisplay').innerText = file.name;
            document.getElementById('staticFileSizeDisplay').innerText = formatBytes(file.size);
            document.getElementById('staticDropZone').classList.add('d-none');
            document.getElementById('staticFileCard').classList.remove('d-none');
            
            const nameInput = document.getElementById('staticProjectName');
            if (!nameInput.value.trim()) {
                const baseName = file.name.replace(/\.zip$/i, '').toLowerCase().replace(/[^a-z0-9-]/g, '-');
                nameInput.value = baseName;
            }
        }

        function clearStaticFile() {
            staticSelectedFile = null;
            document.getElementById('staticFileInput').value = '';
            document.getElementById('staticFileCard').classList.add('d-none');
            document.getElementById('staticDropZone').classList.remove('d-none');
        }

        function onVercelFileChosen(file) {
            if (!file.name.toLowerCase().endsWith('.zip')) {
                return showToast('Please upload a valid .zip codebase file', 'error');
            }
            vercelSelectedFile = file;
            document.getElementById('vercelFileNameDisplay').innerText = file.name;
            document.getElementById('vercelFileSizeDisplay').innerText = formatBytes(file.size);
            document.getElementById('vercelDropZone').classList.add('d-none');
            document.getElementById('vercelFileCard').classList.remove('d-none');

            const nameInput = document.getElementById('vercelProjectName');
            if (!nameInput.value.trim()) {
                const baseName = file.name.replace(/\.zip$/i, '').toLowerCase().replace(/[^a-z0-9-]/g, '-');
                nameInput.value = baseName;
            }
        }

        function clearVercelFile() {
            vercelSelectedFile = null;
            document.getElementById('vercelFileInput').value = '';
            document.getElementById('vercelFileCard').classList.add('d-none');
            document.getElementById('vercelDropZone').classList.remove('d-none');
        }

        // --- Persistent Vercel Projects Helper ---
        function getSavedVercelDeployments() {
            try {
                return JSON.parse(localStorage.getItem('elivora_vercel_projects') || '[]');
            } catch(e) {
                return [];
            }
        }

        function saveVercelDeploymentRecord(rec) {
            const list = getSavedVercelDeployments();
            const idx = list.findIndex(x => x.id === rec.id);
            if (idx >= 0) list[idx] = { ...list[idx], ...rec };
            else list.unshift(rec);
            localStorage.setItem('elivora_vercel_projects', JSON.stringify(list));
        }

        // --- GitHub API Helper ---
        async function ghFetch(endpoint, options = {}) {
            const url = endpoint.startsWith('http') ? endpoint : `https://api.github.com${endpoint}`;
            const headers = { 
                'Authorization': `token ${CONFIG.TOKEN}`, 
                'Accept': 'application/vnd.github.v3+json', 
                'Content-Type': 'application/json', 
                ...options.headers 
            };
            const response = await fetch(url, { ...options, headers });
            if (!response.ok) { 
                const err = await response.json().catch(() => ({})); 
                throw new Error(err.message || `GitHub API Error: ${response.status}`); 
            }
            return response.status !== 204 ? await response.json().catch(() => ({})) : null;
        }

        // --- Settings Storage ---
        function saveConfig() {
            CONFIG.USERNAME = document.getElementById('cfgUsername').value.trim(); 
            CONFIG.TOKEN = document.getElementById('cfgToken').value.trim();
            CONFIG.VERCEL_TOKEN = document.getElementById('cfgVercelToken').value.trim();

            localStorage.setItem('elivora_gh_user', CONFIG.USERNAME); 
            localStorage.setItem('elivora_gh_token', CONFIG.TOKEN);
            localStorage.setItem('elivora_vercel_token', CONFIG.VERCEL_TOKEN);

            showToast("Configuration saved successfully.", "success"); 
            setTimeout(() => location.reload(), 600);
        }

        // --- Deploy Pipeline 1: Static (GitHub Pages) ---
        async function triggerStaticDeploy() {
            if (!CONFIG.TOKEN) {
                showToast("Please configure your GitHub Personal Access Token in Settings first.", "error");
                return switchView('settings', document.querySelectorAll('.nav-link-custom')[3]);
            }

            const file = staticSelectedFile;
            if (!file) return showToast("Please select or drop a .zip file", "warning");

            let repoName = document.getElementById('staticProjectName').value.trim() || `project-${Date.now()}`;
            repoName = repoName.toLowerCase().replace(/[^a-z0-9-]/g, '-').replace(/^-+|-+$/g, '');

            const progCont = document.getElementById('staticProgressContainer');
            const progBar = document.getElementById('staticProgressBar');
            const pText = document.getElementById('staticProgressText');
            const sText = document.getElementById('staticStatusText');
            const tText = document.getElementById('staticTimeRemaining');
            const deployBtn = document.getElementById('staticDeployBtn');

            progCont.classList.remove('d-none');
            progCont.scrollIntoView({ behavior: 'smooth', block: 'center' });
            deployBtn.disabled = true;

            uploadStartTime = performance.now();
            isPipelineActive = true;

            const updateStaticProgress = (pct, status, timeStr) => {
                progBar.style.width = `${pct}%`;
                pText.innerText = `${pct}%`;
                sText.innerText = status;
                tText.innerText = timeStr || "Calculating...";

                // Sync with persistent floating widget
                setGlobalFloatingProgress({
                    visible: true,
                    name: repoName,
                    badge: 'ELIVORA',
                    pct: pct,
                    status: status,
                    time: timeStr || "Calculating..."
                });
            };

            try {
                if (!CONFIG.USERNAME) {
                    updateStaticProgress(5, "Resolving GitHub account...", "Starting...");
                    const uData = await ghFetch('/user');
                    CONFIG.USERNAME = uData.login;
                    localStorage.setItem('elivora_gh_user', CONFIG.USERNAME);
                }

                updateStaticProgress(12, `Creating GitHub repository '${repoName}'...`, "Connecting...");
                await ghFetch('/user/repos', { 
                    method: 'POST', 
                    body: JSON.stringify({ name: repoName, auto_init: true, private: false, description: "Deployed via Elivora Cloud (Static)" }) 
                }).catch(async () => {
                    await ghFetch(`/repos/${CONFIG.USERNAME}/${repoName}`);
                });

                updateStaticProgress(25, "Extracting files from archive...", "Decompressing...");
                const zip = new JSZip(); 
                const loadedZip = await zip.loadAsync(file);
                const filesToUpload = Object.keys(loadedZip.files).filter(k => !loadedZip.files[k].dir && !k.startsWith('__MACOSX') && !k.includes('.DS_Store'));
                
                if (filesToUpload.length === 0) throw new Error("Zip archive contains no valid files.");

                let commonPrefix = "";
                const firstParts = filesToUpload[0].split('/');
                if (firstParts.length > 1) {
                    const candidatePrefix = firstParts[0] + '/';
                    if (filesToUpload.every(f => f.startsWith(candidatePrefix))) {
                        commonPrefix = candidatePrefix;
                    }
                }
                
                uploadStartTime = performance.now();
                for (let i = 0; i < filesToUpload.length; i++) {
                    const rawPath = filesToUpload[i];
                    let uploadPath = commonPrefix && rawPath.startsWith(commonPrefix) ? rawPath.substring(commonPrefix.length) : rawPath;
                    if (!uploadPath) continue;

                    const base64Data = await loadedZip.files[rawPath].async("base64");
                    
                    let sha = null;
                    try {
                        const fileInfo = await ghFetch(`/repos/${CONFIG.USERNAME}/${repoName}/contents/${uploadPath}`);
                        if (fileInfo && fileInfo.sha) sha = fileInfo.sha;
                    } catch(e) {}

                    const putPayload = { message: `Deploy ${uploadPath} via Elivora Cloud`, content: base64Data };
                    if (sha) putPayload.sha = sha;

                    try { 
                        await ghFetch(`/repos/${CONFIG.USERNAME}/${repoName}/contents/${uploadPath}`, { 
                            method: 'PUT', 
                            body: JSON.stringify(putPayload) 
                        }); 
                    } catch(e) {}
                    
                    const progress = 25 + Math.floor((i / filesToUpload.length) * 65);
                    const realTime = calculateRealUploadTimeRemaining(i + 1, filesToUpload.length);
                    updateStaticProgress(progress, `Pushing (${i+1}/${filesToUpload.length}): ${uploadPath}`, realTime);
                }

                updateStaticProgress(92, "Configuring GitHub Pages...", "Activating Pages...");
                try { 
                    await ghFetch(`/repos/${CONFIG.USERNAME}/${repoName}/pages`, { 
                        method: 'POST', 
                        body: JSON.stringify({ source: { branch: "main", path: "/" } }), 
                        headers: { 'Accept': 'application/vnd.github.switcheroo-preview+json' } 
                    }); 
                } catch(e) {}

                updateStaticProgress(100, "Deployment Complete!", "Live Ready"); 
                showToast("Static site successfully deployed to GitHub Pages!", "success");

                setGlobalFloatingProgress({
                    visible: true,
                    name: repoName,
                    badge: 'ELIVORA',
                    pct: 100,
                    status: "Live & Ready!",
                    time: "Completed",
                    done: true
                });
                setTimeout(() => setGlobalFloatingProgress({ visible: false }), 4000);

                clearStaticFile();
                document.getElementById('staticProjectName').value = '';
                
                activeDeployments.add(repoName);
                const newP = { 
                    id: repoName, 
                    url: `https://${CONFIG.USERNAME}.github.io/${repoName}/`, 
                    github: `https://github.com/${CONFIG.USERNAME}/${repoName}`, 
                    date: new Date().toISOString(), 
                    status: 'live',
                    platform: 'github'
                };
                projects.unshift(newP);
                renderProjects();
                renderAnalytics();

                switchView('dashboard', document.querySelectorAll('.nav-link-custom')[0]); 

            } catch (err) { 
                console.error(err);
                showToast(err.message || "Failed to deploy static project", 'error'); 
                setGlobalFloatingProgress({ visible: false });
            } finally {
                deployBtn.disabled = false;
                isPipelineActive = false;
                setTimeout(() => {
                    progCont.classList.add('d-none');
                    progBar.style.width = '0%';
                }, 3000);
            }
        }

        // =====================================================================
        // HELPER: Push environment variables to Vercel project via correct API
        // =====================================================================
        async function pushEnvVarsToVercel(projectId, envVars, vercelToken) {
            if (!envVars || envVars.length === 0) return;
            try {
                // First fetch existing env vars so we can delete them before re-adding
                const existingRes = await fetch(`/vercel_api/v10/projects/${projectId}/env`, {
                    headers: { 'Authorization': `Bearer ${vercelToken}` }
                });
                if (existingRes.ok) {
                    const existingData = await existingRes.json();
                    const existingEnvs = existingData.envs || [];
                    // Delete existing vars that match our keys to avoid duplicates
                    const keysToUpdate = new Set(envVars.map(e => e.key));
                    for (const env of existingEnvs) {
                        if (keysToUpdate.has(env.key)) {
                            await fetch(`/vercel_api/v10/projects/${projectId}/env/${env.id}`, {
                                method: 'DELETE',
                                headers: { 'Authorization': `Bearer ${vercelToken}` }
                            }).catch(() => {});
                        }
                    }
                }
                // Now add all env vars fresh
                for (const ev of envVars) {
                    await fetch(`/vercel_api/v10/projects/${projectId}/env`, {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${vercelToken}`,
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            key: ev.key,
                            value: ev.value,
                            type: 'plain',
                            target: ['production', 'preview', 'development']
                        })
                    }).catch(() => {});
                }
            } catch(e) {
                console.warn('[Elivora] pushEnvVarsToVercel warning:', e);
            }
        }

        // =====================================================================
        // HELPER: Compute SHA1 hex string for Vercel file upload (Web Crypto API)
        // =====================================================================
        async function sha1Hex(uint8Array) {
            const hashBuffer = await crypto.subtle.digest('SHA-1', uint8Array);
            return Array.from(new Uint8Array(hashBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
        }

        // =====================================================================
        // HELPER: Fetch with retry logic for robust API calls
        // =====================================================================
        async function fetchWithRetry(url, options = {}, retries = 3) {
            for (let i = 0; i < retries; i++) {
                try {
                    const res = await fetch(url, options);
                    if (!res.ok && res.status >= 500) {
                        if (i === retries - 1) return res;
                        await new Promise(r => setTimeout(r, 1000 * (i + 1))); // exponential backoff
                        continue;
                    }
                    return res;
                } catch (err) {
                    if (i === retries - 1) throw err;
                    await new Promise(r => setTimeout(r, 1000 * (i + 1)));
                }
            }
        }

        // --- Deploy Pipeline 2: Node.js / Dynamic App (Vercel — Direct File Upload) ---
        // --- Error Banner Helpers ---
        function showPipelineError(title, message) {
            const banner = document.getElementById('pipelineErrorBanner');
            const titleEl = document.getElementById('pipelineErrorTitle');
            const msgEl = document.getElementById('pipelineErrorMessage');
            if (banner && titleEl && msgEl) {
                titleEl.innerText = title || "Deployment Pipeline Failed";
                msgEl.innerText = message || "An unexpected error occurred during the process.";
                banner.classList.remove('d-none');
                banner.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            showToast(message, 'error');
        }

        function dismissPipelineError() {
            const banner = document.getElementById('pipelineErrorBanner');
            if (banner) banner.classList.add('d-none');
        }

        // --- Deploy Pipeline 2: Node.js / Dynamic App (GitHub Push + Vercel Deployment) ---
        async function triggerVercelDeploy() {
            dismissPipelineError();

            const vercelToken = (CONFIG.VERCEL_TOKEN || "").trim();
            const ghToken = (CONFIG.TOKEN || "").trim();

            if (!vercelToken) {
                showPipelineError("Authentication Missing", "Vercel Access Token is required. Please set it in Settings.");
                return switchView('settings', document.querySelectorAll('.nav-link-custom')[3]);
            }
            if (!ghToken) {
                showPipelineError("Authentication Missing", "GitHub Personal Access Token is required to push source code. Please configure it in Settings.");
                return switchView('settings', document.querySelectorAll('.nav-link-custom')[3]);
            }

            const rawName = document.getElementById('vercelProjectName').value.trim();
            if (!rawName) return showToast("Please enter a Project Name", "warning");

            const cleanProjectName = rawName.toLowerCase().replace(/[^a-z0-9-]/g, '-').replace(/^-+|-+$/g, '');
            if (!cleanProjectName) return showToast("Invalid Project Name. Use alphanumeric characters.", "warning");

            const zipFile = vercelSelectedFile;
            if (!zipFile) return showToast("Please drag & drop or select a .zip codebase file", "warning");

            const progCont = document.getElementById('vercelProgressContainer');
            const progBar = document.getElementById('vercelProgressBar');
            const pText = document.getElementById('vercelProgressText');
            const sText = document.getElementById('vercelStatusText');
            const tText = document.getElementById('vercelTimeRemaining');
            const deployBtn = document.getElementById('vercelDeployBtn');

            progCont.classList.remove('d-none');
            progCont.scrollIntoView({ behavior: 'smooth', block: 'center' });
            deployBtn.disabled = true;

            uploadStartTime = performance.now();
            isPipelineActive = true;

            const updateVercelProgress = (pct, status, timeStr) => {
                progBar.style.width = `${pct}%`;
                pText.innerText = `${pct}%`;
                sText.innerText = status;
                tText.innerText = timeStr || "Calculating...";
                setGlobalFloatingProgress({
                    visible: true,
                    name: cleanProjectName,
                    badge: 'NODE/VERCEL',
                    pct: pct,
                    status: status,
                    time: timeStr || "Calculating..."
                });
            };

            try {
                const preset = document.getElementById('vercelPreset').value;
                const frameworkMap = { "Next.js": "nextjs", "Vite": "vite", "React": "create-react-app", "Other": null };
                const frameworkValue = frameworkMap[preset] || null;
                const rootDir = document.getElementById('vercelRootDir').value.trim();
                const buildCmd = document.getElementById('vercelBuildCommand').value.trim();
                const outputDir = document.getElementById('vercelOutputDir').value.trim();
                const installCmd = document.getElementById('vercelInstallCommand').value.trim();
                const envVars = getEnvVariablesFromContainer('envRowsContainer');

                // 1. Resolve GitHub Identity
                updateVercelProgress(5, "Verifying GitHub & Vercel credentials...", "Connecting...");
                if (!CONFIG.USERNAME) {
                    const ghUserData = await ghFetch('/user');
                    CONFIG.USERNAME = ghUserData.login;
                    localStorage.setItem('elivora_gh_user', CONFIG.USERNAME);
                }

                // 2. Extract and Filter Zip Contents
                updateVercelProgress(10, "Extracting and filtering package files...", "Decompressing...");
                const zip = new JSZip();
                const loadedZip = await zip.loadAsync(zipFile);
                
                // Exclude node_modules, .git, and platform artifacts
                const rawPaths = Object.keys(loadedZip.files).filter(k => {
                    const norm = k.replace(/\\/g, '/');
                    return !loadedZip.files[k].dir && 
                           !norm.startsWith('__MACOSX') && 
                           !norm.includes('.DS_Store') &&
                           !norm.includes('node_modules/') &&
                           !norm.startsWith('node_modules/') &&
                           !norm.includes('.git/') &&
                           !norm.startsWith('.git/') &&
                           !norm.includes('.next/') &&
                           !norm.includes('dist/');
                });

                if (rawPaths.length === 0) {
                    throw new Error("No deployable files found in ZIP archive (ignoring node_modules). Make sure your project files are at the root or within a top-level directory.");
                }

                // Identify common root folder if files are nested
                let commonPrefix = "";
                const firstParts = rawPaths[0].replace(/\\/g, '/').split('/');
                if (firstParts.length > 1) {
                    const candidate = firstParts[0] + '/';
                    if (rawPaths.every(f => f.replace(/\\/g, '/').startsWith(candidate))) {
                        commonPrefix = candidate;
                    }
                }

                // 3. Create or Link GitHub Repository
                updateVercelProgress(18, `Creating GitHub repository '${cleanProjectName}'...`, "Syncing GitHub...");
                try {
                    await ghFetch('/user/repos', {
                        method: 'POST',
                        body: JSON.stringify({
                            name: cleanProjectName,
                            private: false,
                            auto_init: true,
                            description: "Deployed via Elivora Cloud Node.js Pipeline"
                        })
                    });
                } catch(e) {
                    // Check if repository already exists
                    await ghFetch(`/repos/${CONFIG.USERNAME}/${cleanProjectName}`);
                }

                // 4. Push Codebase to GitHub
                uploadStartTime = performance.now();
                for (let i = 0; i < rawPaths.length; i++) {
                    const rawPath = rawPaths[i];
                    let normPath = rawPath.replace(/\\/g, '/');
                    let cleanPath = commonPrefix && normPath.startsWith(commonPrefix) ? normPath.substring(commonPrefix.length) : normPath;
                    cleanPath = cleanPath.replace(/^\/+/, '');
                    if (!cleanPath) continue;

                    const base64Data = await loadedZip.files[rawPath].async("base64");
                    let sha = null;
                    try {
                        const fileInfo = await ghFetch(`/repos/${CONFIG.USERNAME}/${cleanProjectName}/contents/${cleanPath}`);
                        if (fileInfo && fileInfo.sha) sha = fileInfo.sha;
                    } catch(e) {}

                    const putPayload = { message: `Deploy ${cleanPath} via Elivora Cloud`, content: base64Data };
                    if (sha) putPayload.sha = sha;

                    await ghFetch(`/repos/${CONFIG.USERNAME}/${cleanProjectName}/contents/${cleanPath}`, {
                        method: 'PUT',
                        body: JSON.stringify(putPayload)
                    });

                    const pct = 20 + Math.floor((i / rawPaths.length) * 35);
                    const timeRem = calculateRealUploadTimeRemaining(i + 1, rawPaths.length);
                    updateVercelProgress(pct, `GitHub Sync (${i+1}/${rawPaths.length}): ${cleanPath}`, timeRem);
                }

                // 5. Upload Files to Vercel File Store
                updateVercelProgress(58, "Uploading codebase to Vercel Cloud Store...", "Uploading...");
                const vercelFiles = [];
                for (let i = 0; i < rawPaths.length; i++) {
                    const rawPath = rawPaths[i];
                    let normPath = rawPath.replace(/\\/g, '/');
                    let cleanPath = commonPrefix && normPath.startsWith(commonPrefix) ? normPath.substring(commonPrefix.length) : normPath;
                    cleanPath = cleanPath.replace(/^\/+/, '');
                    if (!cleanPath) continue;

                    const uint8 = await loadedZip.files[rawPath].async("uint8array");
                    const sha1 = await sha1Hex(uint8);
                    const size = uint8.length;

                    await fetchWithRetry('/vercel_api/v2/files', {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${vercelToken}`,
                            'Content-Type': 'application/octet-stream',
                            'x-now-digest': sha1,
                            'x-now-size': String(size)
                        },
                        body: uint8
                    });

                    vercelFiles.push({ file: cleanPath, sha: sha1, size: size });
                }

                // 6. Create / Update Vercel Project
                updateVercelProgress(75, "Configuring Vercel project & build commands...", "Configuring...");
                const projPayload = { name: cleanProjectName };
                if (frameworkValue) projPayload.framework = frameworkValue;
                if (rootDir && rootDir !== './' && rootDir !== '.') projPayload.rootDirectory = rootDir;
                if (buildCmd) projPayload.buildCommand = buildCmd;
                if (outputDir) projPayload.outputDirectory = outputDir;
                if (installCmd) projPayload.installCommand = installCmd;

                await fetch('/vercel_api/v11/projects', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${vercelToken}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify(projPayload)
                });

                // 7. Inject Environment Variables
                if (envVars.length > 0) {
                    updateVercelProgress(82, `Injecting ${envVars.length} environment variables...`, "Setting env...");
                    await pushEnvVarsToVercel(cleanProjectName, envVars, vercelToken);
                }

                // 8. Trigger Vercel Production Build
                updateVercelProgress(88, "Triggering build and container initialization...", "Deploying...");
                const deployPayload = {
                    name: cleanProjectName,
                    files: vercelFiles,
                    target: "production",
                    projectSettings: {
                        framework: frameworkValue,
                        buildCommand: buildCmd || null,
                        outputDirectory: outputDir || null,
                        installCommand: installCmd || null,
                        rootDirectory: (rootDir && rootDir !== './' && rootDir !== '.') ? rootDir : null
                    }
                };

                const deployRes = await fetch('/vercel_api/v13/deployments?skipAutoDetectionConfirmation=1', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${vercelToken}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(deployPayload)
                });

                if (!deployRes.ok) {
                    const dErr = await deployRes.json().catch(() => ({}));
                    throw new Error(dErr.error?.message || `Vercel Deployment error (HTTP ${deployRes.status}). Check build commands.`);
                }

            const dData = await deployRes.json();
                const deploymentId = dData.id || "";
                
                // Extract the exact live production URL assigned by Vercel
                let rawUrl = dData.url || (dData.alias && dData.alias[0]) || `${cleanProjectName}.vercel.app`;
                if (dData.subdomain) {
                    rawUrl = `${dData.subdomain}.vercel.app`;
                }
                const liveUrl = rawUrl.startsWith('http') ? rawUrl : `https://${rawUrl}`;

                const newProject = {
                    id: cleanProjectName,
                    deploymentId: deploymentId,
                    url: liveUrl,
                    deploymentUrl: liveUrl,
                    inspectorUrl: dData.inspectorUrl || "https://vercel.com",
                    github: `https://github.com/${CONFIG.USERNAME}/${cleanProjectName}`,
                    date: new Date().toISOString(),
                    status: (dData.readyState === 'READY' ? 'live' : 'building'),
                    platform: 'vercel',
                    preset: preset,
                    _vercelFiles: vercelFiles,
                    config: { preset, rootDir, buildCmd, outputDir, installCmd, envVars }
                };

                saveVercelDeploymentRecord(newProject);
                activeDeployments.add(cleanProjectName);

                const existingIdx = projects.findIndex(p => p.id === cleanProjectName);
                if (existingIdx >= 0) projects[existingIdx] = newProject;
                else projects.unshift(newProject);

                renderProjects();
                renderAnalytics();
                clearVercelFile();
                document.getElementById('vercelProjectName').value = '';

                if (deploymentId && dData.readyState !== 'READY') {
                    showToast("Code pushed to GitHub & uploaded to Vercel. Polling deployment...", "info");
                    pollVercelBuildStatus(deploymentId, cleanProjectName);
                } else {
                    updateVercelProgress(100, "Live and Ready!", "Ready");
                    showToast(`Deployment ready at ${liveUrl}`, "success");
                    setGlobalFloatingProgress({ visible: true, name: cleanProjectName, badge: 'NODE/VERCEL', pct: 100, status: "Live & Ready!", time: "Ready", done: true });
                    setTimeout(() => setGlobalFloatingProgress({ visible: false }), 4000);
                }

                switchView('dashboard', document.querySelectorAll('.nav-link-custom')[0]);

            } catch (err) {
                console.error("Vercel pipeline failure:", err);
                showPipelineError("Pipeline Execution Error", err.message || "An unexpected error stopped the deployment.");
                setGlobalFloatingProgress({ visible: false });
            } finally {
                deployBtn.disabled = false;
                isPipelineActive = false;
                setTimeout(() => {
                    progCont.classList.add('d-none');
                    progBar.style.width = '0%';
                }, 3000);
            }
        }

        // --- Real-Time Vercel Build Polling (Resolves 404 DEPLOYMENT_NOT_FOUND) ---
        async function pollVercelBuildStatus(deploymentId, cleanProjectName) {
            let attempts = 0;
            const maxAttempts = 40; // Poll for up to ~2 minutes
            const pollStartTime = performance.now();

            const pollInterval = setInterval(async () => {
                attempts++;
                const elapsedSec = Math.round((performance.now() - pollStartTime) / 1000);
                const estRemaining = Math.max(5, 55 - elapsedSec);

                try {
                    const res = await fetch(`/vercel_api/v13/deployments/${deploymentId}`, {
                        headers: { 'Authorization': `Bearer ${CONFIG.VERCEL_TOKEN}` }
                    });

                    if (res.ok) {
                        const data = await res.json();
                        const state = data.readyState; // QUEUED, BUILDING, READY, ERROR, CANCELED

                        setGlobalFloatingProgress({
                            visible: true,
                            name: cleanProjectName,
                            badge: 'ELIVORA',
                            pct: Math.min(98, 86 + Math.floor((attempts / maxAttempts) * 12)),
                            status: `Elivora Cloud: ${state} (${elapsedSec}s)...`,
                            time: state === 'READY' ? 'Ready!' : `Est. ~${estRemaining}s left`
                        });

                        const proj = projects.find(p => p.id === cleanProjectName);
                        if (proj) {
                            if (state === 'READY') {
                                clearInterval(pollInterval);
                                proj.status = 'live';
                                
                                // Grab the exact working domain from Vercel's status response
                                let activeDomain = data.url || (data.alias && data.alias[0]) || `${cleanProjectName}.vercel.app`;
                                proj.url = activeDomain.startsWith('http') ? activeDomain : `https://${activeDomain}`;
                                saveVercelDeploymentRecord(proj);
                                renderProjects();

                                setGlobalFloatingProgress({
                                    visible: true,
                                    name: cleanProjectName,
                                    badge: 'ELIVORA',
                                    pct: 100,
                                    status: 'Deployment Live & Verified!',
                                    time: `Done in ${elapsedSec}s`,
                                    done: true
                                });
                                showToast(`Vercel build ready! Site is live at https://${cleanProjectName}.vercel.app`, 'success');
                                setTimeout(() => setGlobalFloatingProgress({ visible: false }), 4500);

                            } else if (state === 'ERROR' || state === 'CANCELED') {
                                clearInterval(pollInterval);
                                proj.status = 'failed';
                                proj.error = data.error?.message || "Vercel build encountered an error. Check install/build commands or env vars.";
                                saveVercelDeploymentRecord(proj);
                                renderProjects();

                                setGlobalFloatingProgress({
                                    visible: true,
                                    name: cleanProjectName,
                                    badge: 'ELIVORA',
                                    pct: 100,
                                    status: 'Build Failed on Vercel',
                                    time: 'Failed',
                                    failed: true
                                });
                                showToast(`Vercel build failed: ${proj.error}. Click 'Settings' on card to adjust.`, 'error');
                                setTimeout(() => setGlobalFloatingProgress({ visible: false }), 6000);

                            } else {
                                proj.status = 'building';
                                updateCardUI(cleanProjectName);
                            }
                        }
                    }

                    if (attempts >= maxAttempts) {
                        clearInterval(pollInterval);
                        setGlobalFloatingProgress({ visible: false });
                    }
                } catch(e) {
                    console.warn("Polling error:", e);
                }
            }, 3000);
        }

        // --- One-Click Auto Re-Deploy for Vercel ---
        async function triggerAutoRedeploy(projectId) {
            const savedList = getSavedVercelDeployments();
            const proj = savedList.find(p => p.id === projectId) || projects.find(p => p.id === projectId);
            if (!proj) return showToast("Project details not found for re-deploy", "error");

            const vercelToken = (CONFIG.VERCEL_TOKEN || "").trim();
            if (!vercelToken) {
                return showToast("Please configure your Vercel Access Token in Settings.", "error");
            }

            startCardProcess(projectId, "Triggering Auto Re-Deploy...");
            setGlobalFloatingProgress({
                visible: true,
                name: projectId,
                badge: 'ELIVORA',
                pct: 15,
                status: "Preparing Vercel re-deployment...",
                time: "Starting..."
            });

            try {
                const pConfig = proj.config || {};
                const frameworkMap = { "Next.js": "nextjs", "Vite": "vite", "React": "create-react-app", "Other": null };
                const frameworkVal = frameworkMap[pConfig.preset] || null;

                const projectSettings = {
                    framework: frameworkVal,
                    buildCommand: pConfig.buildCmd || null,
                    outputDirectory: pConfig.outputDir || null,
                    installCommand: pConfig.installCmd || null,
                    rootDirectory: (pConfig.rootDir && pConfig.rootDir !== './' && pConfig.rootDir !== '.') ? pConfig.rootDir : null
                };

                // Push env vars to Vercel before redeploying (if any saved)
                const savedEnvVars = pConfig.envVars || [];
                if (savedEnvVars.length > 0) {
                    setGlobalFloatingProgress({ visible: true, name: projectId, badge: 'ELIVORA', pct: 25, status: "Pushing env vars to Vercel...", time: "Configuring..." });
                    await pushEnvVarsToVercel(projectId, savedEnvVars, vercelToken);
                }

                let vercelDeployPayload;

                // Strategy 1: Use stored Vercel files list (direct re-upload, no GitHub needed)
                if (proj._vercelFiles && proj._vercelFiles.length > 0) {
                    setGlobalFloatingProgress({ visible: true, name: projectId, badge: 'ELIVORA', pct: 50, status: "Re-deploying from stored files...", time: "Building..." });
                    vercelDeployPayload = {
                        name: projectId,
                        files: proj._vercelFiles,
                        target: "production",
                        projectSettings
                    };
                }
                // Strategy 2: Use GitHub source (requires GitHub token + GitHub-Vercel integration)
                else if (CONFIG.TOKEN && CONFIG.USERNAME) {
                    setGlobalFloatingProgress({ visible: true, name: projectId, badge: 'ELIVORA', pct: 40, status: "Fetching GitHub repo info...", time: "Connecting..." });
                    const repoInfo = await ghFetch(`/repos/${CONFIG.USERNAME}/${projectId}`);
                    const repoId = repoInfo.id;
                    const defaultBranch = repoInfo.default_branch || 'main';
                    vercelDeployPayload = {
                        name: projectId,
                        target: "production",
                        gitSource: { type: "github", repoId: String(repoId), ref: defaultBranch },
                        projectSettings
                    };
                }
                // Strategy 3: Trigger re-deploy from Vercel's last known deployment
                else {
                    // Just re-trigger from latest deployment on Vercel
                    setGlobalFloatingProgress({ visible: true, name: projectId, badge: 'ELIVORA', pct: 50, status: "Triggering Vercel re-build...", time: "Building..." });
                    vercelDeployPayload = {
                        name: projectId,
                        target: "production",
                        projectSettings
                    };
                }

                const deployRes = await fetch('/vercel_api/v13/deployments?skipAutoDetectionConfirmation=1', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${vercelToken}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(vercelDeployPayload)
                });

                if (!deployRes.ok) {
                    const err = await deployRes.json().catch(() => ({}));
                    throw new Error(err.error?.message || `Re-deploy failed (HTTP ${deployRes.status}). Try uploading a new zip.`);
                }

                const dData = await deployRes.json();
                const deploymentId = dData.id;
                const inspectorUrl = dData.inspectorUrl || `https://vercel.com`;

                proj.status = 'building';
                proj.deploymentId = deploymentId;
                proj.inspectorUrl = inspectorUrl;
                saveVercelDeploymentRecord(proj);
                updateCardUI(projectId);

                finishCardProcess(projectId, "Build Triggered!");
                showToast(`🔄 Re-deploy triggered for ${projectId}! Monitoring build...`, 'info');

                pollVercelBuildStatus(deploymentId, projectId);

            } catch (err) {
                console.error("Auto Re-Deploy error:", err);
                failCardProcess(projectId, err.message);
                setGlobalFloatingProgress({ visible: false });
            }
        }

        // --- Vercel Project Settings Modal Logic ---
        function openVercelSettingsModal(projectId) {
            const savedList = getSavedVercelDeployments();
            const proj = savedList.find(p => p.id === projectId) || projects.find(p => p.id === projectId);
            if (!proj) return showToast("Project not found", "error");

            document.getElementById('modalVercelProjectId').value = projectId;
            
            const cfg = proj.config || {};
            document.getElementById('modalVercelPreset').value = cfg.preset || proj.preset || 'Other';
            document.getElementById('modalVercelRootDir').value = cfg.rootDir || './';
            document.getElementById('modalVercelBuildCmd').value = cfg.buildCmd || '';
            document.getElementById('modalVercelOutputDir').value = cfg.outputDir || '';
            document.getElementById('modalVercelInstallCmd').value = cfg.installCmd || 'npm install';

            // Clear and populate env vars
            const container = document.getElementById('modalEnvRowsContainer');
            container.innerHTML = '';
            const envs = cfg.envVars || [];
            if (envs.length > 0) {
                envs.forEach(ev => addEnvVariableRow(ev.key, ev.value, 'modalEnvRowsContainer'));
            } else {
                addEnvVariableRow('NODE_ENV', 'production', 'modalEnvRowsContainer');
            }

            document.getElementById('vercelSettingsModalOverlay').classList.add('active');
        }

        function saveVercelModalSettingsOnly() {
            const projectId = document.getElementById('modalVercelProjectId').value;
            const preset = document.getElementById('modalVercelPreset').value;
            const rootDir = document.getElementById('modalVercelRootDir').value.trim();
            const buildCmd = document.getElementById('modalVercelBuildCmd').value.trim();
            const outputDir = document.getElementById('modalVercelOutputDir').value.trim();
            const installCmd = document.getElementById('modalVercelInstallCmd').value.trim();
            const envVars = getEnvVariablesFromContainer('modalEnvRowsContainer');

            const proj = projects.find(p => p.id === projectId);
            if (proj) {
                proj.preset = preset;
                proj.config = { preset, rootDir, buildCmd, outputDir, installCmd, envVars };
                saveVercelDeploymentRecord(proj);
                renderProjects();
            }

            closeModals();
            showToast("Project settings saved locally!", "success");
        }

        async function saveAndAutoRedeployFromModal() {
            const projectId = document.getElementById('modalVercelProjectId').value;
            const preset = document.getElementById('modalVercelPreset').value;
            const rootDir = document.getElementById('modalVercelRootDir').value.trim();
            const buildCmd = document.getElementById('modalVercelBuildCmd').value.trim();
            const outputDir = document.getElementById('modalVercelOutputDir').value.trim();
            const installCmd = document.getElementById('modalVercelInstallCmd').value.trim();
            const envVars = getEnvVariablesFromContainer('modalEnvRowsContainer');

            const proj = projects.find(p => p.id === projectId);
            if (proj) {
                proj.preset = preset;
                proj.config = { preset, rootDir, buildCmd, outputDir, installCmd, envVars };
                saveVercelDeploymentRecord(proj);
            }

            closeModals();

            showToast("Updating Vercel cloud project settings & env vars...", "info");
            try {
                const frameworkMap = { "Next.js": "nextjs", "Vite": "vite", "React": "create-react-app", "Other": null };
                // 1. Update project build settings via PATCH
                const updatePayload = {};
                if (frameworkMap[preset] !== undefined) updatePayload.framework = frameworkMap[preset];
                if (rootDir) updatePayload.rootDirectory = rootDir === './' ? null : rootDir;
                if (buildCmd) updatePayload.buildCommand = buildCmd;
                if (outputDir) updatePayload.outputDirectory = outputDir;
                if (installCmd) updatePayload.installCommand = installCmd;

                await fetch(`/vercel_api/v9/projects/${projectId}`, {
                    method: 'PATCH',
                    headers: {
                        'Authorization': `Bearer ${CONFIG.VERCEL_TOKEN}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(updatePayload)
                }).catch(() => {});

                // 2. Push env vars using the correct Vercel env API (POST /v10/projects/:id/env)
                if (envVars.length > 0) {
                    await pushEnvVarsToVercel(projectId, envVars, CONFIG.VERCEL_TOKEN);
                    showToast(`✅ Pushed ${envVars.length} env var(s) to Vercel successfully!`, "success");
                }
            } catch(e) {
                console.warn('Settings update warning:', e);
            }

            // Now trigger fresh deployment
            await triggerAutoRedeploy(projectId);
        }

        // --- Load & Render Deployments ---
        async function loadDeployments() {
            const grid = document.getElementById('projectGrid');
            grid.innerHTML = `<div class="col-12 text-center py-5"><div class="spinner-border text-primary"></div><p class="text-muted mt-2">Loading deployments...</p></div>`;
            
            try {
                const savedVercel = getSavedVercelDeployments();
                let ghRepos = [];
                
                if (CONFIG.TOKEN) {
                    ghRepos = await ghFetch(`/user/repos?affiliation=owner&sort=created&direction=desc&per_page=100`).catch(() => []);
                }

                const repoMap = new Map();

                // Add GitHub repos
                ghRepos.forEach(repo => {
                    const savedState = localStatuses[repo.name] || { status: 'live', reason: '' };
                    repoMap.set(repo.name, {
                        id: repo.name,
                        url: `https://${CONFIG.USERNAME || repo.owner.login}.github.io/${repo.name}/`,
                        github: repo.html_url,
                        date: repo.created_at,
                        status: savedState.status,
                        reason: savedState.reason,
                        platform: 'github'
                    });
                });

                // Merge Vercel projects
                savedVercel.forEach(vp => {
                    if (repoMap.has(vp.id)) {
                        const existing = repoMap.get(vp.id);
                        existing.url = vp.url;
                        existing.platform = 'vercel';
                        existing.preset = vp.preset;
                        existing.status = vp.status || existing.status;
                        existing.deploymentId = vp.deploymentId;
                        existing.inspectorUrl = vp.inspectorUrl;
                        existing.config = vp.config;
                        existing.error = vp.error;
                    } else {
                        repoMap.set(vp.id, vp);
                    }
                });

                projects = Array.from(repoMap.values()).sort((a, b) => new Date(b.date) - new Date(a.date));
                
                renderProjects();
                renderAnalytics();
            } catch (err) {
                console.error(err);
                grid.innerHTML = `<div class="col-12 text-center py-5 text-danger"><i class="bi bi-wifi-off fs-1"></i><p>Connection Error. Check API Token in Settings.</p></div>`;
            }
        }

        async function backgroundPingSync() {
            if (!CONFIG.TOKEN || isPipelineActive) return;
            try {
                const repos = await ghFetch(`/user/repos?affiliation=owner&sort=created&direction=desc&per_page=100`);
                let changed = false;
                const fetchedIds = repos.map(r => r.name);
                const existingIds = projects.map(p => p.id);

                fetchedIds.forEach(id => {
                    if (!existingIds.includes(id)) {
                        const repo = repos.find(r => r.name === id);
                        projects.unshift({
                            id: repo.name,
                            url: `https://${CONFIG.USERNAME}.github.io/${repo.name}/`,
                            github: repo.html_url,
                            date: repo.created_at,
                            status: 'live',
                            platform: 'github'
                        });
                        changed = true;
                    }
                });

                projects = projects.filter(p => {
                    if (activeDeployments.has(p.id) || p.platform === 'vercel') return true;
                    return fetchedIds.includes(p.id);
                });

                if (changed) {
                    renderProjects();
                    renderAnalytics();
                }
            } catch(e) {}
        }

        // --- Card Generation & UI ---
        function generateCardHTML(p) {
            const cacheBuster = new Date().getTime();
            const isLive = p.status === 'live';
            const isBuilding = p.status === 'building';
            const isFailed = p.status === 'failed';
            const isVercel = p.platform === 'vercel';
            
            let previewHTML = '';
            if (isLive) {
                previewHTML = `
                    <iframe src="${p.url}?t=${cacheBuster}" class="preview-iframe" scrolling="no" loading="lazy" sandbox="allow-scripts allow-same-origin"></iframe>
                    <div class="preview-shield" onclick="window.open('${p.url}', '_blank')"></div>
                `;
            } else if (isBuilding) {
                previewHTML = `
                <div class="w-100 h-100 d-flex flex-column align-items-center justify-content-center bg-white p-3 text-center">
                    <div class="spinner-border text-primary mb-2" style="width: 1.8rem; height: 1.8rem;"></div>
                    <span class="fw-bold small text-uppercase text-main">Building on Elivora Cloud...</span>
                    <span class="text-muted small mt-1" style="font-size:0.75rem;">Provisioning serverless runtime & building</span>
                </div>`;
            } else if (isFailed) {
                previewHTML = `
                <div class="w-100 h-100 d-flex flex-column align-items-center justify-content-center bg-white p-3 text-center">
                    <i class="bi bi-exclamation-triangle-fill fs-2 mb-1 text-danger"></i>
                    <span class="fw-bold small text-uppercase text-danger">Build Failed</span>
                    <span class="text-muted small mt-1 text-truncate w-100 px-2" style="font-size:0.75rem;">${escapeHtml(p.error || 'Check build command or env vars')}</span>
                    <div class="d-flex gap-2 mt-2">
                        ${p.inspectorUrl ? `<a href="${p.inspectorUrl}" target="_blank" class="btn btn-sm btn-outline-dark py-1 px-2" style="font-size:0.72rem;">Logs</a>` : ''}
                        <button class="btn btn-sm btn-primary-custom py-1 px-2" style="font-size:0.72rem;" onclick="triggerAutoRedeploy('${p.id}')"><i class="bi bi-arrow-repeat"></i> Re-deploy</button>
                    </div>
                </div>`;
            } else {
                previewHTML = `
                <div class="w-100 h-100 d-flex flex-column align-items-center justify-content-center bg-light text-main p-3 text-center">
                    <i class="bi bi-tools fs-2 mb-2 text-warning"></i>
                    <span class="fw-bold small text-uppercase text-warning">Maintenance Active</span>
                    <span class="small mt-1 fst-italic text-truncate w-100 px-2 text-muted" style="font-size:0.75rem;">"${p.reason || 'Under update'}"</span>
                </div>`;
            }

            const platformBadge = `<span class="badge bg-light text-dark border" style="font-size:0.65rem; border-color: var(--border-color) !important;"><i class="bi bi-cloud-check text-dark me-1"></i> ELIVORA</span>`;

            let statusBadge = '';
            if (isLive) {
                statusBadge = `<span class="status-badge live"><span class="status-dot"></span> LIVE</span>`;
            } else if (isBuilding) {
                statusBadge = `<span class="status-badge paused" style="background: var(--primary-light); color: var(--text-main);"><span class="spinner-border spinner-border-sm me-1" style="width:10px; height:10px; border-width: 1.5px;"></span> BUILDING</span>`;
            } else if (isFailed) {
                statusBadge = `<span class="status-badge failed"><span class="status-dot"></span> FAILED</span>`;
            } else {
                statusBadge = `<span class="status-badge paused"><span class="status-dot"></span> UPDATING</span>`;
            }

            return `
                <div class="col-12 col-md-6 col-xl-4 col-xxl-3 repo-card-wrapper" data-id="${p.id}" id="repo-card-${p.id}">
                    <div class="saas-card p-3 h-100 d-flex flex-column">
                        
                        <div class="card-process-overlay" id="process-overlay-${p.id}">
                            <div class="spinner-border text-primary mb-2" style="width: 2rem; height: 2rem;" id="process-spinner-${p.id}"></div>
                            <h6 class="fw-bold text-main mb-3" id="process-title-${p.id}">Processing...</h6>
                            <div class="w-100 px-3">
                                <div class="d-flex justify-content-between mb-1">
                                    <span class="small text-muted fw-bold" style="font-size:0.7rem;">PROGRESS</span>
                                    <span class="small fw-bold text-primary" id="process-text-${p.id}">0%</span>
                                </div>
                                <div class="progress" style="height: 6px; background: var(--border-color);">
                                    <div class="progress-bar bg-primary progress-bar-striped progress-bar-animated" id="process-bar-${p.id}" style="width: 0%; transition: 0.1s linear;"></div>
                                </div>
                            </div>
                        </div>

                        <div class="preview-wrapper">${previewHTML}</div>
                        <div class="d-flex justify-content-between align-items-start mb-2 mt-1">
                            <div class="d-flex align-items-center gap-1 text-truncate pe-2">
                                <h5 class="fw-bold mb-0 text-truncate text-main" title="${p.id}">${p.id}</h5>
                            </div>
                            <div class="d-flex align-items-center gap-1 flex-shrink-0">
                                ${platformBadge}
                                ${statusBadge}
                            </div>
                        </div>
                        <a href="${isLive ? p.url : '#'}" target="${isLive ? '_blank' : '_self'}" class="text-muted text-decoration-none small mb-3 d-block text-truncate">${p.url.replace('https://', '')}</a>
                        
                        <div class="mt-auto d-flex align-items-center justify-content-between pt-3 border-top" style="border-color: var(--border-color) !important;">
                            <div class="d-flex align-items-center gap-2">
                                <a href="${p.github}" target="_blank" class="text-main text-decoration-none d-flex align-items-center gap-1" title="Source Repository" style="font-size: 0.78rem; font-weight: 500;"><i class="bi bi-code-slash fs-5"></i></a>
                                ${isVercel ? `<button class="btn btn-sm border bg-white text-main d-flex align-items-center gap-1 py-1 px-2" onclick="triggerAutoRedeploy('${p.id}')" title="Auto Re-Deploy on Vercel" style="font-size: 0.75rem; border-color: var(--border-color) !important;"><i class="bi bi-arrow-repeat"></i> Re-deploy</button>` : ''}
                            </div>
                            <div class="dropdown">
                                <button class="btn border-0 text-muted p-1" data-bs-toggle="dropdown"><i class="bi bi-three-dots-vertical"></i></button>
                                <ul class="dropdown-menu dropdown-menu-end">
                                    <li><button class="dropdown-item" onclick="copyUrl('${p.url}')"><i class="bi bi-clipboard me-2"></i> Copy URL</button></li>
                                    <li><button class="dropdown-item" onclick="window.open('${p.url}', '_blank')"><i class="bi bi-box-arrow-up-right me-2"></i> Open Site</button></li>
                                    ${isVercel ? `<li><button class="dropdown-item" onclick="triggerAutoRedeploy('${p.id}')"><i class="bi bi-arrow-repeat me-2"></i> Auto Re-Deploy</button></li>` : ''}
                                    ${isVercel ? `<li><button class="dropdown-item" onclick="openVercelSettingsModal('${p.id}')"><i class="bi bi-sliders me-2"></i> Project Settings & Env</button></li>` : ''}
                                    <li><hr class="dropdown-divider"></li>
                                    <li><button class="dropdown-item" onclick="openRenameModal('${p.id}')"><i class="bi bi-input-cursor-text me-2"></i> Rename</button></li>
                                    <li><button class="dropdown-item text-warning fw-bold" onclick="openPauseModal('${p.id}')"><i class="bi bi-pause-circle me-2"></i> Maintenance</button></li>
                                    <li><button class="dropdown-item text-success fw-bold" onclick="executeResume('${p.id}')"><i class="bi bi-play-circle me-2"></i> Resume</button></li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li><button class="dropdown-item text-danger fw-bold" onclick="promptDeleteModal('${p.id}')"><i class="bi bi-trash3-fill me-2"></i> Delete</button></li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>`;
        }

        function filterProjects() {
            const query = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.repo-card-wrapper').forEach(card => {
                const id = card.getAttribute('data-id').toLowerCase();
                card.style.display = id.includes(query) ? '' : 'none';
            });
        }

        function renderProjects() {
            const grid = document.getElementById('projectGrid');
            if (!projects.length) {
                grid.innerHTML = `<div class="col-12 text-center py-5 text-muted"><i class="bi bi-inbox fs-1 d-block mb-2"></i>No deployments found yet. Launch a static or Vercel project to get started.</div>`;
                return;
            }
            grid.innerHTML = projects.map(p => generateCardHTML(p)).join('');
        }

        function updateCardUI(id) {
            const p = projects.find(x => x.id === id);
            if (!p) return;
            const el = document.getElementById(`repo-card-${id}`);
            if (el) {
                const temp = document.createElement('div');
                temp.innerHTML = generateCardHTML(p);
                el.replaceWith(temp.firstElementChild);
            }
        }

        // --- Analytics Velocity Chart ---
        function renderAnalytics() {
            document.getElementById('statTotal').innerText = projects.length;
            const now = new Date();
            const sevenDaysAgo = new Date(now.getTime() - (7 * 24 * 60 * 60 * 1000));
            const recent = projects.filter(p => new Date(p.date) >= sevenDaysAgo).length;
            document.getElementById('statRecent').innerText = recent;

            const days = [];
            const counts = [];
            for (let i = 6; i >= 0; i--) {
                const d = new Date(now.getTime() - (i * 24 * 60 * 60 * 1000));
                const dStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                days.push(dStr);
                const count = projects.filter(p => {
                    const pDate = new Date(p.date);
                    return pDate.getDate() === d.getDate() && pDate.getMonth() === d.getMonth();
                }).length;
                counts.push(count);
            }

            const canvas = document.getElementById('analyticsChart');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            if (analyticsChartInstance) analyticsChartInstance.destroy();

            analyticsChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: days,
                    datasets: [{
                        label: 'Deployments',
                        data: counts,
                        borderColor: '#0f172a',
                        backgroundColor: 'rgba(15, 23, 42, 0.04)',
                        fill: true,
                        tension: 0.35,
                        borderWidth: 2,
                        pointBackgroundColor: '#0f172a',
                        pointBorderColor: '#ffffff',
                        pointHoverBackgroundColor: '#ffffff',
                        pointHoverBorderColor: '#0f172a',
                        pointRadius: 4,
                        pointHoverRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#0f172a',
                            titleColor: '#ffffff',
                            bodyColor: '#ffffff',
                            padding: 10,
                            displayColors: false,
                            cornerRadius: 6
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { precision: 0, color: '#64748b' },
                            grid: { color: '#f1f5f9' }
                        },
                        x: {
                            ticks: { color: '#64748b' },
                            grid: { display: false }
                        }
                    }
                }
            });
        }

        // --- Card Async Operations & Overlay Helpers ---
        function startCardProcess(id, title) {
            const overlay = document.getElementById(`process-overlay-${id}`);
            if (!overlay) return;
            overlay.classList.add('active');
            document.getElementById(`process-title-${id}`).innerText = title;
            document.getElementById(`process-text-${id}`).innerText = '0%';
            document.getElementById(`process-bar-${id}`).style.width = '0%';
            document.getElementById(`process-bar-${id}`).className = 'progress-bar bg-primary progress-bar-striped progress-bar-animated';
            document.getElementById(`process-spinner-${id}`).style.display = 'block';
        }

        function finishCardProcess(id, successTitle, isDelete = false) {
            const overlay = document.getElementById(`process-overlay-${id}`);
            if (!overlay) return;
            document.getElementById(`process-bar-${id}`).style.width = '100%';
            document.getElementById(`process-text-${id}`).innerText = '100%';
            document.getElementById(`process-spinner-${id}`).style.display = 'none';
            document.getElementById(`process-title-${id}`).innerHTML = `<i class="bi bi-check-circle-fill text-success me-1"></i> ${successTitle}`;

            setTimeout(() => {
                if (isDelete) {
                    const card = document.getElementById(`repo-card-${id}`);
                    if (card) {
                        card.style.opacity = '0';
                        card.style.transform = 'scale(0.85)';
                        setTimeout(() => card.remove(), 300);
                    }
                } else {
                    overlay.classList.remove('active');
                    updateCardUI(id);
                }
            }, 1200);
        }

        function failCardProcess(id, errorMsg) {
            const overlay = document.getElementById(`process-overlay-${id}`);
            if (!overlay) return;
            document.getElementById(`process-spinner-${id}`).style.display = 'none';
            document.getElementById(`process-bar-${id}`).className = 'progress-bar bg-danger';
            document.getElementById(`process-title-${id}`).innerHTML = `<i class="bi bi-x-circle-fill text-danger me-1"></i> Failed`;
            showToast(errorMsg, 'error');
            setTimeout(() => {
                overlay.classList.remove('active');
            }, 2000);
        }

        // --- Modals & Repo Actions ---
        let targetDeleteId = '';
        function promptDeleteModal(id) {
            targetDeleteId = id;
            document.getElementById('confirmDeleteName').innerText = id;
            document.getElementById('confirmDeleteOverlay').classList.add('active');
        }

        async function executeConfirmedDelete() {
            closeModals();
            const id = targetDeleteId;
            startCardProcess(id, "Deleting Deployment & Repo...");

            let githubDeleted = false;
            let vercelDeleted = false;
            let warningNotes = [];

            // 1. Delete from GitHub if token is present
            if (CONFIG.TOKEN) {
                try {
                    if (!CONFIG.USERNAME) {
                        const uData = await ghFetch('/user').catch(() => null);
                        if (uData) CONFIG.USERNAME = uData.login;
                    }
                    if (CONFIG.USERNAME) {
                        await ghFetch(`/repos/${CONFIG.USERNAME}/${id}`, { method: 'DELETE' });
                        githubDeleted = true;
                    }
                } catch (ghErr) {
                    if (ghErr.message.includes('404')) {
                        githubDeleted = true; // Repo already gone on GitHub
                    } else if (ghErr.message.includes('403') || ghErr.message.includes('Must have admin rights')) {
                        warningNotes.push("GitHub PAT requires 'delete_repo' scope to delete from GitHub directly.");
                    } else {
                        warningNotes.push(`GitHub: ${ghErr.message}`);
                    }
                }
            }

            // 2. Delete from Vercel if Vercel token is present
            if (CONFIG.VERCEL_TOKEN) {
                try {
                    const vRes = await fetch(`/vercel_api/v9/projects/${id}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${CONFIG.VERCEL_TOKEN}` }
                    });
                    if (vRes.ok || vRes.status === 404) {
                        vercelDeleted = true;
                    } else {
                        const vErr = await vRes.json().catch(() => ({}));
                        warningNotes.push(`Vercel: ${vErr.error?.message || vRes.status}`);
                    }
                } catch(e) {
                    warningNotes.push(`Vercel: ${e.message}`);
                }
            }

            // 3. Clear from local storage and cache regardless
            const vList = getSavedVercelDeployments().filter(x => x.id !== id);
            localStorage.setItem('elivora_vercel_projects', JSON.stringify(vList));
            
            delete localStatuses[id];
            localStorage.setItem('elivora_statuses', JSON.stringify(localStatuses));

            projects = projects.filter(x => x.id !== id);
            activeDeployments.delete(id);

            finishCardProcess(id, "Deleted", true);

            if (warningNotes.length > 0) {
                showToast(`Project removed locally. (${warningNotes.join(' | ')})`, 'warning');
            } else {
                showToast(`Deployment '${id}' deleted successfully from all platforms.`, 'success');
            }
            renderAnalytics();
        }

        function openRenameModal(oldName) {
            document.getElementById('renameOldName').value = oldName;
            document.getElementById('renameNewName').value = oldName;
            document.getElementById('renameModalOverlay').classList.add('active');
        }

        async function executeRename() {
            const oldName = document.getElementById('renameOldName').value;
            const newName = document.getElementById('renameNewName').value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-');
            closeModals();
            if (!newName || newName === oldName) return;

            startCardProcess(oldName, "Renaming Project...");
            try {
                await ghFetch(`/repos/${CONFIG.USERNAME}/${oldName}`, { 
                    method: 'PATCH', 
                    body: JSON.stringify({ name: newName }) 
                });
                
                const proj = projects.find(x => x.id === oldName);
                if (proj) {
                    proj.id = newName;
                    if (proj.platform === 'github') {
                        proj.url = `https://${CONFIG.USERNAME}.github.io/${newName}/`;
                    }
                    proj.github = `https://github.com/${CONFIG.USERNAME}/${newName}`;
                }

                finishCardProcess(oldName, "Renamed!");
                showToast(`Repository renamed to ${newName}`, 'success');
                setTimeout(() => location.reload(), 1200);
            } catch (err) {
                failCardProcess(oldName, err.message);
            }
        }

        function toggleCustomHtml() {
            const isCustom = document.getElementById('useCustomHtmlToggle').checked;
            document.getElementById('standardPauseInput').classList.toggle('d-none', isCustom);
            document.getElementById('customPauseInput').classList.toggle('d-none', !isCustom);
        }

        function openPauseModal(id) {
            document.getElementById('pauseProjectId').value = id;
            document.getElementById('pauseModalOverlay').classList.add('active');
        }

        async function executeGlobalPause() {
            const id = document.getElementById('pauseProjectId').value;
            const isCustom = document.getElementById('useCustomHtmlToggle').checked;
            const reason = document.getElementById('pauseReasonInput').value.trim() || 'Site temporarily undergoing maintenance.';
            const customCode = document.getElementById('pauseCustomHtmlCode').value.trim();
            closeModals();

            startCardProcess(id, "Deploying Maintenance Notice...");
            const htmlContent = isCustom && customCode ? customCode : `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Maintenance</title><style>body{font-family:sans-serif;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;}</style></head><body><div><h1>Under Maintenance</h1><p>${escapeHtml(reason)}</p></div></body></html>`;

            try {
                let sha = null;
                try {
                    const idxFile = await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/index.html`);
                    if (idxFile && idxFile.sha) sha = idxFile.sha;
                } catch(e) {}

                const putPayload = { message: "Deploy maintenance mode", content: btoa(unescape(encodeURIComponent(htmlContent))) };
                if (sha) putPayload.sha = sha;

                await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/index.html`, { 
                    method: 'PUT', 
                    body: JSON.stringify(putPayload) 
                });

                localStatuses[id] = { status: 'paused', reason: reason };
                localStorage.setItem('elivora_statuses', JSON.stringify(localStatuses));

                const proj = projects.find(x => x.id === id);
                if (proj) { proj.status = 'paused'; proj.reason = reason; }

                finishCardProcess(id, "Maintenance Live");
                showToast("Maintenance mode deployed", 'warning');
            } catch (err) {
                failCardProcess(id, err.message);
            }
        }

        async function executeResume(id) {
            startCardProcess(id, "Resuming Website...");
            try {
                localStatuses[id] = { status: 'live', reason: '' };
                localStorage.setItem('elivora_statuses', JSON.stringify(localStatuses));

                const proj = projects.find(x => x.id === id);
                if (proj) { proj.status = 'live'; proj.reason = ''; }

                finishCardProcess(id, "Live Ready");
                showToast("Site resumed to live status", 'success');
            } catch (err) {
                failCardProcess(id, err.message);
            }
        }

        function closeModals() {
            document.querySelectorAll('.elivora-overlay').forEach(el => el.classList.remove('active'));
        }

        function copyUrl(url) {
            navigator.clipboard.writeText(url);
            showToast('Deployment URL copied to clipboard!', 'info');
        }

        function showToast(msg, type = 'info') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast-item ${type}`;
            const iconMap = {
                'error': '<i class="bi bi-x-circle-fill"></i>',
                'success': '<i class="bi bi-check-circle-fill text-success"></i>',
                'warning': '<i class="bi bi-exclamation-triangle-fill text-warning"></i>',
                'info': '<i class="bi bi-info-circle-fill"></i>'
            };
            toast.innerHTML = `${iconMap[type] || ''}<span>${escapeHtml(msg)}</span>`;
            container.appendChild(toast);
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transform = 'translateY(10px)';
                toast.style.transition = 'all 0.3s ease';
                setTimeout(() => toast.remove(), 300);
            }, 3500);
        }

        // --- Application Bootstrap ---
        window.addEventListener('DOMContentLoaded', () => {
            // Setup default tokens in Settings UI
            if (CONFIG.USERNAME) document.getElementById('cfgUsername').value = CONFIG.USERNAME;
            if (CONFIG.TOKEN && !CONFIG.TOKEN.includes('{{')) document.getElementById('cfgToken').value = CONFIG.TOKEN;
            if (CONFIG.VERCEL_TOKEN && !CONFIG.VERCEL_TOKEN.includes('{{')) document.getElementById('cfgVercelToken').value = CONFIG.VERCEL_TOKEN;

            // Drag & drop listeners
            setupDragDropZone('staticDropZone', 'staticFileInput', onStaticFileChosen);
            setupDragDropZone('vercelDropZone', 'vercelFileInput', onVercelFileChosen);

            // Populate initial env row
            addEnvVariableRow('NODE_ENV', 'production');
            checkActiveFloatingProgress();

            // Load repositories
            if (CONFIG.TOKEN && !CONFIG.TOKEN.includes('{{')) {
                loadDeployments();
                setInterval(backgroundPingSync, 20000);
            } else {
                switchView('settings', document.querySelectorAll('.nav-link-custom')[3]);
                showToast("Please enter your API credentials in Settings.", "warning");
            }
        });
    </script>
</body>
</html>

"""

# =====================================================================
# LOCAL WEB SERVER & API HANDLER
# =====================================================================
class WebDashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_vercel_proxy(self, method):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else None
        
        target_url = "https://api.vercel.com" + self.path.replace("/vercel_api", "")
        req = urllib.request.Request(target_url, data=post_data, method=method)
        
        for h in ['Authorization', 'Content-Type', 'x-now-digest', 'x-now-size']:
            if h in self.headers:
                req.add_header(h, self.headers[h])
                
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read()
                self.send_response(response.status)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                self.end_headers()
                self.wfile.write(body)
        except Exception as e:
            if hasattr(e, 'code') and hasattr(e, 'read'):
                self.send_response(e.code)
                self.send_header('Content-Type', e.headers.get('Content-Type', 'application/json') if hasattr(e, 'headers') else 'application/json')
                self.end_headers()
                self.wfile.write(e.read())
            else:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": str(e)}}).encode('utf-8'))

    def do_PATCH(self):
        if self.path.startswith('/vercel_api/'):
            self.do_vercel_proxy('PATCH')
            return
        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        if self.path.startswith('/vercel_api/'):
            self.do_vercel_proxy('DELETE')
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/vercel_api/'):
            self.do_vercel_proxy('GET')
            return
            
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
            gh_user = os.environ.get("GITHUB_DEFAULT_USER", "")
            vercel_token = os.environ.get("VERCEL_DEFAULT_TOKEN", "")
            fb_api_key = os.environ.get("FIREBASE_API_KEY", "")
            fb_auth_domain = os.environ.get("FIREBASE_AUTH_DOMAIN", "")
            fb_project_id = os.environ.get("FIREBASE_PROJECT_ID", "")
            fb_storage_bucket = os.environ.get("FIREBASE_STORAGE_BUCKET", "")
            fb_sender_id = os.environ.get("FIREBASE_MESSAGING_SENDER_ID", "")
            fb_app_id = os.environ.get("FIREBASE_APP_ID", "")
            final_html = (CLOUD_HTML
                .replace('{{GITHUB_TOKEN_PLACEHOLDER}}', gh_token)
                .replace('{{GITHUB_USERNAME_PLACEHOLDER}}', gh_user)
                .replace('{{VERCEL_TOKEN_PLACEHOLDER}}', vercel_token)
                .replace('{{FIREBASE_API_KEY}}', fb_api_key)
                .replace('{{FIREBASE_AUTH_DOMAIN}}', fb_auth_domain)
                .replace('{{FIREBASE_PROJECT_ID}}', fb_project_id)
                .replace('{{FIREBASE_STORAGE_BUCKET}}', fb_storage_bucket)
                .replace('{{FIREBASE_MESSAGING_SENDER_ID}}', fb_sender_id)
                .replace('{{FIREBASE_APP_ID}}', fb_app_id)
            )
            
            self.wfile.write(final_html.encode('utf-8'))
            
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
        if self.path.startswith('/vercel_api/'):
            self.do_vercel_proxy('POST')
            return
            
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/send_message':
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
    httpd = ReusableTCPServer(("localhost", PORT), WebDashboardHandler)
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
            except (ExceptionGroup, Exception) as err:
                if self.audio_stream is not None:
                    try:
                        self.audio_stream.close()
                    except Exception:
                        pass
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
        url='http://localhost:8080',
        js_api=api,
        width=1280, 
        height=800,
        background_color='#050505',
        confirm_close=True
    )
    
    webview.start()