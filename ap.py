







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
</body>
</html>
"""




CLOUD_HTML = """
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ELIVORA AI Platform | Global Serverless</title>
    
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <style>
        /* Force Light Theme Variables */
        :root[data-theme="light"] {
            --bg-main: #f8fafc; --bg-sidebar: #ffffff; --bg-card: #ffffff;
            --text-main: #0f172a; --text-muted: #64748b; --border-color: #e2e8f0;
            --primary: #0f172a; --primary-hover: #334155; --primary-light: #f1f5f9;
            --accent-green: #10b981; --accent-green-light: #d1fae5;
            --warning: #f59e0b; --warning-light: #fef3c7;
            --danger: #ef4444; --danger-light: #fee2e2;
            --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            --modal-bg: rgba(255, 255, 255, 0.85);
            --card-overlay: rgba(255, 255, 255, 0.95);
        }

        body { font-family: 'Inter', sans-serif; background-color: var(--bg-main); color: var(--text-main); transition: background-color 0.3s ease; overflow-x: hidden; }

        #app-container { min-height: 100vh; }
        .sidebar { width: 260px; background: var(--bg-sidebar); border-right: 1px solid var(--border-color); height: 100vh; position: fixed; z-index: 1040; transition: transform 0.3s ease; }
        .main-content { margin-left: 260px; padding: 2rem; min-height: 100vh; transition: margin-left 0.3s ease; }

        .nav-link-custom { color: var(--text-muted); padding: 10px 16px; border-radius: 8px; margin-bottom: 4px; display: flex; align-items: center; gap: 12px; text-decoration: none; font-weight: 500; transition: 0.2s; cursor: pointer; }
        .nav-link-custom:hover, .nav-link-custom.active { background-color: var(--primary-light); color: var(--text-main); font-weight: 600; }

        .saas-card { 
            background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; 
            box-shadow: var(--shadow-sm); transition: transform 0.2s ease, box-shadow 0.2s ease; 
            position: relative; z-index: 1; overflow: hidden; 
            will-change: transform; transform: translateZ(0); 
        }
        .saas-card:hover, .saas-card:focus-within { box-shadow: var(--shadow-md); transform: translateY(-2px) translateZ(0); border-color: var(--text-muted); z-index: 10; }
        
        .repo-card-wrapper { transition: opacity 0.3s ease, transform 0.3s ease; transform-origin: top; }

        .card-process-overlay {
            position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background: var(--card-overlay); backdrop-filter: blur(8px);
            z-index: 20; display: flex; flex-direction: column; align-items: center; justify-content: center;
            opacity: 0; pointer-events: none; transition: opacity 0.2s ease;
        }
        .card-process-overlay.active { opacity: 1; pointer-events: auto; }

        .dropdown-menu { background-color: var(--bg-card); border: 1px solid var(--border-color); box-shadow: var(--shadow-lg); z-index: 1050; padding: 8px; border-radius: 12px; }
        .dropdown-item { color: var(--text-main); border-radius: 6px; font-size: 0.9rem; font-weight: 500; padding: 8px 16px; transition: 0.2s; cursor: pointer; }
        .dropdown-item:hover { background-color: var(--primary-light); color: var(--text-main); }

        .preview-wrapper { 
            width: 100%; height: 160px; border-radius: 8px; overflow: hidden; position: relative; 
            margin-bottom: 1rem; display: flex; align-items: center; justify-content: center;
            cursor: pointer; transition: opacity 0.2s ease;
            box-shadow: inset 0 0 0 1px rgba(0,0,0,0.05);
        }
        .preview-wrapper:hover { opacity: 0.9; }
        .preview-iframe { width: 400%; height: 400%; transform: scale(0.25); transform-origin: top left; border: none; outline: none; position: absolute; top: 0; left: 0; background: #ffffff; pointer-events: none; }
        .preview-shield { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 5; background: transparent; cursor: pointer; }

        .status-badge { padding: 4px 10px; font-size: 0.75rem; font-weight: 600; border-radius: 50px; display: inline-flex; align-items: center; gap: 6px; letter-spacing: 0.5px; }
        .status-badge.live { background: var(--accent-green-light); color: var(--accent-green); }
        .status-badge.paused { background: var(--warning-light); color: var(--warning); }
        .status-dot { width: 6px; height: 6px; border-radius: 50%; }
        .live .status-dot { background: var(--accent-green); box-shadow: 0 0 6px var(--accent-green); }
        .paused .status-dot { background: var(--warning); }

        .form-control-custom { background: var(--bg-main); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 8px; padding: 10px 16px; width: 100%; transition: 0.2s; }
        .form-control-custom:focus { outline: none; border-color: var(--text-main); box-shadow: 0 0 0 3px var(--primary-light); }
        .btn-primary-custom { background: var(--primary); color: var(--bg-card); border: none; padding: 10px 20px; border-radius: 8px; font-weight: 500; transition: transform 0.2s; }
        
        .upload-zone { border: 2px dashed var(--border-color); border-radius: 12px; padding: 40px; text-align: center; background: var(--bg-main); cursor: pointer; transition: 0.2s; }
        .upload-zone:hover { border-color: var(--text-main); background: var(--primary-light); }

        .view-section { display: none; animation: fadeIn 0.3s ease; }
        .view-section.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

        .elivora-overlay { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: var(--modal-bg); backdrop-filter: blur(5px); z-index: 2000; display: flex; align-items: center; justify-content: center; opacity: 0; pointer-events: none; transition: opacity 0.3s ease; }
        .elivora-overlay.active { opacity: 1; pointer-events: auto; }
        .elivora-modal { background: var(--bg-card); width: 100%; max-width: 480px; border-radius: 16px; border: 1px solid var(--border-color); box-shadow: var(--shadow-lg); transform: translateY(20px) scale(0.95); transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
        .elivora-overlay.active .elivora-modal { transform: translateY(0) scale(1); }

        @keyframes subtlePulse { 0% { opacity: 0.3; } 50% { opacity: 1; } 100% { opacity: 0.3; } }
        .sync-indicator { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent-green); margin-left: 8px; animation: subtlePulse 2s infinite; }

        @media (max-width: 991px) {
            .sidebar { transform: translateX(-100%); box-shadow: var(--shadow-md); }
            .sidebar.open { transform: translateX(0); }
            .main-content { margin-left: 0; padding: 1rem; }
            .sidebar-overlay { display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.5); z-index: 1030; }
            .sidebar-overlay.show { display: block; }
        }
    </style>
