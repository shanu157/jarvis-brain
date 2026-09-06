const log = document.getElementById('log');
const form = document.getElementById('composer');
const input = document.getElementById('input');
const core = document.getElementById('core');
const connDot = document.getElementById('conn-dot');
const statMemory = document.getElementById('stat-memory');
const micBtn = document.getElementById('mic-btn');
const langSelect = document.getElementById('lang-select');

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const label = document.createElement('span');
  label.className = 'msg-label';
  label.textContent = role === 'user' ? 'you' : role === 'action' ? 'jarvis · action' : role === 'error' ? 'jarvis · error' : 'jarvis';
  div.appendChild(label);
  div.appendChild(document.createTextNode(text));
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function refreshStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    statMemory.textContent = `${data.memory_kb} KB`;
    connDot.className = 'dot online';
  } catch (e) {
    connDot.className = 'dot error';
  }
}

// Strips markdown so spoken replies don't say "asterisk asterisk bold asterisk asterisk"
function stripMarkdownForSpeech(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/[*_#`~]/g, '')
    .replace(/\n+/g, '. ');
}

// The core send: used by both typing and voice input, so both paths behave identically
async function sendMessage(text) {
  addMessage('user', text);
  core.classList.add('thinking');

  let reply = null;
  let isAction = false;
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    if (data.error) {
      addMessage('error', data.error);
    } else {
      reply = data.reply;
      isAction = data.type === 'action';
      addMessage(isAction ? 'action' : 'jarvis', reply);
    }
  } catch (err) {
    addMessage('error', 'Connection lost — is the Jarvis server still running?');
  } finally {
    core.classList.remove('thinking');
    refreshStatus();
  }
  return reply;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  sendMessage(text);
});

refreshStatus();
setInterval(refreshStatus, 15000);

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/static/service-worker.js').catch(() => {});
}

// ---------- Voice mode (Web Speech API — live listen + live talk, any language) ----------

const VOICE_LANGS = [
  ['en-US', 'English'],
  ['en-IN', 'English (India)'],
  ['hi-IN', 'Hindi'],
  ['bn-IN', 'Bengali'],
  ['es-ES', 'Spanish'],
  ['fr-FR', 'French'],
  ['de-DE', 'German'],
  ['pt-PT', 'Portuguese'],
  ['ar-SA', 'Arabic'],
  ['ru-RU', 'Russian'],
  ['ja-JP', 'Japanese'],
  ['zh-CN', 'Chinese'],
  ['ur-PK', 'Urdu'],
  ['ta-IN', 'Tamil'],
  ['te-IN', 'Telugu'],
];

VOICE_LANGS.forEach(([code, label]) => {
  const opt = document.createElement('option');
  opt.value = code;
  opt.textContent = label;
  langSelect.appendChild(opt);
});
langSelect.value = localStorage.getItem('jarvis-voice-lang') || 'en-US';
langSelect.addEventListener('change', () => {
  localStorage.setItem('jarvis-voice-lang', langSelect.value);
});

const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let voiceModeActive = false;

if (!SpeechRecognitionAPI) {
  micBtn.disabled = true;
  micBtn.title = 'Voice input not supported in this browser';
}

function speak(text, onDone) {
  const utter = new SpeechSynthesisUtterance(stripMarkdownForSpeech(text));
  utter.lang = langSelect.value;
  utter.onend = onDone;
  utter.onerror = onDone;
  speechSynthesis.speak(utter);
}

function startListening() {
  if (!SpeechRecognitionAPI) return;
  recognition = new SpeechRecognitionAPI();
  recognition.lang = langSelect.value;
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = async (event) => {
    const heard = event.results[0][0].transcript;
    if (!heard.trim()) {
      if (voiceModeActive) startListening();
      return;
    }
    const reply = await sendMessage(heard);
    if (voiceModeActive && reply) {
      speak(reply, () => { if (voiceModeActive) startListening(); });
    } else if (voiceModeActive) {
      startListening();
    }
  };

  recognition.onerror = (event) => {
    if (event.error === 'no-speech' && voiceModeActive) {
      startListening(); // silence timeout — just keep the conversation open
    } else if (event.error !== 'aborted') {
      addMessage('error', `Voice recognition error: ${event.error}`);
      stopVoiceMode();
    }
  };

  recognition.start();
  micBtn.classList.add('listening');
}

function stopVoiceMode() {
  voiceModeActive = false;
  micBtn.classList.remove('listening');
  speechSynthesis.cancel();
  if (recognition) {
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.abort();
  }
}

micBtn.addEventListener('click', () => {
  if (voiceModeActive) {
    stopVoiceMode();
  } else {
    voiceModeActive = true;
    startListening();
  }
});
