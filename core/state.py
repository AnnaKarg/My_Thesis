from typing import Annotated, TypedDict, List
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # Το ιστορικό της συνομιλίας (χρησιμοποιείται add_messages για να προσθέτει νέα μηνύματα)
    messages: Annotated[List, add_messages]
    
    # Ο κώδικας που γράφει ο φοιτητής στον editor
    student_code: str 
    
    # Η τεχνική αναφορά του Debugging Agent
    debug_report: str 
    
    # Το αποτέλεσμα της αξιολόγησης (True αν είναι σωστό, False αν όχι)
    is_correct: bool 
    
    # Σε ποια ενότητα από τις 6 βρίσκεται ο φοιτητής
    current_lesson: str 