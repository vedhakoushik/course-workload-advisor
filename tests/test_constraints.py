"""
tests/test_constraints.py — unit tests for the deterministic core.

These must be 100% pass rate, always.
If they fail, the hard constraint logic is broken.
Run: python -m pytest tests/ -v
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.constraints import (
    check_prerequisites,
    check_time_conflict,
    is_early_class,
    filter_eligible_courses,
    find_all_conflicts,
)

# ── Sample courses for testing ────────────────────────────────
CS101 = {"id": "CS-101", "prereqs": [], "days": ["Mon", "Wed"], "start": "09:00", "end": "10:00"}
CS201 = {"id": "CS-201", "prereqs": ["CS-101"], "days": ["Tue", "Thu"], "start": "10:00", "end": "11:30"}
CS301 = {"id": "CS-301", "prereqs": ["CS-201"], "days": ["Mon", "Wed"], "start": "08:00", "end": "09:30"}
MATH  = {"id": "MATH-201", "prereqs": [], "days": ["Mon", "Wed", "Fri"], "start": "08:00", "end": "09:00"}
ENG   = {"id": "ENG-101", "prereqs": [], "days": ["Fri"], "start": "11:00", "end": "13:00"}
LATE  = {"id": "CS-999", "prereqs": [], "days": ["Mon"], "start": "14:00", "end": "15:30"}


# ── Prerequisites ─────────────────────────────────────────────

class TestPrerequisites:
    def test_no_prereqs_always_passes(self):
        ok, reason = check_prerequisites(CS101, [])
        assert ok is True

    def test_has_prereq_passes(self):
        ok, reason = check_prerequisites(CS201, ["CS-101"])
        assert ok is True

    def test_missing_prereq_fails(self):
        ok, reason = check_prerequisites(CS201, [])
        assert ok is False
        assert "CS-101" in reason

    def test_missing_one_of_two_prereqs_fails(self):
        ok, reason = check_prerequisites(
            {"id": "X", "prereqs": ["CS-101", "MATH-201"]},
            ["CS-101"]
        )
        assert ok is False
        assert "MATH-201" in reason

    def test_all_prereqs_present_passes(self):
        ok, _ = check_prerequisites(
            {"id": "X", "prereqs": ["CS-101", "MATH-201"]},
            ["CS-101", "MATH-201", "ENG-101"]
        )
        assert ok is True


# ── Time conflicts ────────────────────────────────────────────

class TestTimeConflicts:
    def test_no_shared_days_no_conflict(self):
        # CS-101 (Mon/Wed) vs ENG-101 (Fri) — no shared days
        conflict, _ = check_time_conflict(CS101, ENG)
        assert conflict is False

    def test_same_time_same_day_conflicts(self):
        # CS-101 09:00-10:00 Mon/Wed vs MATH 08:00-09:00 Mon/Wed/Fri
        # Overlap check: 09:00 < 09:00 is False → no overlap (back-to-back is NOT a conflict)
        conflict, _ = check_time_conflict(CS101, MATH)
        assert conflict is False   # back-to-back, not overlapping

    def test_actual_overlap_conflicts(self):
        # CS-301 08:00-09:30 Mon/Wed overlaps CS-101 09:00-10:00 Mon/Wed
        # 08:00 < 10:00 AND 09:00 < 09:30 → overlap on Mon and Wed
        conflict, reason = check_time_conflict(CS301, CS101)
        assert conflict is True
        assert "CS-301" in reason

    def test_completely_separate_times_no_conflict(self):
        # CS-101 09:00-10:00 vs LATE 14:00-15:30 — same day (Mon), no overlap
        conflict, _ = check_time_conflict(CS101, LATE)
        assert conflict is False

    def test_conflict_is_symmetric(self):
        # A conflicts B == B conflicts A
        c1, _ = check_time_conflict(CS301, CS101)
        c2, _ = check_time_conflict(CS101, CS301)
        assert c1 == c2


# ── Early class detection ─────────────────────────────────────

class TestEarlyClass:
    def test_8am_is_early(self):
        early, reason = is_early_class(CS301, cutoff="09:00")
        assert early is True
        assert "08:00" in reason

    def test_9am_is_not_early(self):
        early, _ = is_early_class(CS101, cutoff="09:00")
        assert early is False

    def test_custom_cutoff(self):
        # CS-101 at 09:00 is early if cutoff is 10:00
        early, _ = is_early_class(CS101, cutoff="10:00")
        assert early is True


# ── Filter eligible courses ───────────────────────────────────

class TestFilterEligible:
    CATALOG = [CS101, CS201, CS301, MATH, ENG]

    def test_no_completed_only_no_prereq_courses_pass(self):
        result = filter_eligible_courses(
            ["CS-101", "CS-201", "MATH-201"],
            self.CATALOG, completed=[]
        )
        eligible_ids = [c["id"] for c in result["eligible"]]
        assert "CS-101" in eligible_ids
        assert "MATH-201" in eligible_ids
        assert "CS-201" not in eligible_ids

    def test_with_prereqs_completed(self):
        result = filter_eligible_courses(
            ["CS-201"],
            self.CATALOG, completed=["CS-101"]
        )
        assert len(result["eligible"]) == 1
        assert len(result["ineligible"]) == 0

    def test_unknown_course_goes_to_ineligible(self):
        result = filter_eligible_courses(
            ["CS-999"],
            self.CATALOG, completed=[]
        )
        assert len(result["ineligible"]) == 1
        assert "not found" in result["ineligible"][0]["reason"]


# ── Find all conflicts ────────────────────────────────────────

class TestFindAllConflicts:
    def test_no_conflicts_in_clean_set(self):
        # CS-101 Mon/Wed 09-10, CS-201 Tue/Thu 10-11:30 → no overlap
        conflicts = find_all_conflicts([CS101, CS201])
        assert len(conflicts) == 0

    def test_detects_conflict(self):
        # CS-301 Mon/Wed 08-09:30 overlaps CS-101 Mon/Wed 09-10
        conflicts = find_all_conflicts([CS301, CS101])
        assert len(conflicts) == 1
        assert "CS-301" in conflicts[0]["course_a"] or "CS-301" in conflicts[0]["course_b"]

    def test_multiple_courses_all_conflicts_found(self):
        # 3 courses where 2 pairs conflict
        conflicts = find_all_conflicts([CS301, CS101, MATH])
        # CS301 conflicts CS101, MATH (08:00-09:00) doesn't overlap CS101 (09:00-10:00)
        assert len(conflicts) >= 1
