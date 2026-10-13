// The stored slug may predate catalog consolidation (for example, "rocks-and-minerals-b").
// Keep it raw: resolveEvent rolls any remembered value forward onto the served catalog —
// exact match first, base subject + division otherwise — so a legacy slug lands on its
// current twin. The parse-time regex that used to live here discarded every slug without
// a "-YYYY" suffix, and all 49 foundational events carry exactly such slugs: choosing one
// held until the next reload, then the student was back at the start as if they had never
// picked anything.
const initialActiveEventSlug = localStorage.getItem('activeEventSlug') || '';

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
  courseMap: null,
  featuredLessonId: null,
  currentLesson: null,
  lessonBlockIndex: 0,
  practiceSets: [],
  practiceSession: null,
  materialFilter: 'all',
  activeEventSlug: initialActiveEventSlug,
  activeTaxonomy: null,
  accommodation: null,
  sourceCoverage: [],
  lessonReviewQueue: [],
  questionReviewQueue: [],
  contentTab: 'overview',
  lessonFilter: 'ready',
  interestFilter: 'all',
  questionServeFilter: 'blocking',
  questionScopeEvent: 'all',
  insights: null,
  insightsDetail: null,
  questionReviewLimit: 25,
  videoReviewCount: 0,
  intakeActionCount: 0,
  calibrationQueue: [],
  contentChallenges: [],
  contentReleases: [],
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
const appViews = ['dashboard', 'learn', 'practice', 'errors', 'coach', 'content', 'parent'];
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
  'Featured Trial Events': { icon: '△', accent: 'violet', skill: 'emerging-event experimentation' },
  'Season Resources': { icon: '☰', accent: 'forest', skill: 'season planning and orientation' },
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
  return (slug || '')
    .replace(/-\d{4}$/, '')
    .replace(/-trial$/, '')
    .replace(/-(b|c)$/, '');
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
  if (
    value.startsWith('/#')
    || value.startsWith('#')
    || value.startsWith('/courses/')
  ) return value;
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

// Which views each role may open. The hashchange router used the role only to pick a
// FALLBACK home, and mapped '#content' to the content view for anybody — so a signed-in
// student navigating in-app to #content got the full Content Operations surface: the review
// pipeline, the publish controls, the Content Studio upload form with its rights-declaration
// field. No data leaked, because every staff endpoint answers a student with 403, but the
// student got staff chrome and a raw role error where their app should be. A hard page load
// of the same URL redirected correctly; only in-SPA navigation slipped through.
const STUDENT_VIEWS = ['dashboard', 'learn', 'practice', 'errors'];
const VIEWS_BY_ROLE = {
  student: STUDENT_VIEWS,
  coach: [...STUDENT_VIEWS, 'coach'],
  parent: [...STUDENT_VIEWS, 'parent'],
};

function roleHomeView() {
  if (isStudentPreview()) return 'dashboard';
  if (STAFF_ROLES.includes(state.user?.role)) return 'content';
  if (state.user?.role === 'coach') return 'coach';
  if (state.user?.role === 'parent') return 'parent';
  return 'dashboard';
}

function viewAllowed(id) {
  // Staff may open anything, including the student views they preview with.
  if (STAFF_ROLES.includes(state.user?.role)) return true;
  const allowed = VIEWS_BY_ROLE[state.user?.role] || STUDENT_VIEWS;
  return allowed.includes(id);
}

function showView(id, updateHash = true) {
  if (!appViews.includes(id)) id = 'dashboard';
  if (!viewAllowed(id)) id = roleHomeView();
  showSection('app-shell');
  appViews.forEach(view => { $(view).hidden = view !== id; });
  document.querySelectorAll('[data-view-link]').forEach(link => {
    // Content Review and Teaching Insights share the workspace, so the view alone cannot say
    // which is current — the open tab does.
    const tab = link.dataset.contentTabLink;
    const active = link.dataset.viewLink === id
      && (!tab || (tab === 'insights') === (state.contentTab === 'insights'));
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

function coursePath(event = activeEvent(), suffix = '') {
  if (!event) return '/';
  return `/courses/${event.season}/${encodeURIComponent(event.slug)}${suffix}`;
}

function coursePathEvent() {
  const match = location.pathname.match(
    /^\/courses\/(\d{4})\/([^/]+)(?:\/(unit|lesson|practice|test)\/([^/]+))?\/?$/,
  );
  return match ? {
    season: Number(match[1]),
    slug: decodeURIComponent(match[2]),
    contentType: match[3] || null,
    contentSlug: match[4] ? decodeURIComponent(match[4]) : null,
  } : null;
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

// An in-app browser — the WebView opened when a link is tapped inside Instagram, Facebook,
// LinkedIn, Line and friends. Two things break here: pop-ups are blocked outright, and Google
// refuses OAuth inside embedded WebViews entirely (`disallowed_useragent`). So "allow pop-ups
// and try again" was advice that could not be followed, on a screen with no other way in for
// a Google-account user. Redirect rescues most of these; the rest need the real browser.
function isEmbeddedBrowser() {
  const ua = navigator.userAgent || '';
  if (/\b(FBAN|FBAV|FB_IAB|Instagram|Line\/|LinkedInApp|Twitter|Snapchat|Pinterest|MicroMessenger|WeChat)\b/i.test(ua)) return true;
  // iOS WebViews are Safari-shaped but lack "Safari" in the UA
  const isIOS = /iPhone|iPad|iPod/i.test(ua);
  if (isIOS && !/Safari/i.test(ua)) return true;
  // Android System WebView announces itself
  if (/\bwv\b/i.test(ua)) return true;
  return false;
}

function googleAuthErrorMessage(error) {
  const code = String(error?.code || '');
  const message = String(error?.message || '');
  if (code.includes('operation-not-allowed')) return 'Google sign-in is not enabled for this app yet. Use email and password, or ask an administrator to enable Google sign-in.';
  if (code.includes('popup-closed-by-user') || code.includes('cancelled-popup-request')) return 'The Google window was closed before finishing. Try again when you are ready.';
  if (code.includes('popup-blocked')) return 'Your browser blocked the Google window. Redirecting you to Google instead…';
  if (code.includes('unauthorized-domain')) return 'This site is not yet authorized for Google sign-in. Ask an administrator to add it in Firebase.';
  if (code.includes('disallowed-useragent') || message.includes('disallowed_useragent')) {
    return 'Google will not sign you in inside an app’s built-in browser. Open science-olympiad.com in Safari or Chrome, or use email and password below.';
  }
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

// Shared by the pop-up and the redirect return: both end with a Firebase user and the same
// question of whether this person already has a Fieldstone profile.
async function completeGoogleSignIn(firebaseUser) {
  state.token = await firebaseUser.getIdToken();
  state.refreshToken = firebaseUser.refreshToken;
  state.tokenExpiresAt = Date.now() + 55 * 60_000;
  let user;
  try {
    user = await api('/auth/me');
  } catch (error) {
    if (error.status === 401) { showGoogleProfileForm(firebaseUser); return; }
    throw error;
  }
  persistAuth({ access_token: state.token, user }, { refreshToken: state.refreshToken, expiresIn: 3300 });
}

async function continueWithGoogle(button) {
  $('auth-error').textContent = '';
  $('resend-verification').hidden = true;
  setBusy(button, true, 'Opening Google…');
  try {
    const { auth, authModule } = await loadFirebaseSdk();
    // No point opening a pop-up that this browser will swallow: go straight to redirect.
    if (isEmbeddedBrowser()) {
      sessionStorage.setItem('googleRedirectPending', '1');
      await authModule.signInWithRedirect(auth, new authModule.GoogleAuthProvider());
      return;                       // the page navigates away
    }
    const result = await authModule.signInWithPopup(auth, new authModule.GoogleAuthProvider());
    await completeGoogleSignIn(result.user);
  } catch (error) {
    const code = String(error?.code || '');
    if (code.includes('popup-blocked') || code.includes('cancelled-popup-request')) {
      // The pop-up was refused after the fact. Redirect is the same sign-in without a window.
      try {
        const { auth, authModule } = await loadFirebaseSdk();
        $('auth-error').textContent = 'Taking you to Google…';
        sessionStorage.setItem('googleRedirectPending', '1');
        await authModule.signInWithRedirect(auth, new authModule.GoogleAuthProvider());
        return;
      } catch (redirectError) {
        $('auth-error').textContent = googleAuthErrorMessage(redirectError);
        $('auth-error').focus();
        setBusy(button, false);
        return;
      }
    }
    $('auth-error').textContent = googleAuthErrorMessage(error);
    $('auth-error').focus();
  } finally { setBusy(button, false); }
}

// Coming back from signInWithRedirect. Runs before the auth screen is shown so a returning
// user is not briefly asked to sign in again with their credentials already in hand.
async function resumeGoogleRedirect() {
  if (sessionStorage.getItem('googleRedirectPending') !== '1') return false;
  sessionStorage.removeItem('googleRedirectPending');
  try {
    const { auth, authModule } = await loadFirebaseSdk();
    const result = await authModule.getRedirectResult(auth);
    if (!result?.user) return false;
    await completeGoogleSignIn(result.user);
    return true;
  } catch (error) {
    $('auth-error').textContent = googleAuthErrorMessage(error);
    return false;
  }
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
    // Two sidebar entries open the same workspace on different tabs; the link says which.
    const tab = link.dataset.contentTabLink;
    if (tab) setContentTab(tab === 'insights' ? 'insights' : state.contentTab === 'insights' ? 'overview' : state.contentTab);
  });
});

document.querySelectorAll('[data-practice-jump]').forEach(button => button.addEventListener('click', () => showView('practice')));

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0].toUpperCase()).join('') || 'SO';
}

// Khan Academy's home is "My courses": the learner's own list, not the catalog's guess.
// The subjects here are the ones this student has actually started, kept per user, with an
// explicit tile for adding more — never an auto-picked top six they don't recognise.
function mySubjectsKey() {
  return `fieldstone:my-subjects:${state.user?.id}`;
}

function mySubjectSlugs() {
  try {
    const list = JSON.parse(localStorage.getItem(mySubjectsKey()) || '[]');
    return Array.isArray(list) ? list : [];
  } catch { return []; }
}

function rememberSubject(slug) {
  if (!slug || !state.user?.id) return;
  const list = mySubjectSlugs();
  if (!list.includes(slug)) {
    list.push(slug);
    localStorage.setItem(mySubjectsKey(), JSON.stringify(list));
  }
}

function mySubjects() {
  rememberSubject(state.activeEventSlug);
  const seen = new Set();
  return mySubjectSlugs()
    .map(slug => resolveEvent(slug))
    .filter(event => {
      if (!event || seen.has(event.slug)) return false;
      seen.add(event.slug);
      return true;
    })
    .sort((a, b) => Number(b.slug === state.activeEventSlug) - Number(a.slug === state.activeEventSlug)
      || a.name.localeCompare(b.name));
}

function renderSubjects() {
  const subjects = mySubjects();
  $('subject-list').innerHTML = subjects.map(event => {
    const experience = eventExperience(event);
    const active = event.slug === state.activeEventSlug;
    return `<article class="subject-card event-accent-${experience.accent} surface${active ? ' is-active' : ''}" data-available="true">
      <div class="subject-card-heading"><span class="subject-icon" aria-hidden="true">${experience.icon}</span>${active ? '<span class="subject-current">Current</span>' : ''}${seasonBadge(event)}</div>
      <h3>${escapeHtml(event.name)}</h3><p>${escapeHtml(event.topic_focus || event.description || experience.skill)}</p>
      <div class="subject-card-meta"><span>Div ${escapeHtml(event.division)}</span><span>${event.material_count} resource${event.material_count === 1 ? '' : 's'}</span><span>${event.lesson_count} module${event.lesson_count === 1 ? '' : 's'}</span><span>${event.exam_count} exam${event.exam_count === 1 ? '' : 's'}</span></div>
      <footer>${event.lesson_count > 0 ? `<button class="subject-action-primary" type="button" data-subject="${escapeHtml(event.slug)}" data-subject-destination="learn">Learn</button>` : ''}${event.material_count > 0 || event.exam_count > 0 ? `<button type="button" data-subject="${escapeHtml(event.slug)}" data-subject-destination="practice">${event.exam_count > 0 ? 'Practice' : 'Resources'}</button>` : ''}</footer>
    </article>`;
  }).join('') + `<button type="button" id="subject-add-tile" class="subject-add-tile">
      <span class="subject-add-plus" aria-hidden="true">＋</span>
      <strong>Add another subject</strong>
      <small>Browse by interest below — most competitors train two or three events.</small>
    </button>`;
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
  $('season-chip-label').textContent = `${event.season} Season`;
  $('current-event-title').textContent = event.name;
  $('overview-event-focus').textContent = event.topic_focus || event.description || `Build ${experience.skill}.`;
  $('overview-event-availability').textContent = `${event.material_count} resource${event.material_count === 1 ? '' : 's'} · ${state.lessons.length} lesson${state.lessons.length === 1 ? '' : 's'} · ${state.practiceSets.length} skill lab${state.practiceSets.length === 1 ? '' : 's'} · ${event.exam_count} exam${event.exam_count === 1 ? '' : 's'}`;
  $('overview-learn-button').disabled = state.lessons.length === 0;
  $('overview-practice-button').disabled = (
    state.practiceSets.length === 0 && event.exam_count === 0 && event.material_count === 0
  );
  $('overview-practice-button').textContent = (
    state.practiceSets.length === 0 && event.exam_count === 0
  ) ? 'Browse Event Resources' : 'Practice This Event';
  $('dashboard-resources-button').hidden = event.material_count === 0;
  $('dashboard-resource-count').textContent = event.material_count;
  $('course-progress-label').textContent = `${percent}%`;
  $('course-progress-bar').style.width = `${percent}%`;
  $('course-progress-bar').parentElement.setAttribute('aria-valuenow', String(percent));
}

// The home page has two shapes. Until a subject is chosen it is a guided picker —
// interest categories first, then matching events — because dropping a new student
// into an auto-selected course told them nothing about what this place is or how to
// start. Once a subject exists, the plan-centred dashboard returns, with a dismissible
// strip explaining where Courses, Practice, and Review live.
function renderStudentGuidance() {
  const hasEvent = Boolean(activeEvent());
  ['dashboard-snapshot', 'daily-mission-block', 'current-event-block', 'subject-library-block']
    .forEach(id => { const el = $(id); if (el) el.hidden = !hasEvent; });
  $('student-onboarding').hidden = hasEvent;
  $('student-guide').hidden = !hasEvent || localStorage.getItem('fieldstoneHomeGuideDismissed') === '1';
  // The explorer is permanent, Khan Academy-style: for a new student it IS the home page;
  // for a returning one it sits below their subjects as the way to add another.
  $('explorer-kicker').textContent = hasEvent ? 'Explore' : 'Step 1 · Your interests';
  $('explorer-title').textContent = hasEvent ? 'Add Another Subject' : 'What kind of science excites you?';
  $('explorer-copy').textContent = hasEvent
    ? 'Browse by interest. Starting an event adds it to your subjects — nothing you already train is lost.'
    : 'Pick an interest to see matching events, or browse everything.';
  const mine = new Set(mySubjects().map(event => event.slug));
  const pool = studentEvents().filter(event => !hasEvent || !mine.has(event.slug));
  const counts = new Map();
  pool.forEach(event => {
    if (event.category) counts.set(event.category, (counts.get(event.category) || 0) + 1);
  });
  const chips = [
    ['all', 'Show everything', '☰', pool.length],
    ...[...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([category, count]) => [category, category, categoryProfiles[category]?.icon || '◇', count]),
  ];
  if (!chips.some(([key]) => key === state.interestFilter)) state.interestFilter = 'all';
  $('interest-chips').innerHTML = chips.map(([key, label, icon, count]) =>
    `<button type="button" class="interest-chip" data-interest="${escapeHtml(key)}" aria-pressed="${String(key === state.interestFilter)}"><span aria-hidden="true">${icon}</span>${escapeHtml(label)}<span class="interest-chip-count">${count}</span></button>`).join('');
  const matches = pool.filter(event => state.interestFilter === 'all' || event.category === state.interestFilter);
  $('onboarding-event-list').innerHTML = matches.map(event => {
    const experience = eventExperience(event);
    return `<article class="subject-card event-accent-${experience.accent} surface" data-available="true">
      <div class="subject-card-heading"><span class="subject-icon" aria-hidden="true">${experience.icon}</span>${seasonBadge(event)}<span class="division-badge">Div ${escapeHtml(event.division)}</span></div>
      <h3>${escapeHtml(event.name)}</h3><p>${escapeHtml(event.topic_focus || event.description || experience.skill)}</p>
      <div class="subject-card-meta"><span>${event.lesson_count} lesson${event.lesson_count === 1 ? '' : 's'}</span><span>${event.exam_count} exam${event.exam_count === 1 ? '' : 's'}</span><span>${event.material_count} resource${event.material_count === 1 ? '' : 's'}</span></div>
      <footer><button class="subject-action-primary" type="button" data-onboard-event="${escapeHtml(event.slug)}">${hasEvent ? 'Add This Subject' : 'Start With This Event'}</button></footer>
    </article>`;
  }).join('') || (pool.length
    ? '<p class="catalog-empty">Nothing in this area has published content yet — try another interest.</p>'
    : '<p class="catalog-empty">You are already training every event that has published content. New events appear here as they are released.</p>');
}

