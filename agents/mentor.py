import json # Φορτώνει το περιεχόμενο των μαθημάτων από το αρχείο JSON
import random # Για την τυχαία επιλογή ασκήσεων
import re # Για καθαρισμό εσωτερικών debug tags από τα μηνύματα
from pathlib import Path # Για να βρει το μονοπάτι του αρχείου JSON με τα μαθήματα
from langchain_groq import ChatGroq # Για την αλληλεπίδραση με το μοντέλο γλώσσας Groq
from langchain_core.prompts import ChatPromptTemplate # Για τη δημιουργία prompt για το μοντέλο γλώσσας
from langchain_core.messages import AIMessage # Για τη δημιουργία μηνυμάτων από το μοντέλο γλώσσας
from dotenv import load_dotenv # Για φόρτωση περιβαλλοντικών μεταβλητών (π.χ. API keys)

load_dotenv() # Φορτώνει τις περιβαλλοντικές μεταβλητές από το .env αρχείο (π.χ. API keys)

llm = ChatGroq( # Αρχικοποιεί το LLM για παραγωγή απαντήσεων
    model_name="llama-3.3-70b-versatile",
    temperature=0.1 # Χαμηλή θερμοκρασία για πιο συνεπείς απαντήσεις
)

llm_classify = ChatGroq( # LLM για deterministic ταξινόμηση προθέσεων (temperature=0, χωρίς τυχαιότητα)
    model_name="llama-3.1-8b-instant",
    temperature=0
)

LESSONS_PATH = Path(__file__).resolve().parents[1] / "content" / "lessons.json"

with open(LESSONS_PATH, "r", encoding="utf-8") as f: # Φορτώνει το περιεχόμενο των μαθημάτων από το JSON αρχείο
    lessons_content = json.load(f)

_NUMERIC_NAMES = {
    "age", "score", "year", "num_var", "n1", "n2", "num", "limit",
    "temp", "speed", "numbers", "price", "rating", "count", "total"
}

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

# ── Keyword helpers (διατηρούνται ως fallback για _classify_intent) ──────────

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
        "proxvrame", "proxwrame", "prochvrame", "proksorame",
        "θελω ακομα μια ακσηση", "ακσηση", "ακομα μια ακσηση",  # typo για ασκηση
        "θελω ακομα", "αλλη ακσηση"
    ]
    return any(phrase in normalized for phrase in phrases)

# ── LLM Intent Classification ────────────────────────────────────────────────

def _classify_intent(user_input: str, profile_checked: bool, task_started: bool) -> str:
    """Ταξινομεί την πρόθεση του χρήστη με LLM (temperature=0), αντικαθιστώντας keyword matching.

    Επιστρέφει ένα από:
      profile_yes | profile_no | wants_task | theory_question |
      advance_lesson | menu_1 | menu_2 | menu_3 | code_help | other
    """
    stripped = (user_input or "").strip()

    # Deterministic shortcuts για αναμφίβολες περιπτώσεις
    if stripped in {"1", "2", "3"}:
        return f"menu_{stripped}"
    if not stripped:
        return "other"

    # Πλαίσιο και κατηγορίες ανά φάση
    if not profile_checked:
        context_hint = "Ο χρήστης αποκρίνεται στην ερώτηση αν έχει ξαναγράψει κώδικα."
        categories = (
            "profile_yes - ο χρήστης έχει εμπειρία κώδικα "
            "(ναι, ξέρω, έχω γράψει, προχωρημένος, γνωρίζω, yes, λίγο κλπ)\n"
            "profile_no  - ο χρήστης δεν έχει εμπειρία "
            "(όχι, πρώτη φορά, αρχάριος, no, ποτέ κλπ)"
        )
    elif task_started:
        context_hint = "Ο χρήστης εργάζεται πάνω σε άσκηση Python."
        categories = (
            "wants_task      - ο χρήστης θέλει νέα άσκηση ή απαντά θετικά για συνέχεια "
            "(ναι, yes, οκ, πάμε, προχωράμε, αλλη ασκηση κλπ)\n"
            "theory_question - ο χρήστης κάνει ερώτηση θεωρίας ή ζητά επεξήγηση/παράδειγμα\n"
            "advance_lesson  - ο χρήστης θέλει να προχωρήσει στο επόμενο κεφάλαιο\n"
            "code_help       - ο χρήστης ζητά βοήθεια με τον κώδικά του\n"
            "other           - κάτι άλλο"
        )
    else:
        context_hint = "Ο χρήστης βρίσκεται στη φάση θεωρίας."
        categories = (
            "wants_task      - ο χρήστης θέλει να ξεκινήσει ή να συνεχίσει με άσκηση "
            "(προχωράμε, θελω ακομα μια ασκηση, θελω ασκηση, θελω ακομα, πάμε, έτοιμος, "
            "δεν έχω απορία, ναι, yes, οκ, οκει, ας πάμε κλπ — ακόμα και με ορθογραφικά λάθη)\n"
            "theory_question - ο χρήστης κάνει ερώτηση ή ζητά επεξήγηση/παράδειγμα "
            "(τι είναι, πώς, γιατί, δώσε παράδειγμα, δεν καταλαβα κλπ)\n"
            "advance_lesson  - ο χρήστης θέλει να πάει στο επόμενο κεφάλαιο/μάθημα\n"
            "other           - κάτι άλλο"
        )

    prompt_text = (
        f"Κατηγοριοποίησε τι θέλει ο χρήστης. Απάντησε ΜΟΝΟ με μία λέξη-κλειδί:\n"
        f"{categories}\n\n"
        f"Πλαίσιο: {context_hint}\n"
        f'Μήνυμα χρήστη: "{user_input}"\n\n'
        f"Λέξη-κλειδί:"
    )

    try:
        result = llm_classify.invoke(prompt_text)
        intent = result.content.strip().lower().split()[0] if result.content.strip() else "other"
        valid = {
            "profile_yes", "profile_no", "wants_task", "theory_question",
            "advance_lesson", "menu_1", "menu_2", "menu_3", "code_help", "other"
        }
        return intent if intent in valid else "other"
    except Exception:
        # Fallback σε keyword matching αν αποτύχει το LLM
        if not profile_checked:
            msg = (user_input or "").lower()
            if any(w in msg for w in ["ναι", "έχω ξαναγράψει", "γνωρίζω", "προχωρημένος", "ξέρω", "yes", "λίγο"]):
                return "profile_yes"
            return "profile_no"
        if _wants_to_start_task(user_input):
            return "wants_task"
        if _is_question_message(user_input):
            return "code_help" if task_started else "theory_question"
        if any(t in (user_input or "").lower() for t in ["επόμενο", "επομενο", "next"]):
            return "advance_lesson"
        return "other"


