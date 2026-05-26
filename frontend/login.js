// Login + Registrierung – Aurora Minutes
// - Tab-Umschaltung Login / Registrieren
// - Inline-Validierung pro Feld
// - Passwort-Anzeigen-Toggle
// - Passwort-Stärke-Indikator (Registrierung)
// - Submit-Button mit Spinner-Loading-State
// - Version-Badge im Footer

const els = {
  form: document.getElementById("authForm"),
  tabLogin: document.getElementById("tabLogin"),
  tabRegister: document.getElementById("tabRegister"),
  toggleLink: document.getElementById("authToggleLink"),
  nameField: document.getElementById("authNameField"),
  nameInput: document.getElementById("authNameInput"),
  nameError: document.getElementById("authNameError"),
  emailInput: document.getElementById("authEmailInput"),
  emailError: document.getElementById("authEmailError"),
  passwordInput: document.getElementById("authPasswordInput"),
  passwordError: document.getElementById("authPasswordError"),
  passwordToggle: document.getElementById("authPasswordToggle"),
  strength: document.getElementById("authPasswordStrength"),
  strengthFill: document.querySelector(".auth-strength-fill"),
  strengthLabel: document.querySelector(".auth-strength-label"),
  submitBtn: document.getElementById("authSubmitBtn"),
  submitLabel: document.querySelector(".auth-submit-label"),
  formError: document.getElementById("authFormError"),
  statusText: document.getElementById("loginStatusText"),
  versionBadge: document.getElementById("authVersionBadge"),
};

const resolveApiBase = () => {
  const config = window.__APP_CONFIG__ || {};
  if (config.API_BASE_URL === "same-origin") return window.location.origin;
  if (config.API_BASE_URL) return config.API_BASE_URL.replace(/\/$/, "");
  const port = config.API_PORT || "";
  const portSegment = port ? `:${port}` : "";
  return `${window.location.protocol}//${window.location.hostname}${portSegment}`.replace(/\/$/, "");
};

const API_BASE = resolveApiBase() || "http://localhost:8000";
const AUTH_REGISTER_ENDPOINT = `${API_BASE}/api/auth/register`;
const AUTH_LOGIN_ENDPOINT = `${API_BASE}/api/auth/login`;
const AUTH_ME_ENDPOINT = `${API_BASE}/api/auth/me`;
const RELEASE_ENDPOINT = `${API_BASE}/api/release/current`;
const AUTH_TOKEN_STORAGE_KEY = "aurora-auth-token-v1";
const CLIENT_ID_HEADER = "X-Client-Id";
const CLIENT_ID_STORAGE_KEY = "aurora-client-id-v1";

let currentMode = "login"; // "login" | "register"
let submitting = false;

// ---------- Helpers ----------