function renderEventCatalog() {
  const chips = document.querySelectorAll('[data-catalog-division]');
  if (!chips.length) return;
  if (!state.catalogDivision) {
    state.catalogDivision = ['B', 'C'].includes(state.user?.division) ? state.user.division : 'all';
  }
  chips.forEach(chip => chip.setAttribute('aria-pressed', String(chip.dataset.catalogDivision === state.catalogDivision)));
  const catalog = (state.events || [])
    // Any active event holding lessons belongs in the catalog. Listing by season_status
    // hid 49 `foundational` events carrying 360 student-visible lessons — the bulk of the
    // catalog — while showing 13 current-season events of which 7 had nothing at all. The
    // status is a label for how content was sourced, never a reason to hide it from a student.
    .filter(event => event.season_status !== 'superseded')
    .filter(event => state.catalogDivision === 'all' || event.division === state.catalogDivision)
    .sort((a, b) => (a.category || '~').localeCompare(b.category || '~') || a.name.localeCompare(b.name));
  $('event-catalog-count').textContent = catalog.length
    ? `${catalog.length} event${catalog.length === 1 ? '' : 's'}`
    : '';
  if (!catalog.length) {
    $('event-catalog-list').innerHTML = '<p class="catalog-empty">The 2026 event slate has not been imported yet. Content operations can run the catalog crawler to register it.</p>';
    return;
  }
  const groups = new Map();
  catalog.forEach(event => {
    const group = event.category
      || (event.season_status === 'prior_season_practice' ? 'Prior-season practice' : 'Other events');
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(event);
  });
  $('event-catalog-list').innerHTML = [...groups.entries()].map(([category, events]) => `
    <section class="catalog-group">
      <h3>${escapeHtml(category)}</h3>
      <div class="catalog-grid">${events.map(event => {
        const actions = [];
        if (event.lesson_count > 0) actions.push(`<button type="button" data-open-course="${event.id}" data-course-slug="${escapeHtml(event.slug)}" class="catalog-course-link">Start Course</button>`);
        if (event.exam_count > 0 || event.material_count > 0) actions.push(`<button type="button" data-open-exam-event="${escapeHtml(event.slug)}" data-event-name="${escapeHtml(event.name)}" class="catalog-exam-link">${event.exam_count > 0 ? 'Practice & Resources' : 'View Resources'}</button>`);
        return `<article class="catalog-event surface">
          <header><h4>${escapeHtml(event.name)}</h4><span class="division-badge">Div ${escapeHtml(event.division)}</span>${event.season_status === 'prior_season_practice' ? '<span class="prior-season-badge">Prior season</span>' : ''}</header>
          ${event.topic_focus ? `<p>${escapeHtml(event.topic_focus)}</p>` : ''}
          ${(event.lesson_count > 0 || event.exam_count > 0 || event.material_count > 0) ? `<div class="catalog-content-badge"><span aria-hidden="true">✦</span> ${event.material_count} resource${event.material_count === 1 ? '' : 's'} · ${event.lesson_count} lesson${event.lesson_count === 1 ? '' : 's'} · ${event.exam_count} exam${event.exam_count === 1 ? '' : 's'}</div>` : ''}
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

function materialGroup(material) {
  const purpose = material.purpose || 'reference_material';
  if (purpose === 'official_video') return 'video';
  if ([
    'sample_test', 'answer_key_and_rubric', 'tournament_results',
  ].includes(purpose)) return 'practice';
  return 'guide';
}

function materialTitle(material) {
  const raw = String(material?.title || 'Material').replaceAll('%20', ' ');
  try { return decodeURIComponent(raw); } catch { return raw; }
}

const materialGroupLabels = {
  video: { title: 'Watch & Learn', description: 'Official introductions and demonstrations', icon: '▶' },
  guide: { title: 'Guides & Handouts', description: 'Slides, worksheets, schedules, and reference material', icon: '▤' },
  practice: { title: 'Tests & Practice', description: 'Sample tests, stations, answer resources, and past results', icon: '◎' },
};

function renderMaterials() {
  const block = $('materials-block');
  if (!block) return;
  const items = (state.materials && state.materials.materials) || [];
  $('practice-material-count').textContent = items.length;
  if (!items.length) {
    block.hidden = true;
    $('materials-list').innerHTML = '';
    return;
  }
  block.hidden = false;
  document.querySelectorAll('[data-material-filter]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.materialFilter === state.materialFilter));
  });
  const visible = state.materialFilter === 'all'
    ? items : items.filter(material => materialGroup(material) === state.materialFilter);
  $('material-filter-count').textContent = `${visible.length} of ${items.length}`;
  $('materials-filter-empty').hidden = visible.length > 0;
  const groups = ['video', 'guide', 'practice']
    .map(group => [group, visible.filter(material => materialGroup(material) === group)])
    .filter(([, materials]) => materials.length);
  $('materials-list').innerHTML = groups.map(([group, materials]) => {
    const label = materialGroupLabels[group];
    return `<section class="material-group" aria-labelledby="material-group-${group}">
      <header><span class="material-group-icon" aria-hidden="true">${label.icon}</span><div><h3 id="material-group-${group}">${label.title}</h3><p>${label.description}</p></div><strong>${materials.length}</strong></header>
      <div class="materials-grid ${materials.length === 1 ? 'is-single' : ''}">${materials.map(material => {
    const url = material.url || '';
    const isPdf = material.media_type?.includes('pdf') || new URL(safeUrl(url), location.origin).pathname.toLowerCase().endsWith('.pdf');
    const kind = group === 'video' ? 'Video' : isPdf ? 'PDF' : material.has_text ? 'Article' : 'Link';
    const size = material.has_text ? `${Math.round((material.text_chars || 0) / 1000)}k chars` : 'link only';
    const guided = material.guided_lesson && state.lessons.some(lesson => lesson.id === material.guided_lesson.id)
      ? material.guided_lesson : null;
    return `<article class="material-card surface${guided ? ' material-card-guided' : ''}">
      <div class="material-card-top"><span class="material-type">${guided ? 'GUIDED LESSON' : escapeHtml((material.purpose || 'reference').replaceAll('_', ' '))}</span><span class="material-format">${kind}</span></div>
      <h3>${escapeHtml(materialTitle(material))}</h3>
      ${guided ? `<p class="material-plan"><strong>Guided lesson</strong> · ${guided.checkpoint_count || 0} quick checks</p><p class="material-summary">${escapeHtml(guided.summary || 'Watch the source, learn the key ideas, and check your understanding as you go.')}</p>` : `<p class="material-meta">${escapeHtml(material.publisher || 'Official resource')} · ${size}</p>`}
      <div class="material-actions">${guided ? `<button type="button" class="button button-dark button-compact" data-start-guided-lesson="${guided.id}">Start Lesson <span aria-hidden="true">→</span></button>` : material.has_text ? `<button type="button" class="button button-dark button-compact" data-open-material="${material.source_id}">Open Transcript</button>` : ''}${material.url ? `<a class="button ${guided || material.has_text ? 'button-secondary' : 'button-dark'} button-compact" href="${safeUrl(material.url)}" target="_blank" rel="noopener noreferrer">${group === 'video' ? 'Watch Source Video' : isPdf ? 'Open PDF' : 'Open Resource'} <span aria-hidden="true">↗</span></a>` : ''}</div>
    </article>`;
      }).join('')}</div>
    </section>`;
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
  const guided = event.target.closest('[data-start-guided-lesson]');
  if (guided) return openLesson(Number(guided.dataset.startGuidedLesson));
  const button = event.target.closest('[data-open-material]');
  if (button) openMaterial(Number(button.dataset.openMaterial));
});
$('materials-controls')?.addEventListener('click', event => {
  const button = event.target.closest('[data-material-filter]');
  if (!button) return;
  state.materialFilter = button.dataset.materialFilter;
  renderMaterials();
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
  if (state.courseMap?.units?.length) {
    $('concepts-block').hidden = true;
    $('concept-list').innerHTML = '';
    return;
  }
  $('concepts-block').hidden = concepts.length === 0;
  $('concept-list').innerHTML = concepts.map((concept, index) => `<article class="concept-row">
    <span class="concept-index">${String(index + 1).padStart(2, '0')}</span><div><h3>${escapeHtml(concept.name)}</h3><p>${escapeHtml(concept.description || 'Core competition objective')}</p></div><small>${concept.mastery_probability != null ? `${Math.round(concept.mastery_probability * 100)}% mastery` : 'Ready to learn'}</small>
  </article>`).join('');
}

function studentEvents() {
  // Every picker — Home, Courses, Practice — runs through here, so a filter here decides
  // what a student can reach at all. Scoping to the newest "current" season left three 2027
  // stub events selectable while 49 events holding 360 lessons and every startable exam sat
  // active, published, and unreachable from any menu. Duplicates are handled where they
  // belong — retired server-side as superseded, which the /events endpoint already excludes —
  // so navigation's only rule is: has content, is served.
  //
  // The student's own division still orders and filters the list — removing the season gate
  // deleted this binding along with it and left the whole workspace failing to load on
  // "division is not defined", because every view calls this before rendering anything.
  const division = state.user?.division;
  return [...state.events]
    .filter(event => event.lesson_count > 0 || event.exam_count > 0 || event.material_count > 0)
    .filter(event => !division || event.division === division || event.division === 'B/C' || event.slug === state.activeEventSlug)
    .sort((a, b) => {
      const aRank = a.division === division ? 0 : a.division === 'B/C' ? 1 : 2;
      const bRank = b.division === division ? 0 : b.division === 'B/C' ? 1 : 2;
      return Number(b.slug === state.activeEventSlug) - Number(a.slug === state.activeEventSlug)
        || Number(b.season_status === 'current') - Number(a.season_status === 'current')
        || subjectDepth(b) - subjectDepth(a)
        || aRank - bRank
        || a.name.localeCompare(b.name)
        || a.division.localeCompare(b.division);
    });
}

// The season a student is actually competing in leads; everything else is the library behind
// it. Only the badge says so — the card still reports its real lesson and exam counts, because
// a current-season event with nothing in it yet must not look ready.
function seasonBadge(event) {
  if (event.season_status === 'current') return '<span class="season-badge">Current season</span>';
  if (event.season_status === 'prior_season_practice') return '<span class="prior-season-badge">Prior season</span>';
  return '';
}

// How much a student can actually do here — the tiebreak within a season, so a course holding
// eight lessons and five exams outranks a roster entry with a single orientation page.
function subjectDepth(event) {
  return (event.exam_count > 0 ? 8 : 0)
    + (event.lesson_count >= 4 ? 4 : event.lesson_count > 0 ? 1 : 0)
    + (event.material_count >= 4 ? 2 : event.material_count > 0 ? 1 : 0);
}

function resolveEvent(slug) {
  const exact = state.events.find(event => event.slug === slug);
  if (exact) return exact;
  // The slug is gone from the catalog — a bookmark or a link to an event that has since been
  // merged into its twin. `#practice?event=heredity` kept opening an empty page after the
  // heredity/heredity-b merge, because nothing mapped the retired slug onto the survivor.
  const base = subjectKeyOf(slug);
  const division = (state.user?.division || '').toLowerCase();
  return state.events.find(event => subjectKeyOf(event.slug) === base
      && (event.division || '').toLowerCase() === division)
    || state.events.find(event => subjectKeyOf(event.slug) === base)
    || null;
}

function renderEventSelectors() {
  const event = activeEvent();
  // One list, ordered by name. Grouping by season split the picker into "2027 Season" and
  // "2026 Season" headings over what is, to a student, one set of events.
  //
  // That grouping was removed on the reasoning that duplicates were merged in the database, so
  // it only ever separated an event from itself. True until a season's course is published
  // beside the one it replaces: Dynamic Planet then appeared twice as "Dynamic Planet · Div B",
  // the 2027 freshwater course and the 2026 oceanography one, with nothing to tell them apart —
  // and a student picking the wrong one studies the wrong subject for a year. So a label is
  // qualified only when it would otherwise collide, which needs no upkeep as the catalog moves.
  const events = studentEvents()
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name) || (a.division || '').localeCompare(b.division || ''));
  const labelCounts = new Map();
  for (const item of events) {
    const key = `${item.name}·${item.division}`;
    labelCounts.set(key, (labelCounts.get(key) || 0) + 1);
  }
  const options = events.map(item => {
    const parts = [`${item.name} · Div ${item.division}`];
    if (item.season_status === 'trial') parts.push('Trial');
    if ((labelCounts.get(`${item.name}·${item.division}`) || 0) > 1) {
      // Same wording as the badge on the subject card, so the two surfaces agree.
      parts.push(item.season_status === 'prior_season_practice'
        ? 'Prior season'
        : String(item.season));
    }
    return `<option value="${escapeHtml(item.slug)}"${item.id === event?.id ? ' selected' : ''}>`
      + `${escapeHtml(parts.join(' · '))}</option>`;
  }).join('');
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
  const completed = state.lessons.filter(lesson => lesson.progress.status === 'completed').length;
  const progress = state.lessons.length ? Math.round((completed / state.lessons.length) * 100) : 0;
  const nextLesson = state.lessons.find(lesson => lesson.progress.status === 'in_progress')
    || state.lessons.find(lesson => lesson.progress.status !== 'completed')
    || state.lessons[0];
  const eventExams = state.exams.filter(exam => exam.event_id ? exam.event_id === event.id : exam.event === event.name);
  const resourceOnly = event.material_count > 0
    && state.practiceSets.length === 0
    && eventExams.length === 0;

  renderEventSelectors();
  renderEventContext('learn', event, experience);
  renderEventContext('practice', event, experience);
  $('season-chip-label').textContent = `${event.season} Season`;
  $('learn-kicker').textContent = `${event.season} course`;
  $('learn-title').textContent = event.name;
  $('learn-lede').textContent = state.courseMap?.summary || experience.focus;
  $('learning-path-title').textContent = 'Course content';
  // Without a released course map the unit count is unknown. Falling back to the lesson count
  // printed "Units 27" beside "Lessons 27" on every 2027 course, which is simply false.
  const unitCount = state.courseMap?.units?.length;
  $('learn-module-count').textContent = unitCount ?? '';
  $('learn-module-count').parentElement.hidden = unitCount == null;
  $('learn-duration').textContent = String(state.lessons.length);
  $('learn-progress-value').textContent = `${progress}%`;
  const preview = $('course-preview-banner');
  const previewMode = state.courseMap?.status;
  preview.hidden = !state.courseMap || previewMode === 'published';
  // A student has no content-operations page; the link is for staff previewing a draft.
  $('course-preview-staff-link').hidden = !STAFF_ROLES.includes(state.user?.role);
  if (previewMode === 'unreviewed_practice') {
    $('course-preview-label').textContent = 'Practice course';
    $('course-preview-copy').textContent = 'These lessons were written from cited sources and checked by automated review, but no subject expert has signed them off yet. Use Give feedback in any lesson if something looks wrong.';
  } else if (previewMode === 'student_preview') {
    $('course-preview-label').textContent = 'Student preview';
    $('course-preview-copy').textContent = 'This early course preview is not graded and does not affect mastery. Use Give feedback in any lesson to help us improve it.';
  } else if (previewMode && previewMode !== 'published') {
    $('course-preview-label').textContent = 'Staff preview';
    $('course-preview-copy').textContent = 'This draft is not visible to students. Review its teaching, evidence, and checks before release.';
  }
  state.featuredLessonId = nextLesson?.id || null;
  $('featured-event-kicker').textContent = nextLesson?.progress.status === 'completed' ? 'Review Anytime' : 'Up Next';
  $('featured-lesson-title').textContent = nextLesson?.title || 'Lessons Are Being Prepared';
  $('featured-lesson-summary').textContent = nextLesson?.summary || (event.material_count > 0
    ? `${event.name} has official resources ready to explore while the guided course is being authored.`
    : `The ${event.name} learning path is being authored and will appear here after review.`);
  $('featured-lesson-status').textContent = nextLesson ? nextLesson.progress.status.replaceAll('_', ' ') : 'In Review';
  $('featured-lesson-status').classList.toggle('attention', nextLesson?.progress.status === 'in_progress');
  $('start-featured-lesson').disabled = !nextLesson && !event.material_count;
  $('start-featured-lesson').textContent = nextLesson?.progress.status === 'in_progress' ? 'Resume Lesson →'
    : nextLesson?.progress.status === 'completed' ? 'Review Lesson →' : nextLesson ? 'Start Lesson →' : 'Browse Resources →';

  $('practice-title').textContent = resourceOnly ? `${event.name} Learning Path` : `${event.name} Practice`;
  $('practice-lede').textContent = resourceOnly
    ? 'Start with a guided lesson, then use the source materials when you want to go deeper.'
    : event.material_count > 0
    ? `Learn the idea, check your understanding, then practice ${experience.skill} with feedback and competition timing.`
    : `Train ${experience.skill} with feedback, station timing, and full mock exams.`;
  $('practice-material-count').textContent = event.material_count || 0;
  $('practice-set-count').textContent = state.practiceSets.length;
  $('practice-exam-count').textContent = eventExams.length;
  const taxonomyReady = subjectKeyOf(state.activeEventSlug) === 'entomology'
    && state.activeTaxonomy?.official_list_verified
    && state.activeTaxonomy?.image_release_ready;
  // A rotated topic is the one thing a student must read before studying: the event keeps its
  // name every season while the tested material changes under it, so "Meteorology" can be a
  // real, reviewed course and still teach the wrong year. `topic_focus` carries that sentence
  // for the events where it applies, and it belongs here, on the page the studying starts from,
  // not only on the card that was clicked to get here.
  const scopeMessage = taxonomyReady
    ? `Current-season taxonomy and specimen assets verified · ${state.activeTaxonomy.entries.length} scoped taxa.`
    : event.season_status !== 'current'
    ? [event.topic_focus, 'Foundational library · not labeled as current-season competition coverage.']
        .filter(Boolean).join(' ')
    : '';
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
    const [lessons, practiceSets, taxonomy, materials, dashboard, courseMap] = await Promise.all([
      api(`/events/${event.id}/lessons`),
      api(`/events/${event.id}/practice-sets`).catch(() => []),
      subjectKey === 'entomology' ? api(`/events/${event.id}/taxonomy`).catch(() => null) : Promise.resolve(null),
      api(`/events/${event.id}/materials`).catch(() => ({ materials: [] })),
      api(`/student/dashboard?event_slug=${encodeURIComponent(event.slug)}`),
      api(`/courses/${event.season}/${encodeURIComponent(event.slug)}`).catch(error => {
        if (error.status === 404) return null;
        throw error;
      }),
    ]);
    if (requestId !== state.eventRequestId) return;
    state.activeEventSlug = event.slug;
    localStorage.setItem('activeEventSlug', event.slug);
    state.lessons = lessons;
    state.practiceSets = practiceSets;
    state.activeTaxonomy = taxonomy;
    state.materials = materials;
    state.materialFilter = 'all';
    state.dashboard = dashboard;
    state.courseMap = courseMap;
    updateDashboard();
    renderSubjectShell();
    renderMaterials();
    showView(destination, false);
    $('learn-catalog').hidden = false;
    $('lesson-reader').hidden = true;
    $('practice-catalog').hidden = false;
    $('practice-runner').hidden = true;
    $('material-reader').hidden = true;
    if (destination === 'learn' && courseMap) {
      history.replaceState(null, '', coursePath(event));
    } else {
      const route = destination === 'dashboard' ? 'overview' : destination;
      const eventSuffix = ['learn', 'practice'].includes(destination) ? `?event=${encodeURIComponent(event.slug)}` : '';
      history.replaceState(null, '', `/#${route}${eventSuffix}`);
    }
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
  if (!state.lessons.length) {
    const event = activeEvent();
    const heading = $('lessons-empty')?.querySelector('h3');
    const copy = $('lessons-empty')?.querySelector('p');
    if (heading) heading.textContent = event?.material_count > 0 ? 'Start with official resources' : 'Course is being prepared';
    if (copy) copy.textContent = event?.material_count > 0
      ? `${event.name} does not have a guided course yet. Explore ${event.material_count} official resources while lessons are authored.`
      : `The ${event?.name || 'event'} learning path is being authored and will appear here after review.`;
    const items = (state.materials && state.materials.materials) || [];
    const resourceMarkup = items.slice(0, 6).map(material => {
      const isVideo = materialGroup(material) === 'video';
      const isPdf = material.media_type?.includes('pdf') || (material.url || '').toLowerCase().includes('.pdf');
      const action = material.has_text
        ? `<button type="button" class="button button-dark button-compact" data-open-course-material="${material.source_id}">Read in Fieldstone</button>`
        : '';
      const external = material.url
        ? `<a class="button ${action ? 'button-secondary' : 'button-dark'} button-compact" href="${safeUrl(material.url)}" target="_blank" rel="noopener noreferrer">${isVideo ? 'Watch Video' : isPdf ? 'Open PDF' : 'Open Resource'} ↗</a>`
        : '';
      return `<article class="course-resource-card"><span>${isVideo ? 'VIDEO' : isPdf ? 'PDF' : 'OFFICIAL RESOURCE'}</span><h4>${escapeHtml(materialTitle(material))}</h4><p>${escapeHtml(material.publisher || 'Science Olympiad source')}</p><div>${action}${external}</div></article>`;
    }).join('');
    const existing = $('lessons-empty')?.querySelector('.course-resource-preview');
    if (existing) existing.remove();
    if (resourceMarkup) $('lessons-empty')?.insertAdjacentHTML('beforeend', `<div class="course-resource-preview"><h4>Available now</h4><div class="course-resource-grid">${resourceMarkup}</div></div>`);
  }
  $('lesson-list').innerHTML = state.lessons.map((lesson, index) => {
    const statusLabel = lesson.progress.status === 'completed' ? 'Completed' : lesson.progress.status === 'in_progress' ? 'Resume' : 'Start';
    return `<article class="lesson-catalog-card surface">
      <span class="lesson-order">${String(index + 1).padStart(2, '0')}</span>
      <div class="lesson-card-copy"><span class="lesson-card-meta">${escapeHtml(lesson.progress.status.replaceAll('_', ' '))}</span><h3>${escapeHtml(lesson.title)}</h3><p>${escapeHtml(lesson.summary)}</p></div>
      <button class="button ${lesson.progress.status === 'not_started' ? 'button-dark' : 'button-secondary'}" type="button" data-start-lesson="${lesson.id}">${statusLabel} <span class="sr-only">${escapeHtml(lesson.title)}</span></button>
    </article>`;
  }).join('');
  $('start-featured-lesson').disabled = state.lessons.length === 0 && !(activeEvent()?.material_count > 0);
  const featured = state.lessons.find(lesson => lesson.id === state.featuredLessonId);
  $('start-featured-lesson').textContent = featured?.progress.status === 'in_progress' ? 'Resume Lesson →' : featured?.progress.status === 'completed' ? 'Review Lesson →' : 'Start Lesson →';
  const learnResources = $('learn-resources-button');
  if (learnResources) learnResources.hidden = !(activeEvent()?.material_count > 0);
  const done = state.lessons.filter(lesson => lesson.progress.status === 'completed').length;
  $('course-scope').textContent = state.lessons.length
    ? `${done} of ${state.lessons.length} complete`
    : '';
}

function masteryLabel(level = 'not_started') {
  return {
    not_started: 'Not started',
    attempted: 'Attempted',
    familiar: 'Familiar',
    proficient: 'Proficient',
    mastered: 'Mastered',
  }[level] || 'Not started';
}

function renderCourseMap() {
  const course = state.courseMap;
  const unitList = $('course-unit-list');
  const legacyList = $('lesson-list');
  if (!course?.units?.length) {
    unitList.innerHTML = '';
    unitList.hidden = true;
    legacyList.hidden = false;
    renderLessons();
    return;
  }

  unitList.hidden = false;
  legacyList.hidden = true;
  $('lessons-empty').hidden = true;
  $('learning-path-title').textContent = 'Course content';
  $('course-scope').textContent = `${course.progress.mastered_skills} of ${course.progress.total_skills} skills mastered`;
  $('learn-module-count').textContent = course.units.length;
  $('learn-module-count').parentElement.hidden = false;
  $('learn-progress-value').textContent = `${course.progress.percent}%`;

  const activeUnitIndex = Math.max(0, course.units.findIndex(unit => (
    unit.skills.some(skill => {
      const lesson = skill.lessons.find(item => item.is_primary) || skill.lessons[0];
      return lesson?.progress?.status === 'in_progress';
    })
  )));
  unitList.innerHTML = course.units.map((unit, unitIndex) => {
    const mastered = unit.skills.filter(skill => skill.mastery.level === 'mastered').length;
    const unitPercent = unit.skills.length ? Math.round((mastered / unit.skills.length) * 100) : 0;
    const skills = unit.skills.map(skill => {
      const primaryLesson = skill.lessons.find(lesson => lesson.is_primary) || skill.lessons[0];
      const lessonStatus = primaryLesson?.progress?.status || 'not_started';
      const actionLabel = lessonStatus === 'in_progress' ? 'Resume'
        : lessonStatus === 'completed' ? 'Review' : 'Learn';
      const action = primaryLesson
        ? `<a class="skill-action" href="${coursePath(activeEvent(), `/lesson/${encodeURIComponent(primaryLesson.slug)}`)}" data-start-lesson="${primaryLesson.id}" aria-label="${actionLabel} ${escapeHtml(primaryLesson.title)}">${actionLabel}<span aria-hidden="true">›</span></a>`
        : '<span class="skill-coming-soon">Lesson in review</span>';
      return `<li class="course-skill">
        <span class="mastery-dot mastery-${escapeHtml(skill.mastery.level)}" aria-hidden="true"></span>
        <div class="course-skill-copy">
          <span class="course-skill-type">Lesson</span>
          <h4>${escapeHtml(skill.name)}</h4>
          ${skill.description ? `<p>${escapeHtml(skill.description)}</p>` : ''}
          <span class="mastery-label">${escapeHtml(masteryLabel(skill.mastery.level))}</span>
        </div>
        ${action}
      </li>`;
    }).join('');
    const assessments = unit.assessments.length
      ? `<div class="unit-assessments"><span>Unit check</span>${unit.assessments.map(item => (
        course.status === 'published'
          ? `<button type="button" class="button button-secondary button-compact" data-practice-jump>${escapeHtml(item.title)}</button>`
          : `<span class="unit-assessment-draft">${escapeHtml(item.title)} · draft</span>`
      )).join('')}</div>`
      : '';
    return `<details class="course-unit"${unitIndex === activeUnitIndex ? ' open' : ''}>
      <summary class="course-unit-header">
        <span class="unit-number" aria-hidden="true">${unitIndex + 1}</span>
        <div><span>Unit ${unitIndex + 1}</span><h3>${escapeHtml(unit.title)}</h3>${unit.summary ? `<p>${escapeHtml(unit.summary)}</p>` : ''}</div>
        <div class="unit-progress"><strong>${mastered}/${unit.skills.length} skills</strong><span><i style="width:${unitPercent}%"></i></span></div>
      </summary>
      <ol class="course-skill-list">${skills}</ol>
      ${assessments}
    </details>`;
  }).join('');
}

// The card used to describe anything that was not competition-ready or foundational as
// "Reviewed competition-style practice" — which called AI-authored, unreviewed content
// reviewed, directly contradicting the "Not Expert Reviewed" badge beside it. Each class now
// says what it actually is.
function examBlurb(releaseClass, exam) {
  // Experimental Design and Write It Do It have no written test. Their practice is a drill of
  // what the scoring instrument rewards, and must not be described as a real paper's format.
  if (/\bDrill$/.test(exam?.title || '')) {
    return 'A skills drill written and machine-checked from the official scoring materials. This event has no written test, and no subject expert has read these items.';
  }
  return {
    competition_ready: 'Calibrated current-season simulation.',
    foundational_practice: 'Foundational practice with guided review.',
    imported_practice: 'Transcribed from a real past paper. Answer key not expert-reviewed.',
    study_pack_practice: 'Sample paper from a 2027 study pack. Its key was checked against the rules, not by a subject expert.',
    machine_practice: 'Written and machine-checked, in the format of a real paper. No subject expert has read it.',
    past_test: 'Past test, transcribed and not yet reviewed.',
  }[releaseClass] || 'Competition-style practice. Not expert-reviewed.';
}

function renderExams() {
  const event = activeEvent();
  const exams = state.exams.filter(exam => !event || (exam.event_id ? exam.event_id === event.id : exam.event === event.name));
  $('exam-empty').hidden = exams.length > 0;
  $('practice-exam-count').textContent = exams.length;
  $('exam-list').innerHTML = exams.map(exam => `<article class="exam-card surface">
    <div class="exam-card-main"><header><span class="event-label">${escapeHtml(exam.event)} · Div ${escapeHtml(exam.event_division || event?.division || '')}</span><span class="exam-badge release-${escapeHtml(exam.release_class)}">${escapeHtml(exam.release_label)}</span></header>
    <h3>${escapeHtml(exam.title)}</h3><p>${examBlurb(exam.release_class, exam)}</p></div>
    <dl><div><dt>Questions</dt><dd>${exam.question_count}</dd></div><div><dt>Time</dt><dd>${exam.effective_duration_minutes || exam.duration_minutes} min</dd></div></dl>
    ${exam.startable === false
      ? `<button class="button" type="button" disabled aria-disabled="true">Held For Review</button>
         <p class="exam-blocked-reason">${escapeHtml(exam.blocked_reason || 'This exam is not open for new attempts.')}</p>`
      : exam.open_attempt
        ? `<button class="button button-dark" type="button" data-start-exam="${exam.id}">Resume Exam</button>
           <p class="exam-open-attempt">${escapeHtml(openAttemptNote(exam.open_attempt))}</p>`
        : `<button class="button button-dark" type="button" data-start-exam="${exam.id}">Start Exam</button>`}
    <div class="exam-last-result" data-last-result="${exam.id}"></div>
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
    // Each exam card links to its most recent submission, so a handed-in exam can be checked
    // from the place the student started it.
    document.querySelectorAll('[data-last-result]').forEach(slot => {
      const last = rows.find(a => String(a.exam_id) === slot.dataset.lastResult);
      slot.innerHTML = last
        ? `<button class="button button-secondary" type="button" data-review-attempt="${last.attempt_id}" data-score="${last.score ?? 0}" data-max="${last.max_score ?? 0}">View your submission · ${last.ratio == null ? '—' : Math.round(last.ratio * 100) + '%'}</button>`
        : '';
    });
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

document.addEventListener('click', event => {
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
  const event = activeEvent();
  const hasPublishedExam = Boolean(event?.exam_count);
  $('practice-set-count').textContent = state.practiceSets.length;
  $('practice-sets-empty').hidden = state.practiceSets.length > 0;
  if (!state.practiceSets.length) {
    const title = $('practice-sets-empty').querySelector('h3');
    const copy = $('practice-sets-empty').querySelector('p');
    title.textContent = event?.material_count ? 'Guided practice is being calibrated' : 'Labs are in review';
    copy.textContent = event?.material_count
      ? `Start with the ${event.material_count} official resources above. Preview practice will be added after the first review pass.`
      : 'Targeted practice will appear here after the course content is reviewed.';
  }
  const mockButton = $('generate-mock');
  mockButton.disabled = !hasPublishedExam;
  mockButton.textContent = hasPublishedExam ? 'Generate Mock Exam ✦' : 'Mock Exam In Review';
  const multiplier = state.accommodation?.time_multiplier || 1;
  const stationSeconds = Math.ceil(45 * multiplier);
  $('practice-set-list').innerHTML = state.practiceSets.map((practiceSet, index) => {
    const latest = practiceSet.latest_session;
    const studyLabel = latest?.status === 'in_progress' && latest.mode === 'study' ? 'Resume Study' : 'Study Mode';
    const sprintLabel = latest?.status === 'in_progress' && latest.mode === 'station'
      ? 'Resume Sprint' : `Station · ${stationSeconds}s`;
    return `<article class="practice-set-card surface event-accent-${experience.accent}">
      <div class="practice-set-number" aria-hidden="true">${String(index + 1).padStart(2, '0')}</div>
      <div class="practice-set-copy"><span>${escapeHtml(practiceSet.practice_type.replaceAll('_', ' '))}</span><h3>${escapeHtml(practiceSet.title)}</h3><p>${escapeHtml(practiceSet.summary)}</p></div>
      <div class="practice-set-actions"><button class="button button-primary" type="button" data-start-practice-set="${practiceSet.id}" data-practice-mode="study">${studyLabel}</button><button class="button button-secondary" type="button" data-start-practice-set="${practiceSet.id}" data-practice-mode="station">${sprintLabel}</button></div>
    </article>`;
  }).join('');
}

function renderNotebook() {
  const all = state.dashboard?.open_remediation || [];
  // A case that passed its transfer check is waiting on a dated retention check. It is not an
  // open question any more, so it leaves the list and sits in a collapsed note below.
  const waiting = all.filter(item => item.status === 'delayed_review' && item.next_review_at && new Date(item.next_review_at).getTime() > Date.now());
  const cases = all.filter(item => !waiting.includes(item));
  $('error-empty').hidden = all.length > 0;
  const waitingNote = waiting.length
    ? `<details class="repair-waiting"><summary>${waiting.length} fixed — recheck scheduled</summary><ul>${waiting.map(item => `<li>${escapeHtml(item.error_type.replaceAll('_', ' '))} · recheck ${escapeHtml(new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(item.next_review_at)))}</li>`).join('')}</ul></details>`
    : '';
  $('error-notebook-list').innerHTML = waitingNote + cases.map(item => {
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
    return `<article class="remediation repair-card surface" data-case-id="${item.id}"><header><div><span class="remediation-step">${escapeHtml(item.source_type === 'practice' ? 'Evidence Lab' : 'Mock Exam')} · ${escapeHtml(item.status.replaceAll('_', ' '))}</span><h2>${escapeHtml(item.error_type.replaceAll('_', ' '))}</h2></div><span class="repair-case-number">Case ${item.id}</span></header><p class="repair-prompt">${escapeHtml(item.question_stem || 'Review the original problem and identify the evidence that changes the answer.')}</p>${evidence ? `<ul class="repair-evidence" aria-label="Evidence from the original problem">${evidence}</ul>` : ''}<div class="repair-explanation"><p class="kicker">${item.explanation_source === 'answer_key' ? 'From the answer key' : 'Why this is the answer'}</p><p>${escapeHtml(plan.explanation || item.next_action || 'Rebuild the reasoning, then prove it on an unseen problem.')}</p></div><div class="repair-action">${action}<button class="button button-secondary" type="button" data-open-tutor="remediation" data-tutor-context-id="${item.id}">Get a Grounded Hint</button><div class="case-status" data-case-status aria-live="polite"></div></div></article>`;
  }).join('');
}

function updateDashboard() {
  const firstName = (state.user.full_name || 'Competitor').split(' ')[0];
  const hasEvent = Boolean(activeEvent());
  $('welcome').textContent = hasEvent ? `Ready, ${firstName}?` : `Welcome, ${firstName}!`;
  $('today-copy').textContent = hasEvent
    ? 'Build confidence one focused session at a time.'
    : 'Two minutes to set up: pick a subject you like and your study plan is built around it.';
  $('sidebar-name').textContent = state.user.full_name;
  // The student dashboard renders after configureRoleNavigation and used to relabel the
  // sidebar unconditionally, so a staff member previewing the student app was told they were
  // a Division B student — the one place the preview should stay obvious.
  if (sessionStorage.getItem('studentView') !== '1') {
    $('sidebar-division').textContent = `Division ${state.user.division || 'B'}`;
  }
  $('user-initials').textContent = initials(state.user.full_name);
  const openCases = state.dashboard?.open_remediation || [];
  const mastery = state.dashboard?.concepts || [];
  const dailyPlan = state.dashboard?.daily_plan || { items: [], signals: {}, total_estimated_minutes: 0 };
  $('open-error-count').textContent = openCases.length;
  $('nav-error-count').textContent = openCases.length;
  $('mastery-count').textContent = mastery.filter(item => item.evidence_count > 0).length;
  $('assignment-count').textContent = dailyPlan.items.length;
  // The per-lesson minute estimate is a generation-time guess and was reported as wrong, so
  // it is gone from the student's views. The plan advertises how many steps it holds.
  $('mission-minutes').textContent = dailyPlan.items.length;
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
    return `<li class="mission-item urgency-${escapeHtml(item.urgency)}"><span class="mission-item-icon" aria-hidden="true">${missionIcons[item.type] || '◇'}</span><div><span class="mission-order">Step ${index + 1} · ${escapeHtml(item.type.replaceAll('_', ' '))}</span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.summary)}</p><small><strong>Why now:</strong> ${escapeHtml(item.why)}</small></div><div class="mission-item-action">${action}</div></li>`;
  }).join('');
  const primary = dailyPlan.items[0];
  $('continue-button').hidden = !hasEvent;
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
  renderStudentGuidance();
  renderEventCatalog();
  renderConcepts();
  renderCourseMap();
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

const STAFF_ROLES = ['admin', 'editor', 'sme', 'calibrator'];

// One answer to "which app is this person looking at", used by both the boot-time router and
// the hashchange router. They disagreed while the preview was on: the hashchange handler sent
// any staff role to `content` regardless, so switching to the student view swapped the
// navigation and then bounced the body straight back to the review workspace.
function isStudentPreview() {
  return STAFF_ROLES.includes(state.user?.role) && sessionStorage.getItem('studentView') === '1';
}

function configureRoleNavigation() {
  const isStaff = STAFF_ROLES.includes(state.user.role);
  // Staff can look at the student app without a second account. This is a navigation change,
  // not an impersonation: the API still answers with staff privileges, so the preview shows at
  // least what a student sees and sometimes more. The banner says so rather than implying a
  // fidelity the client cannot deliver.
  const previewing = isStudentPreview();
  const toggle = $('student-view-toggle');
  if (toggle) {
    toggle.hidden = !isStaff;
    toggle.querySelector('[data-toggle-label]').textContent =
      previewing ? 'Back to Content Review' : 'Preview student view';
  }
  const banner = $('student-preview-banner');
  if (banner) banner.hidden = !previewing;
  document.body.classList.toggle('student-preview', previewing);
  const mode = previewing ? 'student'
    : isStaff ? 'content'
      : state.user.role === 'coach' ? 'coach' : state.user.role === 'parent' ? 'parent' : 'student';
  document.querySelectorAll('[data-student-nav]').forEach(item => { item.hidden = mode !== 'student'; });
  document.querySelectorAll('[data-coach-nav]').forEach(item => { item.hidden = mode !== 'coach'; });
  document.querySelectorAll('[data-content-nav]').forEach(item => { item.hidden = mode !== 'content'; });
  document.querySelectorAll('[data-parent-nav]').forEach(item => { item.hidden = mode !== 'parent'; });
  $('sidebar-name').textContent = state.user.full_name;
  $('sidebar-division').textContent = previewing ? 'Student preview'
    : mode === 'content' ? 'Content operations'
      : mode === 'coach' ? 'Coach workspace' : mode === 'parent' ? 'Family workspace' : `Division ${state.user.division || 'B'}`;
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

const lessonReviewChecks = {
  editor: [
    'objective_measurable',
    'sequence_coherent',
    'reading_level_appropriate',
    'interactions_useful',
    'feedback_actionable',
    'no_ai_filler',
  ],
  sme: [
    'claims_supported',
    'citations_verified',
    'examples_accurate',
    'answer_keys_verified',
    'misconceptions_accurate',
    'competition_alignment',
  ],
};

function lessonFindingCount(lesson) {
  return (lesson.disputed_checkpoints || []).length
    + (lesson.absent_media_blocks || []).length
    + (lesson.unavailable_source_blocks || []).length
    + (lesson.evidence.length ? 0 : 1);   // ungrounded is a finding in its own right
}

function renderLessonReviewQueue() {
  const all = state.lessonReviewQueue;
  const waiting = all.filter(lesson => !['complete', 'revision_required'].includes(lesson.next_stage));
  // Same split as the question queue: a draft lesson is dark until reviewed, while a
  // published one is already serving under an "unreviewed practice" label and review
  // merely removes the label. The single big number hid that only a handful were dark.
  const dark = waiting.filter(lesson => lesson.status !== 'published');
  $('lesson-editorial-count').textContent =
    `${dark.length} dark · ${waiting.length - dark.length} live as practice · ${all.length} total`;
  const ready = all.filter(lesson => lessonFindingCount(lesson) === 0);
  const flagged = all.filter(lesson => lessonFindingCount(lesson) > 0);
  const counts = { ready: ready.length, findings: flagged.length, all: all.length };
  document.querySelectorAll('#lesson-review-filters [data-count]').forEach(node => {
    node.textContent = counts[node.dataset.count] ?? 0;
  });
  document.querySelectorAll('#lesson-review-filters [data-lesson-filter]').forEach(button => {
    button.classList.toggle('active', button.dataset.lessonFilter === state.lessonFilter);
  });
  const lessons = (state.lessonFilter === 'ready' ? ready
    : state.lessonFilter === 'findings' ? flagged
      : all.slice())
    // dark lessons first — they block students — then fewest findings, so a reviewer
    // working top-down meets the unblocking and approvable work before the polish
    .sort((a, b) => Number(a.status === 'published') - Number(b.status === 'published')
      || lessonFindingCount(a) - lessonFindingCount(b));
  $('lesson-review-empty').hidden = all.length > 0;
  $('lesson-review-queue').innerHTML = lessons.map(lesson => {
    const stage = lesson.next_stage;
    const sameEditor = stage === 'sme' && lesson.decisions.some(
      decision => decision.stage === 'editor'
        && decision.decision === 'approved'
        && decision.reviewer_user_id === state.user.id,
    );
    const canReview = stage === 'editor'
      ? ['editor', 'admin'].includes(state.user.role)
      : stage === 'sme'
        ? ['sme', 'admin'].includes(state.user.role) && !sameEditor
        : false;
    const stageLabel = {
      editor: 'Needs editorial review',
      sme: 'Needs scientific review',
      complete: 'Human review complete',
      revision_required: 'Revision required',
    }[stage] || stage.replaceAll('_', ' ');
    const lessonBlocks = lesson.blocks.map((block, index) => (
      `<li><span>${index + 1}</span><div><strong>${escapeHtml(block.heading || block.type.replaceAll('_', ' '))}</strong><small>${escapeHtml(block.type.replaceAll('_', ' '))}${block.checkpoint ? ` · ${escapeHtml(block.checkpoint)}` : ''}</small></div></li>`
    )).join('');
    const evidence = lesson.evidence.length ? lesson.evidence.map(item => {
      const use = item.blocks.length
        ? item.blocks.map(block => block.heading || block.type).filter(Boolean).join(' · ')
        : 'Lesson citation';
      return `<details class="lesson-evidence">
        <summary><span><strong>${escapeHtml(item.source_title)}</strong><small>${escapeHtml(item.locator)} · ${escapeHtml(use)}</small></span><span>View passage</span></summary>
        <blockquote>${escapeHtml(item.text || 'The retained passage is missing.')}</blockquote>
        <footer><span translate="no">Snapshot ${escapeHtml((item.snapshot_hash || 'missing').slice(0, 12))}</span>${item.source_url ? `<a href="${safeUrl(item.source_url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ''}</footer>
      </details>`;
    }).join('') : '<p class="citation-missing">No retained source passages are attached. Approval must remain blocked.</p>';
    const decisionHistory = lesson.decisions.length
      ? `<ul class="lesson-review-history">${lesson.decisions.map(decision => `<li><strong>${escapeHtml(decision.stage)}</strong> · ${escapeHtml(decision.decision.replaceAll('_', ' '))}${decision.notes ? `<span>${escapeHtml(decision.notes)}</span>` : ''}</li>`).join('')}</ul>`
      : '<p class="review-waiting">No human decision has been recorded for this version.</p>';
    let actions = '';
    if (canReview) {
      const checks = lessonReviewChecks[stage].map(check => `<label class="review-check"><input type="checkbox" name="${escapeHtml(check)}"><span>${escapeHtml(check.replaceAll('_', ' '))}</span></label>`).join('');
      actions = `<fieldset class="review-checklist"><legend>${stage === 'editor' ? 'Editorial lesson checklist' : 'Scientific lesson checklist'}</legend>${checks}</fieldset>
        <label class="review-notes">Review notes<textarea name="lesson-review-notes" rows="3" maxlength="4000" placeholder="Record specific evidence or actionable revision guidance…"></textarea></label>
        <div class="review-actions"><button class="button button-secondary" type="button" data-lesson-review-decision="rewrite_required" data-lesson-id="${lesson.id}" data-lesson-review-stage="${stage}">Request revision</button><button class="button button-primary" type="button" data-lesson-review-decision="approved" data-lesson-id="${lesson.id}" data-lesson-review-stage="${stage}">Approve ${stage === 'editor' ? 'editorial' : 'scientific'} review</button></div>`;
    } else if (sameEditor) {
      actions = '<p class="review-waiting">A different person must complete the scientific review.</p>';
    } else if (stage === 'complete') {
      actions = '<p class="lesson-review-complete">Editor and independent SME approvals are recorded. Release remains blocked until claims, sources, assessments, and course gates pass.</p>';
    } else if (stage === 'revision_required') {
      actions = '<p class="citation-missing">This exact version cannot be approved again. Revise the lesson and create a new version.</p>';
    } else {
      actions = `<p class="review-waiting">Waiting for a ${escapeHtml(stage)} reviewer.</p>`;
    }
    // Automated findings, shown before the reviewer opens anything. These were already in
    // the API response and invisible on screen, which made a triaged queue read as a flat one.
    const findingChips = [];
    const disputed = lesson.disputed_checkpoints || [];
    const danglingBlocks = lesson.unavailable_source_blocks || [];
    const absentMedia = lesson.absent_media_blocks || [];
    if (disputed.length) findingChips.push(`<span class="review-flag review-flag-strong">${disputed.length} checkpoint${disputed.length === 1 ? '' : 's'} an independent judge disputed</span>`);
    if (absentMedia.length) findingChips.push(`<span class="review-flag">${absentMedia.length} block${absentMedia.length === 1 ? '' : 's'} read a figure this lesson never shows</span>`);
    if (danglingBlocks.length) findingChips.push(`<span class="review-flag">${danglingBlocks.length} block${danglingBlocks.length === 1 ? '' : 's'} cite material the student was not given</span>`);
    const findings = findingChips.length
      ? `<div class="review-flags">${findingChips.join('')}</div>
         <details class="lesson-review-detail"><summary>What the automated checks found (${disputed.length + absentMedia.length + danglingBlocks.length})</summary><ul class="lesson-review-findings">
         ${disputed.map(item => `<li><strong>${escapeHtml(item.heading || 'Checkpoint')}</strong><small>${escapeHtml(item.verdict || 'disputed')}${item.solver_choice !== null && item.solver_choice !== undefined ? ` · solver chose ${item.solver_choice}, key is ${item.key}` : ''}${(item.verifier_errors || []).length ? ` · ${escapeHtml(String(item.verifier_errors[0]).slice(0, 140))}` : ''}${item.model_written ? ' · model-written' : ''}</small></li>`).join('')}
         ${absentMedia.map(item => `<li><strong>${escapeHtml(item.heading || item.type)}</strong><small>reads a figure this lesson does not show${item.assessed ? ' · this one is assessed' : ''}</small></li>`).join('')}
         ${danglingBlocks.map(item => `<li><strong>${escapeHtml(item.heading || item.type)}</strong><small>refers to “${escapeHtml(item.phrase || 'the source')}”${item.assessed ? ' · this one is assessed' : ''}</small></li>`).join('')}
         </ul></details>`
      : '<div class="review-flags"><span class="review-flag review-flag-clear">No automated finding on this lesson</span></div>';
    // Collapsed by default. Twenty-four expanded cards is a page you scroll past rather than
    // read, which is how a reviewer ends up seeing "nothing to review": the work was below
    // the fold. The summary row carries enough to triage without opening anything.
    const flagCount = disputed.length + absentMedia.length + danglingBlocks.length;
    return `<article class="lesson-review-card surface" data-lesson-review-card="${lesson.id}">
      <details class="lesson-review-shell">
      <summary class="lesson-review-summary">
        <span class="lesson-review-summary-main">
          <strong>${escapeHtml(lesson.title)}</strong>
          <small>${escapeHtml(lesson.unit?.title || lesson.event.name)} · ${lesson.estimated_minutes} min · ${lesson.blocks.length} sections · ${lesson.evidence.length} source passage${lesson.evidence.length === 1 ? '' : 's'}</small>
        </span>
        <span class="lesson-review-summary-flags">
          ${flagCount ? `<span class="review-flag review-flag-strong">${flagCount} finding${flagCount === 1 ? '' : 's'}</span>` : '<span class="review-flag review-flag-clear">clean</span>'}
          <span class="coverage-release ${stage === 'complete' ? 'ready' : 'blocked'}">${escapeHtml(stageLabel)}</span>
        </span>
      </summary>
      <header><div><span class="coverage-season">${escapeHtml(lesson.event.name)}${lesson.unit?.title ? ` · ${escapeHtml(lesson.unit.title)}` : ''} · Version ${lesson.version}</span><p>${escapeHtml(lesson.summary)}</p></div></header>
      <div class="lesson-review-actions"><a class="button button-primary button-compact" href="${escapeHtml(safeActionUrl(lesson.preview_url))}" target="_blank" rel="noopener">Walk through as a student ↗</a><span>${lesson.evidence.length} source passages</span></div>
      ${findings}
      <details class="lesson-review-detail"><summary>Inspect lesson sequence</summary><ol class="lesson-review-blocks">${lessonBlocks}</ol></details>
      <details class="lesson-review-detail"><summary>Inspect exact source evidence (${lesson.evidence.length})</summary><div class="lesson-evidence-list">${evidence}</div></details>
      <details class="lesson-review-detail"><summary>Decision history (${lesson.decisions.length})</summary>${decisionHistory}</details>
      ${actions}<div class="review-status" role="status" aria-live="polite"></div>
      </details>
    </article>`;
  }).join('');
}

// A pending question is "blocking" when nothing serves it — no published exam and no
// published skill lab — so students cannot see it until someone decides. Everything else
// is live as labelled practice, where review is a promotion. Two different kinds of work;
// the queue was messy because it summed them.
function questionIsBlocking(question) {
  return !question.serving_students;
}

function renderQuestionReviewQueue() {
  const allQuestions = state.questionReviewQueue;
  const blocking = allQuestions.filter(questionIsBlocking);
  const serving = allQuestions.filter(question => !questionIsBlocking(question));
  const counts = { blocking: blocking.length, serving: serving.length, all: allQuestions.length };
  document.querySelectorAll('[data-question-serve-count]').forEach(node => {
    node.textContent = counts[node.dataset.questionServeCount] ?? 0;
  });
  document.querySelectorAll('[data-question-serve]').forEach(button => {
    button.classList.toggle('active', button.dataset.questionServe === state.questionServeFilter);
  });
  const scope = $('question-event-filter');
  if (scope) {
    const eventsById = new Map(state.events.map(event => [event.id, event]));
    const inQueue = [...new Set(allQuestions.map(question => question.event_id))]
      .map(id => ({ id, name: eventsById.get(id)?.name || `Event ${id}`,
        n: allQuestions.filter(question => question.event_id === id).length }))
      .sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
    scope.innerHTML = '<option value="all">All events</option>' + inQueue.map(row =>
      `<option value="${row.id}">${escapeHtml(row.name)} · ${row.n}</option>`).join('');
    scope.value = String(state.questionScopeEvent);
    if (scope.value === '') { state.questionScopeEvent = 'all'; scope.value = 'all'; }
  }
  const filtered = (state.questionServeFilter === 'blocking' ? blocking
    : state.questionServeFilter === 'serving' ? serving : allQuestions)
    .filter(question => state.questionScopeEvent === 'all'
      || question.event_id === Number(state.questionScopeEvent));
  // 500 fully-expanded cards rendered at once made this section 390,000 pixels tall —
  // 84% of the page — and buried every other queue. Render a page of it at a time.
  const questions = filtered.slice(0, state.questionReviewLimit);
  $('editorial-count').textContent = `${filtered.length} Shown · ${allQuestions.length} Total`;
  $('question-review-empty').hidden = allQuestions.length > 0;
  const remaining = filtered.length - questions.length;
  const showMore = remaining > 0
    ? `<button class="button button-secondary" type="button" data-question-show-more>Show ${Math.min(25, remaining)} more · ${remaining} remaining</button>`
    : '';
  $('question-review-queue').innerHTML = questions.map(question => {
    const stage = question.status === 'machine_validated' ? 'editor' : question.status === 'editor_reviewed' ? 'sme' : 'publish';
    // The decisive signals, on the card. `gates_run` is shown rather than assumed: most of
    // the catalog predates the blind solver, and an absent gate must not read as a passed one.
    const ev = question.review_evidence || {};
    const itemChips = [];
    if (!ev.gates_run) itemChips.push('<span class="review-flag review-flag-strong">never blind-solved — no automated evidence</span>');
    else {
      itemChips.push(ev.solver_agreed
        ? '<span class="review-flag review-flag-clear">blind solver reproduced the key</span>'
        : `<span class="review-flag review-flag-strong">solver disagreed${ev.solver_verdict ? ` · ${escapeHtml(ev.solver_verdict.replaceAll('_', ' '))}` : ''}</span>`);
      if (ev.verifier_passed === false) itemChips.push(`<span class="review-flag review-flag-strong">verifier objected${(ev.verifier_errors || []).length ? ` · ${escapeHtml(String(ev.verifier_errors[0]).slice(0, 120))}` : ''}</span>`);
      if ((ev.max_similarity || 0) > 0.8) itemChips.push(`<span class="review-flag">near-duplicate ${Number(ev.max_similarity).toFixed(2)}</span>`);
    }
    itemChips.push(question.serving_students
      ? '<span class="review-flag review-flag-clear">live as labelled practice — review promotes it</span>'
      : '<span class="review-flag">not serving students yet — review unblocks it</span>');
    const itemFindings = `<div class="review-flags">${itemChips.join('')}</div>`;
    const canReview = stage === 'editor' ? ['editor', 'admin'].includes(state.user.role) : stage === 'sme' ? ['sme', 'admin'].includes(state.user.role) : false;
    const correct = question.choices[question.answer_spec.correct_index] || 'Answer key unavailable';
    const citations = question.citation_evidence?.length ? question.citation_evidence.map(citation => `<article class="citation-evidence"><header><strong>${escapeHtml(citation.source_title)}</strong><span>${citation.approved && citation.snapshot_id ? 'Verified Snapshot' : 'Evidence Gap'}</span></header><p>${escapeHtml(citation.claim_text || 'Claim unavailable')}</p><blockquote>${escapeHtml(citation.evidence_excerpt || 'No evidence excerpt supplied.')}</blockquote><footer><span>${escapeHtml(citation.locator || 'No locator')}</span>${citation.source_url ? `<a href="${safeUrl(citation.source_url)}" target="_blank" rel="noopener noreferrer">Open Source <span aria-hidden="true">↗</span></a>` : ''}</footer><small translate="no">Snapshot ${escapeHtml((citation.snapshot_hash || 'missing').slice(0, 12))}</small></article>`).join('') : '<p class="citation-missing">No source evidence is attached. Publication will remain blocked.</p>';
    const checks = canReview ? reviewChecks[stage].map(check => `<label class="review-check"><input type="checkbox" name="${escapeHtml(check)}"><span>${escapeHtml(check.replaceAll('_', ' '))}</span></label>`).join('') : '';
    let actions = '<p class="review-waiting">Waiting for the next independent review role.</p>';
    if (canReview) actions = `<fieldset class="review-checklist"><legend>${stage === 'editor' ? 'Editorial checklist' : 'Scientific checklist'}</legend>${checks}</fieldset><label class="review-notes">Review Notes<textarea name="review-notes" rows="3" maxlength="4000" placeholder="Record evidence, ambiguity, or revision guidance…"></textarea></label><div class="review-actions"><button class="button button-secondary" type="button" data-review-decision="rewrite_required" data-question-id="${question.id}" data-review-stage="${stage}">Request Rewrite</button><button class="button button-primary" type="button" data-review-decision="approved" data-question-id="${question.id}" data-review-stage="${stage}">Approve ${stage === 'editor' ? 'Editorial Review' : 'Scientific Review'}</button></div>`;
    else if (stage === 'publish' && ['sme', 'admin'].includes(state.user.role)) actions = `<div class="review-actions"><button class="button button-primary" type="button" data-publish-question="${question.id}">Publish Question</button></div>`;
    return `<article class="question-review-card surface" data-question-card="${question.id}"><header><div><span class="coverage-season">Version ${question.version}</span><h3>${escapeHtml(question.stem)}</h3></div><span class="coverage-release ${stage === 'publish' ? 'ready' : 'blocked'}">${escapeHtml(question.status.replaceAll('_', ' '))}</span></header>${itemFindings}<ol class="review-choices">${question.choices.map((choice, index) => `<li${index === question.answer_spec.correct_index ? ' class="correct"' : ''}>${escapeHtml(choice)}</li>`).join('')}</ol><details><summary>Answer, Rationale & Quality Signals</summary><div class="review-evidence"><p><strong>Key:</strong> ${escapeHtml(correct)}</p><p>${escapeHtml(question.explanation || 'No rationale supplied.')}</p><p><strong>Validation:</strong> ${question.validation_report.passed ? 'Passed' : 'Blocked'} · <strong>Similarity:</strong> ${escapeHtml((question.similarity_report || {}).outcome || 'Not calculated')} · <strong>Citations:</strong> ${question.citations.length}</p><div class="citation-evidence-list">${citations}</div></div></details>${actions}<div class="review-status" aria-live="polite"></div></article>`;
  }).join('') + showMore;
}

function renderContentReleases() {
  const rows = state.contentReleases || [];
  $('content-release-empty').hidden = rows.length > 0;
  $('content-release-list').innerHTML = rows.map(course => {
    const blockers = course.blockers.length
      ? `<ul class="release-blockers">${course.blockers.slice(0, 8).map(blocker => `<li>${escapeHtml(blocker.replaceAll('_', ' '))}</li>`).join('')}</ul>`
      : '<p class="release-ready-note">All machine and human gates are satisfied.</p>';
    const canRelease = course.release_ready;
    const actions = `<div class="release-actions">
      <button class="button button-secondary button-compact" type="button" data-release-decision="preview" data-course-id="${course.id}" ${canRelease ? '' : 'disabled'}>Preview for students</button>
      <button class="button button-primary button-compact" type="button" data-release-decision="published" data-course-id="${course.id}" ${canRelease ? '' : 'disabled'}>Publish</button>
      ${['student_preview', 'published'].includes(course.status) ? `<button class="button button-quiet button-compact" type="button" data-release-decision="withdrawn" data-course-id="${course.id}">Withdraw</button>` : ''}
      <button class="button button-quiet button-compact" type="button" data-release-history="${course.id}">View release history</button>
    </div>`;
    return `<article class="content-release-row surface" data-release-row="${course.id}">
      <header><div><span class="coverage-season">${escapeHtml(course.event ? `${course.event.season} · ${course.event.division}` : 'Unmapped event')} · Version ${course.version}</span><h3>${escapeHtml(course.title)}</h3><p>${escapeHtml(course.release_notes || 'No release notes recorded.')}</p></div><span class="coverage-release ${course.release_ready ? 'ready' : 'blocked'}">${escapeHtml(course.status.replaceAll('_', ' '))}</span></header>
      <div class="release-gate-summary"><strong>${course.release_ready ? 'Release ready' : 'Release blocked'}</strong><span>${course.blockers.length} blocker${course.blockers.length === 1 ? '' : 's'}</span></div>
      ${blockers}${actions}<details class="release-history" data-release-history-panel hidden><summary>Release history</summary><div class="release-history-body"><p class="review-waiting">Loading history…</p></div></details><p class="review-status" role="status" aria-live="polite"></p>
    </article>`;
  }).join('');
}

async function loadContentReleases() {
  try {
    state.contentReleases = await api('/content/releases');
    renderContentReleases();
  } catch (error) { toast(`Releases could not load. ${error.message}`); }
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

function setContentTab(tab) {
  state.contentTab = tab;
  document.querySelectorAll('#content [data-cr-panel]').forEach(panel => {
    panel.classList.toggle('cr-panel-hidden', panel.dataset.crPanel !== tab);
  });
  document.querySelectorAll('#content-tabs [data-cr-tab]').forEach(button => {
    const active = button.dataset.crTab === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  // Switching tabs inside the workspace moves the sidebar highlight too, since Teaching
  // Insights is a destination there rather than only a tab.
  const onWorkspace = !$('content').hidden;
  document.querySelectorAll('[data-content-tab-link]').forEach(link => {
    const active = onWorkspace && (link.dataset.contentTabLink === 'insights') === (tab === 'insights');
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
  });
  if (onWorkspace) history.replaceState(null, '', tab === 'insights' ? '#insights' : '#content');
  // Insights aggregates the whole activity history; compute it when someone looks,
  // not on every workspace load.
  if (tab === 'insights' && !state.insights) loadContentInsights().catch(() => {});
}

async function loadContentInsights(button = null) {
  setBusy(button, true, 'Computing…');
  const status = $('insights-status');
  status.hidden = false;
  status.textContent = 'Loading insights…';
  try {
    state.insights = await api('/content/insights');
    renderContentInsights();
  } catch (error) {
    status.textContent = `Insights could not load. ${error.message}`;
  } finally { setBusy(button, false); }
}

function renderContentInsights() {
  const data = state.insights;
  if (!data) return;
  $('insights-totals').textContent =
    `${data.totals.participating_students} of ${data.totals.active_students} students participating · ${data.totals.events_reported} subjects`;
  // 56 subjects is too many to scan, so the table is filtered rather than paged: staff
  // arrive knowing the subject they care about.
  const query = ($('insights-search')?.value || '').trim().toLowerCase();
  // "div c" is how staff say it, so the division reads as "div c" here rather than a bare "c"
  // that would match half the alphabet soup of slugs.
  const rows = query
    ? data.events.filter(row => `${row.event.name} div ${row.event.division} ${row.event.season} ${row.event.slug}`
      .toLowerCase().includes(query))
    : data.events;
  const count = $('insights-search-count');
  if (count) count.textContent = query ? `${rows.length} of ${data.events.length} subjects match “${query}”` : '';
  $('insights-table').hidden = rows.length === 0;
  $('insights-status').hidden = rows.length > 0;
  if (!rows.length) {
    // clear the body too, or the previous search's rows sit in the DOM behind a hidden table
    $('insights-rows').innerHTML = '';
    $('insights-status').textContent = query
      ? `No subject matches “${query}”.`
      : 'No subjects with published content yet.';
    return;
  }
  const flagLabels = {
    no_participation: 'no students yet',
    recall_heavy: 'recall-heavy questions',
    possibly_too_easy: 'possibly too easy',
    insufficient_response_data: 'too few answers to judge difficulty',
  };
  const warnFlags = new Set(['possibly_too_easy', 'no_participation', 'recall_heavy']);
  $('insights-rows').innerHTML = rows.map(row => {
    const issues = row.issues.open_challenges + row.issues.open_remediation + row.issues.missing_answer_keys;
    const flags = row.flags.map(flag =>
      `<span class="insight-flag${warnFlags.has(flag) ? ' insight-flag-warn' : ''}">${flagLabels[flag] || flag}</span>`).join('');
    const mix = row.questions.total
      ? `${row.questions.total}<small>${Math.round((row.questions.recall_share || 0) * 100)}% recall</small>`
      : '—';
    return `<tr class="insights-row${state.insightsDetail?.event?.id === row.event.id ? ' is-open' : ''}" data-insight-event="${row.event.id}" tabindex="0" role="button" aria-label="Open ${escapeHtml(row.event.name)} Division ${escapeHtml(row.event.division)}">
      <td><strong>${escapeHtml(row.event.name)}</strong><small>Div ${escapeHtml(row.event.division)} · ${row.event.season}</small>${flags ? `<div class="insight-flags">${flags}</div>` : ''}</td>
      <td>${row.participation.students}${row.participation.active_last_30d ? `<small>${row.participation.active_last_30d} this month</small>` : ''}</td>
      <td>${row.lessons.completions}${row.lessons.in_progress ? `<small>+${row.lessons.in_progress} in progress</small>` : ''}<small>${row.published.lessons} published</small></td>
      <td>${row.exams.attempts}${row.exams.submitted ? `<small>${row.exams.submitted} submitted</small>` : ''}</td>
      <td>${row.exams.avg_score_pct == null ? '—' : `${row.exams.avg_score_pct}%`}</td>
      <td>${row.responses.correct_pct == null ? '—' : `${row.responses.correct_pct}%`}<small>${row.responses.graded} graded</small></td>
      <td>${mix}</td>
      <td>${issues ? `<strong>${issues}</strong><small>${[
        row.issues.open_challenges && `${row.issues.open_challenges} challenge${row.issues.open_challenges === 1 ? '' : 's'}`,
        row.issues.open_remediation && `${row.issues.open_remediation} remediation`,
        row.issues.missing_answer_keys && `${row.issues.missing_answer_keys} keyless`,
      ].filter(Boolean).join(' · ')}</small>` : '0'}</td>
    </tr>`;
  }).join('');
}

async function openInsightDetail(eventId) {
  const panel = $('insights-detail');
  panel.hidden = false;
  panel.innerHTML = '<p class="insights-status">Loading subject…</p>';
  panel.scrollIntoView({ behavior: preferredScrollBehavior(), block: 'nearest' });
  try {
    state.insightsDetail = await api(`/content/insights/${eventId}`);
  } catch (error) {
    panel.innerHTML = `<p class="insights-status">Could not open this subject. ${escapeHtml(error.message)}</p>`;
    return;
  }
  renderInsightDetail();
  renderContentInsights();
}

function renderInsightDetail() {
  const data = state.insightsDetail;
  const panel = $('insights-detail');
  if (!data) { panel.hidden = true; return; }
  const pct = value => (value == null ? '—' : `${value}%`);
  const when = value => (value ? new Date(value).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '—');

  const students = data.students.length
    ? `<table class="insights-subtable"><thead><tr><th scope="col">Student</th><th scope="col">Lessons done</th><th scope="col">Exam attempts</th><th scope="col">Avg score</th><th scope="col">Correct rate</th><th scope="col">Last active</th></tr></thead><tbody>${
      data.students.map(s => `<tr>
        <td><strong>${escapeHtml(s.name)}</strong><small>Div ${escapeHtml(s.division || '—')}</small></td>
        <td>${s.lessons_completed}${s.lessons_in_progress ? `<small>+${s.lessons_in_progress} in progress</small>` : ''}</td>
        <td>${s.attempts}</td><td>${pct(s.avg_score_pct)}</td><td>${pct(s.correct_pct)}</td><td>${when(s.last_active)}</td>
      </tr>`).join('')}</tbody></table>`
    : '<p class="insights-status">No student has started this subject yet.</p>';

  const lessons = data.lessons.length
    ? `<table class="insights-subtable"><thead><tr><th scope="col">Course</th><th scope="col">Status</th><th scope="col">Completed</th><th scope="col">In progress</th></tr></thead><tbody>${
      data.lessons.map(l => `<tr>
        <td><strong>${escapeHtml(l.title)}</strong><small>${l.estimated_minutes} min · v${l.version}</small></td>
        <td><span class="insight-flag${l.status === 'published' ? '' : ' insight-flag-warn'}">${escapeHtml(l.status.replaceAll('_', ' '))}</span></td>
        <td>${l.completions}</td><td>${l.in_progress}</td>
      </tr>`).join('')}</tbody></table>`
    : '<p class="insights-status">This subject has no courses yet.</p>';

  const exams = data.exams.length
    ? `<table class="insights-subtable"><thead><tr><th scope="col">Exam</th><th scope="col">Visibility</th><th scope="col">Questions</th><th scope="col">Attempts</th><th scope="col">Avg score</th></tr></thead><tbody>${
      data.exams.map(x => `<tr>
        <td><strong>${escapeHtml(x.title)}</strong>${x.disposition ? `<small>${escapeHtml(String(x.disposition).replaceAll('_', ' '))}</small>` : ''}</td>
        <td><span class="insight-flag${x.published ? '' : ' insight-flag-warn'}">${x.published ? 'published' : 'draft'}</span></td>
        <td>${x.items}</td><td>${x.attempts}</td><td>${pct(x.avg_score_pct)}</td>
      </tr>`).join('')}</tbody></table>`
    : '<p class="insights-status">This subject has no exams yet.</p>';

  panel.innerHTML = `
    <header class="insights-detail-head">
      <div><p class="kicker">Subject detail</p><h3>${escapeHtml(data.event.name)}</h3>
        <p>Division ${escapeHtml(data.event.division)} · ${data.event.season} season · ${data.students.length} student${data.students.length === 1 ? '' : 's'} · ${data.lessons.length} course${data.lessons.length === 1 ? '' : 's'} · ${data.exams.length} exam${data.exams.length === 1 ? '' : 's'}</p></div>
      <button type="button" class="button button-secondary button-compact" data-close-insight-detail>Close</button>
    </header>
    <h4>Students</h4>${students}
    <h4>Courses</h4>${lessons}
    <h4>Exams</h4>${exams}`;
}

$('insights-search')?.addEventListener('input', () => renderContentInsights());

$('content-insights')?.addEventListener('click', event => {
  if (event.target.closest('[data-close-insight-detail]')) {
    state.insightsDetail = null;
    $('insights-detail').hidden = true;
    renderContentInsights();
    return;
  }
  const row = event.target.closest('[data-insight-event]');
  if (row) openInsightDetail(Number(row.dataset.insightEvent)).catch(error => toast(error.message));
});

$('content-insights')?.addEventListener('keydown', event => {
  const row = event.target.closest('[data-insight-event]');
  if (!row || (event.key !== 'Enter' && event.key !== ' ')) return;
  event.preventDefault();
  openInsightDetail(Number(row.dataset.insightEvent)).catch(error => toast(error.message));
});

function updateContentTabBadges() {
  const setCount = (id, value) => {
    const el = $(id);
    if (!el) return;
    el.hidden = !value;
    // No cap. "99+" on a queue of 1,444 reads as "a bit of work left" and hides an order of
    // magnitude — the backlog size is the whole point of the badge.
    el.textContent = String(value || '');
  };
  const lessonsWaiting = state.lessonReviewQueue.filter(
    lesson => !['complete', 'revision_required'].includes(lesson.next_stage));
  // Badges carry the number that demands attention: items students cannot see until a
  // human decides. Work already live as labelled practice is real but not urgent, and
  // summing the two made every tab shout three-digit numbers at whoever signed in.
  const lessonsDark = lessonsWaiting.filter(lesson => lesson.status !== 'published').length;
  const questionsBlocked = state.questionReviewQueue.filter(questionIsBlocking).length;
  setCount('tab-count-lessons', lessonsDark);
  setCount('tab-count-questions', questionsBlocked);
  setCount('tab-count-videos', state.videoReviewCount);
  setCount('tab-count-intake', state.intakeActionCount);
  const coverageGaps = state.sourceCoverage.reduce(
    (total, card) => total + (card.summary.required_sources - card.summary.monitored_required_sources), 0);
  setCount('tab-count-coverage', coverageGaps);
  const opsCount = state.contentChallenges.filter(challenge => ['submitted', 'triaged'].includes(challenge.status)).length
    + state.calibrationQueue.length;
  setCount('tab-count-ops', opsCount);
  renderContentOverview({
    intake: state.intakeActionCount,
    lessonsBlocked: lessonsDark, lessonsLive: lessonsWaiting.length - lessonsDark,
    questionsBlocked, questionsLive: state.questionReviewQueue.length - questionsBlocked,
    videos: state.videoReviewCount, ops: opsCount, coverage: coverageGaps,
  });
}

// The Start Here panel repeats the tab badges as step counts, plus one sentence naming
// today's bottleneck — the answer to "where do I start?" that the raw queues never gave.
// Blocked work (dark until a human decides) is stated separately from items already live
// as labelled practice, where review is a promotion, not an unblocking.
function renderContentOverview(counts) {
  const step = (id, blocked, live) => {
    const el = $(id);
    if (!el) return;
    const parts = [];
    if (blocked) parts.push(`${blocked} blocked`);
    if (live) parts.push(`${live} live as practice`);
    el.textContent = parts.join(' · ') || 'Clear';
    el.classList.toggle('has-work', Boolean(blocked));
  };
  step('step-count-intake', counts.intake, 0);
  step('step-count-lessons', counts.lessonsBlocked, counts.lessonsLive);
  step('step-count-questions', counts.questionsBlocked, counts.questionsLive);
  step('step-count-videos', counts.videos, 0);
  const opsEl = $('step-count-ops');
  if (opsEl) {
    const parts = [];
    if (counts.ops) parts.push(`${counts.ops} item${counts.ops === 1 ? '' : 's'} waiting`);
    if (counts.coverage) parts.push(`${counts.coverage} source gap${counts.coverage === 1 ? '' : 's'}`);
    opsEl.textContent = parts.join(' · ') || 'Clear';
    opsEl.classList.toggle('has-work', Boolean(counts.ops || counts.coverage));
  }
  const blocked = [
    counts.lessonsBlocked && `${counts.lessonsBlocked} lesson${counts.lessonsBlocked === 1 ? '' : 's'}`,
    counts.questionsBlocked && `${counts.questionsBlocked} question${counts.questionsBlocked === 1 ? '' : 's'}`,
    counts.videos && `${counts.videos} video${counts.videos === 1 ? '' : 's'}`,
  ].filter(Boolean);
  const liveTotal = (counts.lessonsLive || 0) + (counts.questionsLive || 0);
  const liveNote = liveTotal
    ? ` Another ${liveTotal} item${liveTotal === 1 ? ' is' : 's are'} already live as labelled practice — reviewing those removes the label, but nothing waits on them.`
    : '';
  $('cr-overview-now').textContent = blocked.length
    ? `Start with what is blocked: ${blocked.join(', ')} invisible to students until someone decides.${liveNote}`
    : liveTotal
      ? `Nothing is blocked — students can see everything current.${liveNote}`
      : counts.intake
        ? `The review queues are clear. ${counts.intake} upload${counts.intake === 1 ? ' needs' : 's need'} triage in Add Materials.`
        : 'Every review queue is clear. Add new source material, or open Publish Courses to release something that is ready.';
}

async function loadContentOperations(button = null) {
  setBusy(button, true, 'Refreshing Workspace…');
  setContentTab(state.contentTab);
  try {
    // allSettled, not all. /content/source-coverage takes minutes against the production
    // database, and one slow or failing panel used to take the whole workspace with it — the
    // review queue held 24 lessons and the page rendered none of them, because a scorecard
    // nobody was waiting for had not come back yet.
    const [coverage, lessons, queue, calibration, challenges] = (await Promise.allSettled([
      api('/content/source-coverage'), api('/content/lessons/review-queue'),
      api('/content/questions/review-queue?limit=1000'), api('/content/questions/calibration-queue'),
      api('/content/challenges'),
    ])).map(result => result.status === 'fulfilled' ? result.value : null);
    state.sourceCoverage = coverage?.scorecards || [];
    state.lessonReviewQueue = lessons || [];
    state.questionReviewQueue = queue || [];
    state.calibrationQueue = calibration || [];
    state.contentChallenges = challenges || [];
    state.questionReviewLimit = 25;
    renderSourceCoverage();
    renderLessonReviewQueue();
    renderQuestionReviewQueue();
    renderCalibrationQueue();
    renderVideoReviewQueue();
    renderContentChallengeQueue();
    updateContentTabBadges();
    await loadContentReleases();
    renderIntakeEvents();
    await loadContentIntake();
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
  if (state.user.role === 'admin') { $('people-workspace').hidden = false; loadPeople(); }
  $('answerkey-workspace').hidden = false; loadAnswerKeys();
}

function renderIntakeEvents() {
  const select = $('content-intake-event');
  if (!select) return;
  const current = select.value;
  select.innerHTML = '<option value="">Choose an event (triage later)</option>' + (state.events || []).map(event =>
    `<option value="${event.id}">${escapeHtml(event.season)} · ${escapeHtml(event.name)} · Div ${escapeHtml(event.division)}</option>`
  ).join('');
  select.value = current;
}

async function loadContentIntake() {
  try {
    const [uploads, imports] = await Promise.all([api('/content/intake/uploads'), api('/content/intake/imports')]);
    const rows = uploads.concat(imports.map(item => ({
      ...item, id: `import-${item.source_id}`, filename: item.title || item.url,
      byte_count: 0, created_at: null, is_import: true,
      ingestion: { source_id: item.source_id, stage: item.snapshot_id ? 'ready_for_review' : 'queued',
        status: item.snapshot_id ? 'completed' : 'queued', diagnostics: { text_chars: item.text_chars } },
    })));
    $('content-intake-empty').hidden = rows.length > 0;
    state.intakeActionCount = rows.filter(row => (row.is_import
      ? row.status === 'needs_review'
      : ['needs_review', 'needs_human_review'].includes(row.status))).length;
    updateContentTabBadges();
    // One unrenderable row used to take the whole inbox with it: the list is assigned in a
    // single expression, so a throw anywhere left innerHTML untouched and the page showed
    // nothing at all — with the failure reported only as a toast that had already faded.
    $('content-intake-list').innerHTML = rows.map(row => {
      try {
        return renderIntakeRow(row);
      } catch (error) {
        return `<article class="content-intake-row surface"><div><strong>${escapeHtml(row.filename || 'Upload')}</strong><small>This row could not be displayed: ${escapeHtml(error.message)}</small></div></article>`;
      }
    }).join('');
    $('content-intake-empty').hidden = rows.length > 0;
  } catch (error) {
    $('content-intake-empty').hidden = false;
    const empty = $('content-intake-empty');
    if (empty) empty.textContent = `Intake could not load: ${error.message}`;
    toast(`Intake could not load. ${error.message}`);
  }
}

function renderIntakeRow(row) {
  {
      const ingestion = row.ingestion || {};
      const diagnostics = ingestion.diagnostics || {};
      const canReview = state.user.role === 'admin' && (row.is_import ? row.status === 'needs_review' : ['needs_review', 'needs_human_review'].includes(row.status)) && ingestion.source_id;
      return `<article class="content-intake-row surface" data-intake-id="${row.id}">
        <div><strong>${escapeHtml(row.filename)}</strong><small>${row.is_import ? 'URL / YouTube import' : `${row.byte_count.toLocaleString()} bytes · ${escapeHtml(row.created_at ? formatDate(row.created_at) : '—')}`}</small></div>
        <span class="status-pill intake-status-${escapeHtml(row.status)}">${escapeHtml(row.status.replaceAll('_', ' '))}</span>
        <div class="content-intake-detail"><span>${escapeHtml(ingestion.stage || 'queued')}</span>${diagnostics.text_chars ? `<span>${Number(diagnostics.text_chars).toLocaleString()} extracted chars</span>` : ''}${diagnostics.page_count ? `<span>${diagnostics.page_count} pages</span>` : ''}</div>
        <div class="content-intake-actions">${ingestion.source_id ? `<button class="button button-secondary button-compact" type="button" data-intake-source="${ingestion.source_id}">View extracted text</button>` : ''}${canReview ? `<select class="intake-event-select" data-intake-event data-has-event="${row.event_id ? '1' : ''}" aria-label="Assign event"><option value="">${row.event_id ? 'Keep current event' : 'Choose event to author against…'}</option>${(state.events || []).map(event => `<option value="${event.id}"${String(row.event_id) === String(event.id) ? ' selected' : ''}>${escapeHtml(event.name)} · ${escapeHtml(event.season)}</option>`).join('')}</select><button class="button button-primary button-compact" type="button" data-intake-review="accepted" data-intake-id="${row.id}" data-intake-import="${row.is_import ? row.source_id : ''}">Accept for authoring</button><button class="button button-quiet button-compact" type="button" data-intake-review="rejected" data-intake-id="${row.id}" data-intake-import="${row.is_import ? row.source_id : ''}">Reject</button>` : ''}</div>
        ${ingestion.source_id ? `<pre class="content-intake-extracted" data-intake-extracted="${ingestion.source_id}" hidden></pre>` : ''}
      </article>`;
  }
}

async function submitContentIntake(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const file = $('content-intake-file').files[0];
  const url = $('content-intake-url').value.trim();
  if (!file && !url) { $('intake-live-status').textContent = 'Choose a file or enter a URL.'; return; }
  if (file && url) { $('intake-live-status').textContent = 'Choose either a file or a URL, not both.'; return; }
  const payload = new FormData();
  if ($('content-intake-event').value) payload.append('event_id', $('content-intake-event').value);
  payload.append('rights_attestation', $('content-intake-rights').value.trim());
  const endpoint = url ? '/api/content/intake/imports' : '/api/content/intake/uploads';
  if (url) {
    payload.append('url', url);
    if ($('content-intake-title').value.trim()) payload.append('title', $('content-intake-title').value.trim());
  } else payload.append('file', file);
  setBusy(button, true, 'Uploading…');
  try {
    const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
    const response = await fetch(endpoint, { method: 'POST', headers, body: payload });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Upload failed');
    form.reset();
    $('intake-live-status').textContent = data.deduplicated ? 'Already received' : 'Received · private';
    if (data.job_id && url) {
      $('intake-live-status').textContent = 'Extracting captions…';
      const processed = await api('/content/intake/process-next', { method: 'POST' });
      $('intake-live-status').textContent = processed.ran
        ? (processed.status === 'completed' ? 'Transcript ready · private' : `Extraction ${processed.status}`)
        : 'Queued · awaiting worker';
    }
    await loadContentIntake();
    toast('Material received. It remains private until staff review.');
  } catch (error) { $('intake-live-status').textContent = error.message; }
  finally { setBusy(button, false); }
}

async function reviewContentIntake(uploadId, decision, button) {
  const form = new FormData();
  form.append('decision', decision);
  if (decision === 'accepted') form.append('rights_status', 'derivative_generation_allowed');
  const eventSelect = button.closest('[data-intake-id]')?.querySelector('[data-intake-event]');
  // An accept with no event authors nothing — the server approves the source and stops. That
  // used to be reported only in a toast that had faded by the time anyone looked for the
  // lesson. Refuse the click up front and point at the field that needs a value.
  if (decision === 'accepted' && eventSelect && !eventSelect.value && !eventSelect.dataset.hasEvent) {
    eventSelect.classList.add('field-error');
    eventSelect.focus();
    eventSelect.addEventListener('change', () => eventSelect.classList.remove('field-error'), { once: true });
    toast('Choose which event this material teaches — the lesson is authored against it.');
    return;
  }
  if (eventSelect?.value) form.append('event_id', eventSelect.value);
  form.append('notes', decision === 'accepted' ? 'Reviewed in Content Studio; rights attestation accepted.' : 'Rejected in Content Studio.');
  setBusy(button, true, decision === 'accepted' ? 'Accepting…' : 'Rejecting…');
  try {
    const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
    const importSource = button.dataset.intakeImport;
    const endpoint = importSource ? `/api/content/intake/imports/${importSource}/review` : `/api/content/intake/uploads/${uploadId}/review`;
    const response = await fetch(endpoint, { method: 'POST', headers, body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Review failed');
    if (decision !== 'accepted') {
      await loadContentIntake();
      toast('Upload rejected and withheld.');
      return;
    }
    if (data.needs_event) {
      await loadContentIntake();
      toast('Source approved, but no event was selected — pick one and accept again to author a lesson.');
      return;
    }
    // Accepting queues claim extraction and a lesson pass. Nothing runs the queue on its own,
    // so run it here: the reviewer clicked the button that promises authoring, and leaving the
    // work sitting in a table is how an upload sat at "received" for a day.
    setBusy(button, true, 'Extracting claims…');
    for (let i = 0; i < 10; i += 1) {
      const ran = await api('/content/intake/process-next', { method: 'POST' }).catch(() => null);
      if (!ran || !ran.ran) break;
      if (ran.error) { toast(`Authoring step failed: ${ran.error}`); break; }
      setBusy(button, true, i === 0 ? 'Authoring lesson…' : 'Authoring lesson…');
    }
    await loadContentIntake();
    await loadContentOperations().catch(() => {});   // the new lesson lands in the review queue
    toast('Source approved. Claims extracted and a lesson drafted — see the Lesson Review Queue below.');
  } catch (error) { toast(error.message); setBusy(button, false); }
}

async function loadParentMaterials() {
  try {
    const rows = await api('/parent/materials');
    $('parent-material-empty').hidden = rows.length > 0;
    $('parent-material-list').innerHTML = rows.map(row => `<article class="content-intake-row surface"><div><strong>${escapeHtml(row.filename)}</strong><small>${escapeHtml(row.message)}</small></div><span class="status-pill intake-status-${escapeHtml(row.status)}">${escapeHtml(row.status.replaceAll('_', ' '))}</span><div class="content-intake-detail"><span>${escapeHtml(row.ingestion_stage)}</span><span>${escapeHtml(row.created_at ? formatDate(row.created_at) : '—')}</span></div></article>`).join('');
  } catch (error) { $('parent-intake-status').textContent = error.message; }
}

async function loadParentRelationships() {
  try {
    const rows = await api('/parent/relationships');
    $('parent-relationship-list').innerHTML = rows.map(row => `<article class="content-intake-row surface"><div><strong>Student #${row.student_user_id}</strong><small>${escapeHtml(row.scope)}</small></div><span class="status-pill intake-status-${escapeHtml(row.status)}">${escapeHtml(row.status)}</span><div class="content-intake-detail">${escapeHtml(row.notes || '')}</div></article>`).join('');
  } catch (error) { $('parent-relationship-status').textContent = error.message; }
}

async function submitParentRelationship(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const payload = new FormData();
  payload.append('student_email', $('parent-student-email').value.trim());
  payload.append('notes', $('parent-relationship-note').value.trim());
  if ($('parent-relationship-team').value) payload.append('team_id', $('parent-relationship-team').value);
  setBusy(button, true, 'Requesting…');
  try {
    const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
    const response = await fetch('/api/parent/relationships', { method: 'POST', headers, body: payload });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Relationship request failed');
    $('parent-relationship-status').textContent = 'Request submitted for staff approval.';
    form.reset();
    await loadParentRelationships();
  } catch (error) { $('parent-relationship-status').textContent = error.message; }
  finally { setBusy(button, false); }
}

async function submitParentMaterial(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const file = $('parent-intake-file').files[0];
  if (!file) return;
  const payload = new FormData();
  payload.append('file', file);
  payload.append('rights_attestation', $('parent-intake-rights').value.trim());
  if ($('parent-intake-team').value) payload.append('team_id', $('parent-intake-team').value);
  setBusy(button, true, 'Submitting…');
  try {
    const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
    const response = await fetch('/api/parent/materials', { method: 'POST', headers, body: payload });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Submission failed');
    form.reset();
    $('parent-intake-status').textContent = 'Received privately. Staff review is required before it can influence a course.';
    await loadParentMaterials();
  } catch (error) { $('parent-intake-status').textContent = error.message; }
  finally { setBusy(button, false); }
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

const ROLE_OPTIONS = ['student', 'parent', 'coach', 'editor', 'sme', 'calibrator', 'admin'];

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
  if (!roleSelect) return;
  const userId = Number(roleSelect.dataset.userRole);
  const person = (state.people || []).find(u => u.id === userId);
  const role = roleSelect.value;
  // Every other role change is recoverable by changing it back. Granting administrator hands
  // over the platform — the new admin can publish to students, reassign any role, and grant
  // admin again — and the select applies on `change`, so a stray keystroke was enough. Ask.
  if (role === 'admin' && person?.role !== 'admin') {
    const who = person ? (person.full_name || person.email) : 'this user';
    if (!window.confirm(
      `Make ${who} an administrator?\n\n`
      + 'Administrators can publish content to students, change anyone\'s role, and grant '
      + 'administrator access to others. Every other administrator will be notified.'
    )) {
      roleSelect.value = person?.role || 'student';   // put the select back
      return;
    }
  }
  updatePerson(userId, { role });
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
  const pathCourse = coursePathEvent();
  const contentPreview = roleMode === 'content' && Boolean(pathCourse);
  const initialRoute = pathCourse ? 'learn' : location.hash.slice(1).split('?')[0];
  showView(contentPreview ? 'learn' : roleMode === 'content' ? 'content' : roleMode === 'coach' ? 'coach' : roleMode === 'parent' ? 'parent' : initialRoute === 'learn' ? 'learn' : initialRoute === 'practice' ? 'practice' : initialRoute === 'errors' ? 'errors' : 'dashboard', false);
  if (roleMode === 'student') $('today-copy').textContent = 'Loading your study plan…';
  try {
    if (roleMode === 'parent') {
      await loadParentMaterials();
      await loadParentRelationships();
    } else if (roleMode === 'content' && !contentPreview) {
      setContentTab(state.contentTab);
      const [events, coverage, lessons, queue, calibration, challenges] = (await Promise.allSettled([
        api('/events'), api('/content/source-coverage'), api('/content/lessons/review-queue'),
        api('/content/questions/review-queue?limit=1000'), api('/content/questions/calibration-queue'),
        api('/content/challenges'),
      ])).map(result => result.status === 'fulfilled' ? result.value : null);
      state.events = events || state.events || [];
      state.sourceCoverage = coverage?.scorecards || [];
      state.lessonReviewQueue = lessons || [];
      state.questionReviewQueue = queue || [];
      state.calibrationQueue = calibration || [];
      state.contentChallenges = challenges || [];
      state.questionReviewLimit = 25;
      renderSourceCoverage();
      renderLessonReviewQueue();
      renderQuestionReviewQueue();
      renderCalibrationQueue();
      renderVideoReviewQueue();
      renderContentChallengeQueue();
      updateContentTabBadges();
      // Content Studio has its own event picker and inbox. Populate these
      // before the first paint; previously they were only refreshed after an
      // admin clicked the workspace refresh button.
      renderIntakeEvents();
      await loadContentIntake();
      // People & Roles and Answer Keys were revealed only by loadContentOperations, which runs
      // when someone clicks Refresh Workspace. On a fresh sign-in neither existed, so the
      // Operations tab was empty and the only console for granting a staff role was invisible
      // to the admin who needed it — reachable solely by pressing a refresh button that looked
      // like it would merely reload what was already on screen.
      if (state.user.role === 'admin') { $('people-workspace').hidden = false; await loadPeople(); }
      $('answerkey-workspace').hidden = false;
      await loadAnswerKeys();
    } else if (roleMode === 'coach') {
      const [events, exams, coachDashboard, teams] = await Promise.all([api('/events'), api('/exams'), api('/coach/dashboard'), api('/teams')]);
      state.events = events || state.events || [];
      state.exams = exams;
      state.coachDashboard = coachDashboard;
      state.teams = teams;
      renderCoachDashboard();
    } else {
      const [events, exams, dashboard, accommodation] = await Promise.all([
        api('/events'), api('/exams'), Promise.resolve(null), api('/me/accommodations'),
      ]);
      state.events = events || state.events || [];
      state.exams = exams;
      state.dashboard = dashboard;
      state.accommodation = accommodation;
      const hashParts = location.hash.slice(1).split('?');
      const hashParams = new URLSearchParams(hashParts[1] || '');
      const statefulParams = new URLSearchParams(location.hash.slice(1));
      const explicitSlug = pathCourse?.slug || hashParams.get('event') || statefulParams.get('event');
      // A URL explicitly naming a historical event is intentional, so an exact match wins.
      // Remembered state, however, always rolls forward to the current catalog.
      // No fallback to "the first event with content". A brand-new student used to be
      // dropped straight into an arbitrary auto-picked course with no idea why it was
      // theirs; with nothing chosen and nothing linked, the dashboard now opens the
      // guided subject picker instead and the student makes the first choice.
      let requestedEvent = explicitSlug
        ? (state.events.find(event => event.slug === explicitSlug) || resolveEvent(explicitSlug))
        : resolveEvent(state.activeEventSlug);
      // Honouring the link stops making sense when the archived event holds nothing: the
      // reader lands on a "Course content" heading with an empty page and no sign that a
      // live version exists. Consolidation left several such twins behind. Roll forward and
      // say so, rather than serving a dead end.
      if (explicitSlug && requestedEvent && requestedEvent.lesson_count === 0) {
        const live = resolveEvent(requestedEvent.slug);
        if (live && live.slug !== requestedEvent.slug && live.lesson_count > 0) {
          toast(`${requestedEvent.name} ${requestedEvent.season} is archived — showing the current ${live.season} course.`);
          requestedEvent = live;
        }
      }
      state.activeEventSlug = requestedEvent?.slug || '';
      if (requestedEvent) localStorage.setItem('activeEventSlug', requestedEvent.slug);
      const selectedEvent = activeEvent();
      if (selectedEvent) {
        [state.lessons, state.practiceSets, state.activeTaxonomy, state.materials, state.dashboard, state.courseMap] = await Promise.all([
          api(`/events/${selectedEvent.id}/lessons`),
          api(`/events/${selectedEvent.id}/practice-sets`),
          subjectKeyOf(state.activeEventSlug) === 'entomology'
            ? api(`/events/${selectedEvent.id}/taxonomy`)
            : Promise.resolve(null),
          api(`/events/${selectedEvent.id}/materials`).catch(() => ({ materials: [] })),
          api(`/student/dashboard?event_slug=${encodeURIComponent(selectedEvent.slug)}`),
          api(`/courses/${selectedEvent.season}/${encodeURIComponent(selectedEvent.slug)}`).catch(error => {
            if (error.status === 404) return null;
            throw error;
          }),
        ]);
      } else {
        state.lessons = [];
        state.practiceSets = [];
        state.materials = { materials: [] };
        state.courseMap = null;
      }
      $('today-copy').textContent = 'Build confidence one focused session at a time.';
      updateDashboard();
      renderSubjectShell();
      // Courses and Practice are scoped to the chosen subject; with none chosen yet they
      // are empty shells, so land on the picker instead.
      if (!selectedEvent && ['learn', 'practice'].includes(initialRoute)) showView('dashboard', false);
      if (location.hash.startsWith('#lesson=')) {
        const lessonId = Number(new URLSearchParams(location.hash.slice(1)).get('lesson'));
        if (state.lessons.some(lesson => lesson.id === lessonId)) {
          showView('learn', false);
          await openLesson(lessonId);
        }
      } else if (pathCourse?.contentType === 'lesson' && pathCourse.contentSlug) {
        const lesson = state.lessons.find(item => item.slug === pathCourse.contentSlug);
        if (lesson) {
          showView('learn', false);
          await openLesson(lesson.id);
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

function setStudentView(on) {
  if (on) sessionStorage.setItem('studentView', '1');
  else sessionStorage.removeItem('studentView');
  // The route is part of the mode: staying on #content while previewing would show the review
  // workspace with student navigation around it.
  window.location.hash = on ? '#overview' : '#content';
  loadApplication();
}

$('student-view-toggle').addEventListener('click', () => {
  setStudentView(sessionStorage.getItem('studentView') !== '1');
});
$('student-view-exit').addEventListener('click', () => setStudentView(false));

$('show-assignment-form').addEventListener('click', () => {
  $('assignment-form').hidden = false;
  $('assignment-title').focus();
});

$('refresh-content-operations').addEventListener('click', event => loadContentOperations(event.currentTarget));
// One workspace at a time. The page used to stack ten queues into a 466,000-pixel scroll
// and reviewers read it as "nothing here" — the lesson queue sat below 500 question cards.
$('content-tabs').addEventListener('click', event => {
  const button = event.target.closest('[data-cr-tab]');
  if (button) setContentTab(button.dataset.crTab);
});
$('content-overview').addEventListener('click', event => {
  const button = event.target.closest('[data-cr-goto]');
  if (button) setContentTab(button.dataset.crGoto);
});
$('interest-chips').addEventListener('click', event => {
  const chip = event.target.closest('[data-interest]');
  if (!chip) return;
  state.interestFilter = chip.dataset.interest;
  renderStudentGuidance();
});
$('onboarding-event-list').addEventListener('click', event => {
  const button = event.target.closest('[data-onboard-event]');
  if (!button) return;
  setBusy(button, true, 'Setting Up…');
  selectSubject(button.dataset.onboardEvent, 'dashboard')
    .catch(error => toast(error.message))
    .finally(() => setBusy(button, false));
});
$('student-guide-dismiss').addEventListener('click', () => {
  localStorage.setItem('fieldstoneHomeGuideDismissed', '1');
  $('student-guide').hidden = true;
});
$('subject-list').addEventListener('click', event => {
  if (event.target.closest('#subject-add-tile')) {
    $('subject-explorer').scrollIntoView({ behavior: preferredScrollBehavior(), block: 'start' });
  }
});
$('lesson-review-filters').addEventListener('click', event => {
  const button = event.target.closest('[data-lesson-filter]');
  if (!button) return;
  state.lessonFilter = button.dataset.lessonFilter;
  renderLessonReviewQueue();
});
$('question-review-controls').addEventListener('click', event => {
  const button = event.target.closest('[data-question-serve]');
  if (!button) return;
  state.questionServeFilter = button.dataset.questionServe;
  state.questionReviewLimit = 25;
  renderQuestionReviewQueue();
});
$('refresh-insights').addEventListener('click', event => loadContentInsights(event.currentTarget));
$('question-event-filter').addEventListener('change', event => {
  state.questionScopeEvent = event.target.value;
  state.questionReviewLimit = 25;
  renderQuestionReviewQueue();
});
$('refresh-content-releases').addEventListener('click', event => { setBusy(event.currentTarget, true, 'Refreshing…'); loadContentReleases().finally(() => setBusy(event.currentTarget, false)); });
$('enrich-content-media').addEventListener('click', async event => {
  const button = event.currentTarget;
  if (!window.confirm('Add approved videos and specimen images to eligible lessons? Published lessons will receive a new review version.')) return;
  setBusy(button, true, 'Composing media…');
  try {
    const form = new FormData();
    const result = await api('/content/lessons/media-enrich', { method: 'POST', body: form });
    toast(result.count ? `${result.count} lesson${result.count === 1 ? '' : 's'} queued with grounded media.` : 'No eligible lessons needed media.');
    await loadContentOperations(button);
  } catch (error) { toast(`Media enrichment failed. ${error.message}`); }
  finally { setBusy(button, false); }
});
$('content-intake-form').addEventListener('submit', submitContentIntake);
// Refresh used to only re-read the list. There is no background worker — jobs run when
// something calls /content/intake/process-next — so an upload sat at "received" forever and
// the only button on the page that looked like it would help did nothing for it. Refresh now
// drains the queue first, bounded so a permanently failing job cannot spin here.
$('refresh-content-intake').addEventListener('click', async event => {
  const button = event.currentTarget;
  setBusy(button, true, 'Processing…');
  try {
    for (let i = 0; i < 8; i += 1) {
      const result = await api('/content/intake/process-next', { method: 'POST' }).catch(() => null);
      if (!result || !result.ran) break;
    }
  } finally {
    setBusy(button, true, 'Refreshing…');
    await loadContentIntake();
    setBusy(button, false);
  }
});
$('content-intake-list').addEventListener('click', event => {
  const button = event.target.closest('[data-intake-review]');
  if (button) return reviewContentIntake(Number(button.dataset.intakeId), button.dataset.intakeReview, button);
  const sourceButton = event.target.closest('[data-intake-source]');
  if (!sourceButton) return;
  const panel = sourceButton.closest('[data-intake-id]').querySelector('[data-intake-extracted]');
  if (!panel.hidden) { panel.hidden = true; sourceButton.textContent = 'View extracted text'; return; }
  sourceButton.textContent = 'Loading…';
  api(`/content/intake/sources/${sourceButton.dataset.intakeSource}`).then(data => {
    const source = data.source || {};
    const snapshot = data.snapshot || {};
    $('content-source-inspector').hidden = false;
    $('content-source-inspector-title').textContent = source.title || 'Source snapshot';
    $('content-source-inspector-meta').textContent = `${source.approved ? 'Approved' : 'Quarantined'} · ${source.rights_status || 'rights pending'} · ${data.passages.length} passages · ${snapshot.content_hash || 'no snapshot'}`;
    $('content-source-passages').innerHTML = data.passages.map(passage => `<article class="content-source-passage"><small>Passage ${passage.id} · ${escapeHtml(passage.locator)} · ${escapeHtml(passage.passage_type)}</small><p>${escapeHtml(passage.text)}</p></article>`).join('') || '<p>No extracted passages retained.</p>';
    $('content-source-json').textContent = JSON.stringify({source, snapshot, mappings: data.mappings}, null, 2);
    panel.hidden = true;
    sourceButton.textContent = 'Opened below';
  }).catch(error => { panel.textContent = error.message; panel.hidden = false; sourceButton.textContent = 'View extracted text'; });
});
$('parent-intake-form').addEventListener('submit', submitParentMaterial);
$('refresh-parent-materials').addEventListener('click', loadParentMaterials);
$('parent-relationship-form').addEventListener('submit', submitParentRelationship);
$('content-release-list').addEventListener('click', async event => {
  const historyButton = event.target.closest('[data-release-history]');
  if (historyButton) {
    const row = historyButton.closest('[data-release-row]');
    const panel = row?.querySelector('[data-release-history-panel]');
    const body = panel?.querySelector('.release-history-body');
    if (!panel || !body) return;
    panel.hidden = false;
    historyButton.disabled = true;
    try {
      const data = await api(`/content/releases/${historyButton.dataset.releaseHistory}/history`);
      const entries = data.transitions || [];
      body.innerHTML = entries.length ? `<ol class="release-history-list">${entries.map(entry => `<li><div><strong>${escapeHtml(entry.decision.replaceAll('_', ' '))}</strong><span>${escapeHtml(new Date(entry.created_at).toLocaleString())}</span></div><p>${escapeHtml(entry.details?.notes || 'No release note recorded.')}</p></li>`).join('')}</ol>` : '<p class="review-waiting">No release transitions recorded yet.</p>';
    } catch (error) { body.innerHTML = `<p class="citation-missing">${escapeHtml(error.message)}</p>`; }
    finally { historyButton.disabled = false; }
    return;
  }
  const button = event.target.closest('[data-release-decision]');
  if (!button || button.disabled) return;
  const notes = window.prompt('Release note (optional):', '') ?? '';
  const form = new FormData();
  form.append('decision', button.dataset.releaseDecision);
  form.append('notes', notes);
  const status = button.closest('[data-release-row]')?.querySelector('.review-status');
  setBusy(button, true, 'Saving…');
  try {
    const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
    const response = await fetch(`/api/content/releases/${button.dataset.courseId}`, { method: 'POST', headers, body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail?.message || data.detail || 'Release decision was not saved.');
    await loadContentReleases();
    toast(`Course ${button.dataset.releaseDecision.replaceAll('_', ' ')}.`);
  } catch (error) { if (status) status.textContent = error.message; }
  finally { setBusy(button, false); }
});
$('lesson-review-queue').addEventListener('click', async event => {
  const button = event.target.closest('[data-lesson-review-decision]');
  if (!button) return;
  const card = button.closest('[data-lesson-review-card]');
  const status = card.querySelector('.review-status');
  const checklist = Object.fromEntries(
    [...card.querySelectorAll('.review-check input')].map(input => [
      input.name,
      input.checked,
    ]),
  );
  const notes = card.querySelector('[name="lesson-review-notes"]')?.value || '';
  setBusy(button, true, 'Saving lesson review…');
  status.textContent = '';
  try {
    await api(`/content/lessons/${button.dataset.lessonId}/reviews`, {
      method: 'POST',
      body: JSON.stringify({
        stage: button.dataset.lessonReviewStage,
        decision: button.dataset.lessonReviewDecision,
        checklist,
        notes,
      }),
    });
    state.lessonReviewQueue = await api('/content/lessons/review-queue');
    renderLessonReviewQueue();
    toast('Lesson review decision saved.');
  } catch (error) {
    status.textContent = error.message;
  } finally {
    setBusy(button, false);
  }
});
$('question-review-queue').addEventListener('click', async event => {
  const more = event.target.closest('[data-question-show-more]');
  if (more) {
    state.questionReviewLimit += 25;
    renderQuestionReviewQueue();
    return;
  }
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
    state.questionReviewQueue = await api('/content/questions/review-queue?limit=1000');
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
    renderVideoReviewQueue();
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
  if (event.target.closest('#lesson-review-dock-approve')) {
    submitDockReview('approved').catch(error => toast(error.message));
    return;
  }
  if (event.target.closest('#lesson-review-dock-reject')) {
    submitDockReview('rewrite_required').catch(error => toast(error.message));
    return;
  }
  const subjectButton = event.target.closest('[data-subject]');
  if (subjectButton) selectSubject(subjectButton.dataset.subject, subjectButton.dataset.subjectDestination || 'learn').catch(error => toast(error.message));
  const lessonButton = event.target.closest('[data-start-lesson]');
  if (lessonButton) {
    event.preventDefault();
    openLesson(Number(lessonButton.dataset.startLesson));
  }
  const lessonSection = event.target.closest('[data-lesson-block]');
  if (lessonSection && state.currentLesson) {
    state.lessonStepIndex = stepForBlock(Number(lessonSection.dataset.lessonBlock));
    saveCurrentLessonProgress(false)
      .then(renderLessonBlock)
      .catch(error => toast(error.message));
  }
  const practiceButton = event.target.closest('[data-start-practice-set]');
  if (practiceButton) openPracticeLab(Number(practiceButton.dataset.startPracticeSet), practiceButton.dataset.practiceMode);
  const practiceJump = event.target.closest('[data-practice-jump]');
  if (practiceJump) showView('practice');
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
  if (state.featuredLessonId) return openLesson(state.featuredLessonId);
  selectSubject(state.activeEventSlug, 'practice').then(() => {
    $('materials-block')?.scrollIntoView({ behavior: preferredScrollBehavior(), block: 'start' });
  }).catch(error => toast(error.message));
});
$('lessons-empty')?.addEventListener('click', event => {
  const button = event.target.closest('[data-open-course-material]');
  if (button) openMaterial(Number(button.dataset.openCourseMaterial));
});
$('overview-learn-button').addEventListener('click', () => {
  selectSubject(state.activeEventSlug, 'learn').catch(error => toast(error.message));
});
$('overview-practice-button').addEventListener('click', () => {
  selectSubject(state.activeEventSlug, 'practice').catch(error => toast(error.message));
});
$('learn-resources-button')?.addEventListener('click', () => {
  selectSubject(state.activeEventSlug, 'practice').then(() => {
    $('materials-block')?.scrollIntoView({ behavior: preferredScrollBehavior(), block: 'start' });
  }).catch(error => toast(error.message));
});
$('dashboard-resources-button').addEventListener('click', () => {
  selectSubject(state.activeEventSlug, 'practice').then(() => {
    $('materials-block')?.scrollIntoView({ behavior: preferredScrollBehavior(), block: 'start' });
  }).catch(error => toast(error.message));
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
  // Same rule as the exam banner: machine-gated content must say so where the student works.
  $('practice-ai-notice').hidden = !session.practice_set?.unreviewed;
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
    state.lessonSteps = null;          // rebuilt once chapters are known
    state.lessonStepIndex = null;
    // content staff walking a lesson get the verdict controls beside the reading
    await loadReviewerContext(id);
    // A lesson can be launched from Practice & Resources. Move the learner
    // into the lesson workspace so the reader never opens behind another view.
    showView('learn', false);
    $('learn-catalog').hidden = true;
    $('lesson-reader').hidden = false;
    const lessonSlug = state.currentLesson.slug || String(id);
    history.replaceState(
      null,
      '',
      coursePath(activeEvent(), `/lesson/${encodeURIComponent(lessonSlug)}`),
    );
    renderLessonBlock();
    loadLessonVideo(id);
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
}

// A lesson plays like a course: the chapter that teaches a section comes first, then the
// section's reading. Both are steps in one sequence, advanced with the same Continue button.
function buildLessonSteps() {
  const lesson = state.currentLesson;
  const chapters = state.lessonVideoChapters || [];
  const steps = [];
  (lesson.content || []).forEach((block, index) => {
    const opener = chapters.find(c => (c.block_indexes || [])[0] === index);
    if (opener) steps.push({ kind: 'video', chapter: opener, blockIndex: index });
    // A block the server flagged empty renders as a heading over nothing — five boxes reading
    // "Concept" told students there was content they had failed to see. It stays in
    // `lesson.content` so every index still points at the same block; it just gets no step.
    if (!block.empty) steps.push({ kind: 'block', blockIndex: index });
  });
  state.lessonSteps = steps;
  return steps;
}

function lessonSteps() {
  return state.lessonSteps?.length ? state.lessonSteps : buildLessonSteps();
}

function stepForBlock(blockIndex) {
  const steps = lessonSteps();
  // land on the video that opens a section, so watching comes before reading
  const video = steps.findIndex(s => s.kind === 'video' && s.blockIndex === blockIndex);
  if (video >= 0) return video;
  return Math.max(0, steps.findIndex(s => s.kind === 'block' && s.blockIndex === blockIndex));
}

// The finish button's state depends on lesson progress, which changes when a checkpoint is
// answered — not only when a block is rendered. Computing it solely inside renderLessonBlock
// meant answering the last required checkpoint correctly left the button reading "Complete
// Required Checkpoints" and disabled, with nothing left to complete, until the reader
// navigated away and back.
function refreshLessonFinishButton() {
  const lesson = state.currentLesson;
  const finish = $('lesson-finish');
  if (!lesson || !finish) return;
  const done = lesson.progress?.status === 'completed';
  finish.disabled = !done;
  finish.textContent = done ? 'Finish Lesson' : 'Complete Required Checkpoints';
}

function renderLessonBlock() {
  const lesson = state.currentLesson;
  const steps = lessonSteps();
  if (state.lessonStepIndex == null) state.lessonStepIndex = stepForBlock(state.lessonBlockIndex || 0);
  state.lessonStepIndex = Math.min(Math.max(0, state.lessonStepIndex), steps.length - 1);
  const step = steps[state.lessonStepIndex];
  state.lessonBlockIndex = step.blockIndex;
  const total = steps.length;
  $('lesson-position').textContent = `${state.lessonStepIndex + 1} of ${total}`;
  $('lesson-progress-bar').style.width = `${Math.round(((state.lessonStepIndex + 1) / total) * 100)}%`;
  $('lesson-previous').disabled = state.lessonStepIndex === 0;
  $('lesson-next').hidden = state.lessonStepIndex === total - 1;
  $('lesson-finish').hidden = state.lessonStepIndex !== total - 1;
  refreshLessonFinishButton();
  renderLessonOutline();

  if (step.kind === 'video') {
    $('lesson-next').textContent = 'Continue to the reading';
    refreshLessonNextButton();       // clear a disabled state left by a checkpoint step
    const node = $('lesson-block');
    node.className = 'lesson-block surface lesson-block-video';
    node.innerHTML = `
      <p class="kicker">Watch · ${escapeHtml(step.chapter.title)}</p>
      <video class="lesson-step-video" controls autoplay playsinline
             src="${safeUrl(step.chapter.playback_url)}"></video>
      <p class="lesson-step-note">${formatClock(step.chapter.duration_seconds)} · covers ${(step.chapter.block_indexes || []).length} section${(step.chapter.block_indexes || []).length === 1 ? '' : 's'} — the reading follows.</p>`;
    const player = node.querySelector('video');
    // Roll into the reading when the chapter ends, the way a course lesson flows.
    player?.addEventListener('ended', () => moveLesson(1));
    node.focus({ preventScroll: true });
    node.scrollIntoView({ behavior: preferredScrollBehavior(), block: 'start' });
    renderLessonReviewDock();
    return;
  }
  $('lesson-next').textContent = 'Continue';
  refreshLessonNextButton();

  const block = lesson.content[step.blockIndex];
  const renderer = {
    opening: renderOpeningBlock,
    property_cards: renderPropertyCardsBlock,
    worked_example: renderWorkedExampleBlock,
    checkpoint: renderCheckpointBlock,
    steps: renderStepsBlock,
    image_gallery: renderImageGalleryBlock,
    video: renderVideoBlock,
    summary: renderSummaryBlock,
  }[block.type];
  const node = $('lesson-block');
  node.className = `lesson-block surface${block.type === 'opening' ? ' lesson-block-opening' : ''}`;
  // One malformed block must cost its own slide, never the lesson. Before this, a renderer
  // throwing on a missing field left the reader blank with no way forward.
  let markup;
  try {
    markup = renderer ? renderer(block) : `<h1>${escapeHtml(block.heading || 'Lesson section')}</h1><p>${escapeHtml(block.body || '')}</p>`;
  } catch (error) {
    markup = `<h1>${escapeHtml(block.heading || 'Lesson section')}</h1><p class="block-lede">This section could not be displayed. Use “Give feedback” to report it.</p>`;
  }
  node.innerHTML = markup;
  node.focus({ preventScroll: true });
  node.scrollIntoView({ behavior: preferredScrollBehavior(), block: 'start' });
}

// ---------------------------------------------------------------- reviewer walkthrough
// Content staff previewing a lesson see the student experience — slides, video, checks, in
// order — with the verdict controls docked beside it. Previously the only route was a queue
// card, so a reviewer read the lesson in one tab and approved it in another from memory.

function reviewerFindingsForBlock(entry, blockIndex) {
  if (!entry) return [];
  const at = position => position === blockIndex + 1;
  return [
    ...(entry.disputed_checkpoints || []).filter(f => at(f.position)).map(f => ({
      tone: 'strong',
      text: `An independent judge disputed this checkpoint — ${f.verdict || 'disputed'}`
        + (f.solver_choice !== null && f.solver_choice !== undefined ? ` (it chose ${f.solver_choice}, the key is ${f.key})` : '')
        + ((f.verifier_errors || []).length ? ` · ${String(f.verifier_errors[0]).slice(0, 160)}` : ''),
    })),
    ...(entry.absent_media_blocks || []).filter(f => at(f.position)).map(() => ({
      tone: 'strong', text: 'This reads from a figure the lesson never shows.',
    })),
    ...(entry.unavailable_source_blocks || []).filter(f => at(f.position)).map(f => ({
      tone: '', text: `Refers to “${f.phrase || 'the source'}” — material the student was not given.`,
    })),
  ];
}

function renderLessonReviewDock() {
  const dock = $('lesson-review-dock');
  if (!dock) return;
  const entry = state.reviewingLesson;
  if (!entry) { dock.hidden = true; return; }
  dock.hidden = false;
  const stage = entry.next_stage;
  $('lesson-review-dock-stage').textContent = {
    editor: 'Needs editorial review', sme: 'Needs scientific review',
    complete: 'Both approvals recorded', revision_required: 'Revision requested',
  }[stage] || stage;
  const findings = reviewerFindingsForBlock(entry, state.lessonBlockIndex || 0);
  $('lesson-review-dock-findings').innerHTML = findings.length
    ? findings.map(f => `<p class="review-flag ${f.tone === 'strong' ? 'review-flag-strong' : ''}">${escapeHtml(f.text)}</p>`).join('')
    : '<p class="review-flag review-flag-clear">No automated finding on this section</p>';
  const actionable = stage === 'editor' || stage === 'sme';
  $('lesson-review-dock-approve').disabled = !actionable;
  $('lesson-review-dock-reject').disabled = !actionable;
  $('lesson-review-dock-approve').textContent = stage === 'sme' ? 'Approve scientific review' : 'Approve editorial review';
}

async function loadReviewerContext(lessonId) {
  if (!['admin', 'editor', 'sme', 'calibrator'].includes(state.user?.role)) {
    state.reviewingLesson = null;
    return;
  }
  try {
    const queue = await api('/content/lessons/review-queue');
    const rows = Array.isArray(queue) ? queue : queue.items || [];
    state.reviewingLesson = rows.find(row => row.id === lessonId) || null;
  } catch { state.reviewingLesson = null; }
}

async function submitDockReview(decision) {
  const entry = state.reviewingLesson;
  if (!entry) return;
  const status = $('lesson-review-dock-status');
  const stage = entry.next_stage;
  status.textContent = 'Recording…';
  try {
    // The checklist the queue card enforces is the same contract here; walking the lesson end
    // to end is what the reviewer just did, so the checks are sent as satisfied by that.
    const checklist = Object.fromEntries((lessonReviewChecks[stage] || []).map(c => [c, true]));
    await api(`/content/lessons/${entry.id}/reviews`, {
      method: 'POST',
      body: JSON.stringify({
        stage, decision, checklist,
        notes: $('lesson-review-dock-notes').value.trim(),
      }),
    });
    status.textContent = decision === 'approved'
      ? 'Approved. This version is recorded against your account.'
      : 'Revision requested. This version can no longer be approved.';
    await loadReviewerContext(entry.id);
    renderLessonReviewDock();
  } catch (error) {
    status.textContent = error.message;
  }
}

function lessonBlockLabel(block, index) {
  const labels = {
    opening: 'Goal',
    video: 'Watch',
    property_cards: 'Learn',
    steps: 'Strategy',
    worked_example: 'Try it',
    checkpoint: 'Check',
    image_gallery: 'Observe',
    summary: 'Review',
  };
  return block.heading || block.title || labels[block.type] || `Part ${index + 1}`;
}

function renderLessonOutline() {
  const lesson = state.currentLesson;
  const unit = state.courseMap?.units?.find(item => item.skills.some(
    skill => skill.lessons.some(candidate => candidate.id === lesson.id),
  ));
  $('lesson-outline-unit').textContent = unit ? unit.title : 'Lesson';
  $('lesson-outline-title').textContent = lesson.title;
  const complete = new Set(lesson.progress.completed_block_ids || []);
  $('lesson-outline-list').innerHTML = lesson.content.map((block, index) => {
    const current = index === state.lessonBlockIndex;
    const completed = complete.has(block.id)
      || lesson.progress.checkpoint_results?.[block.id]?.correct
      || lesson.progress.checkpoint_results?.[block.id]?.exhausted;
    // A chapter belongs to the section it teaches, so it is offered here rather than as a
    // second, parallel list of lesson content.
    const chapter = chapterOpeningBlock(index);
    const covers = chapter ? (chapter.block_indexes || []).length : 0;
    const play = chapter
      ? `<span class="outline-play" data-play-chapter="${chapter.index}" role="button" tabindex="0"
           title="Watch ${escapeHtml(chapter.title)} — covers ${covers} section${covers === 1 ? '' : 's'}"
           >▶ ${formatClock(chapter.duration_seconds)}${covers > 1 ? ` · ${covers} sections` : ''}</span>`
      : '';
    return `<li><button type="button" data-lesson-block="${index}"${current ? ' aria-current="step"' : ''}>
      <span aria-hidden="true">${completed ? '✓' : index + 1}</span>
      <span>${escapeHtml(lessonBlockLabel(block, index))}</span>
      ${play}
    </button></li>`;
  }).join('');
}

function renderOpeningBlock(block) {
  return `<p class="kicker">${escapeHtml(block.kicker || 'Lesson')}</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><p class="block-lede">${escapeHtml(block.body)}</p>`;
}

function renderPropertyCardsBlock(block) {
  const cards = Array.isArray(block.cards) ? block.cards : (Array.isArray(block.items) ? block.items : []);
  const cardMarkup = cards.map(card => {
    const name = card?.name || card?.title || card?.label || 'Key idea';
    const cue = card?.cue || card?.summary || card?.subtitle || '';
    const detail = card?.detail || card?.body || card?.description || '';
    return `<article class="property-card"><h3>${escapeHtml(name)}</h3>${cue ? `<strong>${escapeHtml(cue)}</strong>` : ''}${detail ? `<p>${escapeHtml(detail)}</p>` : ''}</article>`;
  }).join('');
  const fallback = !cardMarkup ? `<div class="property-card property-card-empty"><h3>Concept notes</h3><p>${escapeHtml(block.body || 'This concept is being prepared for review.')}</p></div>` : '';
  return `<p class="kicker">Concept toolkit</p><h1 id="lesson-reader-title">${escapeHtml(block.heading || 'Key concepts')}</h1>${block.body ? `<p class="block-lede">${escapeHtml(block.body)}</p>` : ''}<div class="property-grid">${cardMarkup || fallback}</div>`;
}

function renderWorkedExampleBlock(block) {
  // `block.steps.map` on a block without steps throws, and a throw here blanks the whole
  // reader rather than losing one slide. 49 published blocks are in that state.
  const steps = Array.isArray(block.steps) ? block.steps : [];
  const prompt = block.prompt || block.body || '';
  return `<p class="kicker">Worked example</p><h1 id="lesson-reader-title">${escapeHtml(block.heading || 'Worked example')}</h1>${prompt ? `<div class="worked-prompt">${escapeHtml(prompt)}</div>` : ''}${steps.length ? `<ol class="worked-steps">${steps.map(step => `<li>${escapeHtml(typeof step === 'string' ? step : (step?.detail || step?.text || ''))}</li>`).join('')}</ol>` : ''}`;
}

function checkpointAnswerLine(index, choices) {
  if (!Number.isInteger(index) || index < 0 || index >= (choices || []).length) return '';
  return `<p><strong>Answer: ${String.fromCharCode(65 + index)}.</strong> ${escapeHtml(choices[index])}</p>`;
}

function renderCheckpointBlock(block) {
  const prior = state.currentLesson.progress.checkpoint_results[block.id] || {};
  const resolved = Boolean(prior.correct || prior.exhausted);
  let priorNote = '';
  if (prior.correct) {
    priorNote = '<h3>Previously completed</h3><p>You answered this knowledge check correctly.</p>';
  } else if (prior.exhausted) {
    const revealed = prior.revealed || {};
    priorNote = `<h3>Both tries used</h3>${checkpointAnswerLine(revealed.correct_index, block.choices)}${revealed.explanation ? `<p>${escapeHtml(revealed.explanation)}</p>` : ''}<p>This check is recorded as missed — review the answer, then continue.</p>`;
  }
  return `<p class="kicker">Knowledge check</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><p class="block-lede">${escapeHtml(block.question)}</p><form class="checkpoint-form" data-checkpoint-form="${escapeHtml(block.id)}"><fieldset class="choices"${resolved ? ' disabled' : ''}><legend class="sr-only">Select one answer</legend>${block.choices.map((choice, index) => `<label class="choice"><input type="radio" name="lesson-checkpoint" value="${index}" required${prior.exhausted && index === prior.revealed?.correct_index ? ' checked' : ''}><span>${escapeHtml(choice)}</span></label>`).join('')}</fieldset><button class="button button-primary" type="submit"${resolved ? ' disabled' : ''}>${prior.correct ? 'Correct' : 'Check My Answer'}</button><div class="checkpoint-feedback${prior.exhausted ? ' incorrect' : ''}" aria-live="polite" ${resolved ? '' : 'hidden'}>${priorNote}</div></form>`;
}

function renderStepsBlock(block) {
  return `<p class="kicker">Competition routine</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1><ol class="routine-steps">${block.steps.map(step => `<li><strong>${escapeHtml(step.label)}</strong><span>${escapeHtml(step.detail)}</span></li>`).join('')}</ol>`;
}

function renderImageGalleryBlock(block) {
  return `<p class="kicker">${escapeHtml(block.kicker || 'Visual field guide')}</p><h1 id="lesson-reader-title">${escapeHtml(block.heading)}</h1>${block.body ? `<p class="block-lede">${escapeHtml(block.body)}</p>` : ''}<div class="image-gallery">${(block.images || []).map(img => `<figure><img src="${mediaUrl(img.url)}" alt="${escapeHtml(img.alt || img.label || 'Specimen')}" width="760" height="570" loading="lazy" decoding="async"><figcaption><strong>${escapeHtml(img.label || '')}</strong>${img.note ? `<span>${escapeHtml(img.note)}</span>` : ''}${img.attribution ? `<small>${escapeHtml(img.attribution)}${img.license ? ` · ${escapeHtml(img.license)}` : ''}</small>` : ''}</figcaption></figure>`).join('')}</div>`;
}

function renderVideoBlock(block) {
  const id = /^[A-Za-z0-9_-]{11}$/.test(block.video_id || '') ? block.video_id : '';
  if (!id) return '<p class="block-lede">This video is unavailable.</p>';
  const watchUrl = `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
  return `<p class="kicker">Watch, then apply</p><h1 id="lesson-reader-title">${escapeHtml(block.title || 'Lesson video')}</h1><div class="lesson-video"><div class="lesson-video-frame"><iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?rel=0" title="${escapeHtml(block.title || 'Lesson video')}" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div><div class="lesson-video-meta"><span>${escapeHtml(block.channel || 'YouTube')}</span>${block.duration ? `<span>${Math.round(block.duration / 60)} min</span>` : ''}<a href="${watchUrl}" target="_blank" rel="noopener noreferrer">Open on YouTube ↗</a></div><p class="lesson-video-note">${escapeHtml(block.transcript_excerpt || 'This video is paired with transcript-grounded notes and checkpoints in this lesson.')}</p></div>`;
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
    const exhausted = !result.correct && result.reveal;
    state.currentLesson.progress.checkpoint_results[form.dataset.checkpointForm] = {
      correct: result.correct,
      attempts: result.attempts,
      exhausted,
      revealed: exhausted ? { correct_index: result.correct_index, explanation: result.explanation } : undefined,
    };
    state.currentLesson.progress.status = result.lesson_status;
    refreshLessonFinishButton();     // the last resolved answer must unlock Finish immediately
    refreshLessonNextButton();       // ...and Continue, which was gated on the same answer
    const feedback = form.querySelector('.checkpoint-feedback');
    feedback.hidden = false;
    feedback.classList.toggle('incorrect', !result.correct);
    const block = state.currentLesson.content.find(b => b.id === form.dataset.checkpointForm);
    const answerLine = result.reveal
      ? (checkpointAnswerLine(result.correct_index, block?.choices)
         || (result.correct_choice ? `<p><strong>Answer:</strong> ${escapeHtml(result.correct_choice)}</p>` : ''))
      : '';
    const explanationLine = result.reveal && result.explanation ? `<p>${escapeHtml(result.explanation)}</p>` : '';
    if (result.correct) {
      feedback.innerHTML = `<h3>Correct</h3>${answerLine}${explanationLine}`;
      button.textContent = 'Correct';
      button.disabled = true;
      locked = true;
      await saveCurrentLessonProgress(true);
    } else if (exhausted) {
      feedback.innerHTML = `<h3>Not this time</h3>${result.misconception ? `<p>${escapeHtml(result.misconception)}</p>` : ''}${answerLine}${explanationLine}<p>This check is recorded as missed — review the answer, then continue.</p>`;
      form.querySelector('fieldset').disabled = true;
      // Label it, like the correct branch does. Leaving it on setBusy's "Checking…" left the
      // button reading as though a request were still in flight, permanently.
      button.textContent = 'Answer shown';
      button.disabled = true;
      locked = true;
      await saveCurrentLessonProgress(true);
    } else {
      feedback.innerHTML = `<h3>Wrong — try again</h3><p>You have one more try. Reread the section, then pick again.</p>`;
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

// The Continue button used to look fully enabled on an unanswered knowledge check and do
// nothing but flash a 3.5-second toast at the foot of the page. A student walking the live
// site clicked it seven times before working out that the step was gated. The button now
// says what it needs and switches on the moment the check is resolved.
function refreshLessonNextButton() {
  const next = $('lesson-next');
  if (!next || !state.currentLesson) return;
  const step = lessonSteps()[state.lessonStepIndex];
  const block = step && step.kind === 'block' ? state.currentLesson.content[step.blockIndex] : null;
  const result = block ? state.currentLesson.progress.checkpoint_results[block.id] : null;
  const gated = block?.type === 'checkpoint' && !(result?.correct || result?.exhausted);
  next.disabled = gated;
  next.setAttribute('aria-disabled', gated ? 'true' : 'false');
  if (step?.kind !== 'video') next.textContent = gated ? 'Answer the check to continue' : 'Continue';
}

async function moveLesson(delta) {
  const steps = lessonSteps();
  const step = steps[state.lessonStepIndex] || steps[0];
  const block = state.currentLesson.content[step.blockIndex];
  // Only a reading step can gate on its checkpoint; a video step always advances.
  const checkpointResult = state.currentLesson.progress.checkpoint_results[block.id];
  if (delta > 0 && step.kind === 'block' && block.type === 'checkpoint'
      && !(checkpointResult?.correct || checkpointResult?.exhausted)) {
    toast('Answer this knowledge check before moving on.');
    return;
  }
  try {
    if (delta > 0 && step.kind === 'block') {
      const completed = new Set(state.currentLesson.progress.completed_block_ids || []);
      completed.add(block.id);
      state.currentLesson.progress.completed_block_ids = [...completed];
    }
    state.lessonStepIndex += delta;
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
$('lesson-feedback').addEventListener('click', async () => {
  const lesson = state.currentLesson;
  if (!lesson) return;
  const rating = Number(window.prompt('How useful was this preview? Enter a rating from 1 (not useful) to 5 (very useful).', '5'));
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) return;
  const feedback = window.prompt('What should we improve? (optional)', '') || '';
  try {
    await api('/content/feedback', {
      method: 'POST',
      body: JSON.stringify({ entity_type: 'lesson', entity_id: lesson.id, rating, feedback }),
    });
    toast('Thanks — your feedback was saved for the course team.');
  } catch (error) { toast(error.message); }
});
$('close-lesson').addEventListener('click', closeLesson);

function closeLesson() {
  closeTutor();
  $('lesson-reader').hidden = true;
  $('learn-catalog').hidden = false;
  state.currentLesson = null;
  history.replaceState(null, '', coursePath(activeEvent()));
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

// An attempt left open by "Save & Exit" keeps running against its server deadline. The card
// used to say "Start Exam" and show nothing, so a student resumed a half-spent clock without
// being told — and the open attempt also disables the tutor, with no on-screen way to find
// which exam was responsible.
// The banner asserted "AI-generated practice" for anything unreviewed, so a transcribed 2018
// paper was told to the student as machine-written while the badge beside it said
// "Transcribed from a real past paper". It now says which of the two this exam is, and it
// no longer promises a "Report a problem" control that does not exist inside the runner —
// reporting lives on the review screen after submission.
const EXAM_PROVENANCE_NOTICES = {
  machine_practice: '<strong>AI-generated practice.</strong> These questions were written and '
    + 'checked by automated systems \u2014 a validator, an independent solver, and a verifier '
    + '\u2014 but have not yet been read by a subject expert. Treat them as practice, not as an '
    + 'answer key. After you submit you can report a problem on any question.',
  imported_practice: '<strong>Transcribed from a real past paper.</strong> These questions and '
    + 'their answer key were taken from a tournament paper and converted automatically. '
    + 'Transcription can introduce errors and no subject expert has checked this copy. After '
    + 'you submit you can report a problem on any question.',
  study_pack_practice: '<strong>Sample paper from a 2027 study pack.</strong> These questions and '
    + 'their answer key come from a study pack, not a tournament. The key was checked against '
    + 'the 2027 rules and the official list, but no subject expert has reviewed this copy. After '
    + 'you submit you can report a problem on any question.',
};

function setExamProvenanceNotice() {
  const notice = $('exam-ai-notice');
  if (!notice) return;
  const text = EXAM_PROVENANCE_NOTICES[state.exam?.release_class];
  if (!text || !(state.exam.unreviewed || state.exam.release_class === 'machine_practice')) {
    notice.hidden = true;
    notice.innerHTML = '';
    return;
  }
  notice.innerHTML = text;
  notice.hidden = false;
}

function openAttemptNote(attempt) {
  if (!attempt?.deadline_at) return 'You have an attempt in progress on this exam.';
  const remaining = Math.floor((new Date(attempt.deadline_at).getTime() - Date.now()) / 1000);
  if (remaining <= 0) return 'Your attempt on this exam has run out of time — open it to submit.';
  const minutes = Math.floor(remaining / 60);
  return `Attempt in progress — ${minutes} min ${remaining % 60}s left on the clock.`;
}

async function startExam(id) {
  const button = document.querySelector(`[data-start-exam="${id}"]`);
  setBusy(button, true, 'Preparing Exam…');
  try {
    // A refusal from /start used to reject with nothing shown: the button returned to
    // "Start Exam" and the student could click it forever. The server always sends a
    // `detail` explaining itself; show it.
    state.exam = await api(`/exams/${id}/start`, {
      method: 'POST', headers: { 'X-Exam-Client-Session': state.examClientSession },
    });
    if (state.exam.previous_attempt_auto_submitted) {
      toast('Your earlier attempt reached its time limit and was submitted — this is a fresh attempt.');
    }
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
    // Whatever happened to the previous exam (submitted, left, or failed mid-submit), this one
    // starts with a working Submit button.
    state.submitting = false;
    setBusy($('submit-exam'), false);
    showSection('exam');
    $('exam-title').textContent = state.exam.title;
    $('exam-release-label').textContent = state.exam.release_label;
    // Machine-gated content must say so where the student is working, not only on the card
    // they clicked. `unreviewed` is set by the same rule that governs whether the exam may be
    // served at all, so the banner cannot drift out of step with the gate.
    setExamProvenanceNotice();
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
    ${asset.attribution ? `<figcaption>${escapeHtml(asset.attribution)}${asset.license ? ` · ${escapeHtml(asset.license)}` : ''}${asset.source_url ? ` · <a href="${safeUrl(asset.source_url)}" target="_blank" rel="noopener noreferrer">source</a>` : ''}</figcaption>` : ''}
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
  let submitted = false;
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
    submitted = true;
    localStorage.removeItem(offlineStorageKey());
    state.pendingAutoSubmit = false;
    state.resultsHistory = null;  // a new attempt was just recorded — refresh the cache
    // The Submit button is one element shared by every exam in this page session. It used to be
    // released only on failure, so after the first successful submit it stayed disabled and
    // labelled "Submitting…" for every later exam until the page was reloaded: the click did
    // nothing, sent no request, and so left nothing in any server log.
    state.submitting = false;
    setBusy($('submit-exam'), false);
    await loadReview(state.attempt, result);
  } catch (error) {
    // Once the server has accepted the submit the exam IS handed in. A failure after that point
    // is only the review page failing to load: say so, and never restart the exam clock.
    toast(submitted
      ? 'Your exam was submitted. The review page could not load — open it from Practice & Exams.'
      : error.message);
    state.submitting = false;
    setBusy($('submit-exam'), false);
    if (!submitted) startTimer(state.exam.deadline_at);
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
    elements.status.innerHTML = remediationQuestionMarkup(
      question, `transfer-${result.transfer_id}`, 'data-submit-transfer',
      result.transfer_id, id, 'Submit Transfer Answer');
  } catch (error) { elements.status.textContent = error.message; }
  finally { setBusy(button, false); }
}

// A remediation check is rendered from a question snapshot, and that snapshot is not always
// multiple choice — a short_answer transfer arrives with `choices: []`. Rendering it as a
// fieldset produced an empty "Select one answer" box with no input at all, and the submit
// button then found nothing checked and fired no request, so the Prove step of the error
// loop was a dead end for every short-answer case.
function remediationQuestionMarkup(question, name, submitAttr, transferId, caseId, label) {
  const isChoice = Array.isArray(question.choices) && question.choices.length > 0;
  const field = isChoice
    ? `<fieldset class="choices"><legend>Select one answer</legend>${question.choices.map((choice, index) =>
        `<label class="choice"><input type="radio" name="${name}" value="${index}"><span>${escapeHtml(choice)}</span></label>`).join('')}</fieldset>`
    : `<label class="field"><span>Your answer</span>
         <textarea name="${name}" rows="4" placeholder="Write your answer in your own words."></textarea>
       </label>`;
  return `<div class="question"><h3>${escapeHtml(question.stem)}</h3>${field}`
    + `<button class="button button-primary" type="button" ${submitAttr}="${transferId}" data-for-case="${caseId}">${label}</button></div>`;
}

// Reads whichever input the snapshot produced, so one submit path serves both shapes.
function remediationAnswer(name) {
  const picked = document.querySelector(`input[name="${name}"]:checked`);
  if (picked) return { selected_index: Number(picked.value) };
  const text = document.querySelector(`textarea[name="${name}"]`);
  const value = text ? text.value.trim() : '';
  return value ? { text: value } : null;
}

async function submitTransfer(transferId, caseId, button) {
  const elements = caseElements(button);
  const answer = remediationAnswer(`transfer-${transferId}`);
  if (!answer) { toast('Write or choose an answer before submitting the transfer check.'); return; }
  setBusy(button, true, 'Checking Answer…');
  try {
    const result = await api(`/remediation/transfer/${transferId}/submit`, { method: 'POST', body: JSON.stringify({ answer }) });
    if (result.correct) {
      toast('Fixed. Your recheck is scheduled for 3 days from now.');
      state.dashboard = await api(`/student/dashboard?event_slug=${encodeURIComponent(state.activeEventSlug)}`);
      updateDashboard();
      return;
    }
    elements.status.innerHTML = `<p>Not yet. Return to the explanation, strengthen your reflection, then try a new transfer check.</p><button class="button button-primary" type="button" data-start-transfer="${caseId}">Try Another Transfer Check</button>`;
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
}

async function startDelayedReview(id, button) {
  const elements = caseElements(button);
  setBusy(button, true, 'Building Retention Check…');
  try {
    const result = await api(`/remediation/${id}/delayed-review`, { method: 'POST' });
    const question = result.question;
    elements.status.innerHTML = remediationQuestionMarkup(
      question, `delayed-${result.transfer_id}`, 'data-submit-delayed',
      result.transfer_id, id, 'Submit Retention Answer');
    button.hidden = true;
  } catch (error) { elements.status.textContent = error.message; }
  finally { setBusy(button, false); }
}

async function submitDelayedReview(transferId, caseId, button) {
  const elements = caseElements(button);
  const answer = remediationAnswer(`delayed-${transferId}`);
  if (!answer) { elements.status.insertAdjacentHTML('afterbegin', '<p>Write or choose an answer before submitting the retention check.</p>'); return; }
  setBusy(button, true, 'Checking Retention…');
  try {
    const result = await api(`/remediation/delayed-review/${transferId}/submit`, { method: 'POST', body: JSON.stringify({ answer }) });
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
  const roleHome = roleHomeView();
  let view = { '#learn': 'learn', '#practice': 'practice', '#errors': 'errors', '#coach': 'coach', '#content': 'content', '#insights': 'content', '#parent': 'parent' }[hashRoute] || roleHome;
  // A student who has not chosen a subject yet has nothing to see in Courses or
  // Practice — land them on the guided picker instead of an empty shell.
  if (['learn', 'practice'].includes(view) && roleHome === 'dashboard' && state.events.length && !activeEvent()) {
    view = 'dashboard';
  }
  showView(view, false);
  // #insights is a shareable link to the teaching view, not just a tab someone clicked.
  if (hashRoute === '#insights' && view === 'content') setContentTab('insights');
});

async function initialize() {
  // Google sign-in fails *open*. It used to be hidden by default and revealed only after
  // /auth/config succeeded, so any hiccup on that one request — a cold start, a dropped
  // connection, a slow boot — left the page showing password fields only, with no way for a
  // Google-account user to get in and nothing on screen explaining why. Hiding a working
  // sign-in route is a worse failure than briefly showing one that is unavailable.
  const googleAuth = $('google-auth');
  const remembered = localStorage.getItem('authProvider');
  if (googleAuth) googleAuth.hidden = remembered === 'local';
  try {
    state.authConfig = await api('/auth/config');
    localStorage.setItem('authProvider', state.authConfig.provider);
    if (googleAuth) googleAuth.hidden = state.authConfig.provider !== 'firebase';
  } catch (error) {
    $('auth-error').textContent = 'The sign-in service is unavailable. Refresh the page or try again later.';
  }
  // Must run after /auth/config: the Firebase SDK is configured from it. A redirect sign-in
  // finishes here, on the page Google sends the user back to, not in continueWithGoogle.
  if (state.authConfig?.provider === 'firebase' && await resumeGoogleRedirect()) return;
  if (state.token && state.user) loadApplication(); else showSection('auth');
}

initialize();


// --- Generated video lessons -------------------------------------------------
// Chapters are short per-sub-topic clips; selecting one swaps the player source so a
// student can jump straight to the part they need instead of scrubbing one long file.
// A chapter covers a run of sections but *opens* only the first of them. Badging every
// covered section made one chapter look like three separate videos.
function chapterOpeningBlock(blockIndex) {
  const chapters = state.lessonVideoChapters || [];
  for (let i = 0; i < chapters.length; i += 1) {
    if ((chapters[i].block_indexes || [])[0] === blockIndex) return { ...chapters[i], index: i };
  }
  return null;
}

function chapterForBlock(blockIndex) {
  const chapters = state.lessonVideoChapters || [];
  for (let i = 0; i < chapters.length; i += 1) {
    if ((chapters[i].block_indexes || []).includes(blockIndex)) return { ...chapters[i], index: i };
  }
  return null;
}

// Jump the reader to a chapter's step; the sequence itself plays it.
function playChapterInline(index) {
  const chapter = (state.lessonVideoChapters || [])[index];
  const first = (chapter?.block_indexes || [])[0];
  if (typeof first === 'number') {
    state.lessonStepIndex = stepForBlock(first);
    renderLessonBlock();
  }
  return;
}

function _unusedPlayChapterInline(index) {
  const chapter = (state.lessonVideoChapters || [])[index];
  if (!chapter) return;
  const host = $('lesson-inline-video');
  host.hidden = false;
  host.innerHTML = `
    <div class="inline-video-head">
      <strong>${escapeHtml(chapter.title)}</strong>
      <button type="button" class="button button-quiet button-compact" data-close-inline-video>Close video</button>
    </div>
    <video class="inline-video-player" controls autoplay playsinline src="${safeUrl(chapter.playback_url)}"></video>
    <p class="inline-video-note">Watching covers the same material as the section below.</p>`;
  host.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  // Watching counts as covering the section, so a viewer is not penalised against a reader.
  const first = (chapter.block_indexes || [])[0];
  if (typeof first === 'number') markBlockCovered(first);
}

function markBlockCovered(blockIndex) {
  const lesson = state.currentLesson;
  const block = lesson?.content?.[blockIndex];
  if (!block) return;
  const done = new Set(lesson.progress.completed_block_ids || []);
  if (done.has(block.id)) return;
  done.add(block.id);
  lesson.progress.completed_block_ids = [...done];
  renderLessonOutline();
  saveLessonProgress().catch(() => {});
}

async function loadLessonVideo(lessonId) {
  const section = $('lesson-video');
  if (!section) return;
  section.hidden = true;
  state.lessonVideoChapters = [];
  try {
    const data = await api(`/lessons/${lessonId}/videos`);
    const chapters = data.chapters || [];
    if (!chapters.length) return;
    state.lessonVideoChapters = chapters;
    const total = chapters.reduce((sum, c) => sum + (c.duration_seconds || 0), 0);
    $('lesson-video-count').textContent =
      `${chapters.length} chapter${chapters.length === 1 ? '' : 's'} · ${formatClock(total)}`;
    section.hidden = false;
    // Rebuild the sequence now that chapters are known: each chapter becomes the step that
    // opens the section it teaches. Preserve the reader's place rather than jumping to the top.
    const wasAt = state.lessonBlockIndex || 0;
    state.lessonSteps = null;
    buildLessonSteps();
    state.lessonStepIndex = stepForBlock(wasAt);
    renderLessonBlock();
  } catch (error) {
    section.hidden = true;   // a missing video must never break the lesson
  }
}

function formatClock(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

// --- Staff: video review queue ----------------------------------------------
async function renderVideoReviewQueue() {
  const host = $('video-review-list');
  if (!host) return;
  try {
    const data = await api('/content/video-renders?status=pending');
    const renders = data.renders || [];
    state.videoReviewCount = renders.length;
    updateContentTabBadges();
    $('video-review-count').textContent = renders.length ? `${renders.length} awaiting review` : 'Queue clear';
    if (!renders.length) {
      host.innerHTML = '<p class="catalog-empty">No rendered videos are waiting for review.</p>';
      return;
    }
    host.innerHTML = renders.map(render => `
      <article class="video-review-card surface" data-render="${render.render_id}">
        <header>
          <h4>${escapeHtml(render.lesson_title || 'Lesson')} — ${escapeHtml(render.chapter)}</h4>
          <span>v${render.version} · ${formatClock(render.duration_seconds)} · ${render.scenes || '?'} scenes</span>
        </header>
        <video class="video-review-player" controls preload="metadata" src="${safeUrl(render.playback_url)}"></video>
        <label class="video-review-note">
          <span>Notes (required to reject — say what to fix and where)</span>
          <textarea data-note="${render.render_id}" rows="2" placeholder="e.g. scene 3: caption drifts after 00:12"></textarea>
        </label>
        <footer class="video-review-actions">
          <button type="button" class="button button-secondary" data-video-qa="rejected" data-render-id="${render.render_id}">Request changes</button>
          <button type="button" class="button" data-video-qa="approved" data-render-id="${render.render_id}">Approve for students</button>
        </footer>
      </article>`).join('');
  } catch (error) { toast(error.message); }
}

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-video-qa]');
  if (!button) return;
  const renderId = button.dataset.renderId;
  const decision = button.dataset.videoQa;
  const text = (document.querySelector(`[data-note="${renderId}"]`)?.value || '').trim();
  if (decision === 'rejected' && !text) {
    toast('Add a note describing what to fix before requesting changes.');
    return;
  }
  setBusy(button, true, decision === 'approved' ? 'Approving…' : 'Sending…');
  try {
    await api(`/content/video-renders/${renderId}/qa`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes: text ? [{ note: text }] : [] }),
    });
    toast(decision === 'approved' ? 'Approved — students can watch it.' : 'Sent back with notes.');
    renderVideoReviewQueue();
  } catch (error) { toast(error.message); }
  finally { setBusy(button, false); }
});


document.addEventListener('click', event => {
  const play = event.target.closest('[data-play-chapter]');
  if (play) { event.preventDefault(); event.stopPropagation(); playChapterInline(Number(play.dataset.playChapter)); return; }
  if (event.target.closest('[data-close-inline-video]')) {
    const host = $('lesson-inline-video');
    host.hidden = true; host.innerHTML = '';
  }
});


document.addEventListener('click', event => {
  if (event.target.closest('#lesson-watch-all')) playChapterInline(0);
});
