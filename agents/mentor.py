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
    model_name="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0.1 # Χαμηλή θερμοκρασία για πιο συνεπείς απαντήσεις
)

llm_classify = ChatGroq( # LLM για deterministic ταξινόμηση προθέσεων (temperature=0, χωρίς τυχαιότητα)
    model_name="llama-3.1-8b-instant",
    temperature=0
)

_FOREIGN_SCRIPT_RE = re.compile(
    "["
    "一-鿿㐀-䶿"   # CJK Unified + Extension A
    "぀-ヿ"                  # Hiragana, Katakana
    "가-힣"                  # Hangul
    "Ѐ-ӿ"                  # Cyrillic
    "؀-ۿ"                  # Arabic
    "֐-׿"                  # Hebrew
    "฀-๿"                  # Thai
    "ऀ-ॿ"                  # Devanagari
    "]+"
)

def _strip_foreign_scripts(text: str) -> str:
    """Αφαιρεί tokens σε αλφάβητα εκτός ελληνικών/λατινικών — μερικές φορές το LLM διαρρέει
    CJK/κυριλλικά/άλλα scripts μέσα σε ελληνικό κείμενο παρά τη ρητή οδηγία να γράφει μόνο Ελληνικά."""
    cleaned = _FOREIGN_SCRIPT_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()

def _strip_thinking(text: str) -> str:
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    elif "<think>" in text:
        text = text.split("<think>", 1)[0].strip()
    else:
        text = text.strip()
    return _strip_foreign_scripts(text)

LESSONS_PATH = Path(__file__).resolve().parents[1] / "content" / "lessons.json"

with open(LESSONS_PATH, "r", encoding="utf-8") as f: # Φορτώνει το περιεχόμενο των μαθημάτων από το JSON αρχείο
    lessons_content = json.load(f)

_NUMERIC_NAMES = {
    "age", "score", "year", "num_var", "n1", "n2", "num", "limit",
    "temp", "speed", "numbers", "price", "rating", "count", "total",
    "level", "value", "result", "x", "y", "z", "n", "sum", "avg",
    "min_val", "max_val", "threshold", "balance", "amount", "weight", "height"
}

# Αντιστοίχιση κατηγοριών λαθών → κατανοητή Ελληνική περιγραφή για προσωποποιημένα μηνύματα
_ERROR_CATEGORY_LABELS = {
    "undefined_name": "χρήση μεταβλητής πριν οριστεί",
    "type_mismatch": "λάθος τύπος δεδομένων (π.χ. αριθμός μέσα σε εισαγωγικά)",
    "missing_if": "δομή if/elif/else",
    "missing_for": "for loop",
    "missing_function": "ορισμός συνάρτησης με def",
    "missing_append": "χρήση .append()",
    "missing_list": "δημιουργία λίστας",
    "missing_output": "ξεχασμένο print()",
    "missing_index": "πρόσβαση στοιχείων λίστας με index",
    "print_as_variable": "χρήση print ως μεταβλητή αντί για συνάρτηση (print = ... αντί print(...))",
    "general_logic": "λογικά λάθη στη ροή του κώδικα",
    "method_error": "λάθος κλήση μεθόδου (π.χ. λίστα.len() αντί len(λίστα))",
    "missing_call": "συνάρτηση ορίστηκε αλλά δεν καλείται",
    "missing_accumulator": "λείπει ο αθροιστής (π.χ. total += num σε κάθε επανάληψη)",
    "literal_param_error": "literal τιμή ως παράμετρος (π.χ. def func(1, 2): αντί def func(a, b):)",
    "print_func_ref": "print() δέχεται αναφορά συνάρτησης αντί για κλήση (print(func) αντί print(func(...)))",
    "wrong_arg_count": "λάθος αριθμός ορισμάτων στην κλήση συνάρτησης",
    "wrong_list_type": "λάθος τύπος στοιχείων λίστας (strings αντί για αριθμούς)",
    "empty_print": "print() χωρίς ορίσματα — τυπώνει κενή γραμμή",
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

# ── Gibberish detection ───────────────────────────────────────────────────────

_GREEK_VOWELS = set('αεηιουωάέήίόύώΑΕΗΙΟΥΩΆΈΉΊΌΎΏ')

# Φράσεις που δηλώνουν "δεν είμαι έτοιμος" — ΔΕΝ πρέπει να μετατρέπονται σε wants_task
_NOT_READY_PATTERNS = [
    "δεν νιωθ", "δεν νιώθ", "δε νιωθ", "δε νιώθ",
    "δεν ειμαι ετοιμ", "δεν είμαι έτοιμ",
    "δεν θελω να προχ", "δεν θέλω να προχ",
    "οχι δεν", "όχι δεν",
    "δεν θελω", "δεν θέλω",
]
_ALL_VOWELS   = _GREEK_VOWELS | set('aeiouAEIOU')

def _is_gibberish(text: str) -> bool:
    """True αν το input είναι ακατανόητο:
    - 1 χαρακτήρας  (π.χ. 'α', 'f')
    - Latin χωρίς φωνήεντα (π.χ. 'sdfgh', 'qwrty', 'ddsdsd')
    - Latin ή ελληνικό όλο με ίδιο γράμμα × 3+ (π.χ. 'ffff', 'ααααα')
    - Ελληνικό χωρίς ελληνικά φωνήεντα (π.χ. 'σδφγ')
    - Ελληνικό με 3+ συνεχόμενα ελληνικά σύμφωνα (π.χ. 'ασδφ', 'σρυξδτ')
      (τα Latin γράμματα όπως 'str'/'pyt' σε μεικτό κείμενο ΔΕΝ μετράνε)
    """
    s = (text or "").strip()
    if len(s) <= 1:
        return True
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False

    has_greek = any('Ͱ' <= c <= 'Ͽ' or 'ἀ' <= c <= '῿' for c in s)

    if not has_greek:
        # ── Latin-only gibberish checks ────────────────────────────────────
        if not any(c in 'aeiouAEIOU' for c in letters):
            return True  # καθόλου φωνήεντα (π.χ. "sdfgh", "ddsdsd")
        if len(set(c.lower() for c in letters)) == 1 and len(letters) >= 3:
            return True  # όλα ίδια (π.χ. "ffff", "ssss")
        return False  # LLM decides για υπόλοιπο Latin κείμενο

    # ── Ελληνικό ή μεικτό κείμενο ─────────────────────────────────────────
    if not any(c in _GREEK_VOWELS for c in letters):
        return True  # χωρίς ελληνικά φωνήεντα (π.χ. "σδφγ", "ξδτφγσ")
    if len(set(c.lower() for c in letters)) == 1 and len(letters) >= 3:
        return True  # όλα ίδια (π.χ. "ααααα", "οοοο")
    # 3+ συνεχόμενα ΕΛΛΗΝΙΚΑ σύμφωνα — Latin γράμματα (str, pyt κλπ) reset το counter
    # Χρησιμοποιούμε ord() με hex τιμές για αδιάφιλη αναγνώριση του Greek Unicode block
    cluster = 0
    for c in s.lower():
        if c.isalpha() and c not in _ALL_VOWELS and 0x0370 <= ord(c) <= 0x03ff:
            cluster += 1
            if cluster >= 3:
                return True
        else:
            cluster = 0
    return False

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
        "δείξε μου", "δειξε μου", "μπορεις να εξηγησεις", "μπορείς να εξηγήσεις",
        # Ρητό αίτημα για θεωρία/επανάληψη
        "θεωρια", "θεωρία", "πες μου", "εξήγησε μου", "εξηγησε μου",
        "ξαναπε", "ξαναπέ", "υπενθυμισε", "υπενθύμισε", "θυμισε", "θύμισε"
    ]
    return any(marker in normalized for marker in question_markers)

def _task_already_presented(messages) -> bool:
    """True αν ο μαθητής έχει ήδη λάβει την τρέχουσα άσκηση.
    Σταματά στο [ASSESSMENT:REPEAT] ή [ASSESSMENT:ADVANCE] — και οι δύο σηματοδοτούν
    τέλος άσκησης, άρα ό,τι ακολουθεί είναι νέα άσκηση (όχι υπενθύμιση)."""
    for msg in reversed(messages[:-1]):  # εξαιρούμε το τελευταίο μήνυμα χρήστη
        content = getattr(msg, 'content', '') or ''
        if '[BUTTON:START_TASK]' in content or '[BUTTON:CONTINUE_TASK]' in content:
            return True
        if '[ASSESSMENT:ADVANCE]' in content or '[ASSESSMENT:REPEAT]' in content:
            return False  # η άσκηση τελείωσε — η επόμενη είναι νέα
    return False

def _new_lesson_theory_shown(messages) -> bool:
    """True αν, μετά το τελευταίο [ASSESSMENT:ADVANCE], η θεωρία της νέας ενότητας έχει ήδη παρουσιαστεί.
    Εξετάζει σε αντίστροφη σειρά: αν βρει [AWAITING_QUESTIONS] ή [BUTTON:START_TASK] πριν το [ASSESSMENT:ADVANCE]
    → η θεωρία έχει δειχθεί. Αν βρει [ASSESSMENT:ADVANCE] πρώτα → δεν έχει δειχθεί ακόμα."""
    for msg in reversed(messages[:-1]):
        content = getattr(msg, 'content', '') or ''
        if '[BUTTON:START_TASK]' in content or '[BUTTON:CONTINUE_TASK]' in content:
            return True   # άσκηση ξεκίνησε → θεωρία παρουσιάστηκε ή παρακάμφθηκε
        if '[AWAITING_QUESTIONS]' in content:
            return True   # θεωρία παρουσιάστηκε στη νέα ενότητα
        if '[ASSESSMENT:ADVANCE]' in content:
            return False  # φτάσαμε στο advance χωρίς θεωρία → δεν έχει παρουσιαστεί
    return False

def _is_repeat_exercise_mode(messages) -> bool:
    """True αν η τελευταία άσκηση ολοκληρώθηκε με decision=repeat (υπάρχει [ASSESSMENT:REPEAT]
    χωρίς νέο [BUTTON:START_TASK] μετά) — η επόμενη άσκηση είναι 'εξάσκηση επανάληψης'."""
    for msg in reversed(messages[:-1]):
        content = getattr(msg, 'content', '') or ''
        if '[BUTTON:START_TASK]' in content or '[BUTTON:CONTINUE_TASK]' in content:
            return False  # νέα άσκηση ήδη ξεκίνησε
        if '[ASSESSMENT:REPEAT]' in content:
            return True   # τελευταία άσκηση είχε repeat και νέα δεν έχει ακόμα εκχωρηθεί
        if '[ASSESSMENT:ADVANCE]' in content:
            return False
    return False

