#!/bin/bash
# Double-click this file on your Mac to start Council Chat.
# It installs dependencies on the first run, then opens the app in your browser.
cd "$(dirname "$0")" || exit 1

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed. Install it from https://nodejs.org (LTS) and try again."
  read -r -p "Press Enter to close."
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "First-time setup: installing dependencies…"
  npm install || { echo "npm install failed."; read -r -p "Press Enter to close."; exit 1; }
fi

echo "Starting Council Chat at http://localhost:4717 …"
( sleep 1.5 && open "http://localhost:4717" ) &
npm start
