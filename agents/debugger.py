import ast
import builtins
import re
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()

BUILTIN_NAMES = set(dir(builtins))

DEBUGGER_SYSTEM_PROMPT = (
    "Είσαι ο Debugging Agent, ειδικευμένος στην ανάλυση κώδικα Python μαθητών. "
    "Κρίνεις μόνος σου, βασισμένος ΑΠΟΚΛΕΙΣΤΙΚΑ στα δομικά στοιχεία και ευρήματα που σου δίνονται "
    "(ποτέ σε υποθέσεις), αν υπάρχει πρόβλημα στον κώδικα και ποιο είναι."
)

llm_debugger = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0)

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
        self.has_nonempty_list = False
        self.has_empty_list = False
        self.has_zero_index = False
        self.has_print = False
        self.has_empty_print = False
        self.list_has_only_strings = False
        self.has_all_empty_string_list = False
        self.print_overwritten = False
        self.quoted_number_vars = []
        self.has_len_method = False
        self.defined_functions = set()
        self.called_functions = set()
        self.has_aug_assign = False
        self.function_params = {}
        self.wrong_call_args = []
        self.print_args = []
        self.func_aliases = set()

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assigned.add(target.id)
                if target.id == "print":
                    self.print_overwritten = True
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            candidate = node.value.value.strip()
            if candidate.replace(".", "", 1).isdigit():
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.quoted_number_vars.append(target.id)
        if isinstance(node.value, ast.Name) and node.value.id in self.defined_functions:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.func_aliases.add(t.id)
        if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
            operands = (node.value.left, node.value.right)
            for target in node.targets:
                if isinstance(target, ast.Name) and any(
                    isinstance(o, ast.Name) and o.id == target.id for o in operands
                ):
                    self.has_aug_assign = True
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name):
            self.assigned.add(node.target.id)
            self.has_aug_assign = True
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
        self.function_params[node.name] = len(node.args.args)
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
            if not node.args and not node.keywords:
                self.has_empty_print = True
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    self.print_args.append(arg.id)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            self.has_append = True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "len":
            self.has_len_method = True
        if isinstance(node.func, ast.Name) and node.func.id not in self._BUILTIN_CALL_NAMES:
            fname = node.func.id
            self.called_functions.add(fname)
            if fname in self.function_params:
                expected = self.function_params[fname]
                actual = len(node.args)
                if expected > 0 and actual != expected:
                    self.wrong_call_args.append((fname, expected, actual))
        self.generic_visit(node)

    def visit_List(self, node):
        self.has_list = True
        if node.elts:
            self.has_nonempty_list = True
            if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
                self.list_has_only_strings = True
                if all(e.value == "" for e in node.elts):
                    self.has_all_empty_string_list = True
        else:
            self.has_empty_list = True
        self.generic_visit(node)

    def visit_Subscript(self, node):
        self.has_index = True
        if isinstance(node.slice, ast.Constant) and node.slice.value == 0:
            self.has_zero_index = True
        self.generic_visit(node)


