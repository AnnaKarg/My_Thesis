import ast # Για έλεγχο σύνταξης του κώδικα Python
from langchain_groq import ChatGroq # Ο LLM που χρησιμοποιούμε για τις απαντήσεις του Debugger
from langchain_core.messages import SystemMessage, HumanMessage # Για τη δημιουργία μηνυμάτων για το LLM
from dotenv import load_dotenv # Για φόρτωση περιβαλλοντικών μεταβλητών (π.χ. API keys)

load_dotenv() # Φορτώνει τις περιβαλλοντικές μεταβλητές από το .env αρχείο (π.χ. API keys)

llm = ChatGroq( # Αρχικοποιεί το LLM
    model_name="llama-3.1-8b-instant",
    temperature=0 # Χαμηλή θερμοκρασία για πιο συνεπείς απαντήσεις
)

def debugging_node(state):# Κύρια λογική του Debugger Agent
    student_code = state.get("student_code", "")
    success_criteria = state.get("success_criteria", "") 
    
    if not student_code.strip():
        return {"debug_report": "[DEBUG: EMPTY] Δεν εντοπίστηκε κώδικας προς ανάλυση."}

    try:
        ast.parse(student_code)
        syntax_status = "O κώδικας είναι συντακτικά σωστός."
    except SyntaxError as e:
        return {
            "debug_report": f"[DEBUG: ERROR] Συντακτικό λάθος στη γραμμή {e.lineno}: {e.msg}. Πιθανή έλλειψη συμβόλου ή λάθος εσοχή." 
        }

    system_prompt = (
        "Είσαι ο Debugging Agent. Ο ρόλος σου είναι να εντοπίζεις λάθη στον κώδικα Python.\n"
        "ΔΩΣΕ ΜΟΝΟ ΥΠΟΔΕΙΞΗ, ΟΧΙ ΛΥΣΗ.\n"
        "ΚΑΝΟΝΕΣ:\n"
        "1. Μην δίνεις έτοιμο κώδικα.\n"
        "2. Μην προτείνεις ακριβή γραμμή διόρθωσης (π.χ. 'άλλαξε Χ σε Υ').\n"
        "3. Δώσε το πολύ 1-2 σύντομα hints στα Ελληνικά, εστιασμένα στο λάθος.\n"
        "4. Αν όλα φαίνονται σωστά, δώσε μόνο μια πολύ σύντομη κατεύθυνση για έλεγχο, όχι ανάλυση.\n"
        "5. Μην εξηγείς θεωρία ούτε δίνεις παραδείγματα κώδικα.\n"
        f"ΚΡΙΤΗΡΙΑ ΜΑΘΗΜΑΤΟΣ: {success_criteria}"
    )

    human_content = f"ΚΩΔΙΚΑΣ ΦΟΙΤΗΤΗ:\n{student_code}\n\nΚΑΤΑΣΤΑΣΗ: {syntax_status}"

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content)
        ])
        
        return {"debug_report": f"[DEBUG: ANALYSIS] {response.content}"}
        
    except Exception as e:
        return {"debug_report": f"[DEBUG: ERROR] Αποτυχία ανάλυσης: {str(e)}"}