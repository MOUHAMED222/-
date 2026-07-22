#!/usr/bin/env python3
"""
🚀 MOUHAMED HOSTING PRO - Enterprise Edition
Architecture: Clean, Modular, Secure, High-Performance
UI/UX: Neo Cyber Glassmorphism Dashboard
"""
import os
import sys
import json
import hashlib
import hmac
import secrets
import time
import uuid
import random
import string
import threading
import subprocess
import shutil
import zipfile
import socket
import platform
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file, abort, make_response
)
import psutil
import re
from collections import defaultdict

# ============================================================================
# 🔐 SECURITY & CONFIGURATION
# ============================================================================

# Use bcrypt for password hashing (fallback to hashlib if not installed)
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    # We'll use a simpler hashing with salt for compatibility

# Secret key from environment or generate
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=7)

# Admin credentials (hashed)
ADMIN_USERNAME = "MOUHAMED1234MA"
ADMIN_PASSWORD = "MOUHAMED1234MA"  # This will be hashed on first run

# Defaults
DEFAULT_CPU_LIMIT = 50
DEFAULT_RAM = "2GB"
DEFAULT_DISK = "500GB"
DEFAULT_EXPIRY_DAYS = 30
MAX_UPLOAD_SIZE = 500 * 1024 * 1024
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE

# Paths
USERS_FILE = 'users.json'
BOTS_DIR = 'bots'
LOGS_DIR = 'logs'
CONFIG_FILE = 'config.json'
SECURITY_LOG_FILE = 'security.log'          # 🔐 New: log file for security events

os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ============================================================================
# 🛡️ SECURITY HELPERS (NEW)
# ============================================================================

# Rate limiting storage
RATE_LIMIT_WINDOW = 60  # seconds
LOGIN_RATE_LIMIT = 5
SENSITIVE_RATE_LIMIT = 10
rate_limit_store = defaultdict(list)

def is_rate_limited(ip, key, limit, window):
    """Check if IP exceeds rate limit for given key."""
    store_key = f"{ip}:{key}"
    now = time.time()
    # Clean old entries
    rate_limit_store[store_key] = [t for t in rate_limit_store[store_key] if now - t < window]
    if len(rate_limit_store[store_key]) >= limit:
        return True
    rate_limit_store[store_key].append(now)
    return False

