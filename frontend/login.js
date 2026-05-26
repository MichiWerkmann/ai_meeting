const authForm = document.getElementById("authForm");
const authMode = document.getElementById("authMode");
const authNameField = document.getElementById("authNameField");
const authNameInput = document.getElementById("authNameInput");
const authEmailInput = document.getElementById("authEmailInput");
const authPasswordInput = document.getElementById("authPasswordInput");
const authSubmitBtn = document.getElementById("authSubmitBtn");
const loginStatusText = document.getElementById("loginStatusText");
const loginStatusBadge = document.getElementById("loginStatusBadge");

const resolveApiBase = () => {
  const config = window.__APP_CONFIG__ || {};
  if (config.API_BASE_URL === "same-origin") {
    return window.location?.origin || null;
  }
  if (config.API_BASE_URL) {
    return config.API_BASE_URL.replace(/\/$/, "");
  }
  const { protocol, hostname } = window.location || {};
  if (!protocol || !hostname) {
    return null;
  }
  const port = config.API_PORT || "8000";
  const portSegment = port ? `:${port}` : "";
  return `${protocol}//${hostname}${portSegment}`.replace(/\/$/, "");
};

const API_BASE = resolveApiBase() || "http://localhost:8000";
const AUTH_REGISTER_ENDPOINT = `${API_BASE}/api/auth/register`;
const AUTH_LOGIN_ENDPOINT = `${API_BASE}/api/auth/login`;
const AUTH_ME_ENDPOINT = `${API_BASE}/api/auth/me`;
const AUTH_TOKEN_STORAGE_KEY = "aurora-auth-token-v1";
const CLIENT_ID_HEADER = "X-Client-Id";

const generateClientId = () => {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `aurora-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const getClientId = () => {
  const existing = localStorage.getItem("aurora-client-id-v1");
  if (existing) {
    return existing;
  }
  const next = generateClientId();
  localStorage.setItem("aurora-client-id-v1", next);
  return next;
};

const readErrorMessage = async (response, fallback) => {
  try {
    const payload = await response.json();
    return payload?.detail || fallback;
  } catch (_error) {
    return fallback;
  }
};

const withBaseHeaders = () => ({
  "Content-Type": "application/json",
  [CLIENT_ID_HEADER]: getClientId(),
});

const redirectToApp = () => {
  window.location.replace("index.html");
};

const setStatus = (text, badgeText = "") => {
  if (loginStatusText) {
    loginStatusText.textContent = text;
  }
  if (loginStatusBadge) {
    loginStatusBadge.textContent = badgeText || "";
  }
};

const ensureSession = async () => {
  const token = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  if (!token) {
    return false;
  }
  try {
    const response = await fetch(AUTH_ME_ENDPOINT, {
      headers: {
        [CLIENT_ID_HEADER]: getClientId(),
        Authorization: `Bearer ${token}`,
      },
    });
    if (!response.ok) {
      return false;
    }
    redirectToApp();
    return true;
  } catch (_error) {
    return false;
  }
};

authMode?.addEventListener("change", () => {
  const registerMode = authMode.value === "register";
  authNameField?.classList.toggle("hidden", !registerMode);
  if (authSubmitBtn) {
    authSubmitBtn.textContent = registerMode ? "Registrieren" : "Anmelden";
  }
  if (authPasswordInput) {
    authPasswordInput.autocomplete = registerMode ? "new-password" : "current-password";
  }
});

authForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const mode = authMode?.value === "register" ? "register" : "login";
  const endpoint = mode === "register" ? AUTH_REGISTER_ENDPOINT : AUTH_LOGIN_ENDPOINT;
  const payload =
    mode === "register"
      ? {
          name: authNameInput?.value?.trim() || "",
          email: authEmailInput?.value?.trim() || "",
          password: authPasswordInput?.value || "",
        }
      : {
          email: authEmailInput?.value?.trim() || "",
          password: authPasswordInput?.value || "",
        };

  if (authSubmitBtn) {
    authSubmitBtn.disabled = true;
  }
  setStatus("Anmeldung läuft ...", "Bitte warten");
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: withBaseHeaders(),
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, `API Fehler ${response.status}`));
    }
    const data = await response.json();
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, data.token);
    setStatus(`Willkommen ${data.user?.name || ""}`.trim(), "Erfolgreich");
    redirectToApp();
  } catch (error) {
    setStatus(error?.message || "Anmeldung fehlgeschlagen.", "Fehler");
  } finally {
    if (authSubmitBtn) {
      authSubmitBtn.disabled = false;
    }
  }
});

authMode?.dispatchEvent(new Event("change"));
void ensureSession();
