import ast # Για deterministic έλεγχο κριτηρίων
import json
import re

ASSESSOR_SYSTEM_PROMPT = (
    "Είσαι ο Assessment Agent (Εξεταστής). "
    "Αξιολογείς με αυστηρότητα τον κώδικα ως προς τα success criteria. "
    "Μηδενική ανοχή σε νοηματικά λάθη τύπων δεδομένων. Το περιεχόμενο χωρίς τη σωστή μορφή θεωρείται λανθασμένο"
)

NUMERIC_TARGET_NAMES = {
    "age", "score", "year", "num_var", "n1", "n2", "num", "limit", "temp", "speed", "numbers"
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

    if "string" in task.lower() or "κείμενο" in task.lower():
        expectations["string_names"].extend(name_matches[:1])
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

    lesson_numeric_sensitive = current_lesson in {"Variables", "Data Types"}
    criteria_numeric_sensitive = _criteria_requires_numeric(success_criteria)

    violating_vars = []
    for var in numeric_strings:
        if criteria_numeric_sensitive or (lesson_numeric_sensitive and var in NUMERIC_TARGET_NAMES):
            violating_vars.append(var)

    return bool(violating_vars), sorted(set(violating_vars))

def _strict_task_matching(student_code: str, current_task: str):
    if not current_task:
        return True, []

    assignments = _extract_assignments(student_code)
    expectations = _extract_expected_from_task(current_task)
    failures = []

    for expected_name in expectations["names"]:
        if expected_name not in assignments:
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
    _ = ASSESSOR_SYSTEM_PROMPT

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
            "result": "FAIL"
        }

    try:
        type_mismatch, violating_vars = _type_mismatch_detected(student_code, success_criteria, current_lesson)
        if type_mismatch:
            decision = "support" if attempts_count >= 2 or hint_count >= 1 else "repeat"
            return {
                "is_correct": False,
                "assessment_feedback": (
                    "[TYPE_ERROR] Αποτυχία λόγω λάθους τύπου δεδομένων: "
                    f"οι μεταβλητές {', '.join(violating_vars)} έχουν αριθμητική τιμή γραμμένη ως string με εισαγωγικά."
                ),
                "assessment_score": 0,
                "assessment_decision": decision,
                "understanding_level": _understanding_level(0, attempts_count, hint_count, False),
                "result": "FAIL"
            }

        strict_ok, strict_failures = _strict_task_matching(student_code, current_task)
        if not strict_ok:
            decision = "support" if attempts_count >= 2 or hint_count >= 1 else "repeat"
            return {
                "is_correct": False,
                "assessment_feedback": "[STRICT_MATCH_FAIL] " + " | ".join(strict_failures),
                "assessment_score": 0,
                "assessment_decision": decision,
                "understanding_level": _understanding_level(0, attempts_count, hint_count, False),
                "result": "FAIL"
            }

        flags = _build_flags(student_code)
        criteria = _normalize_criteria(success_criteria)
        per_criterion = [(criterion, _criterion_passed(criterion, flags)) for criterion in criteria]

        passed = sum(1 for _, ok in per_criterion if ok)
        total = len(per_criterion)
        score = int((passed / total) * 100) if total else 0

        # Απόλυτη ακρίβεια στα criteria: PASS μόνο όταν όλα είναι True.
        is_correct = (total > 0 and passed == total)
        if is_correct and performance_summary:
            total_attempts = int(performance_summary.get("total_attempts", 0) or 0)
            avg_time = float(performance_summary.get("avg_time_spent", 0.0) or 0.0)
            repeated_errors = performance_summary.get("frequent_error_categories", []) or []
            if total_attempts >= 4 or avg_time >= 60 or len(repeated_errors) >= 2:
                decision = "support"
                feedback = (
                    "Η λύση είναι σωστή, αλλά το ιστορικό δείχνει ότι ο μαθητής δυσκολεύτηκε σημαντικά. "
                    "Προτείνεται επανάληψη παρόμοιας άσκησης πριν την προαγωγή."
                )
                return {
                    "is_correct": True,
                    "assessment_feedback": feedback,
                    "assessment_score": score,
                    "assessment_decision": decision,
                    "understanding_level": _understanding_level(score, attempts_count, hint_count, True),
                    "result": "PASS"
                }
        if is_correct:
            decision = "advance"
            feedback = "Ικανοποιούνται επαρκώς τα ακαδημαϊκά κριτήρια."
        else:
            decision = "support" if attempts_count >= 3 or time_spent > 180 or hint_count >= 2 else "repeat"
            failed = [criterion for criterion, ok in per_criterion if not ok]
            feedback = "Κριτήρια που δεν ικανοποιήθηκαν: " + "; ".join(failed) if failed else "Απαιτείται επιπλέον εξάσκηση."

        return {
            "is_correct": is_correct,
            "assessment_feedback": feedback,
            "assessment_score": score,
            "assessment_decision": decision,
            "understanding_level": _understanding_level(score, attempts_count, hint_count, is_correct),
            "result": "PASS" if is_correct else "FAIL"
        }
    except Exception:
        return {
            "is_correct": False,
            "assessment_feedback": "Αποτυχία αξιολόγησης. Προτείνεται επανάληψη.",
            "assessment_score": 0,
            "assessment_decision": "repeat",
            "understanding_level": "developing",
            "result": "FAIL"
        }