def log_security_event(ip, event, details=''):
    """Log security-related events to a dedicated log file."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] IP: {ip} | Event: {event} | Details: {details}\n"
    try:
        with open(SECURITY_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line)
    except:
        pass

def secure_file_path(server_dir, user_path):
    """
    Sanitize user-provided path to prevent path traversal.
    Returns absolute safe path or None if invalid.
    """
    # Basic checks: disallow '..', absolute paths, or attempts to escape
    if '..' in user_path or user_path.startswith('/') or user_path.startswith('\\'):
        log_security_event(request.remote_addr, 'path_traversal_attempt', f"Path: {user_path}")
        return None
    full_path = os.path.join(server_dir, user_path)
    full_path = os.path.realpath(full_path)
    real_base = os.path.realpath(server_dir)
    if not full_path.startswith(real_base):
        log_security_event(request.remote_addr, 'path_traversal_attempt', f"Path: {user_path} (resolved: {full_path})")
        return None
    return full_path

def safe_error_response(message='An error occurred', status=500, log_details=None):
    """Return a generic error response and log the actual error if provided."""
    if log_details:
        log_security_event(request.remote_addr, 'error', str(log_details))
    return jsonify({'success': False, 'error': message}), status

# ============================================================================
# 📦 CONFIGURATION MANAGEMENT
# ============================================================================

DEFAULT_CONFIG = {
    "project_name": "MOUHAMED HOSTING PRO",
    "project_logo": "⚡",
    "theme": "dark",  # dark / light
    "primary_color": "#0066ff",
    "secondary_color": "#00b4ff",
    "accent_color": "#00e5ff",
    "default_main_file": "main.py",
    "default_requirements_file": "requirements.txt",
    "timezone": "UTC",
    "language": "en"
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        # Ensure all keys exist
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    except:
        return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4)
    except:
        pass

config = load_config()

# ============================================================================
# 🔐 PASSWORD HASHING (FIXED)
# ============================================================================

def hash_password(password):
    if BCRYPT_AVAILABLE:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    else:
        # Fallback to salted SHA-256 (still secure enough)
        salt = secrets.token_hex(16)
        return f"{salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"

def verify_password(password, hashed):
    """
    Verify password against hashed value.
    Supports both bcrypt (starts with $2) and SHA-256 salt format (salt$hash).
    """
    if not hashed:
        return False

    # If bcrypt is available and hash is in bcrypt format, use bcrypt
    if BCRYPT_AVAILABLE and hashed.startswith('$2'):
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except ValueError:
            # If bcrypt fails (e.g., corrupted hash), fall through to SHA-256 check
            pass

    # SHA-256 format with salt: salt$hash
    if '$' in hashed:
        salt, h = hashed.split('$', 1)
        return h == hashlib.sha256((salt + password).encode()).hexdigest()
    else:
        # No salt (plain text) - fallback for legacy, should not happen
        return hashed == password

# ============================================================================
# 👥 USER MANAGEMENT
# ============================================================================

def load_users():
    if not os.path.exists(USERS_FILE):
        default = {
            ADMIN_USERNAME: {
                "password": hash_password(ADMIN_PASSWORD),
                "role": "admin",
                "created": str(datetime.now()),
                "servers": []
            }
        }
        save_users(default)
        return default
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Ensure admin exists and password is hashed
        if ADMIN_USERNAME not in data:
            data[ADMIN_USERNAME] = {
                "password": hash_password(ADMIN_PASSWORD),
                "role": "admin",
                "created": str(datetime.now()),
                "servers": []
            }
            save_users(data)
        else:
            # If admin password is plain text, hash it
            if not data[ADMIN_USERNAME].get('password', '').startswith('$2') and not '$' in data[ADMIN_USERNAME].get('password', ''):
                data[ADMIN_USERNAME]['password'] = hash_password(data[ADMIN_USERNAME]['password'])
                save_users(data)
        return data
    except:
        default = {
            ADMIN_USERNAME: {
                "password": hash_password(ADMIN_PASSWORD),
                "role": "admin",
                "created": str(datetime.now()),
                "servers": []
            }
        }
        save_users(default)
        return default

def save_users(data):
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except:
        pass

def get_user(username):
    users = load_users()
    return users.get(username)

def get_server_for_user(username, server_id):
    user = get_user(username)
    if not user:
        return None
    servers = user.get('servers', [])
    for s in servers:
        if s.get('server_id') == server_id:
            return s
    return None

def update_server_for_user(username, server_id, updates):
    users = load_users()
    if username not in users:
        return False
    servers = users[username].get('servers', [])
    for i, s in enumerate(servers):
        if s.get('server_id') == server_id:
            servers[i].update(updates)
            users[username]['servers'] = servers
            save_users(users)
            return True
    return False

def get_server_dir(server_id):
    path = os.path.join(BOTS_DIR, server_id)
    os.makedirs(path, exist_ok=True)
    return path

def generate_server_id():
    return str(uuid.uuid4())[:8]

# ============================================================================
# 🛡️ SECURITY HELPERS (continued)
# ============================================================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session or session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated

def csrf_protect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ('POST', 'PUT', 'DELETE'):
            token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
            if not token or token != session.get('csrf_token'):
                abort(403, 'CSRF token missing or invalid')
        return f(*args, **kwargs)
    return decorated

def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

# ============================================================================
# 📁 BOT EXECUTION
# ============================================================================

def run_bot(server_id, main_file, requirements_file):
    server_dir = get_server_dir(server_id)
    main_path = os.path.join(server_dir, main_file)
    log_file = os.path.join(server_dir, 'output.log')
    python_exe = sys.executable

    if not os.path.exists(main_path):
        return None, f"ERROR: {main_file} not found!"

    # Clear old log
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
        except:
            open(log_file, 'w').close()

    # Install requirements if file exists
    if requirements_file and requirements_file.strip():
        req_path = os.path.join(server_dir, requirements_file.strip())
        if os.path.exists(req_path):
            with open(req_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            lines = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
            if lines:
                try:
                    subprocess.Popen(
                        [python_exe, '-m', 'pip', 'install', '-r', os.path.abspath(req_path),
                         '--disable-pip-version-check', '--no-warn-script-location'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    ).wait()
                except:
                    pass

    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'

        proc = subprocess.Popen(
            [python_exe, os.path.abspath(main_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=server_dir,
            text=True, encoding='utf-8', errors='replace',
            bufsize=1, env=env, universal_newlines=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )

        def stream_output():
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    for line in iter(proc.stdout.readline, ''):
                        if line:
                            line = line.rstrip('\n\r')
                            if line:
                                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {line}\n")
                                f.flush()
            except:
                pass

        threading.Thread(target=stream_output, daemon=True).start()
        return proc.pid, None

    except Exception as e:
        log_security_event(request.remote_addr, 'bot_start_failed', str(e))  # 🔐 Log error
        return None, str(e)

def stop_bot_process(pid):
    try:
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
        else:
            os.kill(pid, 15)
        return True
    except:
        return False

# ============================================================================
# 🚀 ROUTES - PUBLIC
# ============================================================================

@app.route('/')
def index():
    cfg = load_config()
    return f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{cfg['project_name']}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #0a0a1a;
                --bg-glass: rgba(20,20,40,0.6);
                --text: #f0f0fa;
                --primary: {cfg['primary_color']};
                --secondary: {cfg['secondary_color']};
                --accent: {cfg['accent_color']};
                --border: rgba(255,255,255,0.05);
            }}
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{
                font-family:'Inter',sans-serif;
                background:var(--bg);
                color:var(--text);
                min-height:100vh;
                display:flex;
                align-items:center;
                justify-content:center;
                background-image: radial-gradient(ellipse at 20% 50%, rgba(0,180,255,0.08) 0%, transparent 60%),
                                  radial-gradient(ellipse at 80% 20%, rgba(255,215,0,0.04) 0%, transparent 50%);
                padding:20px;
            }}
            .container {{
                max-width:880px;
                width:100%;
                background:var(--bg-glass);
                backdrop-filter:blur(30px);
                -webkit-backdrop-filter:blur(30px);
                border:1px solid var(--border);
                border-radius:48px;
                padding:60px 50px;
                text-align:center;
                box-shadow:0 40px 80px -20px rgba(0,0,0,0.9), inset 0 1px 0 rgba(255,255,255,0.04);
                transition:0.4s ease;
            }}
            .container:hover {{ border-color:rgba(0,180,255,0.15); }}
            .logo {{
                font-size:3.8rem;
                margin-bottom:6px;
                display:inline-block;
                background:linear-gradient(135deg,var(--secondary),var(--accent));
                -webkit-background-clip:text;
                -webkit-text-fill-color:transparent;
            }}
            h1 {{
                font-size:3.2rem;
                font-weight:900;
                letter-spacing:-0.02em;
                background:linear-gradient(135deg,#ffffff 20%,var(--secondary) 80%);
                -webkit-background-clip:text;
                -webkit-text-fill-color:transparent;
                background-clip:text;
                margin-bottom:8px;
            }}
            .sub {{
                font-size:1.2rem;
                font-weight:300;
                color:rgba(255,255,255,0.4);
                margin-bottom:40px;
                letter-spacing:0.5px;
            }}
            .btn-group {{
                display:flex;
                gap:16px;
                justify-content:center;
                flex-wrap:wrap;
                margin-bottom:45px;
            }}
            .btn {{
                display:inline-flex;
                align-items:center;
                gap:12px;
                padding:16px 40px;
                border-radius:60px;
                font-weight:600;
                font-size:1rem;
                text-decoration:none;
                transition:all 0.3s ease;
                border:none;
                cursor:pointer;
                background:linear-gradient(135deg,var(--primary),var(--secondary));
                color:#fff;
                box-shadow:0 8px 28px rgba(0,102,255,0.25);
            }}
            .btn:hover {{
                transform:translateY(-4px) scale(1.02);
                box-shadow:0 16px 48px rgba(0,102,255,0.35);
            }}
            .btn-outline {{
                background:transparent;
                border:1.5px solid rgba(255,255,255,0.1);
                box-shadow:none;
                color:#d0d0ea;
            }}
            .btn-outline:hover {{
                background:rgba(255,255,255,0.03);
                border-color:rgba(0,180,255,0.4);
            }}
            .features {{
                display:grid;
                grid-template-columns:1fr 1fr;
                gap:12px 24px;
                text-align:left;
                margin-bottom:40px;
            }}
            .features li {{
                list-style:none;
                display:flex;
                align-items:center;
                gap:12px;
                font-size:0.95rem;
                color:rgba(255,255,255,0.6);
                padding:6px 0;
            }}
            .features li::before {{
                content:"◆";
                color:var(--secondary);
                font-weight:700;
                font-size:1.2rem;
            }}
            .footer {{
                font-size:0.8rem;
                color:rgba(255,255,255,0.15);
                border-top:1px solid var(--border);
                padding-top:24px;
                margin-top:8px;
                letter-spacing:0.5px;
            }}
            .footer a {{
                color:var(--secondary);
                text-decoration:none;
                font-weight:500;
                transition:0.2s;
            }}
            .footer a:hover {{ color:var(--accent); }}
            @media (max-width:640px) {{
                .container {{ padding:36px 20px; border-radius:32px; }}
                h1 {{ font-size:2.4rem; }}
                .features {{ grid-template-columns:1fr; gap:6px; }}
                .btn {{ padding:14px 28px; font-size:0.9rem; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">{cfg['project_logo']}</div>
            <h1>{cfg['project_name']}</h1>
            <p class="sub">Premium Bot Hosting Platform</p>
            <div class="btn-group">
                <a href="/login" class="btn">🔐 Login</a>
                <a href="/api/create" class="btn btn-outline">⚡ Create Server</a>
            </div>
            <ul class="features">
                <li>Auto-Restart on Crash</li>
                <li>CPU Rate Limiting</li>
                <li>File Manager & Code Editor</li>
                <li>GitHub Deployment</li>
                <li>Auto Install Requirements</li>
                <li>SSL Ready</li>
                <li>ZIP Upload & Extract</li>
                <li>Password Change</li>
            </ul>
            <div class="footer">
                {cfg['project_name']} v5.0 · Developed by <a href="https://t.me/mouhamed_ma" target="_blank">@mouhamed_ma</a>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # 🔐 Rate limiting for login attempts
        ip = request.remote_addr
        if is_rate_limited(ip, 'login', LOGIN_RATE_LIMIT, RATE_LIMIT_WINDOW):
            log_security_event(ip, 'rate_limit_exceeded', 'Login attempts')
            return "Too many login attempts. Please try again later.", 429

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        users = load_users()

        if username in users and verify_password(password, users[username].get('password', '')):
            session.permanent = True
            session['user'] = username
            session['role'] = users[username].get('role', 'user')
            # Generate CSRF token
            session['csrf_token'] = secrets.token_hex(32)
            # Redirect to appropriate dashboard
            if session['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                # If user has only one server, go directly
                servers = users[username].get('servers', [])
                if len(servers) == 1:
                    server_id = servers[0].get('server_id')
                    session['current_server_id'] = server_id
                    return redirect(url_for('server_home', server_id=server_id))
                return redirect(url_for('admin_dashboard'))  # fallback
        else:
            # 🔐 Log failed login attempt
            log_security_event(ip, 'failed_login', f"Username: {username}")
            return '''
            <!DOCTYPE html>
            <html>
            <head><title>Login Failed</title>
            <style>
                body { background:#0a0a1a; color:#f0f0fa; font-family:'Inter',sans-serif; display:flex; justify-content:center; align-items:center; height:100vh; text-align:center; margin:0; }
                .box { background:rgba(20,20,40,0.8); padding:40px; border-radius:40px; border:1px solid rgba(255,255,255,0.05); backdrop-filter:blur(12px); }
                a { color:#00b4ff; text-decoration:none; font-weight:500; }
            </style>
            </head>
            <body>
            <div class="box">
                <h2 style="font-weight:300;">❌ Invalid credentials</h2>
                <a href="/login">← Try again</a>
            </div>
            </body>
            </html>
            '''

    cfg = load_config()
    return f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login · {cfg['project_name']}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #0a0a1a;
                --bg-glass: rgba(20,20,40,0.7);
                --text: #f0f0fa;
                --primary: {cfg['primary_color']};
                --secondary: {cfg['secondary_color']};
                --border: rgba(255,255,255,0.04);
            }}
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{
                font-family:'Inter',sans-serif;
                background:var(--bg);
                color:var(--text);
                min-height:100vh;
                display:flex;
                align-items:center;
                justify-content:center;
                background-image: radial-gradient(ellipse at 70% 30%, rgba(0,180,255,0.06) 0%, transparent 60%);
                padding:20px;
            }}
            .login-box {{
                max-width:400px;
                width:100%;
                background:var(--bg-glass);
                backdrop-filter:blur(30px);
                -webkit-backdrop-filter:blur(30px);
                border:1px solid var(--border);
                border-radius:48px;
                padding:48px 36px;
                text-align:center;
                box-shadow:0 40px 80px -20px rgba(0,0,0,0.9);
            }}
            h1 {{
                font-size:2.2rem;
                font-weight:800;
                background:linear-gradient(135deg,#ffffff,var(--secondary));
                -webkit-background-clip:text;
                -webkit-text-fill-color:transparent;
                background-clip:text;
                margin-bottom:4px;
            }}
            .sub {{
                color:rgba(255,255,255,0.25);
                font-size:0.9rem;
                margin-bottom:32px;
                font-weight:300;
            }}
            input {{
                width:100%;
                padding:16px 20px;
                margin:8px 0;
                background:rgba(255,255,255,0.03);
                border:1px solid var(--border);
                border-radius:24px;
                color:var(--text);
                font-size:0.95rem;
                transition:0.3s;
                outline:none;
            }}
            input:focus {{
                border-color:var(--primary);
                background:rgba(255,255,255,0.05);
                box-shadow:0 0 0 4px rgba(0,102,255,0.06);
            }}
            input::placeholder {{ color:rgba(255,255,255,0.15); }}
            button {{
                width:100%;
                padding:16px;
                margin-top:22px;
                border:none;
                border-radius:60px;
                background:linear-gradient(135deg,var(--primary),var(--secondary));
                color:#fff;
                font-weight:600;
                font-size:1rem;
                cursor:pointer;
                transition:all 0.3s;
                box-shadow:0 8px 28px rgba(0,102,255,0.2);
            }}
            button:hover {{
                transform:translateY(-3px);
                box-shadow:0 16px 40px rgba(0,102,255,0.3);
            }}
            .link {{ margin-top:24px; color:rgba(255,255,255,0.15); font-size:0.85rem; }}
            .link a {{ color:var(--secondary); text-decoration:none; font-weight:500; }}
        </style>
    </head>
    <body>
        <div class="login-box">
            <h1>🔐 Login</h1>
            <p class="sub">Sign in to your panel</p>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required autofocus>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Continue</button>
            </form>
            <div class="link"><a href="/">← Back to Home</a></div>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============================================================================
# 🧑‍💻 USER DASHBOARD (SERVER VIEW)
# ============================================================================

@app.route('/<server_id>/login', methods=['GET', 'POST'])
def server_login(server_id):
    # This is for direct server login - we keep original functionality
    # Check if server exists
    users = load_users()
    found = False
    for uname, data in users.items():
        if uname == 'admin':
            continue
        for s in data.get('servers', []):
            if s.get('server_id') == server_id:
                found = True
                break
        if found:
            break
    if not found:
        return f"<h1>❌ Server not found</h1><a href='/'>Back to Home</a>"

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        users = load_users()
        for uname, data in users.items():
            if uname == 'admin':
                continue
            for s in data.get('servers', []):
                if s.get('server_id') == server_id:
                    if uname == username and verify_password(password, data.get('password', '')):
                        session.permanent = True
                        session['user'] = uname
                        session['role'] = 'user'
                        session['current_server_id'] = server_id
                        session['csrf_token'] = secrets.token_hex(32)
                        return redirect(url_for('server_home', server_id=server_id))
                    else:
                        # 🔐 Log failed login to specific server
                        log_security_event(request.remote_addr, 'failed_server_login', f"Server: {server_id}, Username: {username}")
                        return "<h1>❌ Invalid credentials!</h1><a href='/'>Back</a>"
        return "<h1>❌ Invalid login!</h1><a href='/'>Back</a>"

    cfg = load_config()
    return f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Server Login · {cfg['project_name']}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #0a0a1a;
                --bg-glass: rgba(20,20,40,0.7);
                --text: #f0f0fa;
                --primary: {cfg['primary_color']};
                --secondary: {cfg['secondary_color']};
                --border: rgba(255,255,255,0.04);
            }}
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{
                font-family:'Inter',sans-serif;
                background:var(--bg);
                color:var(--text);
                min-height:100vh;
                display:flex;
                align-items:center;
                justify-content:center;
                background-image: radial-gradient(ellipse at 30% 70%, rgba(0,180,255,0.06) 0%, transparent 60%);
                padding:20px;
            }}
            .login-box {{
                max-width:400px;
                width:100%;
                background:var(--bg-glass);
                backdrop-filter:blur(30px);
                -webkit-backdrop-filter:blur(30px);
                border:1px solid var(--border);
                border-radius:48px;
                padding:48px 36px;
                text-align:center;
                box-shadow:0 40px 80px -20px rgba(0,0,0,0.9);
            }}
            h1 {{
                font-size:2rem;
                font-weight:800;
                background:linear-gradient(135deg,#ffffff,var(--secondary));
                -webkit-background-clip:text;
                -webkit-text-fill-color:transparent;
                background-clip:text;
                margin-bottom:4px;
            }}
            .server-id {{ color:rgba(255,255,255,0.2); font-size:0.85rem; margin-bottom:28px; }}
            input {{
                width:100%;
                padding:16px 20px;
                margin:8px 0;
                background:rgba(255,255,255,0.03);
                border:1px solid var(--border);
                border-radius:24px;
                color:var(--text);
                font-size:0.95rem;
                transition:0.3s;
                outline:none;
            }}
            input:focus {{
                border-color:var(--primary);
                background:rgba(255,255,255,0.05);
                box-shadow:0 0 0 4px rgba(0,102,255,0.06);
            }}
            input::placeholder {{ color:rgba(255,255,255,0.15); }}
            button {{
                width:100%;
                padding:16px;
                margin-top:22px;
                border:none;
                border-radius:60px;
                background:linear-gradient(135deg,var(--primary),var(--secondary));
                color:#fff;
                font-weight:600;
                font-size:1rem;
                cursor:pointer;
                transition:all 0.3s;
                box-shadow:0 8px 28px rgba(0,102,255,0.2);
            }}
            button:hover {{
                transform:translateY(-3px);
                box-shadow:0 16px 40px rgba(0,102,255,0.3);
            }}
        </style>
    </head>
    <body>
        <div class="login-box">
            <h1>🔐 Server Login</h1>
            <div class="server-id">🆔 {server_id}</div>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
        </div>
    </body>
    </html>
    '''

@app.route('/<server_id>/home')
@login_required
def server_home(server_id):
    if session.get('role') != 'user':
        return redirect(url_for('admin_dashboard'))
    if session.get('current_server_id') != server_id:
        # User may have multiple servers, redirect to admin
        return redirect(url_for('admin_dashboard'))

    # Fetch server data
    user = get_user(session['user'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    server = get_server_for_user(session['user'], server_id)
    if not server:
        session.clear()
        return redirect(url_for('login'))

    # Check expiry
    if server.get('expiry'):
        try:
            exp_date = datetime.strptime(server['expiry'], '%Y-%m-%d %H:%M:%S.%f')
            if datetime.now() > exp_date:
                return "<h1>❌ Server expired</h1><a href='/logout'>Logout</a>"
        except:
            pass

    # Render dashboard with server info
    return render_dashboard(server_id, server)

def render_dashboard(server_id, server_info):
    cfg = load_config()
    user = session['user']
    csrf_token = session.get('csrf_token', '')
    # Build HTML with inline styles and JS (same as before but improved UI)
    # We'll use a compact representation with all features
    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard · {cfg['project_name']}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #0a0a1a;
                --bg-glass: rgba(20,20,40,0.6);
                --bg-card: rgba(20,20,40,0.5);
                --primary: {cfg['primary_color']};
                --secondary: {cfg['secondary_color']};
                --accent: {cfg['accent_color']};
                --text: #f0f0fa;
                --text-dim: rgba(255,255,255,0.5);
                --border: rgba(255,255,255,0.04);
                --shadow: 0 40px 80px -20px rgba(0,0,0,0.9);
                --radius: 32px;
                --radius-sm: 20px;
            }}
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{
                font-family:'Inter',sans-serif;
                background:var(--bg);
                color:var(--text);
                min-height:100vh;
                padding:24px;
                background-image: radial-gradient(ellipse at 80% 20%, rgba(0,180,255,0.04) 0%, transparent 60%);
            }}
            .container {{ max-width:1440px; margin:0 auto; }}
            .header {{
                display:flex;
                justify-content:space-between;
                align-items:center;
                padding:16px 28px;
                background:var(--bg-glass);
                backdrop-filter:blur(16px);
                -webkit-backdrop-filter:blur(16px);
                border:1px solid var(--border);
                border-radius:var(--radius);
                margin-bottom:28px;
                flex-wrap:wrap;
                gap:12px;
            }}
            .header h1 {{
                font-size:1.8rem;
                font-weight:800;
                background:linear-gradient(135deg,var(--primary),var(--secondary));
                -webkit-background-clip:text;
                -webkit-text-fill-color:transparent;
                background-clip:text;
            }}
            .header-actions {{
                display:flex;
                align-items:center;
                gap:14px;
                flex-wrap:wrap;
            }}
            .badge {{
                background:rgba(0,102,255,0.12);
                padding:6px 18px;
                border-radius:60px;
                font-size:0.8rem;
                font-weight:500;
                color:var(--secondary);
                border:1px solid rgba(0,102,255,0.08);
            }}
            .tabs {{
                display:flex;
                gap:2px;
                margin-bottom:24px;
                border-bottom:1px solid var(--border);
                padding-bottom:2px;
                flex-wrap:wrap;
            }}
            .tab {{
                padding:12px 28px;
                border-radius:40px 40px 0 0;
                cursor:pointer;
                transition:0.25s;
                font-weight:500;
                color:rgba(255,255,255,0.35);
                background:transparent;
                border:none;
                font-size:0.95rem;
            }}
            .tab:hover {{ color:#fff; background:rgba(255,255,255,0.02); }}
            .tab.active {{
                color:var(--secondary);
                background:rgba(0,102,255,0.06);
                border-bottom:2px solid var(--secondary);
            }}
            .tab-content {{ display:none; padding:20px 0 24px; }}
            .tab-content.active {{ display:block; animation:fadeIn 0.3s ease; }}
            @keyframes fadeIn {{ from {{ opacity:0; transform:translateY(8px); }} to {{ opacity:1; transform:translateY(0); }} }}
            .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:24px; }}
            .card {{
                background:var(--bg-card);
                backdrop-filter:blur(12px);
                -webkit-backdrop-filter:blur(12px);
                border:1px solid var(--border);
                border-radius:var(--radius);
                padding:24px 28px;
                transition:0.3s;
            }}
            .card:hover {{ border-color:rgba(0,102,255,0.15); }}
            .card h3 {{ color:var(--secondary); font-weight:600; font-size:1.1rem; margin-bottom:16px; }}
            .card p {{ margin:6px 0; opacity:0.6; font-size:0.95rem; }}
            .status-badge {{
                display:inline-block;
                padding:4px 18px;
                border-radius:60px;
                font-weight:600;
                font-size:0.75rem;
                text-transform:uppercase;
                letter-spacing:0.3px;
            }}
            .running {{ background:#00e676; color:#000; }}
            .stopped {{ background:#ff1744; color:#fff; }}
            .btn {{
                padding:8px 24px;
                border:none;
                border-radius:60px;
                font-weight:600;
                cursor:pointer;
                transition:all 0.25s;
                font-size:0.85rem;
                color:#fff;
                display:inline-flex;
                align-items:center;
                gap:6px;
                background:rgba(255,255,255,0.05);
                border:1px solid var(--border);
                text-decoration:none;
            }}
            .btn:hover {{ transform:translateY(-2px); box-shadow:0 12px 32px rgba(0,0,0,0.3); }}
            .btn-start {{ background:#00e676; border-color:#00e676; color:#000; }}
            .btn-stop {{ background:#ff1744; border-color:#ff1744; }}
            .btn-restart {{ background:#ff9100; border-color:#ff9100; }}
            .btn-primary {{ background:linear-gradient(135deg,var(--primary),var(--secondary)); border-color:transparent; }}
            .btn-danger {{ background:#d32f2f; border-color:#d32f2f; }}
            .btn-success {{ background:#00e676; border-color:#00e676; color:#000; }}
            .btn-sm {{ padding:5px 18px; font-size:0.75rem; }}
            .file-manager {{
                background:rgba(0,0,0,0.3);
                border-radius:var(--radius-sm);
                padding:12px;
                max-height:360px;
                overflow-y:auto;
                border:1px solid var(--border);
            }}
            .file-item {{
                display:flex;
                justify-content:space-between;
                align-items:center;
                padding:8px 14px;
                border-bottom:1px solid rgba(255,255,255,0.02);
                cursor:pointer;
                transition:0.15s;
                border-radius:12px;
            }}
            .file-item:hover {{ background:rgba(255,255,255,0.02); }}
            .file-item .name {{ color:var(--secondary); font-weight:500; }}
            .file-item .size {{ opacity:0.4; font-size:0.75rem; }}
            .editor {{
                width:100%;
                height:320px;
                background:rgba(0,0,0,0.4);
                color:#e0e0f0;
                border:1px solid var(--border);
                border-radius:var(--radius-sm);
                padding:16px;
                font-family:'Courier New',monospace;
                font-size:14px;
                resize:vertical;
                outline:none;
            }}
            .editor:focus {{ border-color:var(--primary); box-shadow:0 0 0 4px rgba(0,102,255,0.06); }}
            .log-box {{
                background:rgba(0,0,0,0.3);
                padding:16px;
                border-radius:var(--radius-sm);
                max-height:260px;
                overflow-y:auto;
                font-family:'Courier New',monospace;
                font-size:13px;
                white-space:pre-wrap;
                border:1px solid var(--border);
            }}
            .flex {{
                display:flex;
                gap:12px;
                flex-wrap:wrap;
                align-items:center;
                margin:12px 0;
            }}
            .flex input,.flex select {{
                padding:10px 16px;
                background:rgba(255,255,255,0.03);
                border:1px solid var(--border);
                border-radius:var(--radius-sm);
                color:var(--text);
                font-size:0.9rem;
                outline:none;
                transition:0.2s;
            }}
            .flex input:focus,.flex select:focus {{
                border-color:var(--primary);
                background:rgba(255,255,255,0.05);
            }}
            .flex input::placeholder {{ color:rgba(255,255,255,0.12); }}
            .flex label {{ display:flex; align-items:center; gap:8px; cursor:pointer; font-size:0.9rem; }}
            .password-form {{ max-width:420px; margin:0 auto; }}
            .password-form input {{
                width:100%;
                padding:14px 18px;
                margin:8px 0;
                background:rgba(255,255,255,0.03);
                border:1px solid var(--border);
                border-radius:var(--radius-sm);
                color:var(--text);
                font-size:0.95rem;
                outline:none;
                transition:0.2s;
            }}
            .password-form input:focus {{
                border-color:var(--primary);
                background:rgba(255,255,255,0.05);
            }}
            .settings-group {{
                margin:16px 0;
                padding:16px;
                background:rgba(255,255,255,0.02);
                border-radius:var(--radius-sm);
                border-left:3px solid var(--primary);
            }}
            .settings-group label {{
                display:block;
                margin-bottom:4px;
                font-weight:500;
                color:var(--text-dim);
            }}
            .settings-group input {{
                width:100%;
                padding:10px 16px;
                background:rgba(255,255,255,0.03);
                border:1px solid var(--border);
                border-radius:var(--radius-sm);
                color:var(--text);
                outline:none;
                transition:0.2s;
            }}
            .settings-group input:focus {{
                border-color:var(--primary);
                background:rgba(255,255,255,0.05);
            }}
            .footer {{
                margin-top:48px;
                opacity:0.2;
                text-align:center;
                font-size:0.8rem;
                border-top:1px solid var(--border);
                padding-top:24px;
            }}
            .footer a {{ color:var(--secondary); text-decoration:none; }}
            @media (max-width:768px) {{
                .grid {{ grid-template-columns:1fr; }}
                .header h1 {{ font-size:1.4rem; }}
                .tab {{ padding:8px 18px; font-size:0.85rem; }}
                .container {{ padding:0; }}
            }}
            ::-webkit-scrollbar {{ width:6px; }}
            ::-webkit-scrollbar-track {{ background:transparent; }}
            ::-webkit-scrollbar-thumb {{ background:rgba(0,102,255,0.2); border-radius:10px; }}
            ::-webkit-scrollbar-thumb:hover {{ background:rgba(0,102,255,0.3); }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Server Dashboard</h1>
                <div class="header-actions">
                    <span class="badge">🆔 {server_id}</span>
                    <span class="badge">👤 {user}</span>
                    <a href="/logout" class="btn btn-danger btn-sm" style="text-decoration:none;">🚪 Logout</a>
                </div>
            </div>

            <div class="tabs">
                <button class="tab active" data-tab="overview">📊 Overview</button>
                <button class="tab" data-tab="files">📁 Files</button>
                <button class="tab" data-tab="settings">⚙️ Settings</button>
            </div>

            <div id="tab-overview" class="tab-content active">
                <div class="grid">
                    <div class="card">
                        <h3>📊 Server Info</h3>
                        <p>Status: <span class="status-badge {server_info.get('status','stopped')}">{server_info.get('status','stopped').upper()}</span></p>
                        <p>💾 RAM: {server_info.get('ram','N/A')}</p>
                        <p>💿 Disk: {server_info.get('disk','N/A')}</p>
                        <p>⚡ CPU Limit: {server_info.get('cpu_limit',80)}%</p>
                        <p>📅 Expiry: {server_info.get('expiry','N/A')}</p>
                        <div class="flex" style="margin-top:16px;">
                            <button class="btn btn-start" onclick="startBot()">▶ Start</button>
                            <button class="btn btn-stop" onclick="stopBot()">⏹ Stop</button>
                            <button class="btn btn-restart" onclick="restartBot()">🔄 Restart</button>
                            <button class="btn btn-primary" onclick="installRequirements()">📦 Install</button>
                            <button class="btn btn-primary" onclick="viewLogs()">📋 Logs</button>
                        </div>
                    </div>
                    <div class="card">
                        <h3>📊 Live Stats</h3>
                        <div id="stats">
                            <p>CPU: <span id="stat-cpu">0%</span></p>
                            <p>RAM: <span id="stat-ram">0 MB</span></p>
                            <p>Uptime: <span id="stat-uptime">0s</span></p>
                            <p>Status: <span id="stat-status" class="status-badge stopped">STOPPED</span></p>
                        </div>
                    </div>
                </div>
                <div class="card" style="margin-top:20px;">
                    <h3>📝 Log Output</h3>
                    <div class="log-box" id="logOutput">No logs yet...</div>
                    <div class="flex" style="margin-top:12px;">
                        <button class="btn btn-sm btn-danger" onclick="clearLogs()">🗑 Clear</button>
                        <button class="btn btn-sm btn-primary" onclick="refreshLogs()">🔄 Refresh</button>
                    </div>
                </div>
                <div class="card" style="margin-top:20px;">
                    <h3>⚡ Quick API</h3>
                    <code style="display:block;padding:8px 14px;background:rgba(0,0,0,0.2);border-radius:12px;margin:4px 0;font-size:0.8rem;">POST /api/run/{server_id} - Start</code>
                    <code style="display:block;padding:8px 14px;background:rgba(0,0,0,0.2);border-radius:12px;margin:4px 0;font-size:0.8rem;">POST /api/stop/{server_id} - Stop</code>
                    <code style="display:block;padding:8px 14px;background:rgba(0,0,0,0.2);border-radius:12px;margin:4px 0;font-size:0.8rem;">POST /api/restart/{server_id} - Restart</code>
                    <code style="display:block;padding:8px 14px;background:rgba(0,0,0,0.2);border-radius:12px;margin:4px 0;font-size:0.8rem;">GET /api/stats/{server_id} - Stats</code>
                    <code style="display:block;padding:8px 14px;background:rgba(0,0,0,0.2);border-radius:12px;margin:4px 0;font-size:0.8rem;">GET /api/logs/{server_id} - Logs</code>
                </div>
            </div>

            <div id="tab-files" class="tab-content">
                <div class="card">
                    <h3>📁 File Manager & Code Editor</h3>
                    <div class="flex">
                        <button class="btn btn-primary btn-sm" onclick="createFile()">📄 New</button>
                        <button class="btn btn-success btn-sm" onclick="uploadFile()">📤 Upload</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteSelected()">🗑 Delete</button>
                        <input type="file" id="fileUpload" multiple style="display:none" onchange="uploadFiles()">
                        <span style="opacity:0.3;font-size:0.8rem;margin-left:6px;" id="filePath">/</span>
                    </div>
                    <div class="flex" style="background:rgba(255,255,255,0.02);padding:12px 16px;border-radius:var(--radius-sm);margin-bottom:14px;">
                        <input type="file" id="zipUpload" accept=".zip" style="color:var(--text);">
                        <label><input type="checkbox" id="extractZip" checked> Extract</label>
                        <button class="btn btn-primary btn-sm" onclick="uploadZip()">📦 Upload ZIP</button>
                        <span id="zipStatus" style="opacity:0.5;font-size:0.8rem;"></span>
                    </div>
                    <div style="display:flex;gap:20px;flex-wrap:wrap;">
                        <div style="flex:1;min-width:240px;">
                            <div class="file-manager" id="fileList">
                                <div style="opacity:0.3;text-align:center;padding:20px;">Loading...</div>
                            </div>
                        </div>
                        <div style="flex:2;min-width:300px;">
                            <select id="fileSelect" style="width:100%;padding:10px 16px;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);margin-bottom:10px;outline:none;">
                                <option value="">Select file to edit...</option>
                            </select>
                            <textarea class="editor" id="editor" placeholder="Edit your code here..."></textarea>
                            <div class="flex" style="margin-top:12px;">
                                <button class="btn btn-success btn-sm" onclick="saveFile()">💾 Save</button>
                                <button class="btn btn-primary btn-sm" onclick="runFile()">▶ Run</button>
                                <button class="btn btn-primary btn-sm" onclick="downloadFile()">📥 Download</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div id="tab-settings" class="tab-content">
                <div class="card" style="max-width:600px;margin:0 auto;">
                    <h3>⚙️ Server Settings</h3>
                    
                    <div class="settings-group">
                        <label for="mainFileInput">Main File Name</label>
                        <input type="text" id="mainFileInput" value="{server_info.get('main_file','main.py')}" placeholder="e.g., main.py">
                        <small style="display:block;margin-top:4px;opacity:0.4;">The Python file that will be executed when starting the bot.</small>
                    </div>

                    <div class="settings-group">
                        <label for="reqFileInput">Requirements File Name</label>
                        <input type="text" id="reqFileInput" value="{server_info.get('requirements_file','requirements.txt')}" placeholder="e.g., requirements.txt">
                        <small style="display:block;margin-top:4px;opacity:0.4;">The file containing pip packages to install.</small>
                    </div>

                    <button class="btn btn-primary" onclick="saveSettings()" style="width:100%;justify-content:center;">💾 Save Settings</button>
                    <div id="settingsMsg" style="margin-top:14px;text-align:center;font-size:0.9rem;"></div>

                    <hr style="border-color:var(--border);margin:28px 0;">
                    <h3 style="text-align:center;margin-bottom:16px;">🔑 Change Password</h3>
                    <div class="password-form">
                        <input type="password" id="currentPass" placeholder="Current Password">
                        <input type="password" id="newPass" placeholder="New Password">
                        <input type="password" id="confirmPass" placeholder="Confirm New Password">
                        <button class="btn btn-primary" onclick="changePassword()" style="width:100%;justify-content:center;">Update Password</button>
                        <div id="passMsg" style="margin-top:14px;text-align:center;font-size:0.9rem;"></div>
                    </div>

                    <hr style="border-color:var(--border);margin:28px 0;">
                    <div style="text-align:center;opacity:0.4;font-size:0.85rem;">
                        <p>📅 Created: {server_info.get('created','N/A')}</p>
                        <p>⏳ Expiry: {server_info.get('expiry','N/A')}</p>
                        <p>💾 RAM: {server_info.get('ram','N/A')} · 💿 Disk: {server_info.get('disk','N/A')}</p>
                    </div>
                </div>
            </div>

            <div class="footer">
                {cfg['project_name']} v5.0 · <a href="https://t.me/mouhamed_ma" target="_blank">@mouhamed_ma</a>
            </div>
        </div>

        <script>
            let currentFolder = '';
            document.querySelectorAll('.tab').forEach(tab => {{
                tab.addEventListener('click', function() {{
                    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    this.classList.add('active');
                    document.getElementById('tab-' + this.dataset.tab).classList.add('active');
                }});
            }});

            function refreshStats() {{
                fetch('/api/stats/{server_id}')
                    .then(r => r.json())
                    .then(data => {{
                        document.getElementById('stat-cpu').textContent = data.cpu || '0%';
                        document.getElementById('stat-ram').textContent = data.ram || '0 MB';
                        document.getElementById('stat-uptime').textContent = data.uptime || '0s';
                        const statusEl = document.getElementById('stat-status');
                        const status = data.status || 'stopped';
                        statusEl.textContent = status.toUpperCase();
                        statusEl.className = 'status-badge ' + status;
                    }})
                    .catch(() => {{}});
            }}

            function refreshLogs() {{
                fetch('/api/logs/{server_id}')
                    .then(r => r.json())
                    .then(data => {{
                        const logDiv = document.getElementById('logOutput');
                        logDiv.textContent = data.logs || 'No logs yet...';
                        logDiv.scrollTop = logDiv.scrollHeight;
                    }})
                    .catch(() => {{}});
            }}

            function refreshFiles() {{
                const path = currentFolder ? '?folder=' + encodeURIComponent(currentFolder) : '';
                fetch('/api/files/{server_id}' + path)
                    .then(r => r.json())
                    .then(data => {{
                        const list = document.getElementById('fileList');
                        const select = document.getElementById('fileSelect');
                        let html = '';
                        if (currentFolder) {{
                            const parent = currentFolder.split('/').slice(0,-1).join('/');
                            html += `<div class="file-item" onclick="goFolder('${{parent}}')">
                                <span class="name">📂 ..</span>
                            </div>`;
                        }}
                        data.files.forEach(file => {{
                            const icon = file.is_dir ? '📂' : '📄';
                            const size = file.size_display || file.size;
                            html += `<div class="file-item" onclick="${{file.is_dir ? `goFolder('${{file.path}}')` : `selectFile('${{file.path}}')`}}">
                                <span class="name">${{icon}} ${{file.name}}</span>
                                <span class="size">${{file.is_dir ? '' : size}}</span>
                            </div>`;
                        }});
                        if (data.files.length === 0) {{
                            html = '<div style="opacity:0.3;text-align:center;padding:20px;">Empty folder</div>';
                        }}
                        list.innerHTML = html;
                        document.getElementById('filePath').textContent = '/' + (currentFolder || '');
                        select.innerHTML = '<option value="">Select file to edit...</option>';
                        data.files.forEach(file => {{
                            if (!file.is_dir) {{
                                select.innerHTML += `<option value="${{file.path}}">${{file.name}}</option>`;
                            }}
                        }});
                    }})
                    .catch(() => {{}});
            }}

            function goFolder(folder) {{
                currentFolder = folder || '';
                refreshFiles();
            }}

            function selectFile(path) {{
                document.getElementById('fileSelect').value = path;
                loadFileContent();
            }}

            function loadFileContent() {{
                const path = document.getElementById('fileSelect').value;
                if (!path) {{
                    document.getElementById('editor').value = '';
                    return;
                }}
                fetch('/api/download_file/{server_id}?path=' + encodeURIComponent(path))
                    .then(r => r.text())
                    .then(content => {{
                        document.getElementById('editor').value = content;
                    }})
                    .catch(() => {{}});
            }}

            function saveFile() {{
                const path = document.getElementById('fileSelect').value;
                if (!path) {{ alert('Select a file first!'); return; }}
                const content = document.getElementById('editor').value;
                fetch('/api/save_file/{server_id}', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{path,content}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    if(data.success){{ alert('✅ Saved!'); refreshFiles(); }} else {{ alert('❌ Error!'); }}
                }})
                .catch(()=>alert('❌ Error!'));
            }}

            function createFile() {{
                const name = prompt('Enter file name:');
                if (!name) return;
                fetch('/api/create_file/{server_id}', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{name, folder:currentFolder}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    if(data.success){{ alert('✅ Created!'); refreshFiles(); }} else {{ alert('❌ Error!'); }}
                }})
                .catch(()=>alert('❌ Error!'));
            }}

            function uploadFile() {{
                document.getElementById('fileUpload').click();
            }}

            function uploadFiles() {{
                const files = document.getElementById('fileUpload').files;
                if (!files.length) return;
                const formData = new FormData();
                for (let file of files) formData.append('files', file);
                formData.append('folder', currentFolder);
                fetch('/api/upload_multiple/{server_id}', {{
                    method:'POST',
                    body:formData
                }})
                .then(r=>r.json())
                .then(data=>{{
                    alert('✅ Uploaded ' + data.uploaded + ' files!');
                    refreshFiles();
                    document.getElementById('fileUpload').value = '';
                }})
                .catch(()=>alert('❌ Error!'));
            }}

            function deleteSelected() {{
                const path = document.getElementById('fileSelect').value;
                if (!path) {{ alert('Select a file first!'); return; }}
                if (!confirm('Delete ' + path + '?')) return;
                fetch('/api/delete_multiple/{server_id}', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{files:[path]}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    alert('✅ Deleted!');
                    refreshFiles();
                    document.getElementById('editor').value = '';
                    document.getElementById('fileSelect').value = '';
                }})
                .catch(()=>alert('❌ Error!'));
            }}

            function downloadFile() {{
                const path = document.getElementById('fileSelect').value;
                if (!path) {{ alert('Select a file first!'); return; }}
                window.open('/api/download_file/{server_id}?path=' + encodeURIComponent(path), '_blank');
            }}

            function runFile() {{
                const path = document.getElementById('fileSelect').value;
                if (!path) {{ alert('Select a file first!'); return; }}
                if (!path.endsWith('.py')) {{ alert('Only Python files can be run!'); return; }}
                fetch('/api/run_file/{server_id}', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{file:path}})
                }})
                .then(r=>r.json())
                .then(data=>{{ alert(data.msg || data.status); refreshLogs(); }})
                .catch(()=>alert('❌ Error!'));
            }}

            function uploadZip() {{
                const fileInput = document.getElementById('zipUpload');
                const extract = document.getElementById('extractZip').checked;
                const file = fileInput.files[0];
                if (!file) {{ alert('Select a ZIP file.'); return; }}
                if (!file.name.endsWith('.zip')) {{ alert('Must be .zip.'); return; }}
                const formData = new FormData();
                formData.append('zip', file);
                formData.append('extract', extract);
                document.getElementById('zipStatus').textContent = 'Uploading...';
                fetch('/api/upload_zip/{server_id}', {{
                    method:'POST',
                    body:formData
                }})
                .then(r=>r.json())
                .then(data=>{{
                    document.getElementById('zipStatus').textContent = data.msg || 'Done';
                    if(data.success){{ alert('✅ ' + data.msg); refreshFiles(); }} else {{ alert('❌ ' + (data.error||data.msg)); }}
                }})
                .catch(err=>{{
                    document.getElementById('zipStatus').textContent = 'Error';
                    alert('❌ Upload failed.');
                }});
            }}

            function startBot() {{
                fetch('/api/run/{server_id}',{{method:'POST'}})
                    .then(r=>r.json())
                    .then(data=>{{ alert(data.msg||data.status); refreshStats(); refreshLogs(); }})
                    .catch(()=>alert('Error!'));
            }}

            function stopBot() {{
                if(!confirm('Stop the bot?')) return;
                fetch('/api/stop/{server_id}',{{method:'POST'}})
                    .then(r=>r.json())
                    .then(data=>{{ alert(data.msg||data.status); refreshStats(); }})
                    .catch(()=>alert('Error!'));
            }}

            function restartBot() {{
                if(!confirm('Restart the bot?')) return;
                fetch('/api/restart/{server_id}',{{method:'POST'}})
                    .then(r=>r.json())
                    .then(data=>{{ alert(data.msg||data.status); refreshStats(); refreshLogs(); }})
                    .catch(()=>alert('Error!'));
            }}

            function installRequirements() {{
                if(!confirm('Install requirements from requirements.txt?')) return;
                fetch('/api/install/{server_id}',{{method:'POST'}})
                    .then(r=>r.json())
                    .then(data=>{{ alert(data.msg||data.status); refreshLogs(); }})
                    .catch(()=>alert('Error!'));
            }}

            function viewLogs() {{ window.open('/api/logs/{server_id}', '_blank'); }}

            function clearLogs() {{
                if(!confirm('Clear logs?')) return;
                fetch('/api/clear_logs/{server_id}',{{method:'POST'}})
                    .then(()=>{{ refreshLogs(); }})
                    .catch(()=>{{}});
            }}

            function changePassword() {{
                const current = document.getElementById('currentPass').value;
                const newp = document.getElementById('newPass').value;
                const confirm = document.getElementById('confirmPass').value;
                if (!current || !newp || !confirm) {{
                    document.getElementById('passMsg').innerHTML = '<span style="color:#ff1744;">Please fill all fields.</span>';
                    return;
                }}
                if (newp !== confirm) {{
                    document.getElementById('passMsg').innerHTML = '<span style="color:#ff1744;">Passwords do not match.</span>';
                    return;
                }}
                if (newp.length < 4) {{
                    document.getElementById('passMsg').innerHTML = '<span style="color:#ff1744;">Minimum 4 characters.</span>';
                    return;
                }}
                fetch('/api/change_password', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{username:'{user}', current, new_password:newp}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    if(data.success){{
                        document.getElementById('passMsg').innerHTML = '<span style="color:#00e676;">✅ Password updated!</span>';
                        document.getElementById('currentPass').value = '';
                        document.getElementById('newPass').value = '';
                        document.getElementById('confirmPass').value = '';
                    }} else {{
                        document.getElementById('passMsg').innerHTML = '<span style="color:#ff1744;">❌ ' + (data.error||'Error') + '</span>';
                    }}
                }})
                .catch(()=>{{
                    document.getElementById('passMsg').innerHTML = '<span style="color:#ff1744;">❌ Network error.</span>';
                }});
            }}

            function saveSettings() {{
                const mainFile = document.getElementById('mainFileInput').value.trim();
                const reqFile = document.getElementById('reqFileInput').value.trim();
                if (!mainFile) {{
                    document.getElementById('settingsMsg').innerHTML = '<span style="color:#ff1744;">Main file name cannot be empty.</span>';
                    return;
                }}
                if (!reqFile) {{
                    document.getElementById('settingsMsg').innerHTML = '<span style="color:#ff1744;">Requirements file name cannot be empty.</span>';
                    return;
                }}
                fetch('/api/update_settings/{server_id}', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{main_file:mainFile, requirements_file:reqFile}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    if(data.success){{
                        document.getElementById('settingsMsg').innerHTML = '<span style="color:#00e676;">✅ Settings updated successfully!</span>';
                    }} else {{
                        document.getElementById('settingsMsg').innerHTML = '<span style="color:#ff1744;">❌ ' + (data.error||'Error') + '</span>';
                    }}
                }})
                .catch(()=>{{
                    document.getElementById('settingsMsg').innerHTML = '<span style="color:#ff1744;">❌ Network error.</span>';
                }});
            }}

            refreshStats();
            refreshLogs();
            refreshFiles();
            setInterval(refreshStats, 5000);
            setInterval(refreshLogs, 3000);
        </script>
    </body>
    </html>
    '''
    return html

# ============================================================================
# 👑 ADMIN DASHBOARD
# ============================================================================

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    users = load_users()
    user_list = []
    total_servers = 0
    total_running = 0

    for uname, data in users.items():
        if uname == 'admin':
            continue
        servers = data.get('servers', [])
        if not isinstance(servers, list):
            servers = []
        running = sum(1 for s in servers if isinstance(s, dict) and s.get('status') == 'running')
        total_servers += len(servers)
        total_running += running
        user_list.append({
            'username': uname,
            'password': data.get('password', ''),  # not shown fully
            'servers': servers,
            'server_count': len(servers),
            'running_count': running
        })

    try:
        cpu_usage = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
    except:
        cpu_usage = 0
        mem = None
        disk = None

    cfg = load_config()
    csrf_token = session.get('csrf_token', '')

    # Render admin template
    html = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Admin · {cfg['project_name']}</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
        <style>
            :root {{
                --bg: #0a0a1a;
                --bg-glass: rgba(20,20,40,0.6);
                --bg-card: rgba(20,20,40,0.5);
                --primary: {cfg['primary_color']};
                --secondary: {cfg['secondary_color']};
                --accent: {cfg['accent_color']};
                --text: #f0f0fa;
                --text-dim: rgba(255,255,255,0.5);
                --border: rgba(255,255,255,0.04);
                --shadow: 0 40px 80px -20px rgba(0,0,0,0.9);
                --radius: 32px;
                --radius-sm: 20px;
            }}
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{
                font-family:'Inter',sans-serif;
                background:var(--bg);
                color:var(--text);
                min-height:100vh;
                padding:24px;
                background-image: radial-gradient(ellipse at 80% 20%, rgba(0,180,255,0.04) 0%, transparent 60%);
            }}
            .container {{ max-width:1440px; margin:0 auto; }}
            .header {{
                display:flex;
                justify-content:space-between;
                align-items:center;
                padding:16px 28px;
                background:var(--bg-glass);
                backdrop-filter:blur(16px);
                -webkit-backdrop-filter:blur(16px);
                border:1px solid var(--border);
                border-radius:var(--radius);
                margin-bottom:28px;
                flex-wrap:wrap;
                gap:12px;
            }}
            .header h1 {{
                font-size:1.8rem;
                font-weight:800;
                background:linear-gradient(135deg,var(--primary),var(--secondary));
                -webkit-background-clip:text;
                -webkit-text-fill-color:transparent;
                background-clip:text;
            }}
            .badge {{
                background:rgba(0,102,255,0.12);
                padding:6px 18px;
                border-radius:60px;
                font-size:0.8rem;
                font-weight:500;
                color:var(--secondary);
                border:1px solid rgba(0,102,255,0.08);
            }}
            .stats {{
                display:grid;
                grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
                gap:20px;
                margin-bottom:28px;
            }}
            .stat-card {{
                background:var(--bg-card);
                backdrop-filter:blur(12px);
                -webkit-backdrop-filter:blur(12px);
                border:1px solid var(--border);
                border-radius:var(--radius-sm);
                padding:20px 18px;
                text-align:center;
                transition:0.3s;
            }}
            .stat-card:hover {{ border-color:rgba(0,102,255,0.15); }}
            .stat-card .num {{ font-size:2.2rem; font-weight:800; color:var(--secondary); }}
            .stat-card .label {{ opacity:0.4; font-size:0.8rem; margin-top:4px; }}
            .card {{
                background:var(--bg-card);
                backdrop-filter:blur(12px);
                -webkit-backdrop-filter:blur(12px);
                border:1px solid var(--border);
                border-radius:var(--radius);
                padding:24px 28px;
                margin-bottom:24px;
                transition:0.3s;
            }}
            .card:hover {{ border-color:rgba(0,102,255,0.1); }}
            .card h3 {{ color:var(--secondary); font-weight:600; margin-bottom:16px; }}
            .user-card {{
                background:rgba(255,255,255,0.01);
                border-left:3px solid var(--primary);
                padding:16px 20px;
                border-radius:var(--radius-sm);
                margin:12px 0;
            }}
            .user-card h4 {{ color:var(--text); font-weight:600; }}
            .server-item {{
                display:flex;
                justify-content:space-between;
                align-items:center;
                padding:10px 16px;
                background:rgba(255,255,255,0.01);
                border-radius:var(--radius-sm);
                margin:6px 0;
                flex-wrap:wrap;
                gap:8px;
            }}
            .status-badge {{
                padding:3px 16px;
                border-radius:60px;
                font-size:0.7rem;
                font-weight:600;
                text-transform:uppercase;
            }}
            .running {{ background:#00e676; color:#000; }}
            .stopped {{ background:#ff1744; color:#fff; }}
            .btn {{
                padding:6px 20px;
                border:none;
                border-radius:60px;
                font-weight:600;
                cursor:pointer;
                transition:all 0.25s;
                color:#fff;
                text-decoration:none;
                display:inline-block;
                font-size:0.8rem;
                background:rgba(255,255,255,0.05);
                border:1px solid var(--border);
            }}
            .btn-primary {{ background:linear-gradient(135deg,var(--primary),var(--secondary)); border-color:transparent; }}
            .btn-danger {{ background:#d32f2f; border-color:#d32f2f; }}
            .btn-sm {{ padding:4px 16px; font-size:0.7rem; }}
            .btn:hover {{ transform:translateY(-2px); box-shadow:0 12px 32px rgba(0,0,0,0.3); }}
            .flex {{ display:flex; gap:12px; flex-wrap:wrap; align-items:center; }}
            .flex input, .flex select {{
                padding:10px 16px;
                background:rgba(255,255,255,0.03);
                border:1px solid var(--border);
                border-radius:var(--radius-sm);
                color:var(--text);
                font-size:0.9rem;
                outline:none;
                transition:0.2s;
            }}
            .flex input:focus, .flex select:focus {{
                border-color:var(--primary);
                background:rgba(255,255,255,0.05);
            }}
            .footer {{
                margin-top:48px;
                opacity:0.2;
                text-align:center;
                font-size:0.8rem;
                border-top:1px solid var(--border);
                padding-top:24px;
            }}
            .footer a {{ color:var(--secondary); text-decoration:none; }}
            .modal {{
                display:none;
                position:fixed;
                top:0;left:0;width:100%;height:100%;
                background:rgba(0,0,0,0.6);
                backdrop-filter:blur(10px);
                -webkit-backdrop-filter:blur(10px);
                justify-content:center;
                align-items:center;
                z-index:1000;
            }}
            .modal-content {{
                background:rgba(20,20,40,0.9);
                backdrop-filter:blur(20px);
                -webkit-backdrop-filter:blur(20px);
                border:1px solid var(--border);
                border-radius:var(--radius);
                padding:32px 28px;
                max-width:480px;
                width:90%;
            }}
            .modal-content h3 {{ color:var(--secondary); margin-bottom:16px; }}
            .modal-content input {{
                width:100%;
                padding:12px 16px;
                margin:6px 0;
                background:rgba(255,255,255,0.03);
                border:1px solid var(--border);
                border-radius:var(--radius-sm);
                color:var(--text);
                outline:none;
                transition:0.2s;
            }}
            .modal-content input:focus {{ border-color:var(--primary); }}
            .modal-content .btn {{ width:100%; margin-top:8px; justify-content:center; }}
            @media (max-width:640px) {{
                .header h1 {{ font-size:1.4rem; }}
                .stats {{ grid-template-columns:1fr 1fr; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>👑 Admin Dashboard</h1>
                <div>
                    <span class="badge">👤 Admin</span>
                    <a href="/logout" class="btn btn-danger btn-sm" style="text-decoration:none;margin-left:10px;">🚪 Logout</a>
                </div>
            </div>

            <div class="stats">
                <div class="stat-card"><div class="num">{total_servers}</div><div class="label">Total Servers</div></div>
                <div class="stat-card"><div class="num">{total_running}</div><div class="label">Running</div></div>
                <div class="stat-card"><div class="num">{len(user_list)}</div><div class="label">Users</div></div>
                <div class="stat-card"><div class="num">{cpu_usage}%</div><div class="label">System CPU</div></div>
                {f'<div class="stat-card"><div class="num">{mem.percent}%</div><div class="label">RAM</div></div>' if mem else ''}
                {f'<div class="stat-card"><div class="num">{disk.percent}%</div><div class="label">Disk</div></div>' if disk else ''}
            </div>

            <div class="card">
                <h3>⚡ Create New Server</h3>
                <div class="flex">
                    <input type="text" id="newUsername" placeholder="Username">
                    <input type="text" id="newPassword" placeholder="Password">
                    <input type="number" id="newDays" placeholder="Days" value="30">
                    <input type="number" id="newCpu" placeholder="CPU Limit" value="80">
                    <button class="btn btn-primary" onclick="createServer()">Create</button>
                </div>
                <span id="createResult" style="opacity:0.5;font-size:0.85rem;margin-left:6px;"></span>
            </div>

            <div class="card">
                <h3>⚙️ System Settings</h3>
                <div class="flex">
                    <input type="text" id="projectName" value="{cfg['project_name']}" placeholder="Project Name">
                    <input type="text" id="projectLogo" value="{cfg['project_logo']}" placeholder="Logo (emoji or text)">
                    <button class="btn btn-primary btn-sm" onclick="saveSystemSettings()">Save</button>
                </div>
                <span id="sysSettingsMsg" style="opacity:0.5;font-size:0.85rem;margin-left:6px;"></span>
            </div>

            <h2 style="font-weight:400;font-size:1.2rem;margin:20px 0 12px;">📋 Users & Servers</h2>
    '''
    for user in user_list:
        html += f'''
        <div class="user-card">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <div>
                    <h4>👤 {user['username']}</h4>
                    <span style="opacity:0.3;font-size:0.8rem;">Password: ******** · {user['server_count']} servers · {user['running_count']} running</span>
                </div>
                <div>
                    <button class="btn btn-primary btn-sm" onclick="editUser('{user['username']}')">✏️ Edit</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteUser('{user['username']}')">🗑 Delete</button>
                </div>
            </div>
        '''
        for server in user['servers']:
            status_class = 'running' if server.get('status') == 'running' else 'stopped'
            html += f'''
            <div class="server-item">
                <div>
                    <strong>{server.get('server_id')}</strong>
                    <span class="status-badge {status_class}">{server.get('status','stopped').upper()}</span>
                    <span style="opacity:0.3;font-size:0.75rem;">CPU: {server.get('cpu_limit',80)}% · RAM: {server.get('ram','N/A')}</span>
                </div>
                <div>
                    <a href="/{server.get('server_id')}/home" class="btn btn-primary btn-sm" target="_blank">Open</a>
                    <button class="btn btn-danger btn-sm" onclick="deleteServer('{user['username']}','{server.get('server_id')}')">Delete</button>
                </div>
            </div>
            '''
        html += '</div>'

    html += f'''
            <div class="footer">
                {cfg['project_name']} v5.0 · <a href="https://t.me/mouhamed_ma" target="_blank">@mouhamed_ma</a>
            </div>
        </div>

        <div id="editModal" class="modal">
            <div class="modal-content">
                <h3>✏️ Edit User: <span id="editUsername"></span></h3>
                <input type="password" id="editNewPass" placeholder="New Password">
                <input type="number" id="editExpiryDays" placeholder="Extend expiry (days)" value="30">
                <button class="btn btn-primary" onclick="saveEdit()">Save Changes</button>
                <button class="btn btn-danger" style="margin-top:6px;" onclick="closeModal()">Cancel</button>
                <div id="editMsg" style="margin-top:10px;text-align:center;"></div>
            </div>
        </div>

        <script>
            let editingUser = '';

            function createServer() {{
                const username = document.getElementById('newUsername').value.trim();
                const password = document.getElementById('newPassword').value.trim();
                const days = parseInt(document.getElementById('newDays').value) || 30;
                const cpu = parseInt(document.getElementById('newCpu').value) || 80;
                if (!username || !password) {{
                    document.getElementById('createResult').textContent = '⚠️ Fill all fields!';
                    return;
                }}
                fetch('/admin/create_server', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{username,password,expiry_days:days,cpu_limit:cpu}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    if(data.success){{
                        document.getElementById('createResult').textContent = '✅ Created! ' + data.login_url;
                        setTimeout(()=>location.reload(),1500);
                    }} else {{
                        document.getElementById('createResult').textContent = '❌ ' + (data.error||'Error');
                    }}
                }})
                .catch(()=>{{
                    document.getElementById('createResult').textContent = '❌ Network error!';
                }});
            }}

            function deleteServer(username, serverId) {{
                if (!confirm('Delete server ' + serverId + '?')) return;
                fetch('/admin/delete_server/' + username + '/' + serverId, {{ method:'POST' }})
                    .then(r=>r.json())
                    .then(data=>{{ if(data.success) location.reload(); }})
                    .catch(()=>{{}});
            }}

            function deleteUser(username) {{
                if (!confirm('Delete user ' + username + ' and all servers?')) return;
                fetch('/admin/delete_user/' + username, {{ method:'POST' }})
                    .then(r=>r.json())
                    .then(data=>{{ if(data.success) location.reload(); }})
                    .catch(()=>{{}});
            }}

            function editUser(username) {{
                editingUser = username;
                document.getElementById('editUsername').textContent = username;
                document.getElementById('editNewPass').value = '';
                document.getElementById('editExpiryDays').value = '30';
                document.getElementById('editMsg').innerHTML = '';
                document.getElementById('editModal').style.display = 'flex';
            }}

            function closeModal() {{
                document.getElementById('editModal').style.display = 'none';
            }}

            function saveEdit() {{
                const newPass = document.getElementById('editNewPass').value.trim();
                const days = parseInt(document.getElementById('editExpiryDays').value) || 0;
                if (!newPass && days === 0) {{
                    document.getElementById('editMsg').innerHTML = '<span style="color:#ff1744;">Enter new password or extend days.</span>';
                    return;
                }}
                fetch('/admin/edit_user/' + editingUser, {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{password:newPass, extend_days:days}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    if(data.success){{
                        document.getElementById('editMsg').innerHTML = '<span style="color:#00e676;">✅ Updated!</span>';
                        setTimeout(()=>location.reload(),1500);
                    }} else {{
                        document.getElementById('editMsg').innerHTML = '<span style="color:#ff1744;">❌ ' + (data.error||'Error') + '</span>';
                    }}
                }})
                .catch(()=>{{
                    document.getElementById('editMsg').innerHTML = '<span style="color:#ff1744;">❌ Network error.</span>';
                }});
            }}

            window.onclick = function(event) {{
                const modal = document.getElementById('editModal');
                if (event.target == modal) modal.style.display = 'none';
            }}

            function saveSystemSettings() {{
                const name = document.getElementById('projectName').value.trim();
                const logo = document.getElementById('projectLogo').value.trim();
                if (!name) {{
                    document.getElementById('sysSettingsMsg').textContent = 'Project name required.';
                    return;
                }}
                fetch('/admin/update_config', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{project_name:name, project_logo:logo}})
                }})
                .then(r=>r.json())
                .then(data=>{{
                    if(data.success){{
                        document.getElementById('sysSettingsMsg').textContent = '✅ Settings updated! Refresh page to see changes.';
                    }} else {{
                        document.getElementById('sysSettingsMsg').textContent = '❌ ' + (data.error||'Error');
                    }}
                }})
                .catch(()=>{{
                    document.getElementById('sysSettingsMsg').textContent = '❌ Network error.';
                }});
            }}
        </script>
    </body>
    </html>
    '''
    return html

# ============================================================================
# 🛠️ ADMIN API - USER & SERVER MANAGEMENT
# ============================================================================

@app.route('/admin/create_server', methods=['POST'])
@login_required
@admin_required
def create_server_admin():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    expiry_days = int(data.get('expiry_days', 30))
    cpu_limit = int(data.get('cpu_limit', 80))
    ram = data.get('ram', '512MB')
    disk = data.get('disk', '1GB')

    if not username or not password:
        return jsonify({'error': 'Username and password required!'}), 400

    if len(username) < 3:
        return jsonify({'error': 'Username too short'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Password too short'}), 400

    users = load_users()
    if username in users:
        return jsonify({'error': 'User already exists'}), 400

    server_id = generate_server_id()
    expiry_date = datetime.now() + timedelta(days=expiry_days)
    server_dir = get_server_dir(server_id)
    create_default_files(server_dir)

    host = request.host
    scheme = 'https' if 'spaceify' in host or 'ngrok' in host else 'http'
    full_url = f"{scheme}://{host}/{server_id}/login"

    new_server = {
        'server_id': server_id,
        'login_url': f"/{server_id}/login",
        'dashboard_url': f"/{server_id}/home",
        'full_link': full_url,
        'type': 'python',
        'ram': ram,
        'disk': disk,
        'status': 'stopped',
        'pid': None,
        'created': str(datetime.now()),
        'expiry': str(expiry_date),
        'main_file': config.get('default_main_file', 'main.py'),
        'requirements_file': config.get('default_requirements_file', 'requirements.txt'),
        'cpu_limit': cpu_limit,
        'color': '#a050ff',
        'rate_limit_exceeded': False,
        'stopped_by_user': False,
        'last_login': None,
        'last_ip': None,
        'banned_ips': [],
        'access_log': []
    }

    users[username] = {
        'password': hash_password(password),
        'role': 'user',
        'servers': [new_server],
        'created': str(datetime.now())
    }
    save_users(users)

    return jsonify({
        'success': True,
        'username': username,
        'password': password,
        'login_url': new_server['login_url'],
        'full_url': full_url,
        'server_id': server_id
    })

@app.route('/admin/delete_server/<username>/<server_id>', methods=['POST'])
@login_required
@admin_required
def delete_server_admin(username, server_id):
    users = load_users()
    if username not in users:
        return jsonify({'error': 'User not found'}), 404

    servers = users[username].get('servers', [])
    for s in servers:
        if s.get('server_id') == server_id:
            if s.get('pid'):
                stop_bot_process(s['pid'])
            try:
                shutil.rmtree(get_server_dir(server_id))
            except:
                pass
            break
    users[username]['servers'] = [s for s in servers if s.get('server_id') != server_id]
    save_users(users)
    return jsonify({'success': True})

@app.route('/admin/delete_user/<username>', methods=['POST'])
@login_required
@admin_required
def delete_user_admin(username):
    if username == ADMIN_USERNAME:
        return jsonify({'error': 'Cannot delete admin'}), 400
    users = load_users()
    if username not in users:
        return jsonify({'error': 'User not found'}), 404
    # Delete all server directories
    for s in users[username].get('servers', []):
        try:
            shutil.rmtree(get_server_dir(s['server_id']))
        except:
            pass
    del users[username]
    save_users(users)
    return jsonify({'success': True})

@app.route('/admin/edit_user/<username>', methods=['POST'])
@login_required
@admin_required
def edit_user_admin(username):
    data = request.get_json()
    new_password = data.get('password', '').strip()
    extend_days = int(data.get('extend_days', 0))

    users = load_users()
    if username not in users:
        return jsonify({'error': 'User not found'}), 404

    if new_password:
        if len(new_password) < 4:
            return jsonify({'error': 'Password too short'}), 400
        users[username]['password'] = hash_password(new_password)

    if extend_days > 0:
        servers = users[username].get('servers', [])
        for s in servers:
            if s.get('expiry'):
                try:
                    exp = datetime.strptime(s['expiry'], '%Y-%m-%d %H:%M:%S.%f')
                    exp += timedelta(days=extend_days)
                    s['expiry'] = str(exp)
                except:
                    pass
        users[username]['servers'] = servers

    save_users(users)
    return jsonify({'success': True})

@app.route('/admin/update_config', methods=['POST'])
@login_required
@admin_required
def update_config():
    data = request.get_json()
    cfg = load_config()
    if 'project_name' in data:
        cfg['project_name'] = data['project_name'].strip() or cfg['project_name']
    if 'project_logo' in data:
        cfg['project_logo'] = data['project_logo'].strip() or cfg['project_logo']
    save_config(cfg)
    return jsonify({'success': True})

# ============================================================================
# 🤖 BOT API ENDPOINTS (Original + Enhanced)
# ============================================================================

@app.route('/api/run/<server_id>', methods=['POST'])
@login_required
def api_run(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return jsonify({'status': 'error', 'msg': 'Server not found'}), 404

    if server.get('status') == 'running':
        return jsonify({'status': 'error', 'msg': 'Already running!'}), 400

    main_file = server.get('main_file', config.get('default_main_file', 'main.py'))
    req_file = server.get('requirements_file', config.get('default_requirements_file', 'requirements.txt'))

    pid, error = run_bot(server_id, main_file, req_file)
    if pid:
        update_server_for_user(user, server_id, {
            'status': 'running',
            'pid': pid,
            'started_at': str(datetime.now()),
            'rate_limit_exceeded': False,
            'stopped_by_user': False
        })
        return jsonify({'status': 'success', 'msg': 'Started!'})
    return jsonify({'status': 'error', 'msg': error or 'Failed'})

@app.route('/api/stop/<server_id>', methods=['POST'])
@login_required
def api_stop(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return jsonify({'status': 'error', 'msg': 'Server not found'}), 404

    if server.get('pid'):
        stop_bot_process(server['pid'])
    update_server_for_user(user, server_id, {
        'status': 'stopped',
        'pid': None,
        'stopped_by_user': True
    })
    return jsonify({'status': 'success', 'msg': 'Stopped'})

@app.route('/api/restart/<server_id>', methods=['POST'])
@login_required
def api_restart(server_id):
    stop_resp = api_stop(server_id)
    if stop_resp.status_code != 200:
        return stop_resp
    time.sleep(1)
    return api_run(server_id)

@app.route('/api/logs/<server_id>')
@login_required
def api_logs(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return jsonify({'logs': ''}), 404
    log_file = os.path.join(get_server_dir(server_id), 'output.log')
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = f.read()
    else:
        logs = ""
    return jsonify({'logs': logs})

@app.route('/api/clear_logs/<server_id>', methods=['POST'])
@login_required
def api_clear_logs(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return jsonify({'status': 'error'}), 404
    log_file = os.path.join(get_server_dir(server_id), 'output.log')
    try:
        if os.path.exists(log_file):
            os.remove(log_file)
        return jsonify({'status': 'success', 'msg': 'Cleared'})
    except:
        return jsonify({'status': 'error'}), 500

@app.route('/api/stats/<server_id>')
@login_required
def api_stats(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return jsonify({
            'cpu': '0%',
            'ram': '0 MB',
            'uptime': '0s',
            'status': 'unknown',
            'cpu_limit': DEFAULT_CPU_LIMIT
        })

    uptime, cpu, ram = "0s", "0%", "0 MB"

    if server.get('status') == 'running' and server.get('pid'):
        try:
            proc = psutil.Process(server['pid'])
            cpu = f"{proc.cpu_percent(interval=0.3)}%"
            mem = proc.memory_info()
            ram_mb = mem.rss / (1024 * 1024)
            ram = f"{ram_mb:.1f} MB" if ram_mb < 1024 else f"{ram_mb/1024:.2f} GB"
        except:
            pass

    if server.get('status') == 'running' and server.get('started_at'):
        try:
            start = datetime.strptime(server['started_at'], '%Y-%m-%d %H:%M:%S.%f')
            diff = datetime.now() - start
            if diff.days > 0:
                uptime = f"{diff.days}d {diff.seconds//3600}h"
            else:
                h, m, s = diff.seconds // 3600, (diff.seconds % 3600) // 60, diff.seconds % 60
                uptime = f"{h}h {m}m {s}s"
        except:
            pass

    return jsonify({
        'cpu': cpu,
        'ram': ram,
        'uptime': uptime,
        'cpu_limit': server.get('cpu_limit', DEFAULT_CPU_LIMIT),
        'status': server.get('status', 'stopped')
    })

@app.route('/api/install/<server_id>', methods=['POST'])
@login_required
def api_install_requirements(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return jsonify({'status': 'error', 'msg': 'Server not found'}), 404

    server_dir = get_server_dir(server_id)
    req_filename = server.get('requirements_file', config.get('default_requirements_file', 'requirements.txt'))
    req_path = os.path.join(server_dir, req_filename)

    if not os.path.exists(req_path):
        return jsonify({'status': 'error', 'msg': f'{req_filename} not found!'}), 404

    with open(req_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    lines = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
    if not lines:
        return jsonify({'status': 'error', 'msg': f'{req_filename} is empty!'}), 400

    python_exe = sys.executable
    log_file = os.path.join(server_dir, 'output.log')

    def install_thread():
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n[{datetime.now().strftime('%H:%M:%S')}] 📦 Installing requirements from {req_filename}...\n")
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] Packages: {', '.join(lines)}\n")

            proc = subprocess.Popen(
                [python_exe, '-m', 'pip', 'install', '-r', os.path.abspath(req_path),
                 '--disable-pip-version-check', '--no-warn-script-location'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            for line in iter(proc.stdout.readline, ''):
                if line.strip():
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {line}")

            proc.wait()
            with open(log_file, 'a', encoding='utf-8') as f:
                if proc.returncode == 0:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Requirements installed successfully!\n\n")
                else:
                    f.write(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Installation failed!\n\n")
        except Exception as e:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error: {str(e)}\n\n")
            log_security_event(request.remote_addr, 'install_requirements_error', str(e))  # 🔐 Log error

    threading.Thread(target=install_thread, daemon=True).start()
    return jsonify({'status': 'success', 'msg': f'Installing from {req_filename}... Check logs for progress!'})

# ============================================================================
# 📁 FILE MANAGEMENT APIS (with security patches)
# ============================================================================

@app.route('/api/files/<server_id>')
@login_required
def api_files(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return jsonify({'files': []}), 404

    folder = request.args.get('folder', '')
    server_dir = get_server_dir(server_id)
    if folder:
        # Secure folder path
        safe_folder = secure_file_path(server_dir, folder)
        if safe_folder is None:
            return jsonify({'files': []}), 400
        server_dir = safe_folder

    if not os.path.exists(server_dir):
        return jsonify({'files': []})

    files = []
    try:
        for item in os.listdir(server_dir):
            item_path = os.path.join(server_dir, item)
            is_dir = os.path.isdir(item_path)
            size = 0 if is_dir else os.path.getsize(item_path)
            files.append({
                'name': item,
                'is_dir': is_dir,
                'size': size,
                'size_display': format_size(size),
                'path': os.path.join(folder, item).replace('\\', '/') if folder else item,
                'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%Y-%m-%d %H:%M:%S')
            })
        files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    except Exception as e:
        log_security_event(request.remote_addr, 'file_list_error', str(e))
    return jsonify({'files': files, 'current_path': folder or ''})

@app.route('/api/upload_multiple/<server_id>', methods=['POST'])
@login_required
def api_upload_multiple(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return safe_error_response('Server not found', 404, 'Server not found')

    folder = request.form.get('folder', '')
    server_dir = get_server_dir(server_id)
    if folder:
        safe_folder = secure_file_path(server_dir, folder)
        if safe_folder is None:
            return safe_error_response('Invalid folder', 400, 'Path traversal attempt')
        server_dir = safe_folder
    os.makedirs(server_dir, exist_ok=True)

    files = request.files.getlist('files')
    uploaded = []
    for file in files:
        if file.filename:
            # Security: prevent path traversal in filename
            safe_name = os.path.basename(file.filename)
            if '..' in safe_name or safe_name.startswith('/') or safe_name.startswith('\\'):
                log_security_event(request.remote_addr, 'upload_path_traversal', f"Filename: {safe_name}")
                continue
            file.save(os.path.join(server_dir, safe_name))
            uploaded.append(safe_name)
    return jsonify({'success': True, 'uploaded': len(uploaded)})

@app.route('/api/delete_multiple/<server_id>', methods=['POST'])
@login_required
def api_delete_multiple(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return safe_error_response('Server not found', 404, 'Server not found')

    data = request.get_json()
    files = data.get('files', [])
    server_dir = get_server_dir(server_id)

    deleted = []
    for f in files:
        safe_path = secure_file_path(server_dir, f)
        if safe_path is None:
            continue
        file_path = safe_path
        if os.path.exists(file_path) and os.path.realpath(file_path).startswith(os.path.realpath(server_dir)):
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
                deleted.append(f)
            except Exception as e:
                log_security_event(request.remote_addr, 'delete_error', f"{f}: {str(e)}")
    return jsonify({'success': True, 'deleted': deleted})

@app.route('/api/download_file/<server_id>')
@login_required
def api_download_file(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return safe_error_response('Server not found', 404, 'Server not found')

    file_path = request.args.get('path', '')
    if not file_path:
        return safe_error_response('No file specified', 400, 'Empty path')

    server_dir = get_server_dir(server_id)
    safe_path = secure_file_path(server_dir, file_path)
    if safe_path is None:
        return safe_error_response('Invalid file path', 400, 'Path traversal')
    full_path = safe_path
    if os.path.exists(full_path) and os.path.isfile(full_path) and os.path.realpath(full_path).startswith(os.path.realpath(server_dir)):
        try:
            return send_file(full_path, as_attachment=True, download_name=os.path.basename(full_path))
        except Exception as e:
            log_security_event(request.remote_addr, 'download_error', str(e))
            return safe_error_response('Error downloading file', 500)
    return safe_error_response('File not found', 404, 'File not found')

@app.route('/api/save_file/<server_id>', methods=['POST'])
@login_required
def api_save_file(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return safe_error_response('Server not found', 404, 'Server not found')

    data = request.get_json()
    path = data.get('path', '')
    content = data.get('content', '')
    if not path:
        return safe_error_response('No path', 400, 'Empty path')

    server_dir = get_server_dir(server_id)
    safe_path = secure_file_path(server_dir, path)
    if safe_path is None:
        return safe_error_response('Invalid path', 400, 'Path traversal')
    full_path = safe_path

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True})
    except Exception as e:
        log_security_event(request.remote_addr, 'save_file_error', str(e))
        return safe_error_response('Error saving file', 500)

@app.route('/api/create_file/<server_id>', methods=['POST'])
@login_required
def api_create_file(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return safe_error_response('Server not found', 404, 'Server not found')

    data = request.get_json()
    name = data.get('name', '')
    folder = data.get('folder', '')
    if not name:
        return safe_error_response('No name', 400, 'Empty name')

    server_dir = get_server_dir(server_id)
    if folder:
        safe_folder = secure_file_path(server_dir, folder)
        if safe_folder is None:
            return safe_error_response('Invalid folder', 400, 'Path traversal')
        server_dir = safe_folder
    safe_name = os.path.basename(name)
    if '..' in safe_name or safe_name.startswith('/') or safe_name.startswith('\\'):
        return safe_error_response('Invalid filename', 400, 'Path traversal in name')
    full_path = os.path.join(server_dir, safe_name)
    if not os.path.realpath(full_path).startswith(os.path.realpath(server_dir)):
        return safe_error_response('Invalid path', 400, 'Path traversal')

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(f"# Created: {datetime.now()}\n")
        return jsonify({'success': True})
    except Exception as e:
        log_security_event(request.remote_addr, 'create_file_error', str(e))
        return safe_error_response('Error creating file', 500)

@app.route('/api/run_file/<server_id>', methods=['POST'])
@login_required
def api_run_file(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return safe_error_response('Server not found', 404, 'Server not found')

    data = request.get_json()
    file_path = data.get('file', '')
    if not file_path:
        return safe_error_response('No file specified', 400, 'Empty file')
    if not file_path.endswith('.py'):
        return safe_error_response('Only Python files can be run', 400, 'Non-Python file')

    server_dir = get_server_dir(server_id)
    safe_path = secure_file_path(server_dir, file_path)
    if safe_path is None:
        return safe_error_response('Invalid file', 400, 'Path traversal')
    full_path = safe_path
    if not os.path.exists(full_path) or not os.path.realpath(full_path).startswith(os.path.realpath(server_dir)):
        return safe_error_response('File not found', 404, 'File not found')

    # Update main_file for this server
    update_server_for_user(user, server_id, {'main_file': file_path})
    return api_run(server_id)

# ============================================================================
# 📦 ZIP UPLOAD & EXTRACT (with security patch)
# ============================================================================

@app.route('/api/upload_zip/<server_id>', methods=['POST'])
@login_required
def api_upload_zip(server_id):
    user = session['user']
    server = get_server_for_user(user, server_id)
    if not server:
        return safe_error_response('Server not found', 404, 'Server not found')

    if 'zip' not in request.files:
        return safe_error_response('No ZIP file uploaded', 400, 'Missing file')

    file = request.files['zip']
    if file.filename == '':
        return safe_error_response('No file selected', 400, 'Empty filename')
    if not file.filename.endswith('.zip'):
        return safe_error_response('File must be a ZIP archive', 400, 'Invalid extension')

    extract = request.form.get('extract', 'false').lower() == 'true'
    server_dir = get_server_dir(server_id)

    safe_name = os.path.basename(file.filename)
    if '..' in safe_name or safe_name.startswith('/') or safe_name.startswith('\\'):
        return safe_error_response('Invalid filename', 400, 'Path traversal in zip name')
    zip_path = os.path.join(server_dir, safe_name)
    file.save(zip_path)

    if extract:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    member_path = os.path.normpath(member)
                    if member_path.startswith('..') or os.path.isabs(member_path):
                        log_security_event(request.remote_addr, 'zip_path_traversal', f"Member: {member}")
                        continue
                    target = os.path.join(server_dir, member_path)
                    if not os.path.realpath(target).startswith(os.path.realpath(server_dir)):
                        log_security_event(request.remote_addr, 'zip_path_traversal', f"Target: {target}")
                        continue
                    zip_ref.extract(member, server_dir)
            os.remove(zip_path)
            msg = 'ZIP extracted successfully!'
        except Exception as e:
            log_security_event(request.remote_addr, 'zip_extract_error', str(e))
            return safe_error_response(f'Extraction failed: {str(e)}', 500)
    else:
        msg = 'ZIP uploaded successfully (not extracted).'

    return jsonify({'success': True, 'msg': msg})

# ============================================================================
# 🔑 PASSWORD CHANGE API (with rate limiting)
# ============================================================================

@app.route('/api/change_password', methods=['POST'])
@login_required
def api_change_password():
    # 🔐 Rate limiting for password change attempts
    ip = request.remote_addr
    if is_rate_limited(ip, 'password_change', SENSITIVE_RATE_LIMIT, RATE_LIMIT_WINDOW):
        log_security_event(ip, 'rate_limit_exceeded', 'Password change attempts')
        return jsonify({'success': False, 'error': 'Too many attempts. Try later.'}), 429

    data = request.get_json()
    username = session['user']
    current = data.get('current', '').strip()
    new_password = data.get('new_password', '').strip()

    if not current or not new_password:
        return jsonify({'success': False, 'error': 'All fields required'}), 400
    if len(new_password) < 4:
        return jsonify({'success': False, 'error': 'Password too short'}), 400

    users = load_users()
    if username not in users:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    if not verify_password(current, users[username].get('password', '')):
        log_security_event(ip, 'failed_password_change', f"User: {username}")
        return jsonify({'success': False, 'error': 'Current password is incorrect'}), 401

    users[username]['password'] = hash_password(new_password)
    save_users(users)
    return jsonify({'success': True, 'msg': 'Password updated successfully'})

# ============================================================================
# ⚙️ UPDATE SERVER SETTINGS API
# ============================================================================

@app.route('/api/update_settings/<server_id>', methods=['POST'])
@login_required
def api_update_settings(server_id):
    user = session['user']
    data = request.get_json()
    main_file = data.get('main_file', '').strip()
    req_file = data.get('requirements_file', '').strip()

    if not main_file or not req_file:
        return jsonify({'success': False, 'error': 'Both file names are required'}), 400

    # Security: ensure filenames are safe (no path traversal)
    if '..' in main_file or main_file.startswith('/') or main_file.startswith('\\'):
        return jsonify({'success': False, 'error': 'Invalid main file name'}), 400
    if '..' in req_file or req_file.startswith('/') or req_file.startswith('\\'):
        return jsonify({'success': False, 'error': 'Invalid requirements file name'}), 400

    if update_server_for_user(user, server_id, {'main_file': main_file, 'requirements_file': req_file}):
        return jsonify({'success': True, 'msg': 'Settings updated successfully'})
    return jsonify({'success': False, 'error': 'Server not found'}), 404

# ============================================================================
# 🛠️ UTILITY FUNCTIONS
# ============================================================================

def format_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size/(1024*1024):.1f} MB"
    else:
        return f"{size/(1024*1024*1024):.2f} GB"

def create_default_files(server_dir):
    main_py = os.path.join(server_dir, config.get('default_main_file', 'main.py'))
    if not os.path.exists(main_py):
        with open(main_py, 'w', encoding='utf-8') as f:
            f.write('''# 🚀 MOUHAMED HOSTING PRO - Bot Template
import time
import os
import sys

print("=" * 50)
print("     🚀 MOUHAMED HOSTING PRO")
print("     Your bot is running!")
print("=" * 50)
print(f"Python: {sys.version}")
print(f"Working Directory: {os.getcwd()}")
print("=" * 50)

counter = 0
while True:
    counter += 1
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] 💚 Heartbeat #{counter}")
    time.sleep(5)
''')

    req_file = os.path.join(server_dir, config.get('default_requirements_file', 'requirements.txt'))
    if not os.path.exists(req_file):
        with open(req_file, 'w', encoding='utf-8') as f:
            f.write('# 📦 MOUHAMED HOSTING - Requirements\n# Add your pip packages here\n# Example: requests==2.28.1\n')

# ============================================================================
# 🚀 STARTUP
# ============================================================================

if __name__ == '__main__':
    print("=" * 70)
    print(f"     🚀 {config['project_name']} - Enterprise Edition")
    print("     Premium Bot Hosting Platform")
    print("=" * 70)
    print(f"👤 Admin: {ADMIN_USERNAME}")
    # 🔐 Mask password in startup log
    print(f"🔑 Password: {'*' * len(ADMIN_PASSWORD)} (hashed on first run)")
    print(f"📁 Bots: {BOTS_DIR}")
    print(f"📊 Python: {sys.version.split()[0]}")
    print("=" * 70)
    print("✅ Server starting with enhanced security and UI...")
    print("=" * 70)

    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
