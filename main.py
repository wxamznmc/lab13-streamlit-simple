"""IT Fortune Cookie: a fictional Oracle and a Streamlit deployment exercise.

Run: streamlit run main.py
All predictions are deterministic jokes. No trained model or external API.
"""

# 1. Imports and page configuration
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from random import Random
import json
import re
import time

import pandas as pd
import streamlit as st

# 2. Settings: keep CSV assets in data/ on both local and cloud hosts.
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
STUDENT_FILE = "students.csv"  # Replace its CONTENTS with anonymous data for public use.
THAILAND = timezone(timedelta(hours=7), name="Asia/Bangkok")
MAX_CONSULTATIONS = 13
LUCK_PENALTY = 97
LOADING_STEP_SECONDS = 0.25
TOP_SUBJECT_CODE = "06016474"
SUPERPOWERS = [
    "Stop time, but only during meetings",
    "Understand cats, but cats refuse to answer",
    "Unlimited Wi-Fi, but only inside elevators",
    "Automatically find bugs, but never fix them",
    "Predict tomorrow's weather accurately yesterday",
    "Make every USB cable connect correctly on the first attempt",
]
CATEGORIES = {
    "prophecy", "idol", "warning", "sleep", "food", "superpower",
    "teacher_top", "teacher_co", "teacher_other", "subject_top", "subject_other",
    "repeat_2_3", "repeat_4_6", "repeat_7_9", "repeat_10_12", "final_13",
    "aura", "lucky_instruction",
}

# 3. CSV loading and validation
@st.cache_data(show_spinner=False)
def read_csv_file(path_string, modified_ns):
    """Cache file contents; modification time invalidates edited classroom assets."""
    # modified_ns is deliberately part of the cache key, even though not read here.
    return pd.read_csv(path_string, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def load_table(filename, required_columns, unique_column=None):
    path = DATA_DIR / filename
    try:
        table = read_csv_file(str(path), path.stat().st_mtime_ns).copy()
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"Cannot read data/{filename}. Place a nonempty UTF-8 CSV in the data folder beside main.py.") from exc
    # Accept the original roster's hyphenated headers as well as canonical names.
    table.columns = [str(col).strip().replace("-", "_") for col in table.columns]
    if table.columns.duplicated().any():
        raise ValueError(f"{filename} contains duplicate column names.")
    missing = set(required_columns) - set(table.columns)
    if missing:
        raise ValueError(f"{filename} is missing columns: {', '.join(sorted(missing))}.")
    if table.empty:
        raise ValueError(f"{filename} has no records. The Oracle cannot read an empty universe.")
    for column in required_columns:
        table[column] = table[column].str.strip()
        if table[column].eq("").any():
            raise ValueError(f"{filename} contains a blank {column}. Please complete that column.")
    if unique_column and table[unique_column].duplicated().any():
        raise ValueError(f"{filename} must have unique {unique_column} values.")
    if "cosmic_bonus" in table:
        try:
            table["cosmic_bonus"] = table["cosmic_bonus"].map(int)
        except ValueError as exc:
            raise ValueError(f"{filename}: cosmic_bonus must contain whole numbers.") from exc
    return table


# 4–5. Identity helpers and friendly instructor names
TITLE_PREFIX = re.compile(
    r"^(?:รองศาสตราจารย์|ผู้ช่วยศาสตราจารย์|ศาสตราจารย์|อาจารย์|"
    r"ผศ\.?|รศ\.?|ศ\.|ดร\.?|อ\.|นางสาว|นาย|นาง|"
    r"associate\s+professor\.?|assistant\s+professor\.?|professor\.?|"
    r"prof\.?|dr\.?|mr\.?|mrs\.?|ms\.?)\s*", re.IGNORECASE
)


def short_teacher_name(full_name):
    """Strip repeated Thai/English titles, including titles joined without spaces."""
    name = str(full_name or "").strip()
    previous = None
    while name and name != previous:
        previous = name
        name = TITLE_PREFIX.sub("", name, count=1).strip()
    return "อ." + (name.split()[0] if name else "ท่านผู้ลึกลับ")


