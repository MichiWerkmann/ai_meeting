// Admin-Benutzerverwaltung

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
const ADMIN_USERS = `${API_BASE}/api/admin/users`;
const TOKEN_KEY = "aurora-auth-token-v1";
const CLIENT_ID_KEY = "aurora-client-id-v1";

const getToken = () => localStorage.getItem(TOKEN_KEY) || "";
const getClientId = () => localStorage.getItem(CLIENT_ID_KEY) || "";

const headers = (extra = {}) => ({
  "Content-Type": "application/json",
  "X-Client-Id": getClientId(),
  Authorization: `Bearer ${getToken()}`,
  ...extra,
});

const redirectLogin = () => {
  localStorage.removeItem(TOKEN_KEY);
  window.location.replace("login.html");
};

const escapeHtml = (s) =>
  String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

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

let currentMe = null;

// ---------- Confirm-Modal (generisch, mit Feldern) ----------

const confirmDialog = ({ title, message, okLabel = "OK", okDanger = false, fields = [] }) =>
  new Promise((resolve) => {
    const overlay = document.getElementById("confirmOverlay");
    const titleEl = document.getElementById("confirmTitle");
    const messageEl = document.getElementById("confirmMessage");
    const fieldsEl = document.getElementById("confirmFields");
    const okBtn = document.getElementById("confirmOk");
    const cancelBtn = document.getElementById("confirmCancel");
    if (!overlay) return resolve(null);

    titleEl.textContent = title || "Bestätigen";
    messageEl.textContent = message || "";
    fieldsEl.innerHTML = "";

    const inputs = {};
    fields.forEach((f) => {
      const wrap = document.createElement("div");
      wrap.className = "auth-field";
      wrap.style.marginTop = "0.6rem";
      const label = document.createElement("label");
      label.textContent = f.label;
      label.htmlFor = `confirmInput_${f.name}`;
      const input = document.createElement("input");
      input.id = `confirmInput_${f.name}`;
      input.type = f.type || "text";
      if (f.placeholder) input.placeholder = f.placeholder;
      if (f.value !== undefined) input.value = f.value;
      if (f.minLength) input.minLength = f.minLength;
      if (f.required) input.required = true;
      if (f.autocomplete) input.autocomplete = f.autocomplete;
      wrap.appendChild(label);
      wrap.appendChild(input);
      fieldsEl.appendChild(wrap);
      inputs[f.name] = input;
    });

    okBtn.textContent = okLabel;
    okBtn.style.background = okDanger
      ? "linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)"
      : "";

    const close = (value) => {
      overlay.classList.add("hidden");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onOk = () => {
      const values = {};
      for (const [name, input] of Object.entries(inputs)) values[name] = input.value;
      close(values);
    };
    const onCancel = () => close(null);
    const onBackdrop = (e) => { if (e.target === overlay) close(null); };
    const onKey = (e) => {
      if (e.key === "Escape") close(null);
      if (e.key === "Enter" && document.activeElement !== cancelBtn) onOk();
    };

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
    overlay.classList.remove("hidden");
    (fields[0] ? inputs[fields[0].name] : okBtn).focus();
  });

const toast = (message, type = "info") => {
  // Lightweight inline toast
  let host = document.getElementById("__adminToastHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "__adminToastHost";
    host.style.cssText = "position:fixed;top:1rem;right:1rem;z-index:12000;display:grid;gap:0.5rem;max-width:340px;";
    document.body.appendChild(host);
  }
  const el = document.createElement("div");
  el.textContent = message;
  el.style.cssText = `
    padding: 0.7rem 1rem;
    border-radius: 10px;
    color: #fff;
    font-size: 0.9rem;
    box-shadow: 0 10px 26px rgba(8,14,28,0.35);
    background: ${type === "error" ? "#b91c1c" : type === "success" ? "#10b981" : "#0b6a4f"};
    opacity: 0;
    transform: translateY(-4px);
    transition: opacity 160ms ease, transform 160ms ease;
  `;
  host.appendChild(el);
  requestAnimationFrame(() => { el.style.opacity = "1"; el.style.transform = "translateY(0)"; });
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(-4px)";
    setTimeout(() => el.remove(), 200);
  }, 3500);
};

