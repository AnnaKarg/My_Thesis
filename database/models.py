from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float, Boolean # Εισάγουμε τα απαραίτητα στοιχεία από το SQLAlchemy για να ορίσουμε τα πεδία των μοντέλων μας
from database.session import Base # Εισάγουμε το Base από το αρχείο session για να ορίσουμε τα μοντέλα μας

class User(Base): # Ορίζουμε το μοντέλο User που αντιπροσωπεύει τους χρήστες της εφαρμογής
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    experience_level = Column(String, default="beginner")
    current_lesson_id = Column(Integer, default=1)
    profile_checked = Column(Boolean, default=False)
    active_task_lesson_id = Column(Integer, default=0)
    active_task_text = Column(Text, default="")
    active_success_criteria = Column(Text, default="[]")
    frequent_error_categories = Column(Text, default="[]")
    avg_time_spent = Column(Float, default=0.0)
    solved_tasks = Column(Integer, default=0)
    understanding_level = Column(String, default="developing")
    last_assessment_decision = Column(String, default="repeat")
    # Advance περιμένει επιβεβαίωση — το current_lesson_id ΔΕΝ ανεβαίνει αμέσως
    pending_advance = Column(Boolean, default=False)
    # Κατεύθυνση dynamic difficulty probe: "" | "upgrade" | "downgrade"
    difficulty_probe_direction = Column(String, default="")
    # Κυλιόμενος μέσος όρος hints ανά άσκηση — χρησιμοποιείται για να ρυθμίζεται
    # πόσο direct/indirect είναι οι υποδείξεις (0.0 = κανένα hint ακόμα)
    avg_hints_per_task = Column(Float, default=0.0)

    # ── Button 2: Εξάσκηση (ελεύθερη πρακτική, ξεχωριστό από την κύρια ροή μαθημάτων) ──
    # Τρέχον σερί σωστών στη σειρά (σε ΟΠΟΙΟΔΗΠΟΤΕ επιλεγμένο κεφάλαιο) — μηδενίζεται σε λάθος,
    # τροφοδοτεί ΚΑΙ τον προσωπικό στόχο ΚΑΙ την adaptive δυσκολία (streak >= 3 → hard).
    practice_streak_current = Column(Integer, default=0)
    # Προσωπικός στόχος του μαθητή (πόσα σωστά στη σειρά θέλει να πετύχει). 0 = δεν έχει οριστεί.
    practice_streak_goal = Column(Integer, default=0)
    # JSON dict {lesson_id: consecutive_correct} — ΞΕΧΩΡΙΣΤΟ από το practice_streak_current
    # (εκείνο είναι ενιαίο σε όλα τα επιλεγμένα κεφάλαια, αυτό είναι ανά κεφάλαιο) — όταν ένα
    # κεφάλαιο φτάσει το threshold, σβήνει το struggled flag του στο Open Learner Model.
    practice_lesson_correct_streak = Column(Text, default="{}")

class ChatHistory(Base): # Ορίζουμε το μοντέλο ChatHistory που αντιπροσωπεύει το ιστορικό συνομιλιών των χρηστών με τον Mentor
    __tablename__ = "chat_histories"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    role = Column(String)
    content = Column(Text)
    time_spent = Column(Float, default=0.0)
    attempts_count = Column(Integer, default=0)
    session_id = Column(Integer, default=0, index=True)  # groups messages per login session
    created_at = Column(String, default="")               # ISO datetime string