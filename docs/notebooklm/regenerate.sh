#!/usr/bin/env bash
# Recreate the Snow Gloves OS pitch deck via NotebookLM.
# Requires: `notebooklm` CLI (https://github.com/teng-lin/notebooklm-py) authenticated via `notebooklm login`.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

NB_NAME="Snow Gloves OS — Pitch Deck"
OUT="docs/assets/snowgloves-pitch.pdf"
PROMPT_FILE="docs/notebooklm/PROMPT.md"

echo "→ creating notebook '$NB_NAME'..."
NB_ID=$(notebooklm create "$NB_NAME" --json | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
notebooklm use "$NB_ID"
echo "  id: $NB_ID"

echo "→ adding 5 sources..."
notebooklm source add docs/explainer.md
notebooklm source add README.md
notebooklm source add .specify/memory/constitution.md
notebooklm source add docs/assets/explainer-hero-1.png
notebooklm source add docs/assets/explainer-hero-2.png

echo "→ waiting for sources to index..."
for sid in $(notebooklm source list --json | python3 -c "import sys,json;[print(s['id']) for s in json.load(sys.stdin)['sources']]"); do
  notebooklm source wait "$sid" --timeout 600 || true
done

PROMPT=$(awk '/^```$/{f=!f;next} f' "$PROMPT_FILE")

echo "→ generating slide deck (5-15 min)..."
TASK=$(notebooklm generate slide-deck --format detailed --length default --retry 2 --json "$PROMPT" | python3 -c "import sys,json;print(json.load(sys.stdin)['task_id'])")
notebooklm artifact wait "$TASK" --timeout 1200

echo "→ downloading to $OUT..."
notebooklm download slide-deck "$OUT" -a "$TASK"

echo "✓ deck regenerated → $OUT"
