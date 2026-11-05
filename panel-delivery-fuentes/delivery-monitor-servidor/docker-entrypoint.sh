#!/bin/sh
set -e
HOME="${HOME:-/home/app}"
mkdir -p "$HOME" /app/data 2>/dev/null || true

# Enlaza las sesiones que monta el dueño. No se crean secretos aquí.
if [ -e /sessions/uber_cookie ]; then
  ln -sfn /sessions/uber_cookie "$HOME/.uber_cookie"
fi
if [ -e /sessions/pya_tokens.json ]; then
  ln -sfn /sessions/pya_tokens.json "$HOME/.pya_tokens.json"
fi

exec "$@"