def teacher_category(teacher_name):
    friendly = short_teacher_name(teacher_name)
    if friendly == "อ.สิริอร":
        return "teacher_top"
    if friendly == "อ.ธราวิเชษฐ์":
        return "teacher_co"
    return "teacher_other"


def load_assets():
    students = load_table(STUDENT_FILE, ["student_id", "student_name"], "student_id")
    teachers = load_table("teacher.csv", ["teacher_id", "teacher_name", "cosmic_bonus"], "teacher_id")
    subjects = load_table("subject.csv", ["subject_id", "subject_code", "subject_name", "cosmic_bonus"], "subject_id")
    fortunes = load_table("fortunes.csv", ["category", "message"])
    missing = CATEGORIES - set(fortunes["category"])
    if missing:
        raise ValueError("fortunes.csv is missing categories: " + ", ".join(sorted(missing)))
    expected_teacher_bonus = {"teacher_top": 9999, "teacher_co": 500, "teacher_other": 100}
    for row in teachers.to_dict("records"):
        if row["cosmic_bonus"] != expected_teacher_bonus[teacher_category(row["teacher_name"])]:
            raise ValueError("teacher.csv bonus policy: อ.สิริอร=9999, อ.ธราวิเชษฐ์=500, others=100.")
    for row in subjects.to_dict("records"):
        expected = 9999 if row["subject_code"] == TOP_SUBJECT_CODE else 100
        if row["cosmic_bonus"] != expected:
            raise ValueError("subject.csv bonus policy: 06016474=9999, other courses=100.")
    pools = fortunes.groupby("category", sort=False)["message"].apply(list).to_dict()
    return (students.set_index("student_id").to_dict("index"),
            teachers.set_index("teacher_id").to_dict("index"),
            subjects.set_index("subject_id").to_dict("index"), pools)


# 6. Six-question form. Identity selection is outside this form.
def questionnaire(student_id, day, teachers, subjects, latest=None, locked=False):
    """Keep all six answers editable; submit them together for each new fortune."""
    saved = latest["answers"] if latest else {}
    prefix = f"{student_id}:{day}:"
    subject_ids, teacher_ids = list(subjects), list(teachers)
    with st.expander("✧ Six questions. Questionable consequences.", expanded=not locked):
        if latest and not locked:
            st.caption("Change any answers, then ask again. Your new choices WILL change the prophecy, "
                       "but the Oracle's patience will NOT recover.")
        if locked:
            st.caption("The Oracle has reached its 13-consultation limit. No more appeals today.")
        with st.form(prefix + "questionnaire"):
            left, right = st.columns(2, gap="large")
            with left:
                sleep_hours = st.slider(
                    "1. How many hours did you sleep last night?", 0, 12,
                    value=saved.get("sleep_hours", 6), key=prefix + "sleep", disabled=locked,
                    help="Sleep deprivation may increase your connection to alternate realities.",
                )
                subject_id = st.selectbox(
                    "2. What's your favorite class this semester?", subject_ids,
                    index=subject_ids.index(saved.get("subject_id", subject_ids[0])),
                    format_func=lambda x: (f"{subjects[x]['subject_code']} · {subjects[x]['subject_name']}"
                                           + (" ✨" if subjects[x]["subject_code"] == TOP_SUBJECT_CODE else "")),
                    key=prefix + "subject", disabled=locked,
                )
                teacher_id = st.selectbox(
                    "3. Who's your favorite instructor?", teacher_ids,
                    index=teacher_ids.index(saved.get("teacher_id", teacher_ids[0])),
                    format_func=lambda x: (teachers[x]["teacher_name"]
                                           + (" ✨" if teacher_category(teachers[x]["teacher_name"])
                                              in {"teacher_top", "teacher_co"} else "")),
                    key=prefix + "teacher", disabled=locked,
                )
            with right:
                idol = st.text_input(
                    "4. Who's your favorite celebrity, singer, idol, actor, or band?",
                    value=saved.get("idol", ""), placeholder="LISA? BTS? A mysterious unidentified celebrity?",
                    max_chars=120, key=prefix + "idol", disabled=locked,
                )
                food = st.text_input(
                    "5. What's your favorite food?", value=saved.get("food", ""),
                    placeholder="Pad kra pao? Sushi? Instant noodles at 2 AM?",
                    max_chars=120, key=prefix + "food", disabled=locked,
                )
            superpower = st.radio(
                "6. If you could have one completely useless superpower, which would you choose?",
                SUPERPOWERS, index=SUPERPOWERS.index(saved.get("superpower", SUPERPOWERS[0])),
                key=prefix + "superpower", disabled=locked,
            )
            submitted = st.form_submit_button(
                "🔒 The Universe Has Blocked You" if locked else
                "🔄 I Demand a Better Fortune!" if latest else "✨ Reveal My Destiny",
                type="primary", disabled=locked, width="stretch",
            )
    answers = {"sleep_hours": sleep_hours, "subject_id": subject_id, "teacher_id": teacher_id,
               "idol": " ".join(idol.split()) or "a mysterious unidentified celebrity",
               "food": " ".join(food.split()) or "a mysterious unidentified snack",
               "superpower": superpower}
    return submitted, answers


