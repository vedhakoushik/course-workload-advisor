"""
src/models.py — Pydantic structured output models.

Every course decision the agent makes must match CourseDecision.
If the LLM returns bad JSON, the harness repairs it rather than crashing.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class Decision(str, Enum):
    IN       = "in"        # recommend taking this course
    OUT      = "out"       # recommend skipping
    CONFLICT = "conflict"  # agent can't decide — student must choose


class Confidence(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


class CourseDecision(BaseModel):
    course_id:       str
    course_name:     str
    decision:        Decision
    reason:          str = Field(description="1-2 sentence plain English explanation")
    workload_hrs:    int = Field(ge=0, description="Estimated study hours per week")
    confidence:      Confidence
    escalate_reason: Optional[str] = None  # set when decision=conflict

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("reason cannot be empty")
        return v.strip()


class ScheduleResult(BaseModel):
    student_name:     str
    recommended:      list[CourseDecision]   # decision=in
    excluded:         list[CourseDecision]   # decision=out
    escalated:        list[CourseDecision]   # decision=conflict
    total_credits:    int
    total_workload_hrs_per_week: int
    job_hrs_per_week: int
    total_hrs_per_week: int
    is_overloaded:    bool
    summary:          str    # the student-readable paragraph


class StudentProfile(BaseModel):
    name:              str
    year:              int
    major:             str
    job_hrs_per_week:  int
    completed_courses: list[str]
    wants_to_take:     list[str]
    no_early_classes:  bool = True
    early_cutoff:      str  = "09:00"
    max_credits:       int  = 12
    max_workload_hrs:  int  = 35
    free_text:         str  = ""
