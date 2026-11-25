# PyRepair AI – Autonomous Python Debugging & Repair Agent
*Detect. Diagnose. Repair. Verify.*

## Overview
PyRepair AI takes Python code, runs it safely, and if it fails it diagnoses the traceback, generates a
minimal repair, re-runs the code and verifies the result – retrying up to 3 times.

**Problem statement:** debugging is slow and repetitive. **Objective:** build an AI agent that closes the loop
(execute → observe → reason → fix → verify) without human help.

## Features
- AST static analysis (undefined names, risky imports, unreachable code, unused variables, dangerous calls, simple type/index problems)
- Subprocess execution with timeout, temp dir, clean environment, CPU/memory limits and an audit-hook sandbox
- LLM diagnosis (Anthropic or any OpenAI-compatible API) returning strict JSON, plus a working rule-based fallback (no key needed)
- Diff view, confidence score, agent log timeline, downloadable repaired code
- SQLite memory of every session (reopen from History)

## Architecture
```
Code → analyzer (AST) → executor (subprocess) → error? ─no→ verify → success
                                                  └yes→ ai_debugger / fallback → repaired code → executor → verifier → success | retry (max 3)
```
| Folder | Role |
|---|---|
| `core/` | executor, sandbox_runner, analyzer, repair_agent (the loop), verifier, agent_state |
| `ai/` | LLM service, prompts, fallback debugger |
| `database/` | SQLite history |
| `utils/` | diff, logger |
| `examples/` | 7 buggy programs |

## Installation
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

## Environment variables (`.env`)
`AI_PROVIDER` (auto|anthropic|openai|fallback), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
`AI_MODEL`, `MAX_REPAIR_ATTEMPTS`, `EXEC_TIMEOUT`. Leave the keys empty to use the fallback debugger.
Keys can also be entered on the Settings page (kept in the session only).

## Run
```bash
streamlit run app.py
```

## Example usage
Click **Example code**, choose e.g. `IndexError`, press **🚀 Analyze & Repair**, then browse the tabs.
`numbers[5]` is repaired to `numbers[-1]`.

## Safety limitations
User code never runs in the Streamlit process, but this is **not a full sandbox** (Python audit hooks can be
bypassed by determined attackers, Windows has no rlimits). For untrusted code run the app in Docker/VM with no network.

## Future enhancements
Docker sandbox, multi-file projects, unit-test-based verification, more fallback rules, streaming LLM output.
