from langchain_groq import ChatGroq
import os

llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0.7)

def mentoring_node(state):
    """
    Διαχειρίζεται την μαθησιακή καθοδήγηση.
    """
    system_prompt = (
        "Είσαι ο Mentoring Agent, ένας έμπειρος καθηγητής Python. "
        "Καθοδηγείς τον φοιτητή στην ύλη χρησιμοποιώντας 'Micro-tasks'. "
        "Μην δίνεις ποτέ έτοιμο κώδικα. Κάνε ερωτήσεις που βοηθούν τον φοιτητή."
    )
    
    response = llm.invoke([{"role": "system", "content": system_prompt}] + state["messages"])
    
    return {"messages": [response]}