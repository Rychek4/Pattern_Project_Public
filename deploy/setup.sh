#!/usr/bin/env bash
# Pattern Project - Ubuntu VPS Setup
# Run as root on a fresh Ubuntu 22.04+ droplet after cloning the repo.
#
# Prerequisites (do these first):
#   - UFW configured (22, 80, 443)
#   - fail2ban installed and running
#
# Usage:
#   cd /opt/pattern
#   chmod +x deploy/setup.sh
#   sudo ./deploy/setup.sh

set -euo pipefail

APP_DIR=/opt/pattern

echo "=== Pattern Project Setup ==="

# System packages
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv \
    nginx certbot python3-certbot-nginx

# Python environment
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Directories
mkdir -p data data/files logs

# .env from template
cp .env.example .env
chmod 600 .env
echo ">>> Edit .env with your API keys and auth password"

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
echo "  1. nano .env                                          # API keys + password"
echo "  2. nano /etc/nginx/sites-available/pattern            # set domain"
echo "  3. certbot --nginx -d YOUR_DOMAIN"
echo "  4. systemctl start pattern"
