import React, { useState, useEffect, useRef } from 'react';
import Editor from '@monaco-editor/react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { Send, Code2, Play, LogOut, Eye, EyeOff } from 'lucide-react';
import './App.css';

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

export default function App() {
  const [user, setUser] = useState(JSON.parse(localStorage.getItem('python_user_data')) || null);
  const [isRegistering, setIsRegistering] = useState(false);
  const [authForm, setAuthForm] = useState({ username: '', password: '' });
  const [authError, setAuthError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [registerSuccessModal, setRegisterSuccessModal] = useState(false);

  const [showEditor, setShowEditor] = useState(false);
  const [editorEnabled, setEditorEnabled] = useState(false);
  const [startTime, setStartTime] = useState(null);
  const [taskActive, setTaskActive] = useState(false);
  const [hintStage, setHintStage] = useState(0);        // 0=καμία υπόδειξη, 1/2/3=έχουν σταλεί
  const [lastActivityTime, setLastActivityTime] = useState(null); // τελευταία ενέργεια (start ή υποβολή)
  const HINT_DELAYS = [40000, 60000, 90000]; // ms μεταξύ υποδείξεων
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

  const bootstrapSession = async (targetUser) => {
    if (!targetUser?.id) return;
    try {
      const res = await axios.get(`${API_BASE}/session/${targetUser.id}/welcome`);
      setMessages([{ role: 'ai', content: res.data.message }]);
    } catch (err) {
      setMessages([{ role: 'ai', content: `Γεια σου ${targetUser.username}! Πριν συνεχίσουμε, έχεις κάποια απορία;` }]);
    }
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (user && messages.length === 0) {
      bootstrapSession(user);
    }
  }, [user]);

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

    const attemptAuth = async () => {
      const res = await axios.post(`${API_BASE}/${endpoint}`, payload);
      if (isRegistering) {
        setRegisterSuccessModal(true);
        setIsRegistering(false);
        setAuthForm({ username: '', password: '' });
        setShowPassword(false);
      } else {
        setUser(res.data);
        localStorage.setItem('python_user_data', JSON.stringify(res.data));
      }
    };

    try {
      await attemptAuth();
    } catch (err) {
      const status = err.response?.status;
      if (status === 401) {
        setAuthError('Λάθος όνομα χρήστη ή κωδικός.');
      } else if (status === 400 && isRegistering) {
        setAuthError('Το όνομα χρήστη υπάρχει ήδη. Δοκίμασε διαφορετικό.');
      } else {
        setAuthError(`Σφάλμα: ${err.message || '?'} | HTTP: ${err.response?.status || 'none'}`);
      }
    }
  };

  const handleLogout = () => {
    setUser(null);
    setShowEditor(false);
    setEditorEnabled(false);
    setStartTime(null);
    setTaskActive(false);
    setHintStage(0);
    setLastActivityTime(null);
    localStorage.removeItem('python_user_data');
    setMessages([]);
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
        event_type: 'no_submission_timeout'
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
        task_started: taskActive
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
        event_type: 'code_submission'
      });

      const mentorResponse = res.data?.mentor_response || "Δεν έλαβα απάντηση από τον Mentor.";
      const isCorrect = Boolean(res.data?.is_correct);
      const courseCompleted = Boolean(res.data?.course_completed);

      setMessages(prev => [...prev, { role: 'ai', content: mentorResponse }]);

      if (isCorrect || courseCompleted) {
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
      <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', background: '#121212', color: 'white' }}>

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

        <div style={{ background: '#1e1e1e', padding: '52px 56px', borderRadius: '24px', width: '460px', textAlign: 'center', boxShadow: '0 10px 48px rgba(0,0,0,0.7)' }}>
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
            style={{ width: '100%', padding: '14px', borderRadius: '10px', border: 'none', background: '#4caf50', color: 'white', fontWeight: 'bold', cursor: 'pointer', fontSize: '1.1rem' }}
          >
            {isRegistering ? 'Εγγραφή' : 'Είσοδος'}
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

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#1e1e1e', color: 'white', fontFamily: 'sans-serif' }}>
      
      <div style={{ width: showEditor ? '40%' : '60%', margin: showEditor ? '0' : '0 auto', transition: 'width 0.5s ease', display: 'flex', flexDirection: 'column', background: '#252526', borderRight: '2px solid #333' }}>
        <div style={{ padding: '20px', background: '#2d2d2d', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong>Μέντορας Python</strong>
          <button onClick={handleLogout} style={{ background: 'transparent', border: 'none', color: '#ff5f56', cursor: 'pointer' }}><LogOut size={20} /></button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {(() => {
            const lastStartIdx = messages.reduceRight(
              (acc, m, i) => (acc === -1 && hasStartButtonToken(m.content) ? i : acc), -1
            );
            return messages.map((m, i) => (
              <div key={i} style={{ alignSelf: m.role === 'human' ? 'flex-end' : 'flex-start', maxWidth: '90%' }}>
                <div style={{ background: m.role === 'human' ? '#007acc' : '#3e3e42', padding: '16px 18px', borderRadius: '15px', fontSize: '1.05rem', lineHeight: '1.6' }}>
                  <ReactMarkdown>
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
        <div style={{ width: '60%', display: 'flex', flexDirection: 'column' }}>
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
                wordBasedSuggestions: 'off',
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