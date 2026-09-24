import re

with open('ap copy.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add global variable TEMP_GITHUB_TOKEN
if "TEMP_GITHUB_TOKEN = None" not in content:
    content = content.replace("import json\n", "import json\nTEMP_GITHUB_TOKEN = None\n")

# 2. Update /github/callback to save token
callback_patch = """
                    global TEMP_GITHUB_TOKEN
                    TEMP_GITHUB_TOKEN = token
                    
                    # Serve a self-closing HTML page that posts the message to the parent window
                    # and saves to localStorage if possible
                    html_response = f'''
                    <!DOCTYPE html>
                    <html>
                    <head><title>Success</title></head>
                    <body>
                        <script>
                            localStorage.setItem("github_token", "{token}");
                            if (window.opener) {{
                                window.opener.postMessage({{ type: "GITHUB_TOKEN", token: "{token}" }}, "*");
                            }}
                            // Attempt to close the window
                            window.close();
                            // If it fails (e.g. Chrome prevents scripts from closing un-scripted tabs), tell user
                            document.body.innerHTML = "<h3 style='font-family:sans-serif; text-align:center; margin-top:50px; color:#10b981;'>Login Successful! 🎉<br><br><span style='color:#6b7280; font-size:16px;'>You can now safely close this browser tab and return to the Elivora App.</span></h3>";
                        </script>
                    </body>
                    </html>
                    '''"""
content = re.sub(
    r"# Serve a self-closing HTML page.*?</html>\s+'''", 
    callback_patch.strip(), 
    content, 
    flags=re.DOTALL
)

# 3. Add /github/status route
status_route = """
        elif parsed_path.path == '/github/status':
            global TEMP_GITHUB_TOKEN
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"token": TEMP_GITHUB_TOKEN}).encode('utf-8'))
            if TEMP_GITHUB_TOKEN:
                TEMP_GITHUB_TOKEN = None  # Clear it after successful fetch
"""
if "/github/status" not in content:
    content = content.replace("elif parsed_path.path == '/video_feed':", status_route.strip() + "\n\n        elif parsed_path.path == '/video_feed':")

# 4. Update CLOUD_HTML polling and fetch repos URL
cloud_html_updates = [
    (r"const response = await fetch\('https://api\.github\.com/user/repos\?sort=updated&per_page=100'", 
     r"const response = await fetch('https://api.github.com/user/repos?type=all&sort=updated&per_page=100'"),
    (r"function startLoginPolling\(\) \{[\s\S]*?\}", """function startLoginPolling() {
            pollInterval = setInterval(async () => {
                // Check localStorage first
                if (localStorage.getItem('github_token')) {
                    clearInterval(pollInterval);
                    showToast();
                    checkAuth();
                    return;
                }
                
                // Poll backend for token (solves Chrome vs WebView isolated storage issue)
                try {
                    const res = await fetch('/github/status');
                    const data = await res.json();
                    if (data.token) {
                        localStorage.setItem('github_token', data.token);
                        clearInterval(pollInterval);
                        showToast();
                        checkAuth();
                    }
                } catch(e) {}
            }, 1000);
        }""")
]

for old, new in cloud_html_updates:
    content = re.sub(old, new, content)

with open('ap copy.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Auth polling and Repo Fetching patched successfully!")
