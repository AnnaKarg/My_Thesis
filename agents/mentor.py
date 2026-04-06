import os
import json
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

current_dir = os.path.dirname(os.path.abspath(__file__))
lessons_path = os.path.join(current_dir, "..", "content", "lessons.json")

with open(lessons_path, "r", encoding="utf-8") as f:
    lessons_content = json.load(f)
    #llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0.7) 
    #Prosorino
    llm = ChatGroq(model_name="llama-3.1-8b-instant", temperature=0.7)
def mentoring_node(state):

    
    current_lesson_name = state.get("current_lesson", "Variables")
    lesson = next((l for l in lessons_content["lessons"] if l["title"] == current_lesson_name), lessons_content["lessons"][0])

    is_correct = state.get("is_correct", False)
    debug_report = state.get("debug_report", "")

    prompt = ChatPromptTemplate.from_messages([
        ("system", """Είσαι ο Mentor, ένας έμπειρος καθηγητής Python. 
        Διδάσκεις την ενότητα: {title}
        Θεωρία: {theory}
        Ασκήσεις Ενότητας: {tasks}
        
        ΟΔΗΓΙΕΣ ΡΟΗΣ (ΠΟΛΥ ΣΗΜΑΝΤΙΚΟ):
        1. Αν ο Assessor είπε ότι ο κώδικας είναι ΣΩΣΤΟΣ (is_correct=True):
           - Συγχάρηκε τον φοιτητή.
           - Ρώτησε τον: 'Θέλεις να σου δώσω μια ακόμη άσκηση για εξάσκηση στην ίδια ενότητα ή έχεις κάποια απορία;'
           - ΜΗΝ τον πας στο επόμενο μάθημα ακόμα.
        
        2. Αν ο Assessor βρήκε ΛΑΘΗ:
           - Χρησιμοποίησε το Debug Report: {debug_report}.
           - Εξήγησε το λάθος παιδαγωγικά χωρίς να δώσεις την έτοιμη λύση.
        
        3. Αν ο φοιτητής έχει ΑΠΟΡΙΑ (με ή χωρίς κώδικα):
           - Λύσε την απορία αναλυτικά και ρώτα αν θέλει να ξαναδοκιμάσει την άσκηση.
        
        4. Αν ο φοιτητής πει 'Όχι, είμαι έτοιμος για το επόμενο':
           - Πες του ότι η ενότητα ολοκληρώθηκε και προχωράτε.

        Μίλα πάντα στα Ελληνικά με ενθαρρυντικό ύφος."""),
        ("human", "{user_input}")
    ])
    
    user_input = state["messages"][-1].content
    
    chain = prompt | llm
    
    response = chain.invoke({
        "title": lesson["title"],
        "theory": lesson["theory"], 
        "tasks": ", ".join(lesson["tasks"]), 
        "debug_report": debug_report,
        "user_input": user_input
    })
    
    return {"messages": [response]}