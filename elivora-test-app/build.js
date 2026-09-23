const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, 'dist');
if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir);
}

// Read env var
const title = process.env.APP_TITLE || 'Elivora Default Title';
const secret = process.env.SECRET_KEY || 'No Secret Provided';

const htmlContent = `
<!DOCTYPE html>
<html>
<head>
    <title>${title}</title>
    <style>
        body { font-family: sans-serif; background: #0f172a; color: white; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1e293b; padding: 2rem; border-radius: 8px; text-align: center; border: 1px solid #334155; }
        .secret { color: #00E5FF; font-family: monospace; font-size: 1.2rem; margin: 1rem 0; padding: 0.5rem; background: rgba(0,229,255,0.1); border-radius: 4px; }
        .footer { margin-top: 2rem; font-size: 0.8rem; color: #94a3b8; }
    </style>
</head>
<body>
    <div class="card">
        <h1>☁️ ${title}</h1>
        <p>This is a custom build generated securely via Vercel CI/CD!</p>
        <div class="secret">Secret Key: ${secret}</div>
    </div>
    <div class="footer">Deployed autonomously by ELIVORA AI</div>
</body>
</html>
`;

fs.writeFileSync(path.join(outDir, 'index.html'), htmlContent);
console.log('Build completed! Output saved to /dist/index.html');