</head>
<body>
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
                <textarea id="pauseCustomHtmlCode" class="form-control-custom font-monospace text-muted small" rows="5" placeholder="&lt;html&gt;&lt;body&gt;&lt;h1&gt;We are updating!&lt;/h1&gt;&lt;/body&gt;&lt;/html&gt;"></textarea>
            </div>
            <div class="d-flex gap-2 justify-content-end mt-4">
                <button class="btn border form-control-custom w-auto bg-transparent text-main" onclick="closeModals()">Cancel</button>
                <button class="btn btn-warning text-dark fw-bold px-4 border-0" onclick="executeGlobalPause()">Apply Maintenance</button>
            </div>
        </div>
    </div>

    <div class="elivora-overlay" id="renameModalOverlay">
        <div class="elivora-modal p-4 p-md-5">
            <h4 class="fw-bold text-main mb-2"><i class="bi bi-input-cursor-text text-primary me-2"></i>Rename Website</h4>
            <p class="text-muted small mb-4">This will change the repository name and your GitHub Pages URL.</p>
            <input type="hidden" id="renameOldName">
            <div class="mb-4">
                <label class="form-label small fw-bold text-main">NEW PROJECT ALIAS</label>
                <div class="d-flex border rounded border-color overflow-hidden">
                    <span class="px-3 py-2 bg-main text-muted border-end border-color">github.io/</span>
                    <input type="text" id="renameNewName" class="form-control border-0 shadow-none bg-card text-main" placeholder="new-name">
                </div>
            </div>
            <div class="d-flex gap-2 justify-content-end mt-4">
                <button class="btn border form-control-custom w-auto bg-transparent text-main" onclick="closeModals()">Cancel</button>
                <button class="btn btn-primary-custom" onclick="executeRename()">Save Name</button>
            </div>
        </div>
    </div>

    <div id="app-container">
        <div class="sidebar-overlay" onclick="toggleSidebar()"></div>

        <nav class="sidebar d-flex flex-column p-3">
            <div class="d-flex align-items-center justify-content-between mb-4 px-2 mt-2">
                <h4 class="fw-bold mb-0 text-main d-flex align-items-center gap-2">
                    <div class="bg-primary rounded text-white d-flex align-items-center justify-content-center" style="width:30px; height:30px;"><i class="bi bi-layers-fill fs-6"></i></div>
                    ELIVORA AI
                </h4>
                <button class="btn d-lg-none text-main border-0 p-1" onclick="toggleSidebar()"><i class="bi bi-x-lg"></i></button>
            </div>
            <div class="d-flex flex-column gap-1 flex-grow-1">
                <span class="text-muted small fw-bold px-2 mt-2 mb-1" style="font-size: 0.7rem;">PLATFORM</span>
                <a class="nav-link-custom" onclick="switchView('dashboard', this)"><i class="bi bi-grid"></i> Overview</a>
                <a class="nav-link-custom active" onclick="switchView('analytics', this)"><i class="bi bi-bar-chart"></i> Analytics</a>
                <a class="nav-link-custom" onclick="switchView('deploy', this)"><i class="bi bi-cloud-arrow-up"></i> Deployments</a>
                <span class="text-muted small fw-bold px-2 mt-4 mb-1" style="font-size: 0.7rem;">CONFIGURATION</span>
                <a class="nav-link-custom" onclick="switchView('settings', this)"><i class="bi bi-key"></i> API Config</a>
                <span class="text-muted small fw-bold px-2 mt-4 mb-1" style="font-size: 0.7rem;">SYSTEM</span>
                <a href="/" class="nav-link-custom text-primary"><i class="bi bi-arrow-left-circle"></i> Back to Hub</a>
            </div>
        </nav>

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

            <section id="dashboard" class="view-section">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h5 class="fw-bold text-main m-0 d-none d-md-block">Deployed Websites</h5>
                    <div class="position-relative w-100 max-w-300" style="max-width: 300px;">
                        <i class="bi bi-search position-absolute top-50 translate-middle-y ms-3 text-muted"></i>
                        <input type="text" class="form-control-custom ps-5" id="searchInput" placeholder="Search..." onkeyup="filterProjects()">
                    </div>
                </div>
                <div class="row g-4" id="projectGrid"></div>
            </section>

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
                    <h5 class="fw-bold text-main mb-3">Deployment Velocity</h5>
                    <p class="text-muted small mb-4">Visual tracking of your repository creation over the past week.</p>
                    <div style="position: relative; height: 300px; width: 100%;">
                        <canvas id="analyticsChart"></canvas>
                    </div>
                </div>
            </section>

            <section id="deploy" class="view-section">
                <div class="row justify-content-center">
                    <div class="col-12 col-lg-8 col-xl-6">
                        <div class="saas-card p-4 p-md-5">
                            <h4 class="fw-bold text-main mb-1">Deploy new project</h4>
                            <p class="text-muted mb-4">Upload your .zip file containing HTML/CSS/JS.</p>
                            <div class="mb-4">
                                <label class="form-label small fw-bold text-main">PROJECT ALIAS</label>
                                <div class="d-flex border rounded border-color overflow-hidden">
                                    <span class="px-3 py-2 bg-main text-muted border-end border-color d-none d-sm-block">github.io/</span>
                                    <input type="text" id="projectName" class="form-control border-0 shadow-none bg-card text-main" placeholder="my-website">
                                </div>
                            </div>
                            <div class="upload-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
                                <i class="bi bi-folder-zip fs-1 text-primary mb-2 d-block"></i>
                                <h5 class="fw-bold text-main">Drag & Drop .zip</h5>
                                <p class="text-muted small mb-1">Processed instantly in your browser</p>
                                <p class="text-warning small fw-bold mb-0">Note: Main pg should have file name as index.html</p>
                                <input type="file" id="fileInput" accept=".zip" class="d-none">
                            </div>
                            <div id="progressContainer" class="mt-4 p-3 border rounded bg-main d-none">
                                <div class="d-flex justify-content-between mb-2">
                                    <span class="fw-bold text-main" id="statusText">Extracting files...</span>
                                    <span class="fw-bold text-primary" id="progressText">0%</span>
                                </div>
                                <div class="progress" style="height: 6px;">
                                    <div class="progress-bar bg-primary progress-bar-striped progress-bar-animated" id="progressBar" style="width: 0%; transition: 0.1s linear;"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            <section id="settings" class="view-section">
                <div class="row justify-content-center">
                    <div class="col-12 col-lg-8">
                        <div class="saas-card p-4 p-md-5">
                            <h5 class="fw-bold text-main mb-3">GitHub API Configuration</h5>
                            <div class="mb-3">
                                <label class="form-label small fw-bold text-main">GITHUB USERNAME</label>
                                <input type="text" id="cfgUsername" class="form-control-custom" placeholder="e.g. ELIVORA">
                            </div>
                            <div class="mb-4">
                                <label class="form-label small fw-bold text-main">PERSONAL ACCESS TOKEN (PAT)</label>
                                <input type="password" id="cfgToken" class="form-control-custom" placeholder="ghp_xxxxxxxxxxxxxxxxx">
                                <div class="form-text mt-1">Requires 'repo' and 'delete_repo' scope.</div>
                            </div>
                            <button class="btn btn-primary-custom w-100" onclick="saveConfig()">Save Configuration</button>
                        </div>
                    </div>
                </div>
            </section>
        </main>
    </div>

    <div class="toast-container position-fixed bottom-0 end-0 p-3" style="z-index: 9999" id="toastContainer"></div>

    <script>
        const DEFAULT_USERNAME = 'ELIVORA';
        const DEFAULT_TOKEN = '{{GITHUB_TOKEN_PLACEHOLDER}}';

        const CONFIG = { 
            USERNAME: localStorage.getItem('elivora_gh_user') || DEFAULT_USERNAME, 
            TOKEN: localStorage.getItem('elivora_gh_token') || DEFAULT_TOKEN 
        };
        
        let projects = [];
        let chartInstance = null;
        let activeCardIntervals = {};
        let repoToDelete = "";
        let localStatuses = JSON.parse(localStorage.getItem('elivora_local_status') || '{}');
        let activeDeployments = new Set(); // Protects active countdown cards from background sync wipes

        document.addEventListener('DOMContentLoaded', () => {
            initTheme();
            document.getElementById('cfgUsername').value = CONFIG.USERNAME; 
            document.getElementById('cfgToken').value = CONFIG.TOKEN;
            
            if(CONFIG.TOKEN) { 
                loadDeployments(); 
                setInterval(backgroundPingSync, 15000); 
            } else { 
                switchView('settings', document.querySelectorAll('.nav-link-custom')[3]); 
                showToast("Please enter API details first.", "warning"); 
            }
        });

        async function ghFetch(endpoint, options = {}) {
            const url = `https://api.github.com${endpoint}`;
            const headers = { 'Authorization': `token ${CONFIG.TOKEN}`, 'Accept': 'application/vnd.github.v3+json', 'Content-Type': 'application/json', ...options.headers };
            const response = await fetch(url, { ...options, headers });
            if (!response.ok) { const err = await response.json().catch(()=>({})); throw new Error(err.message || `API Error: ${response.status}`); }
            return response.status !== 204 ? await response.json().catch(()=>({})) : null;
        }

        function saveConfig() {
            CONFIG.USERNAME = document.getElementById('cfgUsername').value.trim(); 
            CONFIG.TOKEN = document.getElementById('cfgToken').value.trim();
            localStorage.setItem('elivora_gh_user', CONFIG.USERNAME); 
            localStorage.setItem('elivora_gh_token', CONFIG.TOKEN);
            showToast("Credentials saved.", "success"); 
            location.reload();
        }

        async function loadDeployments() {
            const grid = document.getElementById('projectGrid');
            grid.innerHTML = `<div class="col-12 text-center py-5"><div class="spinner-border text-primary"></div><p class="text-muted mt-2">Fetching repos...</p></div>`;
            try {
                const repos = await ghFetch(`/user/repos?affiliation=owner&sort=created&direction=desc&per_page=100`);
                projects = repos.map(repo => {
                    const savedState = localStatuses[repo.name] || { status: 'live', reason: '' };
                    return { id: repo.name, url: `https://${CONFIG.USERNAME}.github.io/${repo.name}/`, github: repo.html_url, date: repo.created_at, status: savedState.status, reason: savedState.reason };
                });
                renderProjects(); 
                renderAnalytics();
            } catch (err) { 
                grid.innerHTML = `<div class="col-12 text-center py-5 text-danger"><i class="bi bi-wifi-off fs-1"></i><p>Connection Error. Check API Token.</p></div>`; 
            }
        }

        async function backgroundPingSync() {
            if(!CONFIG.TOKEN) return;
            try {
                const repos = await ghFetch(`/user/repos?affiliation=owner&sort=created&direction=desc&per_page=100`);
                if(!repos) return;
                
                const fetchedIds = repos.map(r => r.name);
                const existingIds = projects.map(p => p.id);
                let changed = false;

                projects.forEach(p => {
                    // Check if repo was deleted remotely AND is not currently protected by an active local process
                    if(!fetchedIds.includes(p.id) && !activeDeployments.has(p.id)) {
                        const card = document.getElementById(`repo-card-${p.id}`);
                        if(card) { card.style.opacity = '0'; card.style.transform = 'scale(0.8)'; setTimeout(() => card.remove(), 300); }
                        changed = true;
                    }
                });
                
                // Preserve protected repos in the data array
                projects = projects.filter(p => fetchedIds.includes(p.id) || activeDeployments.has(p.id));

                const grid = document.getElementById('projectGrid');
                repos.forEach(repo => {
                    if(!existingIds.includes(repo.name)) {
                        const newP = { id: repo.name, url: `https://${CONFIG.USERNAME}.github.io/${repo.name}/`, github: repo.html_url, date: repo.created_at, status: 'live' };
                        projects.unshift(newP); 
                        const tempDiv = document.createElement('div'); tempDiv.innerHTML = generateCardHTML(newP);
                        const newCard = tempDiv.firstElementChild;
                        newCard.style.opacity = '0'; newCard.style.transform = 'scale(0.8)';
                        grid.insertBefore(newCard, grid.firstChild);
                        void newCard.offsetWidth; newCard.style.opacity = '1'; newCard.style.transform = 'scale(1)';
                        changed = true;
                    }
                });
                if(changed) renderAnalytics();
            } catch(e) {}
        }

        function generateCardHTML(p) {
            const cacheBuster = new Date().getTime();
            const isLive = p.status === 'live';
            
            let previewHTML = '';
            if(isLive) {
                previewHTML = `
                    <iframe src="${p.url}?t=${cacheBuster}" class="preview-iframe" scrolling="no" loading="lazy" sandbox="allow-scripts allow-same-origin"></iframe>
                    <div class="preview-shield" onclick="window.open('${p.url}', '_blank')"></div>
                `;
            } else {
                previewHTML = `
                <div class="w-100 h-100 d-flex flex-column align-items-center justify-content-center bg-dark text-white p-3 text-center">
                    <i class="bi bi-tools fs-2 mb-2 text-warning"></i>
                    <span class="fw-bold small text-uppercase text-warning">Maintenance Active</span>
                    <span class="small mt-1 fst-italic text-truncate w-100 px-2 text-muted" style="font-size:0.75rem;">"${p.reason || 'Under update'}"</span>
                </div>`;
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
                                <div class="progress" style="height: 6px;">
                                    <div class="progress-bar bg-primary progress-bar-striped progress-bar-animated" id="process-bar-${p.id}" style="width: 0%; transition: 0.1s linear;"></div>
                                </div>
                            </div>
                        </div>

                        <div class="preview-wrapper">${previewHTML}</div>
                        <div class="d-flex justify-content-between align-items-start mb-2 mt-1">
                            <h5 class="fw-bold mb-0 text-truncate text-main" title="${p.id}">${p.id}</h5>
                            <span class="status-badge ${isLive ? 'live' : 'paused'}"><span class="status-dot"></span> ${isLive ? 'LIVE' : 'UPDATING'}</span>
                        </div>
                        <a href="${isLive ? p.url : '#'}" target="${isLive ? '_blank' : '_self'}" class="text-muted text-decoration-none small mb-3 d-block text-truncate">${p.url.replace('https://', '')}</a>
                        
                        <div class="mt-auto d-flex align-items-center justify-content-between pt-3 border-top border-color">
                            <a href="${p.github}" target="_blank" class="text-main hover-primary"><i class="bi bi-github fs-5"></i></a>
                            <div class="dropdown">
                                <button class="btn border-0 text-muted p-1" data-bs-toggle="dropdown"><i class="bi bi-three-dots-vertical"></i></button>
                                <ul class="dropdown-menu dropdown-menu-end">
                                    <li><button class="dropdown-item" onclick="copyUrl('${p.url}')"><i class="bi bi-clipboard me-2"></i> Copy URL</button></li>
                                    <li><button class="dropdown-item" onclick="window.open('${p.url}', '_blank')"><i class="bi bi-box-arrow-up-right me-2"></i> Open Site</button></li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li><button class="dropdown-item" onclick="openRenameModal('${p.id}')"><i class="bi bi-input-cursor-text me-2"></i> Rename Repo</button></li>
                                    <li><button class="dropdown-item text-warning fw-bold" onclick="openPauseModal('${p.id}')"><i class="bi bi-pause-circle me-2"></i> Global Pause</button></li>
                                    <li><button class="dropdown-item text-success fw-bold" onclick="executeResume('${p.id}')"><i class="bi bi-play-circle me-2"></i> Global Resume</button></li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li><button class="dropdown-item text-danger fw-bold" onclick="promptDeleteModal('${p.id}')"><i class="bi bi-trash3-fill me-2"></i> Delete Repo</button></li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>`;
        }

        function filterProjects() {
            const query = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.repo-card-wrapper').forEach(card => {
                const title = card.getAttribute('data-id').toLowerCase();
                if(title.includes(query)) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        }

        function renderProjects() {
            const grid = document.getElementById('projectGrid');
            if(projects.length === 0) { grid.innerHTML = `<div class="col-12 text-center py-5 text-muted">No repositories found.</div>`; return; }
            grid.innerHTML = projects.map(p => generateCardHTML(p)).join('');
            filterProjects(); 
        }

        function updateCardUI(id) {
            const p = projects.find(x => x.id === id);
            if (!p) return;
            const oldCard = document.getElementById(`repo-card-${id}`);
            if (oldCard) {
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = generateCardHTML(p);
                oldCard.replaceWith(tempDiv.firstElementChild);
            }
        }

        function renderAnalytics() {
            document.getElementById('statTotal').innerText = projects.length;
            const counts = [0,0,0,0,0,0,0]; const labels = []; const today = new Date(); today.setHours(0,0,0,0);
            for (let i = 6; i >= 0; i--) { const d = new Date(today); d.setDate(d.getDate() - i); labels.push(d.toLocaleDateString('en-US', { weekday: 'short' })); }
            let recent = 0;
            projects.forEach(p => {
                const pDate = new Date(p.date); pDate.setHours(0,0,0,0);
                const diffDays = Math.ceil(Math.abs(today - pDate) / (1000 * 60 * 60 * 24));
                if (diffDays < 7) { recent++; counts[6 - diffDays]++; }
            });
            document.getElementById('statRecent').innerText = recent;
            
            const ctx = document.getElementById('analyticsChart').getContext('2d');
            if(chartInstance) {
                chartInstance.data.datasets[0].data = counts;
                chartInstance.data.labels = labels;
                chartInstance.update();
            } else {
                chartInstance = new Chart(ctx, { type: 'line', data: { labels: labels, datasets: [{ label: 'Deployments', data: counts, borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true, tension: 0.4 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } }, x: { grid: { display: false } } } } });
            }
        }

        function startCardProcess(id, title) {
            const overlay = document.getElementById(`process-overlay-${id}`);
            if (!overlay) return;
            overlay.classList.add('active');
            
            const titleEl = document.getElementById(`process-title-${id}`);
            const pBar = document.getElementById(`process-bar-${id}`);
            const pText = document.getElementById(`process-text-${id}`);
            const spinner = document.getElementById(`process-spinner-${id}`);
            
            titleEl.innerText = title;
            spinner.className = 'spinner-border text-primary mb-2';
            pBar.className = 'progress-bar bg-primary progress-bar-striped progress-bar-animated';
            pBar.style.width = '0%';
            pText.innerText = '0%';
            pText.className = 'small fw-bold text-primary';

            let p = 0;
            activeCardIntervals[id] = setInterval(() => {
                p += Math.random() * 15; if (p > 85) p = 85;
                pBar.style.width = `${p}%`; pText.innerText = `${Math.floor(p)}%`;
            }, 150);
        }

        function finishCardProcess(id, successTitle, isDelete = false) {
            clearInterval(activeCardIntervals[id]);
            const overlay = document.getElementById(`process-overlay-${id}`);
            if (!overlay) return;

            const titleEl = document.getElementById(`process-title-${id}`);
            const pBar = document.getElementById(`process-bar-${id}`);
            const pText = document.getElementById('process-text-' + id);
            const spinner = document.getElementById(`process-spinner-${id}`);

            pBar.style.width = '100%'; pText.innerText = '100%';
            pBar.classList.replace('bg-primary', 'bg-success');
            pBar.classList.remove('progress-bar-animated');
            pText.classList.replace('text-primary', 'text-success');
            
            spinner.className = 'bi bi-check-circle-fill text-success fs-1 mb-1';
            titleEl.innerText = successTitle;

            setTimeout(() => {
                overlay.classList.remove('active');
                if (isDelete) {
                    const card = document.getElementById(`repo-card-${id}`);
                    if (card) { card.style.opacity = '0'; card.style.transform = 'scale(0.8)'; setTimeout(() => card.remove(), 400); }
                } else {
                    updateCardUI(id); 
                }
            }, 1500);
        }

        function runDeploymentCountdown(id, titleText, callback) {
            let overlay = document.getElementById(`process-overlay-${id}`);
            if (!overlay) return;
            overlay.classList.add('active');
            
            let titleEl = document.getElementById(`process-title-${id}`);
            let pBar = document.getElementById(`process-bar-${id}`);
            let pText = document.getElementById(`process-text-${id}`);
            let spinner = document.getElementById(`process-spinner-${id}`);
            
            titleEl.innerText = titleText;
            spinner.classList.add('d-none');
            
            let countdownEl = document.getElementById(`countdown-${id}`);
            if(!countdownEl) {
                countdownEl = document.createElement('div');
                countdownEl.id = `countdown-${id}`;
                countdownEl.className = 'display-1 fw-bold text-primary mb-2';
                spinner.parentNode.insertBefore(countdownEl, spinner);
            }
            countdownEl.classList.remove('d-none');
            
            let timeLeft = 59;
            countdownEl.innerText = timeLeft;
            pBar.style.width = '0%';
            pText.innerText = "Waiting for GitHub servers...";
            
            let interval = setInterval(() => {
                timeLeft--;
                
                // DOM checks included to keep timer ticking flawlessly in the background 
                // even when elements are hidden or recreated.
                let elCount = document.getElementById(`countdown-${id}`);
                let elBar = document.getElementById(`process-bar-${id}`);
                
                if (elCount) elCount.innerText = timeLeft;
                if (elBar) elBar.style.width = `${((59 - timeLeft) / 59) * 100}%`;
                
                if(timeLeft <= 0) {
                    clearInterval(interval);
                    activeDeployments.delete(id); // Clear protection flag so it behaves normally again
                    
                    if(elCount) elCount.classList.add('d-none');
                    let sp = document.getElementById(`process-spinner-${id}`);
                    if(sp) {
                        sp.className = 'bi bi-check-circle-fill text-success fs-1 mb-1';
                        sp.classList.remove('d-none');
                    }
                    
                    let titleOut = document.getElementById(`process-title-${id}`);
                    if (titleOut) titleOut.innerText = "Complete!";
                    
                    if (elBar) elBar.classList.replace('bg-primary', 'bg-success');
                    
                    let txtOut = document.getElementById(`process-text-${id}`);
                    if (txtOut) txtOut.innerText = "Reloading Platform...";
                    
                    setTimeout(() => {
                        if(callback) callback();
                        else location.reload();
                    }, 1000);
                }
            }, 1000);
        }

        async function forceDeleteRepo(id) {
            try {
                await ghFetch(`/repos/${CONFIG.USERNAME}/${id}`, { method: 'DELETE' });
            } catch(e) {
                console.log("Force clear context trace protection loop active.");
            }
            
            projects = projects.filter(p => p.id !== id);
            delete localStatuses[id];
            localStorage.setItem('elivora_local_status', JSON.stringify(localStatuses));
            renderAnalytics();
            
            const card = document.getElementById(`repo-card-${id}`);
            if(card) {
                card.style.opacity = '0';
                card.style.transform = 'scale(0.8)';
                setTimeout(() => card.remove(), 300);
            }
            showToast("Force cleared.", "success");
        }

        function failCardProcess(id, errorMsg) {
            clearInterval(activeCardIntervals[id]);
            const overlay = document.getElementById(`process-overlay-${id}`);
            if (!overlay) return;

            const titleEl = document.getElementById(`process-title-${id}`);
            const pBar = document.getElementById(`process-bar-${id}`);
            const pText = document.getElementById(`process-text-${id}`);
            const spinner = document.getElementById(`process-spinner-${id}`);

            pBar.classList.replace('bg-primary', 'bg-danger');
            pBar.classList.remove('progress-bar-animated');
            pText.classList.replace('text-primary', 'text-danger');
            
            spinner.className = 'bi bi-x-circle-fill text-danger fs-1 mb-1';
            spinner.classList.remove('d-none');
            titleEl.innerText = "Failed";
            
            let countdownEl = document.getElementById(`countdown-${id}`);
            if(countdownEl) countdownEl.classList.add('d-none');

            let actionDiv = document.getElementById(`process-actions-${id}`);
            if(!actionDiv) {
                actionDiv = document.createElement('div');
                actionDiv.id = `process-actions-${id}`;
                actionDiv.className = "w-100 px-3 mt-3 d-flex gap-2";
                actionDiv.innerHTML = `
                    <button class="btn btn-sm btn-outline-secondary w-50 fw-bold" style="font-size: 0.75rem;" onclick="document.getElementById('process-overlay-${id}').classList.remove('active')">Dismiss</button>
                    <button class="btn btn-sm btn-danger w-50 fw-bold" style="font-size: 0.75rem;" onclick="forceDeleteRepo('${id}')">Force Delete</button>
                `;
                overlay.appendChild(actionDiv);
            }
            
            showToast(errorMsg || "Process failed.", 'error');
        }

        function promptDeleteModal(id) {
            repoToDelete = id; document.getElementById('confirmDeleteName').innerText = id;
            document.getElementById('confirmDeleteOverlay').classList.add('active');
        }

        async function executeConfirmedDelete() {
            closeModals(); 
            activeDeployments.add(repoToDelete); // Protect from being wiped while the countdown runs
            
            try {
                await ghFetch(`/repos/${CONFIG.USERNAME}/${repoToDelete}`, { method: 'DELETE' });
                
                projects = projects.filter(p => p.id !== repoToDelete);
                delete localStatuses[repoToDelete];
                localStorage.setItem('elivora_local_status', JSON.stringify(localStatuses));
                
                runDeploymentCountdown(repoToDelete, "Destroying Server...", () => {
                    location.reload(); 
                });

            } catch (err) { 
                failCardProcess(repoToDelete, "API Error: Check 'delete_repo' token scope."); 
            }
        }

        function openRenameModal(oldName) { 
            document.getElementById('renameOldName').value = oldName; 
            document.getElementById('renameNewName').value = oldName; 
            document.getElementById('renameModalOverlay').classList.add('active'); 
        }
        
        async function executeRename() {
            const oldName = document.getElementById('renameOldName').value; 
            const newName = document.getElementById('renameNewName').value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-');
            if(!newName || oldName === newName) return closeModals();
            
            closeModals(); 
            startCardProcess(oldName, 'Renaming...');
            try { 
                await ghFetch(`/repos/${CONFIG.USERNAME}/${oldName}`, { method: 'PATCH', body: JSON.stringify({ name: newName }) }); 
                
                const proj = projects.find(x => x.id === oldName);
                if(proj) {
                    proj.id = newName; 
                    proj.url = `https://${CONFIG.USERNAME}.github.io/${newName}/`;
                    if(localStatuses[oldName]) { 
                        localStatuses[newName] = localStatuses[oldName]; 
                        delete localStatuses[oldName]; 
                        localStorage.setItem('elivora_local_status', JSON.stringify(localStatuses)); 
                    }
                }
                
                finishCardProcess(oldName, 'Renamed'); 
            } catch (err) { failCardProcess(oldName, err.message); }
        }

        function toggleCustomHtml() {
            const isChecked = document.getElementById('useCustomHtmlToggle').checked;
            document.getElementById('standardPauseInput').classList.toggle('d-none', isChecked);
            document.getElementById('customPauseInput').classList.toggle('d-none', !isChecked);
        }

        function openPauseModal(id) { 
            document.getElementById('pauseProjectId').value = id; 
            document.getElementById('pauseReasonInput').value = ''; 
            document.getElementById('pauseCustomHtmlCode').value = ''; 
            document.getElementById('useCustomHtmlToggle').checked = false; 
            toggleCustomHtml(); 
            document.getElementById('pauseModalOverlay').classList.add('active'); 
        }

        async function executeGlobalPause() {
            const id = document.getElementById('pauseProjectId').value;
            const isCustom = document.getElementById('useCustomHtmlToggle').checked;
            let msg = '';
            
            let maintenanceHTML = "";
            const endTags = "</" + "body></" + "html>"; 
            
            if (isCustom) {
                msg = 'Custom HTML Maintenance';
                maintenanceHTML = btoa(unescape(encodeURIComponent(document.getElementById('pauseCustomHtmlCode').value.trim() || '<h1>Maintenance</h1>')));
            } else {
                msg = document.getElementById('pauseReasonInput').value.trim() || 'Site is undergoing maintenance.';
                maintenanceHTML = btoa(unescape(encodeURIComponent(`<html><body style="font-family:sans-serif; text-align:center; padding:10%; background:#111; color:#fff;"><h2>Maintenance Mode</h2><p style="color:#aaa;">${msg}</p>${endTags}`)));
            }

            closeModals(); 
            startCardProcess(id, 'Pausing Global Site...');
            
            try {
                let currentFile = null;
                try { currentFile = await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/index.html`); } catch(e) {}
                
                if (currentFile) {
                    let backupExists = false;
                    try { await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/elivora_backup.html`); backupExists = true; } catch(e) {}
                    if(!backupExists) { await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/elivora_backup.html`, { method: 'PUT', body: JSON.stringify({ message: "ELIVORA AI Pause Backup", content: currentFile.content }) }); }
                }
                
                await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/index.html`, { method: 'PUT', body: JSON.stringify({ message: "Apply Maintenance Page", content: maintenanceHTML, sha: currentFile ? currentFile.sha : undefined }) });
                
                localStatuses[id] = { status: 'paused', reason: msg };
                localStorage.setItem('elivora_local_status', JSON.stringify(localStatuses));
                const proj = projects.find(x => x.id === id); if(proj) { proj.status = 'paused'; proj.reason = msg; }
                
                finishCardProcess(id, 'Paused Successfully');
            } catch (err) { failCardProcess(id, err.message || 'Could not modify repository files.'); }
        }

        async function executeResume(id) {
            startCardProcess(id, 'Resuming Site...');
            try {
                let backupFile = null;
                try { backupFile = await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/elivora_backup.html`); } catch(e) {}
                
                let currentMaintenanceFile = null;
                try { currentMaintenanceFile = await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/index.html`); } catch(e) {}
                
                if (backupFile) {
                    await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/index.html`, { method: 'PUT', body: JSON.stringify({ message: "ELIVORA AI Resume", content: backupFile.content, sha: currentMaintenanceFile ? currentMaintenanceFile.sha : undefined }) });
                    await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/elivora_backup.html`, { method: 'DELETE', body: JSON.stringify({ message: "Cleanup Backup", sha: backupFile.sha }) });
                } else if (currentMaintenanceFile) {
                    await ghFetch(`/repos/${CONFIG.USERNAME}/${id}/contents/index.html`, { method: 'DELETE', body: JSON.stringify({ message: "Remove maintenance (No backup found)", sha: currentMaintenanceFile.sha }) });
                }

                localStatuses[id] = { status: 'live', reason: '' };
                localStorage.setItem('elivora_local_status', JSON.stringify(localStatuses));
                const proj = projects.find(x => x.id === id); if(proj) { proj.status = 'live'; proj.reason = ''; }
                
                finishCardProcess(id, 'Resumed Successfully');
            } catch (err) { failCardProcess(id, err.message); }
        }

        function closeModals() { document.querySelectorAll('.elivora-overlay').forEach(el => el.classList.remove('active')); }

        document.getElementById('fileInput').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file || !file.name.endsWith('.zip')) return showToast('Upload a .zip file', 'error');
            if (!CONFIG.TOKEN) return showToast('Set API Token first', 'error');
            
            showToast("Note: Main pg should have file name as index.html", "warning");

            let repoName = document.getElementById('projectName').value.trim() || `project-${Date.now()}`;
            repoName = repoName.toLowerCase().replace(/[^a-z0-9-]/g, '-');

            const progCont = document.getElementById('progressContainer'); const progBar = document.getElementById('progressBar');
            const pText = document.getElementById('progressText');
            document.getElementById('dropZone').classList.add('d-none'); progCont.classList.remove('d-none');

            try {
                document.getElementById('statusText').innerText = 'Creating Repository...';
                await ghFetch('/user/repos', { method: 'POST', body: JSON.stringify({ name: repoName, auto_init: true }) });

                document.getElementById('statusText').innerText = "Extracting & Uploading...";
                const zip = new JSZip(); const loadedZip = await zip.loadAsync(file);
                const filesToUpload = Object.keys(loadedZip.files).filter(k => !loadedZip.files[k].dir);
                
                let commonPrefix = "";
                if (filesToUpload.length > 0) {
                    const firstPathParts = filesToUpload[0].split('/');
                    if (firstPathParts.length > 1) {
                        const potentialPrefix = firstPathParts[0] + '/';
                        const allSharePrefix = filesToUpload.every(f => f.startsWith(potentialPrefix));
                        if (allSharePrefix) {
                            commonPrefix = potentialPrefix;
                        }
                    }
                }
                
                for (let i = 0; i < filesToUpload.length; i++) {
                    const base64Data = await loadedZip.files[filesToUpload[i]].async("base64");
                    
                    let uploadPath = filesToUpload[i];
                    if (commonPrefix && uploadPath.startsWith(commonPrefix)) {
                        uploadPath = uploadPath.substring(commonPrefix.length);
                    }

                    try { 
                        await ghFetch(`/repos/${CONFIG.USERNAME}/${repoName}/contents/${uploadPath}`, { 
                            method: 'PUT', 
                            body: JSON.stringify({ message: `Deploy via ELIVORA AI`, content: base64Data }) 
                        }); 
                    } catch(e) {}
                    
                    const progress = 20 + Math.floor((i / filesToUpload.length) * 70);
                    progBar.style.width = `${progress}%`; pText.innerText = `${progress}%`;
                }

                document.getElementById('statusText').innerText = "Configuring Pages...";
                try { await ghFetch(`/repos/${CONFIG.USERNAME}/${repoName}/pages`, { method: 'POST', body: JSON.stringify({ source: { branch: "main", path: "/" } }), headers: { 'Accept': 'application/vnd.github.switcheroo-preview+json' } }); } catch(e) {}

                progBar.style.width = '100%'; pText.innerText = "100%"; document.getElementById('statusText').innerText = "Push Complete!"; 
                
                progCont.classList.add('d-none'); document.getElementById('dropZone').classList.remove('d-none'); 
                document.getElementById('fileInput').value = ''; document.getElementById('projectName').value = ''; 
                
                // Setup card locally and flag it to protect it from being cleared by the ping sync
                activeDeployments.add(repoName);
                const newP = { id: repoName, url: `https://${CONFIG.USERNAME}.github.io/${repoName}/`, github: `https://github.com/${CONFIG.USERNAME}/${repoName}`, date: new Date().toISOString(), status: 'live' };
                projects.unshift(newP);
                renderProjects();
                switchView('dashboard', document.querySelectorAll('.nav-link-custom')[0]); 

                runDeploymentCountdown(repoName, "Building Live Site...", () => {
                    location.reload();
                });

            } catch (err) { progCont.classList.add('d-none'); document.getElementById('dropZone').classList.remove('d-none'); showToast(err.message, 'error'); }
        });

        function toggleSidebar() { document.querySelector('.sidebar').classList.toggle('open'); document.querySelector('.sidebar-overlay').classList.toggle('show'); }
        function switchView(id, el) { document.querySelectorAll('.view-section').forEach(e => e.classList.remove('active')); document.getElementById(id).classList.add('active'); document.querySelectorAll('.nav-link-custom').forEach(e => e.classList.remove('active')); if(el) el.classList.add('active'); const titles = { 'dashboard': 'Overview', 'analytics': 'Analytics Dashboard', 'deploy': 'New Deployment', 'settings': 'Configuration' }; document.getElementById('pageTitle').innerText = titles[id]; if(window.innerWidth < 992) toggleSidebar(); }
        
        function initTheme() { 
            document.documentElement.setAttribute('data-theme', 'light'); 
        }
        
        function copyUrl(url) { navigator.clipboard.writeText(url); showToast('URL Copied to clipboard', 'success'); }
        function showToast(msg, type='info') { const c = document.getElementById('toastContainer'); const t = document.createElement('div'); t.className = `toast align-items-center text-white bg-${type==='error'?'danger':type==='warning'?'warning':'dark'} border-0 show`; t.innerHTML = `<div class="d-flex"><div class="toast-body">${msg}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`; c.appendChild(t); setTimeout(() => t.remove(), 4000); }
    </script>
</body>
</html>
"""
# =====================================================================
# LOCAL WEB SERVER & API HANDLER
# =====================================================================
class WebDashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
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
            final_html = CLOUD_HTML.replace('{{GITHUB_TOKEN_PLACEHOLDER}}', gh_token)
            
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
        url='http://127.0.0.1:8080',
        js_api=api,
        width=1280, 
        height=800,
        background_color='#050505',
        confirm_close=True
    )
    
    webview.start()