// Aurora Minutes – Release-Popup
// Holt /api/release/current, zeigt einmalig pro Version ein Modal mit Confetti.

(function () {
  "use strict";

  const STORAGE_KEY = "aurora-last-seen-release-v1";
  const ICON_MAP = {
    sparkles: "&#10024;",
    rocket: "&#128640;",
    bug: "&#128030;",
    wrench: "&#128295;",
    zap: "&#9889;",
    lock: "&#128274;",
    party: "&#127881;",
    star: "&#11088;",
    gear: "&#9881;&#65039;",
    chart: "&#128202;",
    shield: "&#128737;&#65039;",
    speech: "&#128172;",
    mic: "&#127908;",
    cloud: "&#9729;&#65039;",
    docs: "&#128221;",
    fire: "&#128293;",
  };

  function resolveApiBase() {
    const config = window.__APP_CONFIG__ || {};
    if (config.API_BASE_URL === "same-origin") {
      return window.location.origin;
    }
    if (config.API_BASE_URL) {
      return config.API_BASE_URL.replace(/\/$/, "");
    }
    const port = config.API_PORT || "";
    const portSegment = port ? `:${port}` : "";
    return `${window.location.protocol}//${window.location.hostname}${portSegment}`;
  }

  function resolveIcon(value) {
    if (!value) return "&#10024;";
    if (Object.prototype.hasOwnProperty.call(ICON_MAP, value)) {
      return ICON_MAP[value];
    }
    return value;
  }

  function fireConfetti(durationMs) {
    const totalDuration = typeof durationMs === "number" ? durationMs : 2200;
    const canvas = document.createElement("canvas");
    canvas.className = "release-confetti-canvas";
    canvas.style.position = "fixed";
    canvas.style.inset = "0";
    canvas.style.width = "100vw";
    canvas.style.height = "100vh";
    canvas.style.pointerEvents = "none";
    canvas.style.zIndex = "10001";
    document.body.appendChild(canvas);

    const dpr = window.devicePixelRatio || 1;
    const resize = () => {
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
    };
    resize();
    window.addEventListener("resize", resize);

    const ctx = canvas.getContext("2d");
    const colors = [
      "#ff5e5b",
      "#ffd166",
      "#06d6a0",
      "#118ab2",
      "#f72585",
      "#7209b7",
      "#4cc9f0",
      "#ffba08",
    ];
    const particles = [];

    function spawnBurst(originX, originY, count) {
      for (let i = 0; i < count; i += 1) {
        const angle = Math.random() * Math.PI * 2;
        const speed = (Math.random() * 8 + 4) * dpr;
        particles.push({
          x: originX,
          y: originY,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed - 4 * dpr,
          size: (Math.random() * 6 + 4) * dpr,
          color: colors[Math.floor(Math.random() * colors.length)],
          rotation: Math.random() * Math.PI,
          rotationSpeed: (Math.random() - 0.5) * 0.3,
          life: 1,
          shape: Math.random() < 0.5 ? "rect" : "circle",
        });
      }
    }

    // Erste Kanonen: links und rechts unten
    spawnBurst(canvas.width * 0.15, canvas.height * 0.85, 80);
    spawnBurst(canvas.width * 0.85, canvas.height * 0.85, 80);

    const startedAt = performance.now();
    let extraBursts = 0;

    function step(now) {
      const elapsed = now - startedAt;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Nachfeuern alle 600ms bis zur Hälfte der Dauer
      if (elapsed > extraBursts * 600 && elapsed < totalDuration * 0.6) {
        spawnBurst(canvas.width * 0.5, canvas.height * 0.4, 40);
        extraBursts += 1;
      }

      const gravity = 0.25 * dpr;
      for (let i = particles.length - 1; i >= 0; i -= 1) {
        const p = particles[i];
        p.vy += gravity;
        p.vx *= 0.99;
        p.x += p.vx;
        p.y += p.vy;
        p.rotation += p.rotationSpeed;
        p.life -= 0.005;
        if (p.life <= 0 || p.y > canvas.height + 50) {
          particles.splice(i, 1);
          continue;
        }
        ctx.save();
        ctx.globalAlpha = Math.max(0, Math.min(1, p.life));
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rotation);
        ctx.fillStyle = p.color;
        if (p.shape === "rect") {
          ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
        } else {
          ctx.beginPath();
          ctx.arc(0, 0, p.size / 2, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }

      if (elapsed < totalDuration || particles.length > 0) {
        requestAnimationFrame(step);
      } else {
        window.removeEventListener("resize", resize);
        canvas.remove();
      }
    }
    requestAnimationFrame(step);
  }

  function readLastSeen() {
    try {
      return localStorage.getItem(STORAGE_KEY) || "";
    } catch (err) {
      return "";
    }
  }

  function writeLastSeen(version) {
    try {
      localStorage.setItem(STORAGE_KEY, version);
    } catch (err) {
      /* localStorage kann disabled sein – Popup taucht dann erneut auf, OK */
    }
  }

  function buildHighlight(entry) {
    const li = document.createElement("li");
    li.className = "release-popup-item";
    const icon = document.createElement("span");
    icon.className = "release-popup-icon";
    icon.innerHTML = resolveIcon(entry.icon);
    const text = document.createElement("span");
    text.className = "release-popup-text";
    text.textContent = String(entry.text || "");
    li.appendChild(icon);
    li.appendChild(text);
    return li;
  }

  function renderModal(release) {
    const overlay = document.createElement("div");
    overlay.className = "release-popup-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "releasePopupTitle");

    const card = document.createElement("div");
    card.className = "release-popup-card";

    const badge = document.createElement("p");
    badge.className = "release-popup-badge";
    badge.textContent = "Neue Version " + (release.version || "");

    const title = document.createElement("h2");
    title.id = "releasePopupTitle";
    title.className = "release-popup-title";
    title.textContent = release.title || "Update verfügbar";

    if (release.subtitle) {
      const subtitle = document.createElement("p");
      subtitle.className = "release-popup-subtitle";
      subtitle.textContent = release.subtitle;
      card.appendChild(badge);
      card.appendChild(title);
      card.appendChild(subtitle);
    } else {
      card.appendChild(badge);
      card.appendChild(title);
    }

    const highlights = Array.isArray(release.highlights) ? release.highlights : [];
    if (highlights.length > 0) {
      const list = document.createElement("ul");
      list.className = "release-popup-list";
      highlights.forEach((entry) => list.appendChild(buildHighlight(entry)));
      card.appendChild(list);
    }

    const footer = document.createElement("div");
    footer.className = "release-popup-footer";
    if (release.date) {
      const date = document.createElement("span");
      date.className = "release-popup-date";
      date.textContent = "Veröffentlicht: " + release.date;
      footer.appendChild(date);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "release-popup-confirm primary";
    button.textContent = "Verstanden";
    footer.appendChild(button);
    card.appendChild(footer);

    overlay.appendChild(card);
    document.body.appendChild(overlay);

    const close = () => {
      writeLastSeen(release.version || "");
      overlay.classList.add("release-popup-closing");
      setTimeout(() => overlay.remove(), 200);
      document.removeEventListener("keydown", onKey);
    };
    const onKey = (event) => {
      if (event.key === "Escape" || event.key === "Enter") {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener("keydown", onKey);
    button.addEventListener("click", close);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close();
    });

    requestAnimationFrame(() => {
      overlay.classList.add("release-popup-visible");
      fireConfetti();
      button.focus();
    });
  }

  async function loadRelease() {
    const base = resolveApiBase();
    const response = await fetch(base.replace(/\/$/, "") + "/api/release/current", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error("Release-Endpoint antwortet mit " + response.status);
    }
    return response.json();
  }

  async function showIfNew() {
    try {
      const release = await loadRelease();
      if (!release || !release.version) return;
      if (release.version === "0.0.0-dev") return; // Lokale Dev-Defaults nicht anzeigen
      if (readLastSeen() === release.version) return;
      renderModal(release);
    } catch (err) {
      // Stillschweigend, damit Auth-/Backend-Probleme nicht das Frontend brechen
      if (window.console && console.debug) {
        console.debug("[release-popup] skip:", err);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", showIfNew);
  } else {
    showIfNew();
  }

  window.__releasePopup = { showIfNew, fireConfetti };
})();
