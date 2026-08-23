#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "[오류] Python 3를 찾지 못했습니다."
    echo "WSL Ubuntu에서 다음 명령을 실행하세요:"
    echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
  fi
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "[1/3] 가상환경을 생성합니다..."
  rm -rf .venv
  if ! "$PYTHON_BIN" -m venv .venv; then
    echo
    echo "[오류] Python venv 모듈이 설치되어 있지 않습니다."
    echo "WSL Ubuntu/Debian에서 다음 명령을 실행한 뒤 다시 ./start.sh를 실행하세요:"
    echo "  sudo apt update && sudo apt install -y python3-venv python3-pip"
    echo
    echo "특정 Python 버전을 사용 중이면 예: sudo apt install -y python3.12-venv"
    exit 1
  fi
fi

VENV_PYTHON="$(pwd)/.venv/bin/python"

echo "[2/3] 의존성을 확인합니다..."
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q --upgrade pip
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q -r requirements.txt

echo "[3/3] 서버를 시작합니다: http://localhost:${PORT:-8787}"
exec "$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8787}"
