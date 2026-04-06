from core.app import app
from langchain_core.messages import HumanMessage

def test_logic():

    state = {
        "messages": [HumanMessage(content="Γεια σου! Είμαι έτοιμη για το πρώτο task.")],
        "student_code": "mpla = 'milo' ; print(milo)", # Επίτηδες λάθος
        "debug_report": "",
        "is_correct": False,
        "current_lesson": "Variables"
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

                if not output.get('is_correct'):
                    print("\n[INFO]: Ο Assessor βρήκε λάθος. Το τεστ ολοκληρώθηκε επιτυχώς!")
                    return 

if __name__ == "__main__":
    test_logic()