#!/bin/bash
# Start Prosper locally. Run from anywhere:  ./run.sh
cd "$(dirname "$0")"
if [ ! -d "venv" ]; then
  echo "No venv found. Create one first:  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
source venv/bin/activate
streamlit run app.py
