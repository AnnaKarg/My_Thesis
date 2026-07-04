"""
test_system.py — Σύστημα ελέγχου AI Python Tutor

Εκτέλεση: python test_system.py
Εκτιμώμενος χρόνος: ~3-5 λεπτά (LLM calls)

Τρία επίπεδα:
  Α) Unit tests χωρίς LLM  — instant
  Β) Intent classification  — ~30 δευτ. (LLM)
  Γ) Pipeline integration   — ~3 λεπτά (debugger+assessor+mentor)
"""

import asyncio, sys, time
from langchain_core.messages import HumanMessage, AIMessage

# ── Terminal colors ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ── Καταμέτρηση αποτελεσμάτων ────────────────────────────────────────────────
_passed   = 0
_failed   = 0
_failures = []

def ok(label):
    global _passed
    _passed += 1
    print(f"  {GREEN}✓{RESET} {label}")

def fail(label, detail=""):
    global _failed
    _failed += 1
    _failures.append(label)
    print(f"  {RED}✗{RESET} {label}")
    if detail:
        print(f"    {YELLOW}↳ {detail}{RESET}")

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*58}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*58}{RESET}")

# ── Βοηθητικά για state ──────────────────────────────────────────────────────
TASK = (
    "Δημιούργησε μεταβλητή age με τιμή 25 και μεταβλητή "
    "first_name ως string. Τύπωνε και τις δύο με print()."
)
CRITERIA = [
    "Υπάρχει ανάθεση τιμής με = σε μεταβλητή.",
    "Το string αποθηκεύεται με εισαγωγικά.",
    "Ο αριθμητικός τύπος αποθηκεύεται χωρίς εισαγωγικά.",
    "Χρησιμοποιείται print().",
    "Δεν υπάρχουν συντακτικά λάθη.",
]
PERF = '{"total_attempts":0,"avg_time_spent":0,"frequent_error_categories":[],"recent_attempts":0}'

def mkstate(**kw):
    s = {
        "messages": [],
        "student_code": "",
        "debug_report": "",
        "is_correct": False,
        "assessment_feedback": "",
        "assessment_score": 0,
        "assessment_decision": "repeat",
        "current_lesson": "Variables & Data Types",
        "current_lesson_id": 1,
        "current_task": TASK,
        "success_criteria": CRITERIA,
        "experience_level": "beginner",
        "profile_checked": True,
        "performance_summary": PERF,
        "understanding_level": "developing",
        "attempts_count": 0,
        "hint_count": 0,
        "time_spent": 0.0,
        "task_started": False,
        "awaiting_questions": False,
        "event_type": "",
        "is_first_login": False,
        "difficulty_probe_direction": "",
        "avg_hints_per_task": 0.0,
    }
    s.update(kw)
    return s

def H(text): return HumanMessage(content=text)
def A(text): return AIMessage(content=text)


