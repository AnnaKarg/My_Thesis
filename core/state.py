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

    profile_checked: bool

    experience_level: str
    attempts_count: int

    time_spent: float
    task_started: bool

    is_first_login: bool 