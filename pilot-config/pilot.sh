#!/bin/bash
set -e

# 1. Load the environment (Reuse Python 3.12)
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
pyenv shell 3.12.8

# 2. Activate the existing VENV
source venv/bin/activate

echo "Pulling big files (LFS)..."
git lfs install
git lfs pull

echo "Building Docker images for hosts..."
sudo docker build -f Dockerfile_Hosts -t hosts:latest .

echo "Importing cEOS image..."
sudo docker import ../NSOT/disc_images/cEOS64-lab-4.33.2F.tar.xz ceos:4.33.2F || true

echo "Applying Netplan configurations..."
sudo cp netcfg.yaml /etc/netplan/100-netcfg.yaml
sudo chmod 600 /etc/netplan/100-netcfg.yaml
sudo netplan apply

echo "Running pilot.py (Logic initialization)..."
python pilot.py

echo "Environment Setup Complete."
