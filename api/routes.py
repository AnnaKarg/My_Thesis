from fastapi import APIRouter, Depends, HTTPException
import asyncio
import json
import random
import re
import time
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from database.session import AsyncSessionLocal
from database.models import User, ChatHistory
from pydantic import BaseModel
from passlib.context import CryptContext
from langchain_core.messages import HumanMessage, AIMessage
from core.app import app as langgraph_app
from agents.mentor import (
    generate_random_task,
    classify_profile_async,
    generate_session_recap_async,
    classify_pending_advance_intent_async,
    _wants_to_start_task,
)
from agents.assessor import UNDERSTANDING_LEVEL_TO_MASTERY_PCT

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

LESSONS_PATH = Path(__file__).resolve().parents[1] / "content" / "lessons.json"
with open(LESSONS_PATH, "r", encoding="utf-8") as f:
    lessons_content = json.load(f)

TOTAL_LESSONS = len(lessons_content.get("lessons", []))

_LESSON_TITLES_DISPLAY = [l.get("title", f"Μάθημα {l.get('id',i+1)}")
                           for i, l in enumerate(lessons_content.get("lessons", []))]
_LESSON_TITLES_AGENT = [
    l.get("agent_title", l.get("title", f"Lesson {l.get('id', i+1)}"))
    for i, l in enumerate(lessons_content.get("lessons", []))
]

class UserAuth(BaseModel):
    username: str
    password: str

class ChatRequest(BaseModel):
    message: str
    code: str = ""
    time_spent: float = 0.0
    is_task_attempt: bool = False
    task_started: bool = False
    event_type: str = ""
    session_id: int = 0

_HISTORY_TOKENS_RE = re.compile(
    r'\n?\[(?:HINT|AWAITING_QUESTIONS|BUTTON:START_TASK|BUTTON:CONTINUE_TASK|'
    r'ASSESSMENT:ADVANCE|ASSESSMENT:REPEAT|ASSESSMENT:SUPPORT|DEBUG:[^\]]*|'
    r'ASCII_SHOWN:\d+|THEORY_DIFFICULTY:\w+:\d+)\]'
)

def _sanitize_history(text: str) -> str:
    return _HISTORY_TOKENS_RE.sub('', text or '').strip()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _format_submission_message(code: str) -> str:
    cleaned_code = code.strip()
    if not cleaned_code:
        return "Υποβολή κώδικα"

    return f"Υποβολή κώδικα:\n```python\n{cleaned_code}\n```"

def _build_welcome_message(username: str, db_history, current_lesson_id: int) -> str:
    if not db_history:
        return (
            f"Γεια σου {username}! Είμαι ο Mentor σου και είμαι εδώ για να σε βοηθήσω να μάθεις Python. "
            "Πριν ξεκινήσουμε, πες μου: έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
        )

    idx = max(0, min(current_lesson_id - 1, len(_LESSON_TITLES_DISPLAY) - 1))
    lesson_name = _LESSON_TITLES_DISPLAY[idx]

    return (
        f"Καλώς ήρθες ξανά {username}! Την προηγούμενη φορά δουλέψαμε πάνω στο μάθημα '{lesson_name}'. "
        "Θέλεις να συνεχίσουμε απευθείας ή να ξαναδούμε πρώτα τη θεωρία;"
    )

def _infer_awaiting_questions(db_history, profile_checked: bool, task_started: bool) -> bool:
    if not profile_checked or task_started:
        return False

    for h in reversed(db_history):
        if h.role != "ai":
            continue
        text = (h.content or "").lower()
        if "[button:start_task]" in text:
            return False
        if "[awaiting_questions]" in text:
            return True
        return False

    return False

def _count_hints(db_history) -> int:
    """Μετράει hints μόνο για την τρέχουσα άσκηση (μετά το τελευταίο [BUTTON:START_TASK] ή [ASSESSMENT:ADVANCE])."""
    count = 0
    for h in reversed(db_history):
        if h.role == "ai":
            content = h.content or ""
            if "[BUTTON:START_TASK]" in content or "[BUTTON:CONTINUE_TASK]" in content or "[ASSESSMENT:ADVANCE]" in content:
                break
            if "[HINT]" in content:
                count += 1
    return count

def _count_attempts_since_last_task(db_history) -> int:
    """Μετράει attempts μόνο για την τρέχουσα άσκηση (από το τελευταίο [BUTTON:START_TASK] ή [ASSESSMENT:ADVANCE])."""
    count = 0
    for h in reversed(db_history):
        if h.role == "ai":
            content = h.content or ""
            if "[BUTTON:START_TASK]" in content or "[BUTTON:CONTINUE_TASK]" in content or "[ASSESSMENT:ADVANCE]" in content:
                break
        elif h.role == "human" and (h.attempts_count or 0) > 0:
            count += h.attempts_count
    return count

