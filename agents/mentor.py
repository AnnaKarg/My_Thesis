import json # Φορτώνει το περιεχόμενο των μαθημάτων από το αρχείο JSON
import random # Για την τυχαία επιλογή ασκήσεων
import re # Για καθαρισμό εσωτερικών debug tags από τα μηνύματα
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

def _is_question_message(text: str) -> bool:
    normalized = (text or "").strip().lower()
    question_markers = [
        "?", "γιατι", "γιατί", "πως", "πώς",
        "τι ειναι", "τι είναι", "τι εννοεις", "τι εννοείς",
        "τι σημαίνει", "τι σημαινει",
        "εξηγε", "εξήγε", "εξήγησε", "εξηγησε",
        "δεν καταλαβα", "δεν καταλαβαίνω",
        "απορια", "απορία", "δεν ξερω", "δεν ξέρω",
        "παραδειγμα", "παράδειγμα", "δωσε μου", "δώσε μου",
        "δείξε μου", "δειξε μου", "μπορεις να εξηγησεις", "μπορείς να εξηγήσεις"
    ]
    return any(marker in normalized for marker in question_markers)

def _wants_to_start_task(text: str) -> bool:
    normalized = (text or "").strip().lower()
    phrases = [
        "δεν έχω απορία", "δεν εχω απορια", "δεν έχω απορίες", "δεν εχω αποριες",
        "προχώρα", "προχωρα", "προχωράμε", "προχωραμε", "πάμε", "παμε",
        "συνέχισε", "συνεχισε",
        "άλλη άσκηση", "αλλη ασκηση", "άλλη μια άσκηση", "αλλη μια ασκηση",
        "επιπλέον άσκηση", "επιπλεον ασκηση", "ακόμα μια άσκηση", "ακομα μια ασκηση",
        "δώσε άσκηση", "δωσε ασκηση", "θέλω άσκηση", "θελω ασκηση",
        "ας επαναλάβουμε", "ας επαναλαβουμε", "επαναλάβουμε", "επαναλαβουμε",
        "ξανά την άσκηση", "ξανα την ασκηση", "πάλι", "παλι",
        "επανάληψη", "επαναληψη", "δοκιμάσω ξανά", "δοκιμασω ξανα",
        "proxvrame", "proxwrame", "prochvrame", "proksorame"
    ]
    return any(phrase in normalized for phrase in phrases)


