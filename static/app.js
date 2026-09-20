'use strict';

/*
 * JARVIS FRONTEND
 *
 * Local:
 *   http://127.0.0.1:5000
 *
 * Cloud:
 *   https://shanu11.pythonanywhere.com
 */

const CLOUD_URL = 'https://shanu11.pythonanywhere.com';
const LOCAL_URL = 'http://127.0.0.1:5000';


/* ---------- DOM ---------- */

const log = document.getElementById('log');
const welcome = document.getElementById('welcome');

const form = document.getElementById('composer');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');

const attachBtn = document.getElementById('attach-btn');
const cameraBtn = document.getElementById('camera-btn');
const micBtn = document.getElementById('mic-btn');
let busy = false;

const fileInput = document.getElementById('file-input');
const cameraInput = document.getElementById('camera-input');

const attachmentPreview =
  document.getElementById('attachment-preview');

const attachmentName =
  document.getElementById('attachment-name');

const attachmentType =
  document.getElementById('attachment-type');

const removeAttachment =
  document.getElementById('remove-attachment');

const connectionMode =
  document.getElementById('connection-mode');

const statusDot =
  document.getElementById('status-dot');

const statMemory =
  document.getElementById('stat-memory');

const langSelect =
  document.getElementById('lang-select');


/* ---------- STATE ---------- */

let activeBackend = null;
let syncRunning = false;
let selectedFile = null;


/* ---------- UI ---------- */

function addMessage(role, text) {

  if (!log) return;

  if (welcome) {
    welcome.classList.add('hidden');
  }

  const div = document.createElement('div');

  div.className = `msg ${role}`;

  const label = document.createElement('span');

  label.className = 'msg-label';

  if (role === 'user') {
    label.textContent = 'YOU';
  } else if (role === 'action') {
    label.textContent = 'JARVIS · ACTION';
  } else if (role === 'error') {
    label.textContent = 'JARVIS · ERROR';
  } else {
    label.textContent = 'JARVIS AI';
  }

  div.appendChild(label);

  div.appendChild(
    document.createTextNode(String(text ?? ''))
  );

  log.appendChild(div);

  log.scrollTop = log.scrollHeight;
}


function setThinking(value) {

  if (!sendBtn) return;

  sendBtn.disabled = value;

  if (value) {
    sendBtn.querySelector('span').textContent = '...';
  } else {
    sendBtn.querySelector('span').textContent = 'SEND';
  }
}


function setBackend(url, mode) {

  activeBackend = url;

  if (connectionMode) {
    connectionMode.textContent = mode;
  }

  if (!statusDot) return;

  statusDot.className = 'status-dot';

  if (mode === 'LOCAL') {
    statusDot.classList.add('local');
  }

  if (mode === 'OFFLINE') {
    statusDot.classList.add('error');
  }
}


/* ---------- BACKEND ---------- */

async function testBackend(base) {

  const controller = new AbortController();

  const timer = setTimeout(
    () => controller.abort(),
    3000
  );

  try {

    const res = await fetch(
      `${base}/api/status?_=${Date.now()}`,
      {
        method: 'GET',
        cache: 'no-store',
        signal: controller.signal
      }
    );

    clearTimeout(timer);

    if (!res.ok) return false;

    const data = await res.json();

    if (!data.ok) return false;

    if (statMemory && data.memory_kb !== undefined) {
      statMemory.textContent =
        `${data.memory_kb} KB`;
    }

    return true;

  } catch (error) {

    clearTimeout(timer);

    return false;
  }
}


async function chooseBackend() {

  if (await testBackend(CLOUD_URL)) {

    setBackend(CLOUD_URL, 'CLOUD');

    return CLOUD_URL;
  }


  if (await testBackend(LOCAL_URL)) {

    setBackend(LOCAL_URL, 'LOCAL');

    return LOCAL_URL;
  }


  setBackend(null, 'OFFLINE');

  if (statMemory) {
    statMemory.textContent = '— KB';
  }

  return null;
}


async function refreshStatus() {
  await chooseBackend();
}


/* ---------- PHONE COMMANDS ---------- */

