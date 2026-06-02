"""
main.py — Run the Course Advisor on the hardcoded sample.

Phase 1: deterministic core only (no LLM yet).
Shows exactly what gets filtered and why before the LLM touches anything.

Run: python main.py
"""

import json
from pathlib import Path
from src.constraints import (
    filter_eligible_courses,
    find_all_conflicts,
    is_early_class,
)

DATA = Path(__file__).parent / "data"


def load_data():
    catalog = json.loads((DATA / "catalog.json").read_text())
    student = json.loads((DATA / "student_profile.json").read_text())
    return catalog, student


def run(catalog, student):
    print("=" * 60)
    print(f"  Course Advisor — {student['name']}")
    print(f"  Year {student['year']} {student['major']} | "
          f"Job: {student['job_hrs_per_week']}hr/week")
    print("=" * 60)

    prefs     = student["preferences"]
    completed = student["completed_courses"]
    wanted    = student["wants_to_take"]

    # ── Step 1: Prerequisites filter (deterministic) ──────────
    print("\n[STEP 1] Checking prerequisites...")
    result    = filter_eligible_courses(wanted, catalog, completed)
    eligible  = result["eligible"]
    ineligible = result["ineligible"]

    for c in ineligible:
        print(f"  BLOCKED  {c['id']:<12}  {c['reason']}")
    for c in eligible:
        print(f"  ELIGIBLE {c['id']:<12}  prereqs OK")

    # ── Step 2: Early class filter (deterministic) ────────────
    print(f"\n[STEP 2] Filtering early classes (cutoff {prefs['early_cutoff']})...")
    cutoff     = prefs.get("early_cutoff", "09:00")
    not_early  = []
    for course in eligible:
        early, reason = is_early_class(course, cutoff)
        if early and prefs.get("no_early_classes"):
            print(f"  FLAGGED  {course['id']:<12}  {reason}")
        else:
            not_early.append(course)
            print(f"  OK       {course['id']:<12}  starts {course['start']}")

    # ── Step 3: Time conflict detection (deterministic) ───────
    print("\n[STEP 3] Detecting time conflicts...")
    conflicts = find_all_conflicts(not_early)
    if conflicts:
        for c in conflicts:
            print(f"  CONFLICT {c['course_a']} x {c['course_b']}: {c['reason']}")
    else:
        print("  No time conflicts found.")

    # ── Step 4: Credit + workload check (deterministic) ───────
    print("\n[STEP 4] Workload summary...")
    total_credits  = sum(c["credits"] for c in not_early)
    total_workload = sum(c["workload_hrs_per_week"] for c in not_early)
    total_with_job = total_workload + student["job_hrs_per_week"]

    print(f"  Courses passing hard filters: {len(not_early)}")
    print(f"  Total credits : {total_credits} / {prefs['max_credits']} max")
    print(f"  Study hrs/week: {total_workload}")
    print(f"  + Job hrs/week: {student['job_hrs_per_week']}")
    print(f"  = Total hrs/week: {total_with_job} / {prefs['max_workload_hrs_per_week']} max")

    over_credits  = total_credits  > prefs["max_credits"]
    over_workload = total_with_job > prefs["max_workload_hrs_per_week"]

    if over_credits:
        print(f"  WARNING: Over credit limit by {total_credits - prefs['max_credits']} credits")
    if over_workload:
        print(f"  WARNING: Over workload limit by {total_with_job - prefs['max_workload_hrs_per_week']} hrs/week")

    # ── Summary ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  PHASE 1 RESULT (hard constraints only — no LLM yet)")
    print("=" * 60)
    print(f"\n  Wanted:   {wanted}")
    print(f"  Blocked (prereqs):  {[c['id'] for c in ineligible]}")
    print(f"  Remaining after hard filters: {[c['id'] for c in not_early]}")
    print(f"\n  Phase 2 will: use Gemini to pick the best {prefs['max_credits']}"
          f" credits from the remaining courses based on the student's preferences.")


if __name__ == "__main__":
    catalog, student = load_data()
    run(catalog, student)
