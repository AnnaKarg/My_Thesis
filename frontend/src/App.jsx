import React, { useState, useEffect, useRef } from 'react';
import Editor from '@monaco-editor/react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { Send, Code2, Play, LogOut, Eye, EyeOff, BookOpen, Zap, FileCode } from 'lucide-react';
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
  const [isRegistering, setIsRegistering] = useState(false);
  const [authForm, setAuthForm] = useState({ username: '', password: '' });
  const [authError, setAuthError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [registerSuccessModal, setRegisterSuccessModal] = useState(false);

  const [authLoading, setAuthLoading] = useState(false);
  const [windowWidth, setWindowWidth] = useState(window.innerWidth);

  const [showEditor, setShowEditor] = useState(false);
  const [editorEnabled, setEditorEnabled] = useState(false);
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

  const bootstrapSession = async (targetUser) => {
    if (!targetUser?.id) return;
    try {
      const res = await axios.get(`${API_BASE}/session/${targetUser.id}/welcome`);
      setMessages([{ role: 'ai', content: res.data.message }]);
      if (res.data.session_id) setCurrentSessionId(res.data.session_id);
      if (res.data.experience_level) setExperienceLevel(res.data.experience_level);
      if (res.data.mastery_profile) setMasteryProfile(res.data.mastery_profile);
    } catch (err) {
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

  const handleStartTask = () => {
    const now = Date.now();
    setShowEditor(true);
    setEditorEnabled(true);
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
      setMessages(prev => [...prev, { role: 'ai', content: "⚠️ Πρόβλημα σύνδεσης με το AI." }]);
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
              <div style={{ fontSize: '3rem', marginBottom: '14px' }}>🎉</div>
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
            {authLoading ? '⏳ Σύνδεση...' : (isRegistering ? 'Εγγραφή' : 'Είσοδος')}
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

        {/* Main */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px 20px' }}>
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

            {/* Κάρτα 2: Εξάσκηση — σύντομα */}
            <div style={{ background: '#161616', border: '2px solid #2a2a2a', borderRadius: '20px', padding: '36px 24px', width: '240px', textAlign: 'center', opacity: 0.55, boxSizing: 'border-box', cursor: 'not-allowed' }}>
              <Zap size={52} color="#444" style={{ marginBottom: '18px' }} />
              <h3 style={{ margin: '0 0 10px', fontSize: '1.15rem', color: '#555' }}>Εξάσκηση</h3>
              <p style={{ color: '#444', fontSize: '0.88rem', margin: '0 0 16px', lineHeight: '1.55' }}>
                Προσαρμοστικές ασκήσεις βάσει των αναγκών σου
              </p>
              <span style={{ fontSize: '0.78rem', background: '#222', color: '#555', padding: '4px 12px', borderRadius: '20px' }}>Σύντομα...</span>
            </div>

            {/* Κάρτα 3: Αξιολόγηση κώδικα — σύντομα */}
            <div style={{ background: '#161616', border: '2px solid #2a2a2a', borderRadius: '20px', padding: '36px 24px', width: '240px', textAlign: 'center', opacity: 0.55, boxSizing: 'border-box', cursor: 'not-allowed' }}>
              <FileCode size={52} color="#444" style={{ marginBottom: '18px' }} />
              <h3 style={{ margin: '0 0 10px', fontSize: '1.15rem', color: '#555' }}>Αξιολόγηση Κώδικα</h3>
              <p style={{ color: '#444', fontSize: '0.88rem', margin: '0 0 16px', lineHeight: '1.55' }}>
                Ανέβασε δικό σου κώδικα για ανάλυση
              </p>
              <span style={{ fontSize: '0.78rem', background: '#222', color: '#555', padding: '4px 12px', borderRadius: '20px' }}>Σύντομα...</span>
            </div>
          </div>

          {/* Open Learner Model — Η πρόοδός μου (Bull & Kay, 2010) */}
          {masteryProfile.length > 0 && (
            <div style={{ marginTop: '52px', width: '100%', maxWidth: '560px' }}>
              <h2 style={{ fontSize: '1rem', color: '#aaa', fontWeight: 600, marginBottom: '18px', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                Η πρόοδός μου
              </h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                {masteryProfile.map(({ id, title, mastery }) => (
                  <div key={id}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                      <span style={{ fontSize: '0.88rem', color: mastery === 0 ? '#444' : '#ccc' }}>{id}. {title}</span>
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
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
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
              <strong style={{ color: '#aaa', fontSize: '0.95rem' }}>📚 Συνομιλία — {historyModal.title}</strong>
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

      <div style={{ width: isMobile ? '100%' : (showEditor ? '40%' : '60%'), minWidth: isMobile ? '0' : (showEditor ? '280px' : 'auto'), margin: (isMobile || showEditor) ? '0' : '0 auto', transition: 'width 0.5s ease', display: 'flex', flexDirection: 'column', background: '#252526', borderRight: showEditor ? '2px solid #333' : 'none', flexShrink: 0 }}>
        <div style={{ padding: '16px 20px', background: '#2d2d2d', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
            <strong style={{ whiteSpace: 'nowrap' }}>Μέντορας Python</strong>
            {courseCompleted && (
              <button
                onClick={() => { setCourseCompleted(false); setMessages([]); setCurrentView('landing'); }}
                style={{ background: '#4caf50', border: 'none', borderRadius: '8px', color: 'white', padding: '6px 14px', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 'bold', whiteSpace: 'nowrap' }}
              >
                🏠 Αρχική
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
                  📚 Ιστορικό
                </button>
                <button
                  onClick={() => setCurrentView('landing')}
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
                      🚀 Πάτα εδώ για να ξεκινήσεις την άσκηση!
                    </button>
                  )}
                  {hasStartButtonToken(m.content) && i === lastStartIdx && editorEnabled && (
                    <span style={{ marginTop: '12px', display: 'inline-block', color: '#4caf50', fontSize: '0.85rem', fontStyle: 'italic' }}>
                      ✅ Η άσκηση ξεκίνησε — γράφε στον editor!
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
                <span style={{ fontSize: '0.75rem', color: '#888', background: '#333', padding: '2px 8px', borderRadius: '4px' }}>
                  Η άσκηση δεν έχει ξεκινήσει ακόμα.
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
                <span style={{ color: '#aaa', fontSize: '1rem', background: 'rgba(30,30,30,0.88)', padding: '12px 24px', borderRadius: '10px', border: '1px solid #3a3a3a' }}>
                  Η άσκηση δεν έχει ξεκινήσει ακόμα.
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}