function isPhoneCommand(text) {

  const t = text
    .toLowerCase()
    .trim();

  return (
    t.includes('flashlight') ||
    t.includes('brightness') ||
    t.includes('vibrate') ||
    t.includes('battery') ||
    t.includes('alarm') ||
    t.includes('remind me') ||
    t.includes('notify me') ||
    t.includes('where am i') ||
    t.includes('location') ||
    t.includes('press back') ||
    t.includes('tap ') ||
    t.includes('screenshot') ||
    t.includes('alarm') ||
    t.includes('remind me') ||
    t.includes('notify me')
  );
}


/* ---------- CHAT ---------- */

async function requestChat(base, text) {

  const res = await fetch(
    `${base}/api/chat`,
    {
      method: 'POST',

      headers: {
        'Content-Type': 'application/json'
      },

      body: JSON.stringify({
        message: text
      })
    }
  );

  let data;

  try {
    data = await res.json();
  } catch (_) {
    throw new Error(
      `Server returned HTTP ${res.status}`
    );
  }

  if (!res.ok || data.error) {

    throw new Error(
      data.error ||
      `Server returned HTTP ${res.status}`
    );
  }

  return data;
}


async function sendMessage(text) {

  text = String(text || '').trim();

  if (!text) return null;

  addMessage('user', text);

  setThinking(true);

  try {

    /*
     * DEVICE COMMANDS
     *
     * Always local.
     */

    if (isPhoneCommand(text)) {

      const localOK =
        await testBackend(LOCAL_URL);

      if (!localOK) {

        addMessage(
          'error',
          'Local Jarvis is not running. Start the local Python brain first.'
        );

        return null;
      }

      setBackend(LOCAL_URL, 'LOCAL');

      const data =
        await requestChat(LOCAL_URL, text);

      const reply =
        data.reply || 'Command completed.';

      addMessage(
        data.type === 'action'
          ? 'action'
          : 'jarvis',
        reply
      );

      return reply;
    }


    /*
     * NORMAL CHAT
     *
     * Cloud first.
     * Local fallback.
     */

    let backend = activeBackend;

    if (!backend) {
      backend = await chooseBackend();
    }


    if (backend) {

      try {

        const data =
          await requestChat(backend, text);

        const reply =
          data.reply || 'I received your message.';

        addMessage(
          data.type === 'action'
            ? 'action'
            : 'jarvis',
          reply
        );

        return reply;

      } catch (firstError) {

        /*
         * If cloud failed, immediately try local.
         */

        if (backend === CLOUD_URL) {

          const localOK =
            await testBackend(LOCAL_URL);

          if (localOK) {

            setBackend(
              LOCAL_URL,
              'LOCAL'
            );

            const data =
              await requestChat(
                LOCAL_URL,
                text
              );

            const reply =
              data.reply ||
              'I received your message.';

            addMessage(
              data.type === 'action'
                ? 'action'
                : 'jarvis',
              reply
            );

            return reply;
          }
        }

        throw firstError;
      }
    }


    throw new Error(
      'Cloud and local Jarvis are unavailable.'
    );

  } catch (error) {

    console.error(
      'JARVIS CHAT ERROR:',
      error
    );

    addMessage(
      'error',
      error.message ||
      'Something went wrong.'
    );

    return null;

  } finally {

    setThinking(false);

    refreshStatus();
  }
}


/* ---------- FORM ---------- */

if (form) {

  form.addEventListener(
    'submit',
    function(event) {

      event.preventDefault();

      event.stopPropagation();

      const text =
        input.value.trim();

      if (!text) {
        input.focus();
        return;
      }

      input.value = '';

      void sendMessage(text);
    }
  );
}


/* ---------- ENTER KEY ---------- */

if (input) {

  input.addEventListener(
    'keydown',
    function(event) {

      if (
        event.key === 'Enter' &&
        !event.shiftKey
      ) {

        event.preventDefault();

        form.requestSubmit();
      }
    }
  );
}


/* ---------- SUGGESTIONS ---------- */

document
  .querySelectorAll('[data-prompt]')
  .forEach(button => {

    button.addEventListener(
      'click',
      () => {

        const prompt =
          button.dataset.prompt || '';

        input.value = prompt;

        input.focus();
      }
    );
  });


