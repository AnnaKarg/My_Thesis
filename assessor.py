from langchain_groq import ChatGroq

llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0)

def assessment_node(state):
    """
    Αξιολογεί την πρόοδο του φοιτητή με βάση την τεχνική αναφορά του Debugger.
    """
    debug_report = state.get("debug_report", "")
    
    prompt = (
        "Είσαι ο Assessment Agent. Η δουλειά σου είναι να διαβάσεις την τεχνική αναφορά "
        "ενός Debugger και να αποφασίσεις αν ο κώδικας του φοιτητή είναι σωστός.\n\n"
        f"Τεχνική Αναφορά: {debug_report}\n\n"
        "Απάντησε ΑΠΟΚΛΕΙΣΤΙΚΑ με 'PASS' αν ο κώδικας είναι σωστός ή 'FAIL' αν υπάρχουν λάθη."
    )
    
    response = llm.invoke(prompt)
    decision = response.content.strip().upper()
    
    return {"is_correct": "PASS" in decision}