def _has_recent_attempts(db_history) -> bool:
    """True μόνο αν υπάρχουν υποβολές κώδικα μετά την τελευταία μετάβαση μαθήματος (ADVANCE)."""
    for h in reversed(db_history):
        if h.role == "ai" and "[ASSESSMENT:ADVANCE]" in (h.content or ""):
            return False
        if h.role == "human" and (h.attempts_count or 0) > 0:
            return True
    return False

def _has_pending_advance_in_history(db_history) -> bool:
    """True αν το τελευταίο AI μήνυμα περιέχει [ASSESSMENT:ADVANCE]."""
    for h in reversed(db_history):
        if h.role != "ai":
            continue
        content = (h.content or "")
        return "[ASSESSMENT:ADVANCE]" in content
    return False

def _should_reset_for_next_lesson(db_history, user_message: str) -> bool:
    """Keyword fallback για παλιές συνεδρίες χωρίς pending_advance flag."""
    normalized = (user_message or "").strip().lower()
    if any(neg in normalized for neg in ["δεν ", "δε ", "μην ", "όχι", "οχι"]):
        return False
    affirmative = any(word in normalized for word in [
        "ναι", "ναι.", "ναι!", "nai", "ne", "yes", "yep", "ok", "okay",
        "προχωράμε", "προχωραμε", "προχωράμε.", "προχωραμε.",
        "πάμε", "παμε", "next", "επόμενο", "επομενο",
        "εντάξει", "εντάξει!", "εντάξει.", "εντάξει,", "εντάξει;",
        "τέλεια", "τελεια", "συνεχίζουμε", "συνεχιζουμε", "ας πάμε", "ας παμε",
        "ειμαι ετοιμ", "είμαι έτοιμ",
    ])
    if not affirmative:
        return False

    return _has_pending_advance_in_history(db_history)

def _extract_debug_categories(debug_report: str):
    categories = []
    marker = "[DEBUG:CATEGORIES]"
    if marker in (debug_report or ""):
        lines = debug_report.split(marker, 1)[1].splitlines()
        tail = lines[0] if lines else ""
        categories = [c.strip() for c in tail.split(",") if c.strip()]
    return categories

def _update_error_profile(raw_profile: str, categories):
    try:
        current = Counter(json.loads(raw_profile or "[]"))
    except Exception:
        current = Counter()

    for category in categories:
        current[category] += 1

    ranked = [name for name, _ in current.most_common(10)]
    return json.dumps(ranked, ensure_ascii=False)

def _build_performance_summary(db_history, user: User):
    human_attempts = [h for h in db_history if h.role == "human" and (h.attempts_count or 0) > 0]
    total_attempts = sum(h.attempts_count or 0 for h in human_attempts)
    avg_time_spent = 0.0
    if human_attempts:
        avg_time_spent = sum((h.time_spent or 0.0) for h in human_attempts) / len(human_attempts)

    frequent_error_categories = []
    try:
        frequent_error_categories = json.loads(user.frequent_error_categories or "[]")
    except Exception:
        frequent_error_categories = []

    latest_attempt_contents = [
        h.content for h in db_history
        if h.role == "human" and (h.attempts_count or 0) > 0
    ][-5:]

    return json.dumps(
        {
            "total_attempts": total_attempts,
            "avg_time_spent": round(avg_time_spent, 2),
            "frequent_error_categories": frequent_error_categories,
            "recent_attempts": len(latest_attempt_contents),
        },
        ensure_ascii=False,
    )

_ERROR_LABEL_SIMPLE = {
    "missing_output": "απουσία εκτύπωσης αποτελέσματος",
    "wrong_operator": "λάθος τελεστής",
    "type_error": "σφάλμα τύπου δεδομένων (π.χ. string αντί για αριθμό)",
    "undefined_variable": "χρήση μεταβλητής που δεν έχει οριστεί",
    "syntax_error": "συντακτικό σφάλμα",
    "wrong_list_type": "λάθος τύπος στοιχείων λίστας",
    "empty_print": "print() χωρίς ορίσματα",
    "missing_return": "απουσία return σε συνάρτηση",
    "wrong_function_name": "λάθος όνομα συνάρτησης",
    "wrong_variable_name": "λάθος όνομα μεταβλητής",
    "missing_loop": "απουσία επανάληψης",
    "off_by_one": "σφάλμα εύρους (off-by-one)",
}