def _wants_to_start_task(text: str) -> bool:
    normalized = (text or "").strip().lower()
    phrases = [
        "δεν έχω απορία", "δεν εχω απορια", "δεν έχω απορίες", "δεν εχω αποριες",
        "προχώρα", "προχωρα", "προχωράμε", "προχωραμε", "πάμε", "παμε",
        "συνέχισε", "συνεχισε",
        "κατάλαβα", "καταλαβα", "κατάλαβα!", "καταλαβα!", "εντάξει", "εντάξει!", "εντάξει.", "εντάξει,",
        "άλλη άσκηση", "αλλη ασκηση", "άλλη μια άσκηση", "αλλη μια ασκηση",
        "επιπλέον άσκηση", "επιπλεον ασκηση", "ακόμα μια άσκηση", "ακομα μια ασκηση",
        "δώσε άσκηση", "δωσε ασκηση", "θέλω άσκηση", "θελω ασκηση",
        "δώσε μου άσκηση", "δωσε μου ασκηση", "δώσε μου μια άσκηση", "δωσε μου μια ασκηση",
        "θέλω μια άσκηση", "θελω μια ασκηση",
        "ας επαναλάβουμε", "ας επαναλαβουμε", "επαναλάβουμε", "επαναλαβουμε",
        "ξανά την άσκηση", "ξανα την ασκηση", "πάλι", "παλι",
        "επανάληψη", "επαναληψη", "δοκιμάσω ξανά", "δοκιμασω ξανα",
        "proxvrame", "proxwrame", "prochvrame", "proksorame",
        "θελω ακομα μια ακσηση", "ακσηση", "ακομα μια ακσηση",  # typo για ασκηση
        "θελω ακομα", "αλλη ακσηση",
        "αυτα τα καταλαβα", "αυτά τα κατάλαβα",  # "αυτά τα κατάλαβα" = ready to continue
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

    # ── Deterministic shortcuts ΠΡΙΝ το gibberish check ────────────────────────
    # (Gibberish θα έπιανε "1"/"2"/"3" ως 1-χαρακτήρα και κώδικα ως "str"/"pyt" cluster)
    if not stripped:
        return "other"
    if stripped in {"1", "2", "3"}:
        return f"menu_{stripped}"
    if "```" in stripped or stripped.lower().startswith("υποβολή κώδικα") or stripped.upper() == "CODE_SUBMISSION":
        return "code_help"

    # ── Deterministic shortcuts παρακάτω ΜΟΝΟ όταν profile_checked=True ─────────
    # Κατά τη φάση profile-check ("έχεις ξαναγράψει κώδικα;"), μια απάντηση σαν
    # "Οχι, δεν έχω ξαναγράψει, θα ήθελα να μου θυμίζεις τη θεωρία κάθε φορά" θα
    # ενεργοποιούσε λανθασμένα αυτά τα shortcuts αντί να ταξινομηθεί ως profile_no/yes.
    _lower_stripped = stripped.lower()
    if profile_checked:
        # "θεωρία"/"θύμισέ μου"/"υπενθύμισε" = πάντα theory_question.
        # Αποτρέπει το μικρό LLM να ερμηνεύσει "Θεωρία" ή "Θύμισέ μου πώς κάνω X" ως wants_task.
        # Παρατηρήθηκε: "Θυμισε μου πως κανω λιστα" ταξινομήθηκε ως wants_task παρά τη ρητή
        # οδηγία "ΟΧΙ wants_task αν ρωτάει 'πώς'" — το μικρό LLM δεν την ακολούθησε αξιόπιστα.
        _reminder_words = ["θεωρια", "θεωρία", "θυμισε", "θύμισε", "υπενθυμισε", "υπενθύμισε", "ξαναπε", "ξαναπέ"]
        if any(w in _lower_stripped for w in _reminder_words):
            return "theory_question"

        # "Οχι + κατάλαβα/έμαθα" = student confirmed understanding.
        # "Οχι τα καταλαβα" / "Οχι τα εμαθα" = "No [questions], I got it" = wants_task.
        # Εξαίρεση: "δεν" πριν το "καταλαβα" = αρνητική κατανόηση.
        _has_understood = any(w in _lower_stripped for w in ["καταλαβ", "κατάλαβ", "εμαθ", "έμαθ"])
        _starts_with_no = _lower_stripped.startswith("οχι") or _lower_stripped.startswith("όχι")
        _has_negation = "δεν " in _lower_stripped or "δε " in _lower_stripped
        if _starts_with_no and _has_understood and not _has_negation:
            return "wants_task"

    # Ρητό αίτημα βοήθειας ενώ δουλεύει σε άσκηση = πάντα code_help, ΟΧΙ "other".
    # Παρατηρήθηκε: "Δεν ξερω πως να το κανω θελω βοηθεια" ταξινομήθηκε ως "other" (ασαφές)
    # από το μικρό LLM, πυροδοτώντας γενική διευκρινιστική ερώτηση αντί για βοήθεια —
    # παρόλο που η φράση είναι ήδη ξεκάθαρο αίτημα βοήθειας, δεν χρειάζεται διευκρίνιση.
    if task_started:
        _help_request_phrases = [
            "θελω βοηθεια", "θέλω βοήθεια", "χρειαζομαι βοηθεια", "χρειάζομαι βοήθεια",
            "δεν ξερω πως να", "δεν ξέρω πώς να", "δεν ξερω τι να κανω", "δεν ξέρω τι να κάνω",
            "δεν ξερω απο που", "δεν ξέρω από πού", "δεν μπορω να το κανω", "δεν μπορώ να το κάνω",
        ]
        if any(p in _lower_stripped for p in _help_request_phrases):
            return "code_help"

    # ── Gibberish / ακατανόητο input ──────────────────────────────────────────
    if _is_gibberish(stripped):
        return "other"

    # ── Πλαίσιο και κατηγορίες ανά φάση ────────────────────────────────────────
    if not profile_checked:
        context_hint = "Ο χρήστης αποκρίνεται στην ερώτηση αν έχει ξαναγράψει κώδικα."
        categories = (
            "profile_yes - ο χρήστης έχει εμπειρία κώδικα "
            "(ναι, ξέρω, έχω γράψει, προχωρημένος, γνωρίζω, yes, λίγο κλπ)\n"
            "profile_no  - ο χρήστης δεν έχει εμπειρία ή θέλει να μάθει από την αρχή "
            "(όχι, πρώτη φορά, αρχάριος, no, ποτέ, θελω να μαθω, θέλω να ξεκινήσω, "
            "να μαθω python, να ξεκινησω, αρχη κλπ)\n"
            "other       - ακατανόητο, άσχετο ή δεν απαντά στην ερώτηση (π.χ. γεια σου, ok)"
        )
    elif task_started:
        context_hint = "Ο χρήστης εργάζεται πάνω σε άσκηση Python."
        categories = (
            "wants_task      - ο χρήστης θέλει νέα άσκηση ή απαντά θετικά για συνέχεια\n"
            "                  (ναι, yes, οκ, πάμε, προχωράμε, αλλη ασκηση, δωσε μου ασκηση, καταλαβα, δεν εχω, αλλο κλπ)\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'αλλο' ή 'άλλο' (μόνη λέξη) = wants_task — ο μαθητής θέλει κάτι διαφορετικό\n"
            "                  ΟΧΙ wants_task αν το μήνυμα ρωτάει 'πώς' ή 'μπορώ να' για σύνταξη\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'καταλαβα, αλλα...' ή 'καταλαβα αλλά [ερώτηση]' = ΟΧΙ wants_task, είναι theory_question\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'πάμε στο επόμενο', 'θέλω επόμενη ενότητα', 'επόμενο κεφάλαιο' = ΟΧΙ wants_task, είναι advance_lesson\n"
            "theory_question - ο χρήστης κάνει ερώτηση θεωρίας, ζητά εξήγηση ή παράδειγμα\n"
            "                  (τι είναι, πώς, γιατί, δεν καταλαβα κάτι, εξήγησέ μου, που βοηθαει, που χρησιμοποιειται κλπ)\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'θεωρια' ή 'θεωρία' (μόνο, ή 'θελω θεωρια', 'δειξε θεωρια', 'θεωρια;') = theory_question\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'μπορώ να κάνω X;' ή 'μπορώ να εκτυπώσω X;' = theory_question\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'δεν καταλαβαίνω X' ή 'δεν καταλαβα πώς γίνεται X' = theory_question\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'καταλαβα, αλλα [ερώτηση]' = theory_question (ΟΧΙ wants_task)\n"
            "advance_lesson  - ο χρήστης θέλει να προχωρήσει στην επόμενη ΕΝΟΤΗΤΑ ή ΚΕΦΑΛΑΙΟ\n"
            "                  (θέλω επόμενη ενότητα, πάμε στο επόμενο, επόμενο κεφάλαιο, θέλω να προχωρήσω, next chapter)\n"
            "code_help       - ο χρήστης ζητά βοήθεια με τον κώδικά του, ρωτά για λάθος, ή επικολλά/δείχνει κώδικα\n"
            "                  ΣΗΜΑΝΤΙΚΟ: 'αυτος ειναι ο κωδικας μου' ή μήνυμα που περιέχει Python κώδικα = code_help\n"
            "other           - κάτι άλλο"
        )
    else:
        context_hint = "Ο χρήστης βρίσκεται στη φάση θεωρίας (δεν έχει ξεκινήσει άσκηση ακόμα)."
        categories = (
            "wants_task      - ο χρήστης δηλώνει ΘΕΤΙΚΑ ότι κατάλαβε και θέλει να προχωρήσει\n"
            "                  (προχωράμε, πάμε, έτοιμος, ναι, οκ, καταλαβα, εντάξει, δεν έχω απορία, δεν εχω, δωσε ασκηση, δωσε μου ασκηση κλπ)\n"
            "                  — ΣΗΜΑΝΤΙΚΟ: 'δεν εχω' μόνο = 'δεν έχω απορίες' = wants_task\n"
            "                  — ΣΗΜΑΝΤΙΚΟ: 'νομίζω τα κατάλαβα', 'νομιζω', 'νομίζω εντάξει' = wants_task\n"
            "                  — ΣΗΜΑΝΤΙΚΟ: 'Οχι αυτα τα καταλαβα' = 'αυτά τα κατάλαβα ήδη, συνέχισε' = wants_task\n"
            "                  — ΔΕΝ είναι wants_task: 'δεν νιωθω ετοιμος/η', 'δεν θελω', 'οχι δεν θελω' → other\n"
            "                  — ακόμα και με greeklish/ορθογραφικά λάθη: nai, katalava, proksorame κλπ\n"
            "theory_question - ο χρήστης κάνει ερώτηση ή ζητά εξήγηση/παράδειγμα για κάτι συγκεκριμένο\n"
            "                  (τι είναι X, πώς λειτουργεί X, γιατί X, δεν καταλαβα ΤΙ είναι X,\n"
            "                   δεν καταλαβα πώς δηλώνω X, εξήγησέ μου κλπ)\n"
            "                  ΚΛΕΙΔΙ: αν το μήνυμα περιέχει ερώτηση για ΣΥΓΚΕΚΡΙΜΕΝΗ έννοια → theory_question\n"
            "advance_lesson  - ο χρήστης θέλει να πάει στο επόμενο κεφάλαιο/μάθημα\n"
            "other           - δεν είναι έτοιμος ('δεν νιωθω ετοιμος', 'δεν θελω'), ακατανόητο, ή κάτι άλλο"
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
            if any(w in msg for w in ["μαθω", "μάθω", "ξεκινησω", "ξεκινήσω", "αρχαριος", "αρχάριος"]):
                return "profile_no"
            return "profile_no"
        if _wants_to_start_task(user_input):
            return "wants_task"
        if _is_question_message(user_input):
            return "code_help" if task_started else "theory_question"
        if any(t in (user_input or "").lower() for t in ["επόμενο", "επομενο", "next"]):
            return "advance_lesson"
        return "other"


def _answer_theory_question(user_input: str, lesson_title: str, theory: str, tone: str, current_lesson_id: int = 1) -> str:
    """Απαντά σε θεωρητική απορία βάσει ΟΛΗΣ της θεωρίας που έχει διδαχθεί μέχρι τώρα.
    Αν η ερώτηση αφορά μελλοντική ενότητα, λέει 'θα το δούμε σύντομα'.
    """
    # Χτίζουμε γνωστική βάση από όλες τις ενότητες που έχουν διδαχθεί
    all_lessons = lessons_content.get("lessons", [])
    covered_parts = []
    future_titles = []
    for l in all_lessons:
        t_raw = l.get("detailed_theory", "")
        t = t_raw.get("easy", "") if isinstance(t_raw, dict) else (t_raw or "")
        if l["id"] <= current_lesson_id:
            if t:
                covered_parts.append(f"Ενότητα {l['id']} - {l.get('title', '')}:\n{t}")
        else:
            future_titles.append(l.get("title", ""))

    knowledge_base = "\n\n---\n\n".join(covered_parts) if covered_parts else theory
    future_info = (
        f"Ενότητες που ΔΕΝ έχουμε καλύψει ακόμα: {', '.join(future_titles[:5])}.\n"
        if future_titles else ""
    )

    prompt_text = (
        f'Είσαι καθηγητής Python. Έχεις διδάξει στον μαθητή τα παρακάτω:\n\n'
        f'{knowledge_base}\n\n'
        f'{future_info}'
        f'Τρέχουσα ενότητα: "{lesson_title}"\n\n'
        f'Οδηγίες:\n'
        f'- Γράψε ΠΑΝΤΑ ΚΑΙ ΑΠΟΚΛΕΙΣΤΙΚΑ στα Ελληνικά — ΜΗΝ χρησιμοποιήσεις καμία άλλη γλώσσα ή αλφάβητο. Ύφος: {tone}.\n'
        f'- ΜΗΝ δώσεις άσκηση\n'
        f'- ΜΗΝ επαναλάβεις όλη τη θεωρία — μόνο ό,τι αφορά την ερώτηση\n'
        f'- Αν ρωτά για κάτι που έχει ΗΔΗ διδαχθεί (ακόμα και από ΠΡΟΗΓΟΥΜΕΝΗ ενότητα), απάντησε κανονικά\n'
        f'- Αν ρωτά για κάτι που ΔΕΝ έχει διδαχθεί ακόμα, πες: '
        f'"Πολύ καλή ερώτηση! Αυτό θα το δούμε σε επόμενη ενότητα — μείνε ψύχραιμος, θα γίνει ξεκάθαρο σύντομα."\n'
        f'- ΕΣΟΧΗ: η Python απαιτεί ΣΥΝΕΠΗ εσοχή. Το PEP 8 προτείνει 4 κενά αλλά 2 ή 3 συνεπή κενά επίσης λειτουργούν — το κλειδί είναι η ΣΥΝΕΠΕΙΑ στο ίδιο block.\n'
        f'- ΕΙΣΑΓΩΓΙΚΑ: μονά \' \' και διπλά " " είναι ΙΣΟΔΥΝΑΜΑ στην Python — και τα δύο ορίζουν string. Χρησιμοποιούμε ένα ή το άλλο ανάλογα με το αν το string περιέχει εισαγωγικά μέσα.\n'
        f'- Αν ρωτά για παράδειγμα, δώσε ΜΟΝΟ ένα σύντομο παράδειγμα (3-5 γραμμές κώδικα) — χωρίς πολλαπλές υπο-ενότητες, χωρίς full tutorial\n'
        f'- Κλείσε με μία σύντομη ερώτηση — εναλλάσσοντας κάθε φορά ανάμεσα σε: "Έγινε πιο ξεκάθαρο;", "Έχεις κι άλλη απορία;", "Βγαίνει νόημα;", "Τι άλλο σε μπερδεύει;". ΜΗΝ χρησιμοποιείς πάντα την ίδια φράση.\n\n'
        f'Ερώτηση μαθητή: {user_input}\n\nΑπάντηση:'
    )
    try:
        result = llm.invoke(prompt_text)
        return _strip_thinking(result.content)
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
    assessment_feedback: str = "",
    frequent_errors: list = None,
    avg_hints_per_task: float = 0.0,
    hint_count: int = 0,
) -> str:
    """Hint generator με δύο στρατηγικές:
    - Δομικά λάθη (syntax, undefined_name κλπ): deterministic hint (ακριβές, χωρίς hallucinations).
    - Assessment failures (σωστός κώδικας που δεν πληροί κριτήρια): LLM grounded στην εκφώνηση.
    Αν frequent_errors δοθεί, ο LLM λαμβάνει ως context τα συνήθη λάθη του μαθητή.
    """
    report = debug_report or ""
    has_structural_error = any(tag in report for tag in [
        "[DEBUG: ERROR]", "undefined_name", "type_mismatch",
        "missing_if", "missing_for", "missing_function",
        "missing_append", "missing_list", "missing_output",
        "missing_index", "print_as_variable",
        "missing_call", "method_error", "missing_accumulator", "literal_param_error",
        "print_func_ref", "wrong_arg_count", "wrong_list_type", "empty_print",
    ])
    if has_structural_error:
        # Deterministic για syntax/δομικά λάθη — αποφεύγει hallucinations
        return _generate_targeted_hint(debug_report, difficulty, assessment_feedback)

    # LLM για assessment-level failures (grounded στην εκφώνηση + semantic analysis)
    clean_fb = _clean_feedback(assessment_feedback)
    # Αν ο Debugger βρήκε semantic πρόβλημα, το συμπεριλαμβάνουμε ως επιπλέον πλαίσιο
    semantic_context = report.replace("[DEBUG: SEMANTIC]", "").strip() if "[DEBUG: SEMANTIC]" in report else ""
    # Συχνά λάθη μαθητή ως επιπλέον context για πιο στοχευμένο hint
    frequent_ctx = ""
    if frequent_errors:
        top = [_ERROR_CATEGORY_LABELS.get(e, e) for e in (frequent_errors or [])[:3]]
        frequent_ctx = f"Συνήθη λάθη αυτού του μαθητή: {', '.join(top)}.\n"
    # Κλιμάκωση hints: κάθε επόμενο hint πρέπει να είναι πιο συγκεκριμένο
    if hint_count >= 2:
        escalation_note = (
            f"ΣΗΜΑΝΤΙΚΟ: Έχουν δοθεί ήδη {hint_count} hints για αυτή την άσκηση. "
            "Αυτή τη φορά δώσε ΔΙΑΦΟΡΕΤΙΚΟ και πιο συγκεκριμένο hint — "
            "μην επαναλάβεις ό,τι ειπώθηκε ήδη, δείξε πιο ξεκάθαρη κατεύθυνση.\n"
        )
    elif hint_count == 1:
        escalation_note = (
            "ΣΗΜΑΝΤΙΚΟ: Έχει δοθεί ήδη 1 hint. "
            "Αυτή τη φορά δώσε ένα ΕΛΑΦΡΑ πιο συγκεκριμένο hint από το προηγούμενο.\n"
        )
    else:
        escalation_note = ""
    # Προσαρμογή ύφους υπόδειξης βάσει ιστορικού αποτελεσματικότητας hints
    if avg_hints_per_task >= 2.0:
        style_note = "Αυτός ο μαθητής χρειάζεται συνήθως πολλές υποδείξεις — δώσε πιο ξεκάθαρη, βήμα-βήμα κατεύθυνση.\n"
    elif 0 < avg_hints_per_task < 1.2:
        style_note = "Αυτός ο μαθητής συνήθως καταλαβαίνει με μια μόνο υπόδειξη — κράτα τη γενική και παιδαγωγική.\n"
    else:
        style_note = ""
    prompt_text = (
        f"Είσαι καθηγητής Python. Ο κώδικας του μαθητή είναι συντακτικά σωστός "
        f"αλλά δεν ικανοποιεί τα κριτήρια της άσκησης.\n\n"
        f"Εκφώνηση: {current_task}\n"
        f"Αξιολόγηση Assessor: {clean_fb}\n"
        + (f"Σημασιολογική ανάλυση Debugger: {semantic_context}\n" if semantic_context else "")
        + frequent_ctx
        + escalation_note
        + style_note
        + f"Επίπεδο κατανόησης μαθητή: {understanding_level}\n\n"
        f"Δώσε ΕΝΑ hint (1-2 προτάσεις) που να οδηγεί στη σωστή κατεύθυνση.\n"
        f"ΚΡΙΤΙΚΟΣ ΚΑΝΟΝΑΣ: Βασίσου ΑΠΟΚΛΕΙΣΤΙΚΑ στην 'Αξιολόγηση Assessor' και στη 'Σημασιολογική ανάλυση'.\n"
        f"ΜΗΝ υποθέσεις πρόσθετα προβλήματα που δεν αναφέρονται εκεί.\n"
        f"ΜΗΝ δώσεις τη λύση. ΜΗΝ γράψεις κώδικα.\n"
        f"Απευθύνσου ΠΑΝΤΑ στον μαθητή σε β' ενικό (π.χ. 'πρόσεξε', 'δες', 'δοκίμασε', 'κοίτα') — ΜΗΝ μιλάς για τον μαθητή σε τρίτο πρόσωπο.\n\nHint:"
    )
    try:
        result = llm.invoke(prompt_text)
        hint = _strip_thinking(result.content)
        return hint if hint else _generate_targeted_hint(debug_report, difficulty, assessment_feedback)
    except Exception:
        return _generate_targeted_hint(debug_report, difficulty, assessment_feedback)


def _enforce_brief(text: str, max_sentences: int = 2) -> str:
    """Περιορίζει σε max_sentences προτάσεις. Ασφαλιστική δικλείδα για brief=True: αν το LLM
    αγνοήσει την οδηγία 1-2 προτάσεων (π.χ. γράψει ολόκληρη εφευρημένη εκφώνηση άσκησης αντί
    για σύντομη εναρκτήρια φράση), κόβουμε στην έξοδο αντί να εμπιστευόμαστε μόνο το prompt."""
    # Σπάμε σε .!? ΚΑΙ σε newlines — το LLM συχνά γράφει πολλαπλές γραμμές (π.χ. εφευρημένη
    # εκφώνηση άσκησης) αντί για σύντομο intro, και δεν βάζει πάντα τελεία στο τέλος κάθε γραμμής.
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if p.strip()]
    if len(parts) <= max_sentences:
        return text.strip()
    return " ".join(parts[:max_sentences]).strip()

