import json # Φορτώνει το περιεχόμενο των μαθημάτων από το αρχείο JSON
import random # Για την τυχαία επιλογή ασκήσεων
from pathlib import Path # Για να βρει το μονοπάτι του αρχείου JSON με τα μαθήματα
from langchain_groq import ChatGroq # Για την αλληλεπίδραση με το μοντέλο γλώσσας Groq
from langchain_core.prompts import ChatPromptTemplate # Για τη δημιουργία prompt για το μοντέλο γλώσσας
from langchain_core.messages import AIMessage # Για τη δημιουργία μηνυμάτων από το μοντέλο γλώσσας
from dotenv import load_dotenv # Για φόρτωση περιβαλλοντικών μεταβλητών (π.χ. API keys)

load_dotenv() # Φορτώνει τις περιβαλλοντικές μεταβλητές από το .env αρχείο (π.χ. API keys)

llm = ChatGroq( # Αρχικοποιεί το LLM
    model_name="llama-3.1-8b-instant",
    temperature=0.1 # Χαμηλή θερμοκρασία για πιο συνεπείς απαντήσεις
)

LESSONS_PATH = Path(__file__).resolve().parents[1] / "content" / "lessons.json"

with open(LESSONS_PATH, "r", encoding="utf-8") as f: # Φορτώνει το περιεχόμενο των μαθημάτων από το JSON αρχείο
    lessons_content = json.load(f)

def pick_lesson(state): # Επιλέγει το τρέχον μάθημα βάσει του state ή επιστρέφει το πρώτο μάθημα ως προεπιλογή
    lessons = lessons_content.get("lessons", [])
    if not lessons:
        return {
            "id": 1,
            "title": "Python Basics",
            "detailed_theory": "",
            "task_templates": {"easy": ["Γράψε ένα απλό πρόγραμμα Python."]},
            "possible_values": {},
            "success_criteria": []
        }
    lesson_id = state.get("current_lesson_id", 1)
    return next((l for l in lessons if l["id"] == lesson_id), lessons[0])

def generate_random_task(lesson, difficulty): 
    templates_dict = lesson.get("task_templates", {}) # Λεξικό με templates για κάθε επίπεδο δυσκολίας
    templates = templates_dict.get(difficulty, templates_dict.get("easy", [])) # Επιλογή λίστας templates βάσει δυσκολίας (easy/hard)
    
    if not templates:
        return "Γράψε ένα απλό πρόγραμμα Python."

    template = random.choice(templates) # Επιλέγει τυχαία ένα template από τη λίστα
    values = lesson.get("possible_values", {}) # Λεξικό με πιθανές τιμές για τα placeholders στα templates

    for key, options in values.items(): 
        if "{" + key + "}" in template and options:
            template = template.replace(
                "{" + key + "}",
                str(random.choice(options))
            )
    return template

def _is_question_message(text: str) -> bool:
    normalized = (text or "").strip().lower()
    question_markers = ["?", "γιατι", "γιατί", "πως", "πώς", "τι σημαίνει", "τι σημαινει", "δεν καταλαβα", "δεν καταλαβαίνω", "απορια", "απορία"]
    return any(marker in normalized for marker in question_markers)

def _wants_to_start_task(text: str) -> bool:
    normalized = (text or "").strip().lower()
    phrases = [
        "δεν έχω απορία", "δεν εχω απορια", "δεν έχω απορίες", "δεν εχω αποριες",
        "προχώρα", "προχωρα", "προχωράμε", "προχωραμε", "πάμε", "παμε",
        "συνέχισε", "συνεχισε"
    ]
    return any(phrase in normalized for phrase in phrases)

