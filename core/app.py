from langgraph.graph import StateGraph, START # Κλάση που ορίζει τη ροή του προγράμματος με βάση την κατάσταση του πράκτορα
from core.state import AgentState # Κλάση που ορίζει την κατάσταση του πράκτορα
from agents.mentor import mentoring_node # Κύρια συνάρτηση που διαχειρίζεται τη λογική του Mentor βάσει του τρέχοντος state
from agents.debugger import debugging_node # Κύρια συνάρτηση που διαχειρίζεται τη λογική του Debugger βάσει του τρέχοντος state
from agents.assessor import assessment_node # Κύρια συνάρτηση που διαχειρίζεται τη λογική του Assessor βάσει του τρέχοντος state


def input_router(state: AgentState): # Συνάρτηση που καθορίζει ποιον κόμβο θα επισκεφθεί ο πράκτορας με βάση την τρέχουσα κατάσταση
    messages = state.get("messages", [])
    student_code = state.get("student_code", "").strip()

    if not messages:
        return "mentor"

    if student_code:
        return "debugger"

    return "mentor"


workflow = StateGraph(AgentState) # Δημιουργία ενός γράφου κατάστασης που θα διαχειρίζεται την κατάσταση του πράκτορα και τη ροή του προγράμματος

workflow.add_node("mentor", mentoring_node) # Προσθήκη του κόμβου "mentor" στον γράφο
workflow.add_node("debugger", debugging_node)# Προσθήκη του κόμβου "debugger" στον γράφο
workflow.add_node("assessor", assessment_node) # Προσθήκη του κόμβου "assessor" στον γράφο

workflow.add_conditional_edges(START, input_router) # Προσθήκη ακμών που καθορίζουν τη ροή του προγράμματος

workflow.add_edge("debugger", "assessor") # Προσθήκη ακμής που καθορίζει ότι μετά τον κόμβο "debugger" θα ακολουθεί ο κόμβος "assessor"
workflow.add_edge("assessor", "mentor") # Προσθήκη ακμής που καθορίζει ότι μετά τον κόμβο "assessor" θα ακολουθεί ο κόμβος "mentor"

app = workflow.compile() 