def _generate_targeted_hint(debug_report: str, difficulty: str, assessment_feedback: str = "") -> str:
    """Μετατρέπει το τεχνικό debug_report σε κατανοητό hint για τον χρήστη."""
    report = debug_report or ""

    if "[DEBUG: ERROR]" in report:
        error_part = report.replace("[DEBUG: ERROR]", "").strip().rstrip(".")
        if "expected ':'" in error_part:
            return "Πρόσεξε τη σύνταξη: μετά τη συνθήκη if/for/while χρειάζεται άνω-κάτω τελεία (:) στο τέλος της γραμμής."
        elif "invalid syntax" in error_part:
            line_info = error_part.split("γραμμή")[-1].strip() if "γραμμή" in error_part else ""
            return f"Συντακτικό λάθος{'στη γραμμή ' + line_info if line_info else ''}. Έλεγξε τη σύνταξη: παρενθέσεις, εισαγωγικά και άνω-κάτω τελείες."
        elif "EOL" in error_part or "EOF" in error_part:
            return "Φαίνεται ότι έχεις ανοιχτό εισαγωγικό ή παρένθεση που δεν έχει κλείσει."
        else:
            return f"Συντακτικό λάθος: {error_part}. Διόρθωσε τη γραμμή που αναφέρεται."

    if "undefined_name" in report:
        for line in report.splitlines():
            if "Χρήση μεταβλητής πριν από ανάθεση" in line:
                vars_part = line.split(":")[-1].strip()
                return f"Χρησιμοποιείς μεταβλητή ({vars_part}) που δεν έχεις ορίσει ακόμα. Ανάθεσέ της πρώτα μια τιμή."
        return "Χρησιμοποιείς μεταβλητή που δεν έχεις ορίσει. Έλεγξε τα ονόματα στον κώδικά σου."

    if "type_mismatch" in report:
        return "Κάποιες αριθμητικές τιμές έχουν μπει σε εισαγωγικά. Αριθμοί (int/float) δεν χρειάζονται εισαγωγικά."

    if "missing_if" in report:
        return "Λείπει η δομή if. Θυμήσου: if <συνθήκη>: → <εντολή με εσοχή>."

    if "missing_for" in report:
        return "Λείπει το for loop. Θυμήσου: for <μεταβλητή> in <λίστα>: → <εντολή με εσοχή>."

    if "missing_function" in report:
        return "Λείπει ο ορισμός συνάρτησης. Θυμήσου: def <όνομα>(<παράμετροι>): → <εντολές με εσοχή>."

    if "missing_append" in report:
        return "Λείπει η χρήση .append(). Πρόσθεσέ την για να προσθέσεις στοιχείο στη λίστα."

    if "missing_list" in report:
        return "Λείπει η δημιουργία λίστας ([]). Ορίσ' τη πρώτα ως κενή λίστα ή με τιμές."

    if "missing_output" in report:
        return "Λείπει η εντολή print(). Πρόσθεσέ την για να εμφανίσεις το αποτέλεσμα."

    # Ο κώδικας είναι συντακτικά σωστός αλλά δεν πληροί τα κριτήρια —
    # χρησιμοποιούμε το assessment_feedback για στοχευμένη καθοδήγηση.
    clean_fb = _clean_feedback(assessment_feedback)

    if clean_fb and "Κριτήρια που δεν ικανοποιήθηκαν" in clean_fb:
        failed_part = clean_fb.replace("Κριτήρια που δεν ικανοποιήθηκαν:", "").strip()
        return f"Ο κώδικάς σου δεν καλύπτει ακόμα όλα τα ζητούμενα. Έλεγξε αν υλοποιείς: {failed_part}"

    if clean_fb and clean_fb not in ("Ο κώδικας χρειάζεται διόρθωση βάσει τεχνικού report.", "Απαιτείται επιπλέον εξάσκηση."):
        return f"Ο κώδικάς σου είναι συντακτικά σωστός αλλά δεν πληροί όλα τα κριτήρια. {clean_fb}"

    return "Ο κώδικάς σου είναι συντακτικά σωστός, αλλά δεν καλύπτει όλα τα ζητούμενα της εκφώνησης. Ξαναδιάβασε την εκφώνηση και έλεγξε αν έχεις υλοποιήσει κάθε μέρος της."

def _clean_feedback(feedback: str) -> str:
    """Αφαιρεί εσωτερικά debug tags (π.χ. [TYPE_ERROR], [STRICT_MATCH_FAIL]) από το assessment feedback."""
    cleaned = re.sub(r'\[[A-Z_:]+\]\s*', '', feedback or '').strip()
    return cleaned


def _extract_last_assessment_decision(messages) -> str:
    for msg in reversed(messages):
        content = getattr(msg, "content", "") or ""
        if "[ASSESSMENT:ADVANCE]" in content:
            return "advance"
        if "[ASSESSMENT:REPEAT]" in content:
            return "repeat"
        if "[ASSESSMENT:SUPPORT]" in content:
            return "support"
    return ""

def _chapter_header(lesson):
    lesson_id = lesson.get("id", "?")
    lesson_title = lesson.get("title", "Ενότητα")
    return f"Κεφάλαιο {lesson_id}: {lesson_title}"

def _resolve_placeholders(text: str, replacements: dict) -> str:
    resolved_text = text or ""
    for key, value in replacements.items():
        resolved_text = resolved_text.replace("{" + key + "}", str(value))
    return resolved_text

