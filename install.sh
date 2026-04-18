#!/data/data/com.termux/files/usr/bin/bash

echo "🔧 Installing SMS_Bombar dependencies for Termux..."

# Update packages
pkg update -y && pkg upgrade -y

# Install required packages
pkg install -y python git

# Optional: install build tools (some pip packages need this)
pkg install -y clang make

# Setup virtual environment
if [ ! -d "venv" ]; then
    python -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# Initialize Database
echo "📦 Initializing database..."
python SMS_Bombar.py --db ./sms_lab.db init-db

echo "✅ Installation complete!"
echo "Run 'bash run.sh' to start the server."