def _gather_facts(tree, success_criteria, current_task=""):
    analyzer = _Analyzer()
    analyzer.visit(tree)

    facts = []
    criteria_text = (_criteria_text(success_criteria) + " " + (current_task or "")).lower()

    undefined = sorted(
        name for name in (analyzer.loaded - analyzer.assigned)
        if name not in BUILTIN_NAMES
    )
    if analyzer.has_len_method:
        facts.append(("Χρήση .len() ως μέθοδος — δεν υπάρχει. Χρησιμοποίησε len(λίστα) αντί για λίστα.len().", "method_error"))

    if undefined:
        facts.append(("Χρήση μεταβλητής πριν από ανάθεση: " + ", ".join(undefined), "undefined_name"))

    if (re.search(r'\bif\b', criteria_text) or "δομή" in criteria_text) and not analyzer.has_if:
        facts.append(("Απουσία δομής if ενώ απαιτείται από τα κριτήρια.", "missing_if"))

    if ("for" in criteria_text or "επανάληψ" in criteria_text) and not analyzer.has_for:
        facts.append(("Απουσία for loop ενώ απαιτείται από τα κριτήρια.", "missing_for"))

    if ("def" in criteria_text or "συνάρτη" in criteria_text) and not analyzer.has_def:
        facts.append(("Απουσία ορισμού συνάρτησης (def).", "missing_function"))

    if "append" in criteria_text and not analyzer.has_append:
        facts.append(("Απουσία χρήσης append() ενώ ζητείται.", "missing_append"))

    if ("λίστα" in criteria_text or "[]" in criteria_text) and not analyzer.has_list:
        facts.append(("Απουσία λίστας ([]) ενώ ζητείται.", "missing_list"))

    if ("index" in criteria_text or "[0]" in criteria_text) and not analyzer.has_index:
        facts.append(("Απουσία πρόσβασης με index ενώ ζητείται.", "missing_index"))

    if (analyzer.has_list and "append" not in criteria_text
            and analyzer.has_empty_list and not analyzer.has_nonempty_list):
        if any(kw in criteria_text for kw in ["στοιχεί", "string", "αριθμ", "τιμ"]):
            facts.append((
                "Η λίστα είναι άδεια ([]). Η εκφώνηση ζητά στοιχεία μέσα σε αυτήν — πρόσθεσέ τα απευθείας.",
                "empty_list",
            ))

    if analyzer.has_all_empty_string_list:
        facts.append((
            "Η λίστα έχει το σωστό πλήθος στοιχείων, αλλά είναι όλα κενά strings (''). "
            "Χρειάζεται πραγματικό περιεχόμενο μέσα σε κάθε στοιχείο, όχι κενό.",
            "empty_string_elements",
        ))

    if "[0]" in criteria_text and analyzer.has_index and not analyzer.has_zero_index:
        facts.append((
            "Χρησιμοποιείται λάθος index. Η εκφώνηση ζητά [0] για να πάρει το πρώτο στοιχείο.",
            "wrong_index",
        ))

    if ("άθροισμ" in criteria_text or "αθροιστ" in criteria_text) and analyzer.has_for and not analyzer.has_aug_assign:
        facts.append(("Λείπει ο αθροιστής (total += ...). Χρειάζεται μεταβλητή που ξεκινά από 0 και αυξάνεται σε κάθε επανάληψη.", "missing_accumulator"))

    for _while_node in ast.walk(tree):
        if not isinstance(_while_node, ast.While):
            continue
        _condition_names = {n.id for n in ast.walk(_while_node.test) if isinstance(n, ast.Name)}
        if not _condition_names:
            continue
        _modified_names = set()
        for _stmt in ast.walk(_while_node):
            if isinstance(_stmt, ast.AugAssign) and isinstance(_stmt.target, ast.Name):
                _modified_names.add(_stmt.target.id)
            elif isinstance(_stmt, ast.Assign):
                for _t in _stmt.targets:
                    if isinstance(_t, ast.Name):
                        _modified_names.add(_t.id)
        _has_break = any(isinstance(n, ast.Break) for n in ast.walk(_while_node))
        if not (_condition_names & _modified_names) and not _has_break:
            facts.append((
                "Πιθανό ατέρμονο (infinite) loop: η μεταβλητή στη συνθήκη του while δεν αλλάζει "
                "ποτέ μέσα στο σώμα του — αν εκτελεστεί, δεν σταματάει ποτέ. Χρειάζεται ενημέρωση "
                "της μεταβλητής (π.χ. x += 1) σε κάθε επανάληψη.",
                "possible_infinite_loop",
            ))
            break

    _bare_in_print = [
        a for a in analyzer.print_args
        if a in analyzer.defined_functions or a in analyzer.func_aliases
    ]
    _has_print_func_ref = bool(_bare_in_print) and not (analyzer.called_functions & analyzer.defined_functions)
    if _has_print_func_ref:
        facts.append((
            "Το print() λαμβάνει τη συνάρτηση ως αναφορά αντί να την καλεί (π.χ. print(process) αντί print(process(...))).",
            "print_func_ref",
        ))

    if analyzer.wrong_call_args and not _has_print_func_ref:
        fname, expected, actual = analyzer.wrong_call_args[0]
        facts.append((f"Η {fname}() καλείται με {actual} ορίσματα ενώ χρειάζεται {expected}.", "wrong_arg_count"))

    if ("τύπων" in criteria_text or "print" in criteria_text) and not analyzer.has_print:
        if analyzer.print_overwritten:
            facts.append(("Ο μαθητής έγραψε 'print = (...)' αντί 'print(...)' — η print αντικαταστάθηκε ως μεταβλητή.", "print_as_variable"))
        elif (analyzer.has_def
              and analyzer.defined_functions
              and not (analyzer.called_functions & analyzer.defined_functions)):
            facts.append(("Συνάρτηση ορίζεται αλλά δεν καλείται ποτέ — γι' αυτό λείπει το output.", "missing_call"))
        else:
            facts.append(("Απουσία print() ενώ ζητείται output.", "missing_output"))

    if ("αριθμη" in criteria_text or "χωρίς εισαγωγικά" in criteria_text) and analyzer.quoted_number_vars:
        facts.append((
            "Αριθμητική τιμή αποθηκεύτηκε ως string στις μεταβλητές: " + ", ".join(sorted(set(analyzer.quoted_number_vars))),
            "type_mismatch",
        ))

    if analyzer.list_has_only_strings and analyzer.has_for and any(
        kw in criteria_text for kw in ["αριθμ", "τετράγων", "τετραγων", "number", "num"]
    ):
        facts.append((
            "Η λίστα περιέχει strings (κείμενο σε εισαγωγικά) αντί για αριθμητικά στοιχεία.",
            "wrong_list_type",
        ))

    if analyzer.has_empty_print and any(
        kw in criteria_text for kw in ["τύπωσε", "τύπωνε", "εκτύπωσε", "print"]
    ):
        facts.append((
            "Χρησιμοποιείται print() χωρίς τίποτα μέσα — τυπώνεται κενή γραμμή.",
            "empty_print",
        ))

    raw_flags = {
        "has_if": analyzer.has_if,
        "has_for": analyzer.has_for,
        "has_def": analyzer.has_def,
        "has_append": analyzer.has_append,
        "has_index": analyzer.has_index,
        "has_list": analyzer.has_list,
        "has_print": analyzer.has_print,
        "has_empty_print": analyzer.has_empty_print,
        "has_aug_assign": analyzer.has_aug_assign,
        "has_len_method": analyzer.has_len_method,
        "undefined_names": undefined,
        "quoted_number_vars": sorted(set(analyzer.quoted_number_vars)),
        "list_has_only_strings": analyzer.list_has_only_strings,
        "wrong_call_args": analyzer.wrong_call_args,
    }
    return facts, raw_flags


