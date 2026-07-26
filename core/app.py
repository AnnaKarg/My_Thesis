from langgraph.graph import StateGraph, START
from core.state import AgentState
from agents.mentor import mentoring_node
from agents.debugger import debugging_node
from agents.assessor import assessment_node


def input_router(state: AgentState):
    messages = state.get("messages", [])
    student_code = state.get("student_code", "").strip()

    if not messages:
        return "mentor"

    if student_code:
        return "debugger"

    return "mentor"


def debugger_router(state: AgentState):
    if state.get("free_check_mode"):
        return "mentor"
    return "assessor"


workflow = StateGraph(AgentState)

workflow.add_node("mentor", mentoring_node)
workflow.add_node("debugger", debugging_node)
workflow.add_node("assessor", assessment_node)

workflow.add_conditional_edges(START, input_router)

workflow.add_conditional_edges("debugger", debugger_router)
workflow.add_edge("assessor", "mentor")

app = workflow.compile()
