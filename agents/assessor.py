import ast # Για deterministic έλεγχο κριτηρίων
import json
import re
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()

ASSESSOR_SYSTEM_PROMPT = (
    "Είσαι ο Assessment Agent (Εξεταστής). "
    "Αξιολογείς με αυστηρότητα τον κώδικα ως προς τα success criteria. "
    "Μηδενική ανοχή σε νοηματικά λάθη τύπων δεδομένων. Το περιεχόμενο χωρίς τη σωστή μορφή θεωρείται λανθασμένο"
)

llm_assessor = ChatGroq(model_name="llama-3.1-8b-instant", temperature=0.1)


def _generate_assessment_feedback(
    is_correct: bool,
    raw_findings: str,
    current_task: str,
    understanding_level: str,
) -> str:
    """Παράγει σύντομη τεχνική περιγραφή των ευρημάτων για χρήση ΩΣ CONTEXT από τον Mentor.
    ΔΕΝ εμφανίζεται απευθείας στον μαθητή — τροφοδοτεί τον Mentor για παραγωγή hint.

    PASS: επιστρέφει αμέσως χωρίς LLM κλήση (δεν χρειάζεται για context).
    FAIL: LLM συνοψίζει ελεύθερα τα τεχνικά ευρήματα σε σύντομο context.
    """
    if is_correct:
        # Δεν χρειάζεται LLM για PASS — ο Mentor ξέρει ήδη ότι πέρασε
        return "Όλα τα κριτήρια ικανοποιούνται."

    prompt = (
        f"{ASSESSOR_SYSTEM_PROMPT}\n\n"
        f"Εκφώνηση: {current_task}\n"
        f"Τεχνικά ευρήματα: {raw_findings}\n"
        f"Επίπεδο κατανόησης: {understanding_level}\n\n"
        f"Συνόψισε τι χρειάζεται διόρθωση με βάση ΑΠΟΚΛΕΙΣΤΙΚΑ τα παραπάνω ευρήματα.\n"
        f"ΜΗΝ υποθέσεις πρόσθετα προβλήματα. ΜΗΝ δώσεις τη λύση.\n"
        f"Το κείμενο θα χρησιμοποιηθεί ως context από τον Mentor, όχι απευθείας στον μαθητή.\n\n"
        f"Σύνοψη ευρημάτων:"
    )
    try:
        result = llm_assessor.invoke(prompt)
        return result.content.strip() or raw_findings
    except Exception:
        return raw_findings

NUMERIC_TARGET_NAMES = {
    "age", "score", "year", "num_var", "n1", "n2", "num", "limit",
    "temp", "speed", "numbers", "price", "rating", "count", "total",
    "level", "value", "result", "x", "y", "z", "n", "sum", "avg",
    "min_val", "max_val", "threshold", "balance", "amount", "weight", "height"
}

# Ονόματα μεταβλητών που σημασιολογικά πρέπει να έχουν string τιμή
STRING_TARGET_NAMES = {
    "username", "email", "city", "country", "name", "category",
    "status", "user_status", "label", "message", "description",
    "title", "first_name", "last_name", "address", "phone"
}

