from langchain_groq import ChatGroq
from dotenv import load_dotenv
load_dotenv() 

llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0) 

def debugging_node(state):
    """
    Αναλύει τον κώδικα του φοιτητή και εντοπίζει τεχνικά λάθη.
    """
    student_code = state.get("student_code", "")
    
    prompt = (
        f"Ανάλυσε τον παρακάτω κώδικα Python για συντακτικά ή λογικά λάθη:\n\n"
        f"{student_code}\n\n"
        "Εξήγησε το λάθος σύντομα και τεχνικά. ΜΗΝ δώσεις τη σωστή λύση."
    )
    
    response = llm.invoke(prompt)
    
    return {"debug_report": response.content}