def _build_course_stats_message(user, total_lessons: int, db_history=None) -> str:
    solved = int(user.solved_tasks or 0)
    avg_time = round(float(user.avg_time_spent or 0.0), 1)
    level_map = {"beginner": "Αρχάριο", "intermediate": "Ενδιάμεσο", "expert": "Προχωρημένο"}
    level_display = level_map.get(user.experience_level or "beginner", "Αρχάριο")

    try:
        raw_errors = json.loads(user.frequent_error_categories or "[]")[:3]
    except Exception:
        raw_errors = []

    if raw_errors:
        error_lines = "\n".join(
            f"  - {_ERROR_LABEL_SIMPLE.get(e, e)}" for e in raw_errors
        )
        error_section = f"- **Συχνότερα λάθη που συναντήθηκαν:**\n{error_lines}"
    else:
        error_section = "- **Λάθη:** Καμία επαναλαμβανόμενη δυσκολία εντοπίστηκε"

    practice_section = ""
    if db_history is not None:
        struggle_flags = _compute_lesson_struggle_flags(db_history)
        struggled_titles = [
            _LESSON_TITLES_DISPLAY[lid - 1]
            for lid, flagged in struggle_flags.items()
            if flagged and 1 <= lid <= len(_LESSON_TITLES_DISPLAY)
        ]
        if struggled_titles:
            practice_section = (
                f"\n\n**Πρόταση:** Δυσκολεύτηκες λίγο περισσότερο σε: {', '.join(struggled_titles)}. "
                f"Αξίζει λίγη επιπλέον εξάσκηση εκεί μέσω του κουμπιού «Εξάσκηση» στην αρχική σελίδα."
            )

    return (
        f"**Συγχαρητήρια, {user.username}! Ολοκλήρωσες όλο το πρόγραμμα μαθημάτων Python!**\n\n"
        f"**Τα στατιστικά σου:**\n"
        f"- **Μαθήματα:** {total_lessons}/{total_lessons} ολοκληρωμένα\n"
        f"- **Ασκήσεις που λύθηκαν:** {solved}\n"
        f"- **Μέσος χρόνος ανά άσκηση:** {avg_time:.0f} δευτερόλεπτα\n"
        f"- **Τελικό επίπεδο:** {level_display}\n"
        f"{error_section}"
        f"{practice_section}\n\n"
        f"Εξαιρετική δουλειά! Συνέχισε να εξασκείσαι — η Python σε περιμένει!"
    )

async def get_db():
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()

_STRUGGLE_ATTEMPTS_THRESHOLD = 3
_STRUGGLE_HINTS_THRESHOLD = 2
_PRACTICE_STRUGGLE_CLEAR_THRESHOLD = 5

def _compute_lesson_struggle_flags(db_history) -> dict:
    """{lesson_id: True/False} ανά ολοκληρωμένο μάθημα, σπάζοντας στα [ASSESSMENT:ADVANCE] boundaries."""
    lesson_id = 1
    attempts = 0
    hints = 0
    flags = {}
    for h in db_history:
        if h.role == "human":
            attempts += (h.attempts_count or 0)
        elif h.role == "ai":
            content = h.content or ""
            if "[HINT]" in content:
                hints += 1
            if "[ASSESSMENT:ADVANCE]" in content:
                flags[lesson_id] = (
                    attempts >= _STRUGGLE_ATTEMPTS_THRESHOLD or hints >= _STRUGGLE_HINTS_THRESHOLD
                )
                lesson_id += 1
                attempts = 0
                hints = 0
    return flags

async def _compute_cohort_completion_pct(db: AsyncSession, total_lessons: int) -> dict:
    """Ποσοστό χρηστών που έχουν φτάσει ή προσπεράσει κάθε μάθημα."""
    result = await db.execute(select(User.current_lesson_id))
    all_lesson_ids = [row[0] for row in result.all()]
    total_users = len(all_lesson_ids)
    if total_users == 0:
        return {}
    return {
        lid: round(sum(1 for clid in all_lesson_ids if clid >= lid) / total_users * 100)
        for lid in range(1, total_lessons + 1)
    }

def _compute_mastery_profile(user: User, db_history, struggle_flags: dict = None, cohort_pct: dict = None) -> list:
    """Open Learner Model: mastery % ανά ενότητα, για το frontend."""
    struggle_flags = struggle_flags or {}
    cohort_pct = cohort_pct or {}
    current_mastery = (
        UNDERSTANDING_LEVEL_TO_MASTERY_PCT.get(user.understanding_level or "developing", 50)
        if _has_recent_attempts(db_history) else 0
    )
    try:
        practice_streaks = json.loads(user.practice_lesson_correct_streak or "{}")
    except Exception:
        practice_streaks = {}
    mastery_profile = []
    for lesson_obj in lessons_content.get("lessons", []):
        lid = lesson_obj.get("id", 0)
        if lid < user.current_lesson_id:
            pct = 100
        elif lid == user.current_lesson_id:
            pct = current_mastery
        else:
            pct = 0
        struggled = bool(struggle_flags.get(lid, False))
        if struggled and practice_streaks.get(str(lid), 0) >= _PRACTICE_STRUGGLE_CLEAR_THRESHOLD:
            struggled = False
        mastery_profile.append({
            "id": lid,
            "title": lesson_obj.get("title", ""),
            "mastery": pct,
            "struggled": struggled,
            "cohort_pct": cohort_pct.get(lid),
        })
    return mastery_profile

