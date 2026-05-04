#!/bin/bash
set -e

echo "--- Starting application with debug script ---"
echo "--- Listing environment variables ---"
printenv
echo "--- End of environment variables ---"

echo "--- Starting Uvicorn server ---"
uvicorn app.main:app --host 0.0.0.0 --port 8000