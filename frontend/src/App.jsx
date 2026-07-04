import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import Editor from '@monaco-editor/react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { Send, Code2, Play, LogOut, Eye, EyeOff, BookOpen, Zap, FileCode, TriangleAlert } from 'lucide-react';
import './App.css';

// Τοπικά: direct στο backend. Production (Vercel): μέσω proxy (/backend) — χωρίς CORS
const _isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const API_BASE = _isLocal ? (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000') : '/backend';

export default function App() {
  const [user, setUser] = useState(JSON.parse(localStorage.getItem('python_user_data')) || null);
  const [currentView, setCurrentView] = useState(
    localStorage.getItem('python_user_data') ? 'landing' : null
  );
  const [courseCompleted, setCourseCompleted] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState(0);
  const [showHistorySidebar, setShowHistorySidebar] = useState(false);
  const [historySessions, setHistorySessions] = useState([]);
  const [historyModal, setHistoryModal] = useState(null); // {title, messages}
  const [showProgressModal, setShowProgressModal] = useState(false);
  const [showLeaveTaskConfirm, setShowLeaveTaskConfirm] = useState(false);
  const [pendingFreshTaskOnReturn, setPendingFreshTaskOnReturn] = useState(false);
  const [showLeaveFreeCheckConfirm, setShowLeaveFreeCheckConfirm] = useState(false);
  const [showLeavePracticeConfirm, setShowLeavePracticeConfirm] = useState(false);
  // Button 3 — ελεύθερος έλεγχος κώδικα (χωρίς βαθμολόγηση, ξεχωριστό από τη ροή μαθημάτων)
  const [freeCheckCode, setFreeCheckCode] = useState('');
  const [freeCheckDescription, setFreeCheckDescription] = useState('');
  const [freeCheckResponse, setFreeCheckResponse] = useState(null);
  const [freeCheckLoading, setFreeCheckLoading] = useState(false);
  const [freeCheckError, setFreeCheckError] = useState('');
  const FREE_CHECK_MAX_CHARS = 2000;
  // Button 2 — Εξάσκηση (πραγματική βαθμολόγηση, ξεχωριστό από τη σειριακή ροή μαθημάτων)
  const [practiceSelectedLessonIds, setPracticeSelectedLessonIds] = useState([]);
  const [practiceCurrentTask, setPracticeCurrentTask] = useState(null); // {task, success_criteria, lesson_id, lesson_title, difficulty}
  const [practiceCode, setPracticeCode] = useState('');
  const [practiceResponse, setPracticeResponse] = useState(null);
  const [practiceIsCorrect, setPracticeIsCorrect] = useState(null);
  const [practiceLoading, setPracticeLoading] = useState(false);
  const [practiceError, setPracticeError] = useState('');
  const [practiceStreakCurrent, setPracticeStreakCurrent] = useState(0);
  const [practiceStreakGoal, setPracticeStreakGoal] = useState(0);
  const [practiceGoalInput, setPracticeGoalInput] = useState('');
  // Custom tooltip (portal-based, ΟΧΙ position:absolute μέσα στο modal) — το native title ήταν
  // αναξιόπιστο/αργό, και το πρώτο absolute-positioned πείραμα έκοβε πάνω/πλάγια από το modal
  // overflow. Με portal στο document.body + fixed coordinates, ΔΕΝ κόβεται ποτέ από κανένα container.
  const [struggleTooltip, setStruggleTooltip] = useState(null); // {id, top, left, placement}
  const [isRegistering, setIsRegistering] = useState(false);
  const [authForm, setAuthForm] = useState({ username: '', password: '' });
  const [authError, setAuthError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [registerSuccessModal, setRegisterSuccessModal] = useState(false);

  const [authLoading, setAuthLoading] = useState(false);
  const [windowWidth, setWindowWidth] = useState(window.innerWidth);

  const [showEditor, setShowEditor] = useState(false);
  const [editorEnabled, setEditorEnabled] = useState(false);
  const [taskJustCompleted, setTaskJustCompleted] = useState(false); // διαχωρίζει "δεν ξεκίνησε ακόμα" από "μόλις ολοκληρώθηκε"
  const [startTime, setStartTime] = useState(null);
  const [taskActive, setTaskActive] = useState(false);
  const [hintStage, setHintStage] = useState(0);        // 0=καμία υπόδειξη, 1/2/3=έχουν σταλεί
  const [lastActivityTime, setLastActivityTime] = useState(null); // τελευταία ενέργεια (start ή υποβολή)
  const [experienceLevel, setExperienceLevel] = useState('beginner');
  const [masteryProfile, setMasteryProfile] = useState([]);
  // Adaptive hint timer: beginner χρειάζεται περισσότερο χρόνο (Cognitive Load Theory)
  // expert: 40s/60s/90s (αδιέξοδο εντοπίζεται γρηγορότερα), beginner: 70s/90s/120s
  const HINT_DELAYS = experienceLevel === 'expert'
    ? [40000, 60000, 90000]
    : [70000, 90000, 120000];
  const [code, setCode] = useState('# Γράψε τον κώδικά σου εδώ...');
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [loading, setLoading] = useState(false);
  // Ref ώστε το timer callback να βλέπει την τρέχουσα τιμή loading
  // (το state δεν διαβάζεται σωστά μέσα σε stale closures setTimeout)
  const loadingRef = useRef(false);
  const chatEndRef = useRef(null);
  const monacoEditorRef = useRef(null);

  const startButtonToken = '[BUTTON:START_TASK]';
  const legacyStartButtonToken = '[BUTTON:CONTINUE_TASK]';

  const sanitizeMentorText = (text = '') =>
    text
      .replace(startButtonToken, '')
      .replace(legacyStartButtonToken, '')
      .replace('[ASSESSMENT:ADVANCE]', '')
      .replace('[ASSESSMENT:REPEAT]', '')
      .replace('[ASSESSMENT:SUPPORT]', '');

  const hasStartButtonToken = (text = '') =>
    text.includes(startButtonToken) || text.includes(legacyStartButtonToken);

  const getEditorFileName = (username) => {
    const normalized = (username || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '_');

    return normalized ? `${normalized}.py` : 'main.py';
  };

  const formatSessionDate = (isoString) => {
    if (!isoString) return 'Παλιά συνομιλία';
    const d = new Date(isoString);
    const today = new Date();
    const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === today.toDateString())
      return `Σήμερα ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
    if (d.toDateString() === yesterday.toDateString()) return 'Χθες';
    const months = ['Ιαν','Φεβ','Μαρ','Απρ','Μάι','Ιουν','Ιουλ','Αυγ','Σεπ','Οκτ','Νοε','Δεκ'];
    return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
  };

  const bootstrapSession = async (targetUser, isRetry = false) => {
    if (!targetUser?.id) return;
    try {
      const res = await axios.get(`${API_BASE}/session/${targetUser.id}/welcome`);
      setMessages([{ role: 'ai', content: res.data.message }]);
      if (res.data.session_id) setCurrentSessionId(res.data.session_id);
      if (res.data.experience_level) setExperienceLevel(res.data.experience_level);
      if (res.data.mastery_profile) setMasteryProfile(res.data.mastery_profile);
    } catch (err) {
      // Μία επανάληψη πριν παραδοθούμε στο fallback μήνυμα — καλύπτει παροδικά network hiccups
      // ώστε να μη χάνεται σιωπηλά ολόκληρο το welcome payload (μαζί με το mastery_profile).
      if (!isRetry) {
        return bootstrapSession(targetUser, true);
      }
      setMessages([{ role: 'ai', content: `Γεια σου ${targetUser.username}! Πριν συνεχίσουμε, έχεις κάποια απορία;` }]);
    }
  };

  const fetchHistorySessions = async () => {
    if (!user?.id) return;
    try {
      const res = await axios.get(`${API_BASE}/history/${user.id}/sessions`);
      setHistorySessions(res.data.filter(s => s.session_id !== currentSessionId));
    } catch { /* ignore */ }
  };

  const openSessionModal = async (session) => {
    try {
      const res = await axios.get(`${API_BASE}/history/${user.id}/sessions/${session.session_id}`);
      setHistoryModal({ title: formatSessionDate(session.created_at), messages: res.data.messages });
    } catch { /* ignore */ }
  };

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (user && currentView === 'mentor' && messages.length === 0) {
      bootstrapSession(user);
    }
  }, [user, currentView]);

  // Μετά από εγκατάλειψη ενεργής άσκησης (βλ. handleConfirmLeaveTask), ΔΕΝ καθαρίζουμε τη
  // συζήτηση — μένουμε στην ίδια. Μόλις ο μαθητής ξαναμπεί στο κεφάλαιο, ζητάμε μόνοι μας μια
  // καινούρια άσκηση (ίδιο μηχανισμό με "θέλω άλλη άσκηση") και προστίθεται σαν συνέχεια της
  // ίδιας συνομιλίας, όχι σαν νέο ξεκίνημα.
  useEffect(() => {
    if (user && currentView === 'mentor' && pendingFreshTaskOnReturn) {
      setPendingFreshTaskOnReturn(false);
      requestFreshTaskAfterAbandon();
    }
  }, [user, currentView, pendingFreshTaskOnReturn]);

  // Η "Η πρόοδός μου" ενότητα ζωντανεύει ξανά κάθε φορά που δείχνουμε την αρχική σελίδα —
  // ανεξάρτητα από το αν έχει ανοίξει ποτέ η συζήτηση. Χωρίς αυτό, το mastery_profile έμενε
  // παγωμένο στην τιμή της πρώτης φοράς που μπήκε στη συζήτηση (ή έλειπε εντελώς αν δεν είχε
  // μπει ποτέ), ακόμα κι αν ο μαθητής μόλις είχε ολοκληρώσει μια ενότητα.
  useEffect(() => {
    if (!user || (currentView !== 'landing' && currentView !== 'practice')) return;
    axios.get(`${API_BASE}/session/${user.id}/progress`)
      .then(res => {
        if (res.data.experience_level) setExperienceLevel(res.data.experience_level);
        if (res.data.mastery_profile) setMasteryProfile(res.data.mastery_profile);
        if (typeof res.data.practice_streak_current === 'number') setPracticeStreakCurrent(res.data.practice_streak_current);
        if (typeof res.data.practice_streak_goal === 'number') setPracticeStreakGoal(res.data.practice_streak_goal);
      })
      .catch(() => { /* σιωπηλή αποτυχία — δεν χαλάει η υπόλοιπη σελίδα */ });
  }, [user, currentView]);

  // Wake-up ping: μόλις εμφανιστεί το login, στέλνουμε ένα GET στο backend
  // ώστε το Render να ξυπνήσει πριν ο χρήστης πατήσει Εγγραφή/Σύνδεση
  useEffect(() => {
    if (!user) {
      axios.get(`${API_BASE}/`).catch(() => {});
    }
  }, []);

  const handleAuth = async () => {
    setAuthError('');
    const endpoint = isRegistering ? 'register' : 'login';
    const payload = {
      username: authForm.username.trim(),
      password: authForm.password,
    };

    if (!payload.username || !payload.password) {
      setAuthError('Συμπλήρωσε όνομα χρήστη και κωδικό.');
      return;
    }

    setAuthLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/${endpoint}`, payload);
      if (isRegistering) {
        setRegisterSuccessModal(true);
        setIsRegistering(false);
        setAuthForm({ username: '', password: '' });
        setShowPassword(false);
      } else {
        setUser(res.data);
        localStorage.setItem('python_user_data', JSON.stringify(res.data));
        setCurrentView('landing');
      }
    } catch (err) {
      const status = err.response?.status;
      if (status === 401) {
        setAuthError('Λάθος όνομα χρήστη ή κωδικός.');
      } else if (status === 400 && isRegistering) {
        setAuthError('Το όνομα χρήστη υπάρχει ήδη. Δοκίμασε διαφορετικό.');
      } else {
        setAuthError('Δεν απαντά ο server. Δοκίμασε ξανά σε λίγο.');
      }
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = () => {
    setUser(null);
    setCurrentView(null);
    setCourseCompleted(false);
    setShowEditor(false);
    setEditorEnabled(false);
    setTaskJustCompleted(false);
    setStartTime(null);
    setTaskActive(false);
    setHintStage(0);
    setLastActivityTime(null);
    localStorage.removeItem('python_user_data');
    setMessages([]);
  };

  const handleEnterMentor = () => {
    setCurrentView('mentor');
  };

  const handleEnterFreeCheck = () => {
    setFreeCheckCode('');
    setFreeCheckDescription('');
    setFreeCheckResponse(null);
    setFreeCheckError('');
    setCurrentView('free_check');
  };

  const handleFreeCheckSubmit = async () => {
    if (!user?.id || !freeCheckCode.trim() || freeCheckLoading) return;
    setFreeCheckLoading(true);
    setFreeCheckError('');
    setFreeCheckResponse(null);
    try {
      const res = await axios.post(`${API_BASE}/free_check/${user.id}`, {
        code: freeCheckCode,
        description: freeCheckDescription,
      });
      setFreeCheckResponse(res.data.mentor_response);
    } catch (err) {
      setFreeCheckError(err.response?.data?.detail || 'Κάτι πήγε στραβά κατά τον έλεγχο. Δοκίμασε ξανά.');
    } finally {
      setFreeCheckLoading(false);
    }
  };

  const handleGoHomeFromFreeCheck = () => {
    if (freeCheckCode.trim()) {
      setShowLeaveFreeCheckConfirm(true);
      return;
    }
    setCurrentView('landing');
  };

  const handleConfirmLeaveFreeCheck = () => {
    setShowLeaveFreeCheckConfirm(false);
    setFreeCheckCode('');
    setFreeCheckDescription('');
    setFreeCheckResponse(null);
    setFreeCheckError('');
    setCurrentView('landing');
  };

  const handleEnterPractice = () => {
    setPracticeSelectedLessonIds([]);
    setPracticeCurrentTask(null);
    setPracticeCode('');
    setPracticeResponse(null);
    setPracticeIsCorrect(null);
    setPracticeError('');
    setPracticeGoalInput('');
    setCurrentView('practice');
  };

  const handleTogglePracticeLesson = (lessonId) => {
    setPracticeSelectedLessonIds(prev =>
      prev.includes(lessonId) ? prev.filter(id => id !== lessonId) : [...prev, lessonId]
    );
  };

  const handleFetchPracticeTask = async () => {
    if (!user?.id || practiceSelectedLessonIds.length === 0 || practiceLoading) return;
    setPracticeLoading(true);
    setPracticeError('');
    setPracticeResponse(null);
    setPracticeIsCorrect(null);
    setPracticeCode('');
    try {
      const res = await axios.post(`${API_BASE}/practice/${user.id}/next_task`, {
        lesson_ids: practiceSelectedLessonIds,
      });
      setPracticeCurrentTask(res.data);
    } catch (err) {
      setPracticeError(err.response?.data?.detail || 'Δεν βρέθηκε άσκηση. Δοκίμασε ξανά.');
      setPracticeCurrentTask(null);
    } finally {
      setPracticeLoading(false);
    }
  };

  const handlePracticeSubmit = async () => {
    if (!user?.id || !practiceCode.trim() || !practiceCurrentTask || practiceLoading) return;
    setPracticeLoading(true);
    setPracticeError('');
    try {
      const res = await axios.post(`${API_BASE}/practice/${user.id}/submit`, {
        code: practiceCode,
        task: practiceCurrentTask.task,
        success_criteria: practiceCurrentTask.success_criteria,
        lesson_id: practiceCurrentTask.lesson_id,
      });
      setPracticeResponse(res.data.mentor_response);
      setPracticeIsCorrect(res.data.is_correct);
      setPracticeStreakCurrent(res.data.practice_streak_current);
      setPracticeStreakGoal(res.data.practice_streak_goal);
    } catch (err) {
      setPracticeError(err.response?.data?.detail || 'Κάτι πήγε στραβά κατά τον έλεγχο. Δοκίμασε ξανά.');
    } finally {
      setPracticeLoading(false);
    }
  };

  const handleSetPracticeGoal = async () => {
    const goal = parseInt(practiceGoalInput, 10);
    if (!user?.id || isNaN(goal) || goal < 0) return;
    try {
      const res = await axios.post(`${API_BASE}/practice/${user.id}/set_goal`, { goal });
      setPracticeStreakGoal(res.data.practice_streak_goal);
      setPracticeGoalInput('');
    } catch (err) { /* ignore */ }
  };

  const handleGoHomeFromPractice = () => {
    if (practiceCurrentTask) {
      setShowLeavePracticeConfirm(true);
      return;
    }
    setCurrentView('landing');
  };

  const handleConfirmLeavePractice = () => {
    setShowLeavePracticeConfirm(false);
    setPracticeCurrentTask(null);
    setPracticeCode('');
    setPracticeResponse(null);
    setPracticeIsCorrect(null);
    setPracticeError('');
    setCurrentView('landing');
  };

  const handleGoHomeClick = () => {
    if (taskActive) {
      setShowLeaveTaskConfirm(true);
      return;
    }
    setCurrentView('landing');
  };

  const handleConfirmLeaveTask = async () => {
    setShowLeaveTaskConfirm(false);
    if (user?.id) {
      try {
        await axios.post(`${API_BASE}/session/${user.id}/abandon_task`);
      } catch (err) {
        // Δεν μπλοκάρουμε την πλοήγηση αν αποτύχει το καθάρισμα στο backend — στη χειρότερη
        // περίπτωση η άσκηση θα ξαναχρησιμοποιηθεί την επόμενη φορά, όπως συμβαίνει ήδη σήμερα.
      }
    }
    setShowEditor(false);
    setEditorEnabled(false);
    setTaskJustCompleted(false);
    setStartTime(null);
    setTaskActive(false);
    setHintStage(0);
    setLastActivityTime(null);
    setPendingFreshTaskOnReturn(true);
    setCurrentView('landing');
  };

  // Καλείται μόνο του (χωρίς ορατό μήνυμα μαθητή) όταν ο μαθητής ξαναμπαίνει στο κεφάλαιο μετά
  // από εγκατάλειψη άσκησης — ζητά νέα παραλλαγή στο ΙΔΙΟ κεφάλαιο (ίδιος μηχανισμός με "θέλω
  // άλλη άσκηση") και προσθέτει μόνο την απάντηση του Mentor στη συζήτηση, χωρίς να τη σβήσει.
  const requestFreshTaskAfterAbandon = async () => {
    if (!user?.id) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/chat/${user.id}`, {
        message: "",
        code: "",
        time_spent: 0,
        task_started: false,
        event_type: 'same_chapter_practice',
        session_id: currentSessionId,
      });
      setMessages(prev => [...prev, { role: 'ai', content: res.data.mentor_response }]);
    } catch (err) {
      // Αν αποτύχει, ο μαθητής μπορεί απλά να ζητήσει άσκηση κανονικά μέσω chat.
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  };

  const handleStartTask = () => {
    const now = Date.now();
    setShowEditor(true);
    setEditorEnabled(true);
    setTaskJustCompleted(false);
    setStartTime(now);
    setTaskActive(true);
    setHintStage(0);
    setLastActivityTime(now);
    const resetComment = '# Γράψε τον κώδικά σου εδώ...';
    setCode(resetComment);
    // Καθαρίζουμε τον editor χωρίς να επηρεαστεί η θέση cursor (uncontrolled mode)
    if (monacoEditorRef.current) {
      monacoEditorRef.current.setValue(resetComment);
    }
  };

  const requestNoSubmissionHint = async (stage) => {
    // Χρησιμοποιούμε loadingRef (όχι state) γιατί το setTimeout callback
    // κλείνει πάνω σε stale τιμή — το ref ενημερώνεται συγχρονικά.
    if (!user?.id || !taskActive || loadingRef.current) return;

    loadingRef.current = true;
    setLoading(true);
    const elapsedSeconds = startTime ? Math.max(0, (Date.now() - startTime) / 1000) : 0;

    try {
      const res = await axios.post(`${API_BASE}/chat/${user.id}`, {
        message: '__NO_SUBMISSION_TIMEOUT__',
        code: '',
        time_spent: elapsedSeconds,
        is_task_attempt: false,
        task_started: true,
        event_type: 'no_submission_timeout',
        session_id: currentSessionId,
      });

      setMessages(prev => [...prev, { role: 'ai', content: res.data.mentor_response }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'ai', content: 'Δεν μπόρεσα να στείλω αυτόματο hint αυτή τη στιγμή.' }]);
    } finally {
      loadingRef.current = false;
      setLoading(false);
      setHintStage(stage + 1);
      setLastActivityTime(Date.now()); // επαναφορά χρόνου για το επόμενο hint
    }
  };

  // Multi-stage timeout: πυροδοτεί σειριακά hints με αυξανόμενο delay
  useEffect(() => {
    if (!taskActive || !lastActivityTime || hintStage >= HINT_DELAYS.length) return;

    const delay = HINT_DELAYS[hintStage];
    const elapsed = Date.now() - lastActivityTime;
    const remaining = Math.max(0, delay - elapsed);

    const timerId = window.setTimeout(() => {
      requestNoSubmissionHint(hintStage);
    }, remaining);

    return () => window.clearTimeout(timerId);
  }, [taskActive, hintStage, lastActivityTime]);

  const sendChatMessage = async (overrideMessage = null) => {
    const textToSend = overrideMessage || chatInput;
    if (!textToSend.trim()) return;

    const msg = { role: 'human', content: textToSend };
    setMessages(prev => [...prev, msg]);
    loadingRef.current = true;
    setLoading(true);
    if (!overrideMessage) setChatInput('');
    // Επαναφορά timer υπόδειξης όταν ο μαθητής στέλνει μήνυμα chat
    // (αποτρέπει αυτόματα hints να εμφανίζονται ενώ ο μαθητής κάνει ερωτήσεις)
    if (taskActive) setLastActivityTime(Date.now());

    try {
      const res = await axios.post(`${API_BASE}/chat/${user.id}`, {
        message: textToSend,
        code: "",
        time_spent: 0,
        task_started: taskActive,
        session_id: currentSessionId,
      });
      setMessages(prev => [...prev, { role: 'ai', content: res.data.mentor_response }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'ai', content: "Πρόβλημα σύνδεσης με το AI." }]);
    } finally { loadingRef.current = false; setLoading(false); }
  };

  const handleRunCode = async () => {
    loadingRef.current = true;
    setLoading(true);
    setHintStage(HINT_DELAYS.length); // παύση timer κατά τη διάρκεια της υποβολής
    const timeSpent = startTime ? (Date.now() - startTime) / 1000 : 0;
    // Χρησιμοποιούμε το ref για αξιόπιστη ανάγνωση (uncontrolled editor)
    const codeToSubmit = monacoEditorRef.current ? monacoEditorRef.current.getValue() : (typeof code === 'string' ? code : '');
    const submissionMessage = codeToSubmit.trim()
      ? `Υποβολή κώδικα:\n\`\`\`python\n${codeToSubmit}\n\`\`\``
      : 'Υποβολή κώδικα';

    setMessages(prev => [...prev, { role: 'human', content: submissionMessage }]);

    try {
      const res = await axios.post(`${API_BASE}/chat/${user.id}`, {
        message: "CODE_SUBMISSION",
        code: codeToSubmit,
        time_spent: timeSpent,
        is_task_attempt: true,
        task_started: true,
        event_type: 'code_submission',
        session_id: currentSessionId,
      });

      const mentorResponse = res.data?.mentor_response || "Δεν έλαβα απάντηση από τον Mentor.";
      const isCorrect = Boolean(res.data?.is_correct);
      const responseComplete = Boolean(res.data?.course_completed);
      if (res.data?.experience_level) setExperienceLevel(res.data.experience_level);

      setMessages(prev => [...prev, { role: 'ai', content: mentorResponse }]);

      if (responseComplete) {
        setCourseCompleted(true);
      }

      if (isCorrect || responseComplete) {
        // Σωστή λύση → κλείδωμα editor μέχρι το κουμπί της επόμενης άσκησης
        setStartTime(null);
        setTaskActive(false);
        setEditorEnabled(false);
        setTaskJustCompleted(true);
        setHintStage(0);
        setLastActivityTime(null);
      } else {
        // Λανθασμένη υποβολή → επαναφορά timer (αρχίζει ξανά από hint 1)
        const now = Date.now();
        setHintStage(0);
        setLastActivityTime(now);
      }
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { role: 'ai', content: "Δεν μπόρεσα να ελέγξω τον κώδικα αυτή τη στιγμή. Δοκίμασε ξανά." }]);
    }
    finally { loadingRef.current = false; setLoading(false); }
  };

  if (!user) {
    return (
      <div style={{ position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', background: '#121212', color: 'white', padding: '16px', overflowY: 'auto' }}>

        {/* ── Modal επιτυχούς εγγραφής ── */}
        {registerSuccessModal && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 999 }}>
            <div style={{ background: '#1e1e1e', border: '1px solid #4caf50', borderRadius: '16px', padding: '40px 48px', textAlign: 'center', maxWidth: '420px', boxShadow: '0 8px 32px rgba(0,0,0,0.7)' }}>
              <div style={{ fontSize: '3rem', marginBottom: '14px' }}></div>
              <h3 style={{ color: '#4caf50', marginBottom: '12px', fontSize: '1.3rem' }}>Η εγγραφή έγινε!</h3>
              <p style={{ color: '#ccc', fontSize: '1.05rem', marginBottom: '28px' }}>Ο λογαριασμός σου δημιουργήθηκε επιτυχώς. Μπορείς τώρα να συνδεθείς.</p>
              <button
                onClick={() => setRegisterSuccessModal(false)}
                style={{ padding: '12px 36px', borderRadius: '8px', border: 'none', background: '#4caf50', color: 'white', fontWeight: 'bold', cursor: 'pointer', fontSize: '1.1rem' }}
              >
                Σύνδεση
              </button>
            </div>
          </div>
        )}

        <div style={{ background: '#1e1e1e', padding: 'clamp(24px, 5vw, 52px) clamp(20px, 5vw, 56px)', borderRadius: '24px', width: '100%', maxWidth: '460px', textAlign: 'center', boxShadow: '0 10px 48px rgba(0,0,0,0.7)', boxSizing: 'border-box' }}>
          <Code2 size={60} color="#4caf50" style={{ marginBottom: '18px' }} />
          <h2 style={{ marginBottom: '8px', fontSize: '1.8rem' }}>AI Python Tutor</h2>
          <p style={{ color: '#888', fontSize: '1rem', marginBottom: '28px' }}>
            {isRegistering ? 'Δημιούργησε λογαριασμό για να ξεκινήσεις' : 'Συνδέσου για να γνωρίσεις τον κόσμο της Python.'}
          </p>

          {/* Username */}
          <input
            style={{ width: '100%', padding: '14px 16px', marginBottom: '14px', borderRadius: '10px', border: '1px solid #444', background: '#2a2a2a', color: 'white', boxSizing: 'border-box', fontSize: '1.05rem' }}
            placeholder="Όνομα χρήστη"
            value={authForm.username}
            onChange={e => setAuthForm({...authForm, username: e.target.value})}
            onKeyDown={e => e.key === 'Enter' && handleAuth()}
          />

          {/* Password με toggle ορατότητας */}
          <div style={{ position: 'relative', marginBottom: '24px' }}>
            <input
              type={showPassword ? 'text' : 'password'}
              style={{ width: '100%', padding: '14px 16px', paddingRight: '50px', borderRadius: '10px', border: '1px solid #444', background: '#2a2a2a', color: 'white', boxSizing: 'border-box', fontSize: '1.05rem' }}
              placeholder="Κωδικός"
              value={authForm.password}
              onChange={e => setAuthForm({...authForm, password: e.target.value})}
              onKeyDown={e => e.key === 'Enter' && handleAuth()}
            />
            <button
              type="button"
              onClick={() => setShowPassword(p => !p)}
              style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', background: 'transparent', border: 'none', cursor: 'pointer', color: '#888', display: 'flex', alignItems: 'center', padding: '4px' }}
              title={showPassword ? 'Απόκρυψη κωδικού' : 'Εμφάνιση κωδικού'}
            >
              {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
          </div>

          {authError && <p style={{ color: '#ff5f56', fontSize: '0.95rem', marginBottom: '16px' }}>{authError}</p>}

          <button
            onClick={handleAuth}
            disabled={authLoading}
            style={{ width: '100%', padding: '14px', borderRadius: '10px', border: 'none', background: authLoading ? '#388e3c' : '#4caf50', color: 'white', fontWeight: 'bold', cursor: authLoading ? 'wait' : 'pointer', fontSize: '1.1rem', transition: 'background 0.2s' }}
          >
            {authLoading ? 'Σύνδεση...' : (isRegistering ? 'Εγγραφή' : 'Είσοδος')}
          </button>
          <p
            onClick={() => { setIsRegistering(!isRegistering); setAuthError(''); setShowPassword(false); }}
            style={{ marginTop: '22px', color: '#4caf50', cursor: 'pointer', fontSize: '1rem' }}
          >
            {isRegistering ? 'Επιστροφή στο Login' : 'Δημιουργία λογαριασμού'}
          </p>
        </div>
      </div>
    );
  }

  if (currentView === 'landing') {
    const hour = new Date().getHours();
    const greeting = hour < 12 ? 'Καλημέρα' : 'Καλησπέρα';

    return (
      <div style={{ position: 'fixed', inset: 0, background: '#121212', color: 'white', display: 'flex', flexDirection: 'column', fontFamily: 'sans-serif', overflowY: 'auto' }}>
        {/* Header */}
        <div style={{ padding: '20px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #2a2a2a', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Code2 size={22} color="#4caf50" />
            <strong style={{ fontSize: '1.05rem' }}>AI Python Tutor</strong>
          </div>
          <button onClick={handleLogout} style={{ background: 'transparent', border: 'none', color: '#888', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.9rem' }}>
            <LogOut size={17} /> Αποσύνδεση
          </button>
        </div>

        {/* Main — flex-start (ΟΧΙ center) ώστε το greeting+κάρτες να μένουν σε σταθερή θέση
            ανεξάρτητα από το αν φόρτωσε ή όχι το mastery_profile· αλλιώς το centering μετατοπίζει
            ΟΛΟ το block κάθε φορά που αλλάζει το συνολικό του ύψος. */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-start', padding: '64px 20px' }}>
          <h1 style={{ fontSize: 'clamp(1.5rem, 4vw, 2.2rem)', marginBottom: '8px', textAlign: 'center', fontWeight: 700 }}>
            {greeting}, {user.username}!
          </h1>
          <p style={{ color: '#888', fontSize: '1.05rem', marginBottom: '52px', textAlign: 'center' }}>
            Τι θα ήθελες να κάνεις σήμερα;
          </p>

          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', justifyContent: 'center', maxWidth: '860px', width: '100%' }}>

            {/* Κάρτα 1: Μαθήματα — ενεργή */}
            <div
              onClick={handleEnterMentor}
              style={{ background: '#1e1e1e', border: '2px solid #4caf50', borderRadius: '20px', padding: '36px 24px', width: '240px', cursor: 'pointer', textAlign: 'center', boxShadow: '0 4px 20px rgba(76,175,80,0.12)', transition: 'transform 0.15s, box-shadow 0.15s', boxSizing: 'border-box' }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-5px)'; e.currentTarget.style.boxShadow = '0 10px 32px rgba(76,175,80,0.28)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 20px rgba(76,175,80,0.12)'; }}
            >
              <BookOpen size={52} color="#4caf50" style={{ marginBottom: '18px' }} />
              <h3 style={{ margin: '0 0 10px', fontSize: '1.15rem' }}>Μαθήματα Python</h3>
              <p style={{ color: '#888', fontSize: '0.88rem', margin: 0, lineHeight: '1.55' }}>
                Δομημένα μαθήματα με τον προσωπικό σου μέντορα
              </p>
            </div>

            {/* Κάρτα 2: Εξάσκηση — Button 2, ελεύθερη πρακτική με streak */}
            <div
              onClick={handleEnterPractice}
              style={{ background: '#1e1e1e', border: '2px solid #4caf50', borderRadius: '20px', padding: '36px 24px', width: '240px', cursor: 'pointer', textAlign: 'center', boxShadow: '0 4px 20px rgba(76,175,80,0.12)', transition: 'transform 0.15s, box-shadow 0.15s', boxSizing: 'border-box' }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-5px)'; e.currentTarget.style.boxShadow = '0 10px 32px rgba(76,175,80,0.28)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 20px rgba(76,175,80,0.12)'; }}
            >
              <Zap size={52} color="#4caf50" style={{ marginBottom: '18px' }} />
              <h3 style={{ margin: '0 0 10px', fontSize: '1.15rem' }}>Εξάσκηση</h3>
              <p style={{ color: '#888', fontSize: '0.88rem', margin: 0, lineHeight: '1.55' }}>
                Προσαρμοστικές ασκήσεις βάσει των αναγκών σου
              </p>
            </div>

            {/* Κάρτα 3: Αξιολόγηση κώδικα — Button 3, ελεύθερος έλεγχος κώδικα */}
            <div
              onClick={handleEnterFreeCheck}
              style={{ background: '#1e1e1e', border: '2px solid #4caf50', borderRadius: '20px', padding: '36px 24px', width: '240px', cursor: 'pointer', textAlign: 'center', boxShadow: '0 4px 20px rgba(76,175,80,0.12)', transition: 'transform 0.15s, box-shadow 0.15s', boxSizing: 'border-box' }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-5px)'; e.currentTarget.style.boxShadow = '0 10px 32px rgba(76,175,80,0.28)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 20px rgba(76,175,80,0.12)'; }}
            >
              <FileCode size={52} color="#4caf50" style={{ marginBottom: '18px' }} />
              <h3 style={{ margin: '0 0 10px', fontSize: '1.15rem' }}>Αξιολόγηση Κώδικα</h3>
              <p style={{ color: '#888', fontSize: '0.88rem', margin: 0, lineHeight: '1.55' }}>
                Ανέβασε δικό σου κώδικα για ανάλυση
              </p>
            </div>
          </div>

          {/* Open Learner Model — Η πρόοδός μου (Bull & Kay, 2010) — κουμπί αντί για μόνιμα
              ορατή ενότητα, ώστε να μη μετατοπίζεται το layout ανάλογα με το αν έχει φορτώσει. */}
          {masteryProfile.length > 0 && (
            <button
              onClick={() => setShowProgressModal(true)}
              style={{ marginTop: '40px', background: '#1e1e1e', border: '2px solid #333', borderRadius: '14px', padding: '14px 28px', color: '#ccc', cursor: 'pointer', fontSize: '0.95rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '10px', transition: 'border-color 0.15s, transform 0.15s' }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = '#4caf50'; e.currentTarget.style.transform = 'translateY(-2px)'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = '#333'; e.currentTarget.style.transform = 'translateY(0)'; }}
            >
              Η πρόοδός μου
            </button>
          )}
        </div>

        {/* ── Progress Modal ──────────────────────────────────────────────── */}
        {showProgressModal && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
            onClick={() => setShowProgressModal(false)}>
            <div style={{ background: '#252526', borderRadius: '16px', width: '100%', maxWidth: '560px', maxHeight: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', border: '1px solid #3a3a3a' }}
              onClick={e => e.stopPropagation()}>
              <div style={{ padding: '16px 20px', background: '#2d2d2d', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
                <strong style={{ color: '#aaa', fontSize: '0.95rem' }}>Η πρόοδός μου</strong>
                <button onClick={() => setShowProgressModal(false)} style={{ background: 'transparent', border: 'none', color: '#888', cursor: 'pointer', fontSize: '1.3rem', lineHeight: 1 }}>✕</button>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '40px 24px 24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {masteryProfile.map(({ id, title, mastery, struggled, cohort_pct }) => (
                  <div key={id}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '5px' }}>
                      <span style={{ fontSize: '0.9rem', color: mastery === 0 ? '#444' : '#ccc', display: 'flex', alignItems: 'center', gap: '7px' }}>
                        {id}. {title}
                        {struggled && (
                          <span
                            style={{ display: 'inline-flex', cursor: 'pointer' }}
                            onMouseEnter={(e) => {
                              const rect = e.currentTarget.getBoundingClientRect();
                              const TOOLTIP_WIDTH = 220;
                              const MARGIN = 10;
                              let left = rect.left + rect.width / 2 - TOOLTIP_WIDTH / 2;
                              left = Math.max(MARGIN, Math.min(left, window.innerWidth - TOOLTIP_WIDTH - MARGIN));
                              // Πάνω από το εικονίδιο εκτός αν δεν χωράει (κοντά στην κορυφή της οθόνης) —
                              // τότε κάτω. Portal στο document.body: ΔΕΝ κόβεται από κανένα container.
                              const placement = rect.top < 90 ? 'below' : 'above';
                              const top = placement === 'above' ? rect.top - 8 : rect.bottom + 8;
                              setStruggleTooltip({ id, top, left, placement });
                            }}
                            onMouseLeave={() => setStruggleTooltip(null)}
                          >
                            <TriangleAlert size={15} color="#f9a825" />
                            {struggleTooltip && struggleTooltip.id === id && createPortal(
                              <div style={{
                                position: 'fixed', top: struggleTooltip.top, left: struggleTooltip.left,
                                transform: struggleTooltip.placement === 'above' ? 'translateY(-100%)' : 'none',
                                background: '#1a1a1a', border: '1px solid #f9a825', borderRadius: '8px',
                                padding: '8px 12px', fontSize: '0.75rem', color: '#eee', whiteSpace: 'normal',
                                width: '220px', textAlign: 'center', lineHeight: '1.4', zIndex: 1000,
                                boxShadow: '0 4px 12px rgba(0,0,0,0.4)', pointerEvents: 'none',
                              }}>
                                Σε αυτό το κεφάλαιο δυσκολεύτηκες — δώσε μεγαλύτερη προσοχή ή κάνε λίγη εξάσκηση.
                              </div>,
                              document.body
                            )}
                          </span>
                        )}
                      </span>
                      <span style={{ fontSize: '0.82rem', color: mastery === 100 ? '#4caf50' : mastery === 0 ? '#444' : '#f9a825', fontWeight: 600 }}>
                        {mastery}%
                      </span>
                    </div>
                    <div style={{ background: '#2a2a2a', borderRadius: '6px', height: '7px', overflow: 'hidden' }}>
                      <div style={{
                        width: `${mastery}%`,
                        height: '100%',
                        borderRadius: '6px',
                        background: mastery === 100 ? '#4caf50' : mastery >= 75 ? '#66bb6a' : mastery >= 50 ? '#f9a825' : mastery > 0 ? '#ef5350' : 'transparent',
                        transition: 'width 0.5s ease',
                      }} />
                    </div>
                    {cohort_pct != null && (
                      <div style={{ fontSize: '0.74rem', color: '#666', marginTop: '5px' }}>
                        {cohort_pct}% των χρηστών έχουν φτάσει μέχρι εδώ
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (currentView === 'free_check') {
    const codeTooLong = freeCheckCode.length > FREE_CHECK_MAX_CHARS;

    return (
      <div style={{ position: 'fixed', inset: 0, background: '#121212', color: 'white', display: 'flex', flexDirection: 'column', fontFamily: 'sans-serif', overflowY: 'auto' }}>
        <div style={{ padding: '20px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #2a2a2a', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileCode size={22} color="#4caf50" />
            <strong style={{ fontSize: '1.05rem' }}>Αξιολόγηση Κώδικα</strong>
          </div>
          <button onClick={handleGoHomeFromFreeCheck} style={{ background: 'transparent', border: '1px solid #444', borderRadius: '8px', color: '#888', cursor: 'pointer', padding: '6px 12px', fontSize: '0.82rem', whiteSpace: 'nowrap' }}>
            Αρχική
          </button>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '32px 20px', gap: '18px' }}>
          <div style={{ width: '100%', maxWidth: '720px' }}>
            <p style={{ color: '#888', fontSize: '0.9rem', margin: '0 0 24px', textAlign: 'center' }}>
              Δοκίμασε ελεύθερα τον δικό σου κώδικα — δεν επηρεάζει την πρόοδό σου στα μαθήματα.
            </p>

            <label style={{ display: 'block', color: '#ccc', fontSize: '0.85rem', marginBottom: '6px' }}>
              Τι θέλεις να κάνει ο κώδικάς σου; (προαιρετικό, αλλά βοηθάει την ανάλυση)
            </label>
            <textarea
              value={freeCheckDescription}
              onChange={e => setFreeCheckDescription(e.target.value)}
              placeholder="π.χ. 'θέλω να υπολογίσω το άθροισμα μιας λίστας αριθμών'"
              rows={2}
              style={{ width: '100%', boxSizing: 'border-box', background: '#1e1e1e', border: '1px solid #333', borderRadius: '10px', color: 'white', padding: '10px 12px', fontSize: '0.9rem', fontFamily: 'sans-serif', resize: 'vertical', marginBottom: '16px' }}
            />

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
              <label style={{ color: '#ccc', fontSize: '0.85rem' }}>Κώδικας</label>
              <span style={{ fontSize: '0.78rem', color: codeTooLong ? '#ef5350' : '#666' }}>
                {freeCheckCode.length} / {FREE_CHECK_MAX_CHARS}
              </span>
            </div>
            <div style={{ border: '1px solid #333', borderRadius: '10px', overflow: 'hidden', height: '260px' }}>
              <Editor
                height="100%"
                theme="vs-dark"
                defaultLanguage="python"
                defaultValue=""
                onChange={(value) => setFreeCheckCode(value ?? '')}
                options={{ fontSize: 15, quickSuggestions: false, suggestOnTriggerCharacters: false, acceptSuggestionOnEnter: 'off' }}
              />
            </div>

            <button
              onClick={handleFreeCheckSubmit}
              disabled={!freeCheckCode.trim() || freeCheckLoading || codeTooLong}
              style={{
                marginTop: '18px', width: '100%', padding: '13px', borderRadius: '10px', border: 'none',
                background: (!freeCheckCode.trim() || freeCheckLoading || codeTooLong) ? '#2a2a2a' : '#4caf50',
                color: (!freeCheckCode.trim() || freeCheckLoading || codeTooLong) ? '#666' : '#0d1f0f',
                fontWeight: 700, fontSize: '0.95rem', cursor: (!freeCheckCode.trim() || freeCheckLoading || codeTooLong) ? 'not-allowed' : 'pointer',
              }}
            >
              {freeCheckLoading ? 'Έλεγχος...' : 'Έλεγχος'}
            </button>

            {freeCheckError && (
              <div style={{ marginTop: '18px', background: '#2a1616', border: '1px solid #5c2b2b', borderRadius: '10px', padding: '14px 16px', color: '#ef9a9a', fontSize: '0.9rem' }}>
                {freeCheckError}
              </div>
            )}

            {freeCheckResponse && (
              <div style={{ marginTop: '18px', background: '#1e1e1e', border: '1px solid #333', borderRadius: '10px', padding: '16px 18px', color: '#ddd', fontSize: '0.92rem', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
                {freeCheckResponse}
              </div>
            )}
          </div>
        </div>

        {showLeaveFreeCheckConfirm && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
            onClick={() => setShowLeaveFreeCheckConfirm(false)}>
            <div style={{ background: '#252526', borderRadius: '16px', width: '100%', maxWidth: '420px', border: '1px solid #3a3a3a', padding: '24px' }}
              onClick={e => e.stopPropagation()}>
              <strong style={{ color: '#eee', fontSize: '1rem', display: 'block', marginBottom: '10px' }}>Έχεις κώδικα σε εξέλιξη</strong>
              <p style={{ color: '#aaa', fontSize: '0.9rem', lineHeight: '1.5', margin: '0 0 22px' }}>
                Αν πας στην αρχική σελίδα, ο κώδικας που έγραψες θα χαθεί. Θέλεις να συνεχίσεις;
              </p>
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setShowLeaveFreeCheckConfirm(false)}
                  style={{ background: 'transparent', border: '1px solid #444', borderRadius: '8px', color: '#ccc', cursor: 'pointer', padding: '8px 16px', fontSize: '0.88rem' }}
                >
                  Παραμονή εδώ
                </button>
                <button
                  onClick={handleConfirmLeaveFreeCheck}
                  style={{ background: '#c0392b', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', padding: '8px 16px', fontSize: '0.88rem', fontWeight: 600 }}
                >
                  Ναι, πήγαινε στην αρχική
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (currentView === 'practice') {
    const completedLessons = masteryProfile.filter(l => l.mastery === 100);
    const goalReached = practiceStreakGoal > 0 && practiceStreakCurrent >= practiceStreakGoal;

    return (
      <div style={{ position: 'fixed', inset: 0, background: '#121212', color: 'white', display: 'flex', flexDirection: 'column', fontFamily: 'sans-serif' }}>
        <div style={{ padding: '20px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #2a2a2a', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Zap size={22} color="#4caf50" />
            <strong style={{ fontSize: '1.05rem' }}>Εξάσκηση</strong>
          </div>
          <button onClick={handleGoHomeFromPractice} style={{ background: 'transparent', border: '1px solid #444', borderRadius: '8px', color: '#888', cursor: 'pointer', padding: '6px 12px', fontSize: '0.82rem', whiteSpace: 'nowrap' }}>
            Αρχική
          </button>
        </div>

        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* Sidebar: πολλαπλή επιλογή ολοκληρωμένων κεφαλαίων */}
          <div style={{ width: '220px', flexShrink: 0, borderRight: '1px solid #2a2a2a', padding: '20px 14px', overflowY: 'auto' }}>
            <div style={{ color: '#888', fontSize: '0.8rem', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Κεφάλαια</div>
            {completedLessons.length === 0 && (
              <p style={{ color: '#666', fontSize: '0.85rem', lineHeight: '1.5' }}>
                Ολοκλήρωσε τουλάχιστον ένα κεφάλαιο στα Μαθήματα για να ξεκλειδώσεις εξάσκηση εδώ.
              </p>
            )}
            {completedLessons.map(l => {
              const active = practiceSelectedLessonIds.includes(l.id);
              return (
                <button
                  key={l.id}
                  onClick={() => handleTogglePracticeLesson(l.id)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left', marginBottom: '8px',
                    padding: '10px 12px', borderRadius: '10px', cursor: 'pointer', fontSize: '0.85rem',
                    border: active ? '2px solid #4caf50' : '2px solid #2a2a2a',
                    background: active ? 'rgba(76,175,80,0.12)' : '#1a1a1a',
                    color: active ? '#eee' : '#aaa',
                  }}
                >
                  {l.title}
                </button>
              );
            })}
          </div>

          {/* Main */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '28px 32px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ width: '100%', maxWidth: '680px' }}>

              {/* Streak */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#1e1e1e', border: '1px solid #333', borderRadius: '12px', padding: '14px 18px', marginBottom: '20px' }}>
                <div>
                  <span style={{ fontSize: '1.1rem', fontWeight: 700, color: goalReached ? '#4caf50' : '#eee' }}>
                    Σερί: {practiceStreakCurrent}{practiceStreakGoal > 0 ? ` / ${practiceStreakGoal}` : ''}
                  </span>
                  {goalReached && <span style={{ marginLeft: '10px', color: '#4caf50', fontSize: '0.85rem' }}>Πέτυχες τον στόχο σου!</span>}
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number"
                    min="0"
                    value={practiceGoalInput}
                    onChange={e => setPracticeGoalInput(e.target.value)}
                    placeholder="Στόχος"
                    style={{ width: '70px', background: '#161616', border: '1px solid #333', borderRadius: '8px', color: 'white', padding: '7px 8px', fontSize: '0.85rem' }}
                  />
                  <button onClick={handleSetPracticeGoal} style={{ background: '#2a2a2a', border: 'none', borderRadius: '8px', color: '#ccc', padding: '7px 12px', fontSize: '0.8rem', cursor: 'pointer' }}>
                    Ορισμός
                  </button>
                </div>
              </div>

              {!practiceCurrentTask && (
                <button
                  onClick={handleFetchPracticeTask}
                  disabled={practiceSelectedLessonIds.length === 0 || practiceLoading}
                  style={{
                    width: '100%', padding: '13px', borderRadius: '10px', border: 'none', fontWeight: 700, fontSize: '0.95rem',
                    cursor: (practiceSelectedLessonIds.length === 0 || practiceLoading) ? 'not-allowed' : 'pointer',
                    background: (practiceSelectedLessonIds.length === 0 || practiceLoading) ? '#2a2a2a' : '#4caf50',
                    color: (practiceSelectedLessonIds.length === 0 || practiceLoading) ? '#666' : '#0d1f0f',
                  }}
                >
                  {practiceLoading ? 'Φόρτωση...' : 'Επόμενη άσκηση'}
                </button>
              )}

              {practiceCurrentTask && (
                <>
                  <div style={{ background: '#1e1e1e', border: '1px solid #333', borderRadius: '10px', padding: '16px 18px', marginBottom: '16px', fontSize: '0.92rem', lineHeight: '1.6' }}>
                    <div style={{ color: '#888', fontSize: '0.78rem', marginBottom: '6px' }}>
                      {practiceCurrentTask.lesson_title} · {practiceCurrentTask.difficulty === 'hard' ? 'Δύσκολο' : 'Εύκολο'}
                    </div>
                    {practiceCurrentTask.task}
                  </div>

                  <div style={{ border: '1px solid #333', borderRadius: '10px', overflow: 'hidden', height: '220px', marginBottom: '14px' }}>
                    <Editor
                      height="100%"
                      theme="vs-dark"
                      defaultLanguage="python"
                      value={practiceCode}
                      onChange={(value) => setPracticeCode(value ?? '')}
                      options={{ fontSize: 15, quickSuggestions: false, suggestOnTriggerCharacters: false, acceptSuggestionOnEnter: 'off' }}
                    />
                  </div>

                  <div style={{ display: 'flex', gap: '10px' }}>
                    <button
                      onClick={handlePracticeSubmit}
                      disabled={!practiceCode.trim() || practiceLoading}
                      style={{
                        flex: 1, padding: '13px', borderRadius: '10px', border: 'none', fontWeight: 700, fontSize: '0.95rem',
                        cursor: (!practiceCode.trim() || practiceLoading) ? 'not-allowed' : 'pointer',
                        background: (!practiceCode.trim() || practiceLoading) ? '#2a2a2a' : '#4caf50',
                        color: (!practiceCode.trim() || practiceLoading) ? '#666' : '#0d1f0f',
                      }}
                    >
                      {practiceLoading ? 'Έλεγχος...' : 'Έλεγχος'}
                    </button>
                    <button
                      onClick={handleFetchPracticeTask}
                      disabled={practiceLoading}
                      style={{ padding: '13px 18px', borderRadius: '10px', border: '1px solid #333', background: 'transparent', color: '#ccc', fontSize: '0.9rem', cursor: practiceLoading ? 'not-allowed' : 'pointer' }}
                    >
                      Νέα άσκηση
                    </button>
                  </div>
                </>
              )}

              {practiceError && (
                <div style={{ marginTop: '16px', background: '#2a1616', border: '1px solid #5c2b2b', borderRadius: '10px', padding: '14px 16px', color: '#ef9a9a', fontSize: '0.9rem' }}>
                  {practiceError}
                </div>
              )}

              {practiceResponse && (
                <div style={{
                  marginTop: '16px', borderRadius: '10px', padding: '16px 18px', fontSize: '0.92rem', lineHeight: '1.6', whiteSpace: 'pre-wrap',
                  background: practiceIsCorrect ? 'rgba(76,175,80,0.1)' : '#1e1e1e',
                  border: practiceIsCorrect ? '1px solid #4caf50' : '1px solid #333',
                  color: '#ddd',
                }}>
                  {practiceResponse}
                </div>
              )}
            </div>
          </div>
        </div>

        {showLeavePracticeConfirm && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
            onClick={() => setShowLeavePracticeConfirm(false)}>
            <div style={{ background: '#252526', borderRadius: '16px', width: '100%', maxWidth: '420px', border: '1px solid #3a3a3a', padding: '24px' }}
              onClick={e => e.stopPropagation()}>
              <strong style={{ color: '#eee', fontSize: '1rem', display: 'block', marginBottom: '10px' }}>Έχεις ενεργή άσκηση</strong>
              <p style={{ color: '#aaa', fontSize: '0.9rem', lineHeight: '1.5', margin: '0 0 22px' }}>
                Αν πας στην αρχική σελίδα, η άσκηση θα σταματήσει και θα πρέπει να πάρεις νέα. Θέλεις να συνεχίσεις;
              </p>
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setShowLeavePracticeConfirm(false)}
                  style={{ background: 'transparent', border: '1px solid #444', borderRadius: '8px', color: '#ccc', cursor: 'pointer', padding: '8px 16px', fontSize: '0.88rem' }}
                >
                  Παραμονή στην άσκηση
                </button>
                <button
                  onClick={handleConfirmLeavePractice}
                  style={{ background: '#c0392b', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', padding: '8px 16px', fontSize: '0.88rem', fontWeight: 600 }}
                >
                  Ναι, πήγαινε στην αρχική
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  const isMobile = windowWidth < 640;

  return (
    <div style={{ position: 'fixed', inset: 0, display: 'flex', backgroundColor: '#1e1e1e', color: 'white', fontFamily: 'sans-serif', overflow: 'hidden' }}>

      {/* ── History Modal ────────────────────────────────────────────────── */}
      {historyModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
          onClick={() => setHistoryModal(null)}>
          <div style={{ background: '#252526', borderRadius: '16px', width: '100%', maxWidth: '680px', maxHeight: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', border: '1px solid #3a3a3a' }}
            onClick={e => e.stopPropagation()}>
            <div style={{ padding: '16px 20px', background: '#2d2d2d', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
              <strong style={{ color: '#aaa', fontSize: '0.95rem' }}>Συνομιλία — {historyModal.title}</strong>
              <button onClick={() => setHistoryModal(null)} style={{ background: 'transparent', border: 'none', color: '#888', cursor: 'pointer', fontSize: '1.3rem', lineHeight: 1 }}>✕</button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {historyModal.messages.map((m, i) => (
                <div key={i} style={{ alignSelf: m.role === 'human' ? 'flex-end' : 'flex-start', maxWidth: '88%' }}>
                  <div style={{ background: m.role === 'human' ? '#007acc' : '#3e3e42', padding: '12px 16px', borderRadius: '12px', fontSize: '0.97rem', lineHeight: '1.55', wordBreak: 'break-word' }}>
                    <ReactMarkdown components={{ pre: ({node, ...props}) => <pre style={{ overflowX: 'auto', maxWidth: '100%', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: '0.5em 0' }} {...props} /> }}>{m.content}</ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Leave Active Task Confirm ────────────────────────────────────── */}
      {showLeaveTaskConfirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
          onClick={() => setShowLeaveTaskConfirm(false)}>
          <div style={{ background: '#252526', borderRadius: '16px', width: '100%', maxWidth: '420px', border: '1px solid #3a3a3a', padding: '24px' }}
            onClick={e => e.stopPropagation()}>
            <strong style={{ color: '#eee', fontSize: '1rem', display: 'block', marginBottom: '10px' }}>Έχεις ενεργή άσκηση</strong>
            <p style={{ color: '#aaa', fontSize: '0.9rem', lineHeight: '1.5', margin: '0 0 22px' }}>
              Αν πας στην αρχική σελίδα, η άσκηση θα σταματήσει και θα πρέπει να την ξεκινήσεις από την αρχή. Θέλεις να συνεχίσεις;
            </p>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowLeaveTaskConfirm(false)}
                style={{ background: 'transparent', border: '1px solid #444', borderRadius: '8px', color: '#ccc', cursor: 'pointer', padding: '8px 16px', fontSize: '0.88rem' }}
              >
                Παραμονή στην άσκηση
              </button>
              <button
                onClick={handleConfirmLeaveTask}
                style={{ background: '#c0392b', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', padding: '8px 16px', fontSize: '0.88rem', fontWeight: 600 }}
              >
                Ναι, πήγαινε στην αρχική
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── History Sidebar ──────────────────────────────────────────────── */}
      {showHistorySidebar && !isMobile && (
        <div style={{ width: '210px', flexShrink: 0, background: '#1a1a1a', borderRight: '1px solid #2a2a2a', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid #2a2a2a', fontSize: '0.85rem', color: '#888', fontWeight: 'bold', flexShrink: 0 }}>
            Παλιές συνομιλίες
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {historySessions.length === 0 ? (
              <p style={{ color: '#555', fontSize: '0.82rem', padding: '16px', margin: 0 }}>Δεν υπάρχουν αποθηκευμένες συνομιλίες ακόμα.</p>
            ) : (
              historySessions.map(s => (
                <div key={s.session_id}
                  onClick={() => openSessionModal(s)}
                  style={{ padding: '12px 14px', borderBottom: '1px solid #222', cursor: 'pointer', transition: 'background 0.15s' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#252525'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                  <div style={{ fontSize: '0.78rem', color: '#4caf50', marginBottom: '4px', fontWeight: 600 }}>
                    {formatSessionDate(s.created_at)}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: '#888', lineHeight: '1.4', overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                    {s.preview || '—'}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <div style={{ width: isMobile ? '100%' : '50%', minWidth: isMobile ? '0' : (showEditor ? '280px' : 'auto'), margin: (isMobile || showEditor) ? '0' : '0 auto', transition: 'width 0.5s ease', display: 'flex', flexDirection: 'column', background: '#252526', borderRight: showEditor ? '2px solid #333' : 'none', flexShrink: 0 }}>
        <div style={{ padding: '16px 20px', background: '#2d2d2d', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
            <strong style={{ whiteSpace: 'nowrap' }}>Μέντορας Python</strong>
            {courseCompleted && (
              <button
                onClick={() => { setCourseCompleted(false); setMessages([]); setCurrentView('landing'); }}
                style={{ background: '#4caf50', border: 'none', borderRadius: '8px', color: 'white', padding: '6px 14px', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 'bold', whiteSpace: 'nowrap' }}
              >
                Αρχική
              </button>
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {!courseCompleted && (
              <>
                <button
                  onClick={() => {
                    const next = !showHistorySidebar;
                    setShowHistorySidebar(next);
                    if (next) fetchHistorySessions();
                  }}
                  style={{ background: showHistorySidebar ? '#3a3a3a' : 'transparent', border: '1px solid #444', borderRadius: '8px', color: '#aaa', cursor: 'pointer', padding: '6px 12px', fontSize: '0.82rem', whiteSpace: 'nowrap' }}
                >
                  Ιστορικό
                </button>
                <button
                  onClick={handleGoHomeClick}
                  style={{ background: 'transparent', border: '1px solid #444', borderRadius: '8px', color: '#888', cursor: 'pointer', padding: '6px 12px', fontSize: '0.82rem', whiteSpace: 'nowrap' }}
                >
                  Αρχική
                </button>
              </>
            )}
            <button onClick={handleLogout} style={{ background: 'transparent', border: 'none', color: '#ff5f56', cursor: 'pointer' }}><LogOut size={20} /></button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {(() => {
            const lastStartIdx = messages.reduceRight(
              (acc, m, i) => (acc === -1 && hasStartButtonToken(m.content) ? i : acc), -1
            );
            return messages.map((m, i) => (
              <div key={i} style={{ alignSelf: m.role === 'human' ? 'flex-end' : 'flex-start', maxWidth: '90%' }}>
                <div style={{ background: m.role === 'human' ? '#007acc' : '#3e3e42', padding: '16px 18px', borderRadius: '15px', fontSize: '1.05rem', lineHeight: '1.6', wordBreak: 'break-word', overflowWrap: 'break-word', minWidth: 0 }}>
                  <ReactMarkdown components={{ pre: ({node, ...props}) => <pre style={{ overflowX: 'auto', maxWidth: '100%', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: '0.5em 0' }} {...props} /> }}>
                    {sanitizeMentorText(m.content)}
                  </ReactMarkdown>

                  {hasStartButtonToken(m.content) && i === lastStartIdx && !editorEnabled && (
                    <button
                      onClick={handleStartTask}
                      style={{ marginTop: '15px', padding: '10px 20px', background: '#4caf50', border: 'none', borderRadius: '8px', color: 'white', fontWeight: 'bold', cursor: 'pointer', fontSize: '0.95rem' }}
                    >
                      Πάτα εδώ για να ξεκινήσεις την άσκηση!
                    </button>
                  )}
                  {hasStartButtonToken(m.content) && i === lastStartIdx && editorEnabled && (
                    <span style={{ marginTop: '12px', display: 'inline-block', color: '#4caf50', fontSize: '0.85rem', fontStyle: 'italic' }}>
                      Η άσκηση ξεκίνησε — γράφε στον editor!
                    </span>
                  )}
                </div>
              </div>
            ));
          })()}
          {loading && <div style={{ color: '#888', fontStyle: 'italic' }}>Ο Mentor πληκτρολογεί...</div>}
          <div ref={chatEndRef} />
        </div>

        <div style={{ padding: '20px', background: '#2d2d2d', display: 'flex', gap: '10px' }}>
          <input
            style={{ flex: 1, padding: '14px 16px', borderRadius: '10px', border: 'none', background: '#3c3c3c', color: 'white', fontSize: '1.05rem' }}
            value={chatInput} onChange={e => setChatInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendChatMessage()}
            placeholder="Γράψε εδώ..."
            autoComplete="off"
          />
          <button onClick={() => sendChatMessage()} style={{ background: '#007acc', border: 'none', padding: '14px 16px', borderRadius: '10px' }}>
            <Send size={22} color="white" />
          </button>
        </div>
      </div>

      {showEditor && (
        <div style={{ flex: 1, minWidth: '300px', display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
          <div style={{ padding: '15px', background: '#1e1e1e', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Code2 size={18} color={editorEnabled ? '#007acc' : '#555'} />
              <span style={{ color: editorEnabled ? 'white' : '#666' }}>{getEditorFileName(user?.username)}</span>
              {!editorEnabled && (
                <span style={{ fontSize: '0.75rem', color: taskJustCompleted ? '#4caf50' : '#888', background: '#333', padding: '2px 8px', borderRadius: '4px' }}>
                  {taskJustCompleted ? 'Η άσκηση ολοκληρώθηκε! Περίμενε την επόμενη.' : 'Η άσκηση δεν έχει ξεκινήσει ακόμα.'}
                </span>
              )}
            </div>
            <button
              onClick={handleRunCode}
              disabled={!editorEnabled || loading}
              style={{
                background: (editorEnabled && !loading) ? '#4caf50' : '#3a3a3a',
                border: 'none',
                padding: '10px 20px',
                borderRadius: '8px',
                color: (editorEnabled && !loading) ? 'white' : '#666',
                fontWeight: 'bold',
                cursor: (editorEnabled && !loading) ? 'pointer' : 'not-allowed',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <Play size={18} /> Έλεγχος Κώδικα
            </button>
          </div>
          <div style={{ flex: 1, position: 'relative' }}>
            <Editor
              onMount={(editor) => { monacoEditorRef.current = editor; }}
              height="100%"
              theme="vs-dark"
              defaultLanguage="python"
              defaultValue="# Γράψε τον κώδικά σου εδώ..."
              onChange={(value) => editorEnabled && setCode(value ?? '')}
              options={{
                fontSize: 16,
                readOnly: !editorEnabled,
                cursorStyle: editorEnabled ? 'line' : 'block',
                renderLineHighlight: editorEnabled ? 'line' : 'none',
                quickSuggestions: false,
                suggestOnTriggerCharacters: false,
                acceptSuggestionOnEnter: 'off',
                wordBasedSuggestions: 'currentDocument',
              }}
            />
            {!editorEnabled && (
              <div style={{
                position: 'absolute', inset: 0,
                background: 'rgba(0,0,0,0.18)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                pointerEvents: 'none',
              }}>
                <span style={{ color: taskJustCompleted ? '#4caf50' : '#aaa', fontSize: '1rem', background: 'rgba(30,30,30,0.88)', padding: '12px 24px', borderRadius: '10px', border: '1px solid #3a3a3a' }}>
                  {taskJustCompleted ? 'Η άσκηση ολοκληρώθηκε! Περίμενε την επόμενη.' : 'Η άσκηση δεν έχει ξεκινήσει ακόμα.'}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}