from fastapi import APIRouter, Depends, HTTPException # Εισάγει τα απαραίτητα components από το FastAPI
import asyncio # Για ασύγχρονες λειτουργίες
import json # Για φόρτωση των μαθημάτων από το αρχείο JSON
from pathlib import Path # Για να βρει το μονοπάτι του αρχείου JSON με τα μαθήματα
from sqlalchemy.ext.asyncio import AsyncSession # Για ασύγχρονη διαχείριση της βάσης δεδομένων
from sqlalchemy.future import select # Για εκτέλεση ερωτημάτων στη βάση δεδομένων
from database.session import AsyncSessionLocal # Για να πάρει μια ασύγχρονη συνεδρία με τη βάση δεδομένων
from database.models import User, ChatHistory # Για να δουλέψει με τα μοντέλα της βάσης δεδομένων
from pydantic import BaseModel # Για να ορίσει τα σχήματα των αιτημάτων
from passlib.context import CryptContext # Για να χειριστεί την κρυπτογράφηση των κωδικών
from langchain_core.messages import HumanMessage, AIMessage  # Για να δημιουργήσει μηνύματα για το μοντέλο γλώσσας
from core.app import app as langgraph_app # Για να καλέσει το LangGraph app που τρέχει τους agents

router = APIRouter() # Δημιουργεί ένα router για να ορίσει τα API endpoints που σχετίζονται με το chat και την αυθεντικοποίηση
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") # Ορίζει το context για την κρυπτογράφηση των κωδικών με bcrypt

LESSONS_PATH = Path(__file__).resolve().parents[1] / "content" / "lessons.json"
with open(LESSONS_PATH, "r", encoding="utf-8") as f:
    lessons_content = json.load(f)

TOTAL_LESSONS = len(lessons_content.get("lessons", [])) 

class UserAuth(BaseModel): # Σχήμα για τα δεδομένα αυθεντικοποίησης που λαμβάνονται από το frontend
    username: str
    password: str

class ChatRequest(BaseModel): # Σχήμα για τα δεδομένα που λαμβάνονται από το frontend για κάθε μήνυμα στο chat
    message: str
    code: str = ""
    time_spent: float = 0.0
    is_task_attempt: bool = False

def _get_success_criteria(current_lesson_id: int):# Επιστρέφει τα κριτήρια επιτυχίας για το τρέχον μάθημα βάσει του ID του μαθήματος
    lessons = lessons_content.get("lessons", [])
    lesson = next((l for l in lessons if l.get("id") == current_lesson_id), None)
    if not lesson:
        return []
    return lesson.get("success_criteria", [])

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

    lesson_titles = ["Εισαγωγή και Μεταβλητές", "Τύποι Δεδομένων", "Δομές Ελέγχου", "Λίστες", "Επαναλήψεις", "Συναρτήσεις"]
    idx = max(0, min(current_lesson_id - 1, len(lesson_titles) - 1))
    lesson_name = lesson_titles[idx]

    recent_human = [h.content for h in db_history if h.role == "human" and not _is_code_submission_message(h.content)]
    last_user_topic = recent_human[-1] if recent_human else "στην εισαγωγή μας"
    
    return (
        f"Καλώς ήρθες ξανά {username}! Την προηγούμενη φορά μείναμε στο μάθημα '{lesson_name}'. "
        f"Θυμάμαι που είπαμε για: '{last_user_topic[:50]}...'. "
        "Έχεις κάποια απορία σε αυτά που είδαμε ή θέλεις να προχωρήσουμε;"
    )