def mentoring_node(state): # Κύρια συνάρτηση που διαχειρίζεται τη λογική του Mentor βάσει του τρέχοντος state
    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else ""
    
    is_first_login = state.get("is_first_login", False)
    profile_checked = state.get("profile_checked", False)
    awaiting_questions = state.get("awaiting_questions", False)
    wants_task = _wants_to_start_task(user_input)
    task_started = state.get("task_started", False)
    is_correct = state.get("is_correct", False)
    debug_report = state.get("debug_report", "")
    experience = state.get("experience_level", "beginner")
    attempts = state.get("attempts_count", 0)
    
    # Αυτόματη προσαρμογή δυσκολίας
    if attempts >= 3:
        difficulty = "easy"
    else:
        difficulty = "hard" if experience == "advanced" else "easy"
    
    lesson = pick_lesson(state)
    theory = lesson.get("detailed_theory", "")
    task = generate_random_task(lesson, difficulty)
    success_criteria = state.get("success_criteria", lesson.get("success_criteria", []))

    if isinstance(success_criteria, list):
        success_criteria_text = "\n".join([f"- {c}" for c in success_criteria]) if success_criteria else "- Σωστή λύση της άσκησης."
    else:
        success_criteria_text = f"- {success_criteria}" if success_criteria else "- Σωστή λύση της άσκησης."

    # Προσαρμογή ύφους επεξήγησης
    tone = "εξήγησε πολύ απλά με παραδείγματα" if difficulty == "easy" else "χρησιμοποίησε τεχνική ορολογία"

    current_context = ""
    if is_first_login and not profile_checked:
        current_context = "Ο μαθητής συνδέεται για πρώτη φορά. Συστήσου και κάνε profile check για να δούμε αν είναι αρχάριος ή προχωρημένος."
    elif is_correct:
        current_context = f"Ο μαθητής έλυσε σωστά την άσκηση. Συγχάρηκε τον και ρώτα αν θέλει την επόμενη ενότητα: {lesson.get('title')}."
    elif wants_task:
        current_context = f"Ο μαθητής είπε ότι δεν έχει άλλες απορίες. Δώσε αμέσως την άσκηση για την ενότητα {lesson.get('title')} και ζήτησέ του να ξεκινήσει."
    elif _is_question_message(user_input):
        current_context = f"Ο μαθητής έκανε απορία πάνω στη θεωρία της ενότητας {lesson.get('title')}. Απάντησε μόνο στην απορία, σύντομα και καθαρά. ΜΗΝ ξαναπείς όλη τη θεωρία και ΜΗΝ δώσεις άσκηση."
    elif awaiting_questions:
        current_context = f"Έχεις μόλις εξηγήσει τη θεωρία της ενότητας {lesson.get('title')}. Περίμενε απορίες από τον μαθητή ή απάντησέ τες σύντομα. ΜΗΝ δώσεις ακόμα άσκηση μέχρι να πει ότι είναι έτοιμος."
    elif task_started and not is_correct:
        current_context = f"Ο μαθητής δουλεύει στην άσκηση (Επίπεδο: {difficulty}) αλλά έχει λάθη. Debug Report: {debug_report}. Δώσε ένα hint κατάλληλο για το επίπεδό του ({tone})."
    else:
        current_context = f"Βρισκόμαστε στην ενότητα {lesson.get('title')}. Παρέδωσε τη θεωρία: {theory}. Στο τέλος ρώτα μόνο αν έχει απορίες. ΜΗΝ πεις 'ποια είναι η επόμενη κίνηση σου;'. Χρησιμοποίησε ύφος: {tone}."

    system_prompt = f""" 
    Είσαι ο Mentor, ένας έμπειρος καθηγητής Python. 
    
    ΤΩΡΙΝΗ ΚΑΤΑΣΤΑΣΗ ΜΑΘΗΜΑΤΟΣ: 
    {current_context}
    ΕΠΙΠΕΔΟ ΔΥΣΚΟΛΙΑΣ: {difficulty}

    ΚΡΙΤΗΡΙΑ ΕΠΙΤΥΧΙΑΣ ΑΣΚΗΣΗΣ:
    {success_criteria_text}
    
    ΑΝ ΠΡΕΠΕΙ ΝΑ ΔΩΣΕΙΣ ΑΣΚΗΣΗ, ΧΡΗΣΙΜΟΠΟΙΗΣΕ ΑΥΤΗ ({difficulty}): {task}
    
    ΚΑΝΟΝΕΣ:
    - Μίλα φιλικά στα Ελληνικά.
    - ΜΗΝ δίνεις έτοιμο κώδικα.
    - Όταν ο μαθητής έχει λάθος, δώσε μόνο 1-2 σύντομα hints και όχι πλήρη λύση.
    - Μην εξηγείς αναλυτικά τον τύπο της διόρθωσης ούτε δίνεις παραδείγματα κώδικα.
    - Μετά τη θεωρία ρώτα μόνο αν έχει απορίες. Μην ρωτάς γενικά τι θα κάνει μετά.
    - Αν ο μαθητής κάνει απορία, απάντησέ την χωρίς να ξαναπείς όλη τη θεωρία.
    - Όταν ο μαθητής πει ότι δεν έχει απορίες, δώσε αμέσως άσκηση.
    - Προσάρμοσε την επεξηγηματικότητά σου στο επίπεδο: {difficulty}.
    - Αν δώσεις άσκηση, βάλε το tag [BUTTON:START_TASK].
    """

    prompt = ChatPromptTemplate.from_messages([ 
        ("system", system_prompt),
        ("human", "{user_input}")
    ])

    chain = prompt | llm 

    try: 
        response = chain.invoke({"user_input": user_input})
        generated_content = response.content.strip()

        if is_first_login and not profile_checked:
            content = (
                "Καλώς ήρθες! Είμαι εδώ για να σε βοηθήσω να μάθεις Python.\n\n"
                "Πριν ξεκινήσουμε, έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
            )
        elif is_correct:
            content = (
                f"Μπράβο, η λύση σου είναι σωστή!\n\n"
                f"Θες να συνεχίσουμε με την επόμενη ενότητα: {lesson.get('title')};"
            )
        elif wants_task:
            content = f"Τέλεια, πάμε στην άσκηση της ενότητας {lesson.get('title')}:\n\n{task}\n\n[BUTTON:START_TASK]"
        elif _is_question_message(user_input):
            content = generated_content
            if "[BUTTON:START_TASK]" in content:
                content = content.replace("[BUTTON:START_TASK]", "").strip()
        elif awaiting_questions or (profile_checked and not task_started and not wants_task):
            content = (
                f"{theory}\n\n"
                "Έχεις κάποια απορία; Αν όχι, γράψε 'προχωράμε'."
            )
        elif task_started and not is_correct:
            content = generated_content
            if "[BUTTON:START_TASK]" in content:
                content = content.replace("[BUTTON:START_TASK]", "").strip()
        else:
            content = f"{theory}\n\nΈχεις κάποια απορία;"

        if wants_task and "[BUTTON:START_TASK]" not in content:
            content += "\n\n[BUTTON:START_TASK]"

        return {"messages": [AIMessage(content=content)]}
    except Exception:
        return {"messages": [AIMessage(content="Κάτι με δυσκόλεψε, μπορείς να ξαναδοκιμάσεις;")]}