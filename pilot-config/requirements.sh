#!/bin/bash

# Exit on any error
set -e

# CLEANUP: Remove known broken or conflicting local repo files before starting
echo "Cleaning up existing repository conflicts..."
sudo rm -f /etc/apt/sources.list.d/docker.list* /etc/apt/sources.list.d/docker.sources
sudo rm -f /etc/apt/sources.list.d/influxdata.list* /etc/apt/sources.list.d/influxdata.sources
sudo rm -f /etc/apt/sources.list.d/grafana.list* /etc/apt/sources.list.d/grafana.sources
sudo rm -f /etc/apt/sources.list.d/ngrok.list* /etc/apt/sources.list.d/ngrok.sources
sudo rm -f /etc/apt/sources.list.d/netdevops.list*
sudo rm -f /etc/apt/sources.list.d/jenkins.list* /etc/apt/sources.list.d/jenkins.sources

echo "[1/12] Removing old Docker components..."
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
    sudo apt-get remove -y $pkg || true
done

echo "[2/12] Setting up Docker repository..."
sudo apt-get update || true
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "[3/12] Installing SSH Server and Containerlab..."
sudo apt-get update
sudo apt-get install -y openssh-server
curl -sL https://containerlab.dev/setup | sudo bash -s "all"

echo "[4/12] Installing InfluxDB 2.x..."
curl --silent --location -O https://repos.influxdata.com/influxdata-archive.key
# Verify fingerprint and install key
gpg --show-keys --with-fingerprint --with-colons ./influxdata-archive.key 2>&1 \
| grep -q '^fpr:\+24C975CBA61A024EE1B631787C3D57159FC2F927:$' \
&& cat influxdata-archive.key | gpg --dearmor --yes | sudo tee /etc/apt/keyrings/influxdata-archive.gpg > /dev/null
echo 'deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main' | sudo tee /etc/apt/sources.list.d/influxdata.list
rm -f influxdata-archive.key
sudo apt-get update && sudo apt-get install -y influxdb2
sudo systemctl enable --now influxdb

echo "[5/12] Installing Grafana..."
curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor --yes | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update && sudo apt-get install -y grafana
sudo systemctl enable --now grafana-server

echo "[6/12] Installing Ngrok..."
# Using bookworm endpoint as confirmed working for arm64/questing
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc > /dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt-get update && sudo apt-get install -y ngrok

echo "[7/12] Installing Java (OpenJDK 21)..."
# Upgraded to 21 for better Jenkins compatibility
sudo apt-get install -y fontconfig openjdk-21-jre

echo "[8/12] Installing Jenkins..."
# Using the 2026 key confirmed working manually
sudo wget -O /etc/apt/keyrings/jenkins-keyring.asc https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key
echo "deb [signed-by=/etc/apt/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" | sudo tee /etc/apt/sources.list.d/jenkins.list > /dev/null
sudo apt-get update && sudo apt-get install -y jenkins
sudo systemctl enable --now jenkins

echo "[9/12] Setting up Python 3.12 via pyenv..."
# Load pyenv paths
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# Ensure we are using 3.12 before creating the venv
pyenv shell 3.12.8

# Recreate venv if it's the wrong version or missing
rm -rf venv
python -m venv venv
echo "[10/12] Installing Network & Automation tools..."
sudo apt-get install -y software-properties-common libsnmp-dev snmp snmpd snmptrapd snmp-mibs-downloader gcc syslog-ng telegraf git-lfs gnmic xdg-utils graphviz socat netplan.io net-tools

sudo add-apt-repository universe -y
sudo download-mibs || true

echo "[11/12] Installing Python packages..."
./venv/bin/pip install --upgrade pip setuptools wheel

# We install easysnmp separately first with a compiler flag to bypass GCC 15 strictness
CFLAGS="-Wno-error=incompatible-pointer-types" ./venv/bin/pip install easysnmp

# Then install the rest of the requirements
./venv/bin/pip install -r requirements.txt

echo "[12/12] Finalizing Permissions..."
sudo usermod -aG docker $USER || true
sudo usermod -aG docker jenkins || true
sudo chmod o+rx $HOME
sudo chmod -R o+rx "$(dirname "$SCRIPT_DIR")"

echo "✅ Setup Complete."