/* ---------- FILE UI ---------- */

function showSelectedFile(file) {

  selectedFile = file;

  if (!file) {
    attachmentPreview.classList.add('hidden');
    return;
  }

  attachmentName.textContent =
    file.name;

  attachmentType.textContent =
    `${file.type || 'unknown type'} · ${formatBytes(file.size)}`;

  attachmentPreview.classList.remove(
    'hidden'
  );
}


function formatBytes(bytes) {

  if (!bytes) return '0 B';

  const units = [
    'B',
    'KB',
    'MB',
    'GB'
  ];

  const index =
    Math.floor(
      Math.log(bytes) /
      Math.log(1024)
    );

  return (
    Math.round(
      bytes /
      Math.pow(1024, index)
    * 10
    ) / 10
  ) + ' ' + units[index];
}


if (attachBtn) {

  attachBtn.addEventListener(
    'click',
    () => fileInput.click()
  );
}


if (cameraBtn) {

  cameraBtn.addEventListener(
    'click',
    () => cameraInput.click()
  );
}


if (fileInput) {

  fileInput.addEventListener(
    'change',
    () => {

      const file =
        fileInput.files?.[0];

      showSelectedFile(file);
    }
  );
}


if (cameraInput) {

  cameraInput.addEventListener(
    'change',
    () => {

      const file =
        cameraInput.files?.[0];

      showSelectedFile(file);
    }
  );
}


if (removeAttachment) {

  removeAttachment.addEventListener(
    'click',
    () => {

      selectedFile = null;

      fileInput.value = '';
      cameraInput.value = '';

      attachmentPreview.classList.add(
        'hidden'
      );
    }
  );
}


/*
 * For now this only prepares the attachment UI.
 * The actual AI vision/document-analysis API
 * will be connected next.
 */

function describeSelectedFile() {

  if (!selectedFile) {
    return '';
  }

  return (
    `Attached file: ${selectedFile.name}`
  );
}


/* ---------- VOICE ---------- */

const SpeechRecognition =
  window.SpeechRecognition ||
  window.webkitSpeechRecognition;

if (micBtn && SpeechRecognition) {

  const recognition =
    new SpeechRecognition();

  recognition.lang = 'en-US';

  recognition.interimResults = false;

  recognition.continuous = false;


  micBtn.addEventListener(
    'click',
    () => {

      try {
        recognition.start();
        micBtn.textContent = '●';
      } catch (_) {}
    }
  );


  recognition.onresult =
    event => {

      const heard =
        event.results?.[0]?.[0]?.transcript ||
        '';

      input.value = heard;

      input.focus();

      micBtn.textContent = '🎙';
    };


  recognition.onerror =
    () => {
      micBtn.textContent = '🎙';
    };


  recognition.onend =
    () => {
      micBtn.textContent = '🎙';
    };

} else if (micBtn) {

  micBtn.title =
    'Voice input is not supported here';
}


/* ---------- LANGUAGE ---------- */

const languages = [
  ['en-US', 'English'],
  ['hi-IN', 'Hindi'],
  ['bn-IN', 'Bengali'],
  ['ta-IN', 'Tamil'],
  ['te-IN', 'Telugu']
];

if (langSelect) {

  for (const [value, label] of languages) {

    const option =
      document.createElement('option');

    option.value = value;
    option.textContent = label;

    langSelect.appendChild(option);
  }

  langSelect.value = 'en-US';

  langSelect.addEventListener(
    'change',
    () => {

      try {
        localStorage.setItem(
          'jarvis_voice_language',
          langSelect.value
        );
      } catch (_) {}
    }
  );
}


/* ---------- STARTUP ---------- */

async function boot() {

  /*
   * Make sure stale service-worker
   * cached JavaScript cannot break the UI.
   */

  try {

    if ('serviceWorker' in navigator) {

      const registrations =
        await navigator.serviceWorker
          .getRegistrations();

      for (const registration of registrations) {
        await registration.unregister();
      }
    }

  } catch (_) {}


  await refreshStatus();

  input.focus();
}


window.addEventListener(
  'online',
  refreshStatus
);

window.addEventListener(
  'offline',
  () => setBackend(null, 'OFFLINE')
);


void boot();

