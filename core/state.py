from typing import Annotated, TypedDict, List  # Εργαλεία typing για ορισμό δομής και τύπων στο state του agent
from langgraph.graph.message import add_messages # Reducer της LangGraph για συγχώνευση μηνυμάτων στο state
from langchain_core.messages import BaseMessage # Βασικός τύπος μηνύματος της LangChain για το πεδίο messages

class AgentState(TypedDict): # Ορισμός της δομής του state του agent με συγκεκριμένα πεδία και τύπους
    messages: Annotated[List[BaseMessage], add_messages] # Λίστα μηνυμάτων που θα συγχωνευτούν με τη βοήθεια του add_messages reducer

    student_code: str 
    success_criteria: list
    debug_report: str 
    is_correct: bool 

    current_lesson: str
    current_lesson_id: int
    current_task: str
    performance_summary: str

    profile_checked: bool

    experience_level: str
    attempts_count: int

    time_spent: float
    task_started: bool
    awaiting_questions: bool
    event_type: str
    hint_count: int

    assessment_feedback: str
    assessment_score: int
    assessment_decision: str
    understanding_level: str

    is_first_login: bool
    difficulty_probe_direction: str  # "" | "upgrade" | "downgrade"
    avg_hints_per_task: float  # κυλιόμενος μέσος όρος hints ανά άσκηση — ρυθμίζει directness των hints
    frustration_score: int    # 0-3: frustration level (hints + failed attempts) — ρυθμίζει τον τόνο του mentor