// ---------- Bootstrap: gate auf Admin ----------

const ensureAdmin = async () => {
  if (!getToken()) {
    redirectLogin();
    return false;
  }
  try {
    const r = await fetch(AUTH_ME, { headers: headers() });
    if (r.status === 401) { redirectLogin(); return false; }
    if (!r.ok) throw new Error(`API ${r.status}`);
    const me = await r.json();
    if (!me.is_admin) {
      document.body.innerHTML = `
        <main class="app-shell profile-page">
          <div class="profile-card">
            <h2>Kein Zugriff</h2>
            <p>Diese Seite ist nur für Administratoren sichtbar. <a href="index.html">Zur App</a>.</p>
          </div>
        </main>`;
      return false;
    }
    currentMe = me;
    return true;
  } catch (err) {
    toast(err?.message || "Konnte Anmeldung nicht prüfen.", "error");
    return false;
  }
};

// ---------- Render users table ----------

const loadUsers = async () => {
  const body = document.getElementById("adminUsersBody");
  if (!body) return;
  body.innerHTML = '<tr><td colspan="6" class="admin-empty">Lade Benutzer…</td></tr>';
  try {
    const r = await fetch(ADMIN_USERS, { headers: headers() });
    if (r.status === 401) return redirectLogin();
    if (r.status === 403) {
      body.innerHTML = '<tr><td colspan="6" class="admin-empty">Kein Zugriff.</td></tr>';
      return;
    }
    if (!r.ok) throw new Error(`API ${r.status}`);
    const data = await r.json();
    const users = data.users || [];
    if (!users.length) {
      body.innerHTML = '<tr><td colspan="6" class="admin-empty">Noch keine Benutzer.</td></tr>';
      return;
    }
    body.innerHTML = users.map(renderRow).join("");
    body.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => handleAction(btn.dataset.action, btn.dataset.userId, users));
    });
  } catch (err) {
    body.innerHTML = `<tr><td colspan="6" class="admin-empty">Fehler: ${escapeHtml(err?.message || "Unbekannt")}</td></tr>`;
  }
};

const renderRow = (user) => {
  const isMe = currentMe && user.id === currentMe.id;
  const rolePill = user.is_admin
    ? '<span class="admin-pill admin-pill-admin">Admin</span>'
    : '<span class="admin-pill admin-pill-active">Benutzer</span>';
  const statusPill = user.is_active
    ? '<span class="admin-pill admin-pill-active">Aktiv</span>'
    : '<span class="admin-pill admin-pill-inactive">Deaktiviert</span>';
  const youBadge = isMe ? ' <span class="admin-pill admin-pill-active" style="margin-left:0.4rem;">Du</span>' : "";
  return `
    <tr>
      <td>${escapeHtml(user.name)}${youBadge}</td>
      <td>${escapeHtml(user.email)}</td>
      <td>${rolePill}</td>
      <td>${statusPill}</td>
      <td>${escapeHtml(formatDate(user.last_login_at))}</td>
      <td class="admin-action-cell" style="text-align:right;">
        <button class="ghost" type="button" data-action="toggle-admin" data-user-id="${escapeHtml(user.id)}" ${isMe && user.is_admin ? "disabled" : ""}>
          ${user.is_admin ? "Admin entziehen" : "Zum Admin machen"}
        </button>
        <button class="ghost" type="button" data-action="toggle-active" data-user-id="${escapeHtml(user.id)}" ${isMe ? "disabled" : ""}>
          ${user.is_active ? "Deaktivieren" : "Reaktivieren"}
        </button>
        <button class="ghost" type="button" data-action="reset-pw" data-user-id="${escapeHtml(user.id)}">Passwort setzen</button>
        <button class="ghost" type="button" data-action="delete" data-user-id="${escapeHtml(user.id)}" ${isMe ? "disabled" : ""} style="color:#fecaca;">Löschen</button>
      </td>
    </tr>`;
};

// ---------- Actions ----------

