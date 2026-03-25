#!/bin/bash

# Exit on any error
set -e

# CLEANUP: Remove known broken or conflicting local repo files before starting
echo "Cleaning up existing repository conflicts..."
sudo rm -f /etc/apt/sources.list.d/docker.list
sudo rm -f /etc/apt/sources.list.d/influxdata.list
sudo rm -f /etc/apt/sources.list.d/grafana.list
sudo rm -f /etc/apt/sources.list.d/ngrok.list
sudo rm -f /etc/apt/sources.list.d/netdevops.list
sudo rm -f /etc/apt/sources.list.d/jenkins.list

echo "[1/12] Removing old Docker components..."
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
    sudo apt-get remove -y $pkg || true
done

echo "[2/12] Setting up Docker repository..."
# 1. Kill BOTH types of source files and keys
sudo rm -f /etc/apt/sources.list.d/docker.list* /etc/apt/sources.list.d/docker.sources
sudo rm -f /etc/apt/keyrings/docker.gpg /etc/apt/keyrings/docker.asc

# 2. Re-setup
sudo apt-get update || true
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings

# 3. Import Key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 4. Add the repo as a standard .list file
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. This update should now succeed 100%
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[3/12] Installing SSH Server and Containerlab..."
# Install SSH first so Containerlab installer doesn't error out
sudo apt-get update
sudo apt-get install -y openssh-server

# Now run the Containerlab installer
curl -sL https://containerlab.dev/setup | sudo bash -s "all"

echo "[4/12] Installing InfluxDB 2.x..."
# 1. Download the key
curl --silent --location -O https://repos.influxdata.com/influxdata-archive.key

# 2. Verify and install key (No changes needed here, your manual logic was good)
gpg --show-keys --with-fingerprint --with-colons ./influxdata-archive.key 2>&1 \
| grep -q '^fpr:\+24C975CBA61A024EE1B631787C3D57159FC2F927:$' \
&& cat influxdata-archive.key \
| gpg --dearmor --yes \
| sudo tee /etc/apt/keyrings/influxdata-archive.gpg > /dev/null

# 3. Use the DEBIAN STABLE path (This is the fix!)
echo 'deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main' | sudo tee /etc/apt/sources.list.d/influxdata.list

# 4. Clean up and install with -y to prevent hanging
rm -f influxdata-archive.key
sudo apt-get update
sudo apt-get install -y influxdb2
sudo systemctl enable --now influxdb

echo "[5/12] Installing Grafana..."
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor --yes | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update && sudo apt-get install -y grafana
sudo systemctl enable --now grafana-server

echo "[6/12] Installing Ngrok..."
# Using bionic as the most compatible stable endpoint for Ubuntu-based distros
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | gpg --dearmor --yes | sudo tee /etc/apt/keyrings/ngrok.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/ngrok.gpg] https://ngrok-agent.s3.amazonaws.com bionic main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt-get update && sudo apt-get install -y ngrok

echo "[7/12] Installing Java (OpenJDK 17)..."
sudo apt-get install -y fontconfig openjdk-17-jre

echo "[8/12] Installing Jenkins..."
# Clean up old jenkins keyring if exists
sudo rm -f /usr/share/keyrings/jenkins-keyring.asc
sudo wget -O /usr/share/keyrings/jenkins-keyring.asc https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" | sudo tee /etc/apt/sources.list.d/jenkins.list > /dev/null
sudo apt-get update && sudo apt-get install -y jenkins
sudo systemctl enable --now jenkins

echo "[9/12] Setting up Python environment..."
sudo apt install -y python3-venv python3-pip
# If venv exists, skip creation, otherwise create it
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "[10/12] Installing Network & Automation tools..."
sudo apt-get install -y libsnmp-dev snmp snmpd snmptrapd snmp-mibs-downloader gcc python3-dev syslog-ng telegraf git-lfs gnmic xdg-utils graphviz socat netplan.io
sudo add-apt-repository universe -y
sudo download-mibs || true

echo "[11/12] Installing Python packages..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"

if [[ -f "$REQ_FILE" ]]; then
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r "$REQ_FILE"
else
    echo "❗ requirements.txt not found. Skipping pip install."
fi

echo "[12/12] Finalizing Permissions..."
# Add current user and jenkins to docker group
sudo usermod -aG docker $USER || true
sudo usermod -aG docker jenkins || true

# Ensure Jenkins can reach the project files
sudo chmod o+rx $HOME
sudo chmod -R o+rx "$(dirname "$SCRIPT_DIR")"

echo "✅ Setup Complete."
echo "CRITICAL: Please run 'newgrp docker' or log out and back in to use Docker without sudo."
