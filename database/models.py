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

class ChatHistory(Base): # Ορίζουμε το μοντέλο ChatHistory που αντιπροσωπεύει το ιστορικό συνομιλιών των χρηστών με τον Mentor
    __tablename__ = "chat_histories"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    role = Column(String)
    content = Column(Text)
    time_spent = Column(Float, default=0.0) 
    attempts_count = Column(Integer, default=0)