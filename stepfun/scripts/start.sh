#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'Install/start Docker, or connect an existing seekdb as described in README.'; exit 1; }
npm ci
npm run db:up
npm run build
echo 'Open http://localhost:3001'
npm start
