#!/usr/bin/env bash
# New-user kit (slides, audio, video, briefing) via NotebookLM.
# Requires: notebooklm CLI authenticated (`notebooklm auth check --test`).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

NB_NAME="Snow Gloves OS — New user"
OUT_DIR="docs/assets/user"
PROMPT_FILE="docs/notebooklm/PROMPT-user.md"
mkdir -p "$OUT_DIR"

echo "→ auth..."
notebooklm auth check --test --json | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok' and d.get('checks',{}).get('token_fetch') is True, d"

echo "→ creating notebook '$NB_NAME'..."
NB_RAW=$(notebooklm create "$NB_NAME" --json)
NB_ID=$(python3 -c "import sys,json; d=json.load(sys.stdin); print((d.get('notebook') or d).get('id'))" <<<"$NB_RAW")
notebooklm use "$NB_ID"
echo "  id: $NB_ID"

echo "→ adding user-facing sources..."
notebooklm source add README.md
notebooklm source add docs/onboarding.md
notebooklm source add docs/catalog.md
notebooklm source add docs/adapters.md

echo "→ waiting for sources..."
python3 - <<'PY'
import json, subprocess
raw = subprocess.check_output(["notebooklm", "source", "list", "--json"], text=True)
data = json.loads(raw)
sources = data.get("sources") or data.get("items") or (data if isinstance(data, list) else [])
for s in sources:
    sid = s.get("id") or s.get("source_id")
    if sid:
        subprocess.call(["notebooklm", "source", "wait", sid, "--timeout", "600"])
PY

PROMPT=$(awk '/^```$/{f=!f;next} f' "$PROMPT_FILE")

wait_dl() {
  local kind="$1" out="$2" extra=("${@:3}")
  echo "→ generate $kind..."
  GEN=$(notebooklm generate "$kind" --json "${extra[@]}" "$PROMPT" || notebooklm generate "$kind" --json "${extra[@]}")
  TASK=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('task_id') or d.get('id') or '')" <<<"$GEN")
  if [[ -z "$TASK" ]]; then
    echo "$GEN" >&2
    echo "failed to parse task id for $kind" >&2
    exit 1
  fi
  notebooklm artifact wait "$TASK" --timeout 1800
  notebooklm download "$kind" "$out" -a "$TASK"
  echo "  → $out"
}

wait_dl slide-deck "$OUT_DIR/snowgloves-user.pdf" --format detailed --length default --retry 2
wait_dl audio "$OUT_DIR/snowgloves-user.mp3"
wait_dl video "$OUT_DIR/snowgloves-user.mp4"
echo "→ generate briefing..."
GEN=$(notebooklm generate report --format briefing-doc --json --append "$PROMPT")
TASK=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('task_id') or d.get('id') or '')" <<<"$GEN")
notebooklm artifact wait "$TASK" --timeout 1800
notebooklm download report "$OUT_DIR/snowgloves-user-briefing.md" -a "$TASK"

python3 - <<PY
import json, pathlib
path = pathlib.Path("docs/notebooklm/user-notebook.json")
path.write_text(json.dumps({"notebook_id": "$NB_ID", "notebook_title": "$NB_NAME"}, indent=2) + "\n")
print("wrote", path)
PY

echo "✓ user kit → $OUT_DIR"
