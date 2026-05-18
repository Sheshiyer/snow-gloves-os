# Quickstart (Spec-Kit Flow)

## Prerequisites

- Python 3.11+
- uv
- AI coding agent integration (Copilot/Codex/etc)

## Initialize (if needed)

```bash
specify init . --here --force --integration copilot
```

## Workflow for this feature

```bash
# 1) Constitution (already drafted)
/speckit.constitution

# 2) Feature spec (already drafted)
/speckit.specify

# 3) Technical plan (already drafted)
/speckit.plan

# 4) Task breakdown (already drafted)
/speckit.tasks

# 5) Execute implementation
/speckit.implement
```

## First implementation slice

Implement one vertical workflow end-to-end:

`Connector event -> interpreted context -> approval policy -> Paperclip task -> execution trace`
