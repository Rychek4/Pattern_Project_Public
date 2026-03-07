# Pattern Project — VPS Setup Guide

## Complete Deployment on Ubuntu 24.04 (DigitalOcean)

This guide walks through every step of deploying Pattern Project on a fresh DigitalOcean
droplet, from creating the server to verifying a running, secured system. It is written
for a **single-user research deployment** and prioritizes practical security over
enterprise-grade hardening.

**Time estimate:** 30–45 minutes for a first-time setup.

---

## Table of Contents

1. [Before You Start — What You'll Need](#1-before-you-start--what-youll-need)
2. [Create the Droplet](#2-create-the-droplet)
3. [Initial Server Hardening](#3-initial-server-hardening)
4. [Deploy Pattern Project](#4-deploy-pattern-project)
5. [Configure Environment](#5-configure-environment)
   - [5.3 Migrating from an Existing Windows Installation](#53-migrating-from-an-existing-windows-installation)
6. [Configure Nginx and SSL](#6-configure-nginx-and-ssl)
7. [Install Guardian Watchdog](#7-install-guardian-watchdog)
8. [Start Everything](#8-start-everything)
9. [Verify the Deployment](#9-verify-the-deployment)
10. [Set Up Backups](#10-set-up-backups)
11. [Set Up Log Rotation](#11-set-up-log-rotation)
12. [Ongoing Maintenance](#12-ongoing-maintenance)
13. [Troubleshooting](#13-troubleshooting)
14. [Quick Reference](#14-quick-reference)

---

## 1. Before You Start — What You'll Need

Gather these before touching the server:

| Item | Where to get it | Required? |
|------|----------------|-----------|
| **DigitalOcean account** | [digitalocean.com](https://www.digitalocean.com/) | Yes |
| **Domain name** | Any registrar (Namecheap, Cloudflare, etc.) | Yes (for HTTPS) |
| **Anthropic API key** | [console.anthropic.com](https://console.anthropic.com/) | Yes |
| **OpenAI API key** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | Only for TTS voice |
| **SSH key pair** | `ssh-keygen -t ed25519` on your local machine | Yes |
| **Telegram bot token + chat ID** | @BotFather on Telegram | Only if using Telegram |

**Choose your auth password now.** You'll need a strong password for the web UI login.
A random passphrase works well — e.g., `openssl rand -base64 24` on your local machine.

> **Windows users:** This guide works from Windows 10/11. You'll SSH into the Ubuntu
> VPS and run server commands there — your local OS doesn't matter for those. The few
> commands you run locally (SSH, SCP, DNS checks) all work in **PowerShell** or
> **Windows Terminal**, which ship with Windows 11. Substitutions:
>
> | Guide shows (Linux/Mac) | Windows equivalent |
> |---|---|
> | `ssh-keygen -t ed25519` | Same — works in PowerShell |
> | `scp -r ./files root@IP:/path` | Same — works in PowerShell (use `\` paths) |
> | `openssl rand -base64 24` | Use `python -c "import secrets; print(secrets.token_urlsafe(24))"` or generate in the VPS after you SSH in |
> | `dig +short domain.com` | `nslookup domain.com` |
>
> If you're migrating from an existing Windows installation, see
> [Section 5.3](#53-migrating-from-an-existing-windows-installation).

---

## 2. Create the Droplet

### 2.1 Droplet Settings

Log in to DigitalOcean and create a new Droplet with these settings:

| Setting | Value |
|---------|-------|
| **Image** | Ubuntu 24.04 (LTS) x64 |
| **Plan** | Regular (shared CPU) — **2 vCPU, 4 GB RAM, 80 GB SSD** minimum |
| **Region** | Closest to you (latency matters for interactive use) |
| **Authentication** | SSH key (add your public key) |
| **Hostname** | Something memorable, e.g. `pattern` |

> **Why 4 GB RAM?** Pattern loads a sentence-transformer embedding model (~200 MB) plus
> the Python runtime, FastAPI, and background services. 2 GB will work but may swap under
> load. 4 GB gives comfortable headroom.

### 2.2 Point Your Domain

After the droplet is created, note its **public IP address**. Go to your domain registrar
and create an **A record**:

```
Type: A
Name: @ (or a subdomain like "pattern")
Value: <YOUR_DROPLET_IP>
TTL: 300
```

DNS propagation can take a few minutes to a few hours. You can check with:

```bash
dig +short your-domain.com
```

Continue with server setup while DNS propagates — you'll need it working by Step 6.

---

## 3. Initial Server Hardening

SSH into your new droplet:

```bash
ssh root@<YOUR_DROPLET_IP>
```

### 3.1 System Updates

```bash
apt update && apt upgrade -y
```

### 3.2 UFW Firewall

This is the single most important hardening step. Bots scan every DigitalOcean IP
within hours of provisioning.

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (for certbot + redirect to HTTPS)
ufw allow 443/tcp   # HTTPS
ufw enable
```

Verify:

```bash
ufw status
```

You should see three ALLOW rules and everything else denied.

> **Important:** Ports 5000 (Flask HTTP API) and 8080 (FastAPI web server) are intentionally
> NOT opened. They are accessed only through nginx on localhost. The firewall ensures they
> are never exposed to the internet.

### 3.3 fail2ban

Protects SSH from brute-force attacks. The defaults are good enough:

```bash
apt install -y fail2ban
systemctl enable fail2ban
systemctl start fail2ban
```

Verify it's running:

```bash
fail2ban-client status sshd
```

### 3.4 (Optional) Create a Non-Root SSH User

For extra security, you can create a personal admin user and disable root SSH login.
This is standard practice but not strictly required for a single-user research server.

```bash
adduser yourname
usermod -aG sudo yourname
# Copy your SSH key to the new user
rsync --archive --chown=yourname:yourname ~/.ssh /home/yourname
```

Then edit `/etc/ssh/sshd_config`:
```
PermitRootLogin no
```

And restart SSH: `systemctl restart sshd`

> **Test the new user login in a separate terminal before closing your root session.**

---

## 4. Deploy Pattern Project

### 4.1 Get the Code onto the Server

**Option A: Clone from Git** (recommended)

```bash
apt install -y git
git clone https://github.com/YOUR_USERNAME/Pattern_Project.git /tmp/pattern-source
```

**Option B: SCP from your local machine**

From your local machine:
```bash
scp -r /path/to/Pattern_Project root@<YOUR_DROPLET_IP>:/tmp/pattern-source
```

### 4.2 Run the Setup Script

The setup script handles everything: system packages, service user, virtualenv,
nginx config, and systemd service.

```bash
cd /tmp/pattern-source
chmod +x deploy/setup.sh
sudo ./deploy/setup.sh
```

**What setup.sh does:**
1. Installs system packages (Python 3, nginx, certbot)
2. Creates a `pattern` system user with home at `/opt/pattern`
3. Copies project files to `/opt/pattern`
4. Creates a Python virtualenv and installs all dependencies
5. Creates `data/`, `data/files/`, `logs/`, and `backups/` directories
6. Copies `.env.example` to `.env` (with `chmod 600`)
7. Sets ownership of `/opt/pattern` to the `pattern` user
8. Configures nginx as a reverse proxy
9. Installs and enables the systemd service

When it finishes, you'll see the remaining manual steps.

### 4.3 Install Playwright (for Browser Delegation)

If you plan to use the delegate browser agent (for posting to Reddit, BearBlog, etc.):

```bash
sudo -u pattern bash -c 'cd /opt/pattern && source venv/bin/activate && playwright install chromium && playwright install-deps'
```

This installs a headless Chromium browser. Skip if you don't need browser automation.

---

## 5. Configure Environment

### 5.1 Edit the .env File

```bash
sudo nano /opt/pattern/.env
```

Here is a complete reference of what to set. Lines beginning with `#` are commented
out (disabled). Uncomment and fill in the ones you need.

```bash
# ==========================================================================
# REQUIRED
# ==========================================================================
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here

# Web UI authentication — set a STRONG password
WEB_AUTH_PASSWORD=your-strong-password-here

# ==========================================================================
# LLM SETTINGS (optional — sensible defaults exist)
# ==========================================================================
# ANTHROPIC_MODEL=claude-opus-4-6
# ANTHROPIC_MODEL_CONVERSATION=claude-sonnet-4-6

# OpenAI key (only needed for text-to-speech voice synthesis)
# OPENAI_API_KEY=sk-your-openai-key-here

# ==========================================================================
# FEATURES TO DISABLE ON VPS (no desktop hardware)
# ==========================================================================
VISUAL_ENABLED=false
VISUAL_SCREENSHOT_MODE=disabled
VISUAL_WEBCAM_MODE=disabled

# ==========================================================================
# FEATURES TO CONFIGURE (optional)
# ==========================================================================
# Telegram — uncomment and fill in if using
# TELEGRAM_ENABLED=true
# telegram_bot=your-bot-token
# TELEGRAM_CHAT_ID=your-chat-id

# Reddit — uncomment if using
# REDDIT_ENABLED=true
# REDDIT_CLIENT_ID=your-client-id
# REDDIT_CLIENT_SECRET=your-secret
# REDDIT_USERNAME=your-username
# REDDIT_PASSWORD=your-password
# REDDIT_USER_AGENT=python:pattern-agent:v1.0 (by /u/your_username)

# ==========================================================================
# VPS-SPECIFIC SETTINGS (defaults are fine, listed for reference)
# ==========================================================================
# WEB_HOST=0.0.0.0
# WEB_PORT=8080
# HTTP_HOST=127.0.0.1
# HTTP_PORT=5000
# LOG_LEVEL=INFO

# ==========================================================================
# GUARDIAN WATCHDOG (configure after installing Guardian — see Step 7)
# ==========================================================================
# GUARDIAN_ENABLED=true
# GUARDIAN_EXECUTABLE_PATH=/opt/guardian/guardian.py
# GUARDIAN_CONFIG_PATH=/opt/guardian/guardian.toml
```

Save and exit (`Ctrl+X`, `Y`, `Enter` in nano).

### 5.2 Set Permissions on Credential Files

The setup script already sets `.env` to `chmod 600`. Also secure the credentials
file if you plan to use browser delegation:

```bash
# Copy and configure the credentials template (only if using browser delegation)
sudo -u pattern cp /opt/pattern/credentials.toml.example /opt/pattern/data/credentials.toml
sudo chmod 600 /opt/pattern/data/credentials.toml

# Edit with your service credentials
sudo nano /opt/pattern/data/credentials.toml
```

The credentials file uses TOML format — one section per service:

```toml
[reddit]
username = "my_reddit_username"
password = "my_reddit_password"
login_url = "https://www.reddit.com/login/"

[bearblog]
username = "me@example.com"
password = "my_password"
login_url = "https://bearblog.dev/accounts/login/"
dashboard_url = "https://bearblog.dev/dashboard/"
```

### 5.3 Migrating from an Existing Windows Installation

If you're moving Pattern Project from a working Windows setup to this VPS (rather than
starting fresh), follow this section to transfer your database, configuration, and
credentials. Skip this section if this is a brand-new deployment.

#### What to Migrate

| File | Windows location (typical) | VPS destination | Priority |
|------|---------------------------|-----------------|----------|
| `pattern.db` | `Pattern_Project\data\pattern.db` | `/opt/pattern/data/pattern.db` | **CRITICAL** — all memories, conversations, embeddings |
| `.env` | `Pattern_Project\.env` | `/opt/pattern/.env` | **HIGH** — API keys and config |
| `credentials.toml` | `Pattern_Project\data\credentials.toml` | `/opt/pattern/data/credentials.toml` | MEDIUM — only if using browser delegation |
| `user_settings.json` | `Pattern_Project\data\user_settings.json` | `/opt/pattern/data/user_settings.json` | LOW — voice/UI preferences (easy to recreate) |

> **Good news:** SQLite databases are fully cross-platform. A `pattern.db` created on
> Windows works identically on Ubuntu — no conversion or export needed. Just copy the file.

#### Step 1: Locate Your Files on Windows

Open PowerShell and find your existing Pattern data:

```powershell
# Find your database (adjust the path to where you cloned Pattern_Project)
dir "$env:USERPROFILE\Pattern_Project\data\pattern.db"

# Check .env exists
dir "$env:USERPROFILE\Pattern_Project\.env"

# Check for credentials
dir "$env:USERPROFILE\Pattern_Project\data\credentials.toml"
dir "$env:USERPROFILE\Pattern_Project\data\user_settings.json"
```

If your project lives somewhere else (e.g., `C:\Projects\Pattern_Project`), adjust
the paths accordingly.

#### Step 2: Stop Pattern on the VPS (if running)

SSH into your VPS and stop the service so you can safely replace the database:

```bash
sudo systemctl stop pattern
```

#### Step 3: Transfer Files from Windows

Run these commands from **PowerShell on your Windows machine**. The `scp` command is
built into Windows 11 (via OpenSSH).

```powershell
# Transfer the database (MOST IMPORTANT)
scp "$env:USERPROFILE\Pattern_Project\data\pattern.db" root@YOUR_DROPLET_IP:/opt/pattern/data/pattern.db

# Transfer .env (you'll adjust it in the next step)
scp "$env:USERPROFILE\Pattern_Project\.env" root@YOUR_DROPLET_IP:/opt/pattern/.env

# Transfer credentials (only if you use browser delegation)
scp "$env:USERPROFILE\Pattern_Project\data\credentials.toml" root@YOUR_DROPLET_IP:/opt/pattern/data/credentials.toml

# Transfer user settings (optional)
scp "$env:USERPROFILE\Pattern_Project\data\user_settings.json" root@YOUR_DROPLET_IP:/opt/pattern/data/user_settings.json
```

> **Tip:** If your SSH key isn't at the default location, add `-i C:\Users\YourName\.ssh\id_ed25519`
> to each `scp` command.
>
> **Alternative:** If SCP gives you trouble, you can also use [WinSCP](https://winscp.net/)
> (a free GUI tool) to drag and drop files to the server.

#### Step 4: Fix Ownership and Permissions on the VPS

After transferring, the files will be owned by root. Fix that:

```bash
# Set correct ownership (pattern user must own these files)
sudo chown pattern:pattern /opt/pattern/.env
sudo chown pattern:pattern /opt/pattern/data/pattern.db
sudo chown pattern:pattern /opt/pattern/data/credentials.toml 2>/dev/null
sudo chown pattern:pattern /opt/pattern/data/user_settings.json 2>/dev/null

# Lock down sensitive files
sudo chmod 600 /opt/pattern/.env
sudo chmod 600 /opt/pattern/data/credentials.toml 2>/dev/null
```

#### Step 5: Adjust Your .env for the VPS

Your Windows `.env` likely has desktop features enabled that won't work on a headless
VPS. SSH into the server and edit:

```bash
sudo nano /opt/pattern/.env
```

Make these changes:

```bash
# DISABLE these (no desktop/display on a VPS)
VISUAL_ENABLED=false
VISUAL_SCREENSHOT_MODE=disabled
VISUAL_WEBCAM_MODE=disabled
```

Everything else — API keys, Telegram tokens, email settings — carries over as-is.
No paths in `.env` reference Windows-style paths, so no path conversion is needed.

#### Step 6: Verify the Database

Confirm the database transferred correctly:

```bash
# Check it exists and has content
ls -lh /opt/pattern/data/pattern.db

# Run an integrity check
sudo -u pattern sqlite3 /opt/pattern/data/pattern.db "PRAGMA integrity_check;"
# Should output: ok

# Quick sanity check — count your memories
sudo -u pattern sqlite3 /opt/pattern/data/pattern.db "SELECT COUNT(*) FROM memories;" 2>/dev/null
```

If the integrity check passes, your data made it safely.

#### Step 7: Continue with the Guide

Your data is now on the VPS. Continue with [Section 6 (Nginx and SSL)](#6-configure-nginx-and-ssl)
and the remaining sections to finish the deployment. When you reach
[Section 8 (Start Everything)](#8-start-everything), Pattern will start up with all
your existing memories, conversations, and settings intact.

---

## 6. Configure Nginx and SSL

### 6.1 Set Your Domain in Nginx

```bash
sudo nano /etc/nginx/sites-available/pattern
```

Replace every instance of `YOUR_DOMAIN` with your actual domain name. There are
**three occurrences** — two `server_name` directives and one in the commented SSL
certificate paths.

Example: if your domain is `pattern.example.com`, you'd have:
```nginx
server_name pattern.example.com;
```

Save and test the config:

```bash
sudo nginx -t
```

If it says "syntax is ok" and "test is successful", reload:

```bash
sudo systemctl reload nginx
```

### 6.2 Get an SSL Certificate with Certbot

Make sure your domain's DNS has propagated (the A record points to your droplet IP)
before running this:

```bash
sudo certbot --nginx -d your-domain.com
```

Certbot will:
1. Verify domain ownership via HTTP challenge
2. Obtain a Let's Encrypt certificate
3. Automatically modify the nginx config to enable SSL
4. Set up automatic renewal (via a systemd timer)

Verify auto-renewal works:

```bash
sudo certbot renew --dry-run
```

### 6.3 What the Nginx Config Provides

The included `deploy/nginx.conf` gives you:

- **HTTP → HTTPS redirect** on port 80
- **SSL termination** on port 443
- **Security headers:** X-Frame-Options, X-Content-Type-Options, X-XSS-Protection
- **Rate limiting** on `/auth/login` — 5 requests per minute (brute-force protection)
- **WebSocket proxying** at `/ws` with 24-hour timeout (for live chat sessions)
- **Reverse proxy** to FastAPI on `127.0.0.1:8080`

---

## 7. Install Guardian Watchdog

Guardian is a **separate, standalone process** that monitors Pattern's health and
restarts it on failure. It's the reliability layer on top of systemd's built-in
restart. A complete specification lives at `docs/GUARDIAN_SPEC.md` in the Pattern
repo.

> **Note:** Guardian is designed as a separate project with zero external dependencies
> (Python standard library only). If Guardian hasn't been built yet, you can skip
> this section and rely on systemd's built-in `Restart=on-failure` — which is already
> configured in `pattern.service`. Come back and add Guardian later.

### 7.1 Install Guardian

```bash
# Clone the Guardian repository
sudo mkdir -p /opt/guardian
sudo git clone https://github.com/YOUR_USERNAME/Guardian.git /opt/guardian
sudo chown -R pattern:pattern /opt/guardian
```

### 7.2 Configure Guardian

Create or edit the Guardian config file:

```bash
sudo -u pattern nano /opt/guardian/guardian.toml
```

Adjust paths and settings for your VPS deployment:

```toml
[pattern]
project_dir = "/opt/pattern"
launch_command = "python main.py"
virtualenv_activate = "/opt/pattern/venv/bin/activate"
health_url = "http://127.0.0.1:5000/health"
stats_url = "http://127.0.0.1:5000/stats"
startup_grace_seconds = 60

[guardian]
check_interval = 30
max_consecutive_failures = 3
shutdown_timeout = 15
log_file = "/opt/pattern/logs/guardian.log"
log_rotation_max_bytes = 52428800

[recovery]
restart_cooldown = 60
max_restarts_per_hour = 5
max_consecutive_restart_failures = 10
```

> **Note:** Pattern defaults to web mode (FastAPI) when launched without flags.
> Use `--cli` only if you want the console interface instead.

### 7.3 Configure Pattern to Talk to Guardian

Edit Pattern's `.env` to point to Guardian:

```bash
sudo nano /opt/pattern/.env
```

Uncomment and set:

```bash
GUARDIAN_ENABLED=true
GUARDIAN_EXECUTABLE_PATH=/opt/guardian/guardian.py
GUARDIAN_CONFIG_PATH=/opt/guardian/guardian.toml
```

### 7.4 Create a systemd Service for Guardian

This creates the full supervision chain: systemd → Guardian → Pattern → Guardian.

```bash
sudo tee /etc/systemd/system/pattern-guardian.service > /dev/null << 'EOF'
[Unit]
Description=Pattern Project Guardian Watchdog
After=network.target

[Service]
Type=simple
User=pattern
Group=pattern
WorkingDirectory=/opt/guardian
ExecStart=/opt/pattern/venv/bin/python /opt/guardian/guardian.py --config /opt/guardian/guardian.toml
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pattern-guardian

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable pattern-guardian
```

### 7.5 How the Supervision Chain Works

```
systemd
  └── pattern-guardian.service (Restart=always)
        └── Guardian process
              └── Monitors Pattern via /health endpoint
                    └── Restarts Pattern on failure
                          └── Pattern checks Guardian heartbeat
                                └── Respawns Guardian if missing
```

Three independent layers of resilience. If any single piece fails, the others bring
it back.

---

## 8. Start Everything

### 8.1 Start Pattern

```bash
sudo systemctl start pattern
```

Watch the startup logs (Pattern takes 10–30 seconds to initialize — it loads an
embedding model on first run):

```bash
sudo journalctl -u pattern -f
```

Wait until you see the web server start message, then `Ctrl+C` to stop following.

### 8.2 Start Guardian (if installed)

```bash
sudo systemctl start pattern-guardian
```

Verify:

```bash
sudo journalctl -u pattern-guardian -f
```

You should see Guardian detecting Pattern as healthy.

---

## 9. Verify the Deployment

Run through this checklist to confirm everything is working:

### 9.1 Service Status

```bash
sudo systemctl status pattern
sudo systemctl status pattern-guardian   # if installed
sudo systemctl status nginx
```

All should show `active (running)`.

### 9.2 Health Endpoints

```bash
# FastAPI health (internal — via localhost)
curl http://127.0.0.1:8080/health

# Flask API health (internal — via localhost)
curl http://127.0.0.1:5000/health

# Public HTTPS (via nginx)
curl -I https://your-domain.com
```

### 9.3 Web UI

Open `https://your-domain.com` in your browser. You should see the login page.
Log in with the `WEB_AUTH_PASSWORD` you configured.

### 9.4 SSL Certificate

```bash
# Check certificate details
echo | openssl s_client -connect your-domain.com:443 2>/dev/null | openssl x509 -noout -dates
```

### 9.5 Firewall

```bash
# Confirm only SSH, HTTP, and HTTPS are open
sudo ufw status

# Confirm internal ports are NOT reachable from outside
# (Run this from your LOCAL machine, not the server)
curl http://<YOUR_DROPLET_IP>:8080   # Should timeout/refuse
curl http://<YOUR_DROPLET_IP>:5000   # Should timeout/refuse
```

### 9.6 Guardian Heartbeat (if installed)

```bash
cat /opt/pattern/data/guardian_heartbeat.json
```

Should show a recent timestamp and `pattern_state: "HEALTHY"`.

---

## 10. Set Up Backups

**This is the most important maintenance task for a research project.** Your memories,
conversations, and growth threads are irreplaceable research data.

### 10.1 What to Back Up

| File | Priority | Why |
|------|----------|-----|
| `/opt/pattern/data/pattern.db` | **CRITICAL** | All memories, conversations, sessions, embeddings |
| `/opt/pattern/.env` | HIGH | Your configuration (API keys, passwords) |
| `/opt/pattern/data/credentials.toml` | MEDIUM | Service login credentials (if used) |
| `/opt/pattern/data/user_settings.json` | LOW | Voice preferences (easy to recreate) |

### 10.2 Simple Daily Backup with Cron

This creates a daily SQLite backup using `.backup` (safe even while Pattern is running)
and keeps the last 7 days:

```bash
sudo tee /opt/pattern/scripts/backup.sh > /dev/null << 'BACKUP'
#!/usr/bin/env bash
# Pattern Project — Daily Database Backup
set -euo pipefail

BACKUP_DIR="/opt/pattern/backups"
DB_PATH="/opt/pattern/data/pattern.db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

# Use SQLite's .backup command (safe for WAL-mode databases)
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/pattern_${TIMESTAMP}.db'"

# Remove backups older than KEEP_DAYS
find "$BACKUP_DIR" -name "pattern_*.db" -mtime +${KEEP_DAYS} -delete

echo "Backup complete: pattern_${TIMESTAMP}.db"
BACKUP

sudo chmod +x /opt/pattern/scripts/backup.sh
sudo chown pattern:pattern /opt/pattern/scripts/backup.sh
sudo mkdir -p /opt/pattern/backups
sudo chown pattern:pattern /opt/pattern/backups
```

Add to pattern user's crontab:

```bash
sudo -u pattern crontab -e
```

Add this line (runs daily at 3 AM):

```cron
0 3 * * * /opt/pattern/scripts/backup.sh >> /opt/pattern/logs/backup.log 2>&1
```

### 10.3 (Optional) Off-Server Backups with DigitalOcean Spaces

For extra safety, push backups off the server. Install the `s3cmd` tool:

```bash
apt install -y s3cmd
s3cmd --configure   # Enter your DO Spaces credentials
```

Add to the backup script (after the sqlite3 line):

```bash
s3cmd put "$BACKUP_DIR/pattern_${TIMESTAMP}.db" s3://your-bucket-name/pattern-backups/
```

### 10.4 (Alternative) DigitalOcean Droplet Backups

DigitalOcean offers automatic weekly droplet snapshots for 20% of the droplet cost.
Enable under **Droplet → Backups** in the DO control panel. This backs up the entire
server image, not just the database.

### 10.5 (Optional) Google Drive Backups

Pattern can upload compressed backups directly to Google Drive. Each backup is
a `.tar.gz` archive containing the SQLite database snapshot and the entire
`data/files/` directory (user writings, journals, novels). Uses the `drive.file`
scope so it can only see files it created — it cannot access any of your
personal Drive files.

**One-time setup:**

1. In [Google Cloud Console](https://console.cloud.google.com), go to the same
   project you used for Google Calendar (or create a new one).
2. Enable the **Google Drive API** (APIs & Services → Library → search "Drive").
3. You can reuse the same OAuth2 credentials file (`Calendar_Google_Credentials.json`).
4. Set the following in your `.env`:

```bash
GOOGLE_DRIVE_BACKUP_ENABLED=true
# These defaults are usually fine:
# GOOGLE_DRIVE_BACKUP_CREDENTIALS_PATH=data/Calendar_Google_Credentials.json
# GOOGLE_DRIVE_BACKUP_TOKEN_PATH=data/Drive_Google_Token.json
# GOOGLE_DRIVE_BACKUP_FOLDER_NAME=Pattern Backups
# GOOGLE_DRIVE_BACKUP_RETENTION_COUNT=7
```

5. On first use, a browser window opens for OAuth consent. After consent, the
   token is saved and auto-refreshes (no browser needed again).

**Running a backup** (from the Pattern project directory):

```bash
cd /opt/pattern
source venv/bin/activate
python -c "
from communication.drive_backup_gateway import init_drive_backup_gateway, run_drive_backup
init_drive_backup_gateway()
result = run_drive_backup()
print(result)
"
```

**Automated daily backups** — add to the `pattern` user's crontab:

```bash
crontab -e
# Add this line (runs at 4 AM daily, after the local backup at 3 AM):
0 4 * * * cd /opt/pattern && source venv/bin/activate && python -c "from communication.drive_backup_gateway import init_drive_backup_gateway, run_drive_backup; init_drive_backup_gateway(); print(run_drive_backup())" >> /opt/pattern/logs/drive_backup.log 2>&1
```

Backups are stored in a "Pattern Backups" folder on Drive as `.tar.gz` archives
containing both the database and user files. Old backups beyond the retention
count (default 7) are automatically deleted after each upload.

---

## 11. Set Up Log Rotation

Without log rotation, `diagnostic.log` will eventually fill your disk.

### 11.1 System Logrotate

```bash
sudo tee /etc/logrotate.d/pattern > /dev/null << 'LOGROTATE'
/opt/pattern/logs/diagnostic.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 50M
}

/opt/pattern/logs/guardian.log {
    daily
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 20M
}
LOGROTATE
```

Test it:

```bash
sudo logrotate -d /etc/logrotate.d/pattern
```

The `-d` flag does a dry run — it shows what would happen without actually rotating.

> **Note:** `copytruncate` is used instead of the standard rotate-and-create approach
> because Pattern holds the log file open. This truncates the file in place after
> copying, so Pattern continues writing without needing a restart or signal.

---

## 12. Ongoing Maintenance

### 12.1 Updating Pattern

```bash
cd /opt/pattern

# Stop the service
sudo systemctl stop pattern

# Pull latest code (if using git)
sudo -u pattern git pull origin main

# Update dependencies
sudo -u pattern bash -c 'source venv/bin/activate && pip install -r requirements.txt -q'

# Restart
sudo systemctl start pattern

# Verify
sudo journalctl -u pattern -n 30
```

### 12.2 Monitoring

**Quick status check:**

```bash
# Is Pattern running?
sudo systemctl status pattern

# Recent logs (last 50 lines)
sudo journalctl -u pattern -n 50

# Is Guardian healthy? (if installed)
cat /opt/pattern/data/guardian_heartbeat.json

# Disk usage
df -h /opt/pattern
du -sh /opt/pattern/data/pattern.db

# Memory usage
free -h
```

**Check from outside the server:**

```bash
curl -s https://your-domain.com/health
```

### 12.3 SSL Certificate Renewal

Certbot sets up automatic renewal via a systemd timer. Certificates renew when they're
within 30 days of expiry. Verify the timer is active:

```bash
sudo systemctl list-timers | grep certbot
```

If you ever need to manually renew:

```bash
sudo certbot renew
sudo systemctl reload nginx
```

---

## 13. Troubleshooting

### Pattern won't start

```bash
# Check what went wrong
sudo journalctl -u pattern -n 100 --no-pager

# Common causes:
# - Missing ANTHROPIC_API_KEY in .env
# - Python dependency not installed
# - Port 8080 already in use
```

### Can't access the web UI

```bash
# Is Pattern running?
sudo systemctl status pattern

# Is nginx running?
sudo systemctl status nginx

# Can you reach the app locally?
curl http://127.0.0.1:8080/health

# Check nginx error log
sudo tail -20 /var/log/nginx/error.log

# Check firewall
sudo ufw status
```

### SSL certificate issues

```bash
# Check certificate status
sudo certbot certificates

# Force renewal
sudo certbot renew --force-renewal
sudo systemctl reload nginx
```

### Database issues

```bash
# Check database integrity (stop Pattern first!)
sudo systemctl stop pattern
sudo -u pattern sqlite3 /opt/pattern/data/pattern.db "PRAGMA integrity_check;"
sudo systemctl start pattern

# Check database size
du -sh /opt/pattern/data/pattern.db*
```

### Guardian not starting

```bash
# Check Guardian logs
sudo journalctl -u pattern-guardian -n 50

# Check heartbeat file
cat /opt/pattern/data/guardian_heartbeat.json

# Verify Guardian can reach Pattern's health endpoint
curl http://127.0.0.1:5000/health
```

### Out of disk space

```bash
# What's using space?
du -sh /opt/pattern/data/*
du -sh /opt/pattern/logs/*

# Force log rotation
sudo logrotate -f /etc/logrotate.d/pattern

# Clean old backups
ls -la /opt/pattern/backups/
```

---

## 14. Quick Reference

### Service Commands

| Action | Command |
|--------|---------|
| Start Pattern | `sudo systemctl start pattern` |
| Stop Pattern | `sudo systemctl stop pattern` |
| Restart Pattern | `sudo systemctl restart pattern` |
| View Pattern logs | `sudo journalctl -u pattern -f` |
| Start Guardian | `sudo systemctl start pattern-guardian` |
| Stop Guardian | `sudo systemctl stop pattern-guardian` |
| View Guardian logs | `sudo journalctl -u pattern-guardian -f` |
| Reload nginx | `sudo systemctl reload nginx` |
| Renew SSL | `sudo certbot renew && sudo systemctl reload nginx` |

### Key File Locations

| File | Purpose |
|------|---------|
| `/opt/pattern/.env` | API keys, passwords, feature toggles |
| `/opt/pattern/data/pattern.db` | Main SQLite database (all memories, conversations) |
| `/opt/pattern/data/credentials.toml` | Service login credentials for browser delegation |
| `/opt/pattern/logs/diagnostic.log` | Pattern application log |
| `/opt/pattern/logs/guardian.log` | Guardian watchdog log |
| `/opt/pattern/data/guardian_heartbeat.json` | Guardian ↔ Pattern liveness proof |
| `/etc/nginx/sites-available/pattern` | Nginx reverse proxy config |
| `/etc/systemd/system/pattern.service` | Pattern systemd service |
| `/etc/systemd/system/pattern-guardian.service` | Guardian systemd service |
| `/etc/logrotate.d/pattern` | Log rotation config |

### Ports

| Port | Service | Accessible from internet? |
|------|---------|--------------------------|
| 22 | SSH | Yes (via UFW) |
| 80 | HTTP (redirects to 443) | Yes (via UFW) |
| 443 | HTTPS (nginx → Pattern) | Yes (via UFW) |
| 5000 | Flask HTTP API | No (localhost only) |
| 8080 | FastAPI Web UI | No (localhost only, via nginx) |

### Architecture Diagram

```
Internet
    │
    ▼
┌──────────────────────┐
│  UFW Firewall        │  Only ports 22, 80, 443 open
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  nginx :443          │  SSL termination, security headers,
│                      │  rate limiting, WebSocket proxy
└──────────┬───────────┘
           │  proxy_pass http://127.0.0.1:8080
           ▼
┌──────────────────────┐
│  Pattern (FastAPI)   │  Web UI, chat, memories, voice
│  :8080 (localhost)   │  Background: pulse, reminders,
│                      │  Telegram, extraction, Guardian check
└──────────┬───────────┘
           │  mutual health checks
           ▼
┌──────────────────────┐
│  Guardian Watchdog   │  Monitors /health, restarts on failure,
│  (separate process)  │  DB integrity checks, log rotation
└──────────────────────┘
           │
           ▼
┌──────────────────────┐
│  systemd             │  Restarts Guardian if it dies
│  (pattern-guardian)  │  Restarts Pattern if it dies (fallback)
└──────────────────────┘
```

---

## Appendix A: Feature Toggles Reference

All features are configured via environment variables in `.env`. For a VPS deployment,
here's what makes sense to enable vs. disable:

| Feature | Default | VPS Recommendation | Why |
|---------|---------|-------------------|-----|
| `INTENTION_ENABLED` | true | **Keep on** | Reminders, goals, plans |
| `SYSTEM_PULSE_ENABLED` | true | **Keep on** | Autonomous self-prompting |
| `CURIOSITY_ENABLED` | true | **Keep on** | Topic exploration |
| `GROWTH_THREADS_ENABLED` | true | **Keep on** | Long-running growth arcs |
| `WEB_SEARCH_ENABLED` | true | **Keep on** | Claude's built-in web search |
| `WEB_FETCH_ENABLED` | true | **Keep on** | Page fetching |
| `NOVEL_READING_ENABLED` | true | **Keep on** | Literary ingestion |
| `TELEGRAM_ENABLED` | true | Your choice | Requires bot token |
| `REDDIT_ENABLED` | false | Your choice | Requires Reddit API credentials |
| `GOOGLE_CALENDAR_ENABLED` | false | Your choice | Requires Google OAuth credentials |
| `GOOGLE_DRIVE_BACKUP_ENABLED` | false | Your choice | Off-server database backups |
| `VISUAL_ENABLED` | true | **Disable** | No display/webcam on VPS |

## Appendix B: The .env File

`deploy/setup.sh` copies `.env.example` to `.env`. This file documents every
available variable with comments. Edit it to set your API keys and feature toggles.

## Appendix C: Systemd Service Hardening

The included `pattern.service` applies these security restrictions:

| Directive | Effect |
|-----------|--------|
| `NoNewPrivileges=yes` | Prevents privilege escalation |
| `ProtectSystem=strict` | Makes `/usr`, `/boot`, `/efi` read-only |
| `ProtectHome=yes` | Makes `/home`, `/root`, `/run/user` inaccessible |
| `ReadWritePaths=/opt/pattern/data /opt/pattern/logs /opt/pattern/backups` | Only these directories are writable |
| `PrivateTmp=yes` | Gives Pattern its own `/tmp` |
| `LimitNOFILE=65535` | Generous file descriptor limit |

Pattern can only write to its `data/`, `logs/`, and `backups/` directories. Everything
else on the filesystem is read-only or invisible to the process.
