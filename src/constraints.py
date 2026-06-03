"""
src/constraints.py — DETERMINISTIC hard constraint checks.
No LLM. No randomness. These are always right.

Two checks:
  1. check_prerequisites  — has the student done the required courses?
  2. check_time_conflict  — do two courses overlap on the same day/time?

These are plain Python. They have unit tests.
The agent never asks an LLM to check time arithmetic.
"""

from datetime import datetime


def _parse_time(t: str) -> datetime:
    """Convert '09:30' → datetime object (date doesn't matter, only time)."""
    return datetime.strptime(t, "%H:%M")


def check_prerequisites(course: dict, completed: list[str]) -> tuple[bool, str]:
    """
    Returns (passes: bool, reason: str).
    passes=True  → student has all prereqs, course is eligible.
    passes=False → at least one prereq is missing.
    """
    missing = [p for p in course.get("prereqs", []) if p not in completed]
    if missing:
        return False, f"Missing prereqs: {', '.join(missing)}"
    return True, "All prerequisites met"


def check_time_conflict(course_a: dict, course_b: dict) -> tuple[bool, str]:
    """
    Returns (conflict: bool, reason: str).
    conflict=True  → the two courses overlap on at least one shared day.
    conflict=False → no overlap.

    Overlap logic: two time ranges [s1,e1] and [s2,e2] overlap when
      s1 < e2  AND  s2 < e1
    """
    # Find shared days
    days_a = set(course_a.get("days", []))
    days_b = set(course_b.get("days", []))
    shared_days = days_a & days_b

    if not shared_days:
        return False, "No shared days"

    s1 = _parse_time(course_a["start"])
    e1 = _parse_time(course_a["end"])
    s2 = _parse_time(course_b["start"])
    e2 = _parse_time(course_b["end"])

    overlaps = s1 < e2 and s2 < e1
    if overlaps:
        days_str = ", ".join(sorted(shared_days))
        return True, (
            f"{course_a['id']} ({course_a['start']}-{course_a['end']}) "
            f"conflicts with {course_b['id']} ({course_b['start']}-{course_b['end']}) "
            f"on {days_str}"
        )
    return False, "No time overlap"


def check_corequisites(selected_ids: list[str], catalog: list[dict]) -> list[dict]:
    """
    Co-requisite check (VIT-style): if a course requires a co-requisite,
    BOTH must be in the schedule together (e.g. BCSE204L theory needs
    BCSE204P lab). Returns a list of violations.

    Deterministic — no LLM.
    """
    catalog_map = {c["id"]: c for c in catalog}
    selected    = set(selected_ids)
    violations  = []

    for cid in selected_ids:
        course = catalog_map.get(cid)
        if not course:
            continue
        coreq = course.get("corequisite")
        if coreq and coreq not in selected:
            violations.append({
                "course_id": cid,
                "missing_coreq": coreq,
                "reason": (
                    f"{cid} ({course['name']}) requires its co-requisite "
                    f"{coreq} to be taken in the same semester."
                ),
            })
    return violations


def is_early_class(course: dict, cutoff: str = "09:00") -> tuple[bool, str]:
    """
    Returns (is_early: bool, reason: str).
    is_early=True → course starts before the cutoff time.
    """
    start = _parse_time(course["start"])
    cut   = _parse_time(cutoff)
    if start < cut:
        return True, f"{course['id']} starts at {course['start']}, before cutoff {cutoff}"
    return False, f"{course['id']} starts at {course['start']}, after cutoff {cutoff}"


def filter_eligible_courses(
    wanted: list[str],
    catalog: list[dict],
    completed: list[str],
) -> dict:
    """
    Given a list of course IDs the student wants,
    return a dict split into eligible and ineligible (with reasons).
    """
    catalog_map = {c["id"]: c for c in catalog}
    eligible   = []
    ineligible = []

    for cid in wanted:
        if cid not in catalog_map:
            ineligible.append({"id": cid, "reason": "Course not found in catalog"})
            continue
        course = catalog_map[cid]
        ok, reason = check_prerequisites(course, completed)
        if ok:
            eligible.append(course)
        else:
            ineligible.append({"id": cid, "reason": reason})

    return {"eligible": eligible, "ineligible": ineligible}


def find_all_conflicts(courses: list[dict]) -> list[dict]:
    """
    Given a list of courses, return all conflicting pairs.
    Checks every pair once (O(n²) — fine for ≤40 courses).
    """
    conflicts = []
    for i in range(len(courses)):
        for j in range(i + 1, len(courses)):
            conflict, reason = check_time_conflict(courses[i], courses[j])
            if conflict:
                conflicts.append({
                    "course_a": courses[i]["id"],
                    "course_b": courses[j]["id"],
                    "reason":   reason,
                })
    return conflicts