# Πρέπει να μείνει συγχρονισμένο με has_structural_error/_targeted_hint_text στο mentor.py
# και με _extract_debug_categories στο routes.py.
_DEBUG_CATEGORIES = {
    "method_error": "χρήση .len() ως μέθοδος σε λίστα αντί της συνάρτησης len(λίστα)",
    "undefined_name": "χρήση μεταβλητής που δεν έχει οριστεί/αναγνωριστεί ακόμα",
    "missing_if": "λείπει δομή if/elif/else ενώ απαιτείται από την εκφώνηση/κριτήρια",
    "missing_for": "λείπει for loop ενώ απαιτείται",
    "missing_function": "λείπει ορισμός συνάρτησης (def) ενώ απαιτείται",
    "missing_append": "λείπει χρήση .append() ενώ απαιτείται",
    "missing_list": "λείπει δημιουργία λίστας ([]) ενώ απαιτείται",
    "missing_index": "λείπει πρόσβαση σε στοιχείο λίστας με index ενώ απαιτείται",
    "empty_list": "η λίστα δημιουργήθηκε άδεια ενώ η εκφώνηση ζητά στοιχεία μέσα της",
    "wrong_index": "χρησιμοποιείται λάθος index (όχι [0] όπου ζητείται το πρώτο στοιχείο)",
    "missing_accumulator": "λείπει αθροιστής (total += ...) σε loop άθροισης",
    "print_func_ref": "το print() καλείται με αναφορά συνάρτησης αντί να την καλέσει (print(f) αντί print(f()))",
    "wrong_arg_count": "συνάρτηση καλείται με λάθος αριθμό ορισμάτων",
    "print_as_variable": "το print αντικαταστάθηκε ως μεταβλητή (print = ...) αντί να χρησιμοποιηθεί ως συνάρτηση",
    "missing_call": "συνάρτηση ορίζεται σωστά αλλά δεν καλείται ποτέ",
    "type_mismatch": "μια αριθμητική τιμή είναι ΚΥΡΙΟΛΕΚΤΙΚΑ γραμμένη σε εισαγωγικά ΣΤΟΝ ΥΠΑΡΧΟΝΤΑ κώδικα (π.χ. age = \"25\") — ΟΧΙ όταν μια μεταβλητή απλώς λείπει ή λέγεται διαφορετικά",
    "wrong_list_type": "λίστα περιέχει strings αντί αριθμητικά στοιχεία όπου ζητούνται αριθμοί",
    "empty_print": "το print() καλείται χωρίς κανένα όρισμα",
    "missing_output": "λείπει εντελώς η εντολή print() ενώ ζητείται εμφάνιση αποτελέσματος",
    "possible_infinite_loop": "while loop όπου η μεταβλητή της συνθήκης δεν ενημερώνεται ποτέ μέσα στο σώμα του loop, χωρίς break — αν εκτελεστεί, δεν τερματίζει ποτέ",
    "empty_string_elements": "λίστα με το σωστό πλήθος στοιχείων αλλά όλα κενά strings ('') — χρειάζεται πραγματικό περιεχόμενο, ΟΧΙ αλλαγή πλήθους",
    "general_logic": "οποιοδήποτε άλλο σημασιολογικό/λογικό πρόβλημα που δεν ταιριάζει στις παραπάνω κατηγορίες",
}