def _safe_literal_eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _safe_literal_eval(node.operand)
        if isinstance(value, (int, float)):
            return value if isinstance(node.op, ast.UAdd) else -value
        return None
    if isinstance(node, ast.BinOp):
        left = _safe_literal_eval(node.left)
        right = _safe_literal_eval(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left ** right
    return None

def _extract_assignments(student_code: str):
    tree = ast.parse(student_code)
    assignments = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = _safe_literal_eval(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                assignments[target.id] = value
    return assignments

def _extract_expected_from_task(current_task: str):
    task = current_task or ""
    expectations = {
        "names": [],
        "numeric_values": [],
        "string_names": [],
        "numeric_names": [],
        "expression_values": []
    }

    name_matches = re.findall(r"(?:όνομα|μεταβλητή|συνάρτηση)\s+([A-Za-z_][A-Za-z0-9_]*)", task)
    expectations["names"].extend(name_matches)

    colon_match = re.search(r"μεταβλητ[^:]*:\s*([^\.\n]+)", task, re.IGNORECASE)
    if colon_match:
        raw_names = colon_match.group(1)
        for chunk in re.split(r",|\bκαι\b", raw_names):
            candidate = chunk.strip().strip(". ")
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate):
                expectations["names"].append(candidate)

    numeric_matches = re.findall(r"τιμή\s+(-?\d+(?:\.\d+)?)", task)
    for value in numeric_matches:
        expectations["numeric_values"].append(float(value) if "." in value else int(value))

    expr_match = re.search(r"\((\d+)\s*\+\s*(\d+)\)\s*\*\s*(\d+)", task)
    if expr_match:
        left = int(expr_match.group(1))
        right = int(expr_match.group(2))
        factor = int(expr_match.group(3))
        expectations["expression_values"].append((left + right) * factor)

    # Specific pattern: "μεταβλητή X ως string" — captures ALL explicitly typed string vars
    for m in re.finditer(r"μεταβλητ[ήη]\s+([A-Za-z_][A-Za-z0-9_]*)\s+ως\s+string", task, re.IGNORECASE):
        vname = m.group(1)
        if vname not in expectations["string_names"]:
            expectations["string_names"].append(vname)
    # Specific pattern: "μεταβλητή X ως αριθμό/int/float"
    for m in re.finditer(r"μεταβλητ[ήη]\s+([A-Za-z_][A-Za-z0-9_]*)\s+ως\s+(?:αριθμό|int|float|δεκαδ\w*)", task, re.IGNORECASE):
        vname = m.group(1)
        if vname not in expectations["string_names"] and vname not in expectations["numeric_names"]:
            expectations["numeric_names"].append(vname)
    # Fallback: generic keyword detection (no explicit "μεταβλητή X ως" patterns found)
    if not expectations["string_names"]:
        if "string" in task.lower() or "κείμενο" in task.lower():
            expectations["string_names"].extend(name_matches[:1])
    if not expectations["numeric_names"]:
        if "δεκαδ" in task.lower() or "αριθμ" in task.lower() or "number" in task.lower():
            already_string = set(expectations["string_names"])
            expectations["numeric_names"].extend([n for n in name_matches if n not in already_string])

    return expectations

def _normalize_criteria(success_criteria):
    if isinstance(success_criteria, list):
        return [str(c).strip() for c in success_criteria if str(c).strip()]
    if isinstance(success_criteria, str) and success_criteria.strip():
        return [success_criteria.strip()]
    return ["Ο κώδικας πρέπει να είναι λειτουργικός."]

def _build_flags(student_code: str):
    tree = ast.parse(student_code)
    return {
        "has_assign": any(isinstance(n, ast.Assign) for n in ast.walk(tree)),
        "has_if": any(isinstance(n, ast.If) for n in ast.walk(tree)),
        "has_for": any(isinstance(n, ast.For) for n in ast.walk(tree)),
        "has_def": any(isinstance(n, ast.FunctionDef) for n in ast.walk(tree)),
        "has_return": any(isinstance(n, ast.Return) for n in ast.walk(tree)),
        "has_print": any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(tree)),
        "has_append": any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append" for n in ast.walk(tree)),
        "has_list": any(isinstance(n, ast.List) for n in ast.walk(tree)),
        "has_index": any(isinstance(n, ast.Subscript) for n in ast.walk(tree))
    }

def _numeric_string_assignments(student_code: str):
    tree = ast.parse(student_code)
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue

        raw = node.value.value.strip()
        if not raw:
            continue
        if not raw.replace(".", "", 1).isdigit():
            continue

        for target in node.targets:
            if isinstance(target, ast.Name):
                issues.append(target.id)

    return sorted(set(issues))

def _criteria_requires_numeric(success_criteria):
    criteria_text = " ".join(_normalize_criteria(success_criteria)).lower()
    markers = ["αριθμη", "int", "float", "δεκαδ", "χωρίς εισαγωγικά", "number"]
    return any(marker in criteria_text for marker in markers)

def _type_mismatch_detected(student_code: str, success_criteria, current_lesson: str):
    numeric_strings = _numeric_string_assignments(student_code)
    if not numeric_strings:
        return False, []

    # Ελέγχουμε με 'in' γιατί το current_lesson μπορεί να είναι "Variables & Data Types"
    lesson_numeric_sensitive = "Variables" in current_lesson or "Data Types" in current_lesson
    criteria_numeric_sensitive = _criteria_requires_numeric(success_criteria)

    violating_vars = []
    for var in numeric_strings:
        if criteria_numeric_sensitive or (lesson_numeric_sensitive and var in NUMERIC_TARGET_NAMES):
            violating_vars.append(var)

    return bool(violating_vars), sorted(set(violating_vars))


