const resolveApiBase = () => {
  if (typeof window === "undefined") {
    return null;
  }
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

const API_BASE =
  resolveApiBase() || import.meta?.env?.VITE_API_URL || "http://localhost:8000";
const LAB_STORAGE_KEY = "minutesLabRows";
const escapeHtml = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const labTableBody = document.getElementById("labTableBody");
const labMinutesContainer = document.getElementById("labMinutes");
const labAddRowBtn = document.getElementById("labAddRow");
const labRunBtn = document.getElementById("labRun");

const loadLabRows = () => {
  try {
    const stored = localStorage.getItem(LAB_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed) && parsed.length) {
        return parsed.map((row, index) => ({
          speaker: row.speaker || `Zeile ${index + 1}`,
          text: row.text || "",
          prediction: row.prediction || null,
          rationale: row.rationale || null,
        }));
      }
    }
  } catch (error) {
    console.warn("Minutes Lab: Konnte gespeicherte Daten nicht laden", error);
  }
  return [
    { speaker: "Zeile 1", text: "Willkommen zur Sitzung.", prediction: null },
    {
      speaker: "Zeile 2",
      text: "Wir beschließen die Roadmap anzupassen.",
      prediction: null,
    },
  ];
};

let labRows = loadLabRows();

const persistLabRows = () => {
  try {
    localStorage.setItem(
      LAB_STORAGE_KEY,
      JSON.stringify(
        labRows.map((row) => ({
          speaker: row.speaker,
          text: row.text,
          prediction: row.prediction,
          rationale: row.rationale,
        }))
      )
    );
  } catch (error) {
    console.warn("Minutes Lab: Konnte Daten nicht speichern", error);
  }
};

const renderLabTable = () => {
  if (!labTableBody) return;
  labTableBody.innerHTML = "";
  labRows.forEach((row, index) => {
    if (!row.speaker) {
      row.speaker = `Zeile ${index + 1}`;
    }
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${index + 1}</td>
      <td>
        <textarea data-row="${index}" data-type="text">${escapeHtml(row.text || "")}</textarea>
        <button class="lab-remove" data-row="${index}">Entfernen</button>
      </td>
      <td>
        <div class="lab-prediction">${escapeHtml(row.prediction || "–")}</div>
        ${row.rationale ? `<p class="hint">${escapeHtml(row.rationale)}</p>` : ""}
      </td>
    `;
    labTableBody.appendChild(tr);
  });

  labTableBody.querySelectorAll("textarea").forEach((element) => {
    element.addEventListener("input", (event) => {
      const target = event.target;
      const rowIndex = Number(target.dataset.row);
      if (Number.isNaN(rowIndex)) return;
      labRows[rowIndex].text = target.value;
      labRows[rowIndex].speaker = labRows[rowIndex].speaker || `Zeile ${rowIndex + 1}`;
      labRows[rowIndex].prediction = null;
      labRows[rowIndex].rationale = null;
      persistLabRows();
    });
  });

  labTableBody.querySelectorAll(".lab-remove").forEach((button) => {
    button.addEventListener("click", (event) => {
      const target = event.target;
      const rowIndex = Number(target.dataset.row);
      if (!Number.isNaN(rowIndex)) {
        labRows.splice(rowIndex, 1);
        if (!labRows.length) {
          labRows.push({ speaker: "Zeile 1", text: "", prediction: null });
        }
        persistLabRows();
        renderLabTable();
      }
    });
  });
};

const renderLabMinutes = (minutes) => {
  if (!labMinutesContainer) return;
  if (!minutes) {
    labMinutesContainer.innerHTML = '<p class="hint">Noch keine Testdaten verarbeitet.</p>';
    return;
  }
  labMinutesContainer.innerHTML = `
    <p class="eyebrow">Lab Minutes</p>
    <p>${escapeHtml(minutes.summary || "Keine Zusammenfassung")}</p>
    <div class="minutes-grid">
      <div class="minutes-section">
        <h3>Agenda</h3>
        ${minutes.agenda?.length ? `<ul>${minutes.agenda.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : '<p class="hint">Keine Agenda</p>'}
      </div>
      <div class="minutes-section">
        <h3>Entscheidungen</h3>
        ${minutes.decisions?.length ? `<ul>${minutes.decisions.map((item) => `<li>${escapeHtml(item.title)}: ${escapeHtml(item.details)}</li>`).join("")}</ul>` : '<p class="hint">Keine Entscheidungen</p>'}
      </div>
    </div>
  `;
};

const runLabEvaluation = async () => {
  if (!labRows.length) return;
  const filledRows = labRows.filter((row) => row.text && row.text.trim().length > 0);
  if (!filledRows.length) {
    alert("Bitte gib mindestens eine Zeile mit Text ein.");
    return;
  }
  try {
    labRunBtn.disabled = true;
    labRunBtn.textContent = "Analysiere …";
    const response = await fetch(`${API_BASE}/api/minutes/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        segments: labRows.map((row, index) => ({
          speaker: row.speaker || `Zeile ${index + 1}`,
          text: row.text,
        })),
      }),
    });
    if (!response.ok) {
      throw new Error(`API Fehler ${response.status}`);
    }
    const payload = await response.json();
    const predictions = payload.predictions || [];
    predictions.forEach((prediction) => {
      const idx = prediction.row_index - 1;
      if (labRows[idx]) {
        labRows[idx].prediction = prediction.label;
        labRows[idx].rationale = prediction.rationale;
      }
    });
    persistLabRows();
    renderLabTable();
    renderLabMinutes(payload.minutes);
  } catch (error) {
    console.error(error);
    alert("Analyse fehlgeschlagen. Bitte erneut versuchen.");
  } finally {
    labRunBtn.disabled = false;
    labRunBtn.textContent = "Vorhersage testen";
  }
};

labAddRowBtn?.addEventListener("click", () => {
  labRows.push({ speaker: `Zeile ${labRows.length + 1}`, text: "", prediction: null });
  persistLabRows();
  renderLabTable();
});

labRunBtn?.addEventListener("click", async () => {
  await runLabEvaluation();
});

renderLabTable();
renderLabMinutes();
