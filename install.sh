#!/bin/bash
# SMS_Bombar Installation Script for Kali Linux / Ubuntu

echo "🔧 Installing SMS_Bombar dependencies..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git

# Setup virtual environment
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# Install Python packages
pip install --upgrade pip
pip install -r requirements.txt

# Initialize Database
echo "📦 Initializing database..."
python3 SMS_Bombar.py --db ./sms_lab.db init-db

echo "✅ Installation complete!"
echo "Run 'bash run.sh' to start the server."
