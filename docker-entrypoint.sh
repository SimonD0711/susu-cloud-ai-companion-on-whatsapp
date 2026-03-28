#!/bin/sh
set -eu

mkdir -p /app/data

case "${1:-agent}" in
  agent)
    exec python /app/wa_agent.py
    ;;
  admin)
    exec python /app/susu_admin_server.py
    ;;
  *)
    exec "$@"
    ;;
esac