def _answer_theory_question(user_input: str, lesson_title: str, theory: str, tone: str) -> str:
    """Απαντά σε θεωρητική απορία GROUNDED στη theory της ενότητας.
    Αποτρέπει hallucinations περιορίζοντας το LLM στο κείμενο της θεωρίας."""
    prompt_text = (
        f'Είσαι καθηγητής Python. Απάντησε στην ερώτηση ΑΠΟΚΛΕΙΣΤΙΚΑ βάσει '
        f'της παρακάτω θεωρίας.\n\n'
        f'Θεωρία ενότητας "{lesson_title}":\n{theory}\n\n'
        f'Οδηγίες:\n'
        f'- Απάντησε σε 2-3 προτάσεις στα Ελληνικά\n'
        f'- Ύφος: {tone}\n'
        f'- ΜΗΝ δώσεις άσκηση\n'
        f'- ΜΗΝ επαναλάβεις όλη τη θεωρία — μόνο ό,τι αφορά την ερώτηση\n'
        f'- Αν ρωτά για παράδειγμα, δώσε ένα μικρό παράδειγμα κώδικα\n\n'
        f'Ερώτηση μαθητή: {user_input}\n\nΑπάντηση:'
    )
    try:
        result = llm.invoke(prompt_text)
        return result.content.strip()
    except Exception:
        return (
            f"Καλή ερώτηση! Ας ξαναδούμε τη θεωρία:\n\n{theory}\n\n"
            "Αν κάτι εξακολουθεί να είναι ασαφές, ρώτα πιο συγκεκριμένα!"
        )