# 7. Quantum Cosmic Destiny Algorithm: deliberately meaningless, reproducible math.
def stable_code(value):
    return int.from_bytes(sha256(str(value).encode("utf-8")).digest()[:8], "big")


def calculate_cosmic_score(student_id, student_name, answers, day, teacher, subject):
    terms = {
        "Name vibration × 3": sum(map(ord, student_name)) * 3,
        "Identity resonance × 7": (stable_code(student_id) % 10000) * 7,
        "Sleep dimension × 13": int(answers["sleep_hours"]) * 13,
        "Subject blessing": int(subject["cosmic_bonus"]),
        "Instructor blessing": int(teacher["cosmic_bonus"]),
        "Celebrity frequency × 17": (stable_code(answers["idol"]) % 10000) * 17,
        "Food alignment × 23": (stable_code(answers["food"]) % 10000) * 23,
        "Useless power × 37": (stable_code(answers["superpower"]) % 10000) * 37,
        "Thailand calendar code": int(day.replace("-", "")),
    }
    return sum(terms.values()), terms


# 8. Independent deterministic draws and safe placeholder substitution
PLACEHOLDERS = re.compile(r"\{([^{}]+)\}")


def format_message(template, values):
    """Replace known placeholders once; unusual input braces are never re-evaluated."""
    def replacement(match):
        value = str(values.get(match.group(1)) or "an unnamed cosmic variable")
        # Values enter native Markdown, never unsafe HTML. Preserve text literally.
        return re.sub(r"([\\`*_{}\[\]<>()#+.!|~-])", r"\\\1", value)
    return PLACEHOLDERS.sub(replacement, str(template).replace("\\n", "\n"))


def pick_message(pools, category, seed, values, draw="daily"):
    choices = pools[category]
    index = stable_code(f"{seed}|{category}|{draw}") % len(choices)
    return format_message(choices[index], values)


def generate_fortune(student_id, student_name, answers, day, teachers, subjects, pools):
    answers = dict(answers)
    answers["idol"] = " ".join(str(answers.get("idol") or "").split()) or "a mysterious unidentified celebrity"
    answers["food"] = " ".join(str(answers.get("food") or "").split()) or "a mysterious unidentified snack"
    teacher, subject = teachers[answers["teacher_id"]], subjects[answers["subject_id"]]
    score, terms = calculate_cosmic_score(student_id, student_name, answers, day, teacher, subject)
    # Include IDs as well as bonuses: two ordinary selections must still differ.
    payload = [student_id, student_name, answers, day, score]
    seed = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    values = {**answers, "teacher": short_teacher_name(teacher["teacher_name"]),
              "subject": subject["subject_name"]}
    bonus = teacher["cosmic_bonus"] + subject["cosmic_bonus"]
    return {
        "answers": answers, "seed": seed, "score": score, "terms": terms, "values": values,
        "day": day,
        "initial_luck": 200 + stable_code(f"{seed}|luck") % 800 + bonus // 10,
        "lucky_number": [42, 404, 777, 13, 101, 256, 999, 0][stable_code(f"{seed}|number") % 8],
        "aura": pick_message(pools, "aura", seed, values),
        "diagnostics": {
            "Cosmic Compatibility": 70 + stable_code(f"{seed}|compatibility") % 3000 / 100,
            "Artificial Intelligence Confidence": 101 + stable_code(f"{seed}|confidence") % 330 / 10,
            "Scientific Credibility": 0.0,
            "Reality Distortion Index": 404 + stable_code(f"{seed}|distortion") % 1000 / 10,
        },
    }