def generate_random_task(lesson, difficulty):
    templates_dict = lesson.get("task_templates", {})
    templates = templates_dict.get(difficulty, templates_dict.get("easy", []))

    if not templates:
        return {
            "task_text": "Γράψε ένα απλό πρόγραμμα Python.",
            "rendered_criteria": lesson.get("success_criteria", []),
        }

    template = random.choice(templates)
    possible_values = lesson.get("possible_values", {})
    replacements = {}

    for key, options in possible_values.items():
        if "{" + key + "}" in template and options:
            replacements[key] = random.choice(options)

    task_text = _resolve_placeholders(template, replacements)

    raw_criteria = lesson.get("success_criteria", [])
    if isinstance(raw_criteria, list):
        resolved_criteria = [_resolve_placeholders(str(criteria), replacements) for criteria in raw_criteria]
    elif isinstance(raw_criteria, str):
        resolved_criteria = _resolve_placeholders(raw_criteria, replacements)
    else:
        resolved_criteria = raw_criteria

    return {
        "task_text": task_text,
        "rendered_criteria": resolved_criteria,
    }

def mentoring_node(state): # Κύρια συνάρτηση που διαχειρίζεται τη λογική του Mentor βάσει του τρέχοντος state
    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else ""
    
    is_first_login = state.get("is_first_login", False)
    profile_checked = state.get("profile_checked", False)
    awaiting_questions = state.get("awaiting_questions", False)
    event_type = state.get("event_type", "")
    wants_task = _wants_to_start_task(user_input)
    next_chapter_request = any(token in (user_input or "").lower() for token in ["επόμενο", "επομενο", "next", "προχωράμε", "προχωραμε"])
    # Ανίχνευση επιλογής από το menu υποστήριξης (1/2/3)
    menu_choice = None
    if (user_input or "").strip() in {"1", "2", "3"}:
        menu_choice = (user_input or "").strip()
    task_started = state.get("task_started", False)
    is_correct = state.get("is_correct", False)
    debug_report = state.get("debug_report", "")
    assessment_decision = state.get("assessment_decision", "")
    assessment_feedback = state.get("assessment_feedback", "")
    performance_summary = state.get("performance_summary", "{}")
    last_assessment_decision = _extract_last_assessment_decision(messages)
    experience = state.get("experience_level", "beginner")
    attempts = state.get("attempts_count", 0)
    
    # Αυτόματη προσαρμογή δυσκολίας
    if attempts >= 3:
        difficulty = "easy"
    else:
        difficulty = "hard" if experience == "expert" else "easy"
    
    lesson = pick_lesson(state)
    chapter_header = _chapter_header(lesson)
    theory = lesson.get("detailed_theory", "")

    # Τίτλος επόμενης ενότητας (για το μήνυμα επιτυχίας)
    all_lessons = lessons_content.get("lessons", [])
    current_lesson_id = state.get("current_lesson_id", 1)
    next_lesson_obj = next((l for l in all_lessons if l["id"] == current_lesson_id + 1), None)
    next_lesson_title = next_lesson_obj.get("title", "επόμενη ενότητα") if next_lesson_obj else "επόμενη ενότητα"
    generated_task = state.get("current_task")
    generated_criteria = state.get("success_criteria")

    if not generated_task or generated_criteria is None:
        task_payload = generate_random_task(lesson, difficulty)
        generated_task = task_payload["task_text"]
        generated_criteria = task_payload["rendered_criteria"]

    task = generated_task
    success_criteria = generated_criteria

    if isinstance(success_criteria, list):
        success_criteria_text = "\n".join([f"- {c}" for c in success_criteria]) if success_criteria else "- Σωστή λύση της άσκησης."
    else:
        success_criteria_text = f"- {success_criteria}" if success_criteria else "- Σωστή λύση της άσκησης."

    # Προσαρμογή ύφους επεξήγησης
    tone = "εξήγησε πολύ απλά με παραδείγματα" if difficulty == "easy" else "χρησιμοποίησε τεχνική ορολογία"

    current_context = ""
    if is_first_login and not profile_checked:
        current_context = "Ο μαθητής συνδέεται για πρώτη φορά. Συστήσου και κάνε profile check για να δούμε αν είναι αρχάριος ή προχωρημένος."
    elif event_type == "no_submission_timeout":
        if difficulty == "easy":
            current_context = "Ο μαθητής δεν υπέβαλε κώδικα για 40+ δευτερόλεπτα. Δώσε 1 σύντομο παιδαγωγικό hint χωρίς λύση."
        else:
            current_context = f"Ο μαθητής δουλεύει στην άσκηση της ενότητας {lesson.get('title')}. Υπενθύμισέ του σύντομα την εκφώνηση χωρίς να δώσεις hint."
    elif menu_choice == "1":
        current_context = f"Ο μαθητής επέλεξε επανάληψη θεωρίας. Παρουσίασε ξανά τη θεωρία της ενότητας {lesson.get('title')} σύντομα."
    elif menu_choice == "2":
        current_context = f"Ο μαθητής επέλεξε νέα άσκηση για την ενότητα {lesson.get('title')}."
    elif menu_choice == "3":
        current_context = f"Ο μαθητής ζητά hints. Debug Report: {debug_report}. Δώσε στοχευμένο hint."
    elif next_chapter_request and task_started and last_assessment_decision in {"repeat", "support"}:
        current_context = "Ο μαθητής ζητά να προχωρήσει, αλλά η τελευταία αξιολόγηση δείχνει ότι χρειάζεται επανάληψη/υποστήριξη. Εξήγησε ευγενικά γιατί και πρότεινε επιλογές."
    elif is_correct:
        current_context = f"Ο μαθητής έλυσε σωστά την άσκηση. Συγχάρηκε τον και ρώτα αν θέλει την επόμενη ενότητα: {lesson.get('title')}."
    elif wants_task:
        current_context = f"Ο μαθητής είπε ότι δεν έχει άλλες απορίες. Δώσε αμέσως την άσκηση για την ενότητα {lesson.get('title')} και ζήτησέ του να ξεκινήσει."
    elif _is_question_message(user_input):
        if task_started:
            current_context = (
                f"Ο μαθητής δουλεύει στην άσκηση της ενότητας {lesson.get('title')} και δεν καταλαβαίνει το λάθος του. "
                f"Debug Report: {debug_report}. "
                f"Εξήγησε σύντομα τι πήγε στραβά χωρίς να δώσεις λύση. Ύφος: {tone}."
            )
        else:
            current_context = f"Ο μαθητής έκανε απορία πάνω στη θεωρία της ενότητας {lesson.get('title')}. Απάντησε μόνο στην απορία, σύντομα και καθαρά. ΜΗΝ ξαναπείς όλη τη θεωρία και ΜΗΝ δώσεις άσκηση."
    elif awaiting_questions:
        current_context = f"Έχεις μόλις εξηγήσει τη θεωρία της ενότητας {lesson.get('title')}. Περίμενε απορίες από τον μαθητή ή απάντησέ τες σύντομα. ΜΗΝ δώσεις ακόμα άσκηση μέχρι να πει ότι είναι έτοιμος."
    elif task_started and not is_correct:
        current_context = f"Ο μαθητής δουλεύει στην άσκηση (Επίπεδο: {difficulty}) αλλά έχει λάθη. Debug Report: {debug_report}. Δώσε ένα hint κατάλληλο για το επίπεδό του ({tone})."
    else:
        current_context = f"Βρισκόμαστε στην ενότητα {lesson.get('title')}. Παρέδωσε τη θεωρία: {theory}. Στο τέλος ρώτα μόνο αν έχει απορίες. ΜΗΝ πεις 'ποια είναι η επόμενη κίνηση σου;'. Χρησιμοποίησε ύφος: {tone}."

    deterministic_content = None
    if is_first_login and not profile_checked:
        deterministic_content = (
            "Καλώς ήρθες! Είμαι εδώ για να σε βοηθήσω να μάθεις Python.\n\n"
            "Πριν ξεκινήσουμε, έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
        )
    elif event_type == "no_submission_timeout":
        if difficulty == "easy":
            deterministic_content = (
                "[HINT] Πάρε το ήσυχα! Ξεκίνα σπάζοντας την εκφώνηση σε μικρά βήματα και υλοποίησε πρώτα το πιο απλό κομμάτι."
            )
        # Για expert χρήστες: το LLM χειρίζεται με updated current_context (χωρίς hint)
    elif menu_choice == "1":
        deterministic_content = (
            f"Ας ξαναδούμε τη θεωρία μαζί!\n\n"
            f"{chapter_header}\n\n{theory}\n\n"
            f"Έχεις ερωτήσεις; Αλλιώς γράψε 'προχωράμε' για να δοκιμάσεις την άσκηση!"
        )
    elif menu_choice == "2":
        deterministic_content = (
            f"Τέλεια! Να μια νέα άσκηση για την ενότητα **{lesson.get('title')}**:\n\n{task}\n\n[BUTTON:START_TASK]"
        )
    elif menu_choice == "3":
        hint_text = _generate_targeted_hint(debug_report, difficulty, assessment_feedback)
        deterministic_content = (
            f"Κοίτα το λάθος πιο προσεκτικά:\n\n{hint_text}\n\nΔοκίμασε να διορθώσεις αυτό το σημείο και υποβάλε ξανά!\n\n[ASSESSMENT:SUPPORT]"
        )
    elif next_chapter_request and task_started and last_assessment_decision in {"repeat", "support"}:
        deterministic_content = (
            "Καταλαβαίνω ότι θέλεις να προχωρήσουμε, αλλά από την τελευταία αξιολόγηση φαίνεται ότι χρειάζεται λίγο ακόμη δουλειά σε αυτή την ενότητα.\n\n"
            "Μπορούμε να κάνουμε ένα από τα εξής:\n"
            "1) Σύντομη επανάληψη θεωρίας\n"
            "2) Μία επιπλέον άσκηση\n"
            "3) Στοχευμένα hints πάνω στον κώδικά σου\n\n"
            "[ASSESSMENT:SUPPORT]"
        )
    elif is_correct:
        decision_tag = "[ASSESSMENT:ADVANCE]" if assessment_decision == "advance" else "[ASSESSMENT:REPEAT]"
        clean_fb = _clean_feedback(assessment_feedback)
        feedback_line = f"\n{clean_fb}\n" if clean_fb and clean_fb != "Ικανοποιούνται επαρκώς τα ακαδημαϊκά κριτήρια." else ""
        deterministic_content = (
            f"Μπράβο, η λύση σου είναι σωστή! Πολύ καλή δουλειά!{feedback_line}\n"
            f"Θέλεις να προχωρήσουμε στην επόμενη ενότητα: **{next_lesson_title}**;\n\n"
            f"{decision_tag}"
        )
    elif wants_task:
        deterministic_content = f"Τέλεια! Να η άσκησή σου για την ενότητα **{lesson.get('title')}**:\n\n{task}\n\n[BUTTON:START_TASK]"
    elif _is_question_message(user_input):
        if task_started and debug_report and "[DEBUG: EMPTY]" not in debug_report:
            # Ερώτηση κατά τη διάρκεια άσκησης: εξήγηση βάσει debug_report χωρίς LLM
            decision_tag = "[ASSESSMENT:SUPPORT]" if assessment_decision == "support" else "[ASSESSMENT:REPEAT]"
            hint_text = _generate_targeted_hint(debug_report, difficulty, assessment_feedback)
            deterministic_content = (
                f"Κοίτα το λάθος πιο προσεκτικά:\n\n"
                f"{hint_text}\n\n"
                f"Δοκίμασε να διορθώσεις αυτό το σημείο και υποβάλε ξανά τον κώδικά σου.\n\n"
                f"{decision_tag}"
            )
        else:
            # Θεωρητική απορία: το LLM θα δώσει στοχευμένη απάντηση.
            # Το deterministic_content παραμένει None για να χρησιμοποιηθεί το LLM.
            deterministic_content = None
    elif awaiting_questions or (profile_checked and not task_started and not wants_task):
        if difficulty == "easy":
            deterministic_content = (
                f"{chapter_header}\n\n{theory}\n\n"
                "Έχεις κάποια απορία πάνω σε αυτά; Αν είσαι έτοιμος, γράψε 'προχωράμε' και πάμε στην άσκηση!"
            )
        else:
            deterministic_content = (
                f"{chapter_header}\n\n{theory}\n\n"
                "Έχεις ερωτήσεις ή είσαι έτοιμος να δοκιμάσεις; Γράψε 'προχωράμε' για να ξεκινήσουμε!"
            )
    elif task_started and not is_correct:
        decision_tag = "[ASSESSMENT:SUPPORT]" if assessment_decision == "support" else "[ASSESSMENT:REPEAT]"
        hint_text = _generate_targeted_hint(debug_report, difficulty, assessment_feedback)
        deterministic_content = (
            f"[HINT] {hint_text}\n\n"
            f"{decision_tag}"
        )
    else:
        deterministic_content = (
            f"{chapter_header}\n\n{theory}\n\n"
            "Έχεις κάποια απορία; Αν είσαι έτοιμος, γράψε 'προχωράμε'!"
        )

    if deterministic_content is not None and not _is_question_message(user_input):
        if wants_task and "[BUTTON:START_TASK]" not in deterministic_content:
            deterministic_content += "\n\n[BUTTON:START_TASK]"
        return {
            "messages": [AIMessage(content=deterministic_content)],
            "current_task": task,
            "success_criteria": success_criteria,
        }

    system_prompt = f""" 
    Είσαι ο Mentor, ένας έμπειρος καθηγητής Python. 
    Ακολουθείς την τελική παιδαγωγική οδηγία του Assessment Agent και δεν προωθείς τον μαθητή αν η αξιολόγηση λέει repeat/support.
    
    ΤΩΡΙΝΗ ΚΑΤΑΣΤΑΣΗ ΜΑΘΗΜΑΤΟΣ: 
    {current_context}
    ΕΠΙΠΕΔΟ ΔΥΣΚΟΛΙΑΣ: {difficulty}
    ΙΣΤΟΡΙΚΗ ΣΥΝΟΨΗ ΜΑΘΗΤΗ: {performance_summary}

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
        if _is_question_message(user_input):
            content = generated_content
            if "[BUTTON:START_TASK]" in content:
                content = content.replace("[BUTTON:START_TASK]", "").strip()
        else:
            content = generated_content

        if wants_task and "[BUTTON:START_TASK]" not in content:
            content += "\n\n[BUTTON:START_TASK]"

        return {
            "messages": [AIMessage(content=content)],
            "current_task": task,
            "success_criteria": success_criteria,
        }
    except Exception:
        # Αν η ερώτηση είναι θεωρητική, επιστρέφουμε τη θεωρία αντί για γενικό σφάλμα
        if _is_question_message(user_input) and not (task_started and debug_report and "[DEBUG: EMPTY]" not in debug_report):
            fallback_content = (
                f"Καλή ερώτηση! Ας ξαναδούμε τη θεωρία μαζί:\n\n"
                f"{theory}\n\n"
                f"Αν κάτι εξακολουθεί να μην είναι ξεκάθαρο, ρώτα πιο συγκεκριμένα και θα σε βοηθήσω. "
                f"Αλλιώς, γράψε 'προχωράμε' για να δούμε μια άσκηση!"
            )
        else:
            fallback_content = "Κάτι με δυσκόλεψε, μπορείς να ξαναδοκιμάσεις;"
        return {
            "messages": [AIMessage(content=fallback_content)],
            "current_task": task,
            "success_criteria": success_criteria,
        }