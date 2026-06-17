from core.app import app
from langchain_core.messages import HumanMessage

def test_logic():

    state = {
        # ── Μηνύματα ──────────────────────────────────────────────────────────
        "messages": [HumanMessage(content="Γεια σου! Είμαι έτοιμη για το πρώτο task.")],

        # ── Κώδικας & Debug ───────────────────────────────────────────────────
        "student_code": "mpla = 'milo' ; print(milo)",  # Επίτηδες λάθος
        "debug_report": "",

        # ── Αξιολόγηση ────────────────────────────────────────────────────────
        "is_correct": False,
        "assessment_feedback": "",
        "assessment_score": 0,
        "assessment_decision": "repeat",

        # ── Μάθημα & Άσκηση ───────────────────────────────────────────────────
        "current_lesson": "Variables & Data Types",
        "current_lesson_id": 1,
        "current_task": "Δημιούργησε μεταβλητή age με τιμή 25 και μεταβλητή first_name ως string. Τύπωνε και τις δύο με print().",
        "success_criteria": [
            "Υπάρχει ανάθεση τιμής με το σύμβολο = σε μεταβλητή.",
            "Το string αποθηκεύεται με σωστά εισαγωγικά.",
            "Ο αριθμητικός τύπος αποθηκεύεται χωρίς εισαγωγικά.",
            "Χρησιμοποιείται print() για εκτύπωση.",
            "Δεν υπάρχουν συντακτικά λάθη."
        ],

        # ── Προφίλ & Επίδοση ──────────────────────────────────────────────────
        "experience_level": "beginner",
        "profile_checked": True,
        "performance_summary": '{"total_attempts": 1, "avg_time_spent": 0, "frequent_error_categories": [], "recent_attempts": 1}',
        "understanding_level": "developing",

        # ── Μετρητές ──────────────────────────────────────────────────────────
        "attempts_count": 1,
        "hint_count": 0,
        "time_spent": 15.0,

        # ── Κατάσταση συνεδρίας ────────────────────────────────────────────────
        "task_started": True,
        "awaiting_questions": False,
        "event_type": "",
        "is_first_login": False,
        "difficulty_probe_direction": "",
        "avg_hints_per_task": 0.0,
    }

    print("--- Ξεκινάει ο έλεγχος του Graph ---")

    for event in app.stream(state):
        for node_name, output in event.items():
            print(f"\n >>> Είμαστε στο Node: {node_name} <<<")

            if node_name == "mentor":
                print(f"Mentor: {output['messages'][-1].content}")

            if node_name == "debugger":
                print(f"Debugger Report: {output.get('debug_report', 'No report')}")

            if node_name == "assessor":
                print(f"Assessor Decision (is_correct): {output.get('is_correct')}")
                print(f"Assessor Score: {output.get('assessment_score')}")
                print(f"Assessor Decision: {output.get('assessment_decision')}")

                if not output.get('is_correct'):
                    print("\n[INFO]: Ο Assessor βρήκε λάθος. Το τεστ ολοκληρώθηκε επιτυχώς!")
                    return

if __name__ == "__main__":
    test_logic()
