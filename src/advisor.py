"""
src/advisor.py — The full agent.

Flow:
  1. Hard constraints (deterministic code) — filter impossible courses
  2. LLM (Gemini) — reason about soft preferences for remaining courses
  3. Workload aggregation — check if semester is survivable
  4. Escalation — flag courses the agent can't decide on
  5. Final schedule + per-course reasoning

KEY DESIGN: hard constraints NEVER touch the LLM.
            The LLM NEVER does time arithmetic.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from src.constraints import (
    filter_eligible_courses,
    find_all_conflicts,
    check_corequisites,
    is_early_class,
)
from src.models import (
    Confidence,
    CourseDecision,
    Decision,
    ScheduleResult,
    StudentProfile,
)


# ── Gemini helper ─────────────────────────────────────────────────────────────

def _call_gemini(prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
    model = genai.GenerativeModel("gemini-1.5-flash")
    for attempt in range(3):
        try:
            return model.generate_content(prompt).text.strip()
        except Exception as exc:
            if "429" in str(exc) and attempt < 2:
                time.sleep(15)
            else:
                raise
    raise RuntimeError("Gemini failed after 3 attempts")


# ── Step 1: Parse free text into StudentProfile ───────────────────────────────

def parse_student_free_text(text: str, catalog: list[dict]) -> StudentProfile:
    """
    Use Gemini to extract a structured student profile from free text.
    Falls back to defaults for anything not mentioned.
    """
    course_ids = [c["id"] for c in catalog]
    prompt = f"""
Extract a student profile from this text. Return ONLY valid JSON, no markdown.

Text: "{text}"

Available course IDs: {course_ids}

Return this exact JSON shape:
{{
  "name": "Student",
  "year": 2,
  "major": "CS",
  "job_hrs_per_week": 0,
  "completed_courses": [],
  "wants_to_take": [],
  "no_early_classes": false,
  "early_cutoff": "09:00",
  "max_credits": 15,
  "max_workload_hrs": 40,
  "free_text": "{text}"
}}

