#!/usr/bin/env bash
# Install and maintain the global Claude Code toolkit. See README.md -> Install.
#   ./install.sh install [--dry-run]      install or update (default modules: openspec, core)
#   ./install.sh uninstall                 undo the last install, restore backups
#   ./install.sh status | verify | drift | equivalence --live DIR
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
command -v python3 >/dev/null || { echo "ERROR python3 is required" >&2; exit 2; }
python3 -c 'import yaml' 2>/dev/null || { echo "ERROR PyYAML is required: python3 -m pip install pyyaml (or apt install python3-yaml)" >&2; exit 2; }
exec python3 -m scripts.toolkit "$@"
