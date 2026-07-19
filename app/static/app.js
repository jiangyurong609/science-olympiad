const state = {
  token: localStorage.getItem('token'),
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  attempt: null,
  exam: null,
  exams: [],
  events: [],
  dashboard: null,
  coachDashboard: null,
  teams: [],
  lessons: [],
  featuredLessonId: null,
  currentLesson: null,
  lessonBlockIndex: 0,
  practiceSets: [],
  practiceSession: null,
  activeEventSlug: localStorage.getItem('activeEventSlug') || 'rocks-and-minerals',
  activeTaxonomy: null,
  accommodation: null,
  sourceCoverage: [],
  questionReviewQueue: [],
  calibrationQueue: [],
  contentChallenges: [],
  reviewAttemptId: null,
  notifications: [],
  unreadNotifications: 0,
  notificationTimer: null,
  tutorSession: null,
  tutorContext: null,
  practiceTimer: null,
  practiceSubmitting: false,
  practiceTimerWarned: false,
  eventRequestId: 0,
  timer: null,
  currentQuestion: 0,
  answers: {},
  confidences: {},
  sequences: {},
  saveQueue: new Map(),
  saveInflight: new Map(),
  questionTimes: {},
  questionEnteredAt: null,
  examClientSession: sessionStorage.getItem('fieldstoneExamClientSession') || crypto.randomUUID(),
  offlineSyncing: false,
  offlineRetryTimer: null,
  pendingAutoSubmit: false,
  submitting: false,
  authConfig: null,
  refreshToken: localStorage.getItem('firebaseRefreshToken'),
  tokenExpiresAt: Number(localStorage.getItem('firebaseTokenExpiresAt') || 0),
};
sessionStorage.setItem('fieldstoneExamClientSession', state.examClientSession);

const $ = id => document.getElementById(id);
const appViews = ['dashboard', 'learn', 'practice', 'errors', 'coach', 'content'];
const mainSections = ['auth', 'app-shell', 'exam', 'review'];
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function preferredScrollBehavior() {
  return prefersReducedMotion.matches ? 'auto' : 'smooth';
}

const categoryProfiles = {
  'Earth & Space Science': { icon: '◐', accent: 'sky', skill: 'evidence and systems reasoning' },
  'Life, Personal & Social Science': { icon: '✦', accent: 'leaf', skill: 'observation and biological reasoning' },
  'Physical Science & Chemistry': { icon: '◉', accent: 'amber', skill: 'measurement and analytical reasoning' },
  'Inquiry & Nature of Science': { icon: '◇', accent: 'violet', skill: 'experimental and problem-solving skills' },
  'Technology & Engineering Design': { icon: '⌘', accent: 'slate', skill: 'design and engineering judgment' },
};

function eventExperience(event = activeEvent()) {
  const category = event?.category || 'Science Olympiad';
  const profile = categoryProfiles[category] || { icon: '◇', accent: 'forest', skill: 'competition-ready scientific reasoning' };
  const name = event?.name || 'Your Event';
  const focus = event?.topic_focus || event?.description || `${name} concepts, evidence, and competition strategy`;
  return {
    ...profile,
    name,
    category,
    focus,
    itemLabel: `${name} challenge`,
    resultTitle: `${name} Practice Complete`,
    reviewTopic: name,
  };
}

function activeEvent() {
  return state.events.find(event => event.slug === state.activeEventSlug) || null;
}

// A subject's experience copy is keyed by the base slug (e.g. 'entomology'),
// while the active event may be a division-specific catalog slug ('entomology-c').
function subjectKeyOf(slug) {
  return (slug || '').replace(/-(b|c)$/, '');
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
}

function safeUrl(value = '') {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
  } catch { return '#'; }
}

function safeActionUrl(value = '') {
  if (value.startsWith('/#') || value.startsWith('#')) return value;
  return safeUrl(value);
}

// Same-origin media paths we control (e.g. /static/media/...). Allows a
// leading-slash relative path or a full http(s) URL; rejects anything else.
function mediaUrl(value = '') {
  if (/^\/static\/[A-Za-z0-9/._-]+$/.test(value)) return value;
  return safeUrl(value);
}

function setBusy(button, busy, label = 'Working…') {
  if (!button) return;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalLabel || button.textContent;
    button.disabled = false;
  }
}

function setExamSaveState(message, sync = 'synced') {
  for (const id of ['save-state', 'exam-save-state']) {
    const node = $(id);
    node.textContent = message;
    if (message) node.dataset.sync = sync;
    else delete node.dataset.sync;
  }
}

function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toast.timeout);
  toast.timeout = setTimeout(() => { node.hidden = true; }, 3500);
}