async def get_db(): 
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()

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

    return {
        "message": _build_welcome_message(user.username, db_history, user.current_lesson_id),
        "current_lesson_id": user.current_lesson_id,
        "profile_checked": user.profile_checked
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
        ai_response = (
            "Συγχαρητήρια! Έχεις ολοκληρώσει όλα τα διαθέσιμα μαθήματα. "
            "Για την παρούσα έκδοση η διδασκαλία ολοκληρώνεται εδώ."
        )
        db.add(ChatHistory(user_id=user.id, role="human", content=submission_message, time_spent=0.0, attempts_count=0))
        db.add(ChatHistory(user_id=user.id, role="ai", content=ai_response))
        await db.commit()
        return {
            "mentor_response": ai_response,
            "is_correct": False,
            "course_completed": True
        }

    # 1. Profile Check Logic (Beginner vs Advanced)
    is_first_login = len(db_history) == 0
    if is_first_login:
        msg = request.message.lower()
        if any(word in msg for word in ["όχι", "ποτέ", "πρώτη φορά", "δεν ξέρω", "αρχάριος"]):
            user.experience_level = "beginner"
        elif any(word in msg for word in ["ναι", "έχω ξαναγράψει", "γνωρίζω", "προχωρημένος"]):
            user.experience_level = "advanced"
        user.profile_checked = True

    # 2. Attempts Tracking
    has_current_submission = bool(request.code.strip()) or "CODE_SUBMISSION" in request.message.upper()
    is_task_attempt_effective = request.is_task_attempt or has_current_submission

    past_attempts = sum(h.attempts_count for h in db_history if h.attempts_count is not None)
    current_total_attempts = past_attempts + (1 if is_task_attempt_effective else 0)

    formatted_history = []
    for h in db_history:
        msg_class = HumanMessage if h.role == "human" else AIMessage
        formatted_history.append(msg_class(content=h.content))
    formatted_history.append(HumanMessage(content=submission_message))

    task_started = any((h.attempts_count or 0) > 0 for h in db_history) or is_task_attempt_effective
    
    lesson_titles = ["Variables", "Data Types", "Conditions", "Lists", "Loops", "Functions"]
    idx = max(0, min(user.current_lesson_id - 1, len(lesson_titles) - 1))
    
    state = {
        "messages": formatted_history,
        "student_code": request.code,
        "current_lesson_id": user.current_lesson_id,
        "current_lesson": lesson_titles[idx],
        "experience_level": user.experience_level,
        "attempts_count": current_total_attempts,
        "success_criteria": _get_success_criteria(user.current_lesson_id),
        "debug_report": "",
        "is_correct": False,
        "time_spent": request.time_spent if is_task_attempt_effective else 0.0,
        "task_started": task_started,
        "is_first_login": is_first_login,
        "profile_checked": user.profile_checked
    }

    try:
        output = await asyncio.wait_for(
            langgraph_app.ainvoke(state, config={"recursion_limit": 15}),
            timeout=60 
        )
        ai_response = output["messages"][-1].content
        is_correct_final = output.get("is_correct", False)
            
    except Exception:
        ai_response = "Ωχ, κάτι με δυσκόλεψε στη σύνδεση. Μπορείς να ξαναδοκιμάσεις;"
        is_correct_final = False

    course_completed = False

    new_human = ChatHistory(
        user_id=user.id, 
        role="human", 
        content=submission_message,
        time_spent=request.time_spent if is_task_attempt_effective else 0.0,
        attempts_count=1 if is_task_attempt_effective else 0
    )
    db.add(new_human)
    
    if is_correct_final:
        if TOTAL_LESSONS and user.current_lesson_id >= TOTAL_LESSONS:
            user.current_lesson_id = TOTAL_LESSONS + 1
            course_completed = True
            ai_response = (
                "Συγχαρητήρια! Ολοκλήρωσες επιτυχώς όλα τα διαθέσιμα μαθήματα. "
                "Στην παρούσα φάση η διδασκαλία ολοκληρώνεται εδώ."
            )
        else:
            user.current_lesson_id += 1

    db.add(ChatHistory(user_id=user.id, role="ai", content=ai_response))

    await db.commit()
    return {
        "mentor_response": ai_response,
        "is_correct": is_correct_final,
        "course_completed": course_completed
    }