# ════════════════════════════════════════════════════════════════════════════
# Α) UNIT TESTS — χωρίς LLM, τρέχουν instant
# ════════════════════════════════════════════════════════════════════════════
def run_unit_tests():
    from agents.mentor import _is_gibberish, _new_lesson_theory_shown, _task_already_presented
    # _count_hints και _infer_awaiting_questions είναι στο api.routes
    # τα εισάγουμε με monkey-patch αφού δεν έχουν side-effects
    from api import routes as _r
    _count_hints             = _r._count_hints
    _infer_awaiting_questions = _r._infer_awaiting_questions

    # ── _is_gibberish ────────────────────────────────────────────────────
    section("Α1) _is_gibberish")

    should_be_gibberish = [
        # Ελληνικά
        ("σρυξδτ",  "Greek: 3+ συνεχόμενα σύμφωνα (ξδτ)"),
        ("ααααα",   "Greek: ίδιο φωνήεν × 5"),
        ("οοοο",    "Greek: ίδιο φωνήεν × 4"),
        ("ξδτφγσ",  "Greek: χωρίς φωνήεντα"),
        ("ασδφασ",  "Greek: 3+ συνεχόμενα σύμφωνα (σδφ)"),
        ("α",       "μόνο 1 χαρακτήρας"),
        ("f",       "μόνο 1 χαρακτήρας (Latin)"),
        ("",        "κενό string"),
        # Latin gibberish
        ("sdfgh",   "Latin: χωρίς φωνήεντα"),
        ("qwrty",   "Latin: χωρίς φωνήεντα"),
        ("ddsdsd",  "Latin: χωρίς φωνήεντα"),
        ("ffff",    "Latin: όλα ίδια × 4"),
        ("ssss",    "Latin: όλα ίδια × 4"),
    ]
    should_not_be_gibberish = [
        ("Ναι",      "έγκυρη ελληνική λέξη"),
        ("οχι",      "έγκυρη ελληνική λέξη"),
        ("yes",      "αγγλική λέξη"),
        ("Python",   "αγγλική λέξη (pyt = Latin, δεν μετράει)"),
        ("ok",       "διεθνής"),
        ("Δεν ξέρω", "ελληνική φράση"),
        ("beginner", "αγγλική λέξη"),
        ("afafafe",  "Latin με φωνήεντα → LLM decides"),
        ("string",   "αγγλική λέξη (str = Latin, δεν μετράει)"),
    ]

    for text, desc in should_be_gibberish:
        if _is_gibberish(text):
            ok(f'gibberish("{text}") [{desc}]')
        else:
            fail(f'gibberish("{text}") → True expected [{desc}]')

    for text, desc in should_not_be_gibberish:
        if not _is_gibberish(text):
            ok(f'not gibberish("{text}") [{desc}]')
        else:
            fail(f'not gibberish("{text}") → False expected [{desc}]')

    # ── _new_lesson_theory_shown ─────────────────────────────────────────
    section("Α2) _new_lesson_theory_shown")

    cases = [
        ([H("Ναι")],                                              False, "μόνο user msg, τίποτα άλλο"),
        ([H("Ναι"), A("[BUTTON:START_TASK]"), H("code")],         True,  "task ξεκίνησε (START_TASK)"),
        ([H("Ναι"), A("Θεωρία\n[AWAITING_QUESTIONS]"), H("Πάμε")], True, "[AWAITING_QUESTIONS] υπάρχει"),
        ([H("ok"),  A("...\n[ASSESSMENT:ADVANCE]"), H("Ναι")],   False, "ADVANCE αλλά νέα θεωρία δεν δειχθεί"),
    ]
    for msgs, expected, desc in cases:
        result = _new_lesson_theory_shown(msgs)
        if result == expected:
            ok(f"theory_shown={expected} [{desc}]")
        else:
            fail(f"theory_shown={expected} expected (got {result}) [{desc}]")

    # ── _task_already_presented ──────────────────────────────────────────
    section("Α3) _task_already_presented")

    cases2 = [
        ([H("Ναι"), A("Θεωρία\n[AWAITING_QUESTIONS]"), H("Πάμε")],   False, "μόνο θεωρία, όχι task"),
        ([H("Πάμε"), A("Ορίστε!\n[BUTTON:START_TASK]"), H("code")],   True,  "task δόθηκε"),
        ([H("ok"),   A("[ASSESSMENT:ADVANCE]"), H("Πάμε")],            False, "μετά ADVANCE, νέα άσκηση"),
    ]
    for msgs, expected, desc in cases2:
        result = _task_already_presented(msgs)
        if result == expected:
            ok(f"task_presented={expected} [{desc}]")
        else:
            fail(f"task_presented={expected} expected (got {result}) [{desc}]")

    # ── _count_hints ─────────────────────────────────────────────────────
    section("Α4) _count_hints")

    class FakeH:
        def __init__(self, role, content):
            self.role = role; self.content = content; self.attempts_count = 0

    h0 = [FakeH("ai","[BUTTON:START_TASK]"), FakeH("human","code"), FakeH("ai","[ASSESSMENT:REPEAT]")]
    h2 = [
        FakeH("ai","[BUTTON:START_TASK]"),
        FakeH("human","code"), FakeH("ai","Hint1\n[ASSESSMENT:REPEAT]\n[HINT]"),
        FakeH("human","code"), FakeH("ai","Hint2\n[ASSESSMENT:REPEAT]\n[HINT]"),
        FakeH("human","code"),
    ]
    h_from_prev_task = [
        FakeH("ai","OLD\n[HINT]"), FakeH("ai","OLD\n[HINT]"), FakeH("ai","OLD\n[HINT]"),
        FakeH("ai","[BUTTON:START_TASK]"),        # ← νέα άσκηση ξεκινά εδώ
        FakeH("human","code"), FakeH("ai","[HINT]"),
    ]

    for history, expected, desc in [
        (h0,               0, "χωρίς hints"),
        (h2,               2, "2 hints"),
        (h_from_prev_task, 1, "3 hints παλιάς + 1 νέας → μετράει μόνο 1"),
    ]:
        result = _count_hints(history)
        if result == expected:
            ok(f"_count_hints={expected} [{desc}]")
        else:
            fail(f"_count_hints={expected} expected (got {result}) [{desc}]")

    # ── _infer_awaiting_questions ─────────────────────────────────────────
    section("Α5) _infer_awaiting_questions")

    for history, pc, ts, expected, desc in [
        ([FakeH("ai","Θεωρία\n[AWAITING_QUESTIONS]")],          True,  False, True,  "τελευταίο AI έχει [AWAITING_QUESTIONS]"),
        ([FakeH("ai","Θεωρία\n[AWAITING_QUESTIONS]")],          False, False, False, "profile_checked=False → αμέσως False"),
        ([FakeH("ai","Θεωρία\n[AWAITING_QUESTIONS]")],          True,  True,  False, "task_started=True → αμέσως False"),
        ([FakeH("ai","[BUTTON:START_TASK]")],                   True,  False, False, "task button → False"),
        ([],                                                    True,  False, False, "κενό ιστορικό → False"),
    ]:
        result = _infer_awaiting_questions(history, pc, ts)
        if result == expected:
            ok(f"awaiting={expected} [{desc}]")
        else:
            fail(f"awaiting={expected} expected (got {result}) [{desc}]")