def _generate_hint_with_llm(
    debug_report: str,
    current_task: str,
    difficulty: str,
    understanding_level: str,
    assessment_feedback: str = ""
) -> str:
    """Hint generator με δύο στρατηγικές:
    - Δομικά λάθη (syntax, undefined_name κλπ): deterministic hint (ακριβές, χωρίς hallucinations).
    - Assessment failures (σωστός κώδικας που δεν πληροί κριτήρια): LLM grounded στην εκφώνηση.
    """
    report = debug_report or ""
    has_structural_error = any(tag in report for tag in [
        "[DEBUG: ERROR]", "undefined_name", "type_mismatch",
        "missing_if", "missing_for", "missing_function",
        "missing_append", "missing_list", "missing_output"
    ])
    if has_structural_error:
        # Deterministic για syntax/δομικά λάθη — αποφεύγει hallucinations
        return _generate_targeted_hint(debug_report, difficulty, assessment_feedback)

    # LLM για assessment-level failures (grounded στην εκφώνηση + semantic analysis)
    clean_fb = _clean_feedback(assessment_feedback)
    # Αν ο Debugger βρήκε semantic πρόβλημα, το συμπεριλαμβάνουμε ως επιπλέον πλαίσιο
    semantic_context = report.replace("[DEBUG: SEMANTIC]", "").strip() if "[DEBUG: SEMANTIC]" in report else ""
    prompt_text = (
        f"Είσαι καθηγητής Python. Ο κώδικας του μαθητή είναι συντακτικά σωστός "
        f"αλλά δεν ικανοποιεί τα κριτήρια της άσκησης.\n\n"
        f"Εκφώνηση: {current_task}\n"
        f"Αξιολόγηση Assessor: {clean_fb}\n"
        + (f"Σημασιολογική ανάλυση Debugger: {semantic_context}\n" if semantic_context else "")
        + f"Επίπεδο κατανόησης μαθητή: {understanding_level}\n\n"
        f"Δώσε ΕΝΑ hint (1-2 προτάσεις) που να οδηγεί στη σωστή κατεύθυνση. "
        f"ΜΗΝ δώσεις τη λύση. ΜΗΝ γράψεις κώδικα.\n\nHint:"
    )
    try:
        result = llm.invoke(prompt_text)
        hint = result.content.strip()
        return hint if hint else _generate_targeted_hint(debug_report, difficulty, assessment_feedback)
    except Exception:
        return _generate_targeted_hint(debug_report, difficulty, assessment_feedback)


def _generate_transition(context_hint: str, tone: str = "φιλικά, ζεστά") -> str:
    """Παράγει φυσική μεταβατική φράση (1-2 προτάσεις) με LLM.

    Χρησιμοποιείται για conversational wrappers γύρω από structural content.
    Επιστρέφει "" αν αποτύχει το LLM — ο caller χρησιμοποιεί fallback hardcoded φράση.
    """
    prompt_text = (
        f"Είσαι ο Mentor, καθηγητής Python. Μιλάς ΩΣ ΚΑΘΗΓΗΤΗΣ προς τον μαθητή.\n"
        f"Γράψε 1-2 φυσικές προτάσεις στα Ελληνικά. Ύφος: {tone}.\n"
        f"Οδηγία: {context_hint}\n"
        f"Κανόνες: μόνο η φράση, χωρίς κώδικα, χωρίς markdown headers, χωρίς επανάληψη θεωρίας.\n\n"
        f"Φράση:"
    )
    try:
        result = llm.invoke(prompt_text)
        return result.content.strip()
    except Exception:
        return ""


async def generate_session_recap_async(history_pairs: list, lesson_name: str, username: str) -> str:
    """Παράγει σύντομη περίληψη της προηγούμενης συνεδρίας με LLM, με δικά του λόγια."""
    recent = []
    for role, content in history_pairs[-12:]:
        if role == "ai":
            clean = re.sub(r'\[[^\]]+\]', '', content or '').strip()
            if clean:
                recent.append(f"Mentor: {clean[:250]}")
        elif role == "human":
            text = (content or '').strip()
            if text and "```" not in text and not text.upper().startswith("CODE_SUBMISSION") and not text.startswith("Υποβολή κώδικα"):
                recent.append(f"Μαθητής: {text[:120]}")

    if not recent:
        return ""

    history_text = "\n".join(recent)
    prompt = (
        f"Είσαι ο Mentor, καθηγητής Python. Γράψε 2-3 προτάσεις που συνοψίζουν "
        f"τι δουλέψατε με τον μαθητή στην προηγούμενη συνεδρία.\n"
        f"Απευθύνσου άμεσα στον μαθητή (β' πρόσωπο). Ύφος: φιλικό, φυσικό.\n"
        f"ΜΗΝ αντιγράφεις αυτολεξεί τα μηνύματα. ΜΗΝ αναφέρεις ότι βλέπεις ιστορικό.\n\n"
        f"Ενότητα: {lesson_name}\n"
        f"Πρόσφατη συνομιλία:\n{history_text}\n\nΠερίληψη:"
    )
    try:
        result = await llm.ainvoke(prompt)
        recap = result.content.strip()
        return recap if recap else ""
    except Exception:
        return ""


