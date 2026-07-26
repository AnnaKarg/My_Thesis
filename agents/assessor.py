import ast
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

llm_assessor = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0.1)

NUMERIC_TARGET_NAMES = {
    "age", "score", "year", "num_var", "n1", "n2", "num", "limit",
    "temp", "speed", "numbers", "price", "rating", "count", "total",
    "level", "value", "result", "x", "y", "z", "n", "sum", "avg",
    "min_val", "max_val", "threshold", "balance", "amount", "weight", "height"
}

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
    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return {}
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

    for lname in re.findall(r"λίστα\s+([A-Za-z_][A-Za-z0-9_]*)", task, re.IGNORECASE):
        if lname not in expectations["names"]:
            expectations["names"].append(lname)

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

    for m in re.finditer(r"μεταβλητ[ήη]\s+([A-Za-z_][A-Za-z0-9_]*)\s+ως\s+string", task, re.IGNORECASE):
        vname = m.group(1)
        if vname not in expectations["string_names"]:
            expectations["string_names"].append(vname)
    for m in re.finditer(r"μεταβλητ[ήη]\s+([A-Za-z_][A-Za-z0-9_]*)\s+ως\s+(?:αριθμό|int|float|δεκαδ\w*)", task, re.IGNORECASE):
        vname = m.group(1)
        if vname not in expectations["string_names"] and vname not in expectations["numeric_names"]:
            expectations["numeric_names"].append(vname)
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

def _has_reachable_print(tree, func_names, called_names) -> bool:
    """print() μέσα σε def που δεν καλείται ποτέ δεν εκτελείται ποτέ."""
    uncalled = func_names - called_names

    class _Visitor(ast.NodeVisitor):
        def __init__(self):
            self.found = False
            self.depth = 0

        def visit_FunctionDef(self, node):
            is_uncalled = node.name in uncalled
            if is_uncalled:
                self.depth += 1
            self.generic_visit(node)
            if is_uncalled:
                self.depth -= 1

        def visit_Call(self, node):
            if self.depth == 0 and isinstance(node.func, ast.Name) and node.func.id == "print":
                self.found = True
            self.generic_visit(node)

    v = _Visitor()
    v.visit(tree)
    return v.found


def _build_flags(student_code: str):
    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return {
            "has_assign": False, "has_if": False, "has_for": False, "has_def": False,
            "has_return": False, "has_print": False, "has_append": False,
            "has_list": False, "has_index": False, "list_elem_counts": [],
            "snake_case_ok": True, "has_elif": False, "has_boolop": False,
            "has_len_call": False, "has_nonempty_list": False,
            "has_function_call": False, "has_reachable_print": False,
        }

    assigned_names = {
        target.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
        for target in n.targets if isinstance(target, ast.Name)
    }
    func_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    called_names = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }

    return {
        "has_assign": any(isinstance(n, ast.Assign) for n in ast.walk(tree)),
        "has_if": any(isinstance(n, ast.If) for n in ast.walk(tree)),
        "has_for": any(isinstance(n, ast.For) for n in ast.walk(tree)),
        "has_def": bool(func_names),
        "has_return": any(isinstance(n, ast.Return) for n in ast.walk(tree)),
        "has_print": any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(tree)),
        "has_append": any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append" for n in ast.walk(tree)),
        "has_list": any(isinstance(n, ast.List) for n in ast.walk(tree)),
        "has_index": any(isinstance(n, ast.Subscript) for n in ast.walk(tree)),
        "list_elem_counts": [len(n.elts) for n in ast.walk(tree) if isinstance(n, ast.List)],
        "snake_case_ok": all(not any(ch.isupper() for ch in name) for name in assigned_names) if assigned_names else True,
        "has_elif": any(
            isinstance(n, ast.If) and len(n.orelse) == 1 and isinstance(n.orelse[0], ast.If)
            for n in ast.walk(tree)
        ),
        "has_boolop": any(isinstance(n, ast.BoolOp) for n in ast.walk(tree)),
        "has_len_call": any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "len"
            for n in ast.walk(tree)
        ),
        "has_nonempty_list": any(isinstance(n, ast.List) and len(n.elts) > 0 for n in ast.walk(tree)),
        "has_function_call": bool(func_names & called_names),
        "has_reachable_print": _has_reachable_print(tree, func_names, called_names),
    }

