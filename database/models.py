from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float, Boolean
from database.session import Base

class User(Base):
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
    pending_advance = Column(Boolean, default=False)  # advance περιμένει επιβεβαίωση πριν ανέβει το current_lesson_id
    difficulty_probe_direction = Column(String, default="")  # "" | "upgrade" | "downgrade"
    avg_hints_per_task = Column(Float, default=0.0)

    practice_streak_current = Column(Integer, default=0)
    practice_streak_goal = Column(Integer, default=0)
    practice_lesson_correct_streak = Column(Text, default="{}")  # JSON {lesson_id: consecutive_correct}

class ChatHistory(Base):
    __tablename__ = "chat_histories"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    role = Column(String)
    content = Column(Text)
    time_spent = Column(Float, default=0.0)
    attempts_count = Column(Integer, default=0)
    session_id = Column(Integer, default=0, index=True)
    created_at = Column(String, default="")
