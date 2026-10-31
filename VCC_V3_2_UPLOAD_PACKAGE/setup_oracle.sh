#!/bin/bash
# =======================================================================
#  NSE Alpha-Sell Options Terminal - Oracle Cloud Free Tier Auto-Setup
# =======================================================================

set -e

echo "[1/5] Updating system packages..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git ufw

echo "[2/5] Setting up 2GB Swap file to prevent out-of-memory during pip builds..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "[3/5] Installing Python dependencies..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
python3 -m venv "$SCRIPT_DIR/venv"
source "$SCRIPT_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r "$SCRIPT_DIR/backend/requirements.txt"

echo "[4/5] Creating Systemd Background Service..."
cat <<EOF | sudo tee /etc/systemd/system/nse-dashboard.service
[Unit]
Description=NSE Options Terminal FastAPI Server
After=network.target

[Service]
User=$USER
WorkingDirectory=$SCRIPT_DIR/backend
ExecStart=$SCRIPT_DIR/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable nse-dashboard
sudo systemctl restart nse-dashboard

echo "[5/5] Configuring Firewall & iptables for Oracle Cloud..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT || true
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT || true
sudo netfilter-persistent save || true

echo "======================================================================="
echo " SUCCESS! NSE Options Terminal Service is running!"
echo " Check status: sudo systemctl status nse-dashboard"
echo " Access URL:   http://$(curl -s ifconfig.me):8000"
echo "======================================================================="
