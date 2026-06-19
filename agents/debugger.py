import ast # Για deterministic ανάλυση σύνταξης και λογικών δομών
import builtins # Για έλεγχο built-in ονομάτων
import re
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()

BUILTIN_NAMES = set(dir(builtins))

DEBUGGER_SYSTEM_PROMPT = (
    "Είσαι ο Debugging Agent, ειδικευμένος στη σημασιολογική ανάλυση κώδικα Python μαθητών. "
    "Εντοπίζεις λογικές αποκλίσεις από τα ζητούμενα που δεν φαίνονται σε στατική ανάλυση."
)

llm_debugger = ChatGroq(model_name="llama-3.1-8b-instant", temperature=0)

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
        self.print_overwritten = False  # True αν ο μαθητής έγραψε print = (...) αντί print(...)
        self.quoted_number_vars = []
        self.has_len_method = False      # True αν χρησιμοποιεί λίστα.len() αντί len(λίστα)
        self.defined_functions = set()   # ονόματα συναρτήσεων που ορίζονται με def
        self.called_functions = set()    # ονόματα συναρτήσεων που καλούνται (εκτός builtins)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assigned.add(target.id)
                if target.id == "print":
                    # Κοινό λάθος αρχαρίων: print = (x, y) αντί για print(x, y)
                    self.print_overwritten = True
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
        self.defined_functions.add(node.name)
        for arg in node.args.args:
            self.assigned.add(arg.arg)
        self.generic_visit(node)

    _BUILTIN_CALL_NAMES = {
        "print", "len", "int", "str", "float", "bool", "type", "range",
        "enumerate", "list", "tuple", "dict", "set", "sorted", "reversed",
        "sum", "min", "max", "abs", "round", "input", "open", "zip", "map",
        "filter", "isinstance", "hasattr", "getattr", "setattr",
    }

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            self.has_print = True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            self.has_append = True
        # Εντοπίζει λίστα.len() — κοινό λάθος αρχαρίων (σωστό: len(λίστα))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "len":
            self.has_len_method = True
        # Παρακολουθεί κλήσεις ορισμένων συναρτήσεων (για εντοπισμό "def χωρίς κλήση")
        if isinstance(node.func, ast.Name) and node.func.id not in self._BUILTIN_CALL_NAMES:
            self.called_functions.add(node.func.id)
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
    # Bug 3: λίστα.len() αντί len(λίστα)
    if analyzer.has_len_method:
        categories.add("method_error")
        findings.append("Χρήση .len() ως μέθοδος — δεν υπάρχει. Χρησιμοποίησε len(λίστα) αντί για λίστα.len().")

    if undefined:
        categories.add("undefined_name")
        findings.append("Χρήση μεταβλητής πριν από ανάθεση: " + ", ".join(undefined))

    if (re.search(r'\bif\b', criteria_text) or "δομή" in criteria_text) and not analyzer.has_if:
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
        if analyzer.print_overwritten:
            # Ειδικό λάθος: print = (...) αντί print(...)
            categories.add("print_as_variable")
            findings.append("print_as_variable: ο μαθητής έγραψε 'print = (...)' αντί 'print(...)'.")
        elif (analyzer.has_def
              and analyzer.defined_functions
              and not (analyzer.called_functions & analyzer.defined_functions)):
            # Bug 5: συνάρτηση ορίστηκε αλλά δεν καλείται ποτέ — αιτία του ελλείποντος print()
            categories.add("missing_call")
            findings.append(
                "Συνάρτηση ορίζεται αλλά δεν καλείται ποτέ. "
                "Πρόσθεσε κλήση έξω από τη συνάρτηση και τύπωσε το αποτέλεσμα με print()."
            )
        else:
            categories.add("missing_output")
            findings.append("Απουσία print() ενώ ζητείται output.")

    if ("αριθμη" in criteria_text or "χωρίς εισαγωγικά" in criteria_text) and analyzer.quoted_number_vars:
        categories.add("type_mismatch")
        findings.append("Αριθμητική τιμή αποθηκεύτηκε ως string στις μεταβλητές: " + ", ".join(sorted(set(analyzer.quoted_number_vars))))

    return findings, sorted(categories)

def _semantic_analysis(student_code: str, success_criteria, current_task: str) -> str:
    """LLM semantic analysis: εντοπίζει λογικά λάθη που δεν φαίνονται σε AST.
    Καλείται μόνο όταν δεν υπάρχουν structural errors — αποφεύγει διπλό έλεγχο."""
    if not current_task or not student_code.strip():
        return ""
    criteria_text = _criteria_text(success_criteria)
    prompt = (
        f"{DEBUGGER_SYSTEM_PROMPT}\n\n"
        f"Εκφώνηση: {current_task}\n"
        f"Κριτήρια: {criteria_text}\n"
        f"Κώδικας μαθητή:\n{student_code}\n\n"
        f"Ελέγξε αν ο κώδικας ικανοποιεί τα ζητούμενα της εκφώνησης σημασιολογικά.\n"
        f"Έλεγξε ΕΙΔΙΚΑ:\n"
        f"- Αν οι τιμές που τυπώνονται (print) ταιριάζουν ΑΚΡΙΒΩΣ με αυτές της εκφώνησης (κεφαλαία/μικρά, ορθογραφία)\n"
        f"- Αν η λογική των if/elif/else κλάδων είναι αντεστραμμένη (π.χ. τυπώνει 'High' αντί 'Low')\n"
        f"- Αν μια συνθήκη ελέγχει λάθος τιμή ή χρησιμοποιεί λάθος τελεστή (>, <, >=, <=)\n"
        f"Αν βρεις ΟΠΟΙΟΔΗΠΟΤΕ από αυτά τα προβλήματα, γράψε 1 σύντομη πρόταση που περιγράφει ΤΙ ακριβώς είναι λάθος.\n"
        f"Αν ο κώδικας είναι πλήρως σωστός, γράψε ΜΟΝΟ: OK\n\nΑνάλυση:"
    )
    try:
        result = llm_debugger.invoke(prompt)
        analysis = result.content.strip()
        if not analysis or analysis.strip().upper().startswith("OK"):
            return ""
        return analysis
    except Exception:
        return ""


def debugging_node(state):
    student_code = state.get("student_code", "")
    success_criteria = state.get("success_criteria", "")
    current_task = state.get("current_task", "")

    if not student_code.strip():
        return {"debug_report": "[DEBUG: EMPTY] Δεν εντοπίστηκε κώδικας προς ανάλυση."}

    try:
        tree = ast.parse(student_code)
    except SyntaxError as e:
        # Συγκεκριμένη ανίχνευση: 'else if' αντί για 'elif' — κοινό λάθος αρχαρίων
        if re.search(r'\belse\s+if\b', student_code):
            return {
                "debug_report": "[DEBUG: ERROR] else_if_error"
            }
        return {
            "debug_report": f"[DEBUG: ERROR] Συντακτικό λάθος: {e.msg} (γραμμή {e.lineno})."
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

    # Structural analysis passed → LLM semantic analysis για λογικά λάθη
    semantic = _semantic_analysis(student_code, success_criteria, current_task)
    if semantic:
        return {
            "debug_report": f"[DEBUG: SEMANTIC] {semantic}"
        }

    return {
        "debug_report": "[DEBUG: OK] Δεν εντοπίστηκαν συντακτικά/λογικά προβλήματα από deterministic έλεγχο."
    }