document.addEventListener('DOMContentLoaded', () => {
    let isLoginMode = true;
    
    // Grab all view containers safely
    const views = {
        auth: document.getElementById('auth-view'),
        app: document.getElementById('app-view'),
        dashboard: document.getElementById('dashboard-view'),
        upload: document.getElementById('upload-view')
    };

    function showView(viewName) {
        // Ensure elements exist before trying to hide them
        if (!views.auth || !views.app) return;

        views.auth.classList.add('hidden');
        views.app.classList.add('hidden');
        views.dashboard.classList.add('hidden');
        views.upload.classList.add('hidden');

        if(viewName === 'auth') {
            views.auth.classList.remove('hidden');
        } else {
            views.app.classList.remove('hidden');
            views[viewName].classList.remove('hidden');
        }
    }

    function init() {
        const token = localStorage.getItem('nexus_token');
        if (token) {
            document.getElementById('nav-username').innerText = localStorage.getItem('nexus_user');
            loadProjects();
            showView('dashboard');
        } else {
            showView('auth');
        }
    }

    // --- Auth Logic ---
    const toggleAuthLink = document.getElementById('toggle-auth-link');
    if (toggleAuthLink) {
        toggleAuthLink.addEventListener('click', (e) => {
            e.preventDefault();
            isLoginMode = !isLoginMode;
            document.getElementById('auth-title').innerText = isLoginMode ? "Welcome back" : "Create an account";
            document.getElementById('auth-subtitle').innerText = isLoginMode ? "Enter your details to access your dashboard." : "Start deploying globally in seconds.";
            document.getElementById('auth-submit-btn').innerText = isLoginMode ? "Sign In" : "Sign Up";
            document.getElementById('toggle-auth-msg').innerText = isLoginMode ? "Don't have an account?" : "Already have an account?";
            document.getElementById('toggle-auth-link').innerText = isLoginMode ? "Sign up" : "Log in";
            document.getElementById('auth-error').classList.add('hidden');
            document.getElementById('auth-success').classList.add('hidden');
        });
    }

    const authForm = document.getElementById('auth-form');
    if (authForm) {
        authForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const btn = document.getElementById('auth-submit-btn');
            const errorEl = document.getElementById('auth-error');
            const successEl = document.getElementById('auth-success');
            
            errorEl.classList.add('hidden'); successEl.classList.add('hidden');
            btn.disabled = true; btn.innerText = "Please wait...";

            const formData = new FormData();
            formData.append("username", username);
            formData.append("password", password);

            try {
                const res = await fetch(isLoginMode ? "/api/login" : "/api/signup", { method: "POST", body: formData });
                const data = await res.json();

                if (!res.ok) throw new Error(data.error || "Authentication failed");

                if (!isLoginMode) {
                    document.getElementById('toggle-auth-link').click();
                    successEl.innerText = "Account created! Please sign in.";
                    successEl.classList.remove('hidden');
                } else {
                    localStorage.setItem('nexus_token', data.access_token);
                    localStorage.setItem('nexus_user', data.username);
                    init();
                }
            } catch (err) {
                errorEl.innerText = err.message;
                errorEl.classList.remove('hidden');
            } finally {
                btn.disabled = false;
                btn.innerText = isLoginMode ? "Sign In" : "Sign Up";
            }
        });
    }

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('nexus_token');
            localStorage.removeItem('nexus_user');
            init();
        });
    }

    // --- Dashboard Logic ---
    async function loadProjects() {
        const grid = document.getElementById('projects-grid');
        grid.innerHTML = '<p class="text-muted">Loading...</p>';

        try {
            const res = await fetch('/api/projects', {
                headers: { "Authorization": `Bearer ${localStorage.getItem('nexus_token')}` }
            });
            if (res.status === 401) return document.getElementById('logout-btn').click(); 
            
            const projects = await res.json();
            
            if (projects.length === 0) {
                grid.innerHTML = '<div style="grid-column: 1/-1" class="card p-5 text-center"><h3 class="mb-2">No projects yet</h3><p class="text-muted">Deploy your first website by clicking New Project above.</p></div>';
                return;
            }

            grid.innerHTML = projects.map(p => `
                <div class="project-card" id="card-${p.id}">
                    <div class="project-id">${p.id}</div>
                    <div class="project-date">Deployed ${p.created_at}</div>
                    <div class="project-actions">
                        <a href="${p.url}" target="_blank" class="btn btn-outline">Visit Site</a>
                        <button onclick="deleteProject('${p.id}')" class="btn btn-danger">Delete</button>
                    </div>
                </div>
            `).join('');
        } catch (err) {
            grid.innerHTML = '<p class="alert-box error">Failed to load projects.</p>';
        }
    }

    window.deleteProject = async function(id) {
        if(!confirm(`Delete project ${id}? This cannot be undone.`)) return;
        try {
            const res = await fetch(`/api/projects/${id}`, {
                method: "DELETE",
                headers: { "Authorization": `Bearer ${localStorage.getItem('nexus_token')}` }
            });
            if (!res.ok) throw new Error("Failed to delete");
            document.getElementById(`card-${id}`).remove();
        } catch (err) { alert(err.message); }
    };

    // --- Upload Logic ---
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');

    const showUploadBtn = document.getElementById('show-upload-btn');
    if (showUploadBtn) {
        showUploadBtn.addEventListener('click', () => showView('upload'));
    }

    const cancelUploadBtn = document.getElementById('cancel-upload-btn');
    if (cancelUploadBtn) {
        cancelUploadBtn.addEventListener('click', () => {
            showView('dashboard');
            document.getElementById('upload-error').classList.add('hidden');
            document.getElementById('status-ui').classList.add('hidden');
            uploadZone.classList.remove('hidden');
        });
    }

    if (uploadZone) {
        uploadZone.addEventListener('click', () => fileInput.click());
        uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); });
        uploadZone.addEventListener('drop', (e) => { e.preventDefault(); if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files[0]); });
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => { if (e.target.files.length) handleUpload(e.target.files[0]); });
    }

    function handleUpload(file) {
        const errorUI = document.getElementById('upload-error');
        const statusUI = document.getElementById('status-ui');
        
        if (!file.name.endsWith('.zip')) {
            errorUI.innerText = "Please upload a valid .zip file.";
            return errorUI.classList.remove('hidden');
        }

        uploadZone.classList.add('hidden');
        errorUI.classList.add('hidden');
        statusUI.classList.remove('hidden');
        document.getElementById('progress-fill').style.width = '60%';

        const formData = new FormData();
        formData.append("file", file);

        fetch("/api/upload", {
            method: "POST",
            headers: { "Authorization": `Bearer ${localStorage.getItem('nexus_token')}` },
            body: formData
        })
        .then(async res => {
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Upload failed");
            
            document.getElementById('progress-fill').style.width = '100%';
            document.getElementById('status-text').innerText = "Deployed Successfully!";
            
            setTimeout(() => {
                fileInput.value = "";
                statusUI.classList.add('hidden');
                uploadZone.classList.remove('hidden');
                document.getElementById('status-text').innerText = "Uploading to global edge...";
                document.getElementById('progress-fill').style.width = '0%';
                loadProjects();
                showView('dashboard');
            }, 1000);
        })
        .catch(err => {
            statusUI.classList.add('hidden');
            uploadZone.classList.remove('hidden');
            errorUI.innerText = err.message;
            errorUI.classList.remove('hidden');
            fileInput.value = "";
        });
    }

    // Start App
    init();
});