"""
app.py — Course Workload Advisor  (Streamlit UI)

Run: streamlit run app.py
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from src.advisor import parse_student_free_text, run_advisor
from src.models import Decision, StudentProfile

DATA    = Path(__file__).parent / "data"
CATALOG = json.loads((DATA / "catalog.json").read_text())


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Course Advisor",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="auto",
)

st.markdown("""
<style>
body { font-family: 'Inter', sans-serif; }
.stApp { background: #0f1117; color: #e0e0e0; }
.block-container { max-width: 900px; padding-top: 32px; }
.card {
  background: #1a1d27; border: 1px solid #2a2d3a;
  border-radius: 12px; padding: 18px 20px; margin-bottom: 12px;
}
.in-card  { border-left: 4px solid #4ade80; }
.out-card { border-left: 4px solid #f87171; }
.esc-card { border-left: 4px solid #fbbf24; }
.badge-in  { background:#14271a; color:#4ade80; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:700; }
.badge-out { background:#2a1414; color:#f87171; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:700; }
.badge-esc { background:#2a1c10; color:#fbbf24; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:700; }
.conf-high   { color:#4ade80; font-size:11px; }
.conf-medium { color:#fbbf24; font-size:11px; }
.conf-low    { color:#f87171; font-size:11px; }
h1 { font-size:26px !important; font-weight:700 !important; color:#f3f4f6 !important; }
h2 { font-size:18px !important; font-weight:600 !important; color:#f3f4f6 !important; }
h3 { font-size:15px !important; font-weight:600 !important; color:#d1d5db !important; }
</style>
""", unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────────
st.title("📚 Course Workload Advisor")
st.caption("Tell me your situation — I'll recommend a schedule, explain every decision, and flag anything you need to choose yourself.")

if not os.getenv("GEMINI_API_KEY"):
    st.error("GEMINI_API_KEY not set. Add it to your .env file.")
    st.stop()


# ── Input ─────────────────────────────────────────────────────────────────────
st.markdown("### Describe your situation")

col1, col2 = st.columns([3, 1])
with col1:
    free_text = st.text_area(
        "Your situation (free text)",
        placeholder=(
            "e.g. I'm a 2nd-year CS major. I work 15 hrs/week and I'm terrible at "
            "8am classes. I've completed CS-101 and MATH-201. I need CS-201, "
            "MATH-301, and two electives this semester."
        ),
        height=120,
        label_visibility="collapsed",
    )

with col2:
    st.markdown("**Or fill the form:**")
    with st.expander("Structured form", expanded=False):
        f_name  = st.text_input("Name", value="Student")
        f_year  = st.selectbox("Year", [1,2,3,4], index=1)
        f_major = st.text_input("Major", value="CS")
        f_job   = st.number_input("Job hrs/week", 0, 60, 0)
        f_done  = st.text_input("Completed (comma-separated IDs)", value="CS-101, MATH-201")
        f_want  = st.text_input("Want to take (comma-separated IDs, blank=all eligible)", value="")
        f_early = st.toggle("Avoid classes before 9am", value=True)
        f_max_c = st.slider("Max credits", 9, 18, 12)
        f_max_w = st.slider("Max study hrs/week", 20, 60, 35)

# ── Wishlist upload ───────────────────────────────────────────────────────────
st.markdown("### 📄 Or upload your course wishlist")
st.caption("Upload a .json, .csv, or .txt file listing the course IDs you want this semester.")

from src.advisor import parse_wishlist_file
wishlist_ids = []
uploaded = st.file_uploader(
    "Wishlist file",
    type=["json", "csv", "txt"],
    label_visibility="collapsed",
)
if uploaded is not None:
    raw = uploaded.read().decode("utf-8", errors="replace")
    wishlist_ids = parse_wishlist_file(raw, CATALOG)
    if wishlist_ids:
        st.success(f"Found {len(wishlist_ids)} valid course(s): {', '.join(wishlist_ids)}")
    else:
        st.warning("No valid course IDs found in the file. Check the IDs match the catalog.")

# Sample wishlist download so users know the format
with st.expander("What should the file look like?", expanded=False):
    st.markdown("**Any of these formats works:**")
    st.code('["CS-201", "MATH-301", "HUM-101", "ENG-101"]', language="json")
    st.code("CS-201\nMATH-301\nHUM-101\nENG-101", language="text")
    st.code("CS-201, MATH-301, HUM-101, ENG-101", language="text")
    st.download_button(
        "Download a sample wishlist.json",
        data='["CS-201", "MATH-301", "HUM-101", "ENG-101"]',
        file_name="wishlist.json",
        mime="application/json",
    )

# Available courses preview
with st.expander("View available courses (catalog)", expanded=False):
    cols = st.columns(3)
    for i, c in enumerate(CATALOG):
        with cols[i % 3]:
            st.markdown(
                f"**{c['id']}** {c['name']}  \n"
                f"`{c['start']}-{c['end']}` · {c['credits']}cr · {c['difficulty']}  \n"
                f"Prereqs: {', '.join(c['prereqs']) or 'none'}"
            )

run_btn = st.button("Get My Schedule →", type="primary", use_container_width=True)

if not run_btn:
    st.stop()

# ── Build student profile ─────────────────────────────────────────────────────
if free_text.strip():
    with st.spinner("Parsing your situation..."):
        student = parse_student_free_text(free_text.strip(), CATALOG)
    # Uploaded wishlist overrides whatever the free text said they want
    if wishlist_ids:
        student.wants_to_take = wishlist_ids
else:
    student = StudentProfile(
        name=f_name, year=f_year, major=f_major,
        job_hrs_per_week=f_job,
        completed_courses=[x.strip() for x in f_done.split(",") if x.strip()],
        # Wishlist file takes priority over the typed "want to take" field
        wants_to_take=wishlist_ids or [x.strip() for x in f_want.split(",") if x.strip()],
        no_early_classes=f_early,
        early_cutoff="09:00",
        max_credits=f_max_c,
        max_workload_hrs=f_max_w,
        free_text="",
    )

st.divider()

# ── Run the agent ─────────────────────────────────────────────────────────────
status_box = st.empty()
progress   = []

def on_progress(msg):
    progress.append(msg)
    status_box.info("\n".join(f"• {m}" for m in progress[-4:]))

with st.spinner("Analysing your schedule..."):
    result = run_advisor(student, CATALOG, stream_callback=on_progress)

status_box.empty()

# ── Summary banner ────────────────────────────────────────────────────────────
st.markdown("## Your Schedule")
color = "#f87171" if result.is_overloaded else "#4ade80"
st.markdown(
    f'<div class="card" style="border-left:4px solid {color}">'
    f'<p style="font-size:15px;color:#f3f4f6;margin:0">{result.summary}</p>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Metrics ───────────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.metric("Courses in",        len(result.recommended))
m2.metric("Study hrs/week",    result.total_workload_hrs_per_week)
m3.metric("Total hrs/week",    result.total_hrs_per_week,
          delta=f"+{result.total_hrs_per_week - result.max_workload_hrs} over limit"
                if result.is_overloaded else "within limit",
          delta_color="inverse" if result.is_overloaded else "normal")
m4.metric("Needs your input",  len(result.escalated))

st.divider()

# ── Recommended courses ───────────────────────────────────────────────────────
if result.recommended:
    st.markdown("### ✅ Recommended")
    for d in result.recommended:
        conf_cls = f"conf-{d.confidence.value}"
        st.markdown(
            f'<div class="card in-card">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
            f'<span style="font-weight:700;color:#f3f4f6">{d.course_id} — {d.course_name}</span>'
            f'<span class="badge-in">IN</span></div>'
            f'<p style="color:#9ca3af;margin:0 0 4px">{d.reason}</p>'
            f'<span class="conf-{d.confidence.value}">Confidence: {d.confidence.value} · ~{d.workload_hrs} hrs/week</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

# ── Escalated — needs student decision ───────────────────────────────────────
if result.escalated:
    st.markdown("### ⚠️ Needs Your Decision")
    for d in result.escalated:
        st.markdown(
            f'<div class="card esc-card">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
            f'<span style="font-weight:700;color:#f3f4f6">{d.course_id} — {d.course_name}</span>'
            f'<span class="badge-esc">CONFLICT</span></div>'
            f'<p style="color:#9ca3af;margin:0 0 4px">{d.reason}</p>'
            f'<p style="color:#fbbf24;margin:0"><strong>Your call:</strong> {d.escalate_reason or ""}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )

# ── Excluded courses ──────────────────────────────────────────────────────────
if result.excluded:
    with st.expander(f"Excluded courses ({len(result.excluded)})", expanded=False):
        for d in result.excluded:
            st.markdown(
                f'<div class="card out-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
                f'<span style="font-weight:700;color:#f3f4f6">{d.course_id} — {d.course_name}</span>'
                f'<span class="badge-out">OUT</span></div>'
                f'<p style="color:#9ca3af;margin:0">{d.reason}</p>'
                f'</div>',
                unsafe_allow_html=True,
            )

# ── Raw JSON for developers ───────────────────────────────────────────────────
with st.expander("Raw JSON output (developer view)", expanded=False):
    st.json(result.model_dump())