const patchUser = async (userId, payload) => {
  const r = await fetch(`${ADMIN_USERS}/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(payload),
  });
  if (r.status === 401) { redirectLogin(); return null; }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body?.detail || `API ${r.status}`);
  }
  return r.json();
};

const handleAction = async (action, userId, users) => {
  const target = users.find((u) => u.id === userId);
  if (!target) return;

  if (action === "toggle-admin") {
    try {
      await patchUser(userId, { is_admin: !target.is_admin });
      toast(target.is_admin ? "Admin-Rechte entzogen." : "Admin-Rechte vergeben.", "success");
      void loadUsers();
    } catch (err) {
      toast(err?.message || "Fehlgeschlagen.", "error");
    }
    return;
  }

  if (action === "toggle-active") {
    try {
      await patchUser(userId, { is_active: !target.is_active });
      toast(target.is_active ? "Account deaktiviert." : "Account reaktiviert.", "success");
      void loadUsers();
    } catch (err) {
      toast(err?.message || "Fehlgeschlagen.", "error");
    }
    return;
  }

  if (action === "reset-pw") {
    const values = await confirmDialog({
      title: "Passwort setzen",
      message: `Neues Passwort für ${target.name} (${target.email}). Alle Sitzungen des Users werden beendet.`,
      okLabel: "Setzen",
      fields: [{ name: "password", label: "Neues Passwort", type: "password", minLength: 8, required: true, autocomplete: "new-password" }],
    });
    if (!values) return;
    try {
      const r = await fetch(`${ADMIN_USERS}/${encodeURIComponent(userId)}/reset-password`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ new_password: values.password }),
      });
      if (r.status === 401) return redirectLogin();
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail || `API ${r.status}`);
      }
      toast("Passwort gesetzt. Der Benutzer muss sich neu anmelden.", "success");
    } catch (err) {
      toast(err?.message || "Fehlgeschlagen.", "error");
    }
    return;
  }

  if (action === "delete") {
    const values = await confirmDialog({
      title: "Benutzer löschen",
      message: `Soll der Account von ${target.name} (${target.email}) endgültig gelöscht werden? Diese Aktion ist nicht reversibel.`,
      okLabel: "Endgültig löschen",
      okDanger: true,
      fields: [{ name: "confirm", label: 'Tippe LOESCHEN zum Bestätigen', placeholder: "LOESCHEN", required: true }],
    });
    if (!values) return;
    if ((values.confirm || "").trim().toUpperCase() !== "LOESCHEN") {
      toast("Abgebrochen – falsche Eingabe.", "error");
      return;
    }
    try {
      const r = await fetch(`${ADMIN_USERS}/${encodeURIComponent(userId)}`, {
        method: "DELETE",
        headers: headers(),
      });
      if (r.status === 401) return redirectLogin();
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body?.detail || `API ${r.status}`);
      }
      toast("Benutzer gelöscht.", "success");
      void loadUsers();
    } catch (err) {
      toast(err?.message || "Fehlgeschlagen.", "error");
    }
    return;
  }
};

// ---------- New user ----------

document.getElementById("newUserBtn")?.addEventListener("click", async () => {
  const values = await confirmDialog({
    title: "Neuen Benutzer anlegen",
    message: "Der Benutzer kann sich danach mit der angegebenen E-Mail und dem Passwort anmelden.",
    okLabel: "Anlegen",
    fields: [
      { name: "name", label: "Name", required: true, autocomplete: "name" },
      { name: "email", label: "E-Mail", type: "email", required: true, autocomplete: "email" },
      { name: "password", label: "Initiales Passwort (mind. 8 Zeichen)", type: "password", minLength: 8, required: true, autocomplete: "new-password" },
    ],
  });
  if (!values) return;
  try {
    const r = await fetch(ADMIN_USERS, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({
        name: values.name,
        email: values.email,
        password: values.password,
        is_admin: false,
      }),
    });
    if (r.status === 401) return redirectLogin();
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body?.detail || `API ${r.status}`);
    }
    toast("Benutzer angelegt.", "success");
    void loadUsers();
  } catch (err) {
    toast(err?.message || "Anlegen fehlgeschlagen.", "error");
  }
});

(async () => {
  const ok = await ensureAdmin();
  if (ok) void loadUsers();
})();
