# Course Workload Advisor Agent

AI agent that recommends a semester schedule based on a student's situation, constraints, and preferences.

## How it works

1. **Hard constraints (deterministic code)** — prerequisite checks and time-conflict detection in plain Python. Never uses an LLM for math.
2. **Soft preferences (Gemini)** — workload reasoning, preference matching, confidence scoring.
3. **Eval harness** — 15 labelled student profiles, hard-constraint accuracy (target 100%), soft-preference scoring, determinism test.

## Run

```bash
# Phase 1 — deterministic filter only
python main.py

# Tests
python -m pytest tests/ -v
```

## Structure

```
data/
  catalog.json          10 sample courses (times, prereqs, workload)
  student_profile.json  sample student profile
src/
  constraints.py        hard constraint checks (prereqs, time conflicts)
tests/
  test_constraints.py   19 unit tests
main.py                 Phase 1 runner
```

## Status

- [x] Phase 1 — deterministic core + unit tests
- [ ] Phase 2 — Gemini preference reasoning + structured output
- [ ] Phase 3 — eval harness + 15 labelled profiles
- [ ] Phase 4 — write-up + Loom
