# NotebookLM artifacts

This folder makes the pitch deck **reproducible**. Anyone with the [notebooklm-py](https://github.com/teng-lin/notebooklm-py) CLI and a NotebookLM account can regenerate the deck from the same 5 sources.

## Files
| File | What it is |
|---|---|
| [`PROMPT.md`](./PROMPT.md) | Verbatim prompt + generation settings |
| [`notebook.json`](./notebook.json) | Notebook metadata (id, title, created_at) |
| [`sources.json`](./sources.json) | The 5 source IDs + their original paths |
| [`artifacts.json`](./artifacts.json) | Generated artifact IDs (slide decks, audio, etc.) |
| [`regenerate.sh`](./regenerate.sh) | One-shot reproduce script |

## Sources used
| # | Path in repo | Role |
|---|---|---|
| 1 | `docs/explainer.md` | 8-section narrative tour |
| 2 | `README.md` | Architecture + 4 engines |
| 3 | `.specify/memory/constitution.md` | 7 governing principles |
| 4 | `docs/assets/explainer-hero-1.png` | Hand-in-Glove visual |
| 5 | `docs/assets/explainer-hero-2.png` | Four Engines visual |

## Output
The deck lives at [`docs/assets/snowgloves-pitch.pdf`](../assets/snowgloves-pitch.pdf) — 12 slides, 1376×768 widescreen, ~14 MB.

## Regenerate
```bash
./docs/notebooklm/regenerate.sh
```

This drops a fresh PDF over the existing one, ready to commit. The notebook IDs in `notebook.json` / `sources.json` won't survive regeneration — that's expected; only `PROMPT.md` is meant to be stable input.

## New-user kit (using the product)

Audience is an operator in their first hour, not a contributor. Prompt: [`PROMPT-user.md`](./PROMPT-user.md). Script: [`regenerate-user.sh`](./regenerate-user.sh). Metadata: `user-notebook.json`, `user-sources.json`, `user-artifacts.json`.

| Artifact | Local | Published |
|---|---|---|
| Slides | [`docs/assets/user/snowgloves-user.pdf`](../assets/user/snowgloves-user.pdf) | wiki `/user/` |
| Briefing | [`docs/assets/user/snowgloves-user-briefing.md`](../assets/user/snowgloves-user-briefing.md) | wiki `/user/` |
| Audio, video | generated locally; gitignored here | [snow-gloves-wiki](https://github.com/Sheshiyer/snow-gloves-wiki) `public/user/` |

```bash
./docs/notebooklm/regenerate-user.sh
```

## Ideas for additional artifacts
Same notebook, different `notebooklm generate` calls:
| Command | Output |
|---|---|
| `notebooklm generate audio-overview` | 8-12 min hosted podcast (`.mp3`) |
| `notebooklm generate video --style whiteboard` | Animated explainer video |
| `notebooklm generate mind-map` | Concept graph |
| `notebooklm generate study-guide` | Onboarding doc for new contributors |
| `notebooklm generate briefing` | Executive 1-pager |
