#!/bin/bash

# Exit on any error
set -e

echo "[1/12] Removing old Docker components..."
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
    sudo apt-get remove -y $pkg || true
done

echo "[2/12] Setting up Docker repository..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[3/12] Installing Containerlab..."
curl -sL https://containerlab.dev/setup | sudo -E bash -s "all"

echo "[4/12] Installing InfluxDB 2.x..."
# Use the official compat key for 2026 Ubuntu releases
wget -q https://repos.influxdata.com/influxdata-archive_compat.key
# Updated SHA256 for the current InfluxData key
echo "393e87fd81bb0a47a135d71867192913d9a2053d340cc7c7f610e3ceca00d6ef influxdata-archive_compat.key" | sha256sum --check -
cat influxdata-archive_compat.key | gpg --dearmor | sudo tee /etc/apt/keyrings/influxdata-archive.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/influxdata.list
sudo apt-get update && sudo apt-get install -y influxdb2
sudo systemctl enable --now influxdb

echo "[5/12] Installing Grafana..."
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update && sudo apt-get install -y grafana
sudo systemctl enable --now grafana-server

echo "[6/12] Installing Ngrok..."
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | gpg --dearmor | sudo tee /etc/apt/keyrings/ngrok.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/ngrok.gpg] https://ngrok-agent.s3.amazonaws.com bionic main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt-get update && sudo apt-get install -y ngrok

echo "[7/12] Installing Java (OpenJDK 17)..."
sudo apt-get install -y fontconfig openjdk-17-jre

echo "[8/12] Installing Jenkins..."
sudo wget -O /usr/share/keyrings/jenkins-keyring.asc https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" | sudo tee /etc/apt/sources.list.d/jenkins.list > /dev/null
sudo apt-get update && sudo apt-get install -y jenkins
sudo systemctl enable --now jenkins

echo "[9/12] Setting up Python environment..."
sudo apt install -y python3-venv python3-pip
# Create venv in the current directory
python3 -m venv venv

echo "[10/12] Installing Network & Automation tools..."
sudo apt-get install -y libsnmp-dev snmp snmpd snmptrapd snmp-mibs-downloader gcc python3-dev syslog-ng telegraf git-lfs gnmic xdg-utils graphviz socat netplan.io
sudo add-apt-repository universe -y
sudo download-mibs || true

echo "[11/12] Installing Python packages..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
REQ_FILE="${SCRIPT_DIR}/requirements.txt"

if [[ -f "$REQ_FILE" ]]; then
    # Ensure we use the venv's pip specifically
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r "$REQ_FILE"
else
    echo "❗ requirements.txt not found. Skipping pip install."
fi

echo "[12/12] Finalizing Permissions..."
# Add current user and jenkins to docker group
sudo usermod -aG docker $USER
sudo usermod -aG docker jenkins

# Ensure Jenkins can reach the project files
sudo chmod o+rx $HOME
sudo chmod -R o+rx "$(dirname "$SCRIPT_DIR")"

echo "✅ Setup Complete. Please log out and back in for Docker group changes to take effect."