def _string_mismatch_detected(student_code: str, current_lesson: str):
    """Ελέγχει αν γνωστά string-type ονόματα μεταβλητών έχουν αναθεθεί μη-string τιμή.
    π.χ. email = 12  →  λάθος (πρέπει να είναι string)"""
    # Ελέγχουμε με 'in' γιατί το current_lesson μπορεί να είναι "Variables & Data Types"
    if not ("Variables" in current_lesson or "Data Types" in current_lesson):
        return False, []

    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return False, []

    violating_vars = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = _safe_literal_eval(node.value)
        if value is None or isinstance(value, str):
            continue  # string τιμή ή σύνθετη έκφραση: δεν ελέγχουμε
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in STRING_TARGET_NAMES:
                violating_vars.append(target.id)

    return bool(violating_vars), sorted(set(violating_vars))


def _count_print_calls(student_code: str) -> int:
    """Μετράει πόσα print() calls υπάρχουν στον κώδικα."""
    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return 0
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    )

def _get_printed_string_values(student_code: str) -> set:
    """Επιστρέφει τα literal string ορίσματα που εμφανίζονται σε print() calls.
    Π.χ. print("High") → {"High"}.
    Χρησιμοποιείται για να ελέγξουμε αν η εκφώνηση ζητά συγκεκριμένο string output
    (π.χ. 'High'/'Low') και ο μαθητής το έχει αντεστραμμένο."""
    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return set()
    printed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    printed.add(arg.value)
    return printed

def _get_printed_var_names(student_code: str) -> set:
    """Επιστρέφει το σύνολο ονομάτων μεταβλητών που εμφανίζονται ως ορίσματα σε print() calls.
    Π.χ. print(age) και print(name) → {"age", "name"}.
    Π.χ. print(age) και print(age) → {"age"} — δύο prints, μία μεταβλητή."""
    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return set()
    printed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    printed.add(arg.id)
    return printed

def _strict_task_matching(student_code: str, current_task: str):
    if not current_task:
        return True, []

    assignments = _extract_assignments(student_code)
    # Συμπεριλαμβάνουμε και ονόματα συναρτήσεων (FunctionDef) ώστε "συνάρτηση calculate" να αναγνωρίζεται
    try:
        _ftree = ast.parse(student_code)
        _defined_funcs = {n.name for n in ast.walk(_ftree) if isinstance(n, ast.FunctionDef)}
    except SyntaxError:
        _defined_funcs = set()
    all_defined_names = set(assignments.keys()) | _defined_funcs

    expectations = _extract_expected_from_task(current_task)
    failures = []

    for expected_name in expectations["names"]:
        if expected_name not in all_defined_names:
            failures.append(f"Απουσία αναμενόμενου ονόματος μεταβλητής: {expected_name}")

    for expected_name in expectations["string_names"]:
        if expected_name in assignments and not isinstance(assignments[expected_name], str):
            failures.append(f"Η μεταβλητή {expected_name} πρέπει να είναι string.")

    for expected_name in expectations["numeric_names"]:
        if expected_name in assignments and isinstance(assignments[expected_name], str):
            failures.append(f"Η μεταβλητή {expected_name} πρέπει να είναι αριθμός, όχι string.")

    for expected_value in expectations["numeric_values"] + expectations["expression_values"]:
        if expected_value not in assignments.values():
            failures.append(f"Δεν βρέθηκε η απαιτούμενη τιμή {expected_value} στο πρόγραμμα.")

    # Έλεγχος ότι κάθε αναμενόμενη μεταβλητή εμφανίζεται σε print() call — όχι απλώς αρίθμηση calls.
    # Αποτρέπει το print(x); print(x) να γίνεται αποδεκτό ως print(x); print(y).
    task_lower = current_task.lower()
    needs_multi_print = (
        "τύπωνε και τις δύο" in task_lower
        or "τύπωνε και τα δύο" in task_lower
        or "τύπωνε και τις τρεις" in task_lower
        or "τύπωνε και τα τρία" in task_lower
        or ("τύπωνε" in task_lower and "με print" in task_lower and len(expectations["names"]) >= 2)
    )
    if needs_multi_print and expectations["names"]:
        printed_vars = _get_printed_var_names(student_code)
        missing_prints = [v for v in expectations["names"] if v not in printed_vars]
        if missing_prints:
            failures.append(
                f"Πρέπει να τυπωθούν ΟΛΕς οι απαιτούμενες μεταβλητές με print(). "
                f"Λείπει το print() για: {', '.join(missing_prints)}."
            )

    # Έλεγχος ότι τα literal strings που ζητά η εκφώνηση εμφανίζονται σε print() calls.
    # Αποτρέπει π.χ. print("Low") όταν η εκφώνηση ζητά print("High").
    # Εντοπίζει: τύπωνε "X" / τύπωνε 'X' / print("X") — έλεγχος case-sensitive.
    required_print_strings = re.findall(
        r'τύπ\w+\s+["\']([^"\']+)["\']',
        current_task,
        re.IGNORECASE
    )
    if required_print_strings:
        printed_strings = _get_printed_string_values(student_code)
        missing_strings = [s for s in required_print_strings if s not in printed_strings]
        if missing_strings:
            failures.append(
                f"Δεν βρέθηκαν τα απαιτούμενα strings στα print() calls: "
                f"{', '.join(missing_strings)}."
            )

    return (len(failures) == 0), failures

