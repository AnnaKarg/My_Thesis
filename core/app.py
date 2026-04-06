from langgraph.graph import StateGraph, START, END
from core.state import AgentState
from agents.mentor import mentoring_node
from agents.debugger import debugging_node
from agents.assessor import assessment_node

def route_after_mentor(state: AgentState):

    user_msg = state["messages"][-1].content.lower()
    student_code = state.get("student_code", "").strip()

    exit_words = ["επόμενο", "τέλος", "όχι", "προχώρα", "έτοιμη", "έτοιμος"]
    if any(word in user_msg for word in exit_words):
        return END

    if student_code:
        return "debugger"
    
    return END

def route_after_assessment(state: AgentState):

    return "mentor"

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

workflow.add_conditional_edges(
    "assessor",
    route_after_assessment,
    {
        "mentor": "mentor"
    }
)

app = workflow.compile()
print("--- Το Agentic Graph αναβαθμίστηκε με Feedback Loop! ---")