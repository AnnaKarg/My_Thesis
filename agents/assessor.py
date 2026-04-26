from langchain_groq import ChatGroq # Ο LLM που χρησιμοποιούμε για τις απαντήσεις του Assessor
from langchain_core.messages import SystemMessage, HumanMessage # Για τη δημιουργία μηνυμάτων για το LLM
import re # Για πιθανή επεξεργασία κειμένου

llm = ChatGroq( # Αρχικοποιεί το LLM
    model_name="llama-3.1-8b-instant",
    temperature=0 # Χαμηλή θερμοκρασία για πιο συνεπείς απαντήσεις
)

def assessment_node(state):# Κύρια λογική του Assessment Agent
    debug_report = state.get("debug_report", "")
    student_code = state.get("student_code", "")
    success_criteria = state.get("success_criteria", "Ο κώδικας πρέπει να είναι λειτουργικός.")
    current_lesson = state.get("current_lesson", "Python Basics")

    if "[DEBUG: ERROR]" in debug_report or "[DEBUG: EMPTY]" in debug_report:
        return {
            "is_correct": False,
            "assessment_feedback": "Needs improvement"
        }

    system_prompt = (
        "Είσαι ο Assessment Agent (Εξεταστής). \n"
        "Ο ρόλος σου είναι να συγκρίνεις τον κώδικα του φοιτητή με τα κριτήρια επιτυχίας "
        "της άσκησης και την τεχνική αναφορά του Debugger. \n\n"
        f"ΕΝΟΤΗΤΑ: {current_lesson}\n"
        f"ΚΡΙΤΗΡΙΑ ΕΠΙΤΥΧΙΑΣ: {success_criteria}\n"
        "ΚΑΝΟΝΕΣ:\n"
        "1. Αν ο κώδικας έχει συντακτικά λάθη (βάσει Debugger), το αποτέλεσμα είναι FAIL.\n"
        "2. Αν ο κώδικας τρέχει αλλά ΔΕΝ ικανοποιεί τα κριτήρια της άσκησης, το αποτέλεσμα είναι FAIL.\n"
        "3. Αν ο κώδικας είναι σωστός και ικανοποιεί τα κριτήρια, το αποτέλεσμα είναι PASS.\n\n"
        "Απάντησε ΑΠΟΚΛΕΙΣΤΙΚΑ στο τέλος με: [RESULT: PASS] ή [RESULT: FAIL]"
    )

    human_content = (
        f"ΚΩΔΙΚΑΣ ΦΟΙΤΗΤΗ:\n{student_code}\n\n"
        f"ΤΕΧΝΙΚΗ ΑΝΑΦΟΡΑ DEBUGGER:\n{debug_report}"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content)
        ])
        
        output = response.content.upper()
        match = re.search(r"\[RESULT:\s*(PASS|FAIL)\]", output)

        if match:
            is_correct = match.group(1) == "PASS"
        elif "PASS" in output and "FAIL" not in output:
            is_correct = True
        else:
            is_correct = False
        print(f"--- ASSESSOR DECISION: {'PASS' if is_correct else 'FAIL'} ---")
        
        return {
            "is_correct": is_correct,
            "assessment_feedback": "Success" if is_correct else "Needs improvement"
        }
        
    except Exception as e:
        print(f"Assessor Error: {e}")
        return {"is_correct": False}