@router.post("/register")
async def register(user_data: UserAuth, db: AsyncSession = Depends(get_db)):
    query = await db.execute(select(User).filter(User.username == user_data.username))
    if query.scalars().first():
        raise HTTPException(status_code=400, detail="Το όνομα χρήστη υπάρχει ήδη")

    hashed_pwd = pwd_context.hash(user_data.password)
    new_user = User(username=user_data.username, hashed_password=hashed_pwd)
    db.add(new_user)
    await db.commit()
    return {"message": "Η εγγραφή ολοκληρώθηκε!"}

@router.post("/login")
async def login(user_data: UserAuth, db: AsyncSession = Depends(get_db)):
    query = await db.execute(select(User).filter(User.username == user_data.username))
    user = query.scalars().first()

    if not user or not pwd_context.verify(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Λάθος όνομα χρήστη ή κωδικός")

    return {"username": user.username, "id": user.id}

@router.get("/session/{user_id}/progress")
async def session_progress(user_id: int, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    history_query = await db.execute(
        select(ChatHistory).filter(ChatHistory.user_id == user_id).order_by(ChatHistory.id.asc())
    )
    db_history = history_query.scalars().all()

    struggle_flags = _compute_lesson_struggle_flags(db_history)
    cohort_pct = await _compute_cohort_completion_pct(db, TOTAL_LESSONS)

    return {
        "experience_level": user.experience_level or "beginner",
        "mastery_profile": _compute_mastery_profile(user, db_history, struggle_flags, cohort_pct),
        "practice_streak_current": int(user.practice_streak_current or 0),
        "practice_streak_goal": int(user.practice_streak_goal or 0),
    }

@router.post("/session/{user_id}/abandon_task")
async def abandon_active_task(user_id: int, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    user.active_task_lesson_id = 0
    user.active_task_text = ""
    await db.commit()
    return {"message": "Η άσκηση εγκαταλείφθηκε."}

FREE_CHECK_MAX_CHARS = 2000

class FreeCheckRequest(BaseModel):
    code: str
    description: str = ""

@router.post("/free_check/{user_id}")
async def free_check(user_id: int, request: FreeCheckRequest, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    code = (request.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Δεν στάλθηκε κώδικας για έλεγχο")
    if len(code) > FREE_CHECK_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"Ο κώδικας ξεπερνά το όριο των {FREE_CHECK_MAX_CHARS} χαρακτήρων")

    state = {
        "messages": [HumanMessage(content="CODE_SUBMISSION")],
        "student_code": code,
        "success_criteria": [],
        "current_task": (request.description or "").strip(),
        "free_check_mode": True,
        "free_check_description": (request.description or "").strip(),
    }
    try:
        output = await asyncio.wait_for(
            langgraph_app.ainvoke(state, config={"recursion_limit": 10}),
            timeout=60
        )
        response = output["messages"][-1].content.strip()
    except Exception:
        response = "Κάτι πήγε στραβά κατά τον έλεγχο του κώδικά σου. Δοκίμασε ξανά."

    return {"mentor_response": response or "Κάτι πήγε στραβά κατά τον έλεγχο του κώδικά σου. Δοκίμασε ξανά."}

class PracticeGoalRequest(BaseModel):
    goal: int

@router.post("/practice/{user_id}/set_goal")
async def set_practice_goal(user_id: int, request: PracticeGoalRequest, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")
    user.practice_streak_goal = max(0, int(request.goal or 0))
    await db.commit()
    return {"practice_streak_goal": user.practice_streak_goal}

class PracticeNextTaskRequest(BaseModel):
    lesson_ids: list[int]

@router.post("/practice/{user_id}/next_task")
async def practice_next_task(user_id: int, request: PracticeNextTaskRequest, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    all_lessons = lessons_content.get("lessons", [])
    completed_ids = {l.get("id") for l in all_lessons if l.get("id", 0) < user.current_lesson_id}
    valid_ids = [lid for lid in (request.lesson_ids or []) if lid in completed_ids]
    if not valid_ids:
        raise HTTPException(status_code=400, detail="Δεν έχει επιλεγεί κανένα ολοκληρωμένο κεφάλαιο")

    lesson_id = random.choice(valid_ids)
    lesson_obj = next((l for l in all_lessons if l.get("id") == lesson_id), None)
    if not lesson_obj:
        raise HTTPException(status_code=400, detail="Άγνωστο κεφάλαιο")

    difficulty = "hard" if int(user.practice_streak_current or 0) >= 3 else "easy"
    task_payload = generate_random_task(lesson_obj, difficulty)
    return {
        "task": task_payload.get("task_text", ""),
        "success_criteria": task_payload.get("rendered_criteria", []),
        "lesson_id": lesson_id,
        "lesson_title": lesson_obj.get("title", ""),
        "difficulty": difficulty,
    }

class PracticeSubmitRequest(BaseModel):
    code: str
    task: str
    success_criteria: list = []
    lesson_id: int

@router.post("/practice/{user_id}/submit")
async def practice_submit(user_id: int, request: PracticeSubmitRequest, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    code = (request.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Δεν στάλθηκε κώδικας για έλεγχο")

    state = {
        "messages": [HumanMessage(content="CODE_SUBMISSION")],
        "student_code": code,
        "success_criteria": request.success_criteria or [],
        "current_task": request.task or "",
        "practice_mode": True,
    }
    try:
        output = await asyncio.wait_for(
            langgraph_app.ainvoke(state, config={"recursion_limit": 15}),
            timeout=60
        )
        response = output["messages"][-1].content.strip()
        is_correct = bool(output.get("is_correct", False))
    except Exception:
        response = "Κάτι πήγε στραβά κατά τον έλεγχο. Δοκίμασε ξανά."
        is_correct = False

    try:
        lesson_streaks = json.loads(user.practice_lesson_correct_streak or "{}")
    except Exception:
        lesson_streaks = {}
    lid_key = str(request.lesson_id)

    if is_correct:
        user.practice_streak_current = int(user.practice_streak_current or 0) + 1
        lesson_streaks[lid_key] = int(lesson_streaks.get(lid_key, 0)) + 1
    else:
        user.practice_streak_current = 0
        lesson_streaks[lid_key] = 0
    user.practice_lesson_correct_streak = json.dumps(lesson_streaks, ensure_ascii=False)

    goal = int(user.practice_streak_goal or 0)
    goal_reached = bool(goal > 0 and user.practice_streak_current >= goal)
    await db.commit()

    return {
        "mentor_response": response or "Κάτι πήγε στραβά κατά τον έλεγχο. Δοκίμασε ξανά.",
        "is_correct": is_correct,
        "practice_streak_current": user.practice_streak_current,
        "practice_streak_goal": goal,
        "goal_reached": goal_reached,
    }

@router.get("/session/{user_id}/welcome")
async def session_welcome(user_id: int, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    history_query = await db.execute(
        select(ChatHistory).filter(ChatHistory.user_id == user_id).order_by(ChatHistory.id.asc())
    )
    db_history = history_query.scalars().all()

    # Κάθε /welcome αντιστοιχεί σε νέο login, άρα ξεχωριστό session_id.
    new_session_id = int(time.time())

    if db_history:
        idx = max(0, min(user.current_lesson_id - 1, len(_LESSON_TITLES_DISPLAY) - 1))
        lesson_name = _LESSON_TITLES_DISPLAY[idx]

        history_pairs = [(h.role, h.content) for h in db_history]
        try:
            recap = await asyncio.wait_for(
                generate_session_recap_async(history_pairs, lesson_name, user.username),
                timeout=8,
            )
        except Exception:
            recap = ""

        if recap:
            welcome_message = f"Καλώς ήρθες ξανά, {user.username}!\n\n{recap}\n\nΘέλεις να συνεχίσουμε απευθείας ή να ξαναδούμε πρώτα τη θεωρία της ενότητας **{lesson_name}**;"
        else:
            welcome_message = _build_welcome_message(user.username, db_history, user.current_lesson_id)

    else:
        welcome_message = _build_welcome_message(user.username, db_history, user.current_lesson_id)

    struggle_flags = _compute_lesson_struggle_flags(db_history)
    cohort_pct = await _compute_cohort_completion_pct(db, TOTAL_LESSONS)
    mastery_profile = _compute_mastery_profile(user, db_history, struggle_flags, cohort_pct)

    db.add(ChatHistory(
        user_id=user.id,
        role="ai",
        content=welcome_message,
        session_id=new_session_id,
        created_at=_now_iso(),
    ))
    await db.commit()

    return {
        "message": welcome_message,
        "current_lesson_id": user.current_lesson_id,
        "profile_checked": user.profile_checked,
        "session_id": new_session_id,
        "experience_level": user.experience_level or "beginner",
        "mastery_profile": mastery_profile,
    }

@router.get("/history/{user_id}/sessions")
async def get_history_sessions(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatHistory)
        .filter(ChatHistory.user_id == user_id, ChatHistory.session_id > 0)
        .order_by(ChatHistory.session_id.asc())
    )
    messages = result.scalars().all()

    sessions: dict = {}
    for msg in messages:
        sid = msg.session_id
        if sid not in sessions:
            sessions[sid] = {"session_id": sid, "created_at": msg.created_at, "preview": ""}
        if msg.role == "ai" and not sessions[sid]["preview"]:
            clean = _sanitize_history(msg.content)
            sessions[sid]["preview"] = (clean[:80] + "…") if len(clean) > 80 else clean

    return sorted(sessions.values(), key=lambda s: s["session_id"], reverse=True)

@router.get("/history/{user_id}/sessions/{session_id}")
async def get_session_messages(user_id: int, session_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatHistory)
        .filter(ChatHistory.user_id == user_id, ChatHistory.session_id == session_id)
        .order_by(ChatHistory.id.asc())
    )
    messages = result.scalars().all()
    return {
        "messages": [
            {"role": m.role, "content": _sanitize_history(m.content)}
            for m in messages
        ]
    }

@router.post("/chat/{user_id}")
async def chat(user_id: int, request: ChatRequest, db: AsyncSession = Depends(get_db)):
    user_query = await db.execute(select(User).filter(User.id == user_id))
    user = user_query.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    history_query = await db.execute(
        select(ChatHistory).filter(ChatHistory.user_id == user_id).order_by(ChatHistory.id.asc())
    )
    db_history = history_query.scalars().all()
    submission_message = _format_submission_message(request.code) if request.code.strip() else request.message

    if TOTAL_LESSONS and user.current_lesson_id > TOTAL_LESSONS:
        ai_response = _build_course_stats_message(user, TOTAL_LESSONS, db_history)
        _ts = _now_iso()
        db.add(ChatHistory(user_id=user.id, role="human", content=submission_message, time_spent=0.0, attempts_count=0, session_id=request.session_id, created_at=_ts))
        db.add(ChatHistory(user_id=user.id, role="ai", content=ai_response, session_id=request.session_id, created_at=_ts))
        await db.commit()
        return {
            "mentor_response": ai_response,
            "is_correct": False,
            "course_completed": True
        }

    # profile_checked (όχι len(db_history)==0): το /welcome εισάγει πάντα ένα welcome μήνυμα πριν
    # το πρώτο μήνυμα του μαθητή, οπότε db_history έχει ήδη 1 εγγραφή στο πρώτο chat request.
    is_first_login = not user.profile_checked
    profile_soft_defaulted = False
    if not user.profile_checked:
        profile_result = await classify_profile_async(request.message)
        if profile_result == "ambiguous":
            user.experience_level = "beginner"
            user.profile_checked = True
            profile_soft_defaulted = True
        elif profile_result != "unclear":
            user.experience_level = profile_result
            user.profile_checked = True

    has_current_submission = bool(request.code.strip()) or "CODE_SUBMISSION" in request.message.upper()
    is_task_attempt_effective = request.is_task_attempt or has_current_submission

    current_total_attempts = _count_attempts_since_last_task(db_history) + (1 if is_task_attempt_effective else 0)

    formatted_history = []
    for h in db_history:
        msg_class = HumanMessage if h.role == "human" else AIMessage
        formatted_history.append(msg_class(content=h.content))
    formatted_history.append(HumanMessage(content=submission_message))

    task_started = request.task_started or _has_recent_attempts(db_history) or is_task_attempt_effective
    awaiting_questions = _infer_awaiting_questions(db_history, user.profile_checked, task_started)
    hint_count = _count_hints(db_history)
    reset_for_next_lesson = _should_reset_for_next_lesson(db_history, request.message)

    effective_event_type = request.event_type
    _previous_task_text = ""

    # Το μάθημα δεν ανεβαίνει αμέσως μετά από σωστή λύση — περιμένει επιβεβαίωση, ώστε ο μαθητής
    # να μπορεί να ζητήσει επιπλέον άσκηση στο ίδιο κεφάλαιο πριν προχωρήσει.
    if user.pending_advance and not is_task_attempt_effective:
        pending_intent = await classify_pending_advance_intent_async(
            request.message,
            lesson_title=_LESSON_TITLES_DISPLAY[max(0, min(user.current_lesson_id - 1, len(_LESSON_TITLES_DISPLAY) - 1))]
        )

        if pending_intent == "wants_advance" or reset_for_next_lesson:
            user.current_lesson_id += 1
            user.pending_advance = False
            user.active_task_lesson_id = 0
            user.active_task_text = ""
            user.active_success_criteria = "[]"
            task_started = False
            awaiting_questions = False
            hint_count = 0
            current_total_attempts = 0
            effective_event_type = "lesson_advanced"
            reset_for_next_lesson = False

        elif pending_intent == "wants_more_practice":
            user.pending_advance = False
            _previous_task_text = user.active_task_text or ""
            user.active_task_lesson_id = 0
            user.active_task_text = ""
            user.active_success_criteria = "[]"
            task_started = False
            effective_event_type = "same_chapter_practice"
        elif _wants_to_start_task(request.message):
            user.pending_advance = False
            _previous_task_text = user.active_task_text or ""
            user.active_task_lesson_id = 0
            user.active_task_text = ""
            user.active_success_criteria = "[]"
            task_started = False
            effective_event_type = "same_chapter_practice"
        else:
            task_started = False

    if reset_for_next_lesson:
        user.current_lesson_id += 1
        user.pending_advance = False
        user.active_task_lesson_id = 0
        user.active_task_text = ""
        user.active_success_criteria = "[]"
        task_started = False
        awaiting_questions = False
        hint_count = 0
        current_total_attempts = 0
        effective_event_type = "lesson_advanced"

    idx = max(0, min(user.current_lesson_id - 1, len(_LESSON_TITLES_AGENT) - 1))
    current_lesson = lessons_content.get("lessons", [])[idx] if lessons_content.get("lessons") else {}
    lesson_name = _LESSON_TITLES_AGENT[idx]

    difficulty_probe_direction = user.difficulty_probe_direction or ""

    fast_solver = (
        int(user.solved_tasks or 0) >= 3 and
        float(user.avg_time_spent or 0.0) < 30.0
    )
    if difficulty_probe_direction == "upgrade":
        task_difficulty = "hard"
    elif difficulty_probe_direction == "downgrade":
        task_difficulty = "easy"
    elif current_total_attempts >= 3:
        task_difficulty = "easy"
    elif user.experience_level == "expert" or fast_solver:
        task_difficulty = "hard"
    else:
        task_difficulty = "easy"
    active_task_matches_lesson = (
        user.active_task_lesson_id == user.current_lesson_id
        and bool((user.active_task_text or "").strip())
        and bool((user.active_success_criteria or "").strip())
    )

    if current_lesson and not active_task_matches_lesson:
        task_payload = generate_random_task(current_lesson, task_difficulty, current_task=_previous_task_text or None)
        user.active_task_lesson_id = user.current_lesson_id
        user.active_task_text = task_payload.get("task_text", "")
        rendered_criteria = task_payload.get("rendered_criteria", [])
        user.active_success_criteria = json.dumps(rendered_criteria, ensure_ascii=False)
        current_task = user.active_task_text
        resolved_success_criteria = rendered_criteria
    elif active_task_matches_lesson:
        current_task = user.active_task_text or ""
        try:
            resolved_success_criteria = json.loads(user.active_success_criteria or "[]")
        except Exception:
            resolved_success_criteria = []
    else:
        current_task, resolved_success_criteria = "", []
    performance_summary = _build_performance_summary(db_history, user)

    _is_new_task_transition = reset_for_next_lesson or effective_event_type in ("same_chapter_practice", "lesson_advanced")
    state = {
        "messages": formatted_history,
        "student_code": "" if _is_new_task_transition else request.code,
        "current_lesson_id": user.current_lesson_id,
        "current_lesson": lesson_name,
        "current_task": current_task,
        "performance_summary": performance_summary,
        "experience_level": user.experience_level,
        "attempts_count": current_total_attempts,
        "success_criteria": resolved_success_criteria,
        "debug_report": "",
        "is_correct": False,
        "time_spent": 0.0 if reset_for_next_lesson else (request.time_spent if is_task_attempt_effective else 0.0),
        "task_started": task_started,
        "event_type": effective_event_type,
        "hint_count": hint_count,
        "assessment_feedback": "",
        "assessment_score": 0,
        "assessment_decision": "repeat" if reset_for_next_lesson else (user.last_assessment_decision or "repeat"),
        "understanding_level": user.understanding_level or "developing",
        "awaiting_questions": awaiting_questions,
        "is_first_login": is_first_login,
        "profile_checked": user.profile_checked,
        "profile_soft_defaulted": profile_soft_defaulted,
        "difficulty_probe_direction": difficulty_probe_direction,
        "avg_hints_per_task": float(user.avg_hints_per_task or 0.0),
        "frustration_score": min(3, hint_count + (1 if current_total_attempts >= 3 else 0)),
        "previous_task": _previous_task_text or None,
    }

    output = {}
    raw_response = None
    try:
        output = await asyncio.wait_for(
            langgraph_app.ainvoke(state, config={"recursion_limit": 15}),
            timeout=60
        )
        raw_response = output["messages"][-1].content
        ai_response = re.sub(r'\n?\[(HINT|AWAITING_QUESTIONS|ASCII_SHOWN:\d+|THEORY_DIFFICULTY:\w+:\d+)\]', '', raw_response).strip()
        if not ai_response:
            ai_response = "Συγγνώμη, κάτι πήγε στραβά με την απάντησή μου. Μπορείς να ξαναγράψεις ή να δοκιμάσεις ξανά;"
            raw_response = ai_response
        assessment_score = int(output.get("assessment_score", 0) or 0)
        assessment_decision = output.get("assessment_decision", "repeat")
        understanding_level = output.get("understanding_level", "developing")
        debug_report_output = output.get("debug_report", "")
        is_correct_final = bool(output.get("is_correct", False)) and assessment_decision == "advance"

    except Exception:
        if effective_event_type == "no_submission_timeout":
            ai_response = "Μην ανησυχείς αν δυσκολεύεσαι λίγο — αυτό είναι φυσιολογικό! Πάρε λίγο χρόνο και δοκίμασε να γράψεις έστω και μια γραμμή."
        else:
            ai_response = "Ωχ, κάτι με δυσκόλεψε στη σύνδεση. Μπορείς να ξαναδοκιμάσεις;"
        raw_response = ai_response
        is_correct_final = False
        assessment_score = 0
        assessment_decision = "repeat"
        understanding_level = "developing"
        debug_report_output = ""

    course_completed = False

    _msg_ts = _now_iso()
    new_human = ChatHistory(
        user_id=user.id,
        role="human",
        content=submission_message,
        time_spent=request.time_spent if is_task_attempt_effective else 0.0,
        attempts_count=1 if is_task_attempt_effective else 0,
        session_id=request.session_id,
        created_at=_msg_ts,
    )
    db.add(new_human)

    if is_task_attempt_effective:
        user.last_assessment_decision = assessment_decision
        user.understanding_level = understanding_level

    if not is_correct_final:
        categories = _extract_debug_categories(debug_report_output)
        if categories:
            user.frequent_error_categories = _update_error_profile(user.frequent_error_categories, categories)

    if is_task_attempt_effective and is_correct_final:
        solved_so_far = int(user.solved_tasks or 0)
        avg_so_far = float(user.avg_time_spent or 0.0)
        new_solved = solved_so_far + 1
        user.avg_time_spent = ((avg_so_far * solved_so_far) + max(request.time_spent, 0.0)) / new_solved
        user.solved_tasks = new_solved
        user.avg_hints_per_task = (
            (float(user.avg_hints_per_task or 0.0) * solved_so_far + hint_count) / new_solved
        )

    if is_task_attempt_effective and not is_correct_final and bool(output.get("is_correct", False)):
        user.active_task_lesson_id = 0
        user.active_task_text = ""
        user.active_success_criteria = "[]"

    if is_task_attempt_effective:
        if is_correct_final:
            if difficulty_probe_direction == "upgrade":
                user.experience_level = "expert"
                user.difficulty_probe_direction = ""
            elif difficulty_probe_direction == "downgrade" and understanding_level in {"strong", "good"}:
                user.difficulty_probe_direction = ""
            elif (difficulty_probe_direction == ""
                  and user.experience_level == "beginner"
                  and understanding_level == "strong"
                  and int(user.solved_tasks or 0) >= 2):
                user.difficulty_probe_direction = "upgrade"
        else:
            if difficulty_probe_direction == "upgrade":
                user.difficulty_probe_direction = ""
            elif (difficulty_probe_direction == ""
                  and user.experience_level == "expert"
                  and understanding_level == "needs_support"):
                user.difficulty_probe_direction = "downgrade"

    if is_correct_final:
        if TOTAL_LESSONS and user.current_lesson_id >= TOTAL_LESSONS:
            user.current_lesson_id = TOTAL_LESSONS + 1
            user.pending_advance = False
            course_completed = True
            ai_response = _build_course_stats_message(user, TOTAL_LESSONS, db_history)
            user.active_task_lesson_id = 0
            user.active_task_text = ""
            user.active_success_criteria = "[]"
        else:
            user.pending_advance = True
            user.active_task_lesson_id = 0
            user.active_task_text = ""
            user.active_success_criteria = "[]"

    db.add(ChatHistory(user_id=user.id, role="ai", content=raw_response, session_id=request.session_id, created_at=_now_iso()))

    code_was_correct = bool(output.get("is_correct", False))

    await db.commit()
    return {
        "mentor_response": ai_response,
        "is_correct": code_was_correct,
        "assessment_score": assessment_score,
        "assessment_decision": assessment_decision,
        "course_completed": course_completed,
        "experience_level": user.experience_level or "beginner",
    }
