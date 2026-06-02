"""
evals/run_evals.py — Evaluation harness.

Two kinds of correctness:
  1. Hard-constraint accuracy: did the agent ever recommend a time conflict
     or a course with missing prereqs? Should be 100%. Checked in code.
  2. Soft-preference quality: does the schedule match the hand-labeled expected output?

Run:
  python evals/run_evals.py              # full eval (uses API)
  python evals/run_evals.py --dry-run    # constraint checks only, no LLM
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.constraints import check_prerequisites, check_time_conflict
from src.models import Decision, StudentProfile

DATA    = ROOT / "data"
CATALOG = json.loads((DATA / "catalog.json").read_text())
CATALOG_MAP = {c["id"]: c for c in CATALOG}


# ── Hard constraint verifier (deterministic, no LLM) ─────────────────────────

def verify_hard_constraints(recommended_ids: list[str], student: StudentProfile) -> list[str]:
    """
    Returns list of violations. Empty = perfect.
    Checks: no missing prereqs, no time conflicts.
    """
    violations = []
    courses = [CATALOG_MAP[cid] for cid in recommended_ids if cid in CATALOG_MAP]

    # Prereq check
    for c in courses:
        ok, reason = check_prerequisites(c, student.completed_courses)
        if not ok:
            violations.append(f"PREREQ VIOLATION: {c['id']} — {reason}")

    # Time conflict check
    for i in range(len(courses)):
        for j in range(i + 1, len(courses)):
            conflict, reason = check_time_conflict(courses[i], courses[j])
            if conflict:
                violations.append(f"TIME CONFLICT: {reason}")

    return violations


# ── Soft preference scorer ────────────────────────────────────────────────────

def score_soft(
    recommended_ids: list[str],
    expected_in: list[str],
    expected_out: list[str],
) -> dict:
    """
    Compare agent output to hand-labeled expected schedule.
    Returns precision, recall, f1 (standard ML metrics on the 'in' decision).
    """
    rec_set = set(recommended_ids)
    exp_set = set(expected_in)

    true_pos  = len(rec_set & exp_set)              # correctly included
    false_pos = len(rec_set - exp_set)              # included but shouldn't be
    false_neg = len(exp_set - rec_set)              # should be included but isn't

    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) > 0 else 1.0
    recall    = true_pos / (true_pos + false_neg) if (true_pos + false_neg) > 0 else 1.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)

    return {
        "precision":  round(precision, 2),
        "recall":     round(recall, 2),
        "f1":         round(f1, 2),
        "true_pos":   true_pos,
        "false_pos":  false_pos,
        "false_neg":  false_neg,
        "got":        sorted(rec_set),
        "expected":   sorted(exp_set),
    }


# ── Main eval loop ────────────────────────────────────────────────────────────

def run_evals(dry_run: bool = False):
    profiles = json.loads((DATA / "eval_profiles.json").read_text())

    print("=" * 68)
    print(f"  Course Advisor Eval — {len(profiles)} profiles")
    print(f"  Mode: {'DRY RUN (hard constraints only)' if dry_run else 'FULL (LLM enabled)'}")
    print("=" * 68)

    results        = []
    total_hard_violations = 0

    for prof in profiles:
        pid     = prof["id"]
        student = StudentProfile(**prof["student"])
        exp_in  = prof["expected_in"]
        exp_out = prof["expected_out"]

        print(f"\n[{pid}] {student.name} — ", end="")

        if dry_run:
            # Only test hard constraint violations on expected_in labels
            violations = verify_hard_constraints(exp_in, student)
            if violations:
                print(f"VIOLATIONS: {violations}")
                total_hard_violations += len(violations)
            else:
                print("Hard constraints OK on labels")
            results.append({"id": pid, "name": student.name, "hard_violations": violations})
            continue

        # Full run with LLM
        try:
            from src.advisor import run_advisor
            result = run_advisor(student, CATALOG)
            recommended_ids = [d.course_id for d in result.recommended]

            # Hard constraint check on agent output
            violations = verify_hard_constraints(recommended_ids, student)
            total_hard_violations += len(violations)

            # Soft score
            soft = score_soft(recommended_ids, exp_in, exp_out)

            status = "PASS" if not violations else "FAIL"
            print(f"F1={soft['f1']:.2f} precision={soft['precision']:.2f} recall={soft['recall']:.2f} | {status}")

            if violations:
                for v in violations:
                    print(f"  !! {v}")

            results.append({
                "id": pid, "name": student.name,
                "hard_violations": violations,
                "soft": soft,
                "recommended": recommended_ids,
                "expected_in": exp_in,
            })
            time.sleep(2)   # rate limit buffer

        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append({"id": pid, "name": student.name, "error": str(exc)})

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print("  RESULTS SUMMARY")
    print("=" * 68)

    if not dry_run:
        soft_results = [r for r in results if "soft" in r]
        if soft_results:
            avg_f1        = sum(r["soft"]["f1"] for r in soft_results) / len(soft_results)
            avg_precision = sum(r["soft"]["precision"] for r in soft_results) / len(soft_results)
            avg_recall    = sum(r["soft"]["recall"] for r in soft_results) / len(soft_results)

            print(f"\n  Soft-preference quality ({len(soft_results)} profiles):")
            print(f"    Avg F1:        {avg_f1:.2f}")
            print(f"    Avg Precision: {avg_precision:.2f}")
            print(f"    Avg Recall:    {avg_recall:.2f}")
            print()

            print(f"  {'ID':<6} {'Student':<12} {'F1':<6} {'P':<6} {'R':<6} Violations")
            print("  " + "-" * 55)
            for r in results:
                if "soft" in r:
                    v   = len(r["hard_violations"])
                    s   = r["soft"]
                    row = f"  {r['id']:<6} {r['name']:<12} {s['f1']:<6.2f} {s['precision']:<6.2f} {s['recall']:<6.2f} {'FAIL: '+str(v)+' violations' if v else 'OK'}"
                    print(row)

    hard_status = "100% (no violations)" if total_hard_violations == 0 else f"FAILED — {total_hard_violations} total violations"
    print(f"\n  Hard-constraint accuracy: {hard_status}")
    print(f"  Profiles evaluated: {len(results)}")
    print("=" * 68)

    return results


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run_evals(dry_run=dry)
