#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check src tests
uv run lint-imports
uv run pytest -q "$@"
