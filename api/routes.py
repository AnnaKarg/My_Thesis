from fastapi import APIRouter, Depends, HTTPException # Εισάγει τα απαραίτητα components από το FastAPI
import asyncio # Για ασύγχρονες λειτουργίες
import json # Για φόρτωση των μαθημάτων από το αρχείο JSON
import re
import time
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path # Για να βρει το μονοπάτι του αρχείου JSON με τα μαθήματα
from sqlalchemy.ext.asyncio import AsyncSession # Για ασύγχρονη διαχείριση της βάσης δεδομένων
from sqlalchemy.future import select # Για εκτέλεση ερωτημάτων στη βάση δεδομένων
from database.session import AsyncSessionLocal # Για να πάρει μια ασύγχρονη συνεδρία με τη βάση δεδομένων
from database.models import User, ChatHistory # Για να δουλέψει με τα μοντέλα της βάσης δεδομένων
from pydantic import BaseModel # Για να ορίσει τα σχήματα των αιτημάτων
from passlib.context import CryptContext # Για να χειριστεί την κρυπτογράφηση των κωδικών
from langchain_core.messages import HumanMessage, AIMessage  # Για να δημιουργήσει μηνύματα για το μοντέλο γλώσσας
from core.app import app as langgraph_app # Για να καλέσει το LangGraph app που τρέχει τους agents
from agents.mentor import (
    generate_random_task,
    classify_profile_async,
    generate_session_recap_async,
    classify_pending_advance_intent_async,
    _wants_to_start_task,
)
from agents.assessor import UNDERSTANDING_LEVEL_TO_MASTERY_PCT

router = APIRouter() # Δημιουργεί ένα router για να ορίσει τα API endpoints που σχετίζονται με το chat και την αυθεντικοποίηση
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") # Ορίζει το context για την κρυπτογράφηση των κωδικών με bcrypt

LESSONS_PATH = Path(__file__).resolve().parents[1] / "content" / "lessons.json"
with open(LESSONS_PATH, "r", encoding="utf-8") as f:
    lessons_content = json.load(f)

TOTAL_LESSONS = len(lessons_content.get("lessons", []))
MIN_PASS_SCORE = 80

# Ενιαία λίστα τίτλων μαθημάτων — αντλείται απευθείας από το lessons.json
# Αποφεύγουμε δύο ανεξάρτητες hardcoded λίστες που μπορούν να αποσυγχρονιστούν.
_LESSON_TITLES_DISPLAY = [l.get("title", f"Μάθημα {l.get('id',i+1)}")
                           for i, l in enumerate(lessons_content.get("lessons", []))]
# Σύντομα αγγλικά ονόματα για το agent state — αντλούνται αυτόματα από lessons.json (agent_title)
_LESSON_TITLES_AGENT = [
    l.get("agent_title", l.get("title", f"Lesson {l.get('id', i+1)}"))
    for i, l in enumerate(lessons_content.get("lessons", []))
]

class UserAuth(BaseModel): # Σχήμα για τα δεδομένα αυθεντικοποίησης που λαμβάνονται από το frontend
    username: str
    password: str

class ChatRequest(BaseModel): # Σχήμα για τα δεδομένα που λαμβάνονται από το frontend για κάθε μήνυμα στο chat
    message: str
    code: str = ""
    time_spent: float = 0.0
    is_task_attempt: bool = False
    task_started: bool = False
    event_type: str = ""
    session_id: int = 0

_HISTORY_TOKENS_RE = re.compile(
    r'\n?\[(?:HINT|AWAITING_QUESTIONS|BUTTON:START_TASK|BUTTON:CONTINUE_TASK|'
    r'ASSESSMENT:ADVANCE|ASSESSMENT:REPEAT|ASSESSMENT:SUPPORT|DEBUG:[^\]]*)\]'
)

def _sanitize_history(text: str) -> str:
    return _HISTORY_TOKENS_RE.sub('', text or '').strip()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _is_code_submission_message(content: str) -> bool: # Ελέγχει αν το μήνυμα υποδηλώνει υποβολή κώδικα
    normalized = (content or "").strip().upper()
    return normalized == "CODE_SUBMISSION" or "```" in (content or "")

