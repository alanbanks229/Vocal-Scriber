#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "Run this script with: source scripts/setup-macos.sh"
  exit 1
fi

cd "${REPO_ROOT}"

python_supports_venv() {
  "$@" -c 'import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

if command -v python3 >/dev/null 2>&1 && python_supports_venv python3; then
  PYTHON_CMD=(python3)
elif command -v python >/dev/null 2>&1 && python_supports_venv python; then
  PYTHON_CMD=(python)
else
  echo "Python 3.11+ is required but was not found."
  return 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Creating virtual environment in .venv ..."
  "${PYTHON_CMD[@]}" -m venv "${VENV_DIR}"
else
  echo "Using existing virtual environment in .venv ..."
fi

source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-build-isolation -e ".[macos]"

echo
echo "Virtual environment is active."
echo "Run the app with: python -m vocal_scriber --debug"
