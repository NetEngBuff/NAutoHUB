#!/bin/bash
set -e

# 1. Load the environment (Reuse Python 3.12)
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
pyenv shell 3.12.8

# 2. Activate the existing VENV
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Error: venv not found! Run requirements.sh first."
    exit 1
fi

# 3. Fix Containerlab permissions
sudo setcap cap_net_admin,cap_net_raw,cap_sys_admin+ep $(which containerlab)

echo "Launching NAutoHUB Flask App..."
echo "Running on http://0.0.0.0:5555"

# Direct path to your Flask app
python ~/projects/NAutoHUB/NSOT/GUI/flask_app/nahub.py
