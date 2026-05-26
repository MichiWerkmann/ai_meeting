// Profil-Seite – Name ändern + Passwort ändern

const resolveApiBase = () => {
  const config = window.__APP_CONFIG__ || {};
  if (config.API_BASE_URL === "same-origin") return window.location.origin;
  if (config.API_BASE_URL) return config.API_BASE_URL.replace(/\/$/, "");
  const port = config.API_PORT || "";
  const portSegment = port ? `:${port}` : "";
  return `${window.location.protocol}//${window.location.hostname}${portSegment}`.replace(/\/$/, "");
};

const API_BASE = resolveApiBase() || "http://localhost:8000";
const AUTH_ME = `${API_BASE}/api/auth/me`;
const AUTH_PROFILE = `${API_BASE}/api/auth/profile`;
const AUTH_PW = `${API_BASE}/api/auth/change-password`;
const TOKEN_KEY = "aurora-auth-token-v1";
const CLIENT_ID_KEY = "aurora-client-id-v1";

const getClientId = () => localStorage.getItem(CLIENT_ID_KEY) || "";
const getToken = () => localStorage.getItem(TOKEN_KEY) || "";

const redirectLogin = () => {
  localStorage.removeItem(TOKEN_KEY);
  window.location.replace("login.html");
};

const headers = () => ({
  "Content-Type": "application/json",
  "X-Client-Id": getClientId(),
  Authorization: `Bearer ${getToken()}`,
});

const setError = (id, msg) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("is-visible", !!msg);
};

const setLoading = (btn, loading) => {
  if (!btn) return;
  btn.disabled = !!loading;
  btn.classList.toggle("is-loading", !!loading);
};

const showSuccess = (id, ms = 4000) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), ms);
};

const showFormError = (id, msg) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("hidden", !msg);
};

const formatDate = (epoch) => {
  if (!epoch && epoch !== 0) return "—";
  try {
    return new Date(epoch * 1000).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch (_) {
    return "—";
  }
};

// ---------- Load profile ----------

const loadProfile = async () => {
  if (!getToken()) {
    redirectLogin();
    return;
  }
  try {
    const r = await fetch(AUTH_ME, { headers: headers() });
    if (r.status === 401) {
      redirectLogin();
      return;
    }
    if (!r.ok) throw new Error(`API ${r.status}`);
    const user = await r.json();
    document.getElementById("profileGreeting").textContent = `Hallo, ${user.name}`;
    document.getElementById("profileName").textContent = user.name;
    document.getElementById("profileEmail").textContent = user.email;
    document.getElementById("profileRole").innerHTML = user.is_admin
      ? '<span class="admin-pill admin-pill-admin">Administrator</span>'
      : '<span class="admin-pill admin-pill-active">Benutzer</span>';
    document.getElementById("profileCreatedAt").textContent = formatDate(user.created_at);
    document.getElementById("profileLastLogin").textContent = formatDate(user.last_login_at);
    document.getElementById("nameInput").value = user.name;
  } catch (err) {
    showFormError("pwFormError", err?.message || "Profil konnte nicht geladen werden.");
  }
};

// ---------- Name form ----------

document.getElementById("nameForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("nameErrorMsg", "");
  const input = document.getElementById("nameInput");
  const btn = document.getElementById("nameSubmit");
  const value = (input?.value || "").trim();
  if (value.length < 2) {
    setError("nameErrorMsg", "Bitte mindestens 2 Zeichen eingeben.");
    return;
  }
  setLoading(btn, true);
  try {
    const r = await fetch(AUTH_PROFILE, {
      method: "PATCH",
      headers: headers(),
      body: JSON.stringify({ name: value }),
    });
    if (r.status === 401) return redirectLogin();
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body?.detail || `Fehler ${r.status}`);
    }
    const user = await r.json();
    document.getElementById("profileGreeting").textContent = `Hallo, ${user.name}`;
    document.getElementById("profileName").textContent = user.name;
    showSuccess("nameSuccess");
  } catch (err) {
    setError("nameErrorMsg", err?.message || "Speichern fehlgeschlagen.");
  } finally {
    setLoading(btn, false);
  }
});

// ---------- Password toggles ----------

document.querySelectorAll("[data-toggle]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = document.getElementById(btn.dataset.toggle);
    if (!target) return;
    const isPw = target.type === "password";
    target.type = isPw ? "text" : "password";
    btn.setAttribute("aria-pressed", String(isPw));
    btn.setAttribute("aria-label", isPw ? "Passwort verbergen" : "Passwort anzeigen");
  });
});

// ---------- Password strength ----------

const computeStrength = (v) => {
  let score = 0;
  if (v.length >= 8) score += 1;
  if (v.length >= 12) score += 1;
  if (/[A-Z]/.test(v) && /[a-z]/.test(v)) score += 1;
  if (/\d/.test(v)) score += 1;
  if (/[^A-Za-z0-9]/.test(v)) score += 1;
  return Math.min(score, 4);
};
const STRENGTH_LABELS = ["Sehr schwach", "Schwach", "Akzeptabel", "Gut", "Stark"];

const newPwInput = document.getElementById("newPw");
newPwInput?.addEventListener("input", () => {
  const v = newPwInput.value;
  const wrap = document.getElementById("newPwStrength");
  const fill = wrap?.querySelector(".auth-strength-fill");
  const label = wrap?.querySelector(".auth-strength-label");
  if (!v) {
    wrap?.classList.add("hidden");
    return;
  }
  wrap?.classList.remove("hidden");
  const score = computeStrength(v);
  if (fill) fill.dataset.level = String(score);
  if (label) label.textContent = STRENGTH_LABELS[score];
});

// ---------- Password form ----------

document.getElementById("passwordForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("currentPwError", "");
  setError("newPwError", "");
  setError("confirmPwError", "");
  showFormError("pwFormError", "");

  const current = document.getElementById("currentPw").value;
  const next = document.getElementById("newPw").value;
  const confirm = document.getElementById("confirmPw").value;

  let hasError = false;
  if (!current) {
    setError("currentPwError", "Aktuelles Passwort fehlt.");
    hasError = true;
  }
  if (next.length < 8) {
    setError("newPwError", "Mindestens 8 Zeichen.");
    hasError = true;
  }
  if (next !== confirm) {
    setError("confirmPwError", "Passwörter stimmen nicht überein.");
    hasError = true;
  }
  if (next && current && next === current) {
    setError("newPwError", "Neues Passwort darf nicht mit dem aktuellen identisch sein.");
    hasError = true;
  }
  if (hasError) return;

  const btn = document.getElementById("passwordSubmit");
  setLoading(btn, true);
  try {
    const r = await fetch(AUTH_PW, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    if (r.status === 401) return redirectLogin();
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body?.detail || `Fehler ${r.status}`);
    }
    document.getElementById("passwordForm").reset();
    document.getElementById("newPwStrength")?.classList.add("hidden");
    showSuccess("pwSuccess");
  } catch (err) {
    showFormError("pwFormError", err?.message || "Passwort konnte nicht geändert werden.");
  } finally {
    setLoading(btn, false);
  }
});

void loadProfile();
