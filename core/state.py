from typing import Annotated, TypedDict, List
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

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
    avg_hints_per_task: float
    frustration_score: int

    profile_soft_defaulted: bool
    previous_task: str

    free_check_mode: bool
    free_check_description: str

    practice_mode: bool
