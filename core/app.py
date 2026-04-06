from langgraph.graph import StateGraph, START, END
from core.state import AgentState
from agents.mentor import mentoring_node
from agents.debugger import debugging_node
from agents.assessor import assessment_node

def route_after_mentor(state: AgentState):
    student_code = state.get("student_code", "").strip()
    if not student_code:
        return END 
    return "debugger"

workflow = StateGraph(AgentState)

workflow.add_node("mentor", mentoring_node)
workflow.add_node("debugger", debugging_node)
workflow.add_node("assessor", assessment_node)

workflow.add_edge(START, "mentor") 

workflow.add_conditional_edges(
    "mentor",
    route_after_mentor,
    {
        "debugger": "debugger",
        END: END
    }
)

workflow.add_edge("debugger", "assessor")

def route_after_assessment(state: AgentState):
    if state["is_correct"]:
        return END 
    else:
        return "mentor" 

workflow.add_conditional_edges(
    "assessor",
    route_after_assessment,
    {
        END: END,
        "mentor": "mentor"
    }
)

app = workflow.compile()
print("--- Το Agentic Graph είναι έτοιμο με ασφάλεια! ---")