async def classify_profile_async(user_input: str) -> str:
    """Ταξινομεί αν ο χρήστης είναι expert ή beginner βάσει LLM.
    Fallback σε keyword matching αν το LLM αποτύχει."""
    prompt_text = (
        'Ο χρήστης αποκρίνεται στην ερώτηση '
        '"Έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;".\n'
        'Απάντησε ΜΟΝΟ με: expert ή beginner\n\n'
        'Παραδείγματα:\n'
        '"ναι έχω εμπειρία" → expert\n'
        '"όχι, πρώτη φορά" → beginner\n'
        '"λίγο, αλλά ξέρω βασικά" → expert\n'
        '"δεν ξέρω τίποτα" → beginner\n\n'
        f'Μήνυμα: "{user_input}"\n\nΑπάντηση:'
    )
    try:
        result = await llm_classify.ainvoke(prompt_text)
        answer = result.content.strip().lower().split()[0]
        return "expert" if "expert" in answer else "beginner"
    except Exception:
        msg = (user_input or "").lower()
        if any(w in msg for w in ["ναι", "έχω ξαναγράψει", "γνωρίζω", "προχωρημένος", "ξέρω", "yes", "λίγο"]):
            return "expert"
        return "beginner"

# ── Deterministic helpers ────────────────────────────────────────────────────

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
        # Ονόματα που σημασιολογικά είναι αριθμητικά — δεν έχουν νόημα ως string
        for line in report.splitlines():
            if "Χρήση μεταβλητής πριν από ανάθεση" in line:
                vars_part = line.split(":")[-1].strip()
                first_var = vars_part.split(",")[0].strip()
                if first_var in _NUMERIC_NAMES:
                    # Πιθανό λάθος: == αντί για = (σύγκριση αντί ανάθεσης)
                    return (
                        f"Ο Python δεν αναγνωρίζει τη μεταβλητή `{vars_part}` — δεν έχει οριστεί ακόμα.\n"
                        f"Πρόσεξε: το `==` είναι σύγκριση, ενώ το `=` είναι ανάθεση τιμής.\n"
                        f"Για να ορίσεις τη μεταβλητή γράψε: `{first_var} = <τιμή>`"
                    )
                return (
                    f"Ο Python δεν αναγνωρίζει τη λέξη `{vars_part}`.\n"
                    f"• Αν θέλεις να γράψεις κείμενο (string), βάλ' το σε εισαγωγικά: `\"{vars_part}\"`\n"
                    f"• Αν είναι όνομα μεταβλητής, ορίσ' τη πρώτα: `{vars_part} = ...`"
                )
        return (
            "Ο Python δεν αναγνωρίζει κάποια λέξη στον κώδικά σου.\n"
            "• Αν θέλεις να γράψεις κείμενο, βάλ' το σε εισαγωγικά (π.χ. `\"κείμενο\"`)\n"
            "• Αν είναι μεταβλητή, σιγουρέψου ότι την έχεις ορίσει πρώτα"
        )

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

# ── Mentor Node ──────────────────────────────────────────────────────────────