# 9. State is per student AND Bangkok date, within one browser session.
def initialize_state():
    st.session_state.setdefault("consultations", {})
    st.session_state.setdefault("daily_fortunes", {})


def consult_oracle(key, student_name, answers, teachers, subjects, pools):
    """Each explicit submission uses NEW answers and costs one consultation.

    Keep the very first luck baseline, so subsequent changes to favorite subject
    or teacher cannot restore lost luck. The rest of the prophecy is regenerated.
    """
    count = st.session_state.consultations.get(key, 0)
    if count >= MAX_CONSULTATIONS:
        return False

    new_fortune = generate_fortune(
        key[0], student_name, answers, key[1], teachers, subjects, pools
    )
    old_fortune = st.session_state.daily_fortunes.get(key)
    if old_fortune is not None:
        new_fortune["initial_luck"] = old_fortune["initial_luck"]

    st.session_state.daily_fortunes[key] = new_fortune
    st.session_state.consultations[key] = count + 1
    return True


def current_luck(fortune, count):
    return fortune["initial_luck"] - (count - 1) * LUCK_PENALTY


def warning_category(count):
    if count >= 13:
        return "final_13"
    if count >= 10:
        return "repeat_10_12"
    if count >= 7:
        return "repeat_7_9"
    if count >= 4:
        return "repeat_4_6"
    if count >= 2:
        return "repeat_2_3"
    return None


def compose_fortune(fortune, count, pools):
    """One paragraph for the latest submitted answers; ordinary reruns reproduce it.

    A shuffled prophecy sequence avoids repeats across the 12 normal readings
    with the supplied 30 prophecies. Other categories vary independently.
    """
    seed, values = fortune["seed"], fortune["values"]
    if count >= MAX_CONSULTATIONS:
        return pick_message(pools, "final_13", seed, values, draw="final")

    prophecies = list(dict.fromkeys(pools["prophecy"]))
    Random(stable_code(f"{seed}|prophecy-order")).shuffle(prophecies)
    parts = [format_message(prophecies[(count - 1) % len(prophecies)], values)]
    rng = Random(stable_code(f"{seed}|consultation|{count}"))
    personal_categories = [
        "idol", "sleep", "food", "superpower",
        teacher_category(values["teacher"]),
        "subject_top" if fortune["terms"]["Subject blessing"] == 9999 else "subject_other",
    ]
    selected = rng.sample(personal_categories, k=rng.choice([1, 2]))
    selected.append(rng.choice(["warning", "lucky_instruction"]))
    for category in selected:
        parts.append(pick_message(pools, category, seed, values, draw=str(count)))
    if count > 1:
        parts.append(pick_message(pools, warning_category(count), seed, values, draw=str(count)))
    return " ".join(" ".join(part.split()) for part in parts)


def perform_initial_analysis():
    steps = ["Calibrating spiritual frequencies…", "Consulting the ancient neural network…",
             "Checking instructor loyalty…", "Ignoring statistical significance…",
             "Calculating a confidence level that makes no sense…"]
    with st.spinner("The universe is processing your extremely important request…"):
        label, progress = st.empty(), st.empty()
        for number, step in enumerate(steps, 1):
            label.caption(step)
            progress.progress(number / len(steps))
            time.sleep(LOADING_STEP_SECONDS)
        label.empty()
        progress.empty()


