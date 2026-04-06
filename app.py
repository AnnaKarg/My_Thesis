from langgraph.graph import StateGraph, START, END
from state import AgentState
from agents.mentor import mentoring_node
from agents.debugger import debugging_node
from agents.assessor import assessment_node

# 1. Αρχικοποίηση του Γραφήματος με το State που ορίσαμε
workflow = StateGraph(AgentState)

# 2. Προσθήκη των Κόμβων (Nodes)
workflow.add_node("mentor", mentoring_node)
workflow.add_node("debugger", debugging_node)
workflow.add_node("assessor", assessment_node)

# 3. Ορισμός των Ακμών (Edges) 
workflow.add_edge(START, "mentor") 

workflow.add_edge("mentor", "debugger")
workflow.add_edge("debugger", "assessor")

# 4. Απόφαση Ροής (Conditional Edge) 
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

# 5. Compile του Γραφήματος
app = workflow.compile()

print("--- Το Agentic Graph είναι έτοιμο! ---")