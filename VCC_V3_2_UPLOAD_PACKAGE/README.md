# 🚀 Alpha-Sell Options Terminal — Oracle Cloud Deployment & Setup Guide

Institutional-grade decision support system for intraday option sellers (Nifty, BankNifty, FinNifty, MidcapNifty) hosted 24/7 on an Oracle Cloud Autonomous Server.

---

## 📌 System & Server Architecture

* **Public Server IP:** `http://137.23.42.11:8000`
* **Cloud Infrastructure:** Oracle Cloud Free Tier (Ubuntu 22.04 LTS, 1GB RAM + 2GB Swap, 46.6GB Storage)
* **SSH Key File Location:** `C:\Users\resea\Downloads\ssh-key-2026-07-30.key`
* **SSH Login User:** `ubuntu`
* **Background Service:** `systemd` service named `nse-dashboard.service`

---

## 🔑 Broker Credentials & Specs (Fyers API v3)

* **Fyers Client ID (App ID):** `` *(Must include `-100` suffix required by Fyers API v3)*
* **Redirect URI:** `http://137.23.42.11:8000/api/fyers/callback`
* **Config Storage Location on Server:** `/home/ubuntu/nse-dashboard/backend/fyers_config.json`
* **OAuth Login Endpoint:** `http://137.23.42.11:8000/api/fyers/login`

---

## ⚡ Quick Deployment & Startup Commands (PowerShell)

Whenever you want to update or restart the server from your Windows PC, open **PowerShell** and use these commands:

### 1. Upload Project Files to Oracle Server
```powershell
scp -i "C:\Users\resea\Downloads\ssh-key-2026-07-30.key" -r "c:\Projects\NSE dashboard\*" ubuntu@137.23.42.11:~/nse-dashboard/
```

### 2. Run Auto-Setup / Initialize Server Service
```powershell
ssh -i "C:\Users\resea\Downloads\ssh-key-2026-07-30.key" ubuntu@137.23.42.11 "cd ~/nse-dashboard && chmod +x setup_oracle.sh && ./setup_oracle.sh"
```

---

## 🛠️ Server Operations & Troubleshooting

### Log into Server via SSH
```powershell
ssh -i "C:\Users\resea\Downloads\ssh-key-2026-07-30.key" ubuntu@137.23.42.11
```

### Check Service Status
```bash
sudo systemctl status nse-dashboard
```

### Restart Service
```bash
sudo systemctl restart nse-dashboard
```

### View Live Realtime Terminal Logs
```bash
sudo journalctl -u nse-dashboard -f
```

---

## ⚙️ Automated Features Built-In

1. **🕘 Intraday Market Timing Restrictor (09:00 AM – 03:45 PM IST):**
   * Live data polling runs only on Monday to Friday between 09:00 AM and 03:45 PM IST.
   * Outside market hours, polling automatically pauses to conserve RAM, CPU, and bandwidth.

2. **🧹 4-Day Storage Retention & Auto-Vacuum:**
   * SQLite snapshots older than 4 days are purged automatically.
   * Runs an automatic `VACUUM;` every 4 hours to reclaim disk space, preventing storage exhaustion.

3. **📱 Mobile-Optimized Dashboard UI:**
   * Features single-hand phone bottom navigation bar (`Chain`, `Strike Walls`, `Smart Money`, `Broker`).
   * Touch-friendly horizontal scrolling option chain & decay charts.

4. **🔑 Dynamic Fyers Broker Auth:**
   * Dynamic callback URL (`http://137.23.42.11:8000/api/fyers/callback`).
   * Auto-refreshes session tokens and stores credentials persistently in `fyers_config.json`.

---

## 🔑 How to Re-Authenticate Fyers Broker

1. Open **`http://137.23.42.11:8000`** in any browser.
2. Click **🔑 FYERS LOGIN** at the top or bottom navigation bar.
3. Enter your **Client ID** (``) and **Secret Key**.
4. Click **`🚀 LOG IN VIA FYERS OAUTH`**.
5. Log into your Fyers account — it will redirect back with `🎉 Fyers OAuth Login Successful!` and stream live tick data.
