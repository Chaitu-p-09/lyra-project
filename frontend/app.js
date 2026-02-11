const CONFIG = {
  // Change this in deployment to your Render backend URL.
  API_BASE_URL: 'https://lyra-backend-16xj.onrender.com',
  LANG: 'en-IN',
};

const state = {
  status: 'Idle',
  currentSpeaker: 'Chaitu',
  mode: 'CHILL',
  recognitionActive: false,
};

const ui = {
  statusText: document.getElementById('statusText'),
  speakerText: document.getElementById('speakerText'),
  modeText: document.getElementById('modeText'),
  micButton: document.getElementById('micButton'),
};

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const speechSynthesisRef = window.speechSynthesis;

function updateUI() {
  ui.statusText.textContent = state.status;
  ui.speakerText.textContent = state.currentSpeaker;
  ui.modeText.textContent = state.mode;

  ui.micButton.classList.remove('listening', 'thinking', 'error');
  if (state.status === 'Listening') ui.micButton.classList.add('listening');
  if (state.status === 'Thinking') ui.micButton.classList.add('thinking');
  if (state.status === 'Error') ui.micButton.classList.add('error');
}

function setStatus(value) {
  state.status = value;
  updateUI();
}

function getPreferredVoice() {
  const voices = speechSynthesisRef.getVoices();
  // Prefer Indian English voice; fallback to any female sounding name.
  return (
    voices.find((voice) => /en-IN|hi-IN|mr-IN/i.test(voice.lang)) ||
    voices.find((voice) => /female|zira|heera|priya|veena|raveena|sangeeta/i.test(voice.name)) ||
    voices[0]
  );
}

function speak(text) {
  if (!speechSynthesisRef || !text) return;
  speechSynthesisRef.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = CONFIG.LANG;
  utterance.rate = 1;
  utterance.pitch = 1.02;

  const voice = getPreferredVoice();
  if (voice) utterance.voice = voice;

  speechSynthesisRef.speak(utterance);
}

function sanitizeSpokenInput(text) {
  return String(text || '')
    .replace(/[<>`$\\]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 600);
}

async function sendToLyra(userText) {
  setStatus('Thinking');

  try {
    const payload = {
      message: sanitizeSpokenInput(userText),
      currentSpeaker: state.currentSpeaker,
      mode: state.mode,
    };

    const response = await fetch(`${CONFIG.API_BASE_URL}/lyra`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Unable to process request.');
    }

    state.currentSpeaker = data.currentSpeaker || state.currentSpeaker;
    state.mode = data.mode || state.mode;
    updateUI();

    speak(data.reply || 'Sorry, I could not generate a response right now.');
    setStatus('Idle');
  } catch (error) {
    console.error('LYRA error:', error);
    setStatus('Error');
    speak('Sorry, I am facing a connection issue right now. Please try again.');
    setTimeout(() => setStatus('Idle'), 1200);
  }
}

function buildRecognition() {
  if (!SpeechRecognition) {
    setStatus('Error');
    speak('Speech recognition is not supported in this browser. Please use Chrome.');
    return null;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = CONFIG.LANG;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    state.recognitionActive = true;
    setStatus('Listening');
  };

  recognition.onresult = (event) => {
    const transcript = event.results?.[0]?.[0]?.transcript || '';
    const cleaned = sanitizeSpokenInput(transcript);
    if (!cleaned) {
      setStatus('Idle');
      return;
    }
    sendToLyra(cleaned);
  };

  recognition.onerror = () => {
    state.recognitionActive = false;
    setStatus('Error');
    speak('I could not hear you clearly. Please try again.');
    setTimeout(() => setStatus('Idle'), 1000);
  };

  recognition.onend = () => {
    state.recognitionActive = false;
    if (state.status === 'Listening') setStatus('Idle');
  };

  return recognition;
}

let recognition = buildRecognition();

ui.micButton.addEventListener('click', () => {
  if (!recognition) {
    recognition = buildRecognition();
    return;
  }

  if (state.recognitionActive) {
    recognition.stop();
    setStatus('Idle');
    return;
  }

  try {
    recognition.start();
  } catch {
    // Some browsers throw if start() is called too quickly.
    setStatus('Idle');
  }
});

window.speechSynthesis?.addEventListener('voiceschanged', () => {
  // Trigger voice list caching.
  getPreferredVoice();
});

updateUI();