def _parse_performance_summary(performance_summary):
    if isinstance(performance_summary, dict):
        return performance_summary
    if not performance_summary:
        return {}
    try:
        return json.loads(performance_summary)
    except Exception:
        return {}

def _criterion_passed(criterion: str, flags):
    c = criterion.lower()
    if "συντακ" in c:
        return True
    if "ανάθεση" in c or "=" in c:
        return flags["has_assign"]
    if "if" in c or "δομή" in c:
        return flags["has_if"]
    if "for" in c or "επανάληψ" in c:
        return flags["has_for"]
    if "def" in c or "συνάρτ" in c:
        return flags["has_def"]
    if "append" in c:
        return flags["has_append"]
    if "λίστα" in c or "[]" in c:
        return flags["has_list"]
    if "index" in c or "[0]" in c:
        return flags["has_index"]
    if "return" in c:
        return flags["has_return"]
    if "print" in c or "τύπων" in c:
        return flags["has_print"]
    # Κριτήρια string/numeric αποθήκευσης — ελέγχονται ήδη από _type_mismatch_detected
    # και _strict_task_matching. Εδώ χαρακτηρίζονται ως "passed" αν υπάρχει έστω μία ανάθεση.
    if "εισαγωγικ" in c or "string" in c or "αριθμητ" in c or "χωρίς εισαγωγικ" in c:
        return flags["has_assign"]
    return True

def _understanding_level(score, attempts, hint_count, is_correct):
    if is_correct and score >= 90 and attempts <= 2 and hint_count == 0:
        return "strong"
    if is_correct and score >= 80:
        return "good"
    if attempts >= 4 or hint_count >= 3:
        return "needs_support"
    return "developing"

