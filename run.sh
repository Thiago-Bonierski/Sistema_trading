#!/usr/bin/env bash
#
# run.sh — sobe o painel completo (backend Flask + frontend Vite).
#
# Uso:
#   ./run.sh
#
# Ctrl+C encerra os dois processos e libera as portas 5000 e 5173.
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"
  DIM="$(printf '\033[2m')"
  GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"
  RED="$(printf '\033[31m')"
  RESET="$(printf '\033[0m')"
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

say() { printf '%s\n' "$*"; }
fail() { printf '%s\n' "${RED}❌ $*${RESET}" >&2; exit 1; }

BACKEND_PID=""
FRONTEND_PID=""
CLEANING=0

# Encerra recursivamente um processo e seus descendentes (npm -> sh -> node).
terminate_tree() {
  local pid="${1:-}"
  [ -z "$pid" ] && return 0
  kill -0 "$pid" 2>/dev/null || return 0

  if command -v pgrep >/dev/null 2>&1; then
    local child
    while IFS= read -r child; do
      [ -n "$child" ] && terminate_tree "$child"
    done < <(pgrep -P "$pid" 2>/dev/null || true)
  fi

  kill -TERM "$pid" 2>/dev/null || true
}

wait_gone() {
  local pid="${1:-}"
  [ -z "$pid" ] && return 0
  local tries=0
  while kill -0 "$pid" 2>/dev/null && [ "$tries" -lt 30 ]; do
    sleep 0.1
    tries=$((tries + 1))
  done
}

cleanup() {
  [ "$CLEANING" -eq 1 ] && return 0
  CLEANING=1
  trap - EXIT INT TERM

  say ""
  say "${YELLOW}🛑 Encerrando backend e frontend…${RESET}"

  terminate_tree "$FRONTEND_PID"
  terminate_tree "$BACKEND_PID"
  wait_gone "$FRONTEND_PID"
  wait_gone "$BACKEND_PID"

  # Garantia final: processos que ignoraram SIGTERM.
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done

  wait "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
  say "${GREEN}✅ Painel encerrado. Portas 5000 e 5173 liberadas.${RESET}"
}

trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# 1. Ambiente Python
# ---------------------------------------------------------------------------
if [ -f "$ROOT_DIR/venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/venv/bin/activate"
  say "${GREEN}🐍 venv ativado${RESET} ${DIM}($ROOT_DIR/venv)${RESET}"
elif [ -f "$ROOT_DIR/venv/Scripts/activate" ]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/venv/Scripts/activate"
  say "${GREEN}🐍 venv ativado${RESET} ${DIM}($ROOT_DIR/venv)${RESET}"
else
  fail "venv não encontrado. Rode ./install.sh primeiro para criar o ambiente."
fi

command -v python >/dev/null 2>&1 || fail "python não encontrado no PATH."
command -v npm >/dev/null 2>&1 || fail "npm não encontrado. Instale o Node.js 18+."

python -c "import flask, flask_cors" 2>/dev/null \
  || fail "Dependências Python ausentes. Rode: pip install -r requirements.txt"

# ---------------------------------------------------------------------------
# 2. Dependências do frontend
# ---------------------------------------------------------------------------
if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  say "${YELLOW}📦 Primeira execução: instalando dependências do frontend…${RESET}"
  (cd "$ROOT_DIR/frontend" && npm install --no-audit --no-fund)
  say "${GREEN}📦 Frontend pronto.${RESET}"
fi

# ---------------------------------------------------------------------------
# 3. Backend + frontend em paralelo
# ---------------------------------------------------------------------------
say ""
say "${BOLD}🚀 Trading Requiem — Painel de Controle${RESET}"
say "   ${DIM}Backend :${RESET} http://127.0.0.1:5000"
say "   ${DIM}Painel  :${RESET} http://127.0.0.1:5173"
say "   ${DIM}Ctrl+C encerra os dois processos.${RESET}"
say ""

PYTHONUNBUFFERED=1 python "$ROOT_DIR/app.py" &
BACKEND_PID=$!

(cd "$ROOT_DIR/frontend" && npm run dev -- --host 127.0.0.1) &
FRONTEND_PID=$!

# Se qualquer um dos dois cair, o script sai e o trap limpa o outro.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
