#!/bin/bash
# Aggiorna il marcatore "**X.Y.Z**" della versione nei doc principali.
# Usage: scripts/bump_version.sh <old_version> <new_version>
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <old_version> <new_version>" >&2
  exit 1
fi

old="$1"
new="$2"
old_escaped=$(printf '%s' "$old" | sed 's/\./\\./g')

files=(
  doc/README.md
  doc/START_HERE.md
  doc/TESTING.md
  doc/ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md
  deployment/README_DEPLOY_IIS_WINDOWS.md
)

for f in "${files[@]}"; do
  sed -i "s/\*\*${old_escaped}\*\*/\*\*${new}\*\*/" "$f"
done
