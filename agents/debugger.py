import ast # Για deterministic ανάλυση σύνταξης και λογικών δομών
import builtins # Για έλεγχο built-in ονομάτων

BUILTIN_NAMES = set(dir(builtins))

def _criteria_text(success_criteria) -> str:
    if isinstance(success_criteria, list):
        return " ".join(str(c) for c in success_criteria)
    return str(success_criteria or "")

class _Analyzer(ast.NodeVisitor):
    def __init__(self):
        self.assigned = set()
        self.loaded = set()
        self.has_if = False
        self.has_for = False
        self.has_def = False
        self.has_append = False
        self.has_index = False
        self.has_list = False
        self.has_print = False
        self.quoted_number_vars = []

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assigned.add(target.id)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            candidate = node.value.value.strip()
            if candidate.replace(".", "", 1).isdigit():
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.quoted_number_vars.append(target.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name):
            self.assigned.add(node.target.id)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.loaded.add(node.id)
        self.generic_visit(node)

    def visit_If(self, node):
        self.has_if = True
        self.generic_visit(node)

    def visit_For(self, node):
        self.has_for = True
        if isinstance(node.target, ast.Name):
            self.assigned.add(node.target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.has_def = True
        self.assigned.add(node.name)
        for arg in node.args.args:
            self.assigned.add(arg.arg)
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            self.has_print = True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            self.has_append = True
        self.generic_visit(node)

    def visit_List(self, node):
        self.has_list = True
        self.generic_visit(node)

    def visit_Subscript(self, node):
        self.has_index = True
        self.generic_visit(node)

def _deterministic_findings(tree, success_criteria):
    analyzer = _Analyzer()
    analyzer.visit(tree)

    findings = []
    categories = set()
    criteria_text = _criteria_text(success_criteria).lower()

    undefined = sorted(
        name for name in (analyzer.loaded - analyzer.assigned)
        if name not in BUILTIN_NAMES
    )
    if undefined:
        categories.add("undefined_name")
        findings.append("Χρήση μεταβλητής πριν από ανάθεση: " + ", ".join(undefined))

    if ("if" in criteria_text or "δομή" in criteria_text) and not analyzer.has_if:
        categories.add("missing_if")
        findings.append("Απουσία δομής if ενώ απαιτείται από τα κριτήρια.")

    if ("for" in criteria_text or "επανάληψ" in criteria_text) and not analyzer.has_for:
        categories.add("missing_for")
        findings.append("Απουσία for loop ενώ απαιτείται από τα κριτήρια.")

    if ("def" in criteria_text or "συνάρτη" in criteria_text) and not analyzer.has_def:
        categories.add("missing_function")
        findings.append("Απουσία ορισμού συνάρτησης (def).")

    if "append" in criteria_text and not analyzer.has_append:
        categories.add("missing_append")
        findings.append("Απουσία χρήσης append() ενώ ζητείται.")

    if ("λίστα" in criteria_text or "[]" in criteria_text) and not analyzer.has_list:
        categories.add("missing_list")
        findings.append("Απουσία λίστας ([]) ενώ ζητείται.")

    if ("index" in criteria_text or "[0]" in criteria_text) and not analyzer.has_index:
        categories.add("missing_index")
        findings.append("Απουσία πρόσβασης με index ενώ ζητείται.")

    if ("τύπων" in criteria_text or "print" in criteria_text) and not analyzer.has_print:
        categories.add("missing_output")
        findings.append("Απουσία print() ενώ ζητείται output.")

    if ("αριθμη" in criteria_text or "χωρίς εισαγωγικά" in criteria_text) and analyzer.quoted_number_vars:
        categories.add("type_mismatch")
        findings.append("Αριθμητική τιμή αποθηκεύτηκε ως string στις μεταβλητές: " + ", ".join(sorted(set(analyzer.quoted_number_vars))))

    return findings, sorted(categories)

def debugging_node(state):# Κύρια λογική του Debugger Agent
    student_code = state.get("student_code", "")
    success_criteria = state.get("success_criteria", "")

    if not student_code.strip():
        return {"debug_report": "[DEBUG: EMPTY] Δεν εντοπίστηκε κώδικας προς ανάλυση."}

    try:
        tree = ast.parse(student_code)
    except SyntaxError as e:
        return {
            "debug_report": f"[DEBUG: ERROR] Συντακτικό λάθος στη γραμμή {e.lineno}: {e.msg}."
        }

    findings, categories = _deterministic_findings(tree, success_criteria)

    if findings:
        technical = "\n".join(f"- {item}" for item in findings)
        categories_text = ", ".join(categories) if categories else "general_logic"
        return {
            "debug_report": (
                "[DEBUG: RULE_FAIL] Εντοπίστηκαν τεχνικά προβλήματα.\n"
                f"[DEBUG:CATEGORIES] {categories_text}\n"
                f"{technical}"
            )
        }

    return {
        "debug_report": "[DEBUG: OK] Δεν εντοπίστηκαν συντακτικά/λογικά προβλήματα από deterministic έλεγχο."
    }