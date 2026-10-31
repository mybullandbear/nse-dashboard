# Oracle Cloud Free Tier Deployment & Mobile Setup Guide

This guide takes you step-by-step from zero to having your **NSE Alpha-Sell Options Terminal** running **24/7 on Oracle Cloud Free Tier** and accessible on your mobile phone as a native app.

---

## 📁 Step 1: Clean Project Directory Structure

Your project directory (`c:\Projects\NSE dashboard`) is already organized and cleaned. Here are the files that need to be uploaded to your VM:

```text
NSE dashboard/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── cache/
│   │   ├── db/
│   │   ├── engines/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── static/          <-- Dashboard HTML/JS UI
│   │   ├── config.py
│   │   └── main.py
│   └── requirements.txt
├── setup_oracle.sh          <-- Auto-setup script for Linux VM
└── .gitignore
```

> [!NOTE]
> Sensitive files like `fyers_config.json`, `.db`, and `.log` are automatically excluded by `.gitignore`. They will be created fresh on the server when you log in.

---

## ☁️ Step 2: Create Free VM Instance on Oracle Cloud

1. Log into your **Oracle Cloud Infrastructure (OCI)** Console.
2. Go to **Compute** $\rightarrow$ **Instances** $\rightarrow$ Click **Create Instance**.
3. **Configure Instance:**
   - **Name:** `nse-options-terminal`
   - **Image:** Ubuntu 22.04 LTS (Minimal or Standard).
   - **Shape:** 
     - Choose **Ampere (ARM)** $\rightarrow$ `VM.Standard.A1.Flex` (Assign **2 to 4 OCPUs** and **12 to 24 GB RAM** — 100% Always Free!).
     - *Alternative:* AMD `VM.Standard.E2.1.Micro` (1 OCPU, 1 GB RAM).
   - **Networking:** Select default VCN and Public Subnet (Assign Public IPv4).
   - **SSH Keys:** Select **"Generate a key pair for me"** and click **Save Private Key** (e.g. `ssh-key.key`). Save this file on your PC!
4. Click **Create**. Wait 1–2 minutes for the status to turn **RUNNING**.
5. Copy your **Public IP Address** (e.g., `139.59.xx.xx`).

---

## 🔒 Step 3: Open Port 8000 in Oracle Cloud Security Rules

By default, Oracle Cloud blocks incoming web traffic. You must open port 8000 (and 80/443 for web/SSL):

1. In Oracle Console, go to **Networking** $\rightarrow$ **Virtual Cloud Networks**.
2. Click your VCN $\rightarrow$ Click **Public Subnet** $\rightarrow$ Click **Default Security List**.
3. Under **Ingress Rules**, click **Add Ingress Rules**:
   - **Source CIDR:** `0.0.0.0/0`
   - **IP Protocol:** `TCP`
   - **Destination Port Range:** `80, 443, 8000`
   - **Description:** `NSE Dashboard Web & API`
4. Click **Add Ingress Rules**.

---

## 🚀 Step 4: Upload Project & Run Auto-Setup

### Option A: Using Git (Recommended)
If you push your code to a private GitHub repo:
1. Connect to your VM via PowerShell/Terminal:
   ```bash
   ssh -i "path/to/ssh-key.key" ubuntu@<YOUR-ORACLE-PUBLIC-IP>
   ```
2. Clone repo and run setup:
   ```bash
   git clone <YOUR-GITHUB-REPO-URL> nse-dashboard
   cd nse-dashboard
   chmod +x setup_oracle.sh
   ./setup_oracle.sh
   ```

### Option B: Direct File Upload (WinSCP / SFTP)
1. Zip your project folder on PC.
2. Open **WinSCP** or **FileZilla** on your PC.
3. Host: `<YOUR-ORACLE-PUBLIC-IP>`, User: `ubuntu`, Private Key: `ssh-key.key`.
4. Upload `NSE dashboard` folder to `/home/ubuntu/`.
5. Connect via SSH and run:
   ```bash
   cd nse-dashboard
   chmod +x setup_oracle.sh
   ./setup_oracle.sh
   ```

---

## 📱 Step 5: Accessing on Mobile & Adding Home Screen Shortcut

1. Open Chrome or Safari on your phone.
2. Enter your server URL:
   ```text
   http://<YOUR-ORACLE-PUBLIC-IP>:8000
   ```
3. Complete the **Fyers Login** directly on your phone.
4. **Add to Home Screen:**
   - **iOS Safari:** Tap **Share** $\rightarrow$ **Add to Home Screen**.
   - **Android Chrome:** Tap **⋮** $\rightarrow$ **Add to Home Screen**.

Now you have a 24/7 high-performance trading dashboard right on your phone screen!