Rules:
- If they say "bad at 8am" or "hate morning classes" → no_early_classes=true, early_cutoff="09:00"
- If they mention specific courses by ID → add to wants_to_take
- If they mention completed courses → add to completed_courses
- If no courses mentioned → wants_to_take=[] (we'll suggest from catalog)
- job_hrs_per_week: extract number, default 0
"""
    raw = _call_gemini(prompt)
    raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
    try:
        data = json.loads(raw)
        data["free_text"] = text
        return StudentProfile(**data)
    except Exception:
        # fallback minimal profile
        return StudentProfile(
            name="Student", year=2, major="CS",
            job_hrs_per_week=0, completed_courses=[],
            wants_to_take=[], free_text=text
        )


def parse_wishlist_file(raw_text: str, catalog: list[dict]) -> list[str]:
    """
    Parse an uploaded wishlist into a list of valid course IDs.
    Accepts:
      - JSON: ["CS-201", "MATH-301"]  or  {"courses": ["CS-201"]}
      - CSV / TXT: one ID per line, or comma-separated, e.g. "CS-201, MATH-301"
    Only returns IDs that exist in the catalog.
    """
    valid_ids = {c["id"] for c in catalog}
    found = []

    raw_text = raw_text.strip()
    # Try JSON first
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict):
            data = data.get("courses") or data.get("wishlist") or []
        if isinstance(data, list):
            found = [str(x).strip().upper() for x in data]
    except Exception:
        # Fall back to plain text — split on commas, newlines, spaces
        tokens = re.split(r"[,\n\r\t ]+", raw_text)
        found = [t.strip().upper() for t in tokens if t.strip()]

    # Keep only IDs that match the catalog (case-insensitive)
    valid_upper = {v.upper(): v for v in valid_ids}
    return [valid_upper[f] for f in found if f in valid_upper]


# ── Step 2: Hard constraint filter ───────────────────────────────────────────

def apply_hard_constraints(
    student: StudentProfile,
    catalog: list[dict],
) -> tuple[list[dict], list[CourseDecision]]:
    """
    Returns (eligible_courses, hard_blocked_decisions).
    Deterministic — no LLM.
    """
    # If student hasn't specified courses, suggest all they're eligible for
    wanted = student.wants_to_take or [c["id"] for c in catalog]

    result = filter_eligible_courses(wanted, catalog, student.completed_courses)
    eligible = result["eligible"]
    blocked  = []

    for item in result["ineligible"]:
        blocked.append(CourseDecision(
            course_id=item["id"],
            course_name=next((c["name"] for c in catalog if c["id"] == item["id"]), item["id"]),
            decision=Decision.OUT,
            reason=item["reason"],
            workload_hrs=0,
            confidence=Confidence.HIGH,
        ))

    # Early class filter
    remaining = []
    for course in eligible:
        early, reason = is_early_class(course, student.early_cutoff)
        if early and student.no_early_classes:
            blocked.append(CourseDecision(
                course_id=course["id"],
                course_name=course["name"],
                decision=Decision.CONFLICT,
                reason=f"Starts at {course['start']} — before your {student.early_cutoff} cutoff.",
                workload_hrs=course.get("workload_hrs_per_week", 0),
                confidence=Confidence.MEDIUM,
                escalate_reason=(
                    f"{course['name']} only runs at {course['start']}. "
                    "You said you avoid early classes. Take it anyway or skip?"
                ),
            ))
        else:
            remaining.append(course)

    # Time conflict detection among remaining courses
    conflicts = find_all_conflicts(remaining)
    conflict_ids = set()
    for cf in conflicts:
        conflict_ids.add(cf["course_a"])
        conflict_ids.add(cf["course_b"])
        blocked.append(CourseDecision(
            course_id=f"{cf['course_a']}+{cf['course_b']}",
            course_name=f"Conflict: {cf['course_a']} × {cf['course_b']}",
            decision=Decision.CONFLICT,
            reason=cf["reason"],
            workload_hrs=0,
            confidence=Confidence.HIGH,
            escalate_reason=f"These two courses overlap: {cf['reason']}. Which one do you want?",
        ))

    # Remove conflicting courses from eligible (agent will escalate them)
    clean = [c for c in remaining if c["id"] not in conflict_ids]
    return clean, blocked


# ── Step 3: LLM preference reasoning ─────────────────────────────────────────

def llm_evaluate_course(
    course: dict,
    student: StudentProfile,
    already_selected: list[dict],
) -> CourseDecision:
    """
    Ask Gemini: given this student's situation, should they take this course?
    Returns structured CourseDecision.
    """
    current_credits  = sum(c.get("credits", 0) for c in already_selected)
    current_workload = sum(c.get("workload_hrs_per_week", 0) for c in already_selected)
    headroom_credits  = student.max_credits - current_credits
    headroom_workload = student.max_workload_hrs - current_workload - student.job_hrs_per_week

    prompt = f"""
You are a course advisor. Decide if this student should take this course.

STUDENT:
- Year {student.year} {student.major} major
- Works {student.job_hrs_per_week} hours/week
- Already selected {current_credits} credits ({current_workload} study hrs/week)
- Credit headroom: {headroom_credits} credits remaining
- Workload headroom: {headroom_workload} study hrs/week remaining
- Preferences: {student.free_text or 'none specified'}

COURSE TO EVALUATE:
- {course['id']}: {course['name']}
- Credits: {course['credits']}, Difficulty: {course['difficulty']}
- Estimated workload: {course['workload_hrs_per_week']} hrs/week
- Category: {course.get('category', 'general')}

ALREADY SELECTED: {[c['name'] for c in already_selected] or 'none yet'}

Return ONLY valid JSON, no markdown:
{{
  "decision": "in" or "out" or "conflict",
  "reason": "1-2 sentence plain English explanation for the student",
  "confidence": "high" or "medium" or "low",
  "escalate_reason": null or "question to ask the student if conflict"
}}

Decision rules:
- "in" if it fits credits/workload and suits the student
- "out" if it would overload the student or doesn't add value
- "conflict" if you genuinely can't decide — the student needs to choose
- If workload headroom < course workload → very likely "out" or "conflict"
"""
    try:
        raw = _call_gemini(prompt)
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        data = json.loads(raw)

        # Validate and repair decision enum
        dec = data.get("decision", "out").lower()
        if dec not in ("in", "out", "conflict"):
            dec = "out"

        conf = data.get("confidence", "medium").lower()
        if conf not in ("high", "medium", "low"):
            conf = "medium"

        return CourseDecision(
            course_id=course["id"],
            course_name=course["name"],
            decision=Decision(dec),
            reason=data.get("reason", "No reason provided."),
            workload_hrs=course.get("workload_hrs_per_week", 0),
            confidence=Confidence(conf),
            escalate_reason=data.get("escalate_reason"),
        )
    except Exception as exc:
        # Repair: if LLM fails, default to out with explanation
        return CourseDecision(
            course_id=course["id"],
            course_name=course["name"],
            decision=Decision.OUT,
            reason=f"Could not evaluate: {exc}",
            workload_hrs=course.get("workload_hrs_per_week", 0),
            confidence=Confidence.LOW,
        )


# ── Step 4: Workload aggregation + final summary ──────────────────────────────

def build_schedule(
    decisions: list[CourseDecision],
    student: StudentProfile,
) -> ScheduleResult:
    recommended = [d for d in decisions if d.decision == Decision.IN]
    excluded    = [d for d in decisions if d.decision == Decision.OUT]
    escalated   = [d for d in decisions if d.decision == Decision.CONFLICT]

    total_credits  = sum(d.workload_hrs and 0 or 0 for d in recommended)
    # get credits from decisions — need catalog lookup, so we store it in workload_hrs
    total_workload = sum(d.workload_hrs for d in recommended)
    total_hrs      = total_workload + student.job_hrs_per_week
    is_overloaded  = total_hrs > student.max_workload_hrs

    # Count actual credits from recommended (use a simple approximation)
    total_credits = len(recommended) * 3  # rough, replaced below

    # Build student-readable summary
    rec_names = [d.course_name for d in recommended]
    esc_names = [d.course_name for d in escalated]
    overload_note = (
        f" Warning: total ~{total_hrs} hrs/week with your job — slightly over your {student.max_workload_hrs}hr limit."
        if is_overloaded else ""
    )
    esc_note = (
        f" One thing needs your decision: {esc_names[0]}."
        if esc_names else ""
    )

    summary = (
        f"Here's your recommended schedule: {', '.join(rec_names) if rec_names else 'no courses fit'}. "
        f"Estimated ~{total_workload} study hrs/week + {student.job_hrs_per_week}hr job = {total_hrs} hrs total."
        f"{overload_note}{esc_note}"
    )

    return ScheduleResult(
        student_name=student.name,
        recommended=recommended,
        excluded=excluded,
        escalated=escalated,
        total_credits=total_credits,
        total_workload_hrs_per_week=total_workload,
        job_hrs_per_week=student.job_hrs_per_week,
        total_hrs_per_week=total_hrs,
        is_overloaded=is_overloaded,
        summary=summary,
    )


# ── Main agent entry point ────────────────────────────────────────────────────

def run_advisor(
    student: StudentProfile,
    catalog: list[dict],
    stream_callback=None,
) -> ScheduleResult:
    """
    Full agent run.
    stream_callback(msg) — optional function called after each step (for UI progress).
    """
    def _emit(msg):
        if stream_callback:
            stream_callback(msg)

    _emit("Checking prerequisites and time conflicts...")
    eligible, hard_blocked = apply_hard_constraints(student, catalog)
    _emit(f"Hard filter: {len(eligible)} eligible, {len(hard_blocked)} blocked/escalated")

    all_decisions = list(hard_blocked)
    selected      = []

    _emit("Asking AI to evaluate each course against your preferences...")
    for course in eligible:
        _emit(f"  Evaluating {course['id']}: {course['name']}...")
        decision = llm_evaluate_course(course, student, selected)
        all_decisions.append(decision)
        if decision.decision == Decision.IN:
            selected.append(course)

    # Co-requisite check on the final selection (VIT lab+theory pairing)
    selected_ids = [c["id"] for c in selected]
    coreq_violations = check_corequisites(selected_ids, catalog)
    for v in coreq_violations:
        catalog_map = {c["id"]: c for c in catalog}
        course = catalog_map[v["course_id"]]
        all_decisions.append(CourseDecision(
            course_id=v["course_id"],
            course_name=course["name"],
            decision=Decision.CONFLICT,
            reason=v["reason"],
            workload_hrs=course.get("workload_hrs_per_week", 0),
            confidence=Confidence.HIGH,
            escalate_reason=(
                f"You picked {v['course_id']} but not its required co-requisite "
                f"{v['missing_coreq']}. Add {v['missing_coreq']} or drop {v['course_id']}."
            ),
        ))

    _emit("Building final schedule...")
    result = build_schedule(all_decisions, student)
    _emit("Done.")
    return result