def mentoring_node(state): # Κύρια συνάρτηση που διαχειρίζεται τη λογική του Mentor βάσει του τρέχοντος state
    messages = state.get("messages", [])
    user_input = messages[-1].content if messages else ""

    is_first_login = state.get("is_first_login", False)
    profile_checked = state.get("profile_checked", False)
    awaiting_questions = state.get("awaiting_questions", False)
    event_type = state.get("event_type", "")
    task_started = state.get("task_started", False)
    is_correct = state.get("is_correct", False)
    debug_report = state.get("debug_report", "")
    assessment_decision = state.get("assessment_decision", "")
    assessment_feedback = state.get("assessment_feedback", "")
    performance_summary = state.get("performance_summary", "{}")
    last_assessment_decision = _extract_last_assessment_decision(messages)
    experience = state.get("experience_level", "beginner")
    attempts = state.get("attempts_count", 0)
    understanding_level = state.get("understanding_level", "developing")

    # Αυτόματη προσαρμογή δυσκολίας
    if attempts >= 3:
        difficulty = "easy"
    else:
        difficulty = "hard" if experience == "expert" else "easy"

    lesson = pick_lesson(state)
    chapter_header = _chapter_header(lesson)
    lesson_title = lesson.get("title", "")
    theory = lesson.get("detailed_theory", "")

    # Τίτλος επόμενης ενότητας (για το μήνυμα επιτυχίας)
    all_lessons = lessons_content.get("lessons", [])
    current_lesson_id = state.get("current_lesson_id", 1)
    next_lesson_obj = next((l for l in all_lessons if l["id"] == current_lesson_id + 1), None)
    next_lesson_title = next_lesson_obj.get("title", "επόμενη ενότητα") if next_lesson_obj else "επόμενη ενότητα"
    task = state.get("current_task")
    success_criteria = state.get("success_criteria")

    if not task or success_criteria is None:
        task_payload = generate_random_task(lesson, difficulty)
        task = task_payload["task_text"]
        success_criteria = task_payload["rendered_criteria"]

    if isinstance(success_criteria, list):
        success_criteria_text = "\n".join([f"- {c}" for c in success_criteria]) if success_criteria else "- Σωστή λύση της άσκησης."
    else:
        success_criteria_text = f"- {success_criteria}" if success_criteria else "- Σωστή λύση της άσκησης."

    # Προσαρμογή ύφους επεξήγησης βάσει understanding_level και difficulty
    if understanding_level == "needs_support":
        tone = "εξήγησε βήμα-βήμα με πολλά παραδείγματα, πολύ αναλυτικά — ο μαθητής δυσκολεύεται"
    elif understanding_level == "strong":
        tone = "δώσε σύντομη υπόδειξη χωρίς αναλυτική εξήγηση — ο μαθητής τα πηγαίνει άριστα"
    elif understanding_level == "good":
        tone = "εξήγησε συνοπτικά" if difficulty == "hard" else "εξήγησε απλά με ένα παράδειγμα"
    else:  # developing (default)
        tone = "εξήγησε πολύ απλά με παραδείγματα" if difficulty == "easy" else "χρησιμοποίησε τεχνική ορολογία"

    # ── LLM Intent Classification ────────────────────────────────────────────
    # Παρακάμπτουμε την ταξινόμηση για deterministic events που δεν εξαρτώνται από το user input
    if (
        is_first_login  # Πρώτος γύρος: πάντα deterministic, δεν ταξινομούμε το user input
        or event_type in {"no_submission_timeout", "lesson_advanced"}
        or is_correct
    ):
        intent = "other"
    else:
        intent = _classify_intent(user_input, profile_checked, task_started)

    wants_task = intent == "wants_task"
    next_chapter_request = intent == "advance_lesson"
    menu_choice = intent if intent.startswith("menu_") else None  # "menu_1", "menu_2", "menu_3" ή None

    # ── Current Context (για το system prompt του LLM fallback) ─────────────
    current_context = ""
    if is_first_login and not profile_checked:
        current_context = "Ο μαθητής συνδέεται για πρώτη φορά. Συστήσου και κάνε profile check για να δούμε αν είναι αρχάριος ή προχωρημένος."
    elif event_type == "lesson_advanced":
        current_context = f"Ο μαθητής μόλις πέρασε στο νέο μάθημα '{lesson_title}'. Παρουσίασε τη θεωρία και ρώτα αν έχει απορίες."
    elif event_type == "no_submission_timeout":
        if difficulty == "easy":
            current_context = "Ο μαθητής δεν υπέβαλε κώδικα για 40+ δευτερόλεπτα. Δώσε 1 σύντομο παιδαγωγικό hint χωρίς λύση."
        else:
            current_context = f"Ο μαθητής δουλεύει στην άσκηση της ενότητας {lesson_title}. Υπενθύμισέ του σύντομα την εκφώνηση χωρίς να δώσεις hint."
    elif menu_choice == "menu_1":
        current_context = f"Ο μαθητής επέλεξε επανάληψη θεωρίας. Παρουσίασε ξανά τη θεωρία της ενότητας {lesson_title} σύντομα."
    elif menu_choice == "menu_2":
        current_context = f"Ο μαθητής επέλεξε νέα άσκηση για την ενότητα {lesson_title}."
    elif menu_choice == "menu_3":
        current_context = f"Ο μαθητής ζητά hints. Debug Report: {debug_report}. Δώσε στοχευμένο hint."
    elif next_chapter_request and task_started and last_assessment_decision in {"repeat", "support"}:
        current_context = "Ο μαθητής ζητά να προχωρήσει, αλλά η τελευταία αξιολόγηση δείχνει ότι χρειάζεται επανάληψη/υποστήριξη. Εξήγησε ευγενικά γιατί και πρότεινε επιλογές."
    elif is_correct:
        current_context = f"Ο μαθητής έλυσε σωστά την άσκηση. Συγχάρηκε τον και ρώτα αν θέλει την επόμενη ενότητα: {lesson_title}."
    elif wants_task:
        current_context = f"Ο μαθητής είπε ότι δεν έχει άλλες απορίες. Δώσε αμέσως την άσκηση για την ενότητα {lesson_title} και ζήτησέ του να ξεκινήσει."
    elif intent == "theory_question":
        current_context = f"Ο μαθητής έκανε απορία πάνω στη θεωρία της ενότητας {lesson_title}. Απάντησε μόνο στην απορία, σύντομα και καθαρά. ΜΗΝ ξαναπείς όλη τη θεωρία και ΜΗΝ δώσεις άσκηση."
    elif intent == "code_help":
        current_context = (
            f"Ο μαθητής δουλεύει στην άσκηση της ενότητας {lesson_title} και δεν καταλαβαίνει το λάθος του. "
            f"Debug Report: {debug_report}. "
            f"Εξήγησε σύντομα τι πήγε στραβά χωρίς να δώσεις λύση. Ύφος: {tone}."
        )
    elif awaiting_questions:
        current_context = f"Έχεις μόλις εξηγήσει τη θεωρία της ενότητας {lesson_title}. Περίμενε απορίες από τον μαθητή ή απάντησέ τες σύντομα. ΜΗΝ δώσεις ακόμα άσκηση μέχρι να πει ότι είναι έτοιμος."
    elif task_started and not is_correct:
        current_context = f"Ο μαθητής δουλεύει στην άσκηση (Επίπεδο: {difficulty}) αλλά έχει λάθη. Debug Report: {debug_report}. Δώσε ένα hint κατάλληλο για το επίπεδό του ({tone})."
    else:
        current_context = f"Βρισκόμαστε στην ενότητα {lesson_title}. Παρέδωσε τη θεωρία: {theory}. Στο τέλος ρώτα μόνο αν έχει απορίες. ΜΗΝ πεις 'ποια είναι η επόμενη κίνηση σου;'. Χρησιμοποίησε ύφος: {tone}."

    # ── Deterministic Content Builder ────────────────────────────────────────
    # Structural tokens ([BUTTON:START_TASK], [ASSESSMENT:*], chapter_header, theory, task)
    # παραμένουν πάντα deterministic. Μόνο τα conversational wrappers παράγονται από LLM.
    deterministic_content = None

    if is_first_login and not profile_checked:
        welcome = _generate_transition(
            "Καλωσόρισε τον νέο μαθητή και ρώτα αν έχει ξαναγράψει κώδικα ή αν είναι η πρώτη του επαφή με προγραμματισμό",
            tone="ζεστά, φιλικά, ενθαρρυντικά"
        )
        deterministic_content = welcome or (
            "Καλώς ήρθες! Είμαι εδώ για να σε βοηθήσω να μάθεις Python.\n\n"
            "Πριν ξεκινήσουμε, έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
        )
    elif event_type == "lesson_advanced":
        intro = _generate_transition(
            f"Ο μαθητής μόλις πέρασε στο κεφάλαιο '{lesson_title}'. Εκφράσου με ενθουσιασμό και ανακοίνωσε ότι αρχίζει η νέα θεωρία",
            tone="ενθαρρυντικά, ζωηρά"
        )
        intro = intro or "Πολύ ωραία, προχωράμε στο επόμενο κεφάλαιο!"
        outro = _generate_transition(
            f"Μόλις παρουσίασες τη θεωρία '{lesson_title}'. Ρώτα φιλικά αν έχει απορίες ή αν είναι έτοιμος για άσκηση",
            tone="φιλικά" if difficulty == "easy" else "ενθαρρυντικά"
        )
        outro = outro or "Έχεις κάποια απορία; Αν είσαι έτοιμος, γράψε 'προχωράμε'!"
        deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
    elif event_type == "no_submission_timeout":
        if difficulty == "easy":
            timeout_msg = _generate_transition(
                "Ο μαθητής δεν έχει υποβάλει κώδικα για ώρα. Ενθάρρυνέ τον να ξεκινήσει από το πιο απλό βήμα της άσκησης, χωρίς να του δώσεις λύση",
                tone="ηρεμιστικά, ενθαρρυντικά"
            )
            deterministic_content = timeout_msg or "Πάρε το ήσυχα! Ξεκίνα σπάζοντας την εκφώνηση σε μικρά βήματα και υλοποίησε πρώτα το πιο απλό κομμάτι."
        # Για expert: deterministic_content παραμένει None → LLM χειρίζεται (reminder χωρίς hint)
    elif menu_choice == "menu_1":
        intro = _generate_transition(
            f"Ο μαθητής ζητά επανάληψη θεωρίας '{lesson_title}'. Ανακοίνωσε ότι θα ξαναδούν τη θεωρία μαζί",
            tone="φιλικά"
        )
        intro = intro or "Ας ξαναδούμε τη θεωρία μαζί!"
        outro = _generate_transition(
            f"Μόλις παρουσίασες ξανά τη θεωρία '{lesson_title}'. Ρώτα αν έχει ερωτήσεις ή αν θέλει να δοκιμάσει την άσκηση",
            tone="φιλικά"
        )
        outro = outro or "Έχεις ερωτήσεις; Αλλιώς γράψε 'προχωράμε' για να δοκιμάσεις!"
        deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
    elif menu_choice == "menu_2":
        task_intro = _generate_transition(
            f"Δίνεις νέα άσκηση στον μαθητή για την ενότητα '{lesson_title}'. Ανακοίνωσέ την σύντομα και ενθαρρυντικά",
            tone="ενθαρρυντικά"
        )
        task_intro = task_intro or f"Τέλεια! Να μια νέα άσκηση για την ενότητα **{lesson_title}**:"
        deterministic_content = f"{task_intro}\n\n{task}\n\n[BUTTON:START_TASK]"
    elif menu_choice == "menu_3":
        hint_text = _generate_hint_with_llm(debug_report, task, difficulty, understanding_level, assessment_feedback)
        hint_intro = _generate_transition(
            "Ο μαθητής ζήτησε hint για το λάθος του. Παρουσίασε το hint που ακολουθεί με παιδαγωγικό τρόπο",
            tone="παιδαγωγικά, φιλικά"
        )
        hint_intro = hint_intro or "Ας δούμε πιο προσεκτικά τι χρειάζεται διόρθωση:"
        hint_outro = _generate_transition(
            "Μόλις έδωσες hint. Ενθάρρυνε τον μαθητή να δοκιμάσει τη διόρθωση και να υποβάλει ξανά",
            tone="ενθαρρυντικά"
        )
        hint_outro = hint_outro or "Δοκίμασε να διορθώσεις αυτό το σημείο και υποβάλε ξανά!"
        deterministic_content = f"{hint_intro}\n\n{hint_text}\n\n{hint_outro}\n\n[ASSESSMENT:SUPPORT]\n[HINT]"
    elif next_chapter_request and task_started and last_assessment_decision in {"repeat", "support"}:
        block_msg = _generate_transition(
            f"Ο μαθητής θέλει να προχωρήσει στο επόμενο κεφάλαιο αλλά η αξιολόγηση λέει ότι χρειάζεται επανάληψη στην ενότητα '{lesson_title}'. Εξήγησε ευγενικά ότι αξίζει να εδραιωθεί πρώτα η κατανόηση",
            tone="κατανοητικά, ευγενικά"
        )
        block_msg = block_msg or "Καταλαβαίνω ότι θέλεις να προχωρήσουμε, αλλά φαίνεται ότι χρειάζεται λίγο ακόμη δουλειά σε αυτή την ενότητα."
        deterministic_content = (
            f"{block_msg}\n\n"
            "Μπορούμε να κάνουμε ένα από τα εξής:\n"
            "1) Σύντομη επανάληψη θεωρίας\n"
            "2) Μία επιπλέον άσκηση\n"
            "3) Στοχευμένα hints πάνω στον κώδικά σου\n\n"
            "[ASSESSMENT:SUPPORT]"
        )
    elif is_correct:
        if assessment_decision == "advance":
            congrats = _generate_transition(
                f"Ο μαθητής έλυσε σωστά την άσκηση. Συγχάρες τον θερμά και ρώτα αν θέλει να προχωρήσει στην επόμενη ενότητα '{next_lesson_title}'",
                tone="ενθουσιαστικά, ζεστά"
            )
            congrats = congrats or f"Μπράβο, η λύση σου είναι σωστή! Πολύ καλή δουλειά!\n\nΘέλεις να προχωρήσουμε στην επόμενη ενότητα: **{next_lesson_title}**;"
            deterministic_content = f"{congrats}\n\n[ASSESSMENT:ADVANCE]"
        else:
            # is_correct=True αλλά assessment_decision=support/repeat:
            # δεν προάγουμε — προτείνουμε επιπλέον άσκηση χωρίς να δείξουμε εσωτερικά μηνύματα
            congrats = _generate_transition(
                f"Ο μαθητής έλυσε σωστά αλλά χρειάζεται περισσότερη εξάσκηση στην ενότητα '{lesson_title}'. Συγχάρες τον και προτρέψτον να συνεχίσει με άλλη άσκηση γράφοντας 'προχωράμε'",
                tone="ενθαρρυντικά, φιλικά"
            )
            congrats = congrats or f"Μπράβο, η λύση σου είναι σωστή!\n\nΑς εξασκηθούμε λίγο ακόμα στην ενότητα **{lesson_title}**. Γράψε 'προχωράμε' για νέα άσκηση!"
            deterministic_content = f"{congrats}\n\n[ASSESSMENT:REPEAT]"
    elif wants_task:
        task_intro = _generate_transition(
            f"Ο μαθητής είναι έτοιμος για άσκηση στην ενότητα '{lesson_title}'. Παρουσίασε την άσκηση που ακολουθεί με ενθουσιασμό",
            tone="ενθαρρυντικά"
        )
        task_intro = task_intro or f"Τέλεια! Να η άσκησή σου για την ενότητα **{lesson_title}**:"
        deterministic_content = f"{task_intro}\n\n{task}\n\n[BUTTON:START_TASK]"
    elif intent == "theory_question":
        # Grounded LLM απάντηση στη θεωρητική απορία — περιορισμένη στο theory text
        theory_answer = _answer_theory_question(user_input, lesson_title, theory, tone)
        deterministic_content = theory_answer
    elif intent == "code_help":
        # Ερώτηση κατά τη διάρκεια άσκησης
        if task_started and debug_report and "[DEBUG: EMPTY]" not in debug_report:
            decision_tag = "[ASSESSMENT:SUPPORT]" if assessment_decision == "support" else "[ASSESSMENT:REPEAT]"
            hint_text = _generate_hint_with_llm(debug_report, task, difficulty, understanding_level, assessment_feedback)
            hint_intro = _generate_transition(
                "Ο μαθητής χρειάζεται βοήθεια με τον κώδικά του. Ανακοίνωσε παιδαγωγικά ότι θα δείτε μαζί το πρόβλημα",
                tone="παιδαγωγικά, φιλικά"
            )
            hint_intro = hint_intro or "Ας δούμε μαζί τι συμβαίνει:"
            hint_outro = _generate_transition(
                "Μόλις εξήγησες το πρόβλημα. Ενθάρρυνε τον μαθητή να δοκιμάσει τη διόρθωση και να υποβάλει ξανά",
                tone="ενθαρρυντικά"
            )
            hint_outro = hint_outro or "Δοκίμασε να διορθώσεις αυτό το σημείο και υποβάλε ξανά τον κώδικά σου."
            deterministic_content = f"{hint_intro}\n\n{hint_text}\n\n{hint_outro}\n\n{decision_tag}\n[HINT]"
        else:
            # Δεν υπάρχει debug report ακόμα — απάντα στη θεωρητική πλευρά
            theory_answer = _answer_theory_question(user_input, lesson_title, theory, tone)
            deterministic_content = theory_answer
    elif awaiting_questions or (profile_checked and not task_started and not wants_task):
        outro = _generate_transition(
            f"Μόλις παρουσίασες τη θεωρία '{lesson_title}'. Ρώτα φιλικά αν έχει απορίες ή αν θέλει να ξεκινήσει την άσκηση",
            tone="φιλικά" if difficulty == "easy" else "ενθαρρυντικά"
        )
        outro = outro or "Έχεις κάποια απορία; Αν είσαι έτοιμος, γράψε 'προχωράμε'!"
        deterministic_content = f"{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
    elif task_started and not is_correct:
        decision_tag = "[ASSESSMENT:SUPPORT]" if assessment_decision == "support" else "[ASSESSMENT:REPEAT]"
        hint_text = _generate_hint_with_llm(debug_report, task, difficulty, understanding_level, assessment_feedback)
        hint_intro = _generate_transition(
            "Ο κώδικας του μαθητή έχει λάθος. Ανακοίνωσε παιδαγωγικά ότι θα δεις τι χρειάζεται βελτίωση",
            tone="παιδαγωγικά, φιλικά"
        )
        hint_intro = hint_intro or "Ας δούμε τι χρειάζεται διόρθωση:"
        deterministic_content = f"{hint_intro}\n\n{hint_text}\n\n{decision_tag}\n[HINT]"
    else:
        outro = _generate_transition(
            f"Παρουσιάζεις τη θεωρία της ενότητας '{lesson_title}'. Ρώτα αν έχει απορίες ή αν είναι έτοιμος να ξεκινήσει",
            tone="φιλικά"
        )
        outro = outro or "Έχεις κάποια απορία; Αν είσαι έτοιμος, γράψε 'προχωράμε'!"
        deterministic_content = f"{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"

    # ── Επιστροφή αποτελέσματος ───────────────────────────────────────────────
    if deterministic_content is not None:
        if wants_task and "[BUTTON:START_TASK]" not in deterministic_content:
            deterministic_content += "\n\n[BUTTON:START_TASK]"
        return {
            "messages": [AIMessage(content=deterministic_content)],
            "current_task": task,
            "success_criteria": success_criteria,
        }

    # LLM fallback — χρησιμοποιείται μόνο για περιπτώσεις χωρίς deterministic handler
    # (π.χ. expert timeout reminder)
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
        content = response.content.strip()

        if wants_task and "[BUTTON:START_TASK]" not in content:
            content += "\n\n[BUTTON:START_TASK]"

        return {
            "messages": [AIMessage(content=content)],
            "current_task": task,
            "success_criteria": success_criteria,
        }
    except Exception:
        fallback_content = (
            f"Καλή ερώτηση! Ας ξαναδούμε τη θεωρία μαζί:\n\n"
            f"{theory}\n\n"
            f"Αν κάτι εξακολουθεί να μην είναι ξεκάθαρο, ρώτα πιο συγκεκριμένα!"
        )
        return {
            "messages": [AIMessage(content=fallback_content)],
            "current_task": task,
            "success_criteria": success_criteria,
        }
