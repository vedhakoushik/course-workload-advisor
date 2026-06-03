# 📚 Course Workload Advisor Agent

An AI agent that takes a student's situation in plain English — *"I'm a 2nd-year CS major, I work 15 hrs/week, I'm bad at 8am classes, I need two electives and a math requirement"* — plus a course catalog, and recommends a semester schedule. For every course it explains **why it's in or out**, estimates **workload**, gives a **confidence**, and **flags conflicts it can't decide** for the student to resolve.

> Built to demonstrate the core agent-engineering lesson: **hard constraints belong in deterministic code, soft preferences belong in the LLM** — and never mix them up.

---

## ✨ What it does

- **Free-text input** — describe your situation naturally; Gemini parses it into a structured profile
- **Wishlist upload** — drop in a `.json` / `.csv` / `.txt` of course IDs (works with real university exports)
- **Per-course decision** — `in` / `out` / `conflict`, each with a reason, workload estimate, and confidence
- **Interactive conflict resolution** — when the agent genuinely can't decide (e.g. required course only runs at 8am, or two courses overlap), it escalates and you make the call in-app
- **Workload aggregation** — rolls per-course hours up to "is this semester survivable with your job?"
- **Real VIT catalog** — includes a catalog extracted from a live VIT registration portal, with **co-requisite** enforcement (lab + theory must be taken together)

---

## 🏗️ Architecture

```
Student free text / wishlist
          │
          ▼
  ┌───────────────────────────────────────────┐
  │  DETERMINISTIC CORE  (src/constraints.py)  │  ← plain Python, unit-tested
  │   • check_prerequisites()                  │
  │   • check_time_conflict()                  │
  │   • check_corequisites()                   │
  └───────────────────────────────────────────┘
          │  (only courses that pass hard constraints)
          ▼
  ┌───────────────────────────────────────────┐
  │  LLM REASONING  (src/advisor.py + Gemini)  │  ← soft preferences only
  │   • workload fit, preference match         │
  │   • returns structured CourseDecision      │
  └───────────────────────────────────────────┘
          │
          ▼
  Workload aggregation → escalation → final schedule
```

**The LLM never does time arithmetic.** `10:00–11:30` overlapping `11:00–12:30` is deterministic code that's always right — not a probabilistic guess.

---

## 🚀 Quick start

```bash
# 1. Clone
git clone https://github.com/vedhakoushik/course-workload-advisor.git
cd course-workload-advisor

# 2. Install
pip install -r requirements.txt

# 3. Add your API key
cp .env.example .env
# then edit .env and paste your Gemini key (free at https://aistudio.google.com/app/apikey)

# 4. Run the web app
streamlit run app.py
#  → opens at http://localhost:8501
```

No key? You can still run the deterministic core and tests (no API needed):

```bash
python main.py                       # Phase-1 hard-constraint demo
python -m pytest tests/ -v           # 23 unit tests
python evals/run_evals.py --dry-run  # hard-constraint accuracy (no API)
```

---

## 🧪 Harness & Evals

**Harness** (the scaffolding that makes the agent testable):
| Piece | File | Role |
|---|---|---|
| Structured output | `src/models.py` | Pydantic enums force valid `in/out/conflict` decisions |
| Repair | `src/advisor.py` | bad JSON / out-of-enum → repaired, never crashes |
| Deterministic core | `src/constraints.py` | prereq / time / co-req checks in plain code |
| Unit tests | `tests/test_constraints.py` | **23 tests, 100% passing** |

**Evals** (measuring if the agent is good):
| Eval | File | Result |
|---|---|---|
| Hard-constraint accuracy | `evals/run_evals.py` | **100%** — never recommends a time conflict or missing prereq |
| Soft-preference quality | `evals/run_evals.py` | F1 / precision / recall vs 15 hand-labeled profiles |
| Labeled dataset | `data/eval_profiles.json` | 15 student profiles with expected schedules |

```bash
python evals/run_evals.py --dry-run   # hard constraints only (no API, instant)
python evals/run_evals.py             # full run with LLM soft scoring
```

---

## 📁 Structure

```
app.py                    Streamlit web UI (input, results, conflict resolution)
main.py                   CLI demo of the deterministic core
src/
  constraints.py          hard constraint checks (prereq, time, co-req)
  models.py               Pydantic structured-output models
  advisor.py              the agent (hard filter → LLM → aggregate → escalate)
data/
  catalog.json            demo catalog (15 courses)
  vit_catalog.json        real VIT catalog with co-requisites
  eval_profiles.json      15 hand-labeled eval profiles
  sample_wishlist.json    example wishlist upload
tests/
  test_constraints.py     23 unit tests for the deterministic core
evals/
  run_evals.py            evaluation harness
```

---

## 🧠 Design decisions

- **Hard vs soft split** — prerequisites, time conflicts, and co-requisites are deterministic and 100%-reliable; only fuzzy preferences ("I hate mornings", "is 4 courses + a job too much?") go to the LLM.
- **Escalation over guessing** — when the only section of a required course clashes with a hard preference, the agent refuses to silently pick and instead asks the student.
- **Structured output + repair** — every LLM response is validated against a Pydantic schema; malformed output is repaired to a safe default instead of crashing a 40-course run.

---

## 📝 License

MIT — free to use, learn from, and build on.
