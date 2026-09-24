import re

with open('ap copy.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_cloud_html = r"""CLOUD_HTML = r'''
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

        <!-- Login Section -->
        <div id="loginSection" class="text-center py-5">
            <div class="card p-5 mx-auto" style="max-width: 400px;">
                <i class="bi bi-github mb-3" style="font-size: 3rem;"></i>
                <h4 class="fw-bold mb-3">Connect to GitHub</h4>
                <p class="text-muted mb-4">Connect your account to view and manage your repositories directly from Elivora Cloud.</p>
                <a href="/github/login" target="_blank" class="btn btn-dark w-100 py-2 fw-semibold" onclick="startLoginPolling()">
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

        function checkAuth() {
            const token = localStorage.getItem('github_token');
            if (token) {
                loginSection.classList.add('d-none');
                repoSection.classList.remove('d-none');
                logoutBtn.classList.remove('d-none');
                fetchRepos(token);
                return true;
            } else {
                loginSection.classList.remove('d-none');
                repoSection.classList.add('d-none');
                logoutBtn.classList.add('d-none');
                return false;
            }
        }

        function startLoginPolling() {
            pollInterval = setInterval(() => {
                if (localStorage.getItem('github_token')) {
                    clearInterval(pollInterval);
                    showToast();
                    checkAuth();
                }
            }, 1000);
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
                const response = await fetch('https://api.github.com/user/repos?sort=updated&per_page=100', {
                    headers: { 'Authorization': 'token ' + token, 'Accept': 'application/vnd.github.v3+json' }
                });
                if (!response.ok) {
                    if(response.status === 401) { logout(); return; } 
                    throw new Error('Failed to fetch');
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
            document.getElementById('modalRepoName').textContent = repoFullName;
            document.getElementById('buildCommand').value = '';
            document.getElementById('outputDir').value = '';
            document.getElementById('envVarsContainer').innerHTML = '';
            document.getElementById('deployConsoleWrapper').classList.add('d-none');
            document.getElementById('deployConsole').innerHTML = '';
            
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
                
                const data = await res.json();
                if (res.ok && data.url) {
                    consoleDiv.innerHTML += `<span class="text-success mt-2 d-block">Deployment Successful!</span>`;
                    consoleDiv.innerHTML += `<a href="${data.url}" target="_blank" class="text-primary mt-1 d-block fw-bold">${data.url}</a>`;
                    btn.innerHTML = 'Deployed Successfully';
                } else {
                    consoleDiv.innerHTML += `<span class="text-danger mt-2 d-block">Deployment Failed: ${data.error}</span>`;
                    if(data.logs) {
                        consoleDiv.innerHTML += `<pre class="text-warning mt-2" style="white-space: pre-wrap;">${data.logs}</pre>`;
                    }
                    if(data.trace) {
                        consoleDiv.innerHTML += `<pre class="text-muted mt-2" style="white-space: pre-wrap; font-size: 0.7rem;">${data.trace}</pre>`;
                    }
                    btn.innerHTML = 'Retry Deployment';
                    btn.disabled = false;
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

        // Initialize
        checkAuth();
    </script>
</body>
</html>
'''"""

m = re.search(r'(?s)CLOUD_HTML = r?(\"\"\"|\'\'\')(.*?)(\1)', content)
if m:
    content = content[:m.start()] + new_cloud_html + content[m.end():]
    print("CLOUD_HTML replaced.")

# Add /deploy_vercel to WebDashboardHandler
# We need to find the `def do_POST(self):` block and insert it there.
post_handler = """    def do_POST(self):
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
                
                with tempfile.TemporaryDirectory() as temp_dir:
                    zip_path = os.path.join(temp_dir, 'repo.zip')
                    with urllib.request.urlopen(req) as response, open(zip_path, 'wb') as out_file:
                        shutil.copyfileobj(response, out_file)
                        
                    # Extract
                    extract_dir = os.path.join(temp_dir, 'extracted')
                    os.makedirs(extract_dir, exist_ok=True)
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    
                    # Find extracted subfolder
                    subfolders = os.listdir(extract_dir)
                    repo_dir = os.path.join(extract_dir, subfolders[0]) if subfolders else extract_dir
                    
                    # Generate vercel.json if custom build steps provided
                    vercel_json = {}
                    if build_cmd: vercel_json['buildCommand'] = build_cmd
                    if output_dir: vercel_json['outputDirectory'] = output_dir
                    if vercel_json:
                        with open(os.path.join(repo_dir, 'vercel.json'), 'w') as f:
                            json.dump(vercel_json, f)
                            
                    # Run Vercel CLI via npx
                    vercel_token = os.environ.get("VERCEL_DEFAULT_TOKEN", "")
                    cmd = f'npx vercel deploy --token "{vercel_token}" --yes --prod'
                    
                    for k, v in env_vars.items():
                        cmd += f' --env {k}="{v}" --build-env {k}="{v}"'
                        
                    safe_name = repo_name.split('/')[-1].replace('.', '-')
                    cmd += f' --name {safe_name}'
                    
                    process = subprocess.Popen(cmd, cwd=repo_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True)
                    output, _ = process.communicate()
                    
                    # Look for URL in output
                    url_match = re.search(r'https://[a-zA-Z0-9.-]+\.vercel\.app', output)
                    if url_match:
                        deployed_url = url_match.group(0)
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'url': deployed_url}).encode('utf-8'))
                    else:
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'error': 'Deployment failed', 'logs': output}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e), 'trace': traceback.format_exc()}).encode('utf-8'))
        elif parsed_path.path == '/send_message':"""

content = content.replace("    def do_POST(self):\n        parsed_path = urllib.parse.urlparse(self.path)\n        if parsed_path.path == '/send_message':", post_handler)

with open('ap copy.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated ap copy.py with POST handler!")
