# AI Python Tutor

Διπλωματική εργασία: Σχεδίαση και Υλοποίηση Αυτόνομου Πράκτορα (Agentic AI) για Εξατομικευμένη Υποστήριξη και Αξιολόγηση Φοιτητών στον Προγραμματισμό.

Το σύστημα διδάσκει Python σε αρχάριους μέσα από έναν Mentor, ο οποίος συνεργάζεται με δύο ακόμα agents — έναν Debugger και έναν Assessor — για να εντοπίζουν λάθη, να αξιολογούν την πρόοδο του μαθητή και να προσαρμόζουν τη δυσκολία και το ύφος της διδασκαλίας.

## Αρχιτεκτονική

Τρεις agents, ο καθένας με συγκεκριμένο ρόλο:

- **Debugger** — αναλύει τον κώδικα με το `ast` module (δομή, μεταβλητές, τύποι) και δίνει τα ευρήματα σε ένα LLM που αποφασίζει αν υπάρχει πρόβλημα.
- **Assessor** — παίρνει την αναφορά του Debugger μαζί με το ιστορικό (προσπάθειες, hints, χρόνος) και αποφασίζει advance / repeat / support.
- **Mentor** — παίρνει την κρίση του Assessor και τη μεταφράζει σε φυσική γλώσσα προς τον μαθητή — δίνει κατεύθυνση, όχι έτοιμη λύση.

Τα δεδομένα από deterministic ανάλυση (AST, κριτήρια) τροφοδοτούν την κρίση του LLM αντί αυτό να αποφασίζει μόνο του — έτσι περιορίζεται το hallucination.

## Λειτουργίες

- Onboarding: ο Mentor ρωτά την εμπειρία του μαθητή και προσαρμόζει θεωρία/ασκήσεις.
- 5 κεφάλαια Python (Μεταβλητές & Τύποι Δεδομένων, Δομές Ελέγχου, Λίστες, Επαναλήψεις, Συναρτήσεις) με θεωρία, δυναμικές ασκήσεις και targeted hints.
- Adaptive difficulty ανάλογα με την επίδοση του μαθητή.
- Open Learner Model — προβολή προόδου ανά κεφάλαιο (mastery %).
- Ιστορικό συνομιλιών ανά συνεδρία.
- Εξάσκηση: επαναληπτικές ασκήσεις σε ολοκληρωμένα κεφάλαια.
- Ελεύθερος έλεγχος κώδικα (χωρίς βαθμολόγηση) για δικό του κώδικα του μαθητή.

## Τεχνολογίες

| Επίπεδο | Τεχνολογία |
|---|---|
| Backend | FastAPI, Python 3.13 |
| Agents | LangGraph, LangChain |
| LLM | Groq — `llama-3.3-70b-versatile` (+ `llama-3.1-8b-instant` για ταξινόμηση πρόθεσης) |
| Βάση δεδομένων | SQLite τοπικά (aiosqlite) / PostgreSQL σε production |
| Frontend | React, Vite, Monaco Editor |
| Deployment | Vercel (frontend) + Render (backend) + Neon (PostgreSQL) |

## Δομή

- `agents/` — Mentor, Debugger, Assessor
- `core/` — LangGraph state machine και state schema
- `api/` — FastAPI endpoints
- `database/` — SQLAlchemy models
- `content/` — ύλη μαθημάτων (lessons.json)
- `frontend/` — React εφαρμογή
- `test_system.py` — automated tests

## Ζωντανή έκδοση

https://my-thesis-nine.vercel.app

Backend σε Render (free tier) — αν έχει αδρανοποιηθεί, το πρώτο request μπορεί να αργήσει λίγα δευτερόλεπτα.