def _format_submission_message(code: str) -> str: # Μορφοποιεί το μήνυμα υποβολής κώδικα 
    cleaned_code = code.strip()
    if not cleaned_code:
        return "Υποβολή κώδικα"

    return f"Υποβολή κώδικα:\n```python\n{cleaned_code}\n```"

def _build_welcome_message(username: str, db_history, current_lesson_id: int) -> str: # Δημιουργεί το μήνυμα καλωσορίσματος 
    if not db_history:
        return (
            f"Γεια σου {username}! Είμαι ο Mentor σου και είμαι εδώ για να σε βοηθήσω να μάθεις Python. "
            "Πριν ξεκινήσουμε, πες μου: έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
        )

    idx = max(0, min(current_lesson_id - 1, len(_LESSON_TITLES_DISPLAY) - 1))
    lesson_name = _LESSON_TITLES_DISPLAY[idx]

    recent_human = [h.content for h in db_history if h.role == "human" and not _is_code_submission_message(h.content) and not (h.content or "").startswith("__NO_SUBMISSION_TIMEOUT__")]
    last_user_topic = recent_human[-1] if recent_human else "στην εισαγωγή μας"
    
    return (
        f"Καλώς ήρθες ξανά {username}! Την προηγούμενη φορά μείναμε στο μάθημα '{lesson_name}'. "
        f"Θυμάμαι που είπαμε για: '{last_user_topic[:50]}...'. "
        "Έχεις κάποια απορία σε αυτά που είδαμε ή θέλεις να προχωρήσουμε;"
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
    """Μετράει hints ΜΟΝΟ για την τρέχουσα άσκηση (μετά το τελευταίο [BUTTON:START_TASK] ή [ASSESSMENT:ADVANCE]).
    Αποτρέπει hints από προηγούμενες ασκήσεις/μαθήματα να επηρεάζουν την αξιολόγηση."""
    count = 0
    for h in reversed(db_history):
        if h.role == "ai":
            content = h.content or ""
            if "[BUTTON:START_TASK]" in content or "[BUTTON:CONTINUE_TASK]" in content or "[ASSESSMENT:ADVANCE]" in content:
                break  # αρχή τρέχουσας άσκησης — σταματάμε
            if "[HINT]" in content:
                count += 1
    return count

def _count_attempts_since_last_task(db_history) -> int:
    """Μετράει attempts ΜΟΝΟ για την τρέχουσα άσκηση (από το τελευταίο [BUTTON:START_TASK] ή [ASSESSMENT:ADVANCE]).
    Αποτρέπει τη συσσώρευση attempts από προηγούμενες ασκήσεις να κρατά τον μαθητή σε 'repeat' για πάντα."""
    count = 0
    for h in reversed(db_history):
        if h.role == "ai":
            content = h.content or ""
            if "[BUTTON:START_TASK]" in content or "[BUTTON:CONTINUE_TASK]" in content or "[ASSESSMENT:ADVANCE]" in content:
                break  # αρχή τρέχουσας άσκησης — μετράμε μόνο από εδώ και μετά
        elif h.role == "human" and (h.attempts_count or 0) > 0:
            count += h.attempts_count
    return count

def _has_recent_attempts(db_history) -> bool:
    """Επιστρέφει True μόνο αν υπάρχουν υποβολές κώδικα ΜΕΤΑ την τελευταία μετάβαση μαθήματος (ADVANCE).
    Αποτρέπει το task_started=True να μεταφέρεται από προηγούμενα μαθήματα."""
    for h in reversed(db_history):
        if h.role == "ai" and "[ASSESSMENT:ADVANCE]" in (h.content or ""):
            return False 
        if h.role == "human" and (h.attempts_count or 0) > 0:
            return True
    return False

def _has_pending_advance_in_history(db_history) -> bool:
    """True αν το τελευταίο AI μήνυμα περιέχει [ASSESSMENT:ADVANCE] — δηλαδή υπάρχει
    εκκρεμής μετάβαση που περιμένει επιβεβαίωση από τον μαθητή."""
    for h in reversed(db_history):
        if h.role != "ai":
            continue
        content = (h.content or "")
        return "[ASSESSMENT:ADVANCE]" in content
    return False

def _should_reset_for_next_lesson(db_history, user_message: str) -> bool:
    """Keyword-based fallback — χρησιμοποιείται ΜΟΝΟ όταν pending_advance=False
    (δηλαδή για παλιές συνεδρίες που δεν έχουν το νέο flag).
    Για pending_advance=True χρησιμοποιείται το LLM classify_pending_advance_intent_async."""
    normalized = (user_message or "").strip().lower()
    # Αρνητικές φράσεις ("δεν νιωθω ετοιμη", "όχι", "δε θέλω") δεν θεωρούνται επιβεβαίωση
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

def _build_course_stats_message(user, total_lessons: int) -> str:
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
        error_section = "- **Λάθη:** Καμία επαναλαμβανόμενη δυσκολία εντοπίστηκε 🌟"

    return (
        f"🎉 **Συγχαρητήρια, {user.username}! Ολοκλήρωσες όλο το πρόγραμμα μαθημάτων Python!**\n\n"
        f"**📊 Τα στατιστικά σου:**\n"
        f"- **Μαθήματα:** {total_lessons}/{total_lessons} ολοκληρωμένα\n"
        f"- **Ασκήσεις που λύθηκαν:** {solved}\n"
        f"- **Μέσος χρόνος ανά άσκηση:** {avg_time:.0f} δευτερόλεπτα\n"
        f"- **Τελικό επίπεδο:** {level_display}\n"
        f"{error_section}\n\n"
        f"Εξαιρετική δουλειά! Συνέχισε να εξασκείσαι — η Python σε περιμένει!"
    )

async def get_db():
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()

def _compute_mastery_profile(user: User, db_history) -> list:
    """Open Learner Model (Bull & Kay): mastery % ανά ενότητα — εμφανίζεται στο frontend.
    0% αν δεν έχει γίνει ΚΑΜΙΑ υποβολή στο τρέχον μάθημα ακόμα — το "developing" είναι το
    DB default για νέους λογαριασμούς, δεν σημαίνει ότι όντως δουλεύει στο επίπεδο εκείνο."""
    current_mastery = (
        UNDERSTANDING_LEVEL_TO_MASTERY_PCT.get(user.understanding_level or "developing", 50)
        if _has_recent_attempts(db_history) else 0
    )
    mastery_profile = []
    for lesson_obj in lessons_content.get("lessons", []):
        lid = lesson_obj.get("id", 0)
        if lid < user.current_lesson_id:
            pct = 100
        elif lid == user.current_lesson_id:
            pct = current_mastery
        else:
            pct = 0
        mastery_profile.append({"id": lid, "title": lesson_obj.get("title", ""), "mastery": pct})
    return mastery_profile

@router.post("/register") # Endpoint για την εγγραφή νέου χρήστη
async def register(user_data: UserAuth, db: AsyncSession = Depends(get_db)): 
    query = await db.execute(select(User).filter(User.username == user_data.username))
    if query.scalars().first():
        raise HTTPException(status_code=400, detail="Το όνομα χρήστη υπάρχει ήδη")

    hashed_pwd = pwd_context.hash(user_data.password)
    new_user = User(username=user_data.username, hashed_password=hashed_pwd)
    db.add(new_user)
    await db.commit()
    return {"message": "Η εγγραφή ολοκληρώθηκε!"}

@router.post("/login") # Endpoint για την αυθεντικοποίηση χρήστη
async def login(user_data: UserAuth, db: AsyncSession = Depends(get_db)):
    query = await db.execute(select(User).filter(User.username == user_data.username))
    user = query.scalars().first()

    if not user or not pwd_context.verify(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Λάθος όνομα χρήστη ή κωδικός")

    return {"username": user.username, "id": user.id}

@router.get("/session/{user_id}/progress")
# Ελαφρύ endpoint ΧΩΡΙΣ side-effects (καμία εγγραφή ChatHistory, κανένα LLM call) — φτιάχτηκε
# ειδικά ώστε η αρχική σελίδα να μπορεί να ανανεώνει mastery_profile/experience_level κάθε φορά
# που εμφανίζεται, χωρίς να δημιουργεί κατά λάθος νέο "session" σαν το /welcome.
async def session_progress(user_id: int, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    history_query = await db.execute(
        select(ChatHistory).filter(ChatHistory.user_id == user_id).order_by(ChatHistory.id.asc())
    )
    db_history = history_query.scalars().all()

    return {
        "experience_level": user.experience_level or "beginner",
        "mastery_profile": _compute_mastery_profile(user, db_history),
    }

@router.get("/session/{user_id}/welcome") # Endpoint για να πάρει το μήνυμα καλωσορίσματος και την τρέχουσα κατάσταση του χρήστη όταν ξεκινάει μια νέα συνεδρία
async def session_welcome(user_id: int, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Ο χρήστης δεν βρέθηκε")

    history_query = await db.execute(
        select(ChatHistory).filter(ChatHistory.user_id == user_id).order_by(ChatHistory.id.asc())
    )
    db_history = history_query.scalars().all()

    if db_history:
        idx = max(0, min(user.current_lesson_id - 1, len(_LESSON_TITLES_DISPLAY) - 1))
        lesson_name = _LESSON_TITLES_DISPLAY[idx]

        history_pairs = [(h.role, h.content) for h in db_history]
        # Timeout σύντομο (όχι τα 60s του /chat) — αυτό το call μπλοκάρει το ΦΟΡΤΩΜΑ της αρχικής
        # σελίδας (μαζί με το mastery_profile, που δεν έχει καμία σχέση με LLM). Αν αργήσει το LLM,
        # προτιμάμε γρήγορο deterministic welcome message παρά να χάσει ο χρήστης ΟΛΟ το response.
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

        # Spaced Repetition Warm-up (Ebbinghaus): αν έχουν περάσει >2 μέρες από την τελευταία συνεδρία
        # και ο μαθητής έχει ήδη κάνει profile check, ζητάμε recall της προηγούμενης ενότητας.
        if user.profile_checked:
            try:
                last_entry = db_history[-1]
                if last_entry.created_at:
                    last_ts = datetime.fromisoformat(last_entry.created_at.replace("Z", "+00:00"))
                    now_ts = datetime.now(timezone.utc)
                    days_away = (now_ts - last_ts).total_seconds() / 86400
                    if days_away > 2 and user.current_lesson_id > 1:
                        # Βρίσκουμε το ΠΡΟΗΓΟΥΜΕΝΟ μάθημα με βάση το id, όχι raw list index —
                        # η λίστα lessons δεν είναι πάντα 1-προς-1 ευθυγραμμισμένη με id-1.
                        prev_lesson = next(
                            (l for l in lessons_content.get("lessons", []) if l.get("id") == user.current_lesson_id - 1),
                            None,
                        )
                        warmup_q = prev_lesson.get("warmup_question", "") if prev_lesson else ""
                        if warmup_q:
                            welcome_message += f"\n\n---\n\n**Επανάληψη σπαγγένης μάθησης:** {warmup_q}"
            except Exception:
                pass
    else:
        welcome_message = _build_welcome_message(user.username, db_history, user.current_lesson_id)

    mastery_profile = _compute_mastery_profile(user, db_history)

    new_session_id = int(time.time())
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

@router.post("/chat/{user_id}") # Endpoint για την αλληλεπίδραση με τον χρήστη στην συνεδρία
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

    # Αν έχει ολοκληρωθεί το πρόγραμμα μαθημάτων, δεν συνεχίζουμε κανονική ροή agents.
    if TOTAL_LESSONS and user.current_lesson_id > TOTAL_LESSONS:
        ai_response = _build_course_stats_message(user, TOTAL_LESSONS)
        _ts = _now_iso()
        db.add(ChatHistory(user_id=user.id, role="human", content=submission_message, time_spent=0.0, attempts_count=0, session_id=request.session_id, created_at=_ts))
        db.add(ChatHistory(user_id=user.id, role="ai", content=ai_response, session_id=request.session_id, created_at=_ts))
        await db.commit()
        return {
            "mentor_response": ai_response,
            "is_correct": False,
            "course_completed": True
        }

    # 1. Profile Check Logic (Beginner vs Expert) — LLM-based classification
    # ΠΡΟΣΟΧΗ: όχι len(db_history) == 0 — το /session/welcome εισάγει πάντα ένα welcome
    # μήνυμα ΠΡΙΝ το πρώτο πραγματικό μήνυμα του μαθητή, άρα db_history έχει ήδη 1 εγγραφή
    # (το welcome, role="ai") όταν φτάνει το πρώτο chat request. Ελέγχουμε αν υπάρχει ΚΑΝΕΝΑ
    # ανθρώπινο μήνυμα — αυτό είναι το πραγματικό "έχει μιλήσει ποτέ ο μαθητής;".
    is_first_login = not any(h.role == "human" for h in db_history)
    profile_soft_defaulted = False
    if not user.profile_checked:
        profile_result = await classify_profile_async(request.message)
        if profile_result == "ambiguous":
            # Απάντησε αλλά χωρίς να διευκρινίσει ποιο από τα δύο (π.χ. γυμνό "ναι") —
            # soft-default σε beginner αντί να ξαναρωτήσουμε, ο mentor το εξηγεί αυτόνομα.
            user.experience_level = "beginner"
            user.profile_checked = True
            profile_soft_defaulted = True
        elif profile_result != "unclear":
            # Ξεκάθαρη απάντηση → κλειδώνουμε το profile
            user.experience_level = profile_result
            user.profile_checked = True
        # αν "unclear" (gibberish): profile_checked παραμένει False → mentor ξαναρωτά

    # 2. Attempts Tracking — μόνο για την τρέχουσα άσκηση, όχι cumulative ιστορία
    has_current_submission = bool(request.code.strip()) or "CODE_SUBMISSION" in request.message.upper()
    is_task_attempt_effective = request.is_task_attempt or has_current_submission

    # Μετράμε attempts μόνο από το τελευταίο [BUTTON:START_TASK] (ή ADVANCE).
    # Αποτρέπει ο μαθητής που αγωνίστηκε σε άσκηση Α να "κολλάει" σε repeat για πάντα λόγω
    # σωρευτικών attempts που ακυρώνουν την καλή επίδοσή του στην άσκηση Β.
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
    _previous_task_text = ""  # αποθηκεύεται πριν καθαριστεί, για αποφυγή επανάληψης same_chapter_practice

    # ── Pending advance handling (LLM-based, όχι keyword matching) ──────────
    # Το μάθημα ΔΕΝ ανεβαίνει αμέσως μετά από σωστή λύση — περιμένει επιβεβαίωση.
    # Έτσι ο μαθητής μπορεί να ζητήσει επιπλέον άσκηση ΙΔΙΟΥ κεφαλαίου πριν προχωρήσει.
    if user.pending_advance and not is_task_attempt_effective:
        # Χρησιμοποιούμε LLM για να καταλάβουμε τι θέλει ο μαθητής:
        # wants_advance | wants_more_practice | other
        pending_intent = await classify_pending_advance_intent_async(
            request.message,
            lesson_title=_LESSON_TITLES_DISPLAY[max(0, min(user.current_lesson_id - 1, len(_LESSON_TITLES_DISPLAY) - 1))]
        )

        if pending_intent == "wants_advance" or reset_for_next_lesson:
            # Ο μαθητής επιβεβαίωσε → advance τώρα
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
            reset_for_next_lesson = False  # αποτρέπει διπλή εκτέλεση παρακάτω

        elif pending_intent == "wants_more_practice":
            # Ο μαθητής θέλει άλλη άσκηση στο ΙΔΙΟ κεφάλαιο → νέα χωρίς advance
            user.pending_advance = False
            _previous_task_text = user.active_task_text or ""  # αποθηκεύουμε πριν καθαρίσουμε
            user.active_task_lesson_id = 0  # force νέα παραλλαγή άσκησης
            user.active_task_text = ""
            user.active_success_criteria = "[]"
            task_started = False
            # Ξεχωριστό event_type για να μην μπει ο mentor στο just_advanced path
            effective_event_type = "same_chapter_practice"
        elif _wants_to_start_task(request.message):
            # Safety net: classify_pending_advance επέστρεψε "other" αλλά το μήνυμα
            # είναι σαφές αίτημα για άσκηση ("αλλη ασκηση", "δωσε μου ασκηση" κλπ).
            user.pending_advance = False
            _previous_task_text = user.active_task_text or ""  # αποθηκεύουμε πριν καθαρίσουμε
            user.active_task_lesson_id = 0
            user.active_task_text = ""
            user.active_success_criteria = "[]"
            task_started = False
            effective_event_type = "same_chapter_practice"
        else:
            # ερώτηση/σχόλιο → το pending_advance παραμένει, ο mentor απαντά κανονικά.
            # task_started=False ΠΑΝΤΑ εδώ (όχι μόνο για συγκεκριμένες λέξεις-κλειδιά): η άσκηση
            # μόλις λύθηκε σωστά, άρα ο μαθητής δεν είναι πια "mid-task" — ασαφές μήνυμα σε αυτό
            # το σημείο είναι πολύ πιο πιθανό να είναι σχόλιο/ερώτηση παρά συνέχιση της άσκησης.
            task_started = False
    # ─────────────────────────────────────────────────────────────────────────

    if reset_for_next_lesson:
        # Legacy fallback (βλ. _should_reset_for_next_lesson) — καθαρίζουμε ΠΛΗΡΩΣ το
        # παλιό μάθημα ώστε να μη μείνουν κατάλοιπα (task/criteria/lesson_id) από πριν.
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

    # ── Dynamic difficulty (probe) ────────────────────────────────────────────
    # Χρησιμοποιούμε το αποτέλεσμα ΠΡΟΗΓΟΥΜΕΝΗΣ άσκησης (user.understanding_level)
    # για να αποφασίσουμε αν δοκιμάσουμε διαφορετική δυσκολία αυτή τη φορά.
    difficulty_probe_direction = user.difficulty_probe_direction or ""

    fast_solver = (
        int(user.solved_tasks or 0) >= 3 and
        float(user.avg_time_spent or 0.0) < 30.0
    )
    if difficulty_probe_direction == "upgrade":
        task_difficulty = "hard"   # δοκιμαστική hard άσκηση για πιθανή αναβάθμιση
    elif difficulty_probe_direction == "downgrade":
        task_difficulty = "easy"   # εύκολες ασκήσεις για ανάκαμψη
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
    
    # Καθαρό student_code σε κάθε μετάβαση σε ΝΕΑ άσκηση/μάθημα — αποτρέπει παλιό κώδικα
    # (π.χ. από προηγούμενη λυμένη άσκηση) να αξιολογηθεί κατά λάθος πάνω σε νέα κριτήρια.
    # Στην πράξη το frontend ήδη στέλνει code="" σε μηνύματα χωρίς submission, αλλά αυτό
    # είναι η ντετερμινιστική εγγύηση στο backend, ανεξάρτητη από τη συμπεριφορά του client.
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
    raw_response = None  # η ακατέργαστη απάντηση με εσωτερικά tokens (αποθηκεύεται στο DB)
    try:
        output = await asyncio.wait_for(
            langgraph_app.ainvoke(state, config={"recursion_limit": 15}),
            timeout=60
        )
        raw_response = output["messages"][-1].content
        # Αφαιρούμε [HINT] και [AWAITING_QUESTIONS] ΜΟΝΟ από την απάντηση προς τον χρήστη.
        # Στο DB αποθηκεύουμε raw_response ώστε να λειτουργούν σωστά τα
        # _infer_awaiting_questions (ψάχνει [AWAITING_QUESTIONS]) και _count_hints (ψάχνει [HINT]).
        ai_response = re.sub(r'\n?\[(HINT|AWAITING_QUESTIONS)\]', '', raw_response).strip()
        assessment_score = int(output.get("assessment_score", 0) or 0)
        assessment_decision = output.get("assessment_decision", "repeat")
        understanding_level = output.get("understanding_level", "developing")
        debug_report_output = output.get("debug_report", "")
        is_correct_final = bool(output.get("is_correct", False)) and assessment_score >= MIN_PASS_SCORE and assessment_decision == "advance"

    except Exception:
        if effective_event_type == "no_submission_timeout":
            ai_response = "Μην ανησυχείς αν δυσκολεύεσαι λίγο — αυτό είναι φυσιολογικό! Πάρε λίγο χρόνο και δοκίμασε να γράψεις έστω και μια γραμμή. 💡"
        else:
            ai_response = "Ωχ, κάτι με δυσκόλεψε στη σύνδεση. Μπορείς να ξαναδοκιμάσεις;"
        raw_response = ai_response  # δεν υπάρχουν tokens να διατηρήσουμε στο error path
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

    # Αποθηκεύουμε assessment αποτελέσματα ΜΟΝΟ όταν έτρεξε ο assessor (κώδικας υποβλήθηκε).
    # Αν δεν υπήρχε υποβολή κώδικα, ο assessor δεν τρέχει και το default "repeat" θα αντικαθιστούσε
    # λανθασμένα μια ήδη αποθηκευμένη "advance" ή "support" απόφαση.
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
        # Rolling avg: πόσα hints χρειάστηκε αυτός ο μαθητής ανά άσκηση
        user.avg_hints_per_task = (
            (float(user.avg_hints_per_task or 0.0) * solved_so_far + hint_count) / new_solved
        )

    # Σωστή λύση αλλά assessment_decision != "advance" (support/repeat):
    # μηδενίζουμε active_task ώστε η επόμενη wants_task να δώσει νέα παραλλαγή άσκησης
    if is_task_attempt_effective and not is_correct_final and bool(output.get("is_correct", False)):
        user.active_task_lesson_id = 0
        user.active_task_text = ""
        user.active_success_criteria = "[]"

    # ── Dynamic difficulty probe update ──────────────────────────────────────
    if is_task_attempt_effective:
        if is_correct_final:
            if difficulty_probe_direction == "upgrade":
                # Η hard δοκιμαστική άσκηση πέρασε → μόνιμη αναβάθμιση σε expert
                user.experience_level = "expert"
                user.difficulty_probe_direction = ""
            elif difficulty_probe_direction == "downgrade" and understanding_level in {"strong", "good"}:
                # Ο μαθητής ανέκαμψε από εύκολες ασκήσεις → καθαρίζουμε το probe
                user.difficulty_probe_direction = ""
            elif (difficulty_probe_direction == ""
                  and user.experience_level == "beginner"
                  and understanding_level == "strong"
                  and int(user.solved_tasks or 0) >= 2):
                # Beginner λύνει όλα γρήγορα → δοκιμαστική hard άσκηση επόμενη φορά
                user.difficulty_probe_direction = "upgrade"
        else:
            # Αποτυχία
            if difficulty_probe_direction == "upgrade":
                # Η hard άσκηση ήταν πολύ δύσκολη → επιστροφή στο κανονικό
                user.difficulty_probe_direction = ""
            elif (difficulty_probe_direction == ""
                  and user.experience_level == "expert"
                  and understanding_level == "needs_support"):
                # Expert δυσκολεύεται → probe με εύκολες ασκήσεις
                user.difficulty_probe_direction = "downgrade"
    # ─────────────────────────────────────────────────────────────────────────

    if is_correct_final:
        if TOTAL_LESSONS and user.current_lesson_id >= TOTAL_LESSONS:
            # Τελευταίο μάθημα → advance αμέσως, ολοκλήρωση προγράμματος
            user.current_lesson_id = TOTAL_LESSONS + 1
            user.pending_advance = False
            course_completed = True
            ai_response = _build_course_stats_message(user, TOTAL_LESSONS)
            user.active_task_lesson_id = 0
            user.active_task_text = ""
            user.active_success_criteria = "[]"
        else:
            # ΔΕΝ ανεβάζουμε αμέσως — περιμένουμε επιβεβαίωση ή "αλλη ασκηση"
            user.pending_advance = True
            user.active_task_lesson_id = 0  # νέα παραλλαγή αν ζητήσει επιπλέον άσκηση
            user.active_task_text = ""
            user.active_success_criteria = "[]"
            # current_lesson_id παραμένει ίδιο μέχρι επιβεβαίωση

    # Αποθηκεύουμε raw_response (με εσωτερικά tokens) ώστε οι helper functions να μπορούν
    # να εντοπίζουν [AWAITING_QUESTIONS], [HINT], [ASSESSMENT:*] κλπ. στο ιστορικό.
    db.add(ChatHistory(user_id=user.id, role="ai", content=raw_response, session_id=request.session_id, created_at=_now_iso()))

    # code_was_correct: True όταν ο κώδικας ήταν σωστός (ακόμα κι αν decision="repeat").
    # Χρησιμοποιείται από το frontend για να κλειδώσει τον editor μόλις η άσκηση λυθεί.
    code_was_correct = bool(output.get("is_correct", False)) and assessment_score >= MIN_PASS_SCORE

    await db.commit()
    return {
        "mentor_response": ai_response,
        "is_correct": code_was_correct,
        "assessment_score": assessment_score,
        "assessment_decision": assessment_decision,
        "course_completed": course_completed,
        "experience_level": user.experience_level or "beginner",
    }