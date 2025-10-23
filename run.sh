#!/bin/bash
# Run SMS_Bombar Flask Server

source venv/bin/activate

echo "🚀 Starting SMS_Bombar Server on http://127.0.0.1:5000 ..."
python3 SMS_Bombar.py --db ./sms_lab.db run-server --host 127.0.0.1 --port 5000
