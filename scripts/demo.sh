#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export AIMEC_LLM_MODEL="${AIMEC_LLM_MODEL:-qwen3:1.7b}"
export AIMEC_OLLAMA_MEMORY="${AIMEC_OLLAMA_MEMORY:-4g}"
export AIMEC_OLLAMA_CPUS="${AIMEC_OLLAMA_CPUS:-2.0}"
export AIMEC_DEMO_PORT="${AIMEC_DEMO_PORT:-127.0.0.1:8020}"
# Local development deliberately does not claim a verified release identity.
export AIMEC_DEMO_SOURCE_COMMIT=unrecorded
dc=(docker compose --env-file /dev/null -p aimec-webmcp-public -f docker-compose.bc094-business-demo.yml)
case "${1:-start}" in
  start)
    "${dc[@]}" config --quiet
    "${dc[@]}" up -d --build --wait --wait-timeout 900
    "${dc[@]}" exec -T ollama ollama show "$AIMEC_LLM_MODEL"
    printf '%s\n' 'Demo started. With default settings, open http://localhost:8020.'
    ;;
  status) "${dc[@]}" ps -a ;;
  logs) "${dc[@]}" logs --tail=80 -f alpha business-advisory ollama ;;
  stop) "${dc[@]}" stop ;;
  *) printf '%s\n' 'Usage: bash scripts/demo.sh [start|status|logs|stop]' >&2; exit 2 ;;
esac