def _generate_mentor_response(
    context: str,
    indicative: str = "",
    tone: str = "φιλικά",
    must_not: str = "",
    brief: bool = False,
) -> str:
    """Παράγει ελεύθερη, φυσική απάντηση Mentor — ο LLM σκέφτεται μόνος του.

    Δίνουμε:
    - context: τι συμβαίνει (situation briefing) — ΟΧΙ hardcoded κείμενο
    - indicative: ενδεικτική φράση ως πρόταση, ΟΧΙ υποχρεωτικό template
    - must_not: τι να αποφύγει ρητά
    - brief=True: 1-2 προτάσεις μόνο (για intros πριν από theory/task)

    Επιστρέφει "" αν αποτύχει το LLM.
    """
    indicative_part = f"\nΕνδεικτικά (ΟΧΙ αυτολεξεί): {indicative}" if indicative else ""
    must_not_part = f"\nΑπόφυγε: {must_not}" if must_not else ""
    length_hint = "Γράψε ΜΟΝΟ 1-2 προτάσεις." if brief else "Γράψε φυσικά."

    prompt_text = (
        f"Είσαι ο Mentor, καθηγητής Python. Μιλάς άμεσα στον μαθητή.\n"
        f"Κατάσταση: {context}\n"
        f"Τόνος: {tone}{indicative_part}{must_not_part}\n\n"
        f"{length_hint} "
        f"Γράφε ΠΑΝΤΑ ΜΟΝΟ στα Ελληνικά — ΜΗΝ χρησιμοποιήσεις καμία άλλη γλώσσα ή αλφάβητο. "
        f"ΜΗΝ αρχίζεις με χαιρετισμό ('Γεια σου!', 'Γεια!', 'Χαίρε!') — είμαστε ήδη σε συνομιλία. "
        f"Χρησιμοποίησε ΠΑΝΤΑ β' ενικό (εσύ/σε/σου/δες/γράψε/δοκίμασε) — ΟΧΙ πληθυντικό (εσείς/σας/δείτε/γράψτε). "
        f"ΜΗΝ γράψεις tokens ([BUTTON:...], [ASSESSMENT:...], [HINT] κλπ) ή markdown headers (###). "
        f"Μόνο η ομιλία σου:\n"
    )
    try:
        result = llm.invoke(prompt_text)
        cleaned = _strip_thinking(result.content)
        return _enforce_brief(cleaned) if brief else cleaned
    except Exception:
        return ""

_INTRO_OUTRO_RE = re.compile(r"ΕΙΣΑΓΩΓΗ\s*:\s*(.*?)\s*ΚΛΕΙΣΙΜΟ\s*:\s*(.*)", re.DOTALL | re.IGNORECASE)

def _generate_mentor_intro_outro(
    context: str,
    intro_indicative: str = "",
    outro_indicative: str = "",
    tone: str = "φιλικά",
    intro_must_not: str = "",
    outro_must_not: str = "",
) -> tuple:
    """Σαν _generate_mentor_response, αλλά παράγει εισαγωγική ΚΑΙ κλείνουσα φράση σε ΕΝΑ LLM call
    αντί για δύο ξεχωριστά — μισή καθυστέρηση ανά turn, χωρίς να γίνει το περιεχόμενο deterministic.
    Το LLM διαβάζει όλο το context μία φορά και αποφασίζει μόνο του τι ταιριάζει και για τις δύο φράσεις.

    Επιστρέφει (intro, outro) — αν αποτύχει το parsing/LLM, intro παίρνει όλο το ελεύθερο κείμενο
    και outro μένει κενό (προτιμάμε να μη χαθεί εντελώς η απάντηση παρά να σπάσει η μορφοποίηση)."""
    intro_part = f"\n1. ΕΙΣΑΓΩΓΗ (πριν παρουσιαστεί το περιεχόμενο) — {intro_indicative or 'σύντομη εναρκτήρια φράση'}."
    intro_must_not_part = f" Απόφυγε: {intro_must_not}." if intro_must_not else ""
    outro_part = f"\n2. ΚΛΕΙΣΙΜΟ (μετά το περιεχόμενο, σαν σύντομη ερώτηση) — {outro_indicative or 'ρώτα αν έχει απορίες'}."
    outro_must_not_part = f" Απόφυγε: {outro_must_not}." if outro_must_not else ""

    prompt_text = (
        f"Είσαι ο Mentor, καθηγητής Python. Μιλάς άμεσα στον μαθητή.\n"
        f"Κατάσταση: {context}\n"
        f"Τόνος: {tone}\n\n"
        f"Χρειάζομαι ΔΥΟ σύντομες φράσεις (1 πρόταση η καθεμία), σκέψου κάθε μία ξεχωριστά "
        f"βάσει της κατάστασης παραπάνω:"
        f"{intro_part}{intro_must_not_part}"
        f"{outro_part}{outro_must_not_part}\n\n"
        f"Γράφε ΠΑΝΤΑ ΜΟΝΟ στα Ελληνικά — ΜΗΝ χρησιμοποιήσεις καμία άλλη γλώσσα ή αλφάβητο. "
        f"ΜΗΝ αρχίζεις με χαιρετισμό. Χρησιμοποίησε ΠΑΝΤΑ β' ενικό — ΟΧΙ πληθυντικό. "
        f"ΜΗΝ γράψεις tokens ([BUTTON:...], [ASSESSMENT:...], [HINT] κλπ) ή markdown headers (###).\n\n"
        f"Απάντησε ΑΚΡΙΒΩΣ σε αυτή τη μορφή, τίποτα άλλο πριν ή μετά:\n"
        f"ΕΙΣΑΓΩΓΗ: <η φράση σου>\n"
        f"ΚΛΕΙΣΙΜΟ: <η φράση σου>"
    )
    try:
        result = llm.invoke(prompt_text)
        cleaned = _strip_thinking(result.content)
        match = _INTRO_OUTRO_RE.search(cleaned)
        if match:
            return _enforce_brief(match.group(1).strip()), _enforce_brief(match.group(2).strip())
        return _enforce_brief(cleaned), ""
    except Exception:
        return "", ""

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
            if text and "```" not in text and not text.upper().startswith("CODE_SUBMISSION") and not text.startswith("Υποβολή κώδικα") and not text.startswith("__NO_SUBMISSION_TIMEOUT__"):
                recent.append(f"Μαθητής: {text[:120]}")

    if not recent:
        return ""

    history_text = "\n".join(recent)
    prompt = (
        f"Είσαι ο Mentor, καθηγητής Python. Γράψε 2-3 προτάσεις που συνοψίζουν "
        f"τι δουλέψατε με τον μαθητή στην προηγούμενη συνεδρία.\n"
        f"Απευθύνσου άμεσα στον μαθητή (β' πρόσωπο). Ύφος: φιλικό, φυσικό.\n"
        f"ΜΗΝ αρχίσεις με χαιρετισμό ('Γεια!', 'Γεια σου!', 'Χαίρε!' κλπ) — ξεκίνα απευθείας με την περίληψη.\n"
        f"ΜΗΝ αντιγράφεις αυτολεξεί τα μηνύματα. ΜΗΝ αναφέρεις ότι βλέπεις ιστορικό.\n"
        f"ΚΡΙΣΙΜΟ: Βασίσου ΑΠΟΚΛΕΙΣΤΙΚΑ σε ό,τι φαίνεται ξεκάθαρα στην παρακάτω συνομιλία. "
        f"ΜΗΝ υποθέσεις ή 'φαντάζεσαι' ότι ο μαθητής ολοκλήρωσε ή έλυσε κάτι — μόνο αν υπάρχει ρητή "
        f"επιβεβαίωση επιτυχίας (π.χ. 'Μπράβο!', 'Σωστά!', συγχαρητήρια μήνυμα). "
        f"Αν δεν είναι ξεκάθαρο ότι η άσκηση ολοκληρώθηκε επιτυχώς, γράψε μόνο ότι δουλεύατε πάνω σε αυτήν, "
        f"χωρίς να αναφέρεις αποτέλεσμα.\n\n"
        f"Ενότητα: {lesson_name}\n"
        f"Πρόσφατη συνομιλία:\n{history_text}\n\nΠερίληψη:"
    )
    try:
        result = await llm.ainvoke(prompt)
        recap = _strip_thinking(result.content)
        return recap if recap else ""
    except Exception:
        return ""


