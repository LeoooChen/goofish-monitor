#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_DIR="$ROOT_DIR/logs"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR"

usage() {
  cat <<EOF
Usage: ./start.sh <command>

Commands:
  install   Install Python, Playwright, and frontend dependencies
  start     Start backend and frontend
  stop      Stop backend and frontend
  restart   Restart backend and frontend
  status    Show process status and local URLs
  logs      Follow backend and frontend logs
  uninstall Show uninstall instructions without deleting files

Environment overrides:
  BACKEND_PORT=8000 FRONTEND_PORT=5173 ./start.sh start
EOF
}

pid_is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1

  local pid
  pid="$(cat "$pid_file")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing command: $command_name"
    exit 1
  fi
}

detect_os() {
  case "$(uname -s)" in
    Darwin)
      echo "macos"
      ;;
    Linux)
      echo "linux"
      ;;
    MINGW* | MSYS* | CYGWIN*)
      echo "windows"
      ;;
    *)
      echo "unknown"
      ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    arm64 | aarch64)
      echo "arm64"
      ;;
    x86_64 | amd64)
      echo "x64"
      ;;
    armv7l)
      echo "armv7"
      ;;
    *)
      uname -m
      ;;
  esac
}

print_environment() {
  local os_name
  local arch_name
  os_name="$(detect_os)"
  arch_name="$(detect_arch)"
  echo "Environment: os=$os_name arch=$arch_name shell=${SHELL:-unknown}"
}

confirm() {
  local prompt="$1"
  local answer
  read -r -p "$prompt [y/N] " answer
  case "$answer" in
    y | Y | yes | YES)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    require_command sudo
    sudo "$@"
  fi
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi

  echo "uv is required to install the Python environment."
  if confirm "Install uv automatically now?"; then
    require_command curl
    curl -LsSf https://astral.sh/uv/install.sh | sh
  else
    echo "Install cancelled. Please install uv first, then run: ./start.sh install"
    exit 1
  fi

  if ! command -v uv >/dev/null 2>&1; then
    echo "uv was installed, but it is not available in PATH. Restart your shell and run again."
    exit 1
  fi
}

ensure_npm() {
  if command -v npm >/dev/null 2>&1; then
    return
  fi

  echo "npm is required to install and run the frontend."
  if ! confirm "Install Node.js/npm automatically now?"; then
    echo "Install cancelled. Please install Node.js/npm first, then run again."
    exit 1
  fi

  case "$(detect_os)" in
    macos)
      if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew is required for automatic npm installation on macOS."
        echo "Install Node.js manually from https://nodejs.org/ or install Homebrew first."
        exit 1
      fi
      brew install node
      ;;
    linux)
      install_npm_linux
      ;;
    windows)
      echo "Automatic npm installation is not supported in this shell."
      echo "Install Node.js from https://nodejs.org/, then run again."
      exit 1
      ;;
    *)
      echo "Unsupported system for automatic npm installation."
      echo "Install Node.js/npm manually, then run again."
      exit 1
      ;;
  esac

  if ! command -v npm >/dev/null 2>&1; then
    echo "npm installation finished, but npm is not available in PATH. Restart your shell and run again."
    exit 1
  fi
}

install_npm_linux() {
  if command -v apt-get >/dev/null 2>&1; then
    run_privileged apt-get update
    run_privileged apt-get install -y nodejs npm
  elif command -v dnf >/dev/null 2>&1; then
    run_privileged dnf install -y nodejs npm
  elif command -v yum >/dev/null 2>&1; then
    run_privileged yum install -y nodejs npm
  elif command -v pacman >/dev/null 2>&1; then
    run_privileged pacman -Sy --needed nodejs npm
  elif command -v apk >/dev/null 2>&1; then
    run_privileged apk add nodejs npm
  else
    echo "No supported Linux package manager found."
    echo "Install Node.js/npm manually, then run again."
    exit 1
  fi
}