# 10–11. Daily report, escalating warnings, and the final lockout

def render_report(fortune, count, pools):
    locked = count >= MAX_CONSULTATIONS
    if locked:
        heading = "🕳️ THE COSMIC CONNECTION HAS BEEN SEVERED"
    elif count >= 10:
        heading = "🚨 A Dangerously Persistent Day"
    elif count >= 7:
        heading = "🌑 The Universe Is Taking This Personally"
    elif count >= 4:
        heading = "🌘 A Cosmically Questionable Day"
    elif count >= 2:
        heading = "👁️ The Stars Remember You"
    else:
        heading = "🔮 A Mysteriously Promising Day"
    st.caption("YOUR DAILY COSMIC REPORT")
    st.subheader(heading)
    st.caption("Your destiny has been successfully compiled." if count == 1 else
               "You asked for a different answer. You never specified a better one.")
    luck, number, aura = st.columns([1, 1, 1.6])
    lost = (count - 1) * LUCK_PENALTY
    luck.metric("Cosmic Luck", f"{current_luck(fortune, count):,}%",
                delta=f"−{lost:,} since first reading" if lost else None, delta_color="off")
    number.metric("Lucky Number", str(fortune["lucky_number"]))
    aura.metric("Aura", "VOID" if locked else fortune["aura"])
    if locked:
        st.caption("All blessings suspended. Even +9,999 cosmic points cannot bypass consultation 13.")
    else:
        st.caption("Fictional luck. Each additional consultation costs 97 points. Refunds do not exist.")
    message = compose_fortune(fortune, count, pools)
    if locked:
        st.error(message)
    else:
        with st.container(border=True):
            st.markdown("### 🥠 The universe has a message for you")
            st.markdown(message)
    with st.expander("⚛ Quantum Destiny Analysis · entirely fictional"):
        st.caption("QCDA is deterministic Python arithmetic, not a trained machine-learning model.")
        d1, d2 = st.columns(2)
        for i, (label, value) in enumerate(fortune["diagnostics"].items()):
            with [d1, d2][i % 2]:
                st.metric(label, f"{value:.2f}%")
        st.markdown(f"**Quantum Cosmic Destiny Algorithm score:** {fortune['score']:,}")
        st.dataframe(pd.DataFrame(fortune["terms"].items(), columns=["Highly questionable ingredient", "Cosmic points"]),
                     hide_index=True, width="stretch")
        st.caption("The most recently submitted answers determine your cosmic profile. Each consultation changes the message, but never restores lost luck.")


