#!/bin/bash
# DigitalOcean Setup Script for Ceefax Station Website
# Run this on your DigitalOcean droplet as root

set -e  # Exit on error

echo "=== Ceefax Station Website - DigitalOcean Setup ==="
echo ""

# Step 1: Update system
echo "[1/10] Updating system packages..."
apt update && apt upgrade -y

# Step 2: Install dependencies
echo "[2/10] Installing dependencies..."
apt install -y python3 python3-pip python3-venv git nginx sqlite3 certbot python3-certbot-nginx ufw

# Step 3: Create non-root user (optional but recommended)
echo "[3/10] Creating ceefax user..."
if ! id "ceefax" &>/dev/null; then
    adduser --disabled-password --gecos "" ceefax
    usermod -aG sudo ceefax
    echo "User 'ceefax' created"
else
    echo "User 'ceefax' already exists"
fi

# Step 4: Clone repository
echo "[4/10] Cloning repository..."
cd /root
if [ -d "ceefax_station" ]; then
    echo "Repository already exists, updating..."
    cd ceefax_station
    git pull
else
    git clone https://github.com/thaum-labs/ceefax_station.git
    cd ceefax_station
fi

# Step 5: Create virtual environment and install dependencies
echo "[5/10] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r ceefax/requirements.txt

# Step 6: Create .env file
echo "[6/10] Creating .env file..."
if [ ! -f .env ]; then
  cat > .env << 'EOF'
# Web server
CEEFAXWEB_HOST=127.0.0.1
CEEFAXWEB_PORT=8088
CEEFAXWEB_DB=/root/ceefax_station/ceefaxweb/ceefaxweb.sqlite3
CEEFAXWEB_UPLOAD_TOKEN=

# Hub page pack (shared teletext pages for TX stations)
CEEFAXWEB_PAGE_PACK_DIR=/root/ceefax_station/ceefaxweb/data/page_pack
CEEFAX_PAGES_SOURCE=local
CEEFAX_HUB_CALLSIGN=CEEFAX

# Free provider API keys (kept on the server only — stations pull the pack)
GUARDIAN_API_KEY=
FOOTBALL_DATA_API_KEY=
LOTTERY_RESULTS_API_KEY=
TMDB_API_KEY=
EOF
  chmod 600 .env
  echo ".env file created — fill in the API keys before enabling hub publishing"
else
  echo ".env already exists, leaving it unchanged"
fi
mkdir -p /root/ceefax_station/ceefaxweb/data/page_pack

# Step 7: Create systemd service
echo "[7/10] Creating systemd service..."
cat > /etc/systemd/system/ceefaxweb.service << 'EOF'
[Unit]
Description=Ceefax Station Web Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/ceefax_station
Environment="PATH=/root/ceefax_station/venv/bin"
EnvironmentFile=/root/ceefax_station/.env
ExecStart=/root/ceefax_station/venv/bin/python -m ceefaxweb
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ceefaxweb
echo "Systemd service created and enabled"

# Hub page refresh timer (every 30 minutes)
echo "Installing hub page refresh timer..."
cp /root/ceefax_station/ceefaxweb/systemd/ceefax-hub-pages.service /etc/systemd/system/
cp /root/ceefax_station/ceefaxweb/systemd/ceefax-hub-pages.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ceefax-hub-pages.timer
echo "Hub page timer enabled (runs every 30 minutes once API keys are set)"

# Step 8: Configure Nginx
echo "[8/10] Configuring Nginx..."
cat > /etc/nginx/sites-available/ceefaxstation << 'EOF'
server {
    listen 80;
    server_name ceefaxstation.com www.ceefaxstation.com;

    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/ceefaxstation /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
echo "Nginx configured"

# Step 9: Configure firewall
echo "[9/10] Configuring firewall..."
ufw --force enable
ufw allow OpenSSH
ufw allow 'Nginx Full'
echo "Firewall configured"

# Step 10: Start service
echo "[10/10] Starting service..."
systemctl start ceefaxweb
sleep 2
systemctl status ceefaxweb --no-pager

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Configure DNS in Namecheap:"
echo "   - Add A record: ceefaxstation.com -> 134.209.23.220"
echo "   - Add A record: www.ceefaxstation.com -> 134.209.23.220"
echo ""
echo "2. Once DNS propagates (5-30 minutes), run SSL setup:"
echo "   certbot --nginx -d ceefaxstation.com -d www.ceefaxstation.com"
echo ""
echo "3. Check service status:"
echo "   systemctl status ceefaxweb"
echo ""
echo "4. View logs:"
echo "   journalctl -u ceefaxweb -f"
echo ""