async def classify_pending_advance_intent_async(user_message: str, lesson_title: str) -> str:
    """Ταξινομεί την πρόθεση του χρήστη όταν υπάρχει pending_advance (η άσκηση λύθηκε σωστά
    αλλά το μάθημα δεν έχει ανεβεί ακόμα — περιμένουμε επιβεβαίωση ή αίτημα για επιπλέον άσκηση).

    Επιστρέφει:
      wants_advance        - ο χρήστης επιβεβαιώνει ότι θέλει να προχωρήσει στην επόμενη ενότητα
      wants_more_practice  - ο χρήστης θέλει άλλη άσκηση ΣΤΗΝ ΙΔΙΑ ενότητα πριν προχωρήσει
      other                - ερώτηση, σχόλιο, κάτι άλλο
    """
    prompt_text = (
        f'Ο μαθητής μόλις έλυσε σωστά μια άσκηση στην ενότητα "{lesson_title}".\n'
        f'Ο Mentor ρώτησε αν θέλει να προχωρήσει στην επόμενη ενότητα.\n\n'
        f'Κατηγοριοποίησε τι λέει ο μαθητής. Απάντησε ΜΟΝΟ με μία λέξη-κλειδί:\n\n'
        f'wants_advance       - αν επιβεβαιώνει ΡΗΤΑ ή ΣΙΩΠΗΡΑ ότι θέλει να προχωρήσει\n'
        f'                      (ναι, yes, ok, πάμε, προχωράμε, συνεχίζουμε, εντάξει, τέλεια, next,\n'
        f'                       υποθετω, μαλλον, ισως, οκ τελεια, καλα, αρχισε, εντάξει υποθετω)\n'
        f'                      ΔΕΝ είναι wants_advance αν το μήνυμα έχει ερώτηση ή αναφέρει "αλλη ασκηση"\n\n'
        f'wants_more_practice - θέλει άλλη άσκηση ΣΤΗΝ ΙΔΙΑ ενότητα πριν προχωρήσει\n'
        f'                      (αλλη ασκηση, θα ηθελα αλλη, βεβαιωθώ, μείνω λίγο, δεν είμαι έτοιμος,\n'
        f'                       μπορώ κι άλλη, θέλω να εξασκηθώ, ακόμα μια, στην ίδια ενότητα,\n'
        f'                       "αμα ειναι ευκολο" ΜΕ "άσκηση", κλπ)\n'
        f'                      ΣΗΜΑΝΤΙΚΟ: "οχι"/"όχι"/"no" ΜΟΝΟ (χωρίς άλλο κείμενο) = wants_more_practice\n'
        f'                      (απόρριψη της πρότασης "θέλεις να προχωρήσεις;" σημαίνει ότι θέλει να μείνει)\n\n'
        f'other               - ερώτηση θεωρίας, σχόλιο, κάτι άλλο\n'
        f'                      (τι είναι, πώς, γιατί, εξήγησέ μου, κλπ)\n'
        f'                      ΚΡΙΤΙΚΟΣ ΚΑΝΟΝΑΣ: Αν το μήνυμα περιέχει ερώτηση (τι, πώς, γιατί, ποιος)\n'
        f'                      ή αρχίζει με "πριν" → other, ακόμα κι αν περιέχει "προχωρίσουμε"\n\n'
        f'Παραδείγματα:\n'
        f'"ναι παμε" → wants_advance\n'
        f'"Είμαι" → wants_advance\n'
        f'"Έτοιμος" → wants_advance\n'
        f'"υποθετω" → wants_advance\n'
        f'"μαλλον" → wants_advance\n'
        f'"ισως" → wants_advance\n'
        f'"θα ήθελα άλλη μια άσκηση σε αυτή την ενότητα αμα είναι εύκολο" → wants_more_practice\n'
        f'"αλλη ασκηση" → wants_more_practice\n'
        f'"ακόμα μια" → wants_more_practice\n'
        f'"Άλλη μια άσκηση πριν προχωρίσουμε παρακαλώ" → wants_more_practice\n'
        f'"αλλη ασκηση πριν προχωρισουμε" → wants_more_practice\n'
        f'"μια ακομα πριν συνεχισουμε" → wants_more_practice\n'
        f'"Δε νιώθω έτοιμος" → wants_more_practice\n'
        f'"δεν νιώθω έτοιμος ακόμα" → wants_more_practice\n'
        f'"πριν προχωρίσουμε, τι είναι το index;" → other\n'
        f'"τι εννοείς;" → other\n\n'
        f'Μήνυμα μαθητή: "{user_message}"\n\nΛέξη-κλειδί:'
    )
    try:
        result = await llm_classify.ainvoke(prompt_text)
        intent = result.content.strip().lower().split()[0] if result.content.strip() else "other"
        return intent if intent in {"wants_advance", "wants_more_practice", "other"} else "other"
    except Exception:
        # Keyword fallback
        normalized = (user_message or "").lower().strip()
        # Ελέγχουμε πρώτα ερωτήσεις → other
        if any(q in normalized for q in ["τι ειναι", "τι είναι", "πως", "πώς", "γιατι", "γιατί", "?"]):
            return "other"
        # Απλό "οχι"/"no" χωρίς ερωτήσεις = wants_more_practice (δεν θέλει να προχωρήσει)
        if normalized in {"οχι", "όχι", "no", "οχι.", "όχι.", "no."}:
            return "wants_more_practice"
        # "αλλη ασκηση πριν προχωρισουμε" / "μια ακομα πριν συνεχισουμε" = wants_more_practice
        _has_exercise_word = any(w in normalized for w in ["ασκηση", "άσκηση", "ασκησ"])
        _has_another_word = any(w in normalized for w in ["αλλη", "άλλη", "ακομα", "ακόμα", "επιπλεον"])
        if _has_exercise_word and _has_another_word:
            return "wants_more_practice"
        practice_words = ["βεβαιωθ", "εξάσκ", "εξασκ", "ίδια ενότητα", "ιδια ενοτητα",
                          "μεινω", "μείνω", "νιωθ", "νιώθ", "δε νιω", "δεν νιω"]
        if any(w in normalized for w in practice_words):
            return "wants_more_practice"
        affirmatives = ["ναι", "nai", "yes", "ok", "παμε", "πάμε", "προχωράμε",
                        "προχωραμε", "εντάξει", "εντάξει", "τέλεια", "τελεια", "next",
                        "ειμαι", "είμαι", "ετοιμ", "έτοιμ",
                        "υποθετω", "μαλλον", "ισως", "καλα"]
        if any(w in normalized for w in affirmatives):
            return "wants_advance"
        return "other"

async def classify_profile_async(user_input: str) -> str:
    """Ταξινομεί αν ο χρήστης είναι expert ή beginner βάσει LLM.
    Επιστρέφει 'unclear' αν το input είναι gibberish — ο mentor θα ξαναρωτήσει.
    Επιστρέφει 'ambiguous' αν ο χρήστης απάντησε αλλά χωρίς να διευκρινίσει ποιο από τα δύο
    (π.χ. ένα γυμνό 'ναι' σε ερώτηση τύπου 'Α ή Β;') — ο mentor θα κάνει soft-default σε beginner.
    Fallback σε keyword matching αν το LLM αποτύχει."""
    if _is_gibberish(user_input):
        return "unclear"
    # Bare affirmatives ("ναι", "ok" κλπ) είναι ΠΑΝΤΑ ασαφή σε ερώτηση τύπου "Α ή Β;" —
    # δεν λέμε στο LLM να το κρίνει, γιατί μπορεί validly να τα ερμηνεύσει ως "beginner"
    # ("ναι, πρώτη μου φορά") και να μην πυροδοτηθεί το profile_soft_defaulted.
    _bare_ambiguous = {"ναι", "nai", "yes", "ok", "οκ", "εντάξει", "ενταξει", "ναι.", "yes."}
    if (user_input or "").strip().lower() in _bare_ambiguous:
        return "ambiguous"
    prompt_text = (
        'Ο χρήστης αποκρίνεται στην ερώτηση '
        '"Έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;" (ερώτηση τύπου "Α ή Β;", ΟΧΙ ναι/όχι).\n'
        'Απάντησε ΜΟΝΟ με: expert, beginner, ambiguous, ή unclear\n\n'
        'ΚΑΝΟΝΑΣ: Οποιοσδήποτε βαθμός εμπειρίας — ακόμα και ελάχιστη επαφή με κώδικα — = expert.\n'
        'Μόνο η ΑΠΟΛΥΤΗ απειρία (πρώτη φορά, ποτέ, δεν ξέρω τίποτα) = beginner.\n'
        'ΣΗΜΑΝΤΙΚΟ: Ένα γυμνό "ναι"/"yes"/"ok"/"εντάξει" ΧΩΡΙΣ καμία άλλη λεπτομέρεια ΔΕΝ διευκρινίζει '
        'ποιο από τα δύο (έμπειρος ή αρχάριος) εννοεί ο χρήστης — αυτό είναι ambiguous, ΟΧΙ expert.\n'
        'Αν το μήνυμα δεν απαντά καθόλου στην ερώτηση ή είναι ακατανόητο → unclear\n\n'
        'Παραδείγματα:\n'
        '"θελω να μαθω python" → beginner\n'
        '"θελω να ξεκινησω" → beginner\n'
        '"να μαθω προγραμματισμο" → beginner\n'
        '"ναι έχω εμπειρία" → expert\n'
        '"εχω ασχοληθει γενικα με κωδικα" → expert\n'
        '"εχω δουλεψει λιγο με python" → expert\n'
        '"ξερω λιγο" → expert\n'
        '"λίγο, αλλά ξέρω βασικά" → expert\n'
        '"έχω γράψει κάποια πράγματα" → expert\n'
        '"όχι, πρώτη φορά" → beginner\n'
        '"δεν ξέρω τίποτα" → beginner\n'
        '"ποτέ μου" → beginner\n'
        '"ναι" (μόνο, χωρίς τίποτα άλλο) → ambiguous\n'
        '"yes" (μόνο) → ambiguous\n'
        '"ok" / "οκ" / "εντάξει" (μόνο) → ambiguous\n'
        '"esghh" / "qwerty" / τυχαία γράμματα → unclear\n'
        '"τι;" / "δεν καταλαβαίνω" / ερώτηση αντί απάντησης → unclear\n\n'
        f'Μήνυμα: "{user_input}"\n\nΑπάντηση:'
    )
    try:
        result = await llm_classify.ainvoke(prompt_text)
        answer = result.content.strip().lower().split()[0]
        if "unclear" in answer:
            return "unclear"
        if "ambiguous" in answer:
            return "ambiguous"
        return "expert" if "expert" in answer else "beginner"
    except Exception:
        normalized = (user_input or "").strip().lower()
        if normalized in {"ναι", "nai", "yes", "ok", "οκ", "εντάξει", "ενταξει"}:
            return "ambiguous"
        if any(w in normalized for w in [
            "ναι", "έχω", "εχω", "γνωρίζω", "γνωριζω", "προχωρημένος",
            "ξέρω", "ξερω", "yes", "λίγο", "λιγο", "ασχολ", "δουλεψ", "γραψ"
        ]):
            return "expert"
        return "beginner"

# ── Deterministic helpers ────────────────────────────────────────────────────