# ════════════════════════════════════════════════════════════════════════════
# Β) INTENT CLASSIFICATION — LLM, ~30 δευτ.
# ════════════════════════════════════════════════════════════════════════════
def run_intent_tests():
    from agents.mentor import _classify_intent

    section("Β) INTENT CLASSIFICATION (LLM)")

    cases = [
        # (input, profile_checked, task_started, expected, desc)

        # Gibberish → always "other"
        ("σρυξδτ",          False, False, "other",          "Greek consonant cluster"),
        ("ααααα",           False, False, "other",          "Same vowel ×5"),
        ("f",               False, False, "other",          "Single char"),

        # Πριν profile check
        ("Ναι",             False, False, "profile_yes",    "Affirmative πριν profile"),
        ("όχι ποτέ",        False, False, "profile_no",     "Negative πριν profile"),
        ("δεν έχω εμπειρία",False, False, "profile_no",     "No experience"),
        ("λίγο",            False, False, "profile_yes",    "Some experience"),

        # Μετά profile, θεωρία
        ("Ναι πάμε!",       True,  False, "wants_task",     "Θέλει άσκηση"),
        ("κατάλαβα",        True,  False, "wants_task",     "Understood → wants task"),
        ("δεν έχω απορία",  True,  False, "wants_task",     "No questions"),
        ("τι είναι string;",True,  False, "theory_question","Theory question"),
        ("πώς λειτουργεί το if;", True, True, "theory_question","Theory Q during task"),

        # Κατά τη διάρκεια άσκησης
        ("δεν καταλαβαίνω το λάθος", True, True, "theory_question", "Asks for help → theory_question (per prompt)"),
        ("1",               True,  True,  "other",          "Menu σβήστηκε — μονοψήφιο '1' είναι πλέον gibberish/other"),
        ("2",               True,  True,  "other",          "Menu σβήστηκε — μονοψήφιο '2' είναι πλέον gibberish/other"),
        ("3",               True,  True,  "other",          "Menu σβήστηκε — μονοψήφιο '3' είναι πλέον gibberish/other"),
    ]

    for inp, pc, ts, expected, desc in cases:
        t0 = time.time()
        result = _classify_intent(inp, pc, ts)
        elapsed = time.time() - t0
        tag = f"{DIM}({elapsed:.1f}s){RESET}"
        if result == expected:
            ok(f'"{inp}" → {expected} {tag} [{desc}]')
        else:
            fail(f'"{inp}" → {expected} expected (got {result!r}) [{desc}]')