def _numeric_string_assignments(student_code: str):
    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return []
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

def _type_mismatch_detected(student_code: str, success_criteria):
    """Γνωστά αριθμητικά ονόματα (NUMERIC_TARGET_NAMES) με τιμή γραμμένη ως string, π.χ. age = "25"."""
    numeric_strings = _numeric_string_assignments(student_code)
    if not numeric_strings:
        return False, []

    criteria_numeric_sensitive = _criteria_requires_numeric(success_criteria)

    violating_vars = []
    for var in numeric_strings:
        if criteria_numeric_sensitive or var in NUMERIC_TARGET_NAMES:
            violating_vars.append(var)

    return bool(violating_vars), sorted(set(violating_vars))


def _string_mismatch_detected(student_code: str):
    """Γνωστά string-type ονόματα (STRING_TARGET_NAMES) με μη-string τιμή, π.χ. email = 12."""
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
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in STRING_TARGET_NAMES:
                violating_vars.append(target.id)

    return bool(violating_vars), sorted(set(violating_vars))


def _empty_string_list_elements_detected(student_code: str, current_lesson: str):
    """Λίστα με μόνο κενά strings, π.χ. scores=['','','']. Μόνο για το μάθημα Λιστών."""
    if "Lists" not in current_lesson:
        return False, ""
    try:
        tree = ast.parse(student_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
                elts = node.value.elts
                if elts and any(isinstance(e, ast.Constant) and e.value == "" for e in elts):
                    return True, "Η λίστα περιέχει μόνο κενά strings (''). Τα στοιχεία πρέπει να έχουν πραγματικές τιμές."
    except Exception:
        pass
    return False, ""


def _count_print_calls(student_code: str) -> int:
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
    """Literal string ορίσματα σε print() calls, μαζί με literal τμήματα μέσα σε f-strings."""
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
                elif isinstance(arg, ast.JoinedStr):
                    for part in arg.values:
                        if isinstance(part, ast.Constant) and isinstance(part.value, str):
                            printed.add(part.value)
    return printed

def _get_printed_var_names(student_code: str) -> set:
    """Ονόματα μεταβλητών που εμφανίζονται ως ορίσματα σε print() calls, μαζί με ό,τι είναι μέσα σε f-strings."""
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
                elif isinstance(arg, ast.JoinedStr):
                    for part in arg.values:
                        if isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
                            printed.add(part.value.id)
    return printed


def _if_else_direction_mismatch(student_code: str, current_task: str):
    """Best-effort έλεγχος αντεστραμμένης λογικής σε απλό if/else (task: 'μεγαλύτερη από 50 →
    High, αλλιώς → Low', κώδικας: τυπώνει Low όταν είναι μεγαλύτερη)."""
    task = current_task or ""
    if "αλλιώς" not in task:
        return False, None
    direction_match = re.search(r"μεγαλύτερ\w*|μικρότερ\w*", task, re.IGNORECASE)
    if not direction_match:
        return False, None
    is_greater = direction_match.group(0).lower().startswith("μεγαλύτερ")

    before, _, after = task.partition("αλλιώς")
    strings_before = re.findall(r"['\"]([^'\"]+)['\"]", before)
    strings_after = re.findall(r"['\"]([^'\"]+)['\"]", after)
    if not strings_before or not strings_after:
        return False, None
    true_string, false_string = strings_before[-1], strings_after[0]
    if true_string == false_string:
        return False, None

    try:
        tree = ast.parse(student_code)
    except SyntaxError:
        return False, None

    def _first_print_string(stmts):
        for s in stmts:
            if (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                    and isinstance(s.value.func, ast.Name) and s.value.func.id == "print"):
                for a in s.value.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        return a.value
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
            continue
        op = test.ops[0]
        if not isinstance(op, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
            continue
        if not node.orelse or isinstance(node.orelse[0], ast.If):
            continue
        body_string = _first_print_string(node.body)
        else_string = _first_print_string(node.orelse)
        if body_string is None or else_string is None:
            continue
        if body_string not in (true_string, false_string) or else_string not in (true_string, false_string):
            continue
        code_is_greater = isinstance(op, (ast.Gt, ast.GtE))
        same_direction = (code_is_greater == is_greater)
        expected_body = true_string if same_direction else false_string
        expected_else = false_string if same_direction else true_string
        if body_string == expected_else and else_string == expected_body:
            return True, (
                f"Η λογική if/else φαίνεται αντεστραμμένη: όταν η συνθήκη ισχύει τυπώνεται "
                f"'{body_string}' αντί για '{expected_body}'."
            )
        return False, None

    return False, None


def _strict_task_matching(student_code: str, current_task: str):
    if not current_task:
        return True, []

    assignments = _extract_assignments(student_code)
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

    required_print_strings = re.findall(
        r'τ[υύ]π\w*\s+["\']([^"\']+)["\']',
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

    is_inverted, inversion_msg = _if_else_direction_mismatch(student_code, current_task)
    if is_inverted:
        failures.append(inversion_msg)

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

_GREEK_LIST_COUNT_WORDS = {"ένα": 1, "ενα": 1, "δύο": 2, "δυο": 2, "τρία": 3, "τρια": 3}


def _required_list_count(criterion_lower: str):
    """Πλήθος στοιχείων λίστας που αναφέρεται ρητά στο κριτήριο (π.χ. 'τουλάχιστον ένα στοιχείο'
    → (1, ελάχιστο)). (None, False) αν δεν αναφέρεται αριθμός. Χρησιμοποιεί \\b όρια λέξης ώστε
    το 'ένα' να μην ταιριάζει μέσα σε λέξεις όπως 'χωρισμένα'."""
    is_minimum = bool(re.search(r"\bτουλάχιστον\b|\bτουλαχιστον\b", criterion_lower))
    for word, n in _GREEK_LIST_COUNT_WORDS.items():
        if re.search(rf"\b{word}\b", criterion_lower):
            return n, is_minimum
    return None, False


def _criterion_passed(criterion: str, flags):
    c = criterion.lower()
    if "συντακ" in c:
        return True
    if "snake_case" in c:
        return flags.get("snake_case_ok", True)
    if "elif" in c or "and/or" in c or "λογικό τελεστ" in c:
        return flags["has_if"] and (flags.get("has_elif") or flags.get("has_boolop"))
    if "len(" in c:
        return flags.get("has_len_call", False)
    if "καλείται" in c or "κλήση" in c:
        return flags.get("has_function_call", False)
    if "print" in c or "τύπων" in c:
        return flags.get("has_reachable_print", flags["has_print"])
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
        if not flags["has_list"]:
            return False
        required_count, is_minimum = _required_list_count(c)
        if required_count is None:
            return flags.get("has_nonempty_list", True)
        counts = flags.get("list_elem_counts") or []
        return any(n >= required_count for n in counts) if is_minimum else any(n == required_count for n in counts)
    if "index" in c or "[0]" in c:
        return flags["has_index"]
    if "return" in c:
        return flags["has_return"]
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

UNDERSTANDING_LEVEL_TO_MASTERY_PCT = {"needs_support": 20, "developing": 50, "good": 75, "strong": 95}

_VALID_DECISIONS = {"advance", "repeat", "support"}
_VALID_UNDERSTANDING_LEVELS = {"needs_support", "developing", "good", "strong"}

_ERROR_REPORT_TAGS = ("[DEBUG: ERROR]", "[DEBUG: EMPTY]", "[DEBUG: RULE_FAIL]")

_LLM_ASSESSMENT_RE = re.compile(
    r"ΣΩΣΤΟ\s*:\s*(.*?)\s*ΑΠΟΦΑΣΗ\s*:\s*(.*?)\s*ΚΑΤΑΝΟΗΣΗ\s*:\s*(.*?)\s*FEEDBACK\s*:\s*(.*)",
    re.DOTALL | re.IGNORECASE,
)


def _gather_assessment_facts(debug_report, student_code, success_criteria, current_lesson,
                              current_task, attempts_count, hint_count, time_spent) -> dict:
    type_mismatch = _type_mismatch_detected(student_code, success_criteria)
    string_mismatch = _string_mismatch_detected(student_code)
    empty_list_issue = _empty_string_list_elements_detected(student_code, current_lesson)
    strict_match_ok, strict_failures = _strict_task_matching(student_code, current_task)

    flags = _build_flags(student_code)
    criteria = _normalize_criteria(success_criteria)
    per_criterion = [(criterion, _criterion_passed(criterion, flags)) for criterion in criteria]
    passed = sum(1 for _, ok in per_criterion if ok)
    total = len(per_criterion)

    has_hard_violation = (
        (bool(debug_report) and any(tag in debug_report for tag in _ERROR_REPORT_TAGS))
        or type_mismatch[0]
        or string_mismatch[0]
        or empty_list_issue[0]
        or not strict_match_ok
    )
    score = 0 if has_hard_violation else (int((passed / total) * 100) if total else 0)

    return {
        "debug_report": debug_report,
        "type_mismatch": type_mismatch,
        "string_mismatch": string_mismatch,
        "empty_list_issue": empty_list_issue,
        "strict_match_ok": strict_match_ok,
        "strict_failures": strict_failures,
        "per_criterion": per_criterion,
        "score": score,
        "passed": passed,
        "total": total,
        "attempts_count": attempts_count,
        "hint_count": hint_count,
        "time_spent": time_spent,
    }


def _fallback_feedback_text(facts: dict) -> str:
    type_mismatch_ok, type_vars = facts["type_mismatch"]
    string_mismatch_ok, string_vars = facts["string_mismatch"]
    empty_list_ok, empty_list_desc = facts["empty_list_issue"]

    if facts["debug_report"] and any(tag in facts["debug_report"] for tag in _ERROR_REPORT_TAGS):
        return "Ο κώδικας χρειάζεται διόρθωση βάσει τεχνικού report."
    if type_mismatch_ok:
        return f"Οι μεταβλητές {', '.join(type_vars)} έχουν αριθμητική τιμή γραμμένη ως string (με εισαγωγικά)."
    if string_mismatch_ok:
        return f"Οι μεταβλητές {', '.join(string_vars)} πρέπει να έχουν τιμή τύπου string (μέσα σε εισαγωγικά)."
    if empty_list_ok:
        return empty_list_desc
    if not facts["strict_match_ok"]:
        return " | ".join(facts["strict_failures"])
    failed = [criterion for criterion, ok in facts["per_criterion"] if not ok]
    return "Κριτήρια που δεν ικανοποιήθηκαν: " + "; ".join(failed) if failed else "Απαιτείται επιπλέον εξάσκηση."


def _needs_support_escalation(attempts_count: int, hint_count: int, time_spent: float) -> bool:
    return attempts_count >= 3 or hint_count >= 2 or time_spent > 180


def _fallback_assessment(facts: dict) -> dict:
    """Χρησιμοποιείται μόνο όταν αποτύχει η κλήση στο LLM."""
    type_mismatch_ok, _ = facts["type_mismatch"]
    string_mismatch_ok, _ = facts["string_mismatch"]
    empty_list_ok, _ = facts["empty_list_issue"]
    has_error_report = bool(facts["debug_report"]) and any(tag in facts["debug_report"] for tag in _ERROR_REPORT_TAGS)

    is_correct = (
        not has_error_report
        and not type_mismatch_ok
        and not string_mismatch_ok
        and not empty_list_ok
        and facts["strict_match_ok"]
        and facts["total"] > 0
        and facts["passed"] == facts["total"]
    )

    attempts_count = facts["attempts_count"]
    hint_count = facts["hint_count"]
    time_spent = facts["time_spent"]

    if is_correct:
        decision = "repeat" if (attempts_count >= 4 or hint_count >= 3) else "advance"
    else:
        decision = "support" if _needs_support_escalation(attempts_count, hint_count, time_spent) else "repeat"

    understanding_level = _understanding_level(facts["score"], attempts_count, hint_count, is_correct)
    feedback = "Όλα τα κριτήρια ικανοποιούνται." if is_correct else _fallback_feedback_text(facts)

    return {
        "is_correct": is_correct,
        "assessment_decision": decision,
        "understanding_level": understanding_level,
        "assessment_feedback": feedback,
    }


def _reason_about_assessment(facts: dict, current_task: str) -> dict:
    per_criterion_lines = "\n".join(
        f"- {'OK' if ok else 'FAIL'}: {criterion}" for criterion, ok in facts["per_criterion"]
    ) or "Δεν υπάρχουν καθορισμένα κριτήρια."

    type_mismatch_ok, type_vars = facts["type_mismatch"]
    string_mismatch_ok, string_vars = facts["string_mismatch"]
    empty_list_ok, empty_list_desc = facts["empty_list_issue"]

    prompt = (
        f"{ASSESSOR_SYSTEM_PROMPT}\n\n"
        f"Εκφώνηση: {current_task}\n"
        f"Κριτήρια:\n{per_criterion_lines}\n\n"
        f"Αναφορά Debugger: {facts['debug_report'] or 'Καμία.'}\n\n"
        f"ΑΝΤΙΚΕΙΜΕΝΙΚΑ ΕΥΡΗΜΑΤΑ (δεδομένα από deterministic ελέγχους — ΟΧΙ γνώμη):\n"
        f"- Score βάσει κριτηρίων: {facts['score']}/100 ({facts['passed']}/{facts['total']} κριτήρια ικανοποιούνται)\n"
        f"- Type mismatch (αριθμός γραμμένος ως string): "
        f"{'ΝΑΙ, στις μεταβλητές: ' + ', '.join(type_vars) if type_mismatch_ok else 'ΟΧΙ'}\n"
        f"- String mismatch (string-type μεταβλητή με μη-string τιμή): "
        f"{'ΝΑΙ, στις μεταβλητές: ' + ', '.join(string_vars) if string_mismatch_ok else 'ΟΧΙ'}\n"
        f"- Κενά strings σε λίστα: {'ΝΑΙ — ' + empty_list_desc if empty_list_ok else 'ΟΧΙ'}\n"
        f"- Strict task matching (ονόματα/τιμές/prints που ζητά η εκφώνηση): "
        f"{'ΟΛΑ ΟΚ' if facts['strict_match_ok'] else 'ΑΠΕΤΥΧΕ — ' + '; '.join(facts['strict_failures'])}\n\n"
        f"ΙΣΤΟΡΙΚΟ ΜΑΘΗΤΗ:\n"
        f"- Προσπάθειες σε αυτή την άσκηση: {facts['attempts_count']}\n"
        f"- Hints που έχουν δοθεί: {facts['hint_count']}\n"
        f"- Χρόνος που αφιέρωσε: {facts['time_spent']:.0f} δευτερόλεπτα\n\n"
        f"Έργο σου: αξιολόγησε ΟΛΙΣΤΙΚΑ βάσει ΑΠΟΚΛΕΙΣΤΙΚΑ των παραπάνω αντικειμενικών ευρημάτων. "
        f"ΜΗΝ υποθέσεις προβλήματα που δεν αναφέρονται. Απόφασε:\n"
        f"1. is_correct: ικανοποιεί ΠΛΗΡΩΣ την εκφώνηση; ΝΑΙ μόνο αν ΟΛΑ τα ευρήματα το επιβεβαιώνουν "
        f"— μηδενική ανοχή σε type/string mismatch ή strict-match αποτυχία, ακόμα κι αν το score είναι υψηλό.\n"
        f"2. assessment_decision — ΑΚΡΙΒΩΣ ένα από: advance, repeat, support\n"
        f"   - advance: μόνο αν is_correct=ΝΑΙ ΚΑΙ ο μαθητής δεν χρειάζεται επιπλέον εξάσκηση (λίγες προσπάθειες/hints)\n"
        f"   - repeat: χρειάζεται να ξαναδοκιμάσει, χωρίς να είναι ακόμα σε σοβαρή δυσκολία\n"
        f"   - support: φαίνεται να δυσκολεύεται σοβαρά (πολλές προσπάθειες/hints/χρόνος) και χρειάζεται πιο ενεργή καθοδήγηση\n"
        f"3. understanding_level — ΑΚΡΙΒΩΣ ένα από: needs_support, developing, good, strong\n"
        f"4. assessment_feedback: 1-3 προτάσεις τεχνική περιγραφή για χρήση ΩΣ CONTEXT από τον Mentor "
        f"(ΟΧΙ απευθείας στον μαθητή) — αν is_correct=ΝΑΙ, γράψε \"Όλα τα κριτήρια ικανοποιούνται.\". "
        f"ΜΗΝ δώσεις τη λύση.\n\n"
        f"Απάντησε ΑΚΡΙΒΩΣ σε αυτή τη μορφή, τίποτα άλλο πριν ή μετά:\n"
        f"ΣΩΣΤΟ: ΝΑΙ ή ΟΧΙ\n"
        f"ΑΠΟΦΑΣΗ: advance ή repeat ή support\n"
        f"ΚΑΤΑΝΟΗΣΗ: needs_support ή developing ή good ή strong\n"
        f"FEEDBACK: <το κείμενο feedback>"
    )

    try:
        result = llm_assessor.invoke(prompt)
        content = (result.content or "").strip()
        match = _LLM_ASSESSMENT_RE.search(content)
        if not match:
            raise ValueError("unparseable assessment response")

        correct_raw, decision_raw, level_raw, feedback = (g.strip() for g in match.groups())

        decision = decision_raw.strip().lower()
        if decision not in _VALID_DECISIONS:
            raise ValueError(f"invalid assessment_decision: {decision_raw!r}")

        is_correct = correct_raw.strip().upper().startswith(("ΝΑΙ", "NAI", "YES"))

        if (decision == "advance" and not is_correct) or (decision == "support" and is_correct):
            raise ValueError(f"inconsistent is_correct/decision pair: {correct_raw!r} / {decision_raw!r}")

        if not is_correct and decision == "repeat" and _needs_support_escalation(
            facts["attempts_count"], facts["hint_count"], facts["time_spent"]
        ):
            decision = "support"

        if is_correct and decision == "advance" and (
            facts["attempts_count"] >= 4 or facts["hint_count"] >= 3
        ):
            decision = "repeat"

        understanding_level = level_raw.strip().lower()
        if understanding_level not in _VALID_UNDERSTANDING_LEVELS:
            understanding_level = _understanding_level(
                facts["score"], facts["attempts_count"], facts["hint_count"], is_correct
            )

        if not feedback:
            feedback = "Όλα τα κριτήρια ικανοποιούνται." if is_correct else _fallback_feedback_text(facts)

        return {
            "is_correct": is_correct,
            "assessment_decision": decision,
            "understanding_level": understanding_level,
            "assessment_feedback": feedback,
        }
    except Exception:
        return _fallback_assessment(facts)


def assessment_node(state):
    debug_report = state.get("debug_report", "")
    student_code = state.get("student_code", "")
    success_criteria = state.get("success_criteria", "Ο κώδικας πρέπει να είναι λειτουργικός.")
    current_lesson = state.get("current_lesson", "Python Basics")
    current_task = state.get("current_task", "")
    attempts_count = int(state.get("attempts_count", 0) or 0)
    time_spent = float(state.get("time_spent", 0.0) or 0.0)
    hint_count = int(state.get("hint_count", 0) or 0)

    try:
        facts = _gather_assessment_facts(
            debug_report, student_code, success_criteria, current_lesson,
            current_task, attempts_count, hint_count, time_spent,
        )
        result = _reason_about_assessment(facts, current_task)
        return {
            "is_correct": result["is_correct"],
            "assessment_feedback": result["assessment_feedback"],
            "assessment_score": facts["score"],
            "assessment_decision": result["assessment_decision"],
            "understanding_level": result["understanding_level"],
        }
    except Exception:
        return {
            "is_correct": False,
            "assessment_feedback": "Αποτυχία αξιολόγησης. Προτείνεται επανάληψη.",
            "assessment_score": 0,
            "assessment_decision": "repeat",
            "understanding_level": "developing",
        }
