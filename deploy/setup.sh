#!/usr/bin/env bash
# Pattern Project - VPS Setup Script
#
# Run as root on a fresh Ubuntu 22.04+ VPS:
#   chmod +x setup.sh && sudo ./setup.sh
#
# After running, configure:
#   1. Edit /opt/pattern/.env with your API keys and auth password
#   2. Edit /etc/nginx/sites-available/pattern (replace YOUR_DOMAIN)
#   3. sudo certbot --nginx -d YOUR_DOMAIN
#   4. sudo systemctl restart pattern

set -euo pipefail

echo "=== Pattern Project VPS Setup ==="

# --- System packages ---
echo "Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    nginx certbot python3-certbot-nginx \
    git curl

# --- Create service user ---
if ! id -u pattern &>/dev/null; then
    echo "Creating 'pattern' user..."
    useradd --system --create-home --home-dir /opt/pattern --shell /bin/bash pattern
fi

# --- Deploy code ---
echo "Setting up application directory..."
APP_DIR=/opt/pattern
mkdir -p "$APP_DIR"

# If running from the repo, copy files
if [ -f "$(dirname "$0")/../main.py" ]; then
    echo "Copying project files..."
    rsync -a --exclude='venv' --exclude='__pycache__' --exclude='.git' \
        "$(dirname "$0")/../" "$APP_DIR/"
fi

# --- Python virtual environment ---
echo "Setting up Python environment..."
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip -q
pip install -r requirements.txt -q

# Create data and logs directories
mkdir -p data data/files logs
chown -R pattern:pattern "$APP_DIR"

# --- Environment file template ---
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Creating .env template..."
    cat > "$ENV_FILE" << 'ENVEOF'
# Pattern Project - Environment Configuration
# Fill in your values and restart the service

# Required
ANTHROPIC_API_KEY=your-key-here

# Web UI authentication (set a strong password!)
WEB_AUTH_PASSWORD=change-me

# Optional
# WEB_HOST=0.0.0.0
# WEB_PORT=8080
# TELEGRAM_ENABLED=false
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
# EMAIL_GATEWAY_ENABLED=false
# VISUAL_ENABLED=false
ENVEOF
    chown pattern:pattern "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "  Created $ENV_FILE (edit with your API keys!)"
fi

# --- nginx ---
echo "Configuring nginx..."
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/pattern
ln -sf /etc/nginx/sites-available/pattern /etc/nginx/sites-enabled/
# Remove default if it exists
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# --- systemd service ---
echo "Installing systemd service..."
cp "$APP_DIR/deploy/pattern.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable pattern

# --- Firewall ---
echo "Configuring firewall..."
if command -v ufw &>/dev/null; then
    ufw allow OpenSSH
    ufw allow 'Nginx Full'
    ufw --force enable
    echo "  UFW enabled (SSH + Nginx allowed)"
else
    echo "  UFW not found, skipping firewall setup"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit /opt/pattern/.env with your API keys and auth password"
echo "  2. Edit /etc/nginx/sites-available/pattern (replace YOUR_DOMAIN)"
echo "  3. sudo certbot --nginx -d YOUR_DOMAIN"
echo "  4. sudo systemctl start pattern"
echo "  5. sudo systemctl status pattern"
echo "  6. Visit https://YOUR_DOMAIN in your browser"
echo ""