install_deps() {
  print_environment
  ensure_uv
  ensure_npm

  cd "$ROOT_DIR"
  rm -rf "$ROOT_DIR/.venv"
  uv venv .venv
  uv pip install --python "$ROOT_DIR/.venv/bin/python" -e ".[dev]"
  "$ROOT_DIR/.venv/bin/python" -m playwright install chromium

  cd "$FRONTEND_DIR"
  npm install

  echo "Install complete."
}

start_backend() {
  if pid_is_running "$BACKEND_PID_FILE"; then
    echo "Backend already running: http://$BACKEND_HOST:$BACKEND_PORT"
    return
  fi

  local uvicorn_bin="$ROOT_DIR/.venv/bin/uvicorn"
  if [[ ! -x "$uvicorn_bin" ]]; then
    echo "Backend dependencies are not installed. Run: ./start.sh install"
    exit 1
  fi

  cd "$ROOT_DIR"
  nohup "$uvicorn_bin" backend.app.main:app \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT" \
    --reload \
    >"$BACKEND_LOG" 2>&1 &
  echo "$!" >"$BACKEND_PID_FILE"

  echo "Backend started: http://$BACKEND_HOST:$BACKEND_PORT"
}

start_frontend() {
  if pid_is_running "$FRONTEND_PID_FILE"; then
    echo "Frontend already running: http://$FRONTEND_HOST:$FRONTEND_PORT"
    return
  fi

  ensure_npm
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "Frontend dependencies are not installed. Run: ./start.sh install"
    exit 1
  fi

  cd "$FRONTEND_DIR"
  nohup npm run dev -- \
    --host "$FRONTEND_HOST" \
    --port "$FRONTEND_PORT" \
    >"$FRONTEND_LOG" 2>&1 &
  echo "$!" >"$FRONTEND_PID_FILE"

  echo "Frontend started: http://$FRONTEND_HOST:$FRONTEND_PORT"
}

stop_one() {
  local name="$1"
  local pid_file="$2"

  if ! pid_is_running "$pid_file"; then
    rm -f "$pid_file"
    echo "$name is not running."
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  kill "$pid" >/dev/null 2>&1 || true

  for _ in {1..30}; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$pid_file"
      echo "$name stopped."
      return
    fi
    sleep 0.2
  done

  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$pid_file"
  echo "$name force stopped."
}

start_all() {
  start_backend
  start_frontend
  echo
  echo "Open: http://$FRONTEND_HOST:$FRONTEND_PORT"
}

stop_all() {
  stop_one "Frontend" "$FRONTEND_PID_FILE"
  stop_one "Backend" "$BACKEND_PID_FILE"
}

status_one() {
  local name="$1"
  local pid_file="$2"
  local url="$3"

  if pid_is_running "$pid_file"; then
    echo "$name: running, pid $(cat "$pid_file"), $url"
  else
    echo "$name: stopped, $url"
  fi
}

show_status() {
  status_one "Backend" "$BACKEND_PID_FILE" "http://$BACKEND_HOST:$BACKEND_PORT"
  status_one "Frontend" "$FRONTEND_PID_FILE" "http://$FRONTEND_HOST:$FRONTEND_PORT"
}

follow_logs() {
  touch "$BACKEND_LOG" "$FRONTEND_LOG"
  tail -n 80 -f "$BACKEND_LOG" "$FRONTEND_LOG"
}

show_uninstall() {
  cat <<EOF
This project is self-contained in:
  $ROOT_DIR

To uninstall it, stop the services first:
  ./start.sh stop

Then delete the project directory manually.

No files were deleted.
EOF
}

command="${1:-}"
case "$command" in
  install)
    install_deps
    ;;
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    show_status
    ;;
  logs)
    follow_logs
    ;;
  uninstall)
    show_uninstall
    ;;
  "" | -h | --help | help)
    usage
    ;;
  *)
    echo "Unknown command: $command"
    echo
    usage
    exit 1
    ;;
esac