def assessment_node(state):# Κύρια λογική του Assessment Agent
    debug_report = state.get("debug_report", "")
    student_code = state.get("student_code", "")
    success_criteria = state.get("success_criteria", "Ο κώδικας πρέπει να είναι λειτουργικός.")
    current_lesson = state.get("current_lesson", "Python Basics")
    current_task = state.get("current_task", "")
    performance_summary = _parse_performance_summary(state.get("performance_summary", "{}"))
    attempts_count = int(state.get("attempts_count", 0) or 0)
    time_spent = float(state.get("time_spent", 0.0) or 0.0)
    hint_count = int(state.get("hint_count", 0) or 0)

    if "[DEBUG: ERROR]" in debug_report or "[DEBUG: EMPTY]" in debug_report or "[DEBUG: RULE_FAIL]" in debug_report:
        decision = "support" if attempts_count >= 3 or hint_count >= 2 else "repeat"
        return {
            "is_correct": False,
            "assessment_feedback": "Ο κώδικας χρειάζεται διόρθωση βάσει τεχνικού report.",
            "assessment_score": 0,
            "assessment_decision": decision,
            "understanding_level": _understanding_level(0, attempts_count, hint_count, False),
        }

    try:
        type_mismatch, violating_vars = _type_mismatch_detected(student_code, success_criteria, current_lesson)
        if type_mismatch:
            decision = "support" if attempts_count >= 2 or hint_count >= 1 else "repeat"
            ulevel = _understanding_level(0, attempts_count, hint_count, False)
            raw = f"Οι μεταβλητές {', '.join(violating_vars)} έχουν αριθμητική τιμή γραμμένη ως string (με εισαγωγικά)."
            feedback = _generate_assessment_feedback(False, raw, current_task, ulevel)
            return {
                "is_correct": False,
                "assessment_feedback": f"[TYPE_ERROR] {feedback}",
                "assessment_score": 0,
                "assessment_decision": decision,
                "understanding_level": ulevel,
            }

        # Έλεγχος αντίστροφου τύπου: string-type μεταβλητές που πήραν αριθμητική τιμή
        # π.χ. email = 12, country = 99  →  σφάλμα τύπου
        str_mismatch, str_violating = _string_mismatch_detected(student_code, current_lesson)
        if str_mismatch:
            decision = "support" if attempts_count >= 2 or hint_count >= 1 else "repeat"
            ulevel = _understanding_level(0, attempts_count, hint_count, False)
            raw = f"Οι μεταβλητές {', '.join(str_violating)} πρέπει να έχουν τιμή τύπου string (μέσα σε εισαγωγικά)."
            feedback = _generate_assessment_feedback(False, raw, current_task, ulevel)
            return {
                "is_correct": False,
                "assessment_feedback": f"[TYPE_ERROR] {feedback}",
                "assessment_score": 0,
                "assessment_decision": decision,
                "understanding_level": ulevel,
            }

        strict_ok, strict_failures = _strict_task_matching(student_code, current_task)
        if not strict_ok:
            decision = "support" if attempts_count >= 2 or hint_count >= 1 else "repeat"
            ulevel = _understanding_level(0, attempts_count, hint_count, False)
            raw = " | ".join(strict_failures)
            feedback = _generate_assessment_feedback(False, raw, current_task, ulevel)
            return {
                "is_correct": False,
                "assessment_feedback": f"[STRICT_MATCH_FAIL] {feedback}",
                "assessment_score": 0,
                "assessment_decision": decision,
                "understanding_level": ulevel,
            }

        flags = _build_flags(student_code)
        criteria = _normalize_criteria(success_criteria)
        per_criterion = [(criterion, _criterion_passed(criterion, flags)) for criterion in criteria]

        passed = sum(1 for _, ok in per_criterion if ok)
        total = len(per_criterion)
        score = int((passed / total) * 100) if total else 0

        # Απόλυτη ακρίβεια στα criteria: PASS μόνο όταν όλα είναι True.
        is_correct = (total > 0 and passed == total)

        ulevel = _understanding_level(score, attempts_count, hint_count, is_correct)
        if is_correct:
            # Πολλές αποτυχίες/hints → συνιστούμε επιπλέον εξάσκηση πριν προχωρήσουμε
            if attempts_count >= 4 or hint_count >= 3:
                decision = "repeat"
            else:
                decision = "advance"
            raw = "Όλα τα κριτήρια ικανοποιούνται πλήρως."
        else:
            decision = "support" if attempts_count >= 3 or time_spent > 180 or hint_count >= 2 else "repeat"
            failed = [criterion for criterion, ok in per_criterion if not ok]
            raw = "Κριτήρια που δεν ικανοποιήθηκαν: " + "; ".join(failed) if failed else "Απαιτείται επιπλέον εξάσκηση."

        feedback = _generate_assessment_feedback(is_correct, raw, current_task, ulevel)
        return {
            "is_correct": is_correct,
            "assessment_feedback": feedback,
            "assessment_score": score,
            "assessment_decision": decision,
            "understanding_level": ulevel,
        }
    except Exception:
        return {
            "is_correct": False,
            "assessment_feedback": "Αποτυχία αξιολόγησης. Προτείνεται επανάληψη.",
            "assessment_score": 0,
            "assessment_decision": "repeat",
            "understanding_level": "developing",
        }