const getClientId = () => {
  let id = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
  if (!id) {
    id = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `aurora-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(CLIENT_ID_STORAGE_KEY, id);
  }
  return id;
};

const setError = (el, message) => {
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("is-visible", !!message);
};

const clearErrors = () => {
  setError(els.nameError, "");
  setError(els.emailError, "");
  setError(els.passwordError, "");
  if (els.formError) {
    els.formError.textContent = "";
    els.formError.classList.add("hidden");
  }
};

const setFormError = (message) => {
  if (!els.formError) return;
  els.formError.textContent = message || "";
  els.formError.classList.toggle("hidden", !message);
};

const setStatus = (text) => {
  if (els.statusText) els.statusText.textContent = text || "";
};

const setSubmitting = (value) => {
  submitting = !!value;
  if (!els.submitBtn) return;
  els.submitBtn.disabled = submitting;
  els.submitBtn.classList.toggle("is-loading", submitting);
};

// ---------- Validation ----------

const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

const validateName = (value) => {
  if (currentMode !== "register") return "";
  const trimmed = (value || "").trim();
  if (trimmed.length < 2) return "Bitte einen Namen mit mindestens 2 Zeichen angeben.";
  return "";
};

const validateEmail = (value) => {
  const trimmed = (value || "").trim();
  if (!trimmed) return "Bitte eine E-Mail-Adresse angeben.";
  if (!EMAIL_RE.test(trimmed)) return "Bitte eine gültige E-Mail-Adresse angeben.";
  return "";
};

const validatePassword = (value) => {
  const v = value || "";
  if (v.length < 8) return "Passwort muss mindestens 8 Zeichen lang sein.";
  if (currentMode === "register") {
    // Empfehlung, nicht hart pflichtig
    if (v.length < 10) return "";
  }
  return "";
};

const computeStrength = (value) => {
  const v = value || "";
  let score = 0;
  if (v.length >= 8) score += 1;
  if (v.length >= 12) score += 1;
  if (/[A-Z]/.test(v) && /[a-z]/.test(v)) score += 1;
  if (/\d/.test(v)) score += 1;
  if (/[^A-Za-z0-9]/.test(v)) score += 1;
  return Math.min(score, 4); // 0..4
};

const STRENGTH_LABELS = ["Sehr schwach", "Schwach", "Akzeptabel", "Gut", "Stark"];

const renderStrength = () => {
  const v = els.passwordInput?.value || "";
  if (currentMode !== "register" || !v) {
    els.strength?.classList.add("hidden");
    return;
  }
  els.strength?.classList.remove("hidden");
  const score = computeStrength(v);
  if (els.strengthFill) {
    els.strengthFill.dataset.level = String(score);
  }
  if (els.strengthLabel) {
    els.strengthLabel.textContent = STRENGTH_LABELS[score];
  }
};

// ---------- Mode switching ----------

const setMode = (mode) => {
  currentMode = mode === "register" ? "register" : "login";
  const isRegister = currentMode === "register";

  els.tabLogin?.classList.toggle("is-active", !isRegister);
  els.tabLogin?.setAttribute("aria-selected", String(!isRegister));
  els.tabRegister?.classList.toggle("is-active", isRegister);
  els.tabRegister?.setAttribute("aria-selected", String(isRegister));

  els.nameField?.classList.toggle("hidden", !isRegister);
  if (els.nameInput) els.nameInput.required = isRegister;

  if (els.submitLabel) els.submitLabel.textContent = isRegister ? "Registrieren" : "Anmelden";
  if (els.passwordInput) {
    els.passwordInput.autocomplete = isRegister ? "new-password" : "current-password";
    els.passwordInput.placeholder = isRegister ? "Mindestens 8 Zeichen" : "Passwort";
  }

  document.querySelectorAll("[data-when]").forEach((el) => {
    el.style.display = el.dataset.when === currentMode ? "inline" : "none";
  });
  if (els.toggleLink) {
    const next = isRegister ? "login" : "register";
    els.toggleLink.dataset.target = next;
    els.toggleLink.textContent = isRegister ? "Jetzt anmelden" : "Jetzt registrieren";
  }

  clearErrors();
  renderStrength();
  setStatus("");
};

// ---------- Submit ----------

const doSubmit = async (event) => {
  event.preventDefault();
  if (submitting) return;
  clearErrors();

  const nameValue = els.nameInput?.value || "";
  const emailValue = els.emailInput?.value || "";
  const passwordValue = els.passwordInput?.value || "";

  const nameErr = validateName(nameValue);
  const emailErr = validateEmail(emailValue);
  const passwordErr = validatePassword(passwordValue);

  setError(els.nameError, nameErr);
  setError(els.emailError, emailErr);
  setError(els.passwordError, passwordErr);

  if (nameErr || emailErr || passwordErr) {
    return;
  }

  const endpoint = currentMode === "register" ? AUTH_REGISTER_ENDPOINT : AUTH_LOGIN_ENDPOINT;
  const payload =
    currentMode === "register"
      ? { name: nameValue.trim(), email: emailValue.trim(), password: passwordValue }
      : { email: emailValue.trim(), password: passwordValue };

  setSubmitting(true);
  setStatus(currentMode === "register" ? "Konto wird angelegt …" : "Anmeldung läuft …");
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [CLIENT_ID_HEADER]: getClientId(),
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let message = `Fehler ${response.status}`;
      try {
        const body = await response.json();
        if (body?.detail) message = body.detail;
      } catch (_) {
        /* keep status */
      }
      throw new Error(message);
    }
    const data = await response.json();
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, data.token);
    setStatus(`Willkommen, ${data.user?.name || "Nutzer"}!`);
    window.location.replace("index.html");
  } catch (error) {
    setStatus("");
    setFormError(error?.message || "Anmeldung fehlgeschlagen.");
  } finally {
    setSubmitting(false);
  }
};

// ---------- Auto-redirect if session already valid ----------

const ensureSession = async () => {
  const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  if (!token) return;
  try {
    const response = await fetch(AUTH_ME_ENDPOINT, {
      headers: { Authorization: `Bearer ${token}`, [CLIENT_ID_HEADER]: getClientId() },
    });
    if (response.ok) {
      window.location.replace("index.html");
    } else if (response.status === 401) {
      // Stale token – aufräumen, damit User sich neu anmelden kann
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    }
  } catch (_) {
    // Backend offline – User sieht das Formular und kann es später versuchen
  }
};

// ---------- Version badge ----------

const loadVersionBadge = async () => {
  if (!els.versionBadge) return;
  try {
    const response = await fetch(RELEASE_ENDPOINT, { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const data = await response.json();
    if (data?.version) els.versionBadge.textContent = `v${data.version}`;
  } catch (_) {
    /* ignore */
  }
};

// ---------- Wire up ----------

els.tabLogin?.addEventListener("click", () => setMode("login"));
els.tabRegister?.addEventListener("click", () => setMode("register"));

els.toggleLink?.addEventListener("click", (event) => {
  event.preventDefault();
  setMode(els.toggleLink.dataset.target === "register" ? "register" : "login");
});

els.passwordToggle?.addEventListener("click", () => {
  if (!els.passwordInput) return;
  const isPw = els.passwordInput.type === "password";
  els.passwordInput.type = isPw ? "text" : "password";
  els.passwordToggle.setAttribute("aria-pressed", String(isPw));
  els.passwordToggle.setAttribute("aria-label", isPw ? "Passwort verbergen" : "Passwort anzeigen");
});

els.passwordInput?.addEventListener("input", renderStrength);
els.nameInput?.addEventListener("blur", () => setError(els.nameError, validateName(els.nameInput.value)));
els.emailInput?.addEventListener("blur", () => setError(els.emailError, validateEmail(els.emailInput.value)));
els.passwordInput?.addEventListener("blur", () => setError(els.passwordError, validatePassword(els.passwordInput.value)));

els.form?.addEventListener("submit", doSubmit);

setMode("login");
void ensureSession();
void loadVersionBadge();
