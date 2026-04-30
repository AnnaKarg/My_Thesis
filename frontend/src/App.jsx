import React, { useState, useEffect, useRef } from 'react';
import Editor from '@monaco-editor/react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import { Send, Code2, Play, LogOut } from 'lucide-react';
import './App.css';

export default function App() {
  const [user, setUser] = useState(JSON.parse(localStorage.getItem('python_user_data')) || null);
  const [isRegistering, setIsRegistering] = useState(false);
  const [authForm, setAuthForm] = useState({ username: '', password: '' });
  const [authError, setAuthError] = useState('');

  const [showEditor, setShowEditor] = useState(false);
  const [startTime, setStartTime] = useState(null);
  const [taskActive, setTaskActive] = useState(false);
  const [timeoutHintSent, setTimeoutHintSent] = useState(false);
  const [code, setCode] = useState('# Γράψε τον κώδικά σου εδώ...');
  const [messages, setMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);

  const startButtonToken = '[BUTTON:START_TASK]';
  const legacyStartButtonToken = '[BUTTON:CONTINUE_TASK]';

  const sanitizeMentorText = (text = '') =>
    text
      .replace(startButtonToken, '')
      .replace(legacyStartButtonToken, '')
      .replace('[ACTIVATE_EDITOR]', '')
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
      const res = await axios.get(`http://127.0.0.1:8000/session/${targetUser.id}/welcome`);
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

    try {
      const res = await axios.post(`http://127.0.0.1:8000/${endpoint}`, payload);
      if (isRegistering) {
        alert("Η εγγραφή πέτυχε! Τώρα κάνε σύνδεση.");
        setIsRegistering(false);
        setAuthForm({ username: '', password: '' });
      } else {
        setUser(res.data);
        localStorage.setItem('python_user_data', JSON.stringify(res.data));
      }
    } catch (err) { 
      setAuthError(err.response?.status === 401 ? "Λάθος όνομα ή κωδικός" : "Σφάλμα σύνδεσης με τον server"); 
    }
  };

  const handleLogout = () => {
    setUser(null);
    setShowEditor(false);
    setStartTime(null);
    setTaskActive(false);
    setTimeoutHintSent(false);
    localStorage.removeItem('python_user_data');
    setMessages([]);
  };

  const handleStartTask = () => {
    setShowEditor(true);
    setStartTime(Date.now());
    setTaskActive(true);
    setTimeoutHintSent(false);
  };

  const requestNoSubmissionHint = async () => {
    if (!user?.id || !taskActive || timeoutHintSent || !startTime) return;

    setLoading(true);
    setTimeoutHintSent(true);
    const elapsedSeconds = Math.max(0, (Date.now() - startTime) / 1000);

    try {
      const res = await axios.post(`http://127.0.0.1:8000/chat/${user.id}`, {
        message: '__NO_SUBMISSION_40S__',
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
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!taskActive || timeoutHintSent || !startTime) return;

    const elapsed = (Date.now() - startTime) / 1000;
    const remainingMs = Math.max(0, (40 - elapsed) * 1000);

    const timerId = window.setTimeout(() => {
      requestNoSubmissionHint();
    }, remainingMs);

    return () => window.clearTimeout(timerId);
  }, [taskActive, timeoutHintSent, startTime]);

  const sendChatMessage = async (overrideMessage = null) => {
    const textToSend = overrideMessage || chatInput;
    if (!textToSend.trim()) return;

    const msg = { role: 'human', content: textToSend };
    setMessages(prev => [...prev, msg]);
    setLoading(true);
    if (!overrideMessage) setChatInput('');

    try {
      const res = await axios.post(`http://127.0.0.1:8000/chat/${user.id}`, {
        message: textToSend,
        code: "",
        time_spent: 0,
        task_started: taskActive
      });
      setMessages(prev => [...prev, { role: 'ai', content: res.data.mentor_response }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'ai', content: "⚠️ Πρόβλημα σύνδεσης με το AI." }]);
    } finally { setLoading(false); }
  };

  const handleRunCode = async () => {
    setLoading(true);
    setTimeoutHintSent(true);
    const timeSpent = startTime ? (Date.now() - startTime) / 1000 : 0;
    const codeToSubmit = typeof code === 'string' ? code : '';
    const submissionMessage = codeToSubmit.trim()
      ? `Υποβολή κώδικα:\n\`\`\`python\n${codeToSubmit}\n\`\`\``
      : 'Υποβολή κώδικα';

    setMessages(prev => [...prev, { role: 'human', content: submissionMessage }]);

    try {
      const res = await axios.post(`http://127.0.0.1:8000/chat/${user.id}`, {
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

      // Ο χρονομετρητής σταματά μόνο όταν υπάρξει σωστή λύση ή ολοκλήρωση μαθημάτων.
      if (isCorrect || courseCompleted) {
        setStartTime(null);
        setTaskActive(false);
      }
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { role: 'ai', content: "Δεν μπόρεσα να ελέγξω τον κώδικα αυτή τη στιγμή. Δοκίμασε ξανά." }]);
    } 
    finally { setLoading(false); }
  };

  if (!user) {
    return (
      <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', background: '#121212', color: 'white' }}>
        <div style={{ background: '#1e1e1e', padding: '40px', borderRadius: '20px', width: '350px', textAlign: 'center', boxShadow: '0 10px 40px rgba(0,0,0,0.6)' }}>
          <Code2 size={50} color="#4caf50" style={{ marginBottom: '15px' }} />
          <h2 style={{ marginBottom: '20px' }}>AI Python Tutor</h2>
          <input 
            style={{ width: '100%', padding: '12px', marginBottom: '10px', borderRadius: '8px', border: '1px solid #333', background: '#252526', color: 'white' }} 
            placeholder="Username" value={authForm.username} onChange={e => setAuthForm({...authForm, username: e.target.value})} 
          />
          <input 
            type="password" 
            style={{ width: '100%', padding: '12px', marginBottom: '20px', borderRadius: '8px', border: '1px solid #333', background: '#252526', color: 'white' }} 
            placeholder="Password" value={authForm.password} onChange={e => setAuthForm({...authForm, password: e.target.value})} 
          />
          {authError && <p style={{ color: '#ff5f56', fontSize: '0.8rem', marginBottom: '15px' }}>{authError}</p>}
          <button onClick={handleAuth} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: 'none', background: '#4caf50', color: 'white', fontWeight: 'bold', cursor: 'pointer' }}>
            {isRegistering ? 'Εγγραφή' : 'Είσοδος'}
          </button>
          <p onClick={() => setIsRegistering(!isRegistering)} style={{ marginTop: '20px', color: '#4caf50', cursor: 'pointer', fontSize: '0.9rem' }}>
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
          {messages.map((m, i) => (
            <div key={i} style={{ alignSelf: m.role === 'human' ? 'flex-end' : 'flex-start', maxWidth: '90%' }}>
              <div style={{ background: m.role === 'human' ? '#007acc' : '#3e3e42', padding: '15px', borderRadius: '15px' }}>
                <ReactMarkdown>
                  {sanitizeMentorText(m.content)}
                </ReactMarkdown>
                
                {hasStartButtonToken(m.content) && !showEditor && (
                  <button 
                    onClick={handleStartTask}
                    style={{ marginTop: '15px', padding: '10px 20px', background: '#4caf50', border: 'none', borderRadius: '8px', color: 'white', fontWeight: 'bold', cursor: 'pointer' }}
                  >
                    🚀 Ξεκινάμε!
                  </button>
                )}
              </div>
            </div>
          ))}
          {loading && <div style={{ color: '#888', fontStyle: 'italic' }}>Ο Mentor πληκτρολογεί...</div>}
          <div ref={chatEndRef} />
        </div>

        <div style={{ padding: '20px', background: '#2d2d2d', display: 'flex', gap: '10px' }}>
          <input 
            style={{ flex: 1, padding: '12px', borderRadius: '10px', border: 'none', background: '#3c3c3c', color: 'white' }} 
            value={chatInput} onChange={e => setChatInput(e.target.value)} 
            onKeyDown={e => e.key === 'Enter' && sendChatMessage()} 
            placeholder="Γράψε εδώ..." 
          />
          <button onClick={() => sendChatMessage()} style={{ background: '#007acc', border: 'none', padding: '12px', borderRadius: '10px' }}>
            <Send size={20} color="white" />
          </button>
        </div>
      </div>

      {showEditor && (
        <div style={{ width: '60%', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '15px', background: '#1e1e1e', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Code2 size={18} color="#007acc" />
              <span>{getEditorFileName(user?.username)}</span>
            </div>
            <button onClick={handleRunCode} style={{ background: '#4caf50', border: 'none', padding: '10px 20px', borderRadius: '8px', color: 'white', fontWeight: 'bold' }}>
              <Play size={18} /> Έλεγχος Κώδικα
            </button>
          </div>
          <Editor height="100%" theme="vs-dark" defaultLanguage="python" value={code} onChange={(value) => setCode(value ?? '')} options={{ fontSize: 16 }} />
        </div>
      )}
    </div>
  );
}