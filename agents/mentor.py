import json
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
import os
import json

current_dir = os.path.dirname(os.path.abspath(__file__))

lessons_path = os.path.join(current_dir, "..", "content", "lessons.json")

with open(lessons_path, "r", encoding="utf-8") as f:
    lessons_content = json.load(f)

def mentoring_node(state):
    llm = ChatGroq(model_name="llama-3.1-8b-instant")
    
    current_lesson_name = state.get("current_lesson", "Variables")
    
    lesson = next((l for l in lessons_content["lessons"] if l["title"] == current_lesson_name), lessons_content["lessons"][0])

    prompt = ChatPromptTemplate.from_messages([
        ("system", """Είσαι ο Mentor, ένας έμπειρος καθηγητής Python. 
        Ο στόχος σου είναι να διδάξεις το εξής μάθημα:
        Τίτλος: {title}
        Θεωρία: {theory}
        Ασκήσεις: {tasks}
        
        ΟΔΗΓΙΕΣ:
        1. Παρουσίασε τη θεωρία και δώσε τις ασκήσεις στον φοιτητή.
        2. Αν ο Assessor βρήκε λάθη, εξήγησε το λάθος χωρίς να δώσεις τη λύση.
        3. Μίλα πάντα στα Ελληνικά."""),
        ("human", "{user_input}")
    ])
    
    user_input = state["messages"][-1].content
    
    chain = prompt | llm
 
    response = chain.invoke({
        "title": lesson["title"],
        "theory": lesson["theory"], 
        "tasks": ", ".join(lesson["tasks"]), 
        "user_input": user_input
    })
    
    return {"messages": [response]}