def _generate_targeted_hint(debug_report: str, difficulty: str, assessment_feedback: str = "") -> str:
    """Μετατρέπει το τεχνικό debug_report σε παιδαγωγικό hint για τον χρήστη.
    Δεν αποκαλύπτει ακριβώς το λάθος — δίνει κατεύθυνση για να το βρει ο μαθητής μόνος του."""
    report = debug_report or ""

    if "[DEBUG: ERROR]" in report:
        error_part = report.replace("[DEBUG: ERROR]", "").strip().rstrip(".")

        # Συγκεκριμένο: 'else if' αντί για 'elif'
        if "else_if_error" in error_part:
            return (
                "Στην Python υπάρχει ειδική λέξη-κλειδί για πολλαπλές συνθήκες — "
                "δεν χρησιμοποιούμε 'else if' όπως σε άλλες γλώσσες. "
                "Ρίξε μια ματιά στη θεωρία για if/elif/else."
            )
        # Λείπει άνω-κάτω τελεία ή λάθος σύνταξη δομής ελέγχου
        if "expected ':'" in error_part:
            return (
                "Κάτι λείπει από τη σύνταξη κάποιας δομής ελέγχου σου. "
                "Έλεγξε αν κάθε if/elif/else/for/while τελειώνει με τον σωστό τρόπο."
            )
        # Λανθασμένη εσοχή
        if "unexpected indent" in error_part or "unindent" in error_part:
            return (
                "Υπάρχει πρόβλημα με την εσοχή (indentation) κάποιας γραμμής. "
                "Η Python είναι πολύ ευαίσθητη στα κενά μπροστά από κάθε γραμμή — "
                "σιγουρέψου ότι χρησιμοποιείς 4 κενά ή Tab με συνέπεια."
            )
        # Literal τιμές ως ονόματα παραμέτρων (π.χ. def process(1, 4):)
        if "literal_param_error" in error_part:
            return (
                "Οι παράμετροι σε μια def πρέπει να είναι ονόματα (π.χ. a, b), "
                "όχι τιμές (π.χ. 1, 4). "
                "Γράψε: def process(a, b): — και μετά κάλεσέ τη με τιμές: process(1, 4)."
            )
        # Ανεξάρτητα invalid syntax
        if "invalid syntax" in error_part:
            line_match = re.search(r'γραμμή (\d+)', error_part)
            line_hint = f" στη γραμμή {line_match.group(1)}" if line_match else ""
            return (
                f"Υπάρχει συντακτικό λάθος{line_hint} στον κώδικά σου. "
                "Κοίτα εκεί προσεκτικά — ελέγξε αν λείπει `=`, `:`, εισαγωγικό ή παρένθεση."
            )
        # Ανοιχτό εισαγωγικό/παρένθεση
        if "EOL" in error_part or "EOF" in error_part or "unterminated" in error_part:
            return (
                "Φαίνεται ότι κάτι δεν έχει κλείσει σωστά. "
                "Έλεγξε αν κάθε εισαγωγικό ή παρένθεση που ανοίγεις κλείνει και αντίστοιχα."
            )
        # Ζεύγος συμβόλου (unmatched paren κλπ)
        if "unmatched" in error_part:
            return (
                "Κάποιο σύμβολο (παρένθεση ή εισαγωγικό) δεν έχει το ζεύγος του. "
                "Ελέγξε προσεκτικά αν κάθε `(` έχει το `)` του και κάθε `\"` το αντίστοιχο κλείσιμο."
            )
        # Γενική περίπτωση — χωρίς τεχνικές λεπτομέρειες
        return (
            "Υπάρχει συντακτικό λάθος. "
            "Διάβασε τον κώδικά σου προσεκτικά και έλεγξε τη σύνταξη — "
            "συχνά φτάνει να τον διαβάσεις μια φορά αργά για να το εντοπίσεις."
        )

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

    if "missing_index" in report:
        return (
            "Λείπει η πρόσβαση σε στοιχείο λίστας με index. "
            "Για να πάρεις το πρώτο στοιχείο γράψε `λίστα[0]`, για το δεύτερο `λίστα[1]` κ.ο.κ."
        )

    if "empty_list" in report:
        return (
            "Η λίστα σου είναι άδεια `[]` — δεν έχει κανένα στοιχείο μέσα. "
            "Πρόσθεσε τα στοιχεία απευθείας, π.χ. `colors = [\"red\", \"green\", \"blue\"]`."
        )

    if "wrong_index" in report:
        return (
            "Ο index που χρησιμοποιείς δεν είναι ο σωστός. "
            "Θυμήσου: `λίστα[0]` δίνει το **πρώτο** στοιχείο, `λίστα[1]` το δεύτερο κ.ο.κ. — "
            "η αρίθμηση ξεκινά από 0, όχι από 1."
        )

    if "print_as_variable" in report:
        extra = ""
        # Αν υπάρχουν ΚΑΙ type issues στο assessment feedback, τα αναφέρουμε μαζί
        if assessment_feedback and "TYPE_ERROR" in assessment_feedback:
            extra = " Επίσης, έλεγξε τους τύπους των μεταβλητών σου (αριθμός vs string)."
        return (
            "Πρόσεξε τη διαφορά: `print = (...)` αναθέτει μια τιμή στη μεταβλητή `print` — "
            "αυτό \"σπάει\" τη συνάρτηση! Για να εκτυπώσεις τιμές χρησιμοποίησε παρενθέσεις: "
            f"`print(μεταβλητή1, μεταβλητή2, ...)`{extra}"
        )

    if "method_error" in report:
        return (
            "Δεν υπάρχει μέθοδος .len() στις λίστες. "
            "Για να βρεις το μήκος μιας λίστας γράψε len(λίστα) — όχι λίστα.len()."
        )

    if "missing_call" in report:
        return (
            "Η συνάρτηση ορίζεται σωστά, αλλά δεν καλείται ποτέ. "
            "Πρόσθεσε μια κλήση της συνάρτησης έξω από αυτήν και τύπωσε το αποτέλεσμα με print()."
        )

    if "missing_accumulator" in report:
        return (
            "Χρειάζεσαι έναν αθροιστή — μια μεταβλητή που ξεκινά από 0 "
            "και αυξάνεται σε κάθε επανάληψη με `+=`. "
            "Επίσης, κάνε loop πάνω στη λίστα, όχι σε range()."
        )

    if "print_func_ref" in report:
        return (
            "Το print() τυπώνει τη συνάρτηση ως αντικείμενο αντί να την εκτελεί. "
            "Πρέπει να καλέσεις τη συνάρτηση μέσα στο print — "
            "γράψε print(process(τιμή1, τιμή2)) αντί print(process)."
        )

    if "wrong_arg_count" in report:
        return (
            "Η συνάρτηση καλείται χωρίς τα απαραίτητα ορίσματα. "
            "Θυμήσου: κάλεσέ τη περνώντας τις τιμές, π.χ. process(3, 5) — "
            "και τύπωσε το αποτέλεσμα: print(process(3, 5))."
        )

    if "wrong_list_type" in report:
        return (
            "Η λίστα σου περιέχει κείμενο (strings σε εισαγωγικά) αντί για αριθμούς. "
            "Ορίσε αριθμούς χωρίς εισαγωγικά, π.χ. numbers = [1, 2, 3]."
        )

    if "empty_print" in report:
        return (
            "Το print() σου δεν έχει τίποτα μέσα — τυπώνει κενή γραμμή. "
            "Πρόσθεσε αυτό που θέλεις να εμφανιστεί: print('κείμενο') ή print(μεταβλητή)."
        )

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

def _is_negative_after_theory(text: str) -> bool:
    """True αν ο μαθητής απάντησε αρνητικά ('οχι', 'δεν κατάλαβα' κλπ) — συνήθως μετά από εξήγηση θεωρίας."""
    normalized = (text or "").strip().lower()
    if normalized in {"οχι", "όχι", "no", "οχι.", "όχι.", "no."}:
        return True
    return any(w in normalized for w in [
        "δεν καταλαβ", "δεν κατάλαβ",
        "δεν εγινε", "δεν έγινε",
        "δεν βγαζ", "δεν βγάζ",
        "δεν καταλαβαιν", "δεν καταλαβαίν",
    ])

def _chapter_header(lesson):
    lesson_id = lesson.get("id", "?")
    lesson_title = lesson.get("title", "Ενότητα")
    return f"Κεφάλαιο {lesson_id}: {lesson_title}"

def _resolve_placeholders(text: str, replacements: dict) -> str:
    resolved_text = text or ""
    for key, value in replacements.items():
        resolved_text = resolved_text.replace("{" + key + "}", str(value))
    return resolved_text

def generate_random_task(lesson, difficulty, current_task=None):
    templates_dict = lesson.get("task_templates", {})
    templates = templates_dict.get(difficulty, templates_dict.get("easy", []))

    if not templates:
        return {
            "task_text": "Γράψε ένα απλό πρόγραμμα Python.",
            "rendered_criteria": lesson.get("success_criteria", []),
        }

    # Αν υπάρχουν πολλά templates, αποφεύγουμε το template που παράγει ίδια άσκηση
    available = templates
    if current_task and len(templates) > 1:
        # Κρατάμε templates που δεν αρχίζουν με τα ίδια 30 πρώτα γράμματα με την τρέχουσα άσκηση
        task_prefix = current_task[:30]
        other = [t for t in templates if not t[:30] == task_prefix]
        if other:
            available = other

    template = random.choice(available)
    possible_values = lesson.get("possible_values", {})
    replacements = {}

    for key, options in possible_values.items():
        if "{" + key + "}" in template and options:
            replacements[key] = random.choice(options)

    task_text = _resolve_placeholders(template, replacements)

    raw_criteria = lesson.get("success_criteria", [])
    if isinstance(raw_criteria, dict):
        raw_criteria = raw_criteria.get(difficulty, raw_criteria.get("easy", []))
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
    profile_soft_defaulted = state.get("profile_soft_defaulted", False)
    awaiting_questions = state.get("awaiting_questions", False)
    event_type = state.get("event_type", "")
    task_started = state.get("task_started", False)
    is_correct = state.get("is_correct", False)
    debug_report = state.get("debug_report", "")
    assessment_decision = state.get("assessment_decision", "")
    assessment_feedback = state.get("assessment_feedback", "")
    performance_summary = state.get("performance_summary", "{}")
    # Εξάγουμε frequent_error_categories για προσωποποιημένα μηνύματα
    try:
        _perf = json.loads(performance_summary) if isinstance(performance_summary, str) else (performance_summary or {})
        frequent_errors = _perf.get("frequent_error_categories", [])
    except Exception:
        frequent_errors = []
    last_assessment_decision = _extract_last_assessment_decision(messages)
    experience = state.get("experience_level", "beginner")
    difficulty_probe_direction = state.get("difficulty_probe_direction", "")
    attempts = state.get("attempts_count", 0)
    hint_count = state.get("hint_count", 0)
    understanding_level = state.get("understanding_level", "developing")
    avg_hints_per_task = float(state.get("avg_hints_per_task", 0.0))
    frustration_score = state.get("frustration_score", 0)

    # Αυτόματη προσαρμογή δυσκολίας — ακολουθεί probe direction ώστε θεωρία και task να συμφωνούν
    if attempts >= 3 or difficulty_probe_direction == "downgrade":
        difficulty = "easy"
    elif difficulty_probe_direction == "upgrade" or experience == "expert":
        difficulty = "hard"
    else:
        difficulty = "easy"

    lesson = pick_lesson(state)
    chapter_header = _chapter_header(lesson)
    lesson_title = lesson.get("title", "")
    theory_raw = lesson.get("detailed_theory", "")
    if isinstance(theory_raw, dict):
        theory = theory_raw.get(difficulty, theory_raw.get("easy", ""))
    else:
        theory = theory_raw

    # Τίτλος επόμενης ενότητας (για το μήνυμα επιτυχίας)
    all_lessons = lessons_content.get("lessons", [])
    current_lesson_id = state.get("current_lesson_id", 1)
    next_lesson_obj = next((l for l in all_lessons if l["id"] == current_lesson_id + 1), None)
    next_lesson_title = next_lesson_obj.get("title", "επόμενη ενότητα") if next_lesson_obj else "επόμενη ενότητα"
    task = state.get("current_task")
    success_criteria = state.get("success_criteria")

    if not task or success_criteria is None:
        task_payload = generate_random_task(lesson, difficulty, current_task=state.get("previous_task"))
        task = task_payload["task_text"]
        success_criteria = task_payload["rendered_criteria"]

    # Αν η εκφώνηση απαιτεί hard concepts (return/παράμετρ), δείχνουμε hard θεωρία
    # ακόμα κι αν ο difficulty υπολογίστηκε ως "easy" (π.χ. λόγω πολλών αποτυχιών)
    if isinstance(theory_raw, dict) and any(
        kw in (task or "").lower()
        for kw in ["return", "παράμετρ", "επιστρέφ", "ορίσματ"]
    ):
        theory = theory_raw.get("hard", theory)

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

    student_code = state.get("student_code", "")

    # ── LLM Intent Classification ────────────────────────────────────────────
    # Παρακάμπτουμε την ταξινόμηση για deterministic events που δεν εξαρτώνται από το user input
    if (
        is_first_login  # Πρώτος γύρος: πάντα deterministic, δεν ταξινομούμε το user input
        or event_type in {"no_submission_timeout", "lesson_advanced", "same_chapter_practice"}
        or is_correct
    ):
        intent = "other"
    else:
        intent = _classify_intent(user_input, profile_checked, task_started)
        # Αρνητική απάντηση σε awaiting_questions context: ο LLM ερμηνεύει "οχι" ως wants_task
        # (= "δεν θέλω άλλη εξήγηση, δώσε άσκηση"), αλλά πρέπει να πάει σε "other" →
        # _is_negative_after_theory handler που ρωτά τι ακριβώς δεν έγινε ξεκάθαρο.
        if awaiting_questions and intent == "wants_task" and _is_negative_after_theory(user_input):
            intent = "other"

    wants_task = intent == "wants_task"
    # Αν υπάρχει κώδικας και ο μαθητής δεν πέρασε, ΔΕΝ ξαναπαρουσιάζουμε την άσκηση
    if student_code and task_started and not is_correct:
        wants_task = False
    # Αν η θεωρία έχει ήδη δειχθεί (awaiting_questions=True) και ο μαθητής ΔΕΝ έκανε ερώτηση,
    # θεωρούμε ότι είναι έτοιμος για άσκηση — αποφεύγει την επανεμφάνιση θεωρίας.
    # Εξαίρεση: "δεν νιωθω ετοιμος/η" — ο μαθητής δεν είναι έτοιμος, δεν πρέπει να πάρει άσκηση.
    _msg_lower_for_ready_check = (user_input or "").lower()
    _is_not_ready_msg = any(p in _msg_lower_for_ready_check for p in _NOT_READY_PATTERNS)
    # Αν η θεωρία έχει ήδη δειχθεί και ο μαθητής απάντησε με κάτι ουδέτερο/θετικό (όχι ερώτηση,
    # όχι "δεν είμαι έτοιμος", όχι άσχετο σχόλιο → intent="other"), θεωρούμε ότι είναι έτοιμος.
    # Εξαίρεση: intent="other" = άσχετο σχόλιο → ΔΕΝ μετατρέπουμε αυτόματα, πάμε στον freeform handler.
    if awaiting_questions and not wants_task and intent not in {"theory_question", "code_help", "other"} and not _is_not_ready_msg:
        wants_task = True
    next_chapter_request = intent == "advance_lesson"
    menu_choice = intent if intent.startswith("menu_") else None  # "menu_1", "menu_2", "menu_3" ή None

    # ── Current Context (για το system prompt του LLM fallback) ─────────────
    current_context = ""
    if is_first_login and not profile_checked:
        current_context = "Ο μαθητής συνδέεται για πρώτη φορά. Συστήσου και κάνε profile check για να δούμε αν είναι αρχάριος ή προχωρημένος."
    elif is_first_login and profile_checked:
        if experience == "beginner":
            current_context = f"Ο μαθητής μόλις είπε ότι δεν έχει εμπειρία. Καλωσόρισέ τον θερμά, πες ότι θα τον οδηγήσεις βήμα-βήμα, και παρουσίασε τη θεωρία '{lesson_title}'."
        else:
            current_context = f"Ο μαθητής έχει κάποια εμπειρία. Χαιρέτησέ τον σύντομα και παρουσίασε τη θεωρία '{lesson_title}'."
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
        # ΜΟΝΟ ΕΔΩ κρατάμε structured fallback — είναι το πρώτο μήνυμα επαφής
        welcome = _generate_mentor_response(
            context="Νέος μαθητής συνδέεται για πρώτη φορά. Καλωσόρισέ τον και ρώτα αν έχει ξαναγράψει κώδικα.",
            indicative="π.χ. 'Γεια σου! Είμαι ο Mentor σου — πριν ξεκινήσουμε, έχεις γράψει ξανά κώδικα;'",
            tone="ζεστά, φιλικά, ενθαρρυντικά"
        )
        deterministic_content = welcome or (
            "Καλώς ήρθες! Είμαι εδώ για να σε βοηθήσω να μάθεις Python.\n\n"
            "Πριν ξεκινήσουμε, έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
        )
    elif is_first_login and profile_checked:
        # Μία LLM κλήση παράγει ΚΑΙ την εισαγωγή ΚΑΙ το κλείσιμο γύρω από τη θεωρία (verbatim,
        # ανάμεσά τους) — αντί για δύο ξεχωριστά calls. Το context της εισαγωγής διαφέρει ανάλογα
        # με soft_defaulted, το κλείσιμο είναι το ίδιο και στις δύο περιπτώσεις.
        if profile_soft_defaulted:
            # Η απάντηση στο profile-check ήταν ασαφής (π.χ. γυμνό "ναι" σε ερώτηση "Α ή Β;").
            # Soft-default σε beginner — το LLM ΜΟΝΟ εξηγεί την απόφαση, χωρίς δεύτερο γύρισμα.
            # ΔΕΝ αναφέρουμε "θεωρία ακολουθεί" στο context — competing instruction που οδηγεί το LLM
            # σε generic "Τέλεια!" αντί για την ουσιαστική εξήγηση.
            _intro_ctx = (
                f"Ο μαθητής απάντησε ασαφώς ('{user_input}') στην ερώτηση αν έχει εμπειρία. "
                f"Πες του φιλικά ότι μιας και δεν ήταν ξεκάθαρο ξεκινάτε από τα βασικά για σιγουριά, "
                f"και ότι αν φανεί ότι τα έχει ήδη θα ανέβει γρήγορα το επίπεδο δυσκολίας."
            )
            _intro_indicative = (
                "π.χ. 'Δεν ήταν απόλυτα ξεκάθαρο, οπότε ξεκινάμε από τα βασικά — "
                "αν δω ότι τα έχεις ήδη, σε ανεβάζω επίπεδο γρήγορα!'"
            )
            _intro_must_not = "περιγράψεις το περιεχόμενο της θεωρίας ή δώσεις άσκηση"
        else:
            _intro_ctx = f"Μόλις έμαθες ότι ο μαθητής είναι {'αρχάριος' if experience == 'beginner' else 'έχει εμπειρία'}. Ξεκινάς να παρουσιάσεις τη θεωρία '{lesson_title}' που ακολουθεί αμέσως."
            _intro_indicative = "π.χ. 'Τέλεια! Ξεκινάμε:' ή 'Καλώς! Ας δούμε:'"
            _intro_must_not = "εξηγήσεις ή περιγράψεις τη θεωρία — αυτή εμφανίζεται αμέσως μετά"
        intro, outro = _generate_mentor_intro_outro(
            context=f"{_intro_ctx} Μετά τη θεωρία (που ο κώδικας παρουσιάζει αυτούσια) θα χρειαστεί και μια κλείνουσα ερώτηση για απορίες.",
            intro_indicative=_intro_indicative,
            outro_indicative="π.χ. 'Έχεις κάποια απορία; Ή πάμε σε άσκηση;'",
            tone="φιλικά, ζεστά",
            intro_must_not=_intro_must_not,
            outro_must_not="επαναλάβεις ή επεκτείνεις τη θεωρία",
        )
        deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
    elif event_type == "lesson_advanced":
        intro, outro = _generate_mentor_intro_outro(
            context=f"Ο μαθητής πέρασε στο κεφάλαιο '{lesson_title}'. Ανακοίνωσε το ξεκίνημα, η θεωρία ακολουθεί αμέσως αυτούσια· μετά χρειάζεται και κλείνουσα ερώτηση για απορίες.",
            intro_indicative="π.χ. 'Πολύ ωραία! Νέα ενότητα:' ή 'Εξαιρετικά! Πάμε στο επόμενο:'",
            outro_indicative="π.χ. 'Έχεις ερωτήσεις; Αν είσαι έτοιμος, πάμε!'",
            tone="ενθαρρυντικά, ζωηρά",
            intro_must_not="εξηγήσεις ή αναφέρεσαι στο περιεχόμενο της θεωρίας — αυτή ακολουθεί",
            outro_must_not="επαναλάβεις ή επεκτείνεις τη θεωρία",
        )
        deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
    elif event_type == "same_chapter_practice":
        # Ο μαθητής ζήτησε επιπλέον άσκηση στο ΙΔΙΟ κεφάλαιο πριν προχωρήσει —
        # δίνουμε κατευθείαν νέα άσκηση χωρίς θεωρία, χωρίς just_advanced path.
        task_intro = _generate_mentor_response(
            context=f"Ο μαθητής ζητά επιπλέον άσκηση στην ενότητα '{lesson_title}' για να εδραιώσει την κατανόηση. Η εκφώνηση ακολουθεί αμέσως — γράψε μόνο μια σύντομη εναρκτήρια φράση.",
            indicative="π.χ. 'Φυσικά! Να μια ακόμα:' ή 'Αμέσως!'",
            tone="φιλικά, ενθαρρυντικά",
            brief=True,
            must_not="γράψεις οτιδήποτε που μοιάζει με εκφώνηση άσκησης — αυτή ακολουθεί αυτούσια αμέσως μετά"
        )
        deterministic_content = f"{task_intro}\n\n{task}\n\n[BUTTON:START_TASK]"
    elif event_type == "no_submission_timeout":
        hint_stage = min(hint_count, 2)
        prev_mistake_ctx = f" Προηγούμενο λάθος: {assessment_feedback}." if assessment_feedback and hint_stage > 0 else ""
        timeout_contexts = [
            f"Ο μαθητής δεν έχει γράψει τίποτα για 40+ δευτερόλεπτα. Άσκηση: '{task}'. Ενθάρρυνέ τον — ΜΗΝ δώσεις hint ακόμα.",
            f"Ο μαθητής αργεί αρκετά. Άσκηση: '{task}'.{prev_mistake_ctx} Δώσε ΕΝΑ hint για το ΤΙ χρειάζεται χωρίς κώδικα.",
            f"Ο μαθητής συνεχίζει να δυσκολεύεται. Άσκηση: '{task}'.{prev_mistake_ctx} Δώσε πιο συγκεκριμένη υπόδειξη για τη δομή.",
        ]
        timeout_indicatives = [
            "π.χ. 'Μην ανησυχείς, ξεκίνα με το πρώτο βήμα!'",
            "π.χ. 'Σκέψου τι εντολή χρησιμοποιείς για να...'",
            "π.χ. 'Για αυτή την άσκηση χρειάζεσαι [δομή]. Θυμάσαι πώς γράφεται;'",
        ]
        timeout_msg = _generate_mentor_response(
            context=timeout_contexts[hint_stage],
            indicative=timeout_indicatives[hint_stage],
            tone="ηρεμιστικά, ενθαρρυντικά",
            must_not="γράψεις πλήρη λύση ή κώδικα"
        )
        deterministic_content = timeout_msg or f"Κοίτα ξανά την εκφώνηση: {task}"
    elif menu_choice == "menu_1":
        intro, outro = _generate_mentor_intro_outro(
            context=f"Ο μαθητής ζητά επανάληψη της θεωρίας '{lesson_title}' — η θεωρία ακολουθεί αμέσως αυτούσια· μετά χρειάζεται και κλείνουσα ερώτηση.",
            intro_indicative="π.χ. 'Φυσικά! Να:' ή 'Ορίστε:'",
            outro_indicative="π.χ. 'Πιο ξεκάθαρο; Ή πάμε σε άσκηση!'",
            tone="φιλικά",
            intro_must_not="εξηγήσεις ή αναφέρεσαι στο περιεχόμενο της θεωρίας — αυτή ακολουθεί",
            outro_must_not="επαναλάβεις ή επεκτείνεις τη θεωρία",
        )
        deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
    elif menu_choice == "menu_2":
        task_intro = _generate_mentor_response(
            context=f"Δίνεις νέα άσκηση στον μαθητή στην ενότητα '{lesson_title}'. Η εκφώνηση ακολουθεί αμέσως — γράψε μόνο μια σύντομη εναρκτήρια φράση.",
            indicative="π.χ. 'Ορίστε!' ή 'Να:' ή 'Πάμε!'",
            tone="φιλικά, ζωηρά",
            brief=True,
            must_not="γράψεις οτιδήποτε που μοιάζει με εκφώνηση άσκησης — αυτή ακολουθεί αυτούσια αμέσως μετά"
        )
        deterministic_content = f"{task_intro}\n\n{task}\n\n[BUTTON:START_TASK]"
    elif menu_choice == "menu_3":
        hint_text = _generate_hint_with_llm(debug_report, task, difficulty, understanding_level, assessment_feedback, frequent_errors, avg_hints_per_task, hint_count)
        hint_intro, hint_outro = _generate_mentor_intro_outro(
            context=f"Ο μαθητής ζήτησε hint για την άσκηση '{lesson_title}'. Μια υπόδειξη ακολουθεί αμέσως αυτούσια· μετά χρειάζεται ενθάρρυνση να τη δοκιμάσει.",
            intro_indicative="π.χ. 'Κοίτα εδώ:' ή 'Ορίστε μια υπόδειξη:'",
            outro_indicative="π.χ. 'Δοκίμασε και πες μου!' ή 'Βλέπεις τώρα;'",
            tone="παιδαγωγικά, φιλικά",
            intro_must_not="γράψεις ή επαναλάβεις την υπόδειξη — αυτή ακολουθεί αυτούσια",
            outro_must_not="επαναλάβεις την υπόδειξη",
        )
        deterministic_content = f"{hint_intro}\n\n{hint_text}\n\n{hint_outro}\n\n[ASSESSMENT:SUPPORT]\n[HINT]"
    elif next_chapter_request and task_started:
        # Bug 2 fix: ο μαθητής ζητά να παραλείψει την άσκηση — ΔΕΝ επιτρέπεται.
        # Ο LLM αποφασίζει αυτόνομα το επιχείρημα (βάσει σημαντικότητας/θέσης της ενότητας),
        # αντί για hardcoded κείμενο. Καλύπτει ΚΑΙ την περίπτωση που δεν έχει γίνει ακόμα
        # καμία υποβολή κώδικα (last_assessment_decision == "") — πριν μόνο "repeat"/"support" καλύπτονταν.
        block_msg = _generate_mentor_response(
            context=(
                f"Ο μαθητής ζητά να παραλείψει την τρέχουσα άσκηση και να προχωρήσει στο επόμενο κεφάλαιο, "
                f"αλλά δεν έχει ολοκληρώσει ακόμα την άσκηση στην ενότητα '{lesson_title}' "
                f"(Κεφάλαιο {current_lesson_id} από {len(all_lessons)}). "
                f"Αυτό ΔΕΝ επιτρέπεται — οι ασκήσεις πρέπει να ολοκληρώνονται πριν προχωρήσει ο μαθητής. "
                f"Εξήγησε ΕΥΓΕΝΙΚΑ και ΠΕΙΣΤΙΚΑ γιατί αξίζει να ολοκληρωθεί αυτή η άσκηση — "
                f"σκέψου μόνος σου ένα πειστικό επιχείρημα βασισμένο στη σημασία αυτής της ενότητας "
                f"για όσα ακολουθούν, ή στο πόσο κοντά είναι στη λύση. Ενθάρρυνέ τον να συνεχίσει."
            ),
            indicative="π.χ. 'Καταλαβαίνω τη βιασύνη! Αλλά αυτό που μαθαίνουμε εδώ είναι θεμέλιο για ό,τι ακολουθεί — ας το ολοκληρώσουμε μαζί!'",
            tone="κατανοητικά, ευγενικά, ενθαρρυντικά",
            must_not="πεις ότι μπορεί να παραλείψει ή να προχωρήσει χωρίς να ολοκληρώσει την άσκηση"
        )
        deterministic_content = (
            f"{block_msg}\n\n"
            "1) Σύντομη επανάληψη θεωρίας\n"
            "2) Στοχευμένα hints για να προχωρήσεις\n\n"
            "[ASSESSMENT:SUPPORT]"
        )
    elif is_correct:
        if assessment_decision == "advance":
            # Dynamic difficulty probe
            probe_ctx = ""
            if difficulty_probe_direction == "upgrade":
                probe_ctx = " Επίσης ανακοίνωσε ότι τα πάει τόσο καλά που θα δοκιμάσεις μια πιο απαιτητική άσκηση — αν τα πάει καλά, τον ανεβάζεις επίπεδο!"
            elif difficulty_probe_direction == "downgrade" and experience != "beginner":
                probe_ctx = " Επίσης ανακοίνωσε ότι ξεπέρασε τις δυσκολίες και επιστρέφετε σιγά-σιγά στις πιο απαιτητικές ασκήσεις."
            congrats = _generate_mentor_response(
                context=f"Ο μαθητής έλυσε σωστά την άσκηση '{lesson_title}'. Συγχάρεσέ τον και ρώτα αν θέλει να προχωρήσει στην '{next_lesson_title}'.{probe_ctx}",
                indicative="π.χ. 'Εξαιρετικά! Πάμε στα...' ή 'Μπράβο! Θέλεις να δούμε τα...'",
                tone="ενθουσιαστικά, ζεστά"
            )
            deterministic_content = f"{congrats}\n\n[ASSESSMENT:ADVANCE]"
        else:
            # Σωστό αλλά χρειάζεται άλλη άσκηση
            congrats = _generate_mentor_response(
                context=f"Ο μαθητής έλυσε σωστά αλλά χρειάστηκε πολλές προσπάθειες. Συγχάρεσέ τον και εξήγησε ότι μία ακόμα άσκηση θα παγιώσει την κατανόηση — πες του να γράψει 'προχωράμε'.",
                indicative="π.χ. 'Μπράβο που το έλυσες! Ας κάνουμε ακόμα μια για σιγουριά...'",
                tone="ενθαρρυντικά, φιλικά"
            )
            deterministic_content = f"{congrats}\n\n[ASSESSMENT:REPEAT]"
    elif wants_task:
        # "Just advanced" state: το μάθημα έχει ήδη προχωρήσει στη DB (current_lesson_id+1) αλλά
        # ο μαθητής δεν έχει δει ακόμα τη θεωρία της νέας ενότητας.
        # Συμβαίνει όταν δεν ο χρήστης δεν απαντά με affirmative ("ναι/παμε")
        # αλλά ζητά κατευθείαν άσκηση ("αλλη ασκηση", "δωσε μου ασκηση" κλπ).
        just_advanced = (
            _extract_last_assessment_decision(messages) == "advance"
            and not _task_already_presented(messages)
            and not _new_lesson_theory_shown(messages)
        )
        if just_advanced:
            # Ο μαθητής ζήτησε κατευθείαν άσκηση — δείχνουμε πρώτα τη νέα θεωρία
            intro, outro = _generate_mentor_intro_outro(
                context=f"Ο μαθητής ολοκλήρωσε την προηγούμενη ενότητα. Ξεκινά η νέα ενότητα '{lesson_title}' — η θεωρία ακολουθεί αμέσως αυτούσια· μετά χρειάζεται και κλείνουσα ερώτηση.",
                intro_indicative="π.χ. 'Τέλεια! Νέα ενότητα:' ή 'Πάμε!'",
                outro_indicative="π.χ. 'Ερωτήσεις; Ή πάμε σε άσκηση;'",
                tone="ενθαρρυντικά, ζεστά",
                intro_must_not="εξηγήσεις ή αναφέρεσαι στο περιεχόμενο της θεωρίας — αυτή ακολουθεί",
                outro_must_not="επαναλάβεις ή επεκτείνεις τη θεωρία",
            )
            deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
        elif _is_repeat_exercise_mode(messages):
            error_ctx = ""
            if frequent_errors:
                top = [_ERROR_CATEGORY_LABELS.get(e, e) for e in frequent_errors[:2]]
                error_ctx = f" Δυσκολεύτηκε ιδιαίτερα με: {' και '.join(top)}."
            repeat_intro = _generate_mentor_response(
                context=f"Ο μαθητής χρειάστηκε πολλές προσπάθειες.{error_ctx} Θα κάνει ακόμα μία άσκηση στην '{lesson_title}' — δεν είναι τιμωρία. Η εκφώνηση ακολουθεί αμέσως — γράψε μόνο ένα σύντομο ενθαρρυντικό μήνυμα.",
                indicative="π.χ. 'Δεν πειράζει! Μια ακόμα:' ή 'Συμβαίνει — να μια νέα:'",
                tone="ενθαρρυντικά, κατανοητικά",
                brief=True,
                must_not="γράψεις οτιδήποτε που μοιάζει με εκφώνηση άσκησης — αυτή ακολουθεί αυτούσια αμέσως μετά"
            )
            deterministic_content = f"{repeat_intro}\n\n{task}\n\n[BUTTON:START_TASK]"
        elif _task_already_presented(messages):
            if awaiting_questions:
                # Ο μαθητής μόλις επιβεβαίωσε ότι κατάλαβε τη θεωρία — πάμε στην άσκηση με ενθάρρυνση
                reminder = _generate_mentor_response(
                    context=f"Ο μαθητής κατάλαβε τη θεωρία της ενότητας '{lesson_title}' και είναι έτοιμος για την άσκηση — ακολουθεί αμέσως. Γράψε μόνο μια σύντομη ενθαρρυντική φράση.",
                    indicative="π.χ. 'Ωραία! Να η άσκηση:' ή 'Τέλεια, πάμε!' ή 'Εξαιρετικό!'",
                    tone="ενθαρρυντικά, ζωηρά",
                    brief=True,
                    must_not="γράψεις οτιδήποτε που μοιάζει με εκφώνηση άσκησης — αυτή ακολουθεί αυτούσια αμέσως μετά"
                )
            else:
                reminder = _generate_mentor_response(
                    context=f"Η άσκηση της ενότητας '{lesson_title}' έχει ήδη δοθεί και ακολουθεί αυτούσια — γράψε μόνο μια εναρκτήρια φράση.",
                    indicative="π.χ. 'Θυμίσου:' ή 'Να η άσκησή σου:' ή 'Εδώ είναι:'",
                    tone="φιλικά",
                    brief=True,
                    must_not="γράψεις οτιδήποτε που μοιάζει με εκφώνηση άσκησης — αυτή ακολουθεί αυτούσια αμέσως μετά"
                )
            deterministic_content = f"{reminder}\n\n{task}\n\n[BUTTON:START_TASK]"
        elif not _new_lesson_theory_shown(messages) and not task_started:
            # Θεωρία δεν έχει δειχθεί ακόμα (π.χ. αρχή session) — εμφάνισε πρώτα
            intro, outro = _generate_mentor_intro_outro(
                context=f"Ο μαθητής είναι έτοιμος να ξεκινήσει. Η θεωρία '{lesson_title}' ακολουθεί αμέσως αυτούσια· μετά χρειάζεται και κλείνουσα ερώτηση.",
                intro_indicative="π.χ. 'Τέλεια! Ας ξεκινήσουμε:' ή 'Ωραία! Αρχικά:'",
                outro_indicative="π.χ. 'Έχεις κάποια ερώτηση; Ή πάμε σε άσκηση;'",
                tone="φιλικά, ενθαρρυντικά",
                intro_must_not="εξηγήσεις ή αναφέρεσαι στο περιεχόμενο της θεωρίας — αυτή ακολουθεί",
                outro_must_not="επαναλάβεις ή επεκτείνεις τη θεωρία",
            )
            deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
        else:
            task_intro = _generate_mentor_response(
                context=f"Δίνεις νέα άσκηση στον μαθητή στην ενότητα '{lesson_title}'. Η εκφώνηση ακολουθεί αμέσως — γράψε μόνο μια σύντομη εναρκτήρια φράση.",
                indicative="π.χ. 'Ορίστε!' ή 'Να:' ή 'Πάμε!'",
                tone="φιλικά, ζωηρά",
                brief=True,
                must_not="γράψεις οτιδήποτε που μοιάζει με εκφώνηση άσκησης — αυτή ακολουθεί αυτούσια αμέσως μετά"
            )
            deterministic_content = f"{task_intro}\n\n{task}\n\n[BUTTON:START_TASK]"
    elif intent in {"theory_question", "code_help"}:
        msg_lower = (user_input or "").lower()
        # Μόνο ρητή αναφορά σε "θεωρία"/"ξαναπές" σημαίνει "ξαναδείξε την ΤΡΕΧΟΥΣΑ θεωρία αυτολεξεί".
        # "Θύμισέ μου"/"υπενθύμισε" ΧΩΡΙΣ τη λέξη "θεωρία" πάει ΠΑΝΤΑ στην _answer_theory_question —
        # μπορεί να αφορά συγκεκριμένη έννοια από ΠΡΟΗΓΟΥΜΕΝΗ ενότητα (π.χ. "θύμισέ μου πώς κάνω
        # λίστα" ενώ βρισκόμαστε σε άλλο κεφάλαιο), και μόνο εκείνη η συνάρτηση έχει πρόσβαση σε
        # ΟΛΕΣ τις προηγούμενες ενότητες. Προτιμάμε αυτό αντί για λίστα ερωτηματικών λέξεων
        # ("πώς"/"τι είναι"/...) που πάντα θα μένει ελλιπής (π.χ. δεν έπιανε "τι κάνει", "γιατί").
        wants_full_theory = any(kw in msg_lower for kw in ["θεωρια", "θεωρία", "ξαναπε", "ξαναπέ"])
        if wants_full_theory:
            outro = _generate_mentor_response(
                context=f"Ο μαθητής ξαναδιάβασε τη θεωρία '{lesson_title}'. Ρώτα αν έχει απορίες.",
                indicative="π.χ. 'Ρώτα ό,τι δεν είναι ξεκάθαρο!' ή 'Πιο κατανοητό;'",
                tone="φιλικά",
                brief=True,
                must_not="επαναλάβεις ή επεκτείνεις τη θεωρία"
            )
            deterministic_content = f"{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
        elif intent == "code_help" and task_started and debug_report and "[DEBUG: EMPTY]" not in debug_report:
            decision_tag = "[ASSESSMENT:SUPPORT]" if assessment_decision == "support" else "[ASSESSMENT:REPEAT]"
            hint_text = _generate_hint_with_llm(debug_report, task, difficulty, understanding_level, assessment_feedback, frequent_errors, avg_hints_per_task, hint_count)
            _frustration_ctx = (
                " Ο μαθητής φαίνεται να δυσκολεύεται αρκετά σε αυτή την άσκηση — ΠΡΩΤΑ αναγνώρισε ζεστά "
                "τη δυσκολία (π.χ. ότι είναι φυσιολογικό), ΜΕΤΑ δώσε την εισαγωγική φράση για το hint."
            ) if frustration_score >= 2 else ""
            hint_wrap = _generate_mentor_response(
                context=f"Ο μαθητής ζητά βοήθεια με τον κώδικά του. Γράψε μόνο μια εισαγωγική φράση — η υπόδειξη ακολουθεί αυτούσια αμέσως μετά.{_frustration_ctx}",
                indicative="π.χ. 'Κοίτα εδώ:' ή 'Πρόσεξε:' ή 'Ας δούμε:'",
                tone="παιδαγωγικά, φιλικά",
                brief=True,
                must_not="αρχίσεις με 'Πώς μπορώ να σε βοηθήσω' ή παρόμοιες γενικές ρητορικές φράσεις — πήγαινε κατευθείαν στην εισαγωγή"
            )
            deterministic_content = f"{hint_wrap}\n\n{hint_text}\n\n{decision_tag}\n[HINT]"
        elif intent == "code_help" and task_started:
            # Ο μαθητής ζητά βοήθεια αλλά δεν έχει υποβάλει κώδικα μέσω button.
            # Ελέγχουμε αν έγραψε κώδικα ή ερώτηση inline στο chat — αν ναι, απαντάμε απευθείας.
            _msg_lower_code = (user_input or "").lower()
            _has_inline_code = any(kw in user_input for kw in [
                "def ", "for ", "while ", "if ", "print(", "return ", "import "
            ])
            # Ρητό γενικό αίτημα βοήθειας ("θέλω βοήθεια", "δεν ξέρω πώς να...") — προηγείται
            # του _has_inline_question παρακάτω, γιατί τέτοιες φράσεις συχνά περιέχουν "πώς" αλλά
            # ΔΕΝ είναι εννοιολογική ερώτηση προς εξήγηση θεωρίας· είναι αίτημα για ένα πρώτο βήμα
            # πάνω στην ΤΡΕΧΟΥΣΑ άσκηση.
            _is_general_help_request = any(p in _msg_lower_code for p in [
                "θελω βοηθεια", "θέλω βοήθεια", "χρειαζομαι βοηθεια", "χρειάζομαι βοήθεια",
                "δεν ξερω πως να", "δεν ξέρω πώς να", "δεν ξερω τι να κανω", "δεν ξέρω τι να κάνω",
                "δεν ξερω απο που", "δεν ξέρω από πού", "δεν μπορω να το κανω", "δεν μπορώ να το κάνω",
            ])
            _has_inline_question = any(q in _msg_lower_code for q in [
                "τι κανω", "τι κάνω", "τι λαθ", "γιατι", "γιατί",
                "πως", "πώς", "εκτυπ", "εμφαν", "τι εννο", "μπορω να",
            ])
            if _has_inline_code:
                # Απαντάμε βάσει του ορατού κώδικα στο chat
                theory_answer = _answer_theory_question(user_input, lesson_title, theory, tone, current_lesson_id)
                deterministic_content = theory_answer
            elif _is_general_help_request:
                # Δεν έχει νόημα να ρωτήσουμε "τι εννοείς" — το είπε ήδη ξεκάθαρα. Δίνουμε ΕΝΑ
                # συγκεκριμένο πρώτο βήμα για ΑΥΤΗ την άσκηση, βασισμένο στη θεωρία.
                starter_hint = _generate_mentor_response(
                    context=(
                        f"Ο μαθητής ζήτησε ρητά βοήθεια ('{user_input}') επειδή δεν ξέρει πώς να ξεκινήσει την "
                        f"άσκηση '{task}' — δεν έχει γράψει ή υποβάλει κανέναν κώδικα ακόμα. ΜΗΝ ρωτήσεις τι "
                        f"εννοεί, το είπε ήδη. Δώσε ΕΝΑ συγκεκριμένο πρώτο βήμα: ποια δομή/εντολή να γράψει "
                        f"πρώτη, βασισμένο ΑΠΟΚΛΕΙΣΤΙΚΑ στη ΘΕΩΡΙΑ — όχι ολόκληρη τη λύση."
                    ),
                    indicative="π.χ. 'Ξεκίνα γράφοντας for i in range(5): και μέσα του, με εσοχή, print(i).'",
                    tone="υποστηρικτικά, καθοδηγητικά",
                    must_not="δώσεις ολόκληρη τη λύση της άσκησης ή ζητήσεις διευκρίνιση αντί να βοηθήσεις"
                )
                deterministic_content = starter_hint
            elif _has_inline_question:
                # Απαντάμε βάσει της συγκεκριμένης ερώτησης στο chat
                theory_answer = _answer_theory_question(user_input, lesson_title, theory, tone, current_lesson_id)
                deterministic_content = theory_answer
            else:
                nudge = _generate_mentor_response(
                    context="Ο μαθητής ζητά βοήθεια για τον κώδικά του αλλά δεν έχει υποβάλει κώδικα. Εξήγησέ του ότι χρειάζεται να πατήσει 'Εκτέλεση' για να δεις τον κώδικά του.",
                    indicative="π.χ. 'Φυσικά! Πάτα Εκτέλεση για να δω τον κώδικά σου και θα σε βοηθήσω!'",
                    tone="φιλικά, βοηθητικά",
                    brief=True,
                    must_not="δώσεις υπόδειξη χωρίς να έχεις δει τον κώδικα"
                )
                deterministic_content = nudge
        else:
            theory_answer = _answer_theory_question(user_input, lesson_title, theory, tone, current_lesson_id)
            deterministic_content = theory_answer
    elif intent == "other":
        if not profile_checked:
            # Deterministic — LLM αγνοεί must_not και ξανασυστήνεται
            deterministic_content = "Χμ, δεν κατάλαβα! Έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
        elif _is_not_ready_msg:
            # Ο μαθητής λέει ότι δεν νιώθει έτοιμος — ενθαρρύνουμε και ρωτάμε αν έχει απορίες
            not_ready_response = _generate_mentor_response(
                context=f"Ο μαθητής λέει ότι δεν νιώθει έτοιμος για την ενότητα '{lesson_title}'. Ενθάρρυνέ τον — πες ότι δεν υπάρχει βιασύνη και ρώτα αν έχει κάποια απορία που θέλει να ξεκαθαρίσει πρώτα.",
                indicative="π.χ. 'Κανένα πρόβλημα! Ρώτα ό,τι σε προβληματίζει.'",
                tone="ηρεμιστικά, ενθαρρυντικά",
                brief=True,
                must_not="πεις ότι 'είσαι έτοιμος' ή δώσεις άσκηση ή επαναλάβεις τη θεωρία"
            )
            deterministic_content = f"{not_ready_response}\n[AWAITING_QUESTIONS]"
        elif awaiting_questions and _is_negative_after_theory(user_input):
            # Bug 6 fix: ο μαθητής απάντησε αρνητικά ("οχι", "δεν κατάλαβα") στο "Έγινε πιο ξεκάθαρο;"
            # μετά από εξήγηση θεωρίας. Πριν αγνοούνταν εντελώς (freeform handler άλλαζε θέμα).
            re_explain = _generate_mentor_response(
                context=(
                    f"Ο μαθητής απάντησε αρνητικά ('{user_input}') αφού είδε εξήγηση πάνω στην ενότητα '{lesson_title}'. "
                    f"Δεν κατάλαβε. Ρώτα ευγενικά τι ακριβώς δεν είναι ξεκάθαρο και προσφέρσου να εξηγήσεις διαφορετικά ή με άλλο παράδειγμα."
                ),
                indicative="π.χ. 'Κανένα πρόβλημα! Τι ακριβώς δεν έγινε ξεκάθαρο;' ή 'Ας το ξαναδούμε — τι σε μπερδεύει;'",
                tone="ηρεμιστικά, ενθαρρυντικά",
                brief=True,
                must_not="επαναλάβεις όλη τη θεωρία, δώσεις άσκηση, ή υποθέσεις τι συγκεκριμένα δεν κατάλαβε"
            )
            deterministic_content = f"{re_explain}\n[AWAITING_QUESTIONS]"
        elif task_started:
            # Ο μαθητής δουλεύει στην άσκηση αλλά έστειλε κάτι ασαφές — ζητάμε διευκρίνιση
            clarify = _generate_mentor_response(
                context=(
                    f"Ο μαθητής εργάζεται στην άσκηση της ενότητας '{lesson_title}' και έστειλε «{user_input}» — "
                    f"κάτι που δεν είναι ξεκάθαρο αν είναι ερώτηση, αίτημα για βοήθεια, ή κάτι άλλο. "
                    f"Ρώτα σύντομα και φιλικά τι χρειάζεται."
                ),
                indicative="π.χ. 'Δεν κατάλαβα καλά — θέλεις hint, θέλεις θεωρία, ή κάτι άλλο;'",
                tone="φιλικά, ήπια",
                brief=True,
                must_not="δώσεις hint, εξηγήσεις θεωρία, ή δείξεις άσκηση χωρίς να μάθεις τι χρειάζεται"
            )
            deterministic_content = clarify
        else:
            phase_ctx = (
                f"εργάζεται πάνω στην άσκηση της ενότητας '{lesson_title}'" if task_started
                else f"βρίσκεται στη φάση θεωρίας της ενότητας '{lesson_title}'"
            )
            freeform = _generate_mentor_response(
                context=(
                    f"Ο μαθητής {phase_ctx} και έστειλε: «{user_input}». "
                    f"Απάντα φυσικά και με ενσυναίσθηση σε αυτό που είπε, "
                    f"και μετά επανάφερε ήπια τη συζήτηση στο μάθημα."
                ),
                indicative="π.χ. 'Καταλαβαίνω! Ας επιστρέψουμε στο...' ή 'Χαχα, αλλά ας συνεχίσουμε!'",
                tone="φιλικά, φυσικά",
                brief=True,
                must_not="δώσεις θεωρία, άσκηση ή hint — απλά απάντα και επανάφερε τη ροή"
            )
            deterministic_content = freeform
    elif awaiting_questions or (profile_checked and not task_started and not wants_task):
        if not awaiting_questions:
            # Θεωρία δεν έχει δειχθεί ακόμα → παρουσίαση θεωρίας, χρειάζεται intro ΚΑΙ outro (1 call)
            intro, outro = _generate_mentor_intro_outro(
                context=f"Ο μαθητής επιστρέφει. Ξεκινά η θεωρία '{lesson_title}' — ακολουθεί αμέσως αυτούσια· μετά χρειάζεται και κλείνουσα ερώτηση.",
                intro_indicative="π.χ. 'Καλώς! Να η θεωρία:' ή 'Ξεκινάμε:'",
                outro_indicative="π.χ. 'Έχεις κάποια απορία; Ή πάμε σε άσκηση;'",
                tone="φιλικά, ζεστά" if difficulty == "easy" else "ενθαρρυντικά",
                intro_must_not="εξηγήσεις ή αναφέρεσαι στο περιεχόμενο της θεωρίας",
                outro_must_not="επαναλάβεις ή επεκτείνεις τη θεωρία",
            )
            deterministic_content = f"{intro}\n\n{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"
        else:
            # Θεωρία έχει ήδη δειχθεί → μόνο re-ask, χωρίς επανάληψη θεωρίας — 1 call αρκούσε ήδη
            outro = _generate_mentor_response(
                context=f"Ο μαθητής διάβασε τη θεωρία '{lesson_title}'. Ρώτα αν έχει απορίες.",
                indicative="π.χ. 'Έχεις κάποια απορία; Ή πάμε σε άσκηση;'",
                tone="φιλικά" if difficulty == "easy" else "ενθαρρυντικά",
                brief=True,
                must_not="επαναλάβεις ή επεκτείνεις τη θεωρία"
            )
            deterministic_content = f"{outro}\n[AWAITING_QUESTIONS]"
    elif task_started and not is_correct:
        decision_tag = "[ASSESSMENT:SUPPORT]" if assessment_decision == "support" else "[ASSESSMENT:REPEAT]"
        hint_text = _generate_hint_with_llm(debug_report, task, difficulty, understanding_level, assessment_feedback, frequent_errors, avg_hints_per_task, hint_count)
        # Downgrade probe context — ο LLM το χειρίζεται φυσικά
        probe_ctx = ""
        if difficulty_probe_direction == "downgrade":
            probe_ctx = " Επίσης ανακοίνωσε ότι βλέπεις ότι δυσκολεύεται και θα δοκιμάσεις πιο απλές ασκήσεις για λίγο — τόνισε ότι δεν είναι πρόβλημα και μπορεί να ζητήσει δυσκολότερες όποτε θέλει."
        # Frustration context: αν ο μαθητής φαίνεται εκνευρισμένος (πολλά hints/αποτυχίες),
        # ζητάμε ζεστή αναγνώριση της δυσκολίας ΠΡΙΝ το hint, όχι κατευθείαν διόρθωση.
        frustration_ctx = ""
        if frustration_score >= 2:
            frustration_ctx = " Ο μαθητής φαίνεται να δυσκολεύεται αρκετά σε αυτή την άσκηση — ΠΡΩΤΑ αναγνώρισε ζεστά τη δυσκολία (π.χ. ότι είναι φυσιολογικό), ΜΕΤΑ δώσε την εισαγωγική φράση για το hint."
        hint_wrap = _generate_mentor_response(
            context=f"Ο κώδικας του μαθητή έχει λάθος. Γράψε μόνο μια εισαγωγική φράση — η υπόδειξη ακολουθεί αυτούσια αμέσως μετά.{probe_ctx}{frustration_ctx}",
            indicative="π.χ. 'Βλέπω κάτι εδώ:' ή 'Κοίτα αυτό:' ή 'Πρόσεξε:'",
            tone="παιδαγωγικά, φιλικά",
            brief=True,
            must_not="αρχίσεις με 'Πώς μπορώ να σε βοηθήσω' ή παρόμοιες γενικές ρητορικές φράσεις — μία σύντομη κατευθυντήρια φράση μόνο"
        )
        deterministic_content = f"{hint_wrap}\n\n{hint_text}\n\n{decision_tag}\n[HINT]"
    else:
        if not profile_checked:
            # Δεν γνωρίζουμε ακόμα το επίπεδο του μαθητή — ξαναρωτάμε (deterministic)
            deterministic_content = "Χμ, δεν κατάλαβα! Έχεις ξαναγράψει κώδικα ή είναι η πρώτη σου επαφή;"
        else:
            outro = _generate_mentor_response(
                context=f"Παρουσιάζεις τη θεωρία '{lesson_title}' στον μαθητή. Ρώτα αν έχει απορίες.",
                indicative="π.χ. 'Έχεις ερωτήσεις; Αν είσαι έτοιμος, πες μου!'",
                tone="φιλικά",
                brief=True,
                must_not="επαναλάβεις ή επεκτείνεις τη θεωρία"
            )
            deterministic_content = f"{chapter_header}\n\n{theory}\n\n{outro}\n[AWAITING_QUESTIONS]"

    # ── Επιστροφή αποτελέσματος ───────────────────────────────────────────────
    if deterministic_content is not None:
        # Προσθέτουμε [BUTTON:START_TASK] μόνο αν ο μαθητής θέλει άσκηση ΚΑΙ δεν έχει παρουσιαστεί θεωρία.
        # Αν περιέχει [AWAITING_QUESTIONS] σημαίνει ότι εμφανίστηκε θεωρία — δεν βάζουμε ακόμα το button.
        if (wants_task
                and "[BUTTON:START_TASK]" not in deterministic_content
                and "[AWAITING_QUESTIONS]" not in deterministic_content):
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