# ════════════════════════════════════════════════════════════════════════════
# Γ) PIPELINE INTEGRATION — debugger+assessor+mentor, ~3 λεπτά
# ════════════════════════════════════════════════════════════════════════════
async def run_pipeline_tests():
    from core.app import app as graph

    section("Γ) PIPELINE INTEGRATION")

    async def chk(label, state, must=(), must_not=(), timeout=90):
        try:
            t0 = time.time()
            out = await asyncio.wait_for(
                graph.ainvoke(state, config={"recursion_limit": 15}),
                timeout=timeout
            )
            elapsed = time.time() - t0
            resp = out["messages"][-1].content
            issues = []
            for tok in must:
                if tok not in resp:
                    issues.append(f"λείπει: {tok!r}")
            for tok in must_not:
                if tok in resp:
                    issues.append(f"ΔΕΝ πρέπει να περιέχει: {tok!r}")
            tag = f"{DIM}({elapsed:.1f}s){RESET}"
            if not issues:
                ok(f"{label} {tag}")
            else:
                fail(label, " | ".join(issues))
                print(f"    {YELLOW}Response: {resp[:300]!r}{RESET}")
        except asyncio.TimeoutError:
            fail(label, "TIMEOUT")
        except Exception as e:
            fail(label, str(e))

    # ── Γ1. Profile flow ─────────────────────────────────────────────────
    print(f"\n  {BOLD}Γ1. Profile flow{RESET}")

    await chk(
        "Gibberish (σρυξδτ) πριν profile → επαναφορά ερώτησης",
        mkstate(is_first_login=True, profile_checked=False,
                messages=[H("σρυξδτ")]),
        must=["κώδικα"],   # welcome ή re-ask — και τα δύο αναφέρουν "κώδικα"
        must_not=["[AWAITING_QUESTIONS]", "[BUTTON:START_TASK]"]
    )

    await chk(
        "Gibberish (ααααα) χωρίς profile → 'δεν κατάλαβα'",
        mkstate(is_first_login=False, profile_checked=False,
                messages=[H("ααααα")]),
        must=["κατάλαβα"],
        must_not=["[AWAITING_QUESTIONS]", "[BUTTON:START_TASK]"]
    )

    await chk(
        "'Ναι' (profile set, θεωρία ΠΟΤΕ δεν δείχθηκε) → θεωρία πρώτα",
        mkstate(profile_checked=True, task_started=False, awaiting_questions=False,
                messages=[H("Ναι")]),
        must=["[AWAITING_QUESTIONS]"],
        must_not=["[BUTTON:START_TASK]"]
    )

    await chk(
        "'Πάμε' (θεωρία ΗΔΗ δείχθηκε) → δίνει άσκηση",
        mkstate(profile_checked=True, task_started=False, awaiting_questions=True,
                messages=[H("Ναι"), A("Θεωρία\n[AWAITING_QUESTIONS]"), H("Πάμε")]),
        must=["[BUTTON:START_TASK]"]
    )

    # ── Γ2. Κώδικας: Debugger + Assessor ─────────────────────────────────
    print(f"\n  {BOLD}Γ2. Κώδικας (Debugger + Assessor){RESET}")

    BAD1 = "pritn('hello')"   # NameError — debugger πιάνει
    await chk(
        "Λάθος κώδικας (typo pritn) → hint, ΌΧΙ 'δεν κατάλαβα'",
        mkstate(task_started=True, student_code=BAD1,
                messages=[H("Ναι"), A("[BUTTON:START_TASK]"),
                          H(f"Υποβολή κώδικα:\n```python\n{BAD1}\n```")]),
        must=["[ASSESSMENT:REPEAT]"],
        must_not=["Δεν κατάλαβα", "Θα ήμουν", "[ASSESSMENT:ADVANCE]"]
    )

    BAD2 = 'age = 25\nprint(age)'   # Λείπει first_name + print(first_name)
    await chk(
        "Ελλιπής κώδικας (λείπει first_name) → repeat",
        mkstate(task_started=True, student_code=BAD2,
                messages=[H("Ναι"), A("[BUTTON:START_TASK]"),
                          H(f"Υποβολή κώδικα:\n```python\n{BAD2}\n```")]),
        must=["[ASSESSMENT:REPEAT]"],
        must_not=["[ASSESSMENT:ADVANCE]"]
    )

    CORRECT = 'age = 25\nfirst_name = "Anna"\nprint(age, first_name)'
    await chk(
        "Σωστός κώδικας → [ASSESSMENT:ADVANCE]",
        mkstate(task_started=True, student_code=CORRECT, attempts_count=1,
                messages=[H("Ναι"), A("[BUTTON:START_TASK]"),
                          H(f"Υποβολή κώδικα:\n```python\n{CORRECT}\n```")]),
        must=["[ASSESSMENT:ADVANCE]"],
        must_not=["Δεν κατάλαβα"]
    )

    SYNTAX_ERR = 'age = 25\nif age == 25\n    print(age)'
    await chk(
        "Syntax error (λείπει :) → hint με αναφορά στο σφάλμα",
        mkstate(task_started=True, student_code=SYNTAX_ERR,
                messages=[H("Ναι"), A("[BUTTON:START_TASK]"),
                          H(f"Υποβολή κώδικα:\n```python\n{SYNTAX_ERR}\n```")]),
        must=["[ASSESSMENT:REPEAT]"],
        must_not=["[ASSESSMENT:ADVANCE]", "Δεν κατάλαβα"]
    )

    # ── Γ3. Συνομιλία ────────────────────────────────────────────────────
    print(f"\n  {BOLD}Γ3. Συνομιλία{RESET}")

    await chk(
        "Ερώτηση θεωρίας (awaiting) → απάντηση, ΌΧΙ task",
        mkstate(profile_checked=True, awaiting_questions=True,
                messages=[H("Ναι"), A("Θεωρία\n[AWAITING_QUESTIONS]"),
                          H("τι είναι τα strings;")]),
        must_not=["[BUTTON:START_TASK]", "[ASSESSMENT:ADVANCE]"]
    )

    await chk(
        "Timeout χωρίς κώδικα → ενθάρρυνση, ΌΧΙ λύση",
        mkstate(task_started=True, event_type="no_submission_timeout",
                messages=[H("Ναι"), A("[BUTTON:START_TASK]"),
                          H("__NO_SUBMISSION_TIMEOUT__")]),
        must_not=["age = 25", "first_name =", "[ASSESSMENT:ADVANCE]"]
    )

    await chk(
        "Code submission → ΟΧΙ 'Δεν κατάλαβα'",
        mkstate(task_started=True, student_code="pritn('hello')",
                messages=[H("Ναι"), A("[BUTTON:START_TASK]"),
                          H("Υποβολή κώδικα:\n```python\npritn('hello')\n```")]),
        must_not=["Δεν κατάλαβα", "Θα ήμουν ευγνώμων"]
    )

    await chk(
        "'δεν καταλαβαίνω το λάθος μου' (task active, με debug) → hint",
        mkstate(task_started=True, student_code="pritn('hello')",
                debug_report="NameError: name 'pritn' is not defined",
                messages=[H("Ναι"), A("[BUTTON:START_TASK]"),
                          H(f"Υποβολή κώδικα:\n```python\npritn('hello')\n```"),
                          A("Υπόδειξη...\n[ASSESSMENT:REPEAT]\n[HINT]"),
                          H("δεν καταλαβαίνω το λάθος μου")]),
        must_not=["[ASSESSMENT:ADVANCE]"]
    )

    # ── Γ4. Περίεργα inputs ───────────────────────────────────────────────
    print(f"\n  {BOLD}Γ4. Περίεργα / edge-case inputs{RESET}")

    await chk(
        "Κενό μήνυμα → δεν κρασάρει",
        mkstate(profile_checked=True, messages=[H("")]),
    )

    await chk(
        "Αριθμός '42' (χωρίς menu context) → δεν κρασάρει",
        mkstate(profile_checked=True, awaiting_questions=True,
                messages=[H("Ναι"), A("Θεωρία\n[AWAITING_QUESTIONS]"), H("42")]),
    )

    await chk(
        "Πολύ μεγάλο μήνυμα (500 χαρακτήρες) → δεν κρασάρει",
        mkstate(profile_checked=True,
                messages=[H("α" * 500)]),
        must=["κατάλαβα"],
    )


# ════════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════════
def _print_summary():
    total = _passed + _failed
    color = GREEN if _failed == 0 else RED
    print(f"\n{BOLD}{'═'*58}{RESET}")
    print(f"{BOLD}  ΑΠΟΤΕΛΕΣΜΑΤΑ: {color}{_passed}/{total} πέρασαν{RESET}")
    if _failures:
        print(f"{BOLD}{RED}  Αποτυχίες:{RESET}")
        for f in _failures:
            print(f"    {RED}• {f}{RESET}")
    print(f"{BOLD}{'═'*58}{RESET}\n")


if __name__ == "__main__":
    print(f"\n{BOLD}{'═'*58}{RESET}")
    print(f"{BOLD}  AI PYTHON TUTOR — SYSTEM TESTS{RESET}")
    print(f"{BOLD}{'═'*58}{RESET}")

    # Sync phases (unit + LLM intent classification) — εκτελούνται ΠΡΙΝ το event loop
    run_unit_tests()
    run_intent_tests()

    # Async phase (full pipeline) — ξεχωριστό event loop
    asyncio.run(run_pipeline_tests())

    _print_summary()
    sys.exit(0 if _failed == 0 else 1)