_LLM_DEBUG_RE = re.compile(
    r"ΚΑΤΑΣΤΑΣΗ\s*:\s*(.*?)\s*ΚΑΤΗΓΟΡΙΑ\s*:\s*(.*?)\s*ΕΞΗΓΗΣΗ\s*:\s*(.*)",
    re.DOTALL | re.IGNORECASE,
)


def _reason_about_code(student_code: str, success_criteria, current_task: str, facts, raw_flags):
    criteria_text = _criteria_text(success_criteria)

    flags_lines = "\n".join(f"- {k}: {v}" for k, v in raw_flags.items())
    findings_lines = "\n".join(f"- {sentence}" for sentence, _cat in facts) or "Κανένα εύρημα από κανόνες."
    categories_lines = "\n".join(f"- {tag}: {desc}" for tag, desc in _DEBUG_CATEGORIES.items())

    prompt = (
        f"{DEBUGGER_SYSTEM_PROMPT}\n\n"
        f"Εκφώνηση: {current_task}\n"
        f"Κριτήρια: {criteria_text}\n"
        f"Κώδικας μαθητή:\n{student_code}\n\n"
        f"ΔΟΜΙΚΑ ΣΤΟΙΧΕΙΑ (από στατική ανάλυση — δεδομένα, ΟΧΙ γνώμη):\n{flags_lines}\n\n"
        f"ΕΥΡΗΜΑΤΑ ΚΑΝΟΝΩΝ (τι ενεργοποιήθηκε από deterministic ελέγχους βάσει κριτηρίων):\n{findings_lines}\n\n"
        f"Πέρα από τα παραπάνω, έλεγξε ΚΑΙ σημασιολογικά:\n"
        f"- Αν οι τιμές που τυπώνονται (print) ταιριάζουν ΑΚΡΙΒΩΣ με αυτές της εκφώνησης (κεφαλαία/μικρά, ορθογραφία)\n"
        f"- Αν η λογική των if/elif/else κλάδων είναι αντεστραμμένη (π.χ. τυπώνει 'High' αντί 'Low')\n"
        f"- Αν μια συνθήκη ελέγχει λάθος τιμή ή χρησιμοποιεί λάθος τελεστή (>, <, >=, <=)\n"
        f"- Αν η συνάρτηση ορίζεται σωστά (σωστό όνομα, παράμετροι, return) και καλείται σωστά\n"
        f"ΣΗΜΑΝΤΙΚΟ: Τα Ελληνικά ονόματα μεταβλητών/παραμέτρων (π.χ. α, β, γ, αποτέλεσμα) "
        f"είναι ΠΛΗΡΩΣ ΕΓΚΥΡΑ στην Python 3 — ΜΗΝ τα σημαίνεις ποτέ ως λάθος.\n"
        f"ΣΗΜΑΝΤΙΚΟ: ΜΗΝ ελέγχεις αν ΟΛΕΣ οι μεταβλητές που ζητά η εκφώνηση υπάρχουν στον κώδικα, "
        f"ούτε αν τα ΟΝΟΜΑΤΑ τους ταιριάζουν ακριβώς με αυτά που αναφέρει η εκφώνηση (π.χ. αν λείπει "
        f"ΤΕΛΕΙΩΣ μια μεταβλητή, ή αν ζητά 'age' και ο μαθητής έγραψε 'ag'/'years') — αυτό ΔΕΝ είναι "
        f"δική σου ευθύνη, το ελέγχει ήδη ξεχωριστό σύστημα (strict task matching). ΜΗΝ το σημάνεις "
        f"ΠΟΤΕ ως 'type_mismatch' ούτε καμία άλλη κατηγορία — αγνόησέ το εντελώς, ακόμα κι αν λείπει "
        f"ολόκληρη μεταβλητή τύπου string/αριθμού. Το 'type_mismatch' ΙΣΧΥΕΙ ΑΠΟΚΛΕΙΣΤΙΚΑ όταν μια "
        f"αριθμητική τιμή είναι ΚΥΡΙΟΛΕΚΤΙΚΑ γραμμένη μέσα σε εισαγωγικά ΣΤΟΝ ΥΠΑΡΧΟΝΤΑ κώδικα "
        f"(π.χ. age = \"25\") — ΠΟΤΕ όταν μια μεταβλητή απλώς λείπει ή λέγεται διαφορετικά. Εστίασε "
        f"ΜΟΝΟ στη ΔΟΜΗ, στους ΤΥΠΟΥΣ ΤΙΜΩΝ μεταβλητών που ΥΠΑΡΧΟΥΝ, και στη ΛΟΓΙΚΗ του κώδικα.\n\n"
        f"ΣΗΜΑΝΤΙΚΟ: Ο κώδικας μπορεί να χρησιμοποιεί έννοιες Python πέρα από τις βασικές δομές "
        f"(π.χ. dictionaries, try/except, classes, list comprehensions, string methods). Οι παραπάνω "
        f"κατηγορίες ΔΕΝ καλύπτουν όλες τις έννοιες της Python — αν ο κώδικας φαίνεται λογικά σωστός "
        f"για ό,τι περιγράφει η εκφώνηση αλλά χρησιμοποιεί κάτι που δεν αναγνωρίζεις με σιγουριά, "
        f"προτίμησε ΚΑΤΑΣΤΑΣΗ: OK αντί να υποθέσεις πρόβλημα που δεν είσαι σίγουρος ότι υπάρχει.\n\n"
        f"Έργο σου: απόφασε αν υπάρχει πρόβλημα στον κώδικα βάσει ΤΩΝ ΠΑΡΑΠΑΝΩ στοιχείων (δομικών "
        f"και σημασιολογικών) — ΜΗΝ υποθέσεις προβλήματα που δεν προκύπτουν από αυτά.\n"
        f"Αν υπάρχει πρόβλημα, επίλεξε ΑΚΡΙΒΩΣ ΜΙΑ κατηγορία από αυτή τη λίστα (όποια ταιριάζει καλύτερα):\n"
        f"{categories_lines}\n\n"
        f"Αν το πρόβλημα ΔΕΝ ταιριάζει με σιγουριά σε ΚΑΠΟΙΑ συγκεκριμένη κατηγορία (π.χ. είναι για "
        f"λείπουσα/λάθος-ονομασμένη μεταβλητή, όχι δομικό/τύπου πρόβλημα), χρησιμοποίησε "
        f"'general_logic' — ΜΗΝ διαλέξεις την πιο κοντινή κατηγορία αν στην πραγματικότητα δεν ταιριάζει.\n\n"
        f"Απάντησε ΑΚΡΙΒΩΣ σε αυτή τη μορφή, τίποτα άλλο πριν ή μετά:\n"
        f"ΚΑΤΑΣΤΑΣΗ: OK ή PROBLEM\n"
        f"ΚΑΤΗΓΟΡΙΑ: <μία από τις παραπάνω κατηγορίες, ή καμία αν ΚΑΤΑΣΤΑΣΗ=OK>\n"
        f"ΕΞΗΓΗΣΗ: <1-2 προτάσεις τεχνική περιγραφή του προβλήματος, ή \"Δεν εντοπίστηκαν προβλήματα.\" αν OK>"
    )

    try:
        result = llm_debugger.invoke(prompt)
        content = (result.content or "").strip()
        match = _LLM_DEBUG_RE.search(content)
        if not match:
            raise ValueError("unparseable debugger response")

        status_raw, category_raw, explanation = (g.strip() for g in match.groups())
        status = "OK" if status_raw.upper().startswith("OK") else "PROBLEM"

        if status == "OK":
            return "OK", "", explanation or "Δεν εντοπίστηκαν προβλήματα."

        category = category_raw.strip().lower()
        if category not in _DEBUG_CATEGORIES:
            category = "general_logic"
        if category == "type_mismatch" and not raw_flags.get("quoted_number_vars"):
            category = "general_logic"
        if not explanation:
            explanation = _DEBUG_CATEGORIES.get(category, "Εντοπίστηκε πρόβλημα.")
        return "PROBLEM", category, explanation
    except Exception:
        if facts:
            sentence, category = facts[0]
            return "PROBLEM", category, sentence
        return "OK", "", "Δεν εντοπίστηκαν συντακτικά/λογικά προβλήματα από deterministic έλεγχο."


