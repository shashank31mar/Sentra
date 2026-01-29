#!/bin/bash
# Start Security Controller server

cd src/security-controller
source venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