// Styled, promise-based replacement for window.confirm — resolves true/false.
function confirmDialog({ title = 'Are you sure?', body = '', confirmLabel = 'Confirm', cancelLabel = 'Cancel' } = {}) {
  return new Promise(resolve => {
    const modal = $('confirm-modal'), ok = $('confirm-ok'), cancel = $('confirm-cancel');
    $('confirm-title').textContent = title;
    $('confirm-body').textContent = body;
    ok.textContent = confirmLabel;
    cancel.textContent = cancelLabel;
    const prevFocus = document.activeElement;
    modal.hidden = false;
    ok.focus();
    const close = result => {
      modal.hidden = true;
      ok.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      if (prevFocus?.focus) prevFocus.focus();
      resolve(result);
    };
    const onOk = () => close(true);
    const onCancel = () => close(false);
    const onBackdrop = event => { if (event.target === modal) close(false); };
    const onKey = event => {
      if (event.key === 'Escape') close(false);
      else if (event.key === 'Enter') { event.preventDefault(); close(true); }
    };
    ok.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

async function api(path, options = {}) {
  if (state.authConfig?.provider === 'firebase' && path !== '/auth/config') await refreshFirebaseTokenIfNeeded();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let response;
  try {
    response = await fetch(`/api${path}`, { ...options, headers });
  } catch (error) {
    throw new Error('You appear to be offline. Check your connection and try again.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // Only tear down an established session: during login/bootstrap a 401
    // simply means the profile does not exist yet, and clearing the token
    // here would strip the Authorization header from the follow-up
    // bootstrap call.
    if (response.status === 401 && state.token && state.user) clearAuth();
    const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message;
    const error = new Error(detail || 'That request did not finish. Please try again.');
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  return data;
}

function showSection(id) {
  mainSections.forEach(section => { $(section).hidden = section !== id; });
  document.body.classList.toggle('exam-active', id === 'exam');
  if (id === 'exam') closeTutor();
  window.scrollTo({ top: 0, behavior: 'instant' });
}

function showView(id, updateHash = true) {
  if (!appViews.includes(id)) id = 'dashboard';
  showSection('app-shell');
  appViews.forEach(view => { $(view).hidden = view !== id; });
  document.querySelectorAll('[data-view-link]').forEach(link => {
    const active = link.dataset.viewLink === id;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
  if (updateHash) {
    const route = id === 'dashboard' ? 'overview' : id;
    const eventSuffix = ['learn', 'practice'].includes(id) ? `?event=${encodeURIComponent(state.activeEventSlug)}` : '';
    history.replaceState(null, '', `#${route}${eventSuffix}`);
  }
  $(`${id === 'dashboard' ? 'welcome' : `${id}-title`}`)?.focus?.({ preventScroll: true });
}

function persistAuth(data, firebaseSession = null) {
  state.token = data.access_token;
  state.user = data.user;
  localStorage.setItem('token', state.token);
  localStorage.setItem('user', JSON.stringify(state.user));
  if (firebaseSession) {
    state.refreshToken = firebaseSession.refreshToken;
    state.tokenExpiresAt = Date.now() + (Number(firebaseSession.expiresIn || 3600) * 1000);
    localStorage.setItem('firebaseRefreshToken', state.refreshToken);
    localStorage.setItem('firebaseTokenExpiresAt', String(state.tokenExpiresAt));
  }
  $('logout').hidden = false;
  loadApplication();
}

function clearAuth() {
  const priorUserId = state.user?.id;
  if (priorUserId) Object.keys(localStorage)
    .filter(key => key.startsWith(`fieldstone:offline-exam:${priorUserId}:`))
    .forEach(key => localStorage.removeItem(key));
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  localStorage.removeItem('firebaseRefreshToken');
  localStorage.removeItem('firebaseTokenExpiresAt');
  state.token = null;
  state.user = null;
  state.refreshToken = null;
  state.tokenExpiresAt = 0;
  state.attempt = null;
  clearInterval(state.notificationTimer);
  state.notificationTimer = null;
  $('logout').hidden = true;
  $('notifications-button').hidden = true;
  $('notification-panel').hidden = true;
  closeTutor();
  showSection('auth');
}

function firebaseErrorMessage(code = '') {
  const messages = {
    EMAIL_EXISTS: 'This email already has an account. Log in instead.',
    EMAIL_NOT_FOUND: 'No account uses this email. Create an account first.',
    INVALID_LOGIN_CREDENTIALS: 'The email or password is incorrect. Check both and try again.',
    INVALID_PASSWORD: 'The email or password is incorrect. Check both and try again.',
    USER_DISABLED: 'This account is disabled. Ask your coach or administrator for help.',
    TOO_MANY_ATTEMPTS_TRY_LATER: 'Too many attempts. Wait a few minutes, then try again.',
    WEAK_PASSWORD: 'Choose a stronger password with at least 8 characters.',
  };
  return messages[code] || 'Firebase could not complete that request. Try again.';
}

async function firebaseRequest(action, payload) {
  const response = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:${action}?key=${encodeURIComponent(state.authConfig.firebase_web_api_key)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(firebaseErrorMessage(data.error?.message?.split(' : ')[0]));
  return data;
}

let firebaseSdkPromise = null;
function loadFirebaseSdk() {
  if (!firebaseSdkPromise) {
    firebaseSdkPromise = Promise.all([
      import('https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js'),
      import('https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js'),
    ]).then(([appModule, authModule]) => {
      const app = appModule.initializeApp({
        apiKey: state.authConfig.firebase_web_api_key,
        authDomain: `${state.authConfig.firebase_project_id}.firebaseapp.com`,
        projectId: state.authConfig.firebase_project_id,
      });
      return { auth: authModule.getAuth(app), authModule };
    });
    firebaseSdkPromise.catch(() => { firebaseSdkPromise = null; });
  }
  return firebaseSdkPromise;
}

function googleAuthErrorMessage(error) {
  const code = String(error?.code || '');
  if (code.includes('operation-not-allowed')) return 'Google sign-in is not enabled for this app yet. Use email and password, or ask an administrator to enable Google sign-in.';
  if (code.includes('popup-closed-by-user') || code.includes('cancelled-popup-request')) return 'The Google window was closed before finishing. Try again when you are ready.';
  if (code.includes('popup-blocked')) return 'Your browser blocked the Google window. Allow pop-ups for this site and try again.';
  if (code.includes('unauthorized-domain')) return 'This site is not yet authorized for Google sign-in. Ask an administrator to add it in Firebase.';
  return error?.message || 'Google sign-in did not finish. Try again.';
}

function showGoogleProfileForm(firebaseUser) {
  ['login-form', 'register-form'].forEach(id => { $(id).hidden = true; });
  document.querySelector('.tabs').hidden = true;
  $('google-auth').hidden = true;
  $('google-profile-form').hidden = false;
  $('google-profile-email').textContent = firebaseUser.email || '';
  if (!$('google-profile-name').value) $('google-profile-name').value = firebaseUser.displayName || '';
  $('google-profile-name').focus();
}

async function continueWithGoogle(button) {
  $('auth-error').textContent = '';
  $('resend-verification').hidden = true;
  setBusy(button, true, 'Opening Google…');
  try {
    const { auth, authModule } = await loadFirebaseSdk();
    const result = await authModule.signInWithPopup(auth, new authModule.GoogleAuthProvider());
    state.token = await result.user.getIdToken();
    state.refreshToken = result.user.refreshToken;
    state.tokenExpiresAt = Date.now() + 55 * 60_000;
    let user;
    try {
      user = await api('/auth/me');
    } catch (error) {
      if (error.status === 401) { showGoogleProfileForm(result.user); return; }
      throw error;
    }
    persistAuth({ access_token: state.token, user }, { refreshToken: state.refreshToken, expiresIn: 3300 });
  } catch (error) {
    $('auth-error').textContent = googleAuthErrorMessage(error);
    $('auth-error').focus();
  } finally { setBusy(button, false); }
}

$('google-signin').addEventListener('click', event => continueWithGoogle(event.currentTarget));

$('google-profile-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  if (!payload.age_years) delete payload.age_years; else payload.age_years = Number(payload.age_years);
  if (!payload.guardian_email) delete payload.guardian_email;
  $('auth-error').textContent = '';
  setBusy(button, true, 'Creating Profile…');
  try {
    const bootstrapped = await api('/auth/firebase/bootstrap', { method: 'POST', body: JSON.stringify(payload) });
    if (bootstrapped.pending_guardian_consent) {
      $('auth-error').classList.remove('error');
      $('auth-error').textContent = 'Profile created. Ask your guardian to approve the consent email before logging in.';
      return;
    }
    persistAuth({ access_token: state.token, user: bootstrapped.user }, { refreshToken: state.refreshToken, expiresIn: 3300 });
  } catch (error) {
    $('auth-error').classList.add('error');
    $('auth-error').textContent = error.message;
    $('auth-error').focus();
  } finally { setBusy(button, false); }
});

$('resend-verification').addEventListener('click', async event => {
  const button = event.currentTarget;
  const email = $('login-email').value.trim();
  const password = $('login-password').value;
  if (!email || !password) {
    $('auth-error').textContent = 'Enter your email and password first, then resend the verification email.';
    return;
  }
  setBusy(button, true, 'Sending…');
  try {
    const session = await firebaseRequest('signInWithPassword', { email, password, returnSecureToken: true });
    await firebaseRequest('sendOobCode', { requestType: 'VERIFY_EMAIL', idToken: session.idToken });
    $('auth-error').classList.remove('error');
    $('auth-error').textContent = `Verification email sent to ${email}. Click the link inside it, then log in again.`;
    button.hidden = true;
  } catch (error) {
    $('auth-error').textContent = error.message;
  } finally { setBusy(button, false); }
});

async function refreshFirebaseTokenIfNeeded() {
  if (!state.refreshToken || Date.now() < state.tokenExpiresAt - 60_000) return;
  const response = await fetch(`https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(state.authConfig.firebase_web_api_key)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: state.refreshToken }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    clearAuth();
    throw new Error('Your session expired. Log in again to continue.');
  }
  state.token = data.id_token;
  state.refreshToken = data.refresh_token;
  state.tokenExpiresAt = Date.now() + (Number(data.expires_in || 3600) * 1000);
  localStorage.setItem('token', state.token);
  localStorage.setItem('firebaseRefreshToken', state.refreshToken);
  localStorage.setItem('firebaseTokenExpiresAt', String(state.tokenExpiresAt));
}

document.querySelectorAll('[data-tab]').forEach(tab => {
  tab.addEventListener('click', () => {
    const selected = tab.dataset.tab;
    document.querySelectorAll('[data-tab]').forEach(item => item.setAttribute('aria-selected', String(item === tab)));
    $('login-form').hidden = selected !== 'login';
    $('register-form').hidden = selected !== 'register';
    $('auth-error').textContent = '';
    (selected === 'login' ? $('login-email') : $('register-name')).focus();
  });
});

$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  $('auth-error').textContent = '';
  setBusy(button, true, 'Logging In…');
  try {
    const credentials = Object.fromEntries(new FormData(event.currentTarget));
    if (state.authConfig.provider === 'firebase') {
      const session = await firebaseRequest('signInWithPassword', { ...credentials, returnSecureToken: true });
      state.token = session.idToken;
      state.refreshToken = session.refreshToken;
      state.tokenExpiresAt = Date.now() + (Number(session.expiresIn || 3600) * 1000);
      let user;
      try {
        user = await api('/auth/me');
      } catch (error) {
        const pending = JSON.parse(localStorage.getItem('pendingFirebaseProfile') || 'null');
        if (!pending || pending.email !== credentials.email.toLowerCase()) {
          // Verified identity without a local profile (e.g. account created
          // on another device): collect the profile now instead of dead-ending.
          showGoogleProfileForm({ email: credentials.email, displayName: '' });
          return;
        }
        const bootstrapped = await api('/auth/firebase/bootstrap', { method: 'POST', body: JSON.stringify(pending.profile) });
        if (bootstrapped.pending_guardian_consent) throw new Error('Your account is waiting for guardian consent. Ask your guardian to check their email.');
        user = bootstrapped.user;
        localStorage.removeItem('pendingFirebaseProfile');
      }
      persistAuth({ access_token: session.idToken, user }, session);
    } else {
      persistAuth(await api('/auth/login', { method: 'POST', body: JSON.stringify(credentials) }));
    }
  } catch (error) {
    if (error.status === 403 && error.message.toLowerCase().includes('verify your email')) {
      $('auth-error').textContent = 'Your email address is not verified yet. Open the verification email we sent and click its link, then log in again.';
      $('resend-verification').hidden = false;
    } else {
      $('auth-error').textContent = `${error.message} Check your email and password, then try again.`;
    }
    $('auth-error').focus();
  } finally { setBusy(button, false); }
});

$('register-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  if (!payload.age_years) delete payload.age_years; else payload.age_years = Number(payload.age_years);
  if (!payload.guardian_email) delete payload.guardian_email;
  $('auth-error').textContent = '';
  setBusy(button, true, 'Creating Account…');
  try {
    if (state.authConfig.provider === 'firebase') {
      const session = await firebaseRequest('signUp', { email: payload.email, password: payload.password, returnSecureToken: true });
      await firebaseRequest('sendOobCode', { requestType: 'VERIFY_EMAIL', idToken: session.idToken });
      const profile = { full_name: payload.full_name, division: payload.division, age_years: payload.age_years, guardian_email: payload.guardian_email };
      Object.keys(profile).forEach(key => profile[key] == null && delete profile[key]);
      localStorage.setItem('pendingFirebaseProfile', JSON.stringify({ email: payload.email.toLowerCase(), profile }));
      $('login-tab').click();
      $('login-email').value = payload.email;
      $('auth-error').classList.remove('error');
      $('auth-error').textContent = 'Account created. Verify your email, then return here to log in and finish your student profile.';
    } else {
      const data = await api('/auth/register', { method: 'POST', body: JSON.stringify(payload) });
      if (data.pending_guardian_consent) {
        $('auth-error').classList.remove('error');
        $('auth-error').textContent = 'Account created. Ask your guardian to approve the consent email before logging in.';
        $('login-tab').click();
      } else persistAuth(data);
    }
  } catch (error) {
    $('auth-error').classList.add('error');
    $('auth-error').textContent = error.message;
    $('auth-error').focus();
  } finally { setBusy(button, false); }
});

$('logout').addEventListener('click', async () => {
  if (state.attempt && !(await confirmDialog({
    title: 'Log out and leave the test?',
    body: 'Your answers are saved. The test timer keeps running while you\'re away.',
    confirmLabel: 'Log out', cancelLabel: 'Stay in the test',
  }))) return;
  clearAuth();
});
// The brand logo links to #overview, but the hashchange handler ignores routing
// during an exam — so mid-exam it looks frozen. Route it through Save & Exit.
document.querySelector('.brand').addEventListener('click', event => {
  if (state.attempt) { event.preventDefault(); exitExam(); }
});
$('notifications-button').addEventListener('click', () => {
  const willOpen = $('notification-panel').hidden;
  $('notification-panel').hidden = !willOpen;
  $('notifications-button').setAttribute('aria-expanded', String(willOpen));
  if (willOpen) $('notification-heading').focus();
});
$('mark-notifications-read').addEventListener('click', async event => {
  setBusy(event.currentTarget, true, 'Marking Read…');
  try {
    await api('/notifications/read-all', { method: 'POST' });
    state.notifications.forEach(notification => { notification.read = true; });
    state.unreadNotifications = 0;
    renderNotifications();
  } catch (error) { toast(error.message); }
  finally { setBusy(event.currentTarget, false); }
});
$('notification-list').addEventListener('click', async event => {
  const link = event.target.closest('[data-notification-id]');
  if (!link) return;
  event.preventDefault();
  const href = link.getAttribute('href');
  try {
    await api(`/notifications/${link.dataset.notificationId}/read`, { method: 'POST' });
    const notification = state.notifications.find(row => row.id === Number(link.dataset.notificationId));
    if (notification && !notification.read) {
      notification.read = true;
      state.unreadNotifications = Math.max(0, state.unreadNotifications - 1);
    }
    renderNotifications();
    $('notification-panel').hidden = true;
    $('notifications-button').setAttribute('aria-expanded', 'false');
    location.href = href;
  } catch (error) { toast(error.message); }
});
document.addEventListener('click', event => {
  if ($('notification-panel').hidden || event.target.closest('#notification-panel, #notifications-button')) return;
  $('notification-panel').hidden = true;
  $('notifications-button').setAttribute('aria-expanded', 'false');
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !$('notification-panel').hidden) {
    $('notification-panel').hidden = true;
    $('notifications-button').setAttribute('aria-expanded', 'false');
    $('notifications-button').focus();
  }
  if (event.key === 'Escape' && !$('tutor-panel').hidden) {
    closeTutor();
    if (!$('lesson-reader').hidden) $('open-lesson-tutor').focus({ preventScroll: true });
  }
});
$('forgot-password').addEventListener('click', async () => {
  const email = $('login-email').value.trim();
  if (!email) {
    $('auth-error').textContent = 'Enter your email first, then select Reset Password.';
    $('login-email').focus();
    return;
  }
  if (state.authConfig.provider !== 'firebase') {
    $('auth-error').textContent = 'Password recovery is available when Firebase Authentication is configured.';
    return;
  }
  setBusy($('forgot-password'), true, 'Sending…');
  try {
    await firebaseRequest('sendOobCode', { requestType: 'PASSWORD_RESET', email });
    $('auth-error').classList.remove('error');
    $('auth-error').textContent = 'Password reset email sent. Check your inbox and spam folder.';
  } catch (error) {
    $('auth-error').classList.add('error');
    $('auth-error').textContent = error.message;
  } finally { setBusy($('forgot-password'), false); }
});

$('open-lesson-tutor').addEventListener('click', () => {
  if (state.currentLesson) openTutor('lesson', state.currentLesson.id);
});
$('close-tutor').addEventListener('click', closeTutor);
$('tutor-mode').addEventListener('change', () => {
  if (state.tutorSession) {
    state.tutorSession = null;
    tutorWelcome();
    $('tutor-status').textContent = 'Tutor mode changed. Your earlier conversation remains saved in its original session.';
  }
});
$('tutor-starters').addEventListener('click', event => {
  const starter = event.target.closest('[data-tutor-starter]');
  if (!starter) return;
  $('tutor-input').value = starter.dataset.tutorStarter;
  $('tutor-input').focus();
});
$('tutor-form').addEventListener('submit', event => {
  event.preventDefault();
  const message = $('tutor-input').value.trim();
  if (!message) return;
  sendTutorMessage(message, event.currentTarget.querySelector('button[type="submit"]'));
});
document.addEventListener('click', event => {
  const trigger = event.target.closest('[data-open-tutor]');
  if (trigger) openTutor(trigger.dataset.openTutor, Number(trigger.dataset.tutorContextId));
});

document.querySelectorAll('[data-view-link]').forEach(link => {
  link.addEventListener('click', event => {
    event.preventDefault();
    showView(link.dataset.viewLink);
  });
});

document.querySelectorAll('[data-practice-jump]').forEach(button => button.addEventListener('click', () => showView('practice')));

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0].toUpperCase()).join('') || 'SO';
}

function renderSubjects() {
  const division = state.user?.division;
  const subjects = [...state.events]
    .filter(event => (event.lesson_count > 0 || event.exam_count > 0) && (event.division === division || event.division === 'B/C'))
    .sort((a, b) => Number(b.slug === state.activeEventSlug) - Number(a.slug === state.activeEventSlug)
      || b.exam_count - a.exam_count || a.name.localeCompare(b.name))
    .slice(0, 6);
  $('subject-list').innerHTML = subjects.map(event => {
    const experience = eventExperience(event);
    const active = event.slug === state.activeEventSlug;
    return `<article class="subject-card event-accent-${experience.accent} surface${active ? ' is-active' : ''}" data-available="true">
      <div class="subject-card-heading"><span class="subject-icon" aria-hidden="true">${experience.icon}</span>${active ? '<span class="subject-current">Current</span>' : ''}</div>
      <h3>${escapeHtml(event.name)}</h3><p>${escapeHtml(event.topic_focus || event.description || experience.skill)}</p>
      <div class="subject-card-meta"><span>${event.lesson_count} module${event.lesson_count === 1 ? '' : 's'}</span><span>${event.exam_count} exam${event.exam_count === 1 ? '' : 's'}</span></div>
      <footer>${event.lesson_count > 0 ? `<button class="subject-action-primary" type="button" data-subject="${escapeHtml(event.slug)}" data-subject-destination="learn">Learn</button>` : ''}${event.exam_count > 0 ? `<button type="button" data-subject="${escapeHtml(event.slug)}" data-subject-destination="practice">Practice</button>` : ''}</footer>
    </article>`;
  }).join('');
}

function renderOverviewEvent() {
  const event = activeEvent();
  if (!event) return;
  const experience = eventExperience(event);
  const completed = state.lessons.filter(lesson => lesson.progress.status === 'completed').length;
  const percent = state.lessons.length ? Math.round((completed / state.lessons.length) * 100) : 0;
  $('overview-event-icon').textContent = experience.icon;
  $('overview-event-icon').className = `current-event-icon event-accent-${experience.accent}`;
  $('overview-event-category').textContent = `${experience.category} · Division ${event.division}`;
  $('current-event-title').textContent = event.name;
  $('overview-event-focus').textContent = event.topic_focus || event.description || `Build ${experience.skill}.`;
  $('overview-event-availability').textContent = `${state.lessons.length} lesson${state.lessons.length === 1 ? '' : 's'} · ${state.practiceSets.length} skill lab${state.practiceSets.length === 1 ? '' : 's'} · ${event.exam_count} exam${event.exam_count === 1 ? '' : 's'}`;
  $('overview-learn-button').disabled = state.lessons.length === 0;
  $('overview-practice-button').disabled = state.practiceSets.length === 0 && event.exam_count === 0;
  $('course-progress-label').textContent = `${percent}%`;
  $('course-progress-bar').style.width = `${percent}%`;
  $('course-progress-bar').parentElement.setAttribute('aria-valuenow', String(percent));
}

function renderEventCatalog() {
  const chips = document.querySelectorAll('[data-catalog-division]');
  if (!chips.length) return;
  if (!state.catalogDivision) {
    state.catalogDivision = ['B', 'C'].includes(state.user?.division) ? state.user.division : 'all';
  }
  chips.forEach(chip => chip.setAttribute('aria-pressed', String(chip.dataset.catalogDivision === state.catalogDivision)));
  const catalog = (state.events || [])
    .filter(event => event.category && event.season_status === 'current')
    .filter(event => state.catalogDivision === 'all' || event.division === state.catalogDivision)
    .sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
  $('event-catalog-count').textContent = catalog.length
    ? `${catalog.length} event${catalog.length === 1 ? '' : 's'}`
    : '';
  if (!catalog.length) {
    $('event-catalog-list').innerHTML = '<p class="catalog-empty">The 2026 event slate has not been imported yet. Content operations can run the catalog crawler to register it.</p>';
    return;
  }
  const groups = new Map();
  catalog.forEach(event => {
    if (!groups.has(event.category)) groups.set(event.category, []);
    groups.get(event.category).push(event);
  });
  $('event-catalog-list').innerHTML = [...groups.entries()].map(([category, events]) => `
    <section class="catalog-group">
      <h3>${escapeHtml(category)}</h3>
      <div class="catalog-grid">${events.map(event => {
        const actions = [];
        if (event.lesson_count > 0) actions.push(`<button type="button" data-open-course="${event.id}" data-course-slug="${escapeHtml(event.slug)}" class="catalog-course-link">Start Course</button>`);
        if (event.exam_count > 0) actions.push(`<button type="button" data-open-exam-event="${escapeHtml(event.slug)}" data-event-name="${escapeHtml(event.name)}" class="catalog-exam-link">Practice & Exams</button>`);
        return `<article class="catalog-event surface">
          <header><h4>${escapeHtml(event.name)}</h4><span class="division-badge">Div ${escapeHtml(event.division)}</span></header>
          ${event.topic_focus ? `<p>${escapeHtml(event.topic_focus)}</p>` : ''}
          ${(event.lesson_count > 0 || event.exam_count > 0) ? `<div class="catalog-content-badge"><span aria-hidden="true">✦</span> Grounded course &amp; exam ready</div>` : ''}
          <footer>
            ${event.official_url ? `<a href="${safeUrl(event.official_url)}" target="_blank" rel="noopener noreferrer">Official Page <span aria-hidden="true">↗</span></a>` : '<span class="catalog-pending">Link pending review</span>'}
            <div class="catalog-actions">${actions.join('') || '<span class="catalog-pending">Content in review</span>'}</div>
          </footer>
        </article>`;
      }).join('')}</div>
    </section>`).join('');
}

document.querySelectorAll('[data-catalog-division]').forEach(chip => {
  chip.addEventListener('click', () => {
    state.catalogDivision = chip.dataset.catalogDivision;
    renderEventCatalog();
  });
});

async function openEventCourse(eventId, slug, button) {
  setBusy(button, true, 'Opening…');
  try { await selectSubject(slug, 'learn'); }
  catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
}

async function openEventPractice(slug, eventName) {
  await selectSubject(slug, 'practice');
}

function renderMaterials() {
  const block = $('materials-block');
  if (!block) return;
  const items = (state.materials && state.materials.materials) || [];
  if (!items.length) { block.hidden = true; $('materials-list').innerHTML = ''; return; }
  block.hidden = false;
  $('materials-list').innerHTML = items.map(material => {
    const kind = material.media_type && material.media_type.includes('pdf') ? 'PDF' : (material.media_type ? 'HTML' : '');
    const size = material.has_text ? `${Math.round((material.text_chars || 0) / 1000)}k chars` : 'link only';
    return `<article class="material-card surface">
      <span class="material-type">${escapeHtml((material.purpose || 'reference').replaceAll('_', ' '))}</span>
      <h3>${escapeHtml(material.title || 'Material')}</h3>
      <p class="material-meta">${size}${kind ? ` · ${kind}` : ''}</p>
      <div class="material-actions">${material.has_text ? `<button type="button" class="button button-dark button-compact" data-open-material="${material.source_id}">Read</button>` : ''}${material.url ? `<a class="button button-secondary button-compact" href="${safeUrl(material.url)}" target="_blank" rel="noopener noreferrer">Source ↗</a>` : ''}</div>
    </article>`;
  }).join('');
}

async function openMaterial(sourceId) {
  try {
    const data = await api(`/materials/${sourceId}`);
    $('material-reader-title').textContent = data.title || 'Material';
    $('material-reader-meta').textContent = `${new Intl.NumberFormat(navigator.language).format(data.text_chars || 0)} characters · collected reference`;
    $('material-text').textContent = data.extracted_text || '';
    const link = $('material-source-link');
    if (data.url) { link.href = safeUrl(data.url); link.hidden = false; } else { link.hidden = true; }
    $('practice-catalog').hidden = true;
    $('practice-runner').hidden = true;
    $('material-reader').hidden = false;
    $('material-reader-title').focus();
    window.scrollTo({ top: 0, behavior: preferredScrollBehavior() });
  } catch (error) { toast(error.message); }
}

$('materials-list')?.addEventListener('click', event => {
  const button = event.target.closest('[data-open-material]');
  if (button) openMaterial(Number(button.dataset.openMaterial));
});
$('close-material')?.addEventListener('click', () => {
  $('material-reader').hidden = true;
  $('practice-catalog').hidden = false;
});

document.addEventListener('click', event => {
  const courseButton = event.target.closest('[data-open-course]');
  if (courseButton) openEventCourse(Number(courseButton.dataset.openCourse), courseButton.dataset.courseSlug, courseButton);
  const examButton = event.target.closest('[data-open-exam-event]');
  if (examButton) openEventPractice(examButton.dataset.openExamEvent, examButton.dataset.eventName);
});

function renderConcepts() {
  const event = activeEvent();
  const concepts = state.dashboard?.concepts?.filter(item => !event || item.event_id === event.id) || [];
  $('concepts-block').hidden = concepts.length === 0;
  $('concept-list').innerHTML = concepts.map((concept, index) => `<article class="concept-row">
    <span class="concept-index">${String(index + 1).padStart(2, '0')}</span><div><h3>${escapeHtml(concept.name)}</h3><p>${escapeHtml(concept.description || 'Core competition objective')}</p></div><small>${concept.mastery_probability != null ? `${Math.round(concept.mastery_probability * 100)}% mastery` : 'Ready to learn'}</small>
  </article>`).join('');
}

function studentEvents() {
  const division = state.user?.division;
  return [...state.events]
    .filter(event => event.lesson_count > 0 || event.exam_count > 0)
    .filter(event => !division || event.division === division || event.division === 'B/C' || event.slug === state.activeEventSlug)
    .sort((a, b) => {
      const aRank = a.division === division ? 0 : a.division === 'B/C' ? 1 : 2;
      const bRank = b.division === division ? 0 : b.division === 'B/C' ? 1 : 2;
      return aRank - bRank || a.name.localeCompare(b.name) || a.division.localeCompare(b.division);
    });
}

function resolveEvent(slug) {
  const exact = state.events.find(event => event.slug === slug);
  if (exact) return exact;
  const base = subjectKeyOf(slug);
  const division = (state.user?.division || '').toLowerCase();
  return state.events.find(event => event.slug === `${base}-${division}`)
    || state.events.find(event => event.slug === base)
    || null;
}

function renderEventSelectors() {
  const event = activeEvent();
  const options = studentEvents().map(item => `<option value="${escapeHtml(item.slug)}"${item.id === event?.id ? ' selected' : ''}>${escapeHtml(item.name)} · Div ${escapeHtml(item.division)}</option>`).join('');
  for (const id of ['overview-event-select', 'learn-event-select', 'practice-event-select']) $(id).innerHTML = options;
}

function renderEventContext(prefix, event, experience) {
  $(`${prefix}-event-icon`).textContent = experience.icon;
  $(`${prefix}-event-icon`).className = `event-context-icon event-accent-${experience.accent}`;
  $(`${prefix}-event-category`).textContent = experience.category;
  $(`${prefix}-event-name`).textContent = event.name;
  $(`${prefix}-event-meta`).textContent = `Division ${event.division} · ${event.season} Season`;
  const link = $(`${prefix}-official-link`);
  link.hidden = !event.official_url;
  if (event.official_url) link.href = safeUrl(event.official_url);
}

function renderSubjectShell() {
  const event = activeEvent();
  if (!event) return;
  const experience = eventExperience(event);
  const totalMinutes = state.lessons.reduce((sum, lesson) => sum + (lesson.estimated_minutes || 0), 0);
  const completed = state.lessons.filter(lesson => lesson.progress.status === 'completed').length;
  const progress = state.lessons.length ? Math.round((completed / state.lessons.length) * 100) : 0;
  const nextLesson = state.lessons.find(lesson => lesson.progress.status === 'in_progress')
    || state.lessons.find(lesson => lesson.progress.status !== 'completed')
    || state.lessons[0];
  const eventExams = state.exams.filter(exam => exam.event_id ? exam.event_id === event.id : exam.event === event.name);

  renderEventSelectors();
  renderEventContext('learn', event, experience);
  renderEventContext('practice', event, experience);
  $('learn-title').textContent = `Learn ${event.name}`;
  $('learn-lede').textContent = experience.focus;
  $('learning-path-title').textContent = `${event.name} Course`;
  $('learn-module-count').textContent = state.lessons.length;
  $('learn-duration').textContent = totalMinutes >= 60 ? `${Math.round(totalMinutes / 6) / 10} hr` : `${totalMinutes} min`;
  $('learn-progress-value').textContent = `${progress}%`;
  state.featuredLessonId = nextLesson?.id || null;
  $('featured-event-kicker').textContent = nextLesson?.progress.status === 'completed' ? 'Review Anytime' : 'Up Next';
  $('featured-lesson-title').textContent = nextLesson?.title || 'Lessons Are Being Prepared';
  $('featured-lesson-summary').textContent = nextLesson?.summary || `The ${event.name} course is currently in editorial review.`;
  $('featured-lesson-status').textContent = nextLesson ? nextLesson.progress.status.replaceAll('_', ' ') : 'In Review';
  $('featured-lesson-status').classList.toggle('attention', nextLesson?.progress.status === 'in_progress');
  $('start-featured-lesson').disabled = !nextLesson;
  $('start-featured-lesson').textContent = nextLesson?.progress.status === 'in_progress' ? 'Resume Lesson →'
    : nextLesson?.progress.status === 'completed' ? 'Review Lesson →' : 'Start Lesson →';

  $('practice-title').textContent = `${event.name} Practice`;
  $('practice-lede').textContent = `Train ${experience.skill} with feedback, station timing, and full mock exams.`;
  $('practice-set-count').textContent = state.practiceSets.length;
  $('practice-exam-count').textContent = eventExams.length;
  const taxonomyReady = subjectKeyOf(state.activeEventSlug) === 'entomology'
    && state.activeTaxonomy?.official_list_verified
    && state.activeTaxonomy?.image_release_ready;
  const scopeMessage = taxonomyReady
    ? `Current-season taxonomy and specimen assets verified · ${state.activeTaxonomy.entries.length} scoped taxa.`
    : event.season_status !== 'current' ? 'Foundational library · This course is not labeled as current-season competition coverage.' : '';
  $('subject-scope-note').hidden = !scopeMessage;
  $('subject-scope-note').textContent = scopeMessage || '';
}

async function selectSubject(slug, destination = 'learn') {
  const event = resolveEvent(slug);
  if (!event) { toast('This subject is not available yet.'); return; }
  const requestId = ++state.eventRequestId;
  for (const id of ['overview-event-select', 'learn-event-select', 'practice-event-select']) $(id).disabled = true;
  setAppLoading(true);
  const subjectKey = subjectKeyOf(event.slug);
  try {
    const [lessons, practiceSets, taxonomy, materials, dashboard] = await Promise.all([
      api(`/events/${event.id}/lessons`),
      api(`/events/${event.id}/practice-sets`).catch(() => []),
      subjectKey === 'entomology' ? api(`/events/${event.id}/taxonomy`).catch(() => null) : Promise.resolve(null),
      api(`/events/${event.id}/materials`).catch(() => ({ materials: [] })),
      api(`/student/dashboard?event_slug=${encodeURIComponent(event.slug)}`),
    ]);
    if (requestId !== state.eventRequestId) return;
    state.activeEventSlug = event.slug;
    localStorage.setItem('activeEventSlug', event.slug);
    state.lessons = lessons;
    state.practiceSets = practiceSets;
    state.activeTaxonomy = taxonomy;
    state.materials = materials;
    state.dashboard = dashboard;
    updateDashboard();
    renderSubjectShell();
    renderMaterials();
    showView(destination, false);
    $('learn-catalog').hidden = false;
    $('lesson-reader').hidden = true;
    $('practice-catalog').hidden = false;
    $('practice-runner').hidden = true;
    $('material-reader').hidden = true;
    const route = destination === 'dashboard' ? 'overview' : destination;
    const eventSuffix = ['learn', 'practice'].includes(destination) ? `?event=${encodeURIComponent(event.slug)}` : '';
    history.replaceState(null, '', `#${route}${eventSuffix}`);
  } finally {
    if (requestId === state.eventRequestId) {
      renderEventSelectors();
      for (const id of ['overview-event-select', 'learn-event-select', 'practice-event-select']) $(id).disabled = false;
      setAppLoading(false);
    }
  }
}

function renderLessons() {
  $('lessons-empty').hidden = state.lessons.length > 0;
  $('lesson-list').innerHTML = state.lessons.map((lesson, index) => {
    const statusLabel = lesson.progress.status === 'completed' ? 'Completed' : lesson.progress.status === 'in_progress' ? 'Resume' : 'Start';
    return `<article class="lesson-catalog-card surface">
      <span class="lesson-order">${String(index + 1).padStart(2, '0')}</span>
      <div class="lesson-card-copy"><span class="lesson-card-meta">${lesson.estimated_minutes} min · ${escapeHtml(lesson.progress.status.replaceAll('_', ' '))}</span><h3>${escapeHtml(lesson.title)}</h3><p>${escapeHtml(lesson.summary)}</p></div>
      <button class="button ${lesson.progress.status === 'not_started' ? 'button-dark' : 'button-secondary'}" type="button" data-start-lesson="${lesson.id}">${statusLabel} <span class="sr-only">${escapeHtml(lesson.title)}</span></button>
    </article>`;
  }).join('');
  $('start-featured-lesson').disabled = state.lessons.length === 0;
  const featured = state.lessons.find(lesson => lesson.id === state.featuredLessonId);
  $('start-featured-lesson').textContent = featured?.progress.status === 'in_progress' ? 'Resume Lesson →' : featured?.progress.status === 'completed' ? 'Review Lesson →' : 'Start Lesson →';
  const totalMin = state.lessons.reduce((sum, lesson) => sum + (lesson.estimated_minutes || 0), 0);
  const done = state.lessons.filter(lesson => lesson.progress.status === 'completed').length;
  $('course-scope').textContent = state.lessons.length
    ? `${done} of ${state.lessons.length} complete · ${totalMin >= 60 ? `~${Math.round(totalMin / 6) / 10} hr` : `${totalMin} min`}`
    : '';
}

function renderExams() {
  const event = activeEvent();
  const exams = state.exams.filter(exam => !event || (exam.event_id ? exam.event_id === event.id : exam.event === event.name));
  $('exam-empty').hidden = exams.length > 0;
  $('practice-exam-count').textContent = exams.length;
  $('exam-list').innerHTML = exams.map(exam => `<article class="exam-card surface">
    <div class="exam-card-main"><header><span class="event-label">${escapeHtml(exam.event)} · Div ${escapeHtml(exam.event_division || event?.division || '')}</span><span class="exam-badge release-${escapeHtml(exam.release_class)}">${escapeHtml(exam.release_label)}</span></header>
    <h3>${escapeHtml(exam.title)}</h3><p>${exam.release_class === 'competition_ready' ? 'Calibrated current-season simulation.' : exam.release_class === 'foundational_practice' ? 'Foundational practice with guided review.' : 'Reviewed competition-style practice.'}</p></div>
    <dl><div><dt>Questions</dt><dd>${exam.question_count}</dd></div><div><dt>Time</dt><dd>${exam.effective_duration_minutes || exam.duration_minutes} min</dd></div></dl>
    <button class="button button-dark" type="button" data-start-exam="${exam.id}">Start Exam</button>
  </article>`).join('');
  loadResultsHistory();
}

async function loadResultsHistory() {
  if (!$('results-history-list')) return;
  // Attempt history is per-user, not per-event, so it doesn't change on subject
  // switches — cache it and only refetch when invalidated (after a submit).
  if (!state.resultsHistory) {
    try { state.resultsHistory = (await api('/me/attempts')).attempts || []; }
    catch { $('results-history-block').hidden = true; return; }
  }
  {
    const rows = state.resultsHistory;
    $('results-history-block').hidden = rows.length === 0;
    $('results-history-list').innerHTML = rows.map(a => {
      const pct = a.ratio == null ? '—' : `${Math.round(a.ratio * 100)}%`;
      return `<article class="result-row surface">
        <div class="result-meta"><strong>${escapeHtml(a.exam_title)}</strong><small>${escapeHtml(a.event)} · ${escapeHtml(formatDate(a.submitted_at))}</small></div>
        <div class="result-score"><span class="result-pct">${pct}</span><small>${a.score ?? 0} / ${a.max_score ?? 0} pts</small></div>
        <button class="button button-secondary" type="button" data-review-attempt="${a.attempt_id}" data-score="${a.score ?? 0}" data-max="${a.max_score ?? 0}">Review</button>
      </article>`;
    }).join('');
  }
}

$('results-history-list').addEventListener('click', event => {
  const btn = event.target.closest('[data-review-attempt]');
  if (!btn) return;
  loadReview(Number(btn.dataset.reviewAttempt),
    { score: Number(btn.dataset.score), max_score: Number(btn.dataset.max) })
    .catch(error => toast(error.message));
});

async function generateMockExam() {
  const event = activeEvent();
  if (!event) { toast('Pick a subject first, then generate a mock exam.'); return; }
  const button = $('generate-mock');
  setBusy(button, true, 'Building your exam…');
  try {
    const created = await api('/exams/mock', {
      method: 'POST', body: JSON.stringify({ event_id: event.id, size: 20 }),
    });
    toast(`New mock exam ready — ${created.question_count} questions.`);
    await startExam(created.exam_id);
  } catch (error) {
    toast(error.status === 409
      ? 'No question pool for this event yet — try one with imported materials.'
      : error.message);
  } finally { setBusy(button, false); }
}

$('generate-mock')?.addEventListener('click', generateMockExam);

function renderPracticeLab() {
  const experience = eventExperience();
  $('practice-set-count').textContent = state.practiceSets.length;
  $('practice-sets-empty').hidden = state.practiceSets.length > 0;
  const multiplier = state.accommodation?.time_multiplier || 1;
  const stationSeconds = Math.ceil(45 * multiplier);
  $('practice-set-list').innerHTML = state.practiceSets.map((practiceSet, index) => {
    const latest = practiceSet.latest_session;
    const studyLabel = latest?.status === 'in_progress' && latest.mode === 'study' ? 'Resume Study' : 'Study Mode';
    const sprintLabel = latest?.status === 'in_progress' && latest.mode === 'station'
      ? 'Resume Sprint' : `Station · ${stationSeconds}s`;
    return `<article class="practice-set-card surface event-accent-${experience.accent}">
      <div class="practice-set-number" aria-hidden="true">${String(index + 1).padStart(2, '0')}</div>
      <div class="practice-set-copy"><span>${escapeHtml(practiceSet.practice_type.replaceAll('_', ' '))} · ${practiceSet.estimated_minutes} min</span><h3>${escapeHtml(practiceSet.title)}</h3><p>${escapeHtml(practiceSet.summary)}</p></div>
      <div class="practice-set-actions"><button class="button button-primary" type="button" data-start-practice-set="${practiceSet.id}" data-practice-mode="study">${studyLabel}</button><button class="button button-secondary" type="button" data-start-practice-set="${practiceSet.id}" data-practice-mode="station">${sprintLabel}</button></div>
    </article>`;
  }).join('');
}

function renderNotebook() {
  const cases = state.dashboard?.open_remediation || [];
  $('error-empty').hidden = cases.length > 0;
  $('error-notebook-list').innerHTML = cases.map(item => {
    const diagnosis = item.diagnosis || {};
    const plan = item.plan || {};
    const due = item.next_review_at ? new Date(item.next_review_at) : null;
    const isDue = due && due.getTime() <= Date.now();
    const evidence = (diagnosis.evidence_profile || []).map(property => `<li><span>${escapeHtml(property.label)}</span><strong>${escapeHtml(property.value)}</strong></li>`).join('');
    let action = '';
    if (item.status === 'delayed_review') {
      action = isDue
        ? `<button class="button button-primary" type="button" data-start-delayed="${item.id}">Start Retention Check</button>`
        : `<p class="repair-scheduled">Recheck scheduled for <strong>${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(due)}</strong>. Your first correction is holding for now.</p>`;
    } else if (item.status === 'delayed_check_in_progress') {
      action = `<button class="button button-primary" type="button" data-start-delayed="${item.id}">Resume Retention Check</button>`;
    } else if (item.student_reflection) {
      action = `<button class="button button-primary" type="button" data-start-transfer="${item.id}">Start Unseen Transfer Check</button>`;
    } else {
      action = `<label for="notebook-reflection-${item.id}"><strong>Which clue should drive your next decision—and why?</strong></label><textarea id="notebook-reflection-${item.id}" rows="4" minlength="10" placeholder="Example: I should test hardness before relying on color…">${escapeHtml(item.student_reflection || '')}</textarea><button class="button button-dark" type="button" data-save-reflection="${item.id}">Save Reflection & Continue</button>`;
    }
    return `<article class="remediation repair-card surface" data-case-id="${item.id}"><header><div><span class="remediation-step">${escapeHtml(item.source_type === 'practice' ? 'Evidence Lab' : 'Mock Exam')} · ${escapeHtml(item.status.replaceAll('_', ' '))}</span><h2>${escapeHtml(item.error_type.replaceAll('_', ' '))}</h2></div><span class="repair-case-number">Case ${item.id}</span></header><p class="repair-prompt">${escapeHtml(item.question_stem || 'Review the original problem and identify the evidence that changes the answer.')}</p>${evidence ? `<ul class="repair-evidence" aria-label="Evidence from the original problem">${evidence}</ul>` : ''}<div class="repair-explanation"><p class="kicker">Coach’s correction</p><p>${escapeHtml(plan.explanation || item.next_action || 'Rebuild the reasoning, then prove it on an unseen problem.')}</p></div><div class="repair-action">${action}<button class="button button-secondary" type="button" data-open-tutor="remediation" data-tutor-context-id="${item.id}">Get a Grounded Hint</button><div class="case-status" data-case-status aria-live="polite"></div></div></article>`;
  }).join('');
}

function updateDashboard() {
  const firstName = (state.user.full_name || 'Competitor').split(' ')[0];
  $('welcome').textContent = `Ready, ${firstName}?`;
  $('sidebar-name').textContent = state.user.full_name;
  $('sidebar-division').textContent = `Division ${state.user.division || 'B'}`;
  $('user-initials').textContent = initials(state.user.full_name);
  const openCases = state.dashboard?.open_remediation || [];
  const mastery = state.dashboard?.concepts || [];
  const dailyPlan = state.dashboard?.daily_plan || { items: [], signals: {}, total_estimated_minutes: 0 };
  $('open-error-count').textContent = openCases.length;
  $('nav-error-count').textContent = openCases.length;
  $('mastery-count').textContent = mastery.filter(item => item.evidence_count > 0).length;
  $('assignment-count').textContent = dailyPlan.items.length;
  $('mission-minutes').textContent = dailyPlan.total_estimated_minutes;
  $('mission-active-days').textContent = dailyPlan.signals.active_days_last_7 || 0;
  $('mission-due-reviews').textContent = dailyPlan.signals.due_reviews || 0;
  $('mission-pending-assignments').textContent = dailyPlan.signals.pending_assignments || 0;
  $('mission-summary').textContent = dailyPlan.items.length
    ? `${dailyPlan.items.length} focused step${dailyPlan.items.length === 1 ? '' : 's'}, ordered by learning value and urgency.`
    : 'No required work is waiting. Choose a subject when you want to explore.';
  $('daily-plan-empty').hidden = dailyPlan.items.length > 0;
  const missionIcons = { remediation: '↻', assignment: '◷', spaced_review: '◎', lesson: '◇', timed_drill: '⌁' };
  $('daily-plan-list').innerHTML = dailyPlan.items.map((item, index) => {
    const action = item.exam_id
      ? `<button class="button button-dark" type="button" data-start-exam="${item.exam_id}">${escapeHtml(item.action_label)}</button>`
      : `<a class="button button-dark" href="${escapeHtml(item.route)}" data-mission-action="${index}">${escapeHtml(item.action_label)}</a>`;
    return `<li class="mission-item urgency-${escapeHtml(item.urgency)}"><span class="mission-item-icon" aria-hidden="true">${missionIcons[item.type] || '◇'}</span><div><span class="mission-order">Step ${index + 1} · ${escapeHtml(item.type.replaceAll('_', ' '))}</span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.summary)}</p><small><strong>Why now:</strong> ${escapeHtml(item.why)}</small></div><div class="mission-item-action"><span>${item.estimated_minutes} min</span>${action}</div></li>`;
  }).join('');
  const primary = dailyPlan.items[0];
  delete $('continue-button').dataset.startExam;
  delete $('continue-button').dataset.missionIndex;
  if (primary) {
    $('continue-button').textContent = `${primary.action_label} →`;
    if (primary.exam_id) $('continue-button').dataset.startExam = primary.exam_id;
    else $('continue-button').dataset.missionIndex = '0';
  } else {
    $('continue-button').textContent = 'Explore Learning Path →';
  }
  renderSubjects();
  renderOverviewEvent();
  renderEventCatalog();
  renderConcepts();
  renderLessons();
  renderExams();
  renderPracticeLab();
  renderNotebook();
}

function formatDate(value) {
  if (!value) return 'No due date';
  return new Intl.DateTimeFormat(navigator.language, {
    month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(new Date(value));
}

function renderNotifications() {
  $('notification-count').textContent = state.unreadNotifications > 99 ? '99+' : state.unreadNotifications;
  $('notification-count').hidden = state.unreadNotifications === 0;
  $('notifications-button').setAttribute('aria-label', state.unreadNotifications
    ? `Open notifications, ${state.unreadNotifications} unread`
    : 'Open notifications');
  $('notification-empty').hidden = state.notifications.length > 0;
  $('mark-notifications-read').hidden = state.unreadNotifications === 0;
  $('notification-list').innerHTML = state.notifications.map(notification => `<article class="notification-item${notification.read ? '' : ' unread'}"><a href="${safeActionUrl(notification.action_url || '#overview')}" data-notification-id="${notification.id}"><span class="notification-dot" aria-hidden="true"></span><span><strong>${escapeHtml(notification.title)}</strong><span>${escapeHtml(notification.body)}</span><time datetime="${escapeHtml(notification.created_at)}">${escapeHtml(formatDate(notification.created_at))}</time></span></a></article>`).join('');
}

async function loadNotifications() {
  const result = await api('/notifications');
  state.notifications = result.notifications;
  state.unreadNotifications = result.unread_count;
  $('notifications-button').hidden = false;
  renderNotifications();
}

function tutorWelcome() {
  $('tutor-messages').innerHTML = '<div class="tutor-welcome"><span aria-hidden="true">✦</span><h3>Start With Your Thinking</h3><p>Ask about the lesson evidence or your error-repair case. The tutor will cite the reviewed sources it uses.</p></div>';
}

function closeTutor() {
  $('tutor-panel').hidden = true;
  document.body.classList.remove('tutor-open');
}

function openTutor(contextType, contextId) {
  const changed = !state.tutorContext
    || state.tutorContext.type !== contextType
    || state.tutorContext.id !== contextId;
  if (changed) {
    state.tutorContext = { type: contextType, id: contextId };
    state.tutorSession = null;
    $('tutor-mode').value = contextType === 'remediation' ? 'diagnose_error' : 'socratic_hint';
    tutorWelcome();
    $('tutor-status').textContent = '';
  }
  $('tutor-panel').hidden = false;
  document.body.classList.add('tutor-open');
  $('tutor-title').focus();
}

function appendTutorMessage(message) {
  const welcome = $('tutor-messages').querySelector('.tutor-welcome');
  if (welcome) welcome.remove();
  const article = document.createElement('article');
  article.className = `tutor-message ${message.role}`;
  const citations = (message.citations || []).map(citation => `<details class="tutor-citation"><summary>Verified Source · ${escapeHtml(citation.source_title)}</summary><blockquote>${escapeHtml(citation.evidence_excerpt)}</blockquote><p>${escapeHtml(citation.locator)}</p><a href="${safeUrl(citation.source_url)}" target="_blank" rel="noopener noreferrer">Open Source <span aria-hidden="true">↗</span></a><small translate="no">Snapshot ${escapeHtml(citation.snapshot_hash.slice(0, 12))}</small></details>`).join('');
  article.innerHTML = `<span class="tutor-speaker">${message.role === 'assistant' ? 'Fieldstone Tutor' : 'You'}</span><p>${escapeHtml(message.content).replaceAll('\n', '<br>')}</p>${citations}${message.role === 'assistant' ? `<span class="tutor-verified"><span aria-hidden="true">✓</span> ${message.verification?.uncertainty === 'verified' ? 'Verified grounding' : 'Grounded guidance'}</span>` : ''}`;
  $('tutor-messages').append(article);
}

async function sendTutorMessage(message, button) {
  setBusy(button, true, 'Checking Sources…');
  $('tutor-status').textContent = '';
  try {
    if (!state.tutorSession) {
      state.tutorSession = await api('/tutor/sessions', {
        method: 'POST', body: JSON.stringify({
          context_type: state.tutorContext.type, context_id: state.tutorContext.id,
          mode: $('tutor-mode').value,
        }),
      });
    }
    appendTutorMessage({ role: 'user', content: message, citations: [] });
    const reply = await api(`/tutor/sessions/${state.tutorSession.id}/messages`, {
      method: 'POST', body: JSON.stringify({ message }),
    });
    appendTutorMessage(reply);
    $('tutor-input').value = '';
    $('tutor-status').textContent = 'Response checked against approved source claims.';
  } catch (error) { $('tutor-status').textContent = error.message; }
  finally { setBusy(button, false); }
}

function configureRoleNavigation() {
  const mode = ['admin', 'editor', 'sme', 'calibrator'].includes(state.user.role) ? 'content'
    : state.user.role === 'coach' ? 'coach' : 'student';
  document.querySelectorAll('[data-student-nav]').forEach(item => { item.hidden = mode !== 'student'; });
  document.querySelectorAll('[data-coach-nav]').forEach(item => { item.hidden = mode !== 'coach'; });
  document.querySelectorAll('[data-content-nav]').forEach(item => { item.hidden = mode !== 'content'; });
  $('sidebar-name').textContent = state.user.full_name;
  $('sidebar-division').textContent = mode === 'content' ? 'Content operations'
    : mode === 'coach' ? 'Coach workspace' : `Division ${state.user.division || 'B'}`;
  $('user-initials').textContent = initials(state.user.full_name);
  return mode;
}

function renderSourceCoverage() {
  const cards = state.sourceCoverage;
  const totals = cards.reduce((sum, card) => ({
    mapped: sum.mapped + card.summary.mapped_sources,
    required: sum.required + card.summary.required_sources,
    monitored: sum.monitored + card.summary.monitored_required_sources,
  }), { mapped: 0, required: 0, monitored: 0 });
  $('coverage-mapped').textContent = totals.mapped;
  $('coverage-required').textContent = totals.required;
  $('coverage-monitored').textContent = totals.monitored;
  const unmappedEvents = cards.filter(card => card.summary.mapped_sources === 0).length;
  $('coverage-gaps').textContent = Math.max(0, totals.required - totals.monitored) + unmappedEvents;
  $('coverage-empty').hidden = cards.length > 0;
  $('coverage-scorecards').innerHTML = cards.map(card => {
    const percent = Math.round(card.summary.coverage_ratio * 100);
    const currentLabel = card.event.season_status === 'current' ? 'Current season' : `${card.event.season_status} library`;
    const sourceRows = card.sources.length ? card.sources.map(source => `<details class="coverage-source"><summary><span class="coverage-state state-${escapeHtml(source.coverage_state)}">${escapeHtml(source.coverage_state)}</span><span><strong>${escapeHtml(source.title)}</strong><small>Tier ${source.source_tier} · ${escapeHtml(source.purpose.replaceAll('_', ' '))}</small></span><span class="coverage-gap-count">${source.coverage_state === 'monitored' ? 'Complete' : source.missing_artifact_types.length ? `${source.missing_artifact_types.length} artifact gap${source.missing_artifact_types.length === 1 ? '' : 's'}` : 'Monitoring gap'}</span></summary><div class="coverage-source-detail"><dl><div><dt>Rights</dt><dd>${escapeHtml(source.rights_status.replaceAll('_', ' '))}</dd></div><div><dt>Crawl health</dt><dd>${escapeHtml(source.crawl_status)}</dd></div><div><dt>Metadata checks</dt><dd>${source.metadata_check_count}</dd></div><div><dt>Snapshots</dt><dd>${source.snapshot_count}</dd></div><div><dt>Approved claims</dt><dd>${source.approved_claim_count}</dd></div></dl><p><strong>Missing:</strong> ${source.missing_artifact_types.length ? escapeHtml(source.missing_artifact_types.join(', ').replaceAll('_', ' ')) : source.coverage_state === 'monitored' ? 'Nothing required' : 'Freshness monitoring or review is incomplete'}</p><p><strong>Owner:</strong> ${escapeHtml(source.coverage_owner)}</p><a href="${safeUrl(source.url)}" target="_blank" rel="noopener noreferrer">Open Registered Source <span aria-hidden="true">↗</span></a></div></details>`).join('') : '<div class="coverage-unmapped"><strong>Source universe missing</strong><p>No reviewed source map exists. Coverage is unknown and this event cannot be release-ready.</p></div>';
    return `<article class="coverage-card surface"><header><div><span class="coverage-season">${escapeHtml(String(card.event.season))} · ${escapeHtml(currentLabel)}</span><h2>${escapeHtml(card.event.name)}</h2></div><span class="coverage-release ${card.summary.competition_release_ready ? 'ready' : 'blocked'}">${card.summary.competition_release_ready ? 'Release Ready' : card.summary.mapped_sources ? 'Gaps Open' : 'Unknown Coverage'}</span></header><div class="coverage-progress"><div><span>Required-source monitoring</span><strong>${card.summary.monitored_required_sources}/${card.summary.required_sources}</strong></div><div class="progress-track" aria-label="${percent}% of required sources monitored"><span style="width:${percent}%"></span></div></div><div class="coverage-source-list">${sourceRows}</div></article>`;
  }).join('');
}

async function loadSourceCoverage(button = null) {
  setBusy(button, true, 'Refreshing Coverage…');
  try {
    const result = await api('/content/source-coverage');
    state.sourceCoverage = result.scorecards;
    renderSourceCoverage();
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
}

const reviewChecks = {
  editor: ['clear_language', 'single_best_answer', 'distractors_plausible', 'age_appropriate', 'original_wording'],
  sme: ['factually_supported', 'answer_key_verified', 'citations_verified', 'no_material_ambiguity'],
};

function renderQuestionReviewQueue() {
  const questions = state.questionReviewQueue;
  $('editorial-count').textContent = `${questions.length} Item${questions.length === 1 ? '' : 's'}`;
  $('question-review-empty').hidden = questions.length > 0;
  $('question-review-queue').innerHTML = questions.map(question => {
    const stage = question.status === 'machine_validated' ? 'editor' : question.status === 'editor_reviewed' ? 'sme' : 'publish';
    const canReview = stage === 'editor' ? ['editor', 'admin'].includes(state.user.role) : stage === 'sme' ? ['sme', 'admin'].includes(state.user.role) : false;
    const correct = question.choices[question.answer_spec.correct_index] || 'Answer key unavailable';
    const citations = question.citation_evidence?.length ? question.citation_evidence.map(citation => `<article class="citation-evidence"><header><strong>${escapeHtml(citation.source_title)}</strong><span>${citation.approved && citation.snapshot_id ? 'Verified Snapshot' : 'Evidence Gap'}</span></header><p>${escapeHtml(citation.claim_text || 'Claim unavailable')}</p><blockquote>${escapeHtml(citation.evidence_excerpt || 'No evidence excerpt supplied.')}</blockquote><footer><span>${escapeHtml(citation.locator || 'No locator')}</span>${citation.source_url ? `<a href="${safeUrl(citation.source_url)}" target="_blank" rel="noopener noreferrer">Open Source <span aria-hidden="true">↗</span></a>` : ''}</footer><small translate="no">Snapshot ${escapeHtml((citation.snapshot_hash || 'missing').slice(0, 12))}</small></article>`).join('') : '<p class="citation-missing">No source evidence is attached. Publication will remain blocked.</p>';
    const checks = canReview ? reviewChecks[stage].map(check => `<label class="review-check"><input type="checkbox" name="${escapeHtml(check)}"><span>${escapeHtml(check.replaceAll('_', ' '))}</span></label>`).join('') : '';
    let actions = '<p class="review-waiting">Waiting for the next independent review role.</p>';
    if (canReview) actions = `<fieldset class="review-checklist"><legend>${stage === 'editor' ? 'Editorial checklist' : 'Scientific checklist'}</legend>${checks}</fieldset><label class="review-notes">Review Notes<textarea name="review-notes" rows="3" maxlength="4000" placeholder="Record evidence, ambiguity, or revision guidance…"></textarea></label><div class="review-actions"><button class="button button-secondary" type="button" data-review-decision="rewrite_required" data-question-id="${question.id}" data-review-stage="${stage}">Request Rewrite</button><button class="button button-primary" type="button" data-review-decision="approved" data-question-id="${question.id}" data-review-stage="${stage}">Approve ${stage === 'editor' ? 'Editorial Review' : 'Scientific Review'}</button></div>`;
    else if (stage === 'publish' && ['sme', 'admin'].includes(state.user.role)) actions = `<div class="review-actions"><button class="button button-primary" type="button" data-publish-question="${question.id}">Publish Question</button></div>`;
    return `<article class="question-review-card surface" data-question-card="${question.id}"><header><div><span class="coverage-season">Version ${question.version}</span><h3>${escapeHtml(question.stem)}</h3></div><span class="coverage-release ${stage === 'publish' ? 'ready' : 'blocked'}">${escapeHtml(question.status.replaceAll('_', ' '))}</span></header><ol class="review-choices">${question.choices.map((choice, index) => `<li${index === question.answer_spec.correct_index ? ' class="correct"' : ''}>${escapeHtml(choice)}</li>`).join('')}</ol><details><summary>Answer, Rationale & Quality Signals</summary><div class="review-evidence"><p><strong>Key:</strong> ${escapeHtml(correct)}</p><p>${escapeHtml(question.explanation || 'No rationale supplied.')}</p><p><strong>Validation:</strong> ${question.validation_report.passed ? 'Passed' : 'Blocked'} · <strong>Similarity:</strong> ${escapeHtml((question.similarity_report || {}).outcome || 'Not calculated')} · <strong>Citations:</strong> ${question.citations.length}</p><div class="citation-evidence-list">${citations}</div></div></details>${actions}<div class="review-status" aria-live="polite"></div></article>`;
  }).join('');
}

const percentFormatter = new Intl.NumberFormat(navigator.language, { style: 'percent', maximumFractionDigits: 1 });
const decimalFormatter = new Intl.NumberFormat(navigator.language, { maximumFractionDigits: 2 });

function renderCalibrationQueue() {
  const candidates = state.calibrationQueue;
  $('calibration-count').textContent = `${candidates.length} Item${candidates.length === 1 ? '' : 's'}`;
  $('calibration-empty').hidden = candidates.length > 0;
  $('calibration-queue').innerHTML = candidates.map(candidate => {
    const metrics = candidate.metrics;
    const canDecide = ['calibrator', 'admin'].includes(state.user.role);
    const failures = candidate.failures.length ? `<ul class="calibration-failures">${candidate.failures.map(failure => `<li>${escapeHtml(failure.replaceAll('_', ' '))}</li>`).join('')}</ul>` : '<p class="calibration-pass">Every deterministic pilot threshold passed.</p>';
    const actions = canDecide ? `<label class="review-notes">Calibration Notes<textarea name="calibration-notes" rows="3" minlength="10" maxlength="4000" autocomplete="off" placeholder="Record cohort quality, anomalies, and your release rationale…"></textarea></label><div class="review-actions"><button class="button button-secondary" type="button" data-calibration-decision="rejected" data-question-id="${candidate.id}">Reject Calibration</button><button class="button button-primary" type="button" data-calibration-decision="accepted" data-question-id="${candidate.id}" ${candidate.passed ? '' : 'disabled'}>Accept Calibration</button></div>` : '<p class="review-waiting">A separate calibrator must record the decision.</p>';
    return `<article class="calibration-card surface" data-calibration-card="${candidate.id}"><header><div><span class="coverage-season">Version ${candidate.version}</span><h3>${escapeHtml(candidate.stem)}</h3></div><span class="coverage-release ${candidate.passed ? 'ready' : 'blocked'}">${candidate.passed ? 'Thresholds Passed' : 'Pilot Evidence Incomplete'}</span></header><dl class="calibration-metrics"><div><dt>Unique Students</dt><dd>${metrics.sample_size}</dd><small>Minimum ${candidate.thresholds.minimum_unique_students}</small></div><div><dt>Facility</dt><dd>${percentFormatter.format(metrics.facility)}</dd><small>${percentFormatter.format(candidate.thresholds.minimum_facility)}–${percentFormatter.format(candidate.thresholds.maximum_facility)}</small></div><div><dt>Discrimination</dt><dd>${decimalFormatter.format(metrics.corrected_item_total_discrimination)}</dd><small>Minimum ${decimalFormatter.format(candidate.thresholds.minimum_discrimination)}</small></div><div><dt>Omissions</dt><dd>${percentFormatter.format(metrics.omission_rate)}</dd><small>Maximum ${percentFormatter.format(candidate.thresholds.maximum_omission_rate)}</small></div><div><dt>Median Time</dt><dd>${metrics.median_response_seconds == null ? '—' : `${metrics.median_response_seconds} s`}</dd><small>Answered responses</small></div><div><dt>Division Data</dt><dd>${percentFormatter.format(metrics.division_representation)}</dd><small>${Object.entries(metrics.division_counts).map(([division, count]) => `${escapeHtml(division)}: ${count}`).join(' · ') || 'None'}</small></div></dl><details><summary>Option & Confidence Signals</summary><div class="calibration-detail"><p><strong>Option selections:</strong> ${Object.entries(metrics.option_counts).map(([option, count]) => `${String.fromCharCode(65 + Number(option))}: ${count}`).join(' · ') || 'No responses'}</p><p><strong>Mean confidence:</strong> Correct ${metrics.mean_confidence_correct ?? '—'} · Incorrect ${metrics.mean_confidence_incorrect ?? '—'}</p><p><strong>Sampling policy:</strong> First scored exposure per student.</p></div></details>${failures}${actions}<div class="review-status" aria-live="polite"></div></article>`;
  }).join('');
}

function renderContentChallengeQueue() {
  const challenges = state.contentChallenges;
  const openCount = challenges.filter(challenge => ['submitted', 'triaged'].includes(challenge.status)).length;
  $('challenge-ops-count').textContent = `${openCount} Open`;
  $('content-challenge-empty').hidden = challenges.length > 0;
  $('content-challenge-queue').innerHTML = challenges.map(challenge => {
    const canTriage = challenge.status === 'submitted' && ['editor', 'sme', 'admin'].includes(state.user.role);
    const canResolve = challenge.status === 'triaged' && state.user.role === 'admin';
    const choices = challenge.choices.map((choice, index) => `<li${index === challenge.original_answer_spec.correct_index ? ' class="original-key"' : ''}>${String.fromCharCode(65 + index)}. ${escapeHtml(choice)}</li>`).join('');
    let workflow = '';
    if (canTriage) workflow = `<form class="challenge-triage-form"><label>Severity<select name="severity" required><option value="low">Low · Monitor</option><option value="medium">Medium · Prompt Review</option><option value="high">High · Pause Item & Exams</option><option value="critical">Critical · Immediate Hold</option></select></label><label class="challenge-notes">Triage Notes<textarea name="notes" rows="3" minlength="10" maxlength="4000" autocomplete="off" placeholder="Record the initial evidence and urgency…" required></textarea></label><button class="button button-primary" type="submit">Record Triage Decision</button></form>`;
    else if (canResolve) workflow = `<form class="challenge-resolution-form"><div class="challenge-form-grid"><label>Decision<select name="decision" required><option value="upheld">Uphold Challenge</option><option value="not_upheld">Do Not Uphold</option></select></label><label>Score Action<select name="correction_type" required><option value="exclude_item">Exclude Item</option><option value="correct_key">Correct Answer Key</option><option value="no_score_change">No Score Change</option></select></label><label>Corrected Key<select name="correct_index"><option value="">Not Applicable</option>${challenge.choices.map((choice, index) => `<option value="${index}">${String.fromCharCode(65 + index)} · ${escapeHtml(choice)}</option>`).join('')}</select></label></div><label>Student-Facing Correction Note<textarea name="public_note" rows="3" minlength="20" maxlength="4000" autocomplete="off" placeholder="Explain the decision and any score or learning impact…" required></textarea></label><label>Internal Review Note<textarea name="internal_note" rows="3" minlength="10" maxlength="4000" autocomplete="off" placeholder="Record the evidence, reviewers, and reproduction steps…" required></textarea></label><button class="button button-primary" type="submit">Resolve & Apply Impact</button></form>`;
    else if (challenge.resolution?.public_note) workflow = `<div class="challenge-resolution-note"><strong>${challenge.status === 'upheld' ? 'Correction Published' : 'Review Complete'}</strong><p>${escapeHtml(challenge.resolution.public_note)}</p>${challenge.resolution.impact ? `<small>${challenge.resolution.impact.changed_scores} score${challenge.resolution.impact.changed_scores === 1 ? '' : 's'} changed · ${challenge.resolution.impact.voided_remediation_cases} remediation case${challenge.resolution.impact.voided_remediation_cases === 1 ? '' : 's'} voided</small>` : ''}</div>`;
    else workflow = '<p class="review-waiting">Waiting for an authorized staff member to complete the next step.</p>';
    return `<article class="content-challenge-card surface" data-content-challenge="${challenge.id}"><header><div><span class="coverage-season">Question ${challenge.question_id} · Version ${challenge.question_version} · ${challenge.report_count_for_version} Report${challenge.report_count_for_version === 1 ? '' : 's'}</span><h3>${escapeHtml(challenge.stem)}</h3></div><span class="challenge-status status-${escapeHtml(challenge.status)}">${escapeHtml(challenge.status.replaceAll('_', ' '))}</span></header><div class="challenge-summary"><span>${escapeHtml(challenge.category.replaceAll('_', ' '))}</span>${challenge.severity ? `<span>${escapeHtml(challenge.severity)} severity</span>` : ''}</div><blockquote>${escapeHtml(challenge.description)}</blockquote><details><summary>Original Choices & Key</summary><ol class="challenge-choices">${choices}</ol></details>${workflow}<p class="review-status" role="status" aria-live="polite"></p></article>`;
  }).join('');
}

async function loadContentOperations(button = null) {
  setBusy(button, true, 'Refreshing Workspace…');
  try {
    const [coverage, queue, calibration, challenges] = await Promise.all([api('/content/source-coverage'), api('/content/questions/review-queue'), api('/content/questions/calibration-queue'), api('/content/challenges')]);
    state.sourceCoverage = coverage.scorecards;
    state.questionReviewQueue = queue;
    state.calibrationQueue = calibration;
    state.contentChallenges = challenges;
    renderSourceCoverage();
    renderQuestionReviewQueue();
    renderCalibrationQueue();
    renderContentChallengeQueue();
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
  if (state.user.role === 'admin') { $('people-workspace').hidden = false; loadPeople(); }
  $('answerkey-workspace').hidden = false; loadAnswerKeys();
}

async function loadAnswerKeys() {
  try {
    const data = await api('/content/questions/needs-key?limit=50');
    const rows = data.questions || [];
    $('answerkey-count').textContent = `${data.total} Item${data.total === 1 ? '' : 's'}`;
    $('answerkey-empty').hidden = rows.length > 0;
    $('answerkey-list').innerHTML = rows.map(q => `<article class="answerkey-item surface" data-answerkey="${q.id}">
      <p class="answerkey-event">${escapeHtml(q.event)}</p>
      <p class="answerkey-stem">${escapeHtml(q.stem)}</p>
      <div class="answerkey-fields">
        <label>Correct answer<input type="text" data-ak-answer autocomplete="off" placeholder="e.g. Extrusive"></label>
        <label>Also accept <small>(comma-separated)</small><input type="text" data-ak-accepted autocomplete="off" placeholder="optional synonyms"></label>
      </div>
      <button class="button button-primary" type="button" data-ak-save="${q.id}">Save Key</button>
    </article>`).join('');
  } catch (error) { toast(error.message); }
}

async function saveAnswerKey(questionId, button) {
  const item = button.closest('[data-answerkey]');
  const answer = item.querySelector('[data-ak-answer]').value.trim();
  if (!answer) { toast('Enter the correct answer first.'); return; }
  const accepted = item.querySelector('[data-ak-accepted]').value.split(',').map(s => s.trim()).filter(Boolean);
  setBusy(button, true, 'Saving…');
  try {
    await api(`/content/questions/${questionId}/answer-key`, { method: 'PATCH', body: JSON.stringify({ answer, accepted }) });
    item.remove();
    const remaining = $('answerkey-list').children.length;
    $('answerkey-empty').hidden = remaining > 0;
    const count = $('answerkey-count');
    const n = Math.max(0, (parseInt(count.textContent, 10) || 1) - 1);
    count.textContent = `${n} Item${n === 1 ? '' : 's'}`;
    toast('Answer key saved.');
  } catch (error) { toast(error.message); setBusy(button, false); }
}

$('answerkey-list').addEventListener('click', event => {
  const save = event.target.closest('[data-ak-save]');
  if (save) saveAnswerKey(Number(save.dataset.akSave), save);
});

const ROLE_OPTIONS = ['student', 'coach', 'editor', 'sme', 'calibrator', 'admin'];

async function loadPeople() {
  const q = $('people-search').value.trim();
  const role = $('people-role-filter').value;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (role) params.set('role', role);
  try {
    const data = await api(`/admin/users?${params.toString()}`);
    state.people = data.users;
    $('people-count').textContent = `${data.total} User${data.total === 1 ? '' : 's'}`;
    renderPeople();
  } catch (error) { toast(error.message); }
}

function renderPeople() {
  const rows = state.people || [];
  $('people-empty').hidden = rows.length > 0;
  $('people-list').innerHTML = rows.map(u => `<article class="person-row surface${u.is_active ? '' : ' inactive'}">
    <div class="person-id"><span class="avatar" aria-hidden="true">${initials(u.full_name)}</span><div><strong>${escapeHtml(u.full_name || '—')}</strong><small translate="no">${escapeHtml(u.email)}</small></div></div>
    <label class="person-role"><span class="sr-only">Role for ${escapeHtml(u.email)}</span>
      <select data-user-role="${u.id}">${ROLE_OPTIONS.map(r => `<option value="${r}"${r === u.role ? ' selected' : ''}>${r.charAt(0).toUpperCase() + r.slice(1)}</option>`).join('')}</select></label>
    <button class="button ${u.is_active ? 'button-secondary' : 'button-primary'} person-active" type="button" data-user-active="${u.id}" data-next="${u.is_active ? 'false' : 'true'}">${u.is_active ? 'Active' : 'Reactivate'}</button>
  </article>`).join('');
}

async function updatePerson(userId, body) {
  try {
    const updated = await api(`/admin/users/${userId}`, { method: 'PATCH', body: JSON.stringify(body) });
    state.people = (state.people || []).map(u => u.id === updated.id ? updated : u);
    renderPeople();
    toast(`Updated ${updated.full_name || updated.email}.`);
  } catch (error) { toast(error.message); loadPeople(); }
}

let peopleSearchTimer = null;
$('people-search').addEventListener('input', () => { clearTimeout(peopleSearchTimer); peopleSearchTimer = setTimeout(loadPeople, 250); });
$('people-role-filter').addEventListener('change', loadPeople);
$('people-list').addEventListener('change', event => {
  const roleSelect = event.target.closest('[data-user-role]');
  if (roleSelect) updatePerson(Number(roleSelect.dataset.userRole), { role: roleSelect.value });
});
$('people-list').addEventListener('click', event => {
  const toggle = event.target.closest('[data-user-active]');
  if (toggle) updatePerson(Number(toggle.dataset.userActive), { is_active: toggle.dataset.next === 'true' });
});

function renderCoachDashboard() {
  const dashboard = state.coachDashboard;
  $('coach-title').textContent = `Welcome, ${(state.user.full_name || 'Coach').split(' ')[0]}`;
  $('coach-student-count').textContent = dashboard.students;
  $('coach-completion-rate').textContent = `${Math.round(dashboard.completion_rate * 100)}%`;
  $('coach-error-count').textContent = dashboard.open_remediation_cases;
  $('coach-score').textContent = dashboard.average_score_ratio == null ? '—' : `${Math.round(dashboard.average_score_ratio * 100)}%`;
  $('coach-student-empty').hidden = dashboard.student_rows.length > 0;
  $('coach-student-rows').innerHTML = dashboard.student_rows.map(student => `<tr>
    <td><div class="student-cell"><span class="avatar" aria-hidden="true">${initials(student.full_name)}</span><div><strong>${escapeHtml(student.full_name)}</strong><small>Division ${escapeHtml(student.division || '—')}</small></div></div></td>
    <td>${student.completed_assignments} / ${student.total_assignments}</td>
    <td>${student.average_score_ratio == null ? '—' : `${Math.round(student.average_score_ratio * 100)}%`}</td>
    <td>${student.open_remediation_cases}</td>
    <td><span class="status-pill${student.attention ? ' attention' : ''}">${student.attention ? 'Needs attention' : 'On track'}</span></td>
    <td><button class="button button-secondary button-compact" type="button" data-manage-accommodation="${student.id}">${student.accommodation_active ? `${student.time_multiplier}× Plan` : 'Set Plan'}</button></td>
  </tr>`).join('');
  $('coach-assignment-empty').hidden = dashboard.assignment_rows.length > 0;
  $('coach-assignment-list').innerHTML = dashboard.assignment_rows.map(assignment => `<article class="assignment-row surface"><div><h3>${escapeHtml(assignment.title)}</h3><p>Team assignment · Reviewed exam</p></div><span class="assignment-date">${escapeHtml(formatDate(assignment.due_at))}</span></article>`).join('');
  $('assignment-team').innerHTML = state.teams.map(team => `<option value="${team.id}">${escapeHtml(team.name)} · Division ${escapeHtml(team.division)}</option>`).join('');
  $('assignment-exam').innerHTML = state.exams.map(exam => `<option value="${exam.id}">${escapeHtml(exam.release_label)} · ${escapeHtml(exam.event)} · ${escapeHtml(exam.title)}</option>`).join('');
  $('show-assignment-form').disabled = !state.teams.length || !state.exams.length;
}

function setAppLoading(on) {
  const bar = $('app-loading-bar');
  if (bar) bar.hidden = !on;
}

async function loadApplication() {
  $('logout').hidden = false;
  setAppLoading(true);
  $('app-error').hidden = true;
  loadNotifications().catch(error => toast(`Notifications could not load. ${error.message}`));
  clearInterval(state.notificationTimer);
  state.notificationTimer = setInterval(() => {
    if (state.token) loadNotifications().catch(() => {});
  }, 60_000);
  const roleMode = configureRoleNavigation();
  const initialRoute = location.hash.slice(1).split('?')[0];
  showView(roleMode === 'content' ? 'content' : roleMode === 'coach' ? 'coach' : initialRoute === 'learn' ? 'learn' : initialRoute === 'practice' ? 'practice' : initialRoute === 'errors' ? 'errors' : 'dashboard', false);
  if (roleMode === 'student') $('today-copy').textContent = 'Loading your study plan…';
  try {
    if (roleMode === 'content') {
      const [events, coverage, queue, calibration, challenges] = await Promise.all([api('/events'), api('/content/source-coverage'), api('/content/questions/review-queue'), api('/content/questions/calibration-queue'), api('/content/challenges')]);
      state.events = events;
      state.sourceCoverage = coverage.scorecards;
      state.questionReviewQueue = queue;
      state.calibrationQueue = calibration;
      state.contentChallenges = challenges;
      renderSourceCoverage();
      renderQuestionReviewQueue();
      renderCalibrationQueue();
      renderContentChallengeQueue();
    } else if (roleMode === 'coach') {
      const [events, exams, coachDashboard, teams] = await Promise.all([api('/events'), api('/exams'), api('/coach/dashboard'), api('/teams')]);
      state.events = events;
      state.exams = exams;
      state.coachDashboard = coachDashboard;
      state.teams = teams;
      renderCoachDashboard();
    } else {
      const [events, exams, dashboard, accommodation] = await Promise.all([
        api('/events'), api('/exams'), api(`/student/dashboard?event_slug=${encodeURIComponent(state.activeEventSlug)}`), api('/me/accommodations'),
      ]);
      state.events = events;
      state.exams = exams;
      state.dashboard = dashboard;
      state.accommodation = accommodation;
      const hashParts = location.hash.slice(1).split('?');
      const hashParams = new URLSearchParams(hashParts[1] || '');
      const statefulParams = new URLSearchParams(location.hash.slice(1));
      const requestedSlug = hashParams.get('event') || statefulParams.get('event') || state.activeEventSlug;
      const requestedEvent = resolveEvent(requestedSlug) || studentEvents()[0] || events[0];
      state.activeEventSlug = requestedEvent?.slug || '';
      if (requestedEvent) localStorage.setItem('activeEventSlug', requestedEvent.slug);
      const selectedEvent = activeEvent();
      if (selectedEvent) {
        [state.lessons, state.practiceSets, state.activeTaxonomy, state.materials, state.dashboard] = await Promise.all([
          api(`/events/${selectedEvent.id}/lessons`),
          api(`/events/${selectedEvent.id}/practice-sets`),
          subjectKeyOf(state.activeEventSlug) === 'entomology'
            ? api(`/events/${selectedEvent.id}/taxonomy`)
            : Promise.resolve(null),
          api(`/events/${selectedEvent.id}/materials`).catch(() => ({ materials: [] })),
          api(`/student/dashboard?event_slug=${encodeURIComponent(selectedEvent.slug)}`),
        ]);
      } else {
        state.lessons = [];
        state.practiceSets = [];
        state.materials = { materials: [] };
      }
      $('today-copy').textContent = 'Build confidence one focused session at a time.';
      updateDashboard();
      renderSubjectShell();
      if (location.hash.startsWith('#lesson=')) {
        const lessonId = Number(new URLSearchParams(location.hash.slice(1)).get('lesson'));
        if (state.lessons.some(lesson => lesson.id === lessonId)) {
          showView('learn', false);
          await openLesson(lessonId);
        }
      }
      if (location.hash.startsWith('#lab=')) {
        const labParams = new URLSearchParams(location.hash.slice(1));
        const practiceSetId = Number(labParams.get('lab'));
        const practiceMode = labParams.get('mode') === 'station' ? 'station' : 'study';
        if (state.practiceSets.some(row => row.id === practiceSetId)) {
          showView('practice', false);
          await openPracticeLab(practiceSetId, practiceMode);
        }
      }
    }
  } catch (error) {
    if (state.token) {
      $('app-error-detail').textContent = ` ${error.message || 'Please try again.'}`;
      $('app-error').hidden = false;
    }
  } finally {
    setAppLoading(false);
  }
}

$('app-error-retry').addEventListener('click', () => { $('app-error').hidden = true; loadApplication(); });

$('show-assignment-form').addEventListener('click', () => {
  $('assignment-form').hidden = false;
  $('assignment-title').focus();
});

$('refresh-content-operations').addEventListener('click', event => loadContentOperations(event.currentTarget));
$('question-review-queue').addEventListener('click', async event => {
  const button = event.target.closest('[data-review-decision], [data-publish-question]');
  if (!button) return;
  const card = button.closest('[data-question-card]');
  const status = card.querySelector('.review-status');
  setBusy(button, true, button.dataset.publishQuestion ? 'Publishing Question…' : 'Saving Review…');
  status.textContent = '';
  try {
    if (button.dataset.publishQuestion) {
      await api(`/content/questions/${button.dataset.publishQuestion}/publish`, { method: 'POST' });
    } else {
      const checklist = Object.fromEntries([...card.querySelectorAll('.review-check input')].map(input => [input.name, input.checked]));
      const notes = card.querySelector('[name="review-notes"]')?.value || '';
      await api(`/content/questions/${button.dataset.questionId}/reviews`, {
        method: 'POST',
        body: JSON.stringify({ stage: button.dataset.reviewStage, decision: button.dataset.reviewDecision, checklist, notes }),
      });
    }
    state.questionReviewQueue = await api('/content/questions/review-queue');
    renderQuestionReviewQueue();
    toast(button.dataset.publishQuestion ? 'Question published.' : 'Review decision saved.');
  } catch (error) { status.textContent = error.message; }
  finally { setBusy(button, false); }
});
$('calibration-queue').addEventListener('click', async event => {
  const button = event.target.closest('[data-calibration-decision]');
  if (!button) return;
  const card = button.closest('[data-calibration-card]');
  const status = card.querySelector('.review-status');
  const notes = card.querySelector('[name="calibration-notes"]').value.trim();
  if (notes.length < 10) {
    status.textContent = 'Add at least 10 characters explaining the calibration decision.';
    card.querySelector('[name="calibration-notes"]').focus();
    return;
  }
  setBusy(button, true, 'Saving Calibration…');
  status.textContent = '';
  try {
    await api(`/content/questions/${button.dataset.questionId}/calibration`, {
      method: 'POST', body: JSON.stringify({ decision: button.dataset.calibrationDecision, notes }),
    });
    state.calibrationQueue = await api('/content/questions/calibration-queue');
    renderCalibrationQueue();
    toast(button.dataset.calibrationDecision === 'accepted' ? 'Calibration accepted.' : 'Calibration rejection recorded.');
  } catch (error) { status.textContent = error.message; }
  finally { setBusy(button, false); }
});
$('content-challenge-queue').addEventListener('submit', async event => {
  const form = event.target.closest('.challenge-triage-form, .challenge-resolution-form');
  if (!form) return;
  event.preventDefault();
  const card = form.closest('[data-content-challenge]');
  const challengeId = card.dataset.contentChallenge;
  const button = form.querySelector('button[type="submit"]');
  const status = card.querySelector('.review-status');
  const values = Object.fromEntries(new FormData(form));
  setBusy(button, true, form.classList.contains('challenge-triage-form') ? 'Saving Triage…' : 'Applying Correction…');
  status.textContent = '';
  try {
    if (form.classList.contains('challenge-triage-form')) {
      await api(`/content/challenges/${challengeId}/triage`, {
        method: 'POST', body: JSON.stringify({ severity: values.severity, notes: values.notes }),
      });
    } else {
      const correctionType = values.decision === 'not_upheld' ? 'no_score_change' : values.correction_type;
      const correctedAnswer = correctionType === 'correct_key'
        ? { correct_index: Number(values.correct_index), points: 1 } : null;
      await api(`/content/challenges/${challengeId}/resolve`, {
        method: 'POST', body: JSON.stringify({
          decision: values.decision, correction_type: correctionType,
          corrected_answer_spec: correctedAnswer,
          public_note: values.public_note, internal_note: values.internal_note,
        }),
      });
    }
    state.contentChallenges = await api('/content/challenges');
    renderContentChallengeQueue();
    toast(form.classList.contains('challenge-triage-form') ? 'Triage decision recorded.' : 'Challenge resolved and impact applied.');
  } catch (error) { status.textContent = error.message; }
  finally { setBusy(button, false); }
});
$('content-challenge-queue').addEventListener('change', event => {
  const form = event.target.closest('.challenge-resolution-form');
  if (!form) return;
  const decision = form.querySelector('[name="decision"]');
  const correction = form.querySelector('[name="correction_type"]');
  const correctedKey = form.querySelector('[name="correct_index"]');
  if (decision.value === 'not_upheld') correction.value = 'no_score_change';
  correction.disabled = decision.value === 'not_upheld';
  correctedKey.required = correction.value === 'correct_key';
  correctedKey.disabled = correction.value !== 'correct_key';
});
$('cancel-assignment').addEventListener('click', () => {
  $('assignment-form').hidden = true;
  $('assignment-message').textContent = '';
});
$('assignment-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const values = Object.fromEntries(new FormData(form));
  const payload = {
    title: values.title,
    team_id: Number(values.team_id),
    exam_id: Number(values.exam_id),
    instructions: values.instructions || '',
  };
  if (values.due_at) payload.due_at = new Date(values.due_at).toISOString();
  setBusy(button, true, 'Assigning…');
  $('assignment-message').textContent = '';
  try {
    await api('/assignments', { method: 'POST', body: JSON.stringify(payload) });
    $('assignment-message').textContent = 'Assignment published to the team.';
    toast('Assignment published.');
    form.reset();
    const [dashboard, teams] = await Promise.all([api('/coach/dashboard'), api('/teams')]);
    state.coachDashboard = dashboard;
    state.teams = teams;
    renderCoachDashboard();
  } catch (error) { $('assignment-message').textContent = error.message; }
  finally { setBusy(button, false); }
});

$('cancel-accommodation').addEventListener('click', () => {
  $('accommodation-form').hidden = true;
  $('accommodation-message').textContent = '';
});

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-manage-accommodation]');
  if (!button) return;
  const studentId = Number(button.dataset.manageAccommodation);
  setBusy(button, true, 'Opening Plan…');
  try {
    const profile = await api(`/students/${studentId}/accommodations`);
    const form = $('accommodation-form');
    form.reset();
    $('accommodation-student-id').value = studentId;
    $('accommodation-form-title').textContent = `Timed Support for ${profile.student_name}`;
    $('accommodation-multiplier').value = String(profile.time_multiplier);
    form.elements.active.checked = profile.active;
    $('accommodation-message').textContent = profile.active
      ? `Current plan: ${profile.time_multiplier}× time. Changes affect new sessions only.`
      : 'No active timed support plan.';
    form.hidden = false;
    form.scrollIntoView({ behavior: preferredScrollBehavior(), block: 'start' });
    $('accommodation-multiplier').focus({ preventScroll: true });
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
});

$('accommodation-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const values = new FormData(form);
  const studentId = Number(values.get('student_id'));
  const until = values.get('effective_until');
  const payload = {
    time_multiplier: Number(values.get('time_multiplier')),
    active: values.has('active'),
    effective_until: until ? new Date(until).toISOString() : null,
    reason: String(values.get('reason') || '').trim(),
  };
  setBusy(button, true, 'Saving Access Plan…');
  $('accommodation-message').textContent = '';
  try {
    const result = await api(`/students/${studentId}/accommodations`, {
      method: 'PUT', body: JSON.stringify(payload),
    });
    $('accommodation-message').textContent = result.active
      ? `Saved. New sessions receive ${result.time_multiplier}× time.`
      : 'Saved. Timed support is inactive for new sessions.';
    toast('Student access plan saved.');
    state.coachDashboard = await api('/coach/dashboard');
    renderCoachDashboard();
  } catch (error) { $('accommodation-message').textContent = error.message; }
  finally { setBusy(button, false); }
});

document.addEventListener('click', event => {
  const examButton = event.target.closest('[data-start-exam]');
  if (examButton?.dataset.startExam) startExam(Number(examButton.dataset.startExam));
  const subjectButton = event.target.closest('[data-subject]');
  if (subjectButton) selectSubject(subjectButton.dataset.subject, subjectButton.dataset.subjectDestination || 'learn').catch(error => toast(error.message));
  const lessonButton = event.target.closest('[data-start-lesson]');
  if (lessonButton) openLesson(Number(lessonButton.dataset.startLesson));
  const practiceButton = event.target.closest('[data-start-practice-set]');
  if (practiceButton) openPracticeLab(Number(practiceButton.dataset.startPracticeSet), practiceButton.dataset.practiceMode);
});

$('overview-event-select').addEventListener('change', event => {
  selectSubject(event.target.value, 'dashboard').catch(error => toast(error.message));
});
$('learn-event-select').addEventListener('change', event => {
  selectSubject(event.target.value, 'learn').catch(error => toast(error.message));
});
$('practice-event-select').addEventListener('change', event => {
  selectSubject(event.target.value, 'practice').catch(error => toast(error.message));
});

// Keyboard activation for non-button elements marked role="button" (e.g. the focus card).
document.addEventListener('keydown', event => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const card = event.target.closest?.('[data-subject][role="button"]');
  if (card) {
    event.preventDefault();
    selectSubject(card.dataset.subject, 'learn').catch(error => toast(error.message));
  }
});

$('start-featured-lesson').addEventListener('click', () => {
  if (state.featuredLessonId) openLesson(state.featuredLessonId);
});
$('overview-learn-button').addEventListener('click', () => {
  selectSubject(state.activeEventSlug, 'learn').catch(error => toast(error.message));
});
$('overview-practice-button').addEventListener('click', () => {
  selectSubject(state.activeEventSlug, 'practice').catch(error => toast(error.message));
});

async function openPracticeLab(id, mode = 'study') {
  const opener = document.querySelector(`[data-start-practice-set="${id}"][data-practice-mode="${mode}"]`);
  setBusy(opener, true, mode === 'station' ? 'Starting Sprint…' : 'Preparing Evidence…');
  try {
    state.practiceSession = await api(`/practice-sets/${id}/start`, {
      method: 'POST',
      body: JSON.stringify({ mode, ...(mode === 'station' ? { seconds_per_item: 45 } : {}) }),
    });
    $('practice-catalog').hidden = true;
    $('practice-runner').hidden = false;
    history.replaceState(null, '', `#lab=${id}&mode=${mode}&event=${encodeURIComponent(state.activeEventSlug)}`);
    renderPracticeItem();
  } catch (error) { toast(error.message); }
  finally { setBusy(opener, false); }
}

function clearPracticeTimer() {
  clearInterval(state.practiceTimer);
  state.practiceTimer = null;
  $('practice-timer').classList.remove('is-warning');
}

function startPracticeTimer() {
  clearPracticeTimer();
  const timer = $('practice-timer');
  const deadline = Date.parse(state.practiceSession.item_deadline_at || '');
  timer.hidden = state.practiceSession.mode !== 'station' || !Number.isFinite(deadline);
  state.practiceTimerWarned = false;
  if (timer.hidden) return;
  const tick = () => {
    const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    timer.textContent = `00:${String(remaining).padStart(2, '0')}`;
    timer.classList.toggle('is-warning', remaining <= 10);
    if (remaining <= 10 && remaining > 0 && !state.practiceTimerWarned) {
      state.practiceTimerWarned = true;
      toast('10 seconds left. Commit your best-supported identification.');
    }
    if (remaining === 0) {
      clearPracticeTimer();
      submitPracticeAnswer(null, true);
    }
  };
  tick();
  if (!state.practiceSubmitting && Date.now() < deadline) state.practiceTimer = setInterval(tick, 250);
}

function renderPracticeItem() {
  const session = state.practiceSession;
  const item = session.current_item;
  $('practice-live-score').textContent = `${session.score} correct`;
  $('practice-mode-badge').textContent = session.mode === 'station'
    ? `Station Sprint${session.accommodation_applied ? ` · ${session.time_multiplier}× Time` : ''}`
    : 'Study Lab';
  $('practice-position').textContent = session.status === 'completed' ? 'Complete' : `${session.current_index + 1} of ${session.total_items}`;
  $('practice-progress-bar').style.width = `${Math.round((session.current_index / session.total_items) * 100)}%`;
  if (!item || session.status === 'completed') {
    renderPracticeResults();
    return;
  }
  $('practice-item').className = 'practice-item surface';
  const experience = eventExperience();
  $('practice-item').innerHTML = `<p class="kicker">${escapeHtml(experience.itemLabel)} ${session.current_index + 1}</p><h1 id="practice-runner-title">Analyze the Evidence</h1><p class="block-lede">${escapeHtml(item.prompt)}</p><div class="evidence-board">${item.property_profile.map(property => `<div class="evidence-tile"><span>${escapeHtml(property.label)}</span><strong>${escapeHtml(property.value)}</strong></div>`).join('')}</div><form id="practice-answer-form"><fieldset class="choices"><legend>Choose the conclusion best supported by all the evidence.</legend>${item.choices.map((choice, index) => `<label class="choice"><input type="radio" name="practice-answer" value="${index}" required><span>${escapeHtml(choice)}</span></label>`).join('')}</fieldset><button class="button button-primary" type="submit">Commit Answer</button><div id="practice-feedback" class="practice-feedback" aria-live="polite" hidden></div></form>`;
  $('practice-item').focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: preferredScrollBehavior() });
  startPracticeTimer();
}

$('practice-item').addEventListener('submit', async event => {
  if (event.target.id !== 'practice-answer-form') return;
  event.preventDefault();
  const form = event.target;
  const selected = form.querySelector('input[name="practice-answer"]:checked');
  if (!selected) return;
  submitPracticeAnswer(Number(selected.value), false, form);
});

async function submitPracticeAnswer(selectedIndex, timedOut, form = $('practice-answer-form')) {
  if (state.practiceSubmitting || !state.practiceSession?.current_item || !form) return;
  state.practiceSubmitting = true;
  clearPracticeTimer();
  const button = form.querySelector('button[type="submit"]');
  setBusy(button, true, timedOut ? 'Time Expired' : 'Checking Evidence…');
  try {
    const result = await api(`/practice/sessions/${state.practiceSession.session_id}/answer`, {
      method: 'POST',
      body: JSON.stringify({
        item_id: state.practiceSession.current_item.id,
        ...(timedOut ? { timed_out: true } : { selected_index: selectedIndex }),
      }),
    });
    state.practiceSession = result;
    form.querySelectorAll('input').forEach(input => { input.disabled = true; });
    button.hidden = true;
    const feedback = $('practice-feedback');
    feedback.hidden = false;
    feedback.classList.toggle('incorrect', !result.correct);
    const heading = result.timed_out ? 'Station time expired' : result.correct ? 'Answer supported' : 'Recheck the key evidence';
    feedback.innerHTML = `<h2>${heading}</h2>${result.correct ? `<p>${escapeHtml(result.explanation)}</p>` : `<p>${escapeHtml(result.misconception || (result.timed_out ? 'No identification was committed before the station closed.' : 'That choice conflicts with the evidence profile.'))}</p><p><strong>Why the key fits:</strong> ${escapeHtml(result.explanation)}</p>`}<div class="form-actions">${result.remediation_case_id ? '<button class="button button-secondary" type="button" data-repair-error>Repair This Error</button>' : ''}<button class="button ${result.correct ? 'button-dark' : 'button-primary'}" type="button" data-next-practice>${result.status === 'completed' ? 'See Lab Results' : 'Next Mystery Specimen'} <span aria-hidden="true">→</span></button></div>`;
    $('practice-live-score').textContent = `${result.score} correct`;
    $('practice-progress-bar').style.width = `${Math.round((result.current_index / result.total_items) * 100)}%`;
  } catch (error) {
    toast(error.message);
    setBusy(button, false);
    if (timedOut) setTimeout(startPracticeTimer, 500);
    else startPracticeTimer();
  } finally {
    state.practiceSubmitting = false;
  }
}

$('practice-item').addEventListener('click', event => {
  if (event.target.closest('[data-next-practice]')) renderPracticeItem();
  if (event.target.closest('[data-repeat-practice]') && state.practiceSets[0]) {
    const priorMode = state.practiceSession?.mode || 'study';
    const practiceSetId = state.practiceSession?.practice_set?.id || state.practiceSets[0].id;
    state.practiceSession = null;
    openPracticeLab(practiceSetId, priorMode);
  }
  if (event.target.closest('[data-return-practice]')) closePracticeLab();
  if (event.target.closest('[data-repair-error]')) openErrorNotebook();
});

async function openErrorNotebook() {
  await closePracticeLab();
  showView('errors');
}

function renderPracticeResults() {
  clearPracticeTimer();
  $('practice-timer').hidden = true;
  const session = state.practiceSession;
  const percent = Math.round((session.score / session.total_items) * 100);
  $('practice-progress-bar').style.width = '100%';
  $('practice-item').className = 'practice-item surface practice-results';
  const experience = eventExperience();
  $('practice-item').innerHTML = `<div><p class="kicker">Evidence lab complete</p><h1 id="practice-runner-title">${escapeHtml(experience.resultTitle)}</h1><div class="practice-result-score"><strong>${session.score}/${session.total_items}</strong><span>${percent}% correct</span></div><p>${percent >= 80 ? 'Strong evidence use. Move into station-speed practice when you are ready.' : `Review the ${escapeHtml(experience.reviewTopic)} lesson, then repeat the lab and compare which evidence you use first.`}</p><div class="form-actions"><button class="button button-secondary" type="button" data-return-practice>Return to Practice</button><button class="button button-primary" type="button" data-repeat-practice>Practice Again</button></div></div>`;
  $('practice-item').focus({ preventScroll: true });
}

$('close-practice-lab').addEventListener('click', closePracticeLab);

async function closePracticeLab() {
  clearPracticeTimer();
  $('practice-runner').hidden = true;
  $('practice-catalog').hidden = false;
  state.practiceSession = null;
  history.replaceState(null, '', `#practice?event=${encodeURIComponent(state.activeEventSlug)}`);
  const event = activeEvent();
  if (event) {
    try {
      [state.practiceSets, state.dashboard] = await Promise.all([
        api(`/events/${event.id}/practice-sets`), api(`/student/dashboard?event_slug=${encodeURIComponent(state.activeEventSlug)}`),
      ]);
      updateDashboard();
    } catch {}
  }
  renderPracticeLab();
  document.querySelector('[data-start-practice-set]')?.focus();
}

async function openLesson(id) {
  const button = document.querySelector(`[data-start-lesson="${id}"]`) || $('start-featured-lesson');
  setBusy(button, true, 'Opening Lesson…');
  try {
    state.currentLesson = await api(`/lessons/${id}/start`, { method: 'POST' });
    state.lessonBlockIndex = state.currentLesson.progress.status === 'completed' ? 0 : Math.min(
      state.currentLesson.progress.current_block || 0,
      state.currentLesson.content.length - 1,
    );
    $('learn-catalog').hidden = true;
    $('lesson-reader').hidden = false;
    history.replaceState(null, '', `#lesson=${id}&event=${encodeURIComponent(state.activeEventSlug)}`);
    renderLessonBlock();
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
}

function renderLessonBlock() {
  const lesson = state.currentLesson;
  const block = lesson.content[state.lessonBlockIndex];
  const total = lesson.content.length;
  $('lesson-position').textContent = `${state.lessonBlockIndex + 1} of ${total}`;
  $('lesson-progress-bar').style.width = `${Math.round(((state.lessonBlockIndex + 1) / total) * 100)}%`;
  $('lesson-previous').disabled = state.lessonBlockIndex === 0;
  $('lesson-next').hidden = state.lessonBlockIndex === total - 1;
  $('lesson-finish').hidden = state.lessonBlockIndex !== total - 1;
  $('lesson-finish').disabled = lesson.progress.status !== 'completed';
  $('lesson-finish').textContent = lesson.progress.status === 'completed' ? 'Finish Lesson' : 'Complete Required Checkpoints';
  const renderer = {
    opening: renderOpeningBlock,
    property_cards: renderPropertyCardsBlock,
    worked_example: renderWorkedExampleBlock,
    checkpoint: renderCheckpointBlock,
    steps: renderStepsBlock,
    image_gallery: renderImageGalleryBlock,
    summary: renderSummaryBlock,
  }[block.type];
  const node = $('lesson-block');
  node.className = `lesson-block surface${block.type === 'opening' ? ' lesson-block-opening' : ''}`;
  node.innerHTML = renderer ? renderer(block) : `<h1>${escapeHtml(block.heading || 'Lesson section')}</h1><p>${escapeHtml(block.body || '')}</p>`;
  node.focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: preferredScrollBehavior() });
}

function renderOpeningBlock(block) {
  return `<p class="kicker">${escapeHtml(block.kicker || 'Lesson')}</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><p class="block-lede">${escapeHtml(block.body)}</p>`;
}

function renderPropertyCardsBlock(block) {
  return `<p class="kicker">Concept toolkit</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><p class="block-lede">${escapeHtml(block.body)}</p><div class="property-grid">${block.cards.map(card => `<article class="property-card"><h3>${escapeHtml(card.name)}</h3><strong>${escapeHtml(card.cue)}</strong><p>${escapeHtml(card.detail)}</p></article>`).join('')}</div>`;
}

function renderWorkedExampleBlock(block) {
  return `<p class="kicker">Worked example</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><div class="worked-prompt">${escapeHtml(block.prompt)}</div><ol class="worked-steps">${block.steps.map(step => `<li>${escapeHtml(step)}</li>`).join('')}</ol>`;
}

function renderCheckpointBlock(block) {
  const prior = state.currentLesson.progress.checkpoint_results[block.id];
  return `<p class="kicker">Knowledge check</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><p class="block-lede">${escapeHtml(block.question)}</p><form class="checkpoint-form" data-checkpoint-form="${escapeHtml(block.id)}"><fieldset class="choices"><legend class="sr-only">Select one answer</legend>${block.choices.map((choice, index) => `<label class="choice"><input type="radio" name="lesson-checkpoint" value="${index}" required><span>${escapeHtml(choice)}</span></label>`).join('')}</fieldset><button class="button button-primary" type="submit">Check My Answer</button><div class="checkpoint-feedback" aria-live="polite" ${prior?.correct ? '' : 'hidden'}>${prior?.correct ? '<h3>Previously completed</h3><p>You answered this checkpoint correctly.</p>' : ''}</div></form>`;
}

function renderStepsBlock(block) {
  return `<p class="kicker">Competition routine</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><ol class="routine-steps">${block.steps.map(step => `<li><strong>${escapeHtml(step.label)}</strong><span>${escapeHtml(step.detail)}</span></li>`).join('')}</ol>`;
}

function renderImageGalleryBlock(block) {
  return `<p class="kicker">${escapeHtml(block.kicker || 'Visual field guide')}</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1>${block.body ? `<p class="block-lede">${escapeHtml(block.body)}</p>` : ''}<div class="image-gallery">${(block.images || []).map(img => `<figure><img src="${mediaUrl(img.url)}" alt="${escapeHtml(img.alt || img.label || 'Specimen')}" width="760" height="570" loading="lazy" decoding="async"><figcaption><strong>${escapeHtml(img.label || '')}</strong>${img.note ? `<span>${escapeHtml(img.note)}</span>` : ''}${img.attribution ? `<small>${escapeHtml(img.attribution)}${img.license ? ` · ${escapeHtml(img.license)}` : ''}</small>` : ''}</figcaption></figure>`).join('')}</div>`;
}

function renderSummaryBlock(block) {
  const citations = state.currentLesson.citations || [];
  return `<p class="kicker">Lesson summary</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><ul class="summary-points">${block.points.map(point => `<li>${escapeHtml(point)}</li>`).join('')}</ul><div class="lesson-citations"><h3>Reviewed Sources</h3>${citations.map(citation => `<p><a href="${safeUrl(citation.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(citation.title)}</a> · ${escapeHtml(citation.publisher || '')}</p>`).join('')}</div>`;
}

$('lesson-block').addEventListener('submit', async event => {
  const form = event.target.closest('[data-checkpoint-form]');
  if (!form) return;
  event.preventDefault();
  const selected = form.querySelector('input[name="lesson-checkpoint"]:checked');
  if (!selected) return;
  const button = form.querySelector('button[type="submit"]');
  setBusy(button, true, 'Checking…');
  // When the answer is correct we intentionally leave the button disabled and
  // relabeled; otherwise the finally block must always re-enable it, since
  // setBusy() has already set disabled = true.
  let locked = false;
  try {
    const result = await api(`/lessons/${state.currentLesson.id}/checkpoint`, {
      method: 'POST',
      body: JSON.stringify({ checkpoint_id: form.dataset.checkpointForm, selected_index: Number(selected.value) }),
    });
    state.currentLesson.progress.checkpoint_results[form.dataset.checkpointForm] = { correct: result.correct, attempts: result.attempts };
    state.currentLesson.progress.status = result.lesson_status;
    const feedback = form.querySelector('.checkpoint-feedback');
    feedback.hidden = false;
    feedback.classList.toggle('incorrect', !result.correct);
    feedback.innerHTML = `<h3>${result.correct ? 'Evidence confirmed' : 'Look at the evidence being tested'}</h3><p>${escapeHtml(result.misconception || result.explanation)}</p>`;
    if (result.correct) {
      button.textContent = 'Correct';
      button.disabled = true;
      locked = true;
      await saveCurrentLessonProgress(true);
    }
  } catch (error) { toast(error.message); }
  finally { if (!locked) setBusy(button, false); }
});

async function saveCurrentLessonProgress(markCurrentComplete = false) {
  const lesson = state.currentLesson;
  const block = lesson.content[state.lessonBlockIndex];
  const completed = new Set(lesson.progress.completed_block_ids || []);
  if (markCurrentComplete) completed.add(block.id);
  $('lesson-save-state').textContent = 'Saving…';
  const result = await api(`/lessons/${lesson.id}/progress`, {
    method: 'PUT',
    body: JSON.stringify({ current_block: state.lessonBlockIndex, completed_block_ids: [...completed] }),
  });
  lesson.progress.completed_block_ids = result.completed_block_ids;
  $('lesson-save-state').textContent = 'Progress saved';
}

async function moveLesson(delta) {
  const block = state.currentLesson.content[state.lessonBlockIndex];
  if (delta > 0 && block.type === 'checkpoint' && !state.currentLesson.progress.checkpoint_results[block.id]?.correct) {
    toast('Answer this knowledge check correctly before moving on.');
    return;
  }
  try {
    if (delta > 0) {
      const completed = new Set(state.currentLesson.progress.completed_block_ids || []);
      completed.add(block.id);
      state.currentLesson.progress.completed_block_ids = [...completed];
    }
    state.lessonBlockIndex += delta;
    await saveCurrentLessonProgress(false);
    renderLessonBlock();
  } catch (error) { toast(error.message); }
}

$('lesson-previous').addEventListener('click', () => moveLesson(-1));
$('lesson-next').addEventListener('click', () => moveLesson(1));
$('lesson-finish').addEventListener('click', async () => {
  if (state.currentLesson.progress.status !== 'completed') return;
  try { await saveCurrentLessonProgress(true); } catch (error) { toast(error.message); return; }
  toast('Lesson complete. Your mastery record has been updated.');
  closeLesson();
  loadApplication();
});
$('close-lesson').addEventListener('click', closeLesson);

function closeLesson() {
  closeTutor();
  $('lesson-reader').hidden = true;
  $('learn-catalog').hidden = false;
  state.currentLesson = null;
  history.replaceState(null, '', `#learn?event=${encodeURIComponent(state.activeEventSlug)}`);
  $('start-featured-lesson').focus();
}

async function runMissionAction(index) {
  const item = state.dashboard?.daily_plan?.items?.[index];
  if (!item) { showView('learn'); return; }
  if (item.event_slug && item.event_slug !== state.activeEventSlug && ['lesson', 'spaced_review'].includes(item.type)) {
    await selectSubject(item.event_slug, item.type === 'lesson' ? 'learn' : 'practice');
  }
  if (item.type === 'remediation') showView('errors');
  else if (item.type === 'lesson') {
    showView('learn');
    await openLesson(item.entity_id);
  } else if (item.type === 'spaced_review' && item.practice_set_id) {
    showView('practice');
    await openPracticeLab(item.practice_set_id, 'study');
  } else location.href = item.route;
}

$('daily-plan-list').addEventListener('click', event => {
  const link = event.target.closest('[data-mission-action]');
  if (!link) return;
  event.preventDefault();
  runMissionAction(Number(link.dataset.missionAction)).catch(error => toast(error.message));
});

$('continue-button').addEventListener('click', event => {
  if (event.currentTarget.dataset.startExam) return;
  if (event.currentTarget.dataset.missionIndex) runMissionAction(Number(event.currentTarget.dataset.missionIndex)).catch(error => toast(error.message));
  else showView('learn');
});

async function startExam(id) {
  const button = document.querySelector(`[data-start-exam="${id}"]`);
  setBusy(button, true, 'Preparing Exam…');
  try {
    state.exam = await api(`/exams/${id}/start`, {
      method: 'POST', headers: { 'X-Exam-Client-Session': state.examClientSession },
    });
    state.attempt = state.exam.attempt_id;
    state.answers = Object.fromEntries(state.exam.questions
      .filter(question => question.saved_answer?.selected_index != null || question.saved_answer?.text != null)
      .map(question => [question.id, question.saved_answer.selected_index != null
        ? Number(question.saved_answer.selected_index)
        : String(question.saved_answer.text)]));
    state.sequences = Object.fromEntries(state.exam.questions.map(question => [
      question.id, Number(question.saved_sequence_number || 0),
    ]));
    state.questionTimes = Object.fromEntries(state.exam.questions.map(question => [
      question.id, Number(question.saved_time_spent_seconds || 0),
    ]));
    state.confidences = Object.fromEntries(state.exam.questions
      .filter(question => question.saved_confidence != null)
      .map(question => [question.id, Number(question.saved_confidence)]));
    const offline = readOfflineQueue();
    Object.values(offline).forEach(payload => {
      if (payload.sequence_number > (state.sequences[payload.question_id] || 0)) {
        state.answers[payload.question_id] = payload.answer && payload.answer.text != null
          ? String(payload.answer.text)
          : Number(payload.answer.selected_index);
        state.sequences[payload.question_id] = payload.sequence_number;
        state.questionTimes[payload.question_id] = payload.time_spent_seconds || 0;
        if (payload.confidence != null) state.confidences[payload.question_id] = Number(payload.confidence);
      }
    });
    state.currentQuestion = Math.max(0, state.exam.questions.findIndex(
      question => !Object.hasOwn(state.answers, question.id)
    ));
    state.questionEnteredAt = Date.now();
    showSection('exam');
    $('exam-title').textContent = state.exam.title;
    $('exam-release-label').textContent = state.exam.release_label;
    $('exam-accommodation').hidden = !state.exam.accommodation_applied;
    $('exam-accommodation').textContent = state.exam.accommodation_applied
      ? `${state.exam.time_multiplier}× Extended Time Applied`
      : 'Standard Time';
    renderExamQuestions();
    if (Object.keys(offline).length) {
      setExamSaveState(
        navigator.onLine ? 'Recovering saved answers…' : 'Saved on this device · will sync when you reconnect',
        navigator.onLine ? 'busy' : 'offline'
      );
      if (navigator.onLine) syncOfflineQueue().catch(() => {});
    } else if (state.exam.restored_response_count) {
      setExamSaveState(`${state.exam.restored_response_count} saved answer${state.exam.restored_response_count === 1 ? '' : 's'} restored`);
    }
    startTimer(state.exam.deadline_at);
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
}

function renderQuestionAssets(assets) {
  if (!Array.isArray(assets) || !assets.length) return '';
  return `<figure class="question-figure">${assets.map(asset => `
    <img src="${mediaUrl(asset.url)}" alt="${escapeHtml(asset.alt || 'Specimen image for identification')}" width="800" height="600" loading="lazy" decoding="async">
    ${asset.attribution ? `<figcaption>${escapeHtml(asset.attribution)}${asset.license ? ` · ${escapeHtml(asset.license)}` : ''}</figcaption>` : ''}
  `).join('')}</figure>`;
}

function renderExamQuestions() {
  $('exam-form').innerHTML = state.exam.questions.map((question, index) => `<section class="question surface" data-question-index="${index}" ${index === state.currentQuestion ? '' : 'hidden'}>
    <div class="question-heading"><span class="question-number">${index + 1}</span><div><p class="kicker">Question ${index + 1} of ${state.exam.questions.length}</p><h2>${escapeHtml(question.stem)}</h2></div></div>
    ${renderQuestionAssets(question.assets)}
    ${question.figure_missing ? `<p class="figure-missing-note"><span aria-hidden="true">⚠</span> This question refers to a figure that isn't available in our copy of the test, so it won't be scored. You can still attempt it for practice.</p>` : ''}
    ${question.choices && question.choices.length
      ? `<fieldset class="choices"><legend class="sr-only">Select one answer</legend>${question.choices.map((choice, choiceIndex) => `<label class="choice"><input type="radio" name="q-${question.id}" value="${choiceIndex}" data-question-id="${question.id}"><span>${escapeHtml(choice)}</span></label>`).join('')}</fieldset>`
      : `<div class="text-answer"><label class="sr-only" for="qtext-${question.id}">Your answer</label>${question.question_type === 'numeric'
          ? `<input id="qtext-${question.id}" type="text" inputmode="decimal" class="answer-input" data-text-id="${question.id}" autocomplete="off" placeholder="Enter your answer…">`
          : `<textarea id="qtext-${question.id}" class="answer-input" data-text-id="${question.id}" rows="3" autocomplete="off" placeholder="Type your answer…"></textarea>`}</div>`}
    <fieldset class="confidence-panel"><legend>How confident are you?</legend><div class="confidence-options">${[['1', 'Guessing'], ['2', 'Unsure'], ['3', 'Fairly sure'], ['4', 'Confident'], ['5', 'Certain']].map(([value, label]) => `<label><input type="radio" name="confidence-${question.id}" value="${value}" data-confidence-id="${question.id}"><span>${label}</span></label>`).join('')}</div></fieldset>
  </section>`).join('');
  $('question-map').innerHTML = state.exam.questions.map((_, index) => `<button class="map-button${index === state.currentQuestion ? ' current' : ''}" type="button" data-question-jump="${index}" aria-label="Go to question ${index + 1}">${index + 1}</button>`).join('');
  Object.entries(state.answers).forEach(([questionId, value]) => {
    if (typeof value === 'string') {
      const field = document.querySelector(`[data-text-id="${questionId}"]`);
      if (field) field.value = value;
      return;
    }
    const answer = document.querySelector(`input[name="q-${questionId}"][value="${value}"]`);
    if (answer) answer.checked = true;
  });
  state.exam.questions.forEach(question => {
    if (state.confidences[question.id] == null) return;
    const confidence = document.querySelector(`input[name="confidence-${question.id}"][value="${state.confidences[question.id]}"]`);
    if (confidence) confidence.checked = true;
  });
  $('exam-form').addEventListener('change', handleExamChange);
  $('exam-form').addEventListener('input', handleExamTextInput);
  $('question-map').addEventListener('click', event => {
    const button = event.target.closest('[data-question-jump]');
    if (button) goToQuestion(Number(button.dataset.questionJump));
  });
  updateExamNavigation();
}

function handleExamChange(event) {
  const questionId = Number(event.target.dataset.questionId || event.target.dataset.confidenceId);
  if (!questionId) return;
  const selected = document.querySelector(`input[name="q-${questionId}"]:checked`);
  if (selected) {
    state.answers[questionId] = Number(selected.value);
    queueSave(questionId);
  }
  if (event.target.dataset.confidenceId) {
    state.confidences[questionId] = Number(event.target.value);
    if (Object.hasOwn(state.answers, questionId)) queueSave(questionId);
  }
  updateExamNavigation();
}

function handleExamTextInput(event) {
  const questionId = Number(event.target.dataset.textId);
  if (!questionId) return;
  const value = event.target.value;
  if (value.trim() === '') delete state.answers[questionId];
  else state.answers[questionId] = value;
  queueSave(questionId);
  updateExamNavigation();
}

function isAnswered(questionId) {
  const value = state.answers[questionId];
  return typeof value === 'number' || (typeof value === 'string' && value.trim() !== '');
}

function queueSave(questionId) {
  clearTimeout(state.saveQueue.get(questionId));
  setExamSaveState('Saving…', 'busy');
  const timeout = setTimeout(() => saveAnswer(questionId).catch(() => {}), 250);
  state.saveQueue.set(questionId, timeout);
}

function offlineStorageKey() {
  return state.user && state.attempt ? `fieldstone:offline-exam:${state.user.id}:${state.attempt}` : '';
}

function readOfflineQueue() {
  const key = offlineStorageKey();
  if (!key) return {};
  try { return JSON.parse(localStorage.getItem(key) || '{}'); }
  catch { return {}; }
}

function persistOfflinePayload(payload) {
  const queue = readOfflineQueue();
  queue[payload.question_id] = payload;
  localStorage.setItem(offlineStorageKey(), JSON.stringify(queue));
}

function removeOfflinePayload(payload) {
  const queue = readOfflineQueue();
  if (queue[payload.question_id]?.idempotency_key !== payload.idempotency_key) return;
  delete queue[payload.question_id];
  if (Object.keys(queue).length) localStorage.setItem(offlineStorageKey(), JSON.stringify(queue));
  else localStorage.removeItem(offlineStorageKey());
}

function accrueQuestionTime() {
  if (!state.exam || state.questionEnteredAt == null) return;
  const question = state.exam.questions[state.currentQuestion];
  if (!question) return;
  const elapsed = Math.max(0, Math.round((Date.now() - state.questionEnteredAt) / 1000));
  state.questionTimes[question.id] = Math.min(86_400, (state.questionTimes[question.id] || 0) + elapsed);
  state.questionEnteredAt = Date.now();
}

async function transmitSave(payload) {
  try {
    const result = await api(`/attempts/${state.attempt}/responses`, {
      method: 'PUT', body: JSON.stringify(payload),
    });
    removeOfflinePayload(payload);
    setExamSaveState(result.duplicate ? 'Already synced' : 'Saved');
    return result;
  } catch (error) {
    if (error.status === 409 && error.message.includes('Stale response')) {
      removeOfflinePayload(payload);
      return { stale: true };
    }
    const online = navigator.onLine;
    setExamSaveState(online
      ? 'Saved on this device · retrying sync'
      : 'Saved on this device · will sync when you reconnect',
    online ? 'pending' : 'offline');
    if (online) scheduleOfflineRetry();
    throw error;
  }
}

async function saveAnswer(questionId) {
  state.saveQueue.delete(questionId);
  accrueQuestionTime();
  const sequence = (state.sequences[questionId] || 0) + 1;
  state.sequences[questionId] = sequence;
  const raw = state.answers[questionId];
  const payload = {
    question_id: questionId,
    answer: typeof raw === 'number' ? { selected_index: raw } : { text: String(raw ?? '') },
    confidence: state.confidences[questionId] ?? null,
    time_spent_seconds: state.questionTimes[questionId] || 0,
    sequence_number: sequence,
    idempotency_key: `${state.attempt}-${questionId}-${sequence}-${crypto.randomUUID()}`,
    client_metadata: {
      offline_replay: false, client_session_id: state.examClientSession,
      connection: navigator.onLine ? 'online' : 'offline',
    },
  };
  persistOfflinePayload(payload);
  const prior = state.saveInflight.get(questionId) || Promise.resolve();
  const operation = prior.catch(() => {}).then(() => transmitSave(payload));
  state.saveInflight.set(questionId, operation);
  try { return await operation; }
  finally {
    if (state.saveInflight.get(questionId) === operation) state.saveInflight.delete(questionId);
  }
}

function scheduleOfflineRetry() {
  if (state.offlineRetryTimer) return;
  state.offlineRetryTimer = setTimeout(() => {
    state.offlineRetryTimer = null;
    if (!state.attempt || !Object.keys(readOfflineQueue()).length) return;
    syncOfflineQueue()
      .then(() => {
        if (!Object.keys(readOfflineQueue()).length) setExamSaveState('All answers synced');
        else scheduleOfflineRetry();
      })
      .catch(() => scheduleOfflineRetry());
  }, 5000);
}

async function syncOfflineQueue() {
  if (state.offlineSyncing || !state.attempt || !navigator.onLine) return;
  state.offlineSyncing = true;
  try {
    const payloads = Object.values(readOfflineQueue()).sort((a, b) => a.sequence_number - b.sequence_number);
    for (const payload of payloads) {
      await transmitSave({
        ...payload,
        client_metadata: { ...(payload.client_metadata || {}), offline_replay: true, client_session_id: state.examClientSession, connection: 'reconnected' },
      });
    }
  } finally { state.offlineSyncing = false; }
}

function goToQuestion(index) {
  if (index < 0 || index >= state.exam.questions.length) return;
  accrueQuestionTime();
  state.currentQuestion = index;
  state.questionEnteredAt = Date.now();
  document.querySelectorAll('[data-question-index]').forEach(section => { section.hidden = Number(section.dataset.questionIndex) !== index; });
  updateExamNavigation();
  $('exam-form').focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: preferredScrollBehavior() });
}

function updateExamNavigation() {
  const total = state.exam.questions.length;
  const answered = state.exam.questions.filter(question => isAnswered(question.id)).length;
  $('answered-count').textContent = `${answered} of ${total} answered`;
  document.querySelectorAll('.map-button').forEach((button, index) => {
    const questionId = state.exam.questions[index].id;
    button.classList.toggle('answered', isAnswered(questionId));
    button.classList.toggle('current', index === state.currentQuestion);
  });
  $('previous-question').disabled = state.currentQuestion === 0;
  $('next-question').hidden = state.currentQuestion === total - 1;
  // Submit is available from any question — students shouldn't have to page to
  // the last question to finish. submitExam() still confirms if any are blank.
  $('submit-exam').hidden = false;
}

$('previous-question').addEventListener('click', () => goToQuestion(state.currentQuestion - 1));
$('next-question').addEventListener('click', () => goToQuestion(state.currentQuestion + 1));
$('submit-exam').addEventListener('click', submitExam);

async function exitExam() {
  if (!(await confirmDialog({
    title: 'Leave this test?',
    body: 'Your answers are saved — you can resume it later from Practice & Exams. The timer keeps running.',
    confirmLabel: 'Leave test', cancelLabel: 'Keep working',
  }))) return;
  clearInterval(state.timer);
  state.exam = null;
  state.attempt = null;  // clear attempt too, or the logout/brand exit guards keep thinking a test is open
  showView('practice');
  loadApplication();
}
$('exit-exam').addEventListener('click', exitExam);

function startTimer(deadlineAt) {
  const deadline = new Date(deadlineAt).getTime();
  clearInterval(state.timer);
  const tick = () => {
    const remaining = Math.max(0, Math.floor((deadline - Date.now()) / 1000));
    const minutes = Math.floor(remaining / 60);
    const seconds = remaining % 60;
    $('timer').textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    $('timer').classList.toggle('warning', remaining <= 300);
    if (remaining <= 0) { clearInterval(state.timer); submitExam(true); }
  };
  tick();
  state.timer = setInterval(tick, 1000);
}

async function submitExam(autoSubmit = false) {
  if (state.submitting) return;
  const unanswered = state.exam.questions.filter(question => !isAnswered(question.id)).length;
  if (!autoSubmit && unanswered > 0 && !(await confirmDialog({
    title: 'Submit with blanks?',
    body: `${unanswered} question${unanswered === 1 ? ' is' : 's are'} still unanswered. You can't change answers after submitting.`,
    confirmLabel: 'Submit exam', cancelLabel: 'Keep working',
  }))) return;
  if (!navigator.onLine) {
    state.pendingAutoSubmit = autoSubmit;
    setExamSaveState(autoSubmit
      ? 'Time ended · submission waiting for connection'
      : 'Offline · reconnect before submitting', 'offline');
    toast('Your answers are saved on this device. Reconnect to sync and submit.');
    return;
  }
  state.submitting = true;
  setBusy($('submit-exam'), true, 'Submitting…');
  try {
    const pendingQuestionIds = [...state.saveQueue.keys()].filter(id => Object.hasOwn(state.answers, id));
    state.saveQueue.forEach(timeout => clearTimeout(timeout));
    state.saveQueue.clear();
    await Promise.all(pendingQuestionIds.map(id => saveAnswer(id)));
    const currentQuestionId = state.exam.questions[state.currentQuestion]?.id;
    if (currentQuestionId && Object.hasOwn(state.answers, currentQuestionId) && !pendingQuestionIds.includes(currentQuestionId)) {
      await saveAnswer(currentQuestionId);
    }
    await Promise.all([...state.saveInflight.values()].map(operation => operation.catch(() => {})));
    await syncOfflineQueue();
    if (Object.keys(readOfflineQueue()).length) {
      throw new Error('Some answers are still saved only on this device. Keep this page open and reconnect before submitting.');
    }
    clearInterval(state.timer);
    const result = await api(`/attempts/${state.attempt}/submit`, {
      method: 'POST', headers: { 'X-Exam-Client-Session': state.examClientSession },
    });
    localStorage.removeItem(offlineStorageKey());
    state.pendingAutoSubmit = false;
    state.resultsHistory = null;  // a new attempt was just recorded — refresh the cache
    await loadReview(state.attempt, result);
  } catch (error) {
    toast(error.message);
    state.submitting = false;
    setBusy($('submit-exam'), false);
    startTimer(state.exam.deadline_at);
  }
}

async function renderAnswerKey(attemptId) {
  const panel = $('answer-key-panel');
  try {
    const data = await api(`/attempts/${attemptId}/answers`);
    const rows = data.questions || [];
    if (!rows.length) { panel.hidden = true; return; }
    $('answer-key-list').innerHTML = rows.map(question => {
      const answer = question.your_answer || {};
      const your = answer.text != null && String(answer.text).trim() !== ''
        ? escapeHtml(answer.text)
        : (answer.selected_index != null ? `Option ${Number(answer.selected_index) + 1}` : '<em>No answer</em>');
      const note = question.rationale || question.explanation || '';
      const stateClass = question.scored === false ? 'is-unscored' : question.correct ? 'is-correct' : 'is-incorrect';
      const mark = question.scored === false ? '—' : question.correct ? '✓' : '✕';
      const pts = question.scored === false ? 'Not scored' : `${question.points_awarded}/${question.max_points} pt`;
      return `<article class="answer-key-item ${stateClass}">
        <header><span class="ak-status" aria-hidden="true">${mark}</span><span class="ak-pos">Q${question.position}</span><span class="ak-points">${pts}</span></header>
        <p class="ak-stem">${escapeHtml(question.stem)}</p>
        <p class="ak-line"><strong>Your answer:</strong> ${your}</p>
        <p class="ak-line"><strong>Reference:</strong> ${escapeHtml(question.reference_answer || '—')}</p>
        ${question.misconception ? `<p class="ak-misconception"><strong>Why that choice misleads:</strong> ${escapeHtml(question.misconception)}</p>` : ''}
        ${note ? `<p class="ak-rationale">${escapeHtml(note)}</p>` : ''}
      </article>`;
    }).join('');
    panel.hidden = false;
  } catch { panel.hidden = true; }
}

async function loadReview(attemptId, result) {
  const review = await api(`/attempts/${attemptId}/review`);
  state.reviewAttemptId = attemptId;
  state.attempt = null;
  setExamSaveState('');
  showSection('review');
  const max = result.max_score || 0;
  const percent = max ? Math.round((result.score / max) * 100) : 0;
  $('score').textContent = `${result.score} of ${max} Points`;
  $('score-percent').textContent = `${percent}%`;
  await renderAnswerKey(attemptId);
  $('challenge-question').innerHTML = review.challengeable_items.map(item => `<option value="${item.question_id}" ${item.challenge ? 'disabled' : ''}>Question ${item.position} · ${item.challenge ? `Report ${escapeHtml(item.challenge.status.replaceAll('_', ' '))}` : escapeHtml(item.stem)}</option>`).join('');
  $('student-challenge-form').querySelector('button[type="submit"]').disabled = review.challengeable_items.every(item => item.challenge);
  $('student-challenge-status').textContent = review.challengeable_items.some(item => item.challenge?.public_note) ? 'A correction decision is available in your content report history.' : '';
  $('remediation-list').innerHTML = review.remediation_cases.length ? review.remediation_cases.map((item, index) => `<article class="remediation surface" data-case-id="${item.id}">
    <span class="remediation-step">Step ${index + 1} · ${escapeHtml(item.error_type.replaceAll('_', ' '))}</span>
    <h2>Understand What Happened</h2><p><strong>Question:</strong> ${escapeHtml(item.diagnosis.question_stem)}</p><p><strong>Targeted explanation:</strong> ${escapeHtml(item.plan.explanation)}</p>
    <ol>${item.plan.steps.map(step => `<li>${escapeHtml(step)}</li>`).join('')}</ol>
    <label for="reflection-${item.id}"><strong>Explain your original approach and where it changed course.</strong></label><textarea id="reflection-${item.id}" rows="5" minlength="10">${escapeHtml(item.student_reflection || '')}</textarea>
    <div class="review-actions"><button class="button button-dark" type="button" data-save-reflection="${item.id}">Save Reflection & Continue</button><button class="button button-secondary" type="button" data-open-tutor="remediation" data-tutor-context-id="${item.id}">Ask Grounded Tutor</button></div><div class="case-status" data-case-status aria-live="polite"></div>
  </article>`).join('') : '<div class="empty-state surface"><span aria-hidden="true">✓</span><h2>Strong Work</h2><p>No remediation cases were created. Keep the knowledge fresh with your next review.</p></div>';
  state.submitting = false;
}

$('student-challenge-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const status = $('student-challenge-status');
  const values = Object.fromEntries(new FormData(form));
  setBusy(button, true, 'Submitting Report…');
  status.textContent = '';
  try {
    await api(`/attempts/${state.reviewAttemptId}/challenges`, {
      method: 'POST', body: JSON.stringify({
        question_id: Number(values.question_id), category: values.category,
        description: values.description,
      }),
    });
    status.textContent = 'Report submitted. Content staff will review the exact question version you saw.';
    form.querySelector(`[value="${CSS.escape(values.question_id)}"]`).disabled = true;
    form.querySelector('[name="description"]').value = '';
  } catch (error) { status.textContent = error.message; }
  finally {
    setBusy(button, false);
    button.disabled = [...$('challenge-question').options].every(option => option.disabled);
  }
});

$('remediation-list').addEventListener('click', async event => {
  const reflectionButton = event.target.closest('[data-save-reflection]');
  const transferButton = event.target.closest('[data-start-transfer]');
  const submitButton = event.target.closest('[data-submit-transfer]');
  if (reflectionButton) await saveReflection(Number(reflectionButton.dataset.saveReflection), reflectionButton);
  if (transferButton) await startTransfer(Number(transferButton.dataset.startTransfer), transferButton);
  if (submitButton) await submitTransfer(Number(submitButton.dataset.submitTransfer), Number(submitButton.dataset.forCase), submitButton);
});

$('error-notebook-list').addEventListener('click', async event => {
  const reflectionButton = event.target.closest('[data-save-reflection]');
  const transferButton = event.target.closest('[data-start-transfer]');
  const submitButton = event.target.closest('[data-submit-transfer]');
  const delayedButton = event.target.closest('[data-start-delayed]');
  const delayedSubmit = event.target.closest('[data-submit-delayed]');
  if (reflectionButton) await saveReflection(Number(reflectionButton.dataset.saveReflection), reflectionButton);
  if (transferButton) await startTransfer(Number(transferButton.dataset.startTransfer), transferButton);
  if (submitButton) await submitTransfer(Number(submitButton.dataset.submitTransfer), Number(submitButton.dataset.forCase), submitButton);
  if (delayedButton) await startDelayedReview(Number(delayedButton.dataset.startDelayed), delayedButton);
  if (delayedSubmit) await submitDelayedReview(Number(delayedSubmit.dataset.submitDelayed), Number(delayedSubmit.dataset.forCase), delayedSubmit);
});

function caseElements(button) {
  // data-case-id marks case cards only; action buttons use data-for-case.
  const card = button.closest('article[data-case-id]');
  return { card, status: card.querySelector('[data-case-status]'), reflection: card.querySelector('textarea') };
}

async function saveReflection(id, button) {
  const elements = caseElements(button);
  const reflection = elements.reflection.value.trim();
  if (reflection.length < 10) { elements.status.textContent = 'Add a little more detail about your reasoning before continuing.'; return; }
  setBusy(button, true, 'Saving Reflection…');
  try {
    const result = await api(`/remediation/${id}/reflection`, { method: 'PUT', body: JSON.stringify({ reflection }) });
    elements.status.innerHTML = `Reflection saved. Status: ${escapeHtml(result.status.replaceAll('_', ' '))}. <button class="button button-primary" type="button" data-start-transfer="${id}">Start Unseen Transfer Check</button>`;
  } catch (error) { elements.status.textContent = error.message; }
  finally { setBusy(button, false); }
}

async function startTransfer(id, button) {
  const elements = caseElements(button);
  setBusy(button, true, 'Building New Problem…');
  try {
    const result = await api(`/remediation/${id}/transfer`, { method: 'POST' });
    const question = result.question;
    elements.status.innerHTML = `<div class="question"><h3>${escapeHtml(question.stem)}</h3><fieldset class="choices"><legend>Select one answer</legend>${question.choices.map((choice, index) => `<label class="choice"><input type="radio" name="transfer-${result.transfer_id}" value="${index}"><span>${escapeHtml(choice)}</span></label>`).join('')}</fieldset><button class="button button-primary" type="button" data-submit-transfer="${result.transfer_id}" data-for-case="${id}">Submit Transfer Answer</button></div>`;
  } catch (error) { elements.status.textContent = error.message; }
  finally { setBusy(button, false); }
}

async function submitTransfer(transferId, caseId, button) {
  const elements = caseElements(button);
  const picked = document.querySelector(`input[name="transfer-${transferId}"]:checked`);
  if (!picked) { toast('Choose an answer before submitting the transfer check.'); return; }
  setBusy(button, true, 'Checking Answer…');
  try {
    const result = await api(`/remediation/transfer/${transferId}/submit`, { method: 'POST', body: JSON.stringify({ answer: { selected_index: Number(picked.value) } }) });
    elements.status.innerHTML = result.correct ? '<p>Transfer passed. Your retention check is scheduled for 3 days from now.</p>' : `<p>Not yet. Return to the explanation, strengthen your reflection, then try a new transfer check.</p><button class="button button-primary" type="button" data-start-transfer="${caseId}">Try Another Transfer Check</button>`;
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
}

async function startDelayedReview(id, button) {
  const elements = caseElements(button);
  setBusy(button, true, 'Building Retention Check…');
  try {
    const result = await api(`/remediation/${id}/delayed-review`, { method: 'POST' });
    const question = result.question;
    elements.status.innerHTML = `<div class="question"><h3>${escapeHtml(question.stem)}</h3><fieldset class="choices"><legend>Select one answer</legend>${question.choices.map((choice, index) => `<label class="choice"><input type="radio" name="delayed-${result.transfer_id}" value="${index}"><span>${escapeHtml(choice)}</span></label>`).join('')}</fieldset><button class="button button-primary" type="button" data-submit-delayed="${result.transfer_id}" data-for-case="${id}">Submit Retention Answer</button></div>`;
    button.hidden = true;
  } catch (error) { elements.status.textContent = error.message; }
  finally { setBusy(button, false); }
}

async function submitDelayedReview(transferId, caseId, button) {
  const elements = caseElements(button);
  const picked = elements.card.querySelector(`input[name="delayed-${transferId}"]:checked`);
  if (!picked) { elements.status.insertAdjacentHTML('afterbegin', '<p>Choose an answer before submitting the retention check.</p>'); return; }
  setBusy(button, true, 'Checking Retention…');
  try {
    const result = await api(`/remediation/delayed-review/${transferId}/submit`, { method: 'POST', body: JSON.stringify({ answer: { selected_index: Number(picked.value) } }) });
    elements.card.innerHTML = result.correct ? '<div class="repair-resolved"><span aria-hidden="true">✓</span><h2>Error Resolved</h2><p>You proved the correction after a delay. This case is now closed.</p></div>' : `<div class="repair-reopened"><h2>This Idea Needs One More Pass</h2><p>The case is reopened so the miss does not disappear before it is learned.</p><button class="button button-primary" type="button" data-start-transfer="${caseId}">Restart Transfer Practice</button><div data-case-status aria-live="polite"></div></div>`;
    state.dashboard = await api(`/student/dashboard?event_slug=${encodeURIComponent(state.activeEventSlug)}`);
    updateDashboard();
  } catch (error) { elements.status.textContent = error.message; }
  finally { setBusy(button, false); }
}

$('back-dashboard').addEventListener('click', async () => {
  state.attempt = null;
  await loadApplication();
  showView('dashboard');
});

window.addEventListener('beforeunload', event => {
  if (state.attempt && !state.submitting) { event.preventDefault(); event.returnValue = ''; }
});

window.addEventListener('offline', () => {
  if (state.attempt) setExamSaveState('Offline · answers are saved on this device', 'offline');
});

window.addEventListener('online', () => {
  if (!state.attempt) return;
  setExamSaveState('Back online · syncing…', 'busy');
  syncOfflineQueue()
    .then(() => {
      if (state.pendingAutoSubmit) return submitExam(true);
      const remaining = Object.keys(readOfflineQueue()).length;
      setExamSaveState(remaining ? 'Sync pending · keep this page open' : 'All answers synced', remaining ? 'pending' : 'synced');
    })
    .catch(error => { setExamSaveState('Sync pending · keep this page open', 'pending'); toast(error.message); });
});

window.addEventListener('hashchange', () => {
  if (!state.token || state.attempt) return;
  const [routePart, queryPart] = location.hash.slice(1).split('?');
  const hashRoute = `#${routePart}`;
  const requestedEvent = new URLSearchParams(queryPart || '').get('event');
  if (requestedEvent && requestedEvent !== state.activeEventSlug && ['learn', 'practice'].includes(routePart)) {
    selectSubject(requestedEvent, routePart).catch(error => toast(error.message));
    return;
  }
  // Non-student roles have no student dashboard, so #overview (the brand logo)
  // must land them on their own home instead of an empty student view.
  const roleHome = ['admin', 'editor', 'sme', 'calibrator'].includes(state.user.role)
    ? 'content' : state.user.role === 'coach' ? 'coach' : 'dashboard';
  const view = { '#learn': 'learn', '#practice': 'practice', '#errors': 'errors', '#coach': 'coach', '#content': 'content' }[hashRoute] || roleHome;
  showView(view, false);
});

async function initialize() {
  try {
    state.authConfig = await api('/auth/config');
    $('google-auth').hidden = state.authConfig.provider !== 'firebase';
  } catch (error) {
    $('auth-error').textContent = 'The sign-in service is unavailable. Refresh the page or try again later.';
  }
  if (state.token && state.user) loadApplication(); else showSection('auth');
}

initialize();