def debugging_node(state):
    student_code = state.get("student_code", "")
    success_criteria = state.get("success_criteria", "")
    current_task = state.get("current_task", "")

    if not student_code.strip():
        return {"debug_report": "[DEBUG: EMPTY] Δεν εντοπίστηκε κώδικας προς ανάλυση."}

    try:
        tree = ast.parse(student_code)
    except SyntaxError as e:
        if re.search(r'\belse\s+if\b', student_code):
            return {
                "debug_report": "[DEBUG: ERROR] else_if_error"
            }
        if re.search(r'\bdef\s+\w+\s*\([^)]*\d[^)]*\)', student_code):
            return {
                "debug_report": "[DEBUG: ERROR] literal_param_error"
            }
        return {
            "debug_report": f"[DEBUG: ERROR] Συντακτικό λάθος: {e.msg} (γραμμή {e.lineno})."
        }

    facts, raw_flags = _gather_facts(tree, success_criteria, current_task)
    status, category, explanation = _reason_about_code(
        student_code, success_criteria, current_task, facts, raw_flags
    )

    if status == "OK":
        return {"debug_report": f"[DEBUG: OK] {explanation}"}

    return {
        "debug_report": (
            "[DEBUG: RULE_FAIL] Εντοπίστηκαν τεχνικά προβλήματα.\n"
            f"[DEBUG:CATEGORIES] {category}\n"
            f"- {explanation}"
        )
    }
