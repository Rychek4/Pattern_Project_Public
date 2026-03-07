#!/usr/bin/env bash
# Pattern Project - Ubuntu VPS Setup
# Run as root from the cloned repo (e.g. /tmp/pattern-source).
#
# Prerequisites (do these first):
#   - UFW configured (22, 80, 443)
#   - fail2ban installed and running
#
# Usage:
#   git clone <repo-url> /tmp/pattern-source
#   cd /tmp/pattern-source
#   chmod +x deploy/setup.sh
#   sudo ./deploy/setup.sh

set -euo pipefail

APP_DIR=/opt/pattern

echo "=== Pattern Project Setup ==="

# System packages
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv \
    nginx certbot python3-certbot-nginx

# Create service user
if ! id -u pattern &>/dev/null; then
    useradd --system --create-home --home-dir "$APP_DIR" --shell /bin/bash pattern
    echo "Created 'pattern' user"
fi

# Copy project files to /opt/pattern
echo "Copying project files..."
mkdir -p "$APP_DIR"
rsync -a --exclude='venv' --exclude='__pycache__' --exclude='.git' \
    "$(dirname "$0")/../" "$APP_DIR/"

# Python environment
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Directories
mkdir -p data data/files logs backups

# .env from template
cp .env.example .env
chmod 600 .env
echo ">>> Edit .env with your API keys and auth password"

# Set ownership
chown -R pattern:pattern "$APP_DIR"

# nginx
cp deploy/nginx.conf /etc/nginx/sites-available/pattern
ln -sf /etc/nginx/sites-available/pattern /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
echo ">>> Edit /etc/nginx/sites-available/pattern — replace YOUR_DOMAIN"
nginx -t
systemctl reload nginx

# systemd service
cp deploy/pattern.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable pattern

echo ""
echo "=== Done ==="
echo "Remaining:"
echo "  1. nano $APP_DIR/.env                                 # API keys + password"
echo "  2. nano /etc/nginx/sites-available/pattern            # set domain"
echo "  3. certbot --nginx -d YOUR_DOMAIN"
echo "  4. systemctl start pattern"
