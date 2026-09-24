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
        .repo-card:hover { transform: translateY(-3px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); }
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
            <h4 class="fw-bold mb-4"><i class="bi bi-journal-code me-2"></i>Your Repositories</h4>
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

        // Add a message listener to receive token from the OAuth callback window
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
                    if(response.status === 401) { logout(); return; } // Token invalid
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
                            <div class="card h-100 repo-card p-3" onclick="window.open('${repo.html_url}', '_blank')">
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
    # Replace exactly that portion of the content
    new_content = content[:m.start()] + new_cloud_html + content[m.end():]
    with open('ap copy.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Successfully replaced CLOUD_HTML! Old len: {len(content)}, New len: {len(new_content)}")
else:
    print("Could not find CLOUD_HTML to replace.")