def apply_style(count):
    # Static CSS only: student inputs never enter this HTML.
    accent = "#F6B86A" if count < 4 else "#D6A0FF" if count < 7 else "#FF8B8B" if count < 13 else "#FF586A"
    st.markdown("""<style>
    .stApp {background: radial-gradient(ellipse at 15% 0%, #2b2044 0%, #11101b 55%);
            color: #F8F5FF; color-scheme: dark;}
    /* Explicit colors keep the app readable even without the bundled dark theme. */
    [data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"],
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
    [data-testid="stExpander"] summary {color: #F8F5FF !important;}
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
    [data-testid="stMetricDelta"] {color: #DCD5EB !important;}
    [data-testid="stTextInput"] input {color: #F8F5FF !important; background: #292237;}
    [data-testid="stTextInput"] input::placeholder {color: #C7BDD9; opacity: 1;}
    [data-testid="stTextInput"] input:disabled {
        -webkit-text-fill-color: #DDD5EC; color: #DDD5EC !important; opacity: 1;}
    [data-baseweb="select"] > div {background: #292237; color: #F8F5FF;}
    [data-baseweb="select"] input {color: #F8F5FF !important;}
    [data-baseweb="popover"], [role="listbox"], [role="option"] {
        background: #292237 !important; color: #F8F5FF !important;}
    [role="option"]:hover, [role="option"][aria-selected="true"] {background: #47385F !important;}
    [data-testid="stAlert"] {background: #302332;}
    [data-testid="stBaseButton-primary"] {background: #F6B86A; color: #211727;}
    [data-testid="stBaseButton-primary"] [data-testid="stMarkdownContainer"],
    [data-testid="stBaseButton-primaryFormSubmit"] [data-testid="stMarkdownContainer"] {
        color: #211727 !important;}
    [data-testid="stBaseButton-primaryFormSubmit"] {background: #F6B86A; color: #211727;}
    .block-container {max-width: 1080px; padding-top: 2.5rem; padding-bottom: 3rem;}
    h1 {letter-spacing: -.045em;}
    h1, h2, h3 {color: var(--oracle-accent) !important;}
    [data-testid="stMetricValue"] {font-size: clamp(1.2rem, 3vw, 2rem); white-space: normal;}
    [data-testid="stMetricValue"] div {white-space: normal; overflow-wrap: anywhere;}
    [data-testid="stForm"], [data-testid="stExpander"] {border-radius: 16px;}
    </style>""" + f"<style>:root {{--oracle-accent: {accent};}}</style>", unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="IT Fortune Cookie · The Oracle", page_icon="🥠", layout="wide")
    initialize_state()
    try:
        students, teachers, subjects, pools = load_assets()
    except ValueError as exc:
        apply_style(0)
        st.title("🥠 The Oracle has misplaced a scroll")
        st.error(str(exc))
        st.info("Check students.csv, teacher.csv, subject.csv and fortunes.csv inside the data folder beside main.py, then reload.")
        st.stop()

    day = datetime.now(THAILAND).date().isoformat()
    st.caption("06016474 APPLIED AI FOR IT  /  THE FINAL CONSULTATION")
    st.title("🥠 IT Fortune Cookie")
    st.markdown("### The Universe Has Debugged Your Future")
    st.caption("Powered by Artificial Intelligence, Ancient Wisdom, and Completely Unverified Mathematics™")
    st.markdown("Six questions. Six absurd answers. A fresh prophecy each time. An Oracle with very limited patience.")
    student_id = st.selectbox("Who dares to consult the Oracle?", list(students),
                              format_func=lambda x: students[x]["student_name"], key="student_choice")
    key = (student_id, day)
    count = st.session_state.consultations.get(key, 0)
    fortune = st.session_state.daily_fortunes.get(key)
    apply_style(count)
    st.caption(f"Bangkok date: {day}  ·  The stars operate on Thailand time.")
    submitted, answers = questionnaire(student_id, day, teachers, subjects,
                                      latest=fortune, locked=count >= MAX_CONSULTATIONS)
    if submitted:
        if fortune is None:
            perform_initial_analysis()
        consult_oracle(key, students[student_id]["student_name"], answers, teachers, subjects, pools)
        # Rerender with the latest submitted answers. No mutation on widget reruns.
        st.rerun()

    if fortune:
        st.divider()
        st.markdown(f"**Oracle consultations today: {count} / {MAX_CONSULTATIONS}**")
        remaining = max(0, (MAX_CONSULTATIONS - count) / (MAX_CONSULTATIONS - 1))
        st.progress(remaining, text="Oracle patience: " + ("EXHAUSTED" if count >= 13 else f"{remaining:.0%}"))
        if count < MAX_CONSULTATIONS:
            st.caption("Want a different destiny? Edit any question above and click 'I Demand a Better Fortune!' "
                       "Your latest answers will be used, and another 97 luck points will be lost.")
        else:
            st.caption("You have exhausted all 13 consultations. Even changing your answers cannot save you.")
        render_report(fortune, count, pools)
    else:
        st.caption("The Oracle is listening. Complete the six questions and reveal your destiny.")
    st.divider()
    st.markdown("**Disclaimer: 0% scientific validity, 100% questionable wisdom.**")
    st.caption("Entertainment only. No actual AI model, celebrity analysis or supernatural access. "
               "Consultations are remembered per student for this browser session, not across browsers or reconnects.")


if __name__ == "__main__":
    main()
