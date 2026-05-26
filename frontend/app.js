const statusText = document.getElementById("statusText");
const timer = document.getElementById("timer");
const recordBtn = document.getElementById("recordBtn");
const stopBtn = document.getElementById("stopBtn");
const transcriptContainer = document.getElementById("transcript");
const transcriptSpeakerControls = document.getElementById("transcriptSpeakerControls");
const transcriptSpeakerHint = document.getElementById("transcriptSpeakerHint");
const transcriptSpeakerToggle = document.getElementById("transcriptSpeakerToggle");
const speakerPanel = document.getElementById("speakerPanel");
const speakerEditor = document.getElementById("speakerEditor");
const minutesContainer = document.getElementById("minutes");
const audioCard = document.getElementById("audioCard");
const audioPlayer = document.getElementById("audioPlayer");
const progressLabel = document.getElementById("progressLabel");
const progressRuntime = document.getElementById("progressRuntime");
const asyncJobStatus = document.getElementById("asyncJobStatus");
const progressFill = document.getElementById("progressFill");
const workflowStepsList = document.getElementById("workflowSteps");
const fileInput = document.getElementById("fileInput");
const editMinutesBtn = document.getElementById("editMinutesBtn");
const downloadBtn = document.getElementById("downloadBtn");
const sendBtn = document.getElementById("sendBtn");
const roomModal = document.getElementById("roomModal");
const roomModalClose = document.getElementById("roomModalClose");
const roomModalCancel = document.getElementById("roomModalCancel");
const confirmSendBtn = document.getElementById("confirmSendBtn");
const notifyActionItemsToggle = document.getElementById("notifyActionItemsToggle");
const actionItemNotifyDetails = document.getElementById("actionItemNotifyDetails");
const actionItemNotifyList = document.getElementById("actionItemNotifyList");
const actionItemDraftModal = document.getElementById("actionItemDraftModal");
const actionItemDraftClose = document.getElementById("actionItemDraftClose");
const actionItemDraftMeta = document.getElementById("actionItemDraftMeta");
const actionItemDraftText = document.getElementById("actionItemDraftText");
const actionItemDraftCancel = document.getElementById("actionItemDraftCancel");
const actionItemDraftSave = document.getElementById("actionItemDraftSave");
const confirmSendDefaultLabel = confirmSendBtn?.textContent?.trim() || "Jetzt senden";
const toast = document.getElementById("toast");
const apiStatusBadge = document.getElementById("apiStatusBadge");
const meetingList = document.getElementById("meetingList");
const refreshMeetingsBtn = document.getElementById("refreshMeetingsBtn");
const selectedMeetingTitle = document.getElementById("selectedMeetingTitle");
const selectedMeetingMeta = document.getElementById("selectedMeetingMeta");
const cancelMeetingBtn = document.getElementById("cancelMeetingBtn");
const deleteMeetingBtn = document.getElementById("deleteMeetingBtn");
const logoutBtn = document.getElementById("logoutBtn");
const profileMenu = document.getElementById("profileMenu");
const profileMenuTrigger = document.getElementById("profileMenuTrigger");
const profileDropdown = document.getElementById("profileDropdown");
const profileName = document.getElementById("profileName");
const profileEmail = document.getElementById("profileEmail");
const profileInitials = document.getElementById("profileInitials");
const openTaskBoardBtn = document.getElementById("openTaskBoardBtn");
const taskBoardPanel = document.getElementById("taskBoardPanel");
const taskBoardSummary = document.getElementById("taskBoardSummary");
const taskBoardEntries = document.getElementById("taskBoardEntries");
const taskBoardInsights = document.getElementById("taskBoardInsights");


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
const HEALTH_ENDPOINT = `${API_BASE}/health`;
const MEETING_FORWARD_ENDPOINT = `${API_BASE}/api/meetings/forward`;
const TASK_BOARD_ENDPOINT = `${API_BASE}/api/tasks/board`;
const TASK_BOARD_FEATURE_ENABLED = false;
const MODEL_SETTINGS_ENDPOINT = `${API_BASE}/api/settings/models`;
const AUTH_ME_ENDPOINT = `${API_BASE}/api/auth/me`;
const AUTH_LOGOUT_ENDPOINT = `${API_BASE}/api/auth/logout`;

const WORKFLOW_STEPS = [
  {
    key: "transcribe",
    label: "Transkribieren",
  },
  {
    key: "diarize",
    label: "Optional: Sprecher erkennen",
  },
  {
    key: "minutes",
    label: "Minutes erstellen",
  },
];
const SELECTED_MEETING_KEY = "aurora-selected-meeting-id-v1";
const CLIENT_ID_STORAGE_KEY = "aurora-client-id-v1";
const AUTH_TOKEN_STORAGE_KEY = "aurora-auth-token-v1";
const getEffectiveTheme = () =>
  document.documentElement?.dataset?.theme ||
  localStorage.getItem("app-theme") ||
  (window.__APP_CONFIG__ || {}).UI_THEME ||
  "aurora";
const getAppName = () => (getEffectiveTheme() === "meetingai" ? "Meeting AI" : "Aurora");
const CLIENT_ID_HEADER = "X-Client-Id";

const SPEAKER_SAMPLE_MIN_DURATION = 2.5; // Sekunden
const SPEAKER_SAMPLE_MAX_DURATION = 6; // Sekunden
const SPEAKER_SAMPLE_PREROLL = 0.4; // Sekunden vor Segmentstart
const OWNER_SPLIT_PATTERN = /\s*(?:,|;|\/|&|\bund\b|\band\b|\+)\s*/i;
const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
const RECORD_BUTTON_LABELS = Object.freeze({
  idle: "Aufnahme starten",
  recording: "Aufnahme stoppen",
  busy: "Wird verarbeitet ...",
});

let mediaRecorder;
let activeRecordingStream = null;
let recordedChunks = [];
let timerInterval;
let startTime;
let recordingStartedAtUtc = null;
let transcriptCache = [];
let minutesCache = null;
let draftMinutesCache = null;
let minutesEditMode = false;
let durationCache = 0;
let speakersCache = [];
let audioUrl;
let currentAudioBlob = null;
let currentAudioFilename = "recording.webm";
let currentSessionId = null;
let currentJobId = null;
let currentMeetingName = "";
let transcriptHasSpeakerDetection = false;
let speakerDetectionEnabled = transcriptSpeakerToggle ? transcriptSpeakerToggle.checked : true;
// Globaler Schalter aus den Backend-Einstellungen. Wenn false, darf das UI
// keinerlei Sprecherinformationen anzeigen und keine Diarisierung anfordern.
let globalSpeakerRecognitionEnabled = true;
// Globaler Schalter: Senden-Funktion aktiv? Wird aus den Backend-Einstellungen geladen.
let globalSendEnabled = true;
let reprocessInFlight = false;
let activeSampleSpeakerId = null;
let speakerSampleTimeoutId = null;
let workflowState = {
  activeKey: null,
  completed: false,
  actualStepDurationsMs: {},
  device: null,
  progressRatio: 0,
  startedAt: null,
  tickerId: null,
};
let toastTimeoutId = null;
let asyncJobPollTimeoutId = null;
let meetingsCache = [];
let authToken = "";
let currentUser = null;
let profileMenuOpen = false;
let actionItemNotificationEntries = [];
let activeActionItemDraftIndex = null;
let taskBoardCache = null;
let taskBoardAutoRefreshIntervalId = null;

const generateClientId = () => {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `aurora-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const getClientId = () => {
  const stored = window.localStorage.getItem(CLIENT_ID_STORAGE_KEY);
  if (stored) {
    return stored;
  }
  const generated = generateClientId();
  window.localStorage.setItem(CLIENT_ID_STORAGE_KEY, generated);
  return generated;
};

const withClientScope = (init = {}) => {
  const headers = new Headers(init.headers || {});
  headers.set(CLIENT_ID_HEADER, currentUser?.id || getClientId());
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }
  return {
    ...init,
    headers,
  };
};

const isAuthenticated = () => Boolean(authToken && currentUser?.id);

const persistAuthToken = (token) => {
  if (!token) {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    return;
  }
  localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
};

const setAuthState = ({ token = "", user = null } = {}) => {
  authToken = token || "";
  currentUser = user || null;
  persistAuthToken(authToken);
  updateAuthUi();
};

const getStoredAuthToken = () => localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";

const buildUserInitials = (name, email) => {
  const source = String(name || "").trim() || String(email || "").trim();
  if (!source) {
    return "U";
  }
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
};

const setProfileMenuOpen = (open) => {
  profileMenuOpen = Boolean(open);
  if (profileDropdown) {
    profileDropdown.classList.toggle("hidden", !profileMenuOpen);
  }
  if (profileMenuTrigger) {
    profileMenuTrigger.setAttribute("aria-expanded", profileMenuOpen ? "true" : "false");
  }
};

const updateAuthUi = () => {
  const authenticated = isAuthenticated();
  if (profileMenu) {
    profileMenu.classList.toggle("hidden", !authenticated);
  }
  if (profileName) {
    profileName.textContent = authenticated ? currentUser.name : "Benutzer";
  }
  if (profileEmail) {
    profileEmail.textContent = authenticated ? currentUser.email : "-";
  }
  if (profileInitials) {
    profileInitials.textContent = authenticated
      ? buildUserInitials(currentUser.name, currentUser.email)
      : "U";
  }
  if (logoutBtn) {
    logoutBtn.disabled = !authenticated;
  }
  if (!authenticated) {
    setProfileMenuOpen(false);
  }
  if (!authenticated) {
    setSelectedMeetingHeaderV2(null);
    if (meetingList) {
      meetingList.innerHTML = '<p class="hint">Bitte anmelden, um Meetings zu sehen.</p>';
    }
  }
};

const requireAuthentication = () => {
  if (isAuthenticated()) {
    return true;
  }
  window.location.replace("login.html");
  return false;
};

const ensureAuthSession = async () => {
  const token = getStoredAuthToken();
  if (!token) {
    setAuthState({ token: "", user: null });
    return false;
  }
  authToken = token;
  try {
    const response = await fetch(AUTH_ME_ENDPOINT, withClientScope());
    if (!response.ok) {
      throw new Error("Sitzung abgelaufen.");
    }
    const user = await response.json();
    setAuthState({ token, user });
    return true;
  } catch (_error) {
    setAuthState({ token: "", user: null });
    return false;
  }
};

const stopActiveRecordingTracks = () => {
  const stream = activeRecordingStream || mediaRecorder?.stream || null;
  if (!stream) {
    return;
  }
  stream.getTracks().forEach((track) => {
    track.stop();
  });
  activeRecordingStream = null;
};

const setRecordButtonState = ({ recording = false, busy = false } = {}) => {
  if (!recordBtn) {
    return;
  }
  recordBtn.disabled = busy;
  recordBtn.classList.toggle("recording-active", recording);
  recordBtn.classList.toggle("recording-busy", busy);
  recordBtn.setAttribute("aria-pressed", recording ? "true" : "false");
  recordBtn.textContent = busy
    ? RECORD_BUTTON_LABELS.busy
    : recording
      ? RECORD_BUTTON_LABELS.recording
      : RECORD_BUTTON_LABELS.idle;

  if (stopBtn) {
    stopBtn.disabled = true;
    stopBtn.classList.add("hidden");
    stopBtn.setAttribute("aria-hidden", "true");
  }
};

const readErrorMessage = async (response, fallback) => {
  try {
    const payload = await response.json();
    return payload?.detail || fallback;
  } catch (_error) {
    return fallback;
  }
};

const setApiStatus = (message, variant = "neutral") => {
  if (!apiStatusBadge) {
    return;
  }
  const nextMessage = String(message || "").trim();
  const shouldHide = variant === "success" && !nextMessage;
  apiStatusBadge.classList.toggle("hidden", shouldHide);
  if (shouldHide) {
    return;
  }
  apiStatusBadge.textContent = nextMessage;
  apiStatusBadge.classList.remove("meeting-status-completed", "meeting-status-running", "meeting-status-failed");
  if (variant === "success") {
    apiStatusBadge.classList.add("meeting-status-completed");
  } else if (variant === "warning") {
    apiStatusBadge.classList.add("meeting-status-running");
  } else if (variant === "error") {
    apiStatusBadge.classList.add("meeting-status-failed");
  }
};

const formatTime = (durationMs) => {
  const totalSeconds = Math.floor(durationMs / 1000);
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
};

const clampMs = (value) => Math.max(0, Number.isFinite(value) ? value : 0);
const formatShortDuration = (durationMs) => {
  const totalSeconds = Math.floor(clampMs(durationMs) / 1000);
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
};

const startWorkflowTicker = () => {
  if (workflowState.tickerId) {
    clearInterval(workflowState.tickerId);
  }
  workflowState.tickerId = window.setInterval(() => {
    renderWorkflow();
  }, 1000);
};

const stopWorkflowTicker = () => {
  if (workflowState.tickerId) {
    clearInterval(workflowState.tickerId);
  }
  workflowState.tickerId = null;
};

const beginWorkflowTracking = () => {
  workflowState = {
    activeKey: "transcribe",
    completed: false,
    actualStepDurationsMs: {},
    device: null,
    progressRatio: 0.05,
    startedAt: Date.now(),
    tickerId: workflowState.tickerId,
  };
  startWorkflowTicker();
  renderWorkflow();
};

const completeWorkflowTracking = (processing) => {
  stopWorkflowTicker();
  const actualStepDurationsMs = Object.fromEntries(
    (processing?.steps || []).map((step) => [step.key, clampMs((step.duration_seconds || 0) * 1000)])
  );
  workflowState = {
    ...workflowState,
    activeKey: WORKFLOW_STEPS[WORKFLOW_STEPS.length - 1]?.key || null,
    completed: true,
    actualStepDurationsMs,
    device: processing?.device || null,
    progressRatio: 1,
    startedAt: workflowState.startedAt,
    tickerId: null,
  };
  renderWorkflow();
};

const loadBlobDurationSeconds = (blob) =>
  new Promise((resolve) => {
    if (typeof document === "undefined") {
      resolve(0);
      return;
    }
    const probe = document.createElement("audio");
    const probeUrl = URL.createObjectURL(blob);
    const cleanup = () => {
      probe.removeAttribute("src");
      URL.revokeObjectURL(probeUrl);
    };
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      const seconds = Number.isFinite(probe.duration) ? probe.duration : 0;
      cleanup();
      resolve(seconds);
    };
    probe.onerror = () => {
      cleanup();
      resolve(0);
    };
    probe.src = probeUrl;
  });

const getRecordingElapsedSeconds = () => {
  if (!startTime) {
    return 0;
  }
  return clampMs(Date.now() - startTime) / 1000;
};

const resolveInitialAudioDurationSeconds = async (blob) => {
  const probedDuration = await loadBlobDurationSeconds(blob);
  const recordingDuration = getRecordingElapsedSeconds();

  if (recordingDuration > 0) {
    if (!Number.isFinite(probedDuration) || probedDuration <= 0) {
      return recordingDuration;
    }
    const difference = Math.abs(probedDuration - recordingDuration);
    if (difference > Math.max(5, recordingDuration * 0.2)) {
      return recordingDuration;
    }
  }

  return Number.isFinite(probedDuration) && probedDuration > 0 ? probedDuration : 0;
};

const startTimer = () => {
  startTime = Date.now();
  timerInterval = setInterval(() => {
    timer.textContent = formatTime(Date.now() - startTime);
  }, 1000);
};

const stopTimer = () => {
  clearInterval(timerInterval);
};

const stopAsyncJobPolling = () => {
  if (asyncJobPollTimeoutId) {
    clearTimeout(asyncJobPollTimeoutId);
    asyncJobPollTimeoutId = null;
  }
};

const setAsyncJobStatus = (message = "", { hidden = false } = {}) => {
  if (!asyncJobStatus) {
    return;
  }
  asyncJobStatus.textContent = message;
  asyncJobStatus.classList.toggle("hidden", hidden || !message);
};

const syncWorkflowStateFromJob = (job) => {
  if (!job) {
    return;
  }
  const nextProgressRatio = Math.max(0, Math.min(Number(job.progress_percent || 0) / 100, 1));
  if (job.started_at && !workflowState.startedAt) {
    workflowState.startedAt = Math.round(Number(job.started_at) * 1000);
  }
  if (job.active_step) {
    workflowState.activeKey = job.active_step;
  }
  if (nextProgressRatio > 0) {
    workflowState.progressRatio = nextProgressRatio;
  }
  renderWorkflow();
};

const requestNotificationPermissionIfNeeded = async () => {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return "unsupported";
  }
  if (Notification.permission === "granted") {
    return "granted";
  }
  if (Notification.permission === "denied") {
    return "denied";
  }
  try {
    return await Notification.requestPermission();
  } catch (_error) {
    return "denied";
  }
};

const notifyProcessingFinished = async (title, body) => {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return;
  }
  const permission = await requestNotificationPermissionIfNeeded();
  if (permission !== "granted") {
    return;
  }
  try {
    new Notification(title, { body });
  } catch (_error) {
    // Ignore notification failures.
  }
};

const getMeetingStatusLabel = (status) => {
  if (status === "running") return "Läuft";
  if (status === "completed") return "Fertig";
  if (status === "failed") return "Fehlgeschlagen";
  if (status === "cancelled") return "Gestoppt";
  return "Eingereiht";
};

const formatMeetingTimestamp = (value) => {
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) {
    return "unbekannt";
  }
  return date.toLocaleString("de-DE");
};

const persistSelectedMeetingId = (meetingId) => {
  try {
    if (!meetingId) {
      localStorage.removeItem(SELECTED_MEETING_KEY);
    } else {
      localStorage.setItem(SELECTED_MEETING_KEY, meetingId);
    }
  } catch (_error) {
    // Ignore storage failures.
  }
};

const getPersistedSelectedMeetingId = () => {
  try {
    return localStorage.getItem(SELECTED_MEETING_KEY);
  } catch (_error) {
    return null;
  }
};


const setSelectedMeetingHeaderV2 = (meeting) => {
  if (!selectedMeetingTitle || !selectedMeetingMeta) {
    return;
  }
  if (!meeting) {
    selectedMeetingTitle.textContent = "Kein Meeting geladen";
    selectedMeetingMeta.textContent = "Starte eine Aufnahme oder lade eine Datei hoch.";
    if (cancelMeetingBtn) cancelMeetingBtn.disabled = true;
    if (deleteMeetingBtn) deleteMeetingBtn.disabled = true;
    return;
  }
  selectedMeetingTitle.textContent = meeting.meeting_name || "Unbenanntes Meeting";
  selectedMeetingMeta.textContent =
    `${getMeetingStatusLabel(meeting.status)} | Datei: ${meeting.audio_filename || "unbekannt"} | ` +
    `Erstellt: ${formatMeetingTimestamp(meeting.created_at)}`;
  if (cancelMeetingBtn) cancelMeetingBtn.disabled = !["queued", "running"].includes(meeting.status);
  if (deleteMeetingBtn) deleteMeetingBtn.disabled = meeting.status === "running";
};

const renderMeetingsListV2 = () => {
  if (!meetingList) {
    return;
  }
  if (!isAuthenticated()) {
    meetingList.innerHTML = '<p class="hint">Bitte anmelden, um Meetings zu sehen.</p>';
    setSelectedMeetingHeaderV2(null);
    return;
  }
  if (!meetingsCache.length) {
    meetingList.innerHTML = '<p class="hint">Noch kein Meeting gespeichert.</p>';
    setSelectedMeetingHeaderV2(null);
    return;
  }
  meetingList.innerHTML = `
    ${meetingsCache
      .map((meeting) => {
        const isActive = meeting.job_id && meeting.job_id === currentJobId;
        return `
          <article
            class="meeting-list-item ${isActive ? "meeting-list-item-active" : "meeting-list-item-single"}"
            data-meeting-id="${escapeHtml(meeting.job_id || "")}"
            tabindex="0"
            role="button"
            aria-pressed="${isActive ? "true" : "false"}"
          >
            <div class="meeting-list-item-header">
              <h3>${escapeHtml(meeting.meeting_name || "Unbenanntes Meeting")}</h3>
              <span class="meeting-status-badge meeting-status-${escapeHtml(meeting.status || "queued")}">
                ${escapeHtml(getMeetingStatusLabel(meeting.status))}
              </span>
            </div>
            <div class="meeting-list-meta">
              <span>${escapeHtml(meeting.audio_filename || "Keine Datei")}</span>
              <span>${escapeHtml(meeting.message || "")}</span>
              <span>${escapeHtml(formatMeetingTimestamp(meeting.created_at))}</span>
            </div>
          </article>
        `;
      })
      .join("")}
  `;
  const activeMeeting = meetingsCache.find((meeting) => meeting.job_id === currentJobId) || meetingsCache[0];
  setSelectedMeetingHeaderV2(activeMeeting);
};

const syncMeetingIntoCacheV2 = (job) => {
  if (!job?.job_id) {
    return;
  }
  const existingIndex = meetingsCache.findIndex((meeting) => meeting.job_id === job.job_id);
  if (existingIndex >= 0) {
    meetingsCache.splice(existingIndex, 1, { ...meetingsCache[existingIndex], ...job });
  } else {
    meetingsCache = [{ ...job }, ...meetingsCache];
  }
  meetingsCache = meetingsCache
    .slice()
    .sort((left, right) => Number(right.created_at || 0) - Number(left.created_at || 0));
  renderMeetingsListV2();
};

const applySelectedMeetingProgress = (meeting) => {
  if (!meeting) {
    setAsyncJobStatus("", { hidden: true });
    return;
  }
  if (meeting.status === "queued") {
    resetWorkflow();
    progressLabel.textContent = "Vorbereitet";
    progressFill.style.width = "0%";
    setAsyncJobStatus(meeting.message || "Meeting wird vorbereitet.");
    return;
  }
  if (meeting.status === "running") {
    if (!workflowState.activeKey || workflowState.completed) {
      beginWorkflowTracking();
    }
    syncWorkflowStateFromJob(meeting);
    setAsyncJobStatus(meeting.message || "Transkription läuft.");
    return;
  }
  if (meeting.status === "completed") {
    setAsyncJobStatus("Transkription abgeschlossen.", { hidden: false });
    return;
  }
  if (meeting.status === "cancelled") {
    resetWorkflow();
    progressLabel.textContent = "Gestoppt";
    progressFill.style.width = "0%";
    setAsyncJobStatus(meeting.message || "Job wurde gestoppt.");
    return;
  }
  if (meeting.status === "failed") {
    resetWorkflow();
    progressLabel.textContent = "Fehlgeschlagen";
    progressFill.style.width = "0%";
    setAsyncJobStatus(meeting.message || "Job ist fehlgeschlagen.");
  }
};

const selectMeeting = async (jobId, { loadFromServer = true } = {}) => {
  if (!jobId) {
    return;
  }
  currentJobId = jobId;
  persistSelectedMeetingId(jobId);
  const existing = meetingsCache.find((meeting) => meeting.job_id === jobId);
  if (existing) {
    currentMeetingName = existing.meeting_name || currentMeetingName;
    setSelectedMeetingHeaderV2(existing);
    applySelectedMeetingProgress(existing);
    renderMeetingsListV2();
  }
  if (!loadFromServer) {
    return;
  }
  try {
    const response = await fetch(`${API_BASE}/api/transcribe/jobs/${jobId}`, withClientScope());
    if (!response.ok) {
      throw new Error(`Meeting ${jobId} konnte nicht geladen werden.`);
    }
    const job = await response.json();
    syncMeetingIntoCacheV2(job);
    currentMeetingName = job.meeting_name || currentMeetingName;
    applySelectedMeetingProgress(job);
    if (job.result) {
      applyTranscriptPayload(job.result, {
        speakerDetection: Array.isArray(job.result.speakers) && job.result.speakers.length > 0,
        audioDurationSeconds: job.result.duration_seconds || 0,
        statusMessage: `Meeting geladen: ${job.meeting_name}`,
      });
    } else {
      currentSessionId = null;
      transcriptCache = [];
      minutesCache = null;
      draftMinutesCache = null;
      durationCache = 0;
      transcriptHasSpeakerDetection = false;
      renderTranscript();
      renderMinutes();
      renderSpeakerEditor();
      updateActionButtonsState();
      statusText.textContent = `Meeting ausgewählt: ${job.meeting_name}`;
    }
    if (job.status === "queued" || job.status === "running") {
      await pollAsyncTranscriptionJob(job.job_id, durationCache || 0);
    }
  } catch (error) {
    handleError(error?.message || "Meeting konnte nicht geladen werden.");
  }
};

const fetchMeetings = async ({ preserveSelection = false } = {}) => {
  if (!isAuthenticated()) {
    meetingsCache = [];
    renderMeetingsListV2();
    currentJobId = null;
    currentSessionId = null;
    persistSelectedMeetingId(null);
    setSelectedMeetingHeaderV2(null);
    return;
  }
  try {
    const response = await fetch(`${API_BASE}/api/transcribe/jobs`, withClientScope());
    if (!response.ok) {
      throw new Error(`Meetings konnten nicht geladen werden (${response.status}).`);
    }
    meetingsCache = await response.json();
    renderMeetingsListV2();
    const persistedMeetingId = preserveSelection ? getPersistedSelectedMeetingId() : null;
    const nextMeetingId =
      (persistedMeetingId && meetingsCache.some((meeting) => meeting.job_id === persistedMeetingId)
        ? persistedMeetingId
        : null) ||
      meetingsCache[0]?.job_id ||
      null;
    if (nextMeetingId) {
      await selectMeeting(nextMeetingId, { loadFromServer: true });
    } else {
      currentJobId = null;
      currentSessionId = null;
      persistSelectedMeetingId(null);
      setSelectedMeetingHeaderV2(null);
      setAsyncJobStatus("", { hidden: true });
      transcriptCache = [];
      minutesCache = null;
      draftMinutesCache = null;
      durationCache = 0;
      transcriptHasSpeakerDetection = false;
      renderTranscript();
      renderMinutes();
      renderSpeakerEditor();
      updateActionButtonsState();
    }
  } catch (error) {
    handleError(error?.message || "Meetings konnten nicht geladen werden.");
  }
};

const resetUI = ({ preserveAudio = false } = {}) => {
  statusText.textContent = "Bereit für Aufnahme";
  setRecordButtonState({ recording: false, busy: false });
  timer.textContent = "00:00:00";
  minutesEditMode = false;
  draftMinutesCache = null;
  resetWorkflow();
  stopAsyncJobPolling();
  stopSpeakerSamplePlayback();
  hideToast();
  setAsyncJobStatus("", { hidden: true });
  if (!preserveAudio) {
    currentAudioBlob = null;
    currentAudioFilename = "recording.webm";
    currentSessionId = null;
    transcriptHasSpeakerDetection = false;
    hideAudioPlayer();
  }
  updateSpeakerControlsState();
  syncActionItemNotifyUi();
};

const normalizeErrorMessage = (value, fallback = "Unbekannter Fehler") => {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (value && typeof value === "object") {
    if (typeof value.message === "string" && value.message.trim()) {
      return value.message.trim();
    }
    if (typeof value.detail === "string" && value.detail.trim()) {
      return value.detail.trim();
    }
  }
  return fallback;
};

const handleError = (message) => {
  const resolvedMessage = normalizeErrorMessage(message, "Ein unerwarteter Fehler ist aufgetreten.");
  statusText.textContent = resolvedMessage;
  statusText.classList.add("error");
  setTimeout(() => statusText.classList.remove("error"), 4000);
  setRecordButtonState({ recording: false, busy: false });
  stopTimer();
  stopActiveRecordingTracks();
  minutesEditMode = false;
  draftMinutesCache = null;
  resetWorkflow();
  stopAsyncJobPolling();
  stopSpeakerSamplePlayback();
  hideToast();
  setAsyncJobStatus(resolvedMessage, { hidden: false });
  updateSpeakerControlsState();
};

const resetUIV2 = ({ preserveAudio = false } = {}) => {
  if (statusText) {
    statusText.textContent = "Bereit für Aufnahme";
  }
  setRecordButtonState({ recording: false, busy: false });
  if (timer) {
    timer.textContent = "00:00:00";
  }
  minutesEditMode = false;
  draftMinutesCache = null;
  resetWorkflow();
  stopAsyncJobPolling();
  stopSpeakerSamplePlayback();
  hideToast();
  setAsyncJobStatus("", { hidden: true });
  if (!preserveAudio) {
    currentAudioBlob = null;
    currentAudioFilename = "recording.webm";
    currentSessionId = null;
    transcriptHasSpeakerDetection = false;
    hideAudioPlayer();
  }
  updateSpeakerControlsState();
};

const checkApiAvailability = async () => {
  try {
    const response = await fetch(HEALTH_ENDPOINT);
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, `API Fehler ${response.status}`));
    }
    const payload = await response.json();
    setApiStatus("", "success");
    return payload;
  } catch (_error) {
    setApiStatus("Backend nicht erreichbar", "error");
    return null;
  }
};

const loadGlobalSpeakerRecognitionSetting = async () => {
  try {
    const response = await fetch(MODEL_SETTINGS_ENDPOINT);
    if (!response.ok) {
      throw new Error(`API Fehler ${response.status}`);
    }
    const settings = await response.json();
    globalSpeakerRecognitionEnabled =
      settings?.speaker_recognition_enabled === undefined
        ? true
        : Boolean(settings.speaker_recognition_enabled);
    globalSendEnabled =
      settings?.send_enabled === undefined
        ? true
        : Boolean(settings.send_enabled);
  } catch (_error) {
    // Im Fehlerfall lassen wir den bisherigen Default (true) bestehen, damit
    // die UI zumindest in einem definierten Zustand bleibt.
  }
  // Senden-Button direkt initial verstecken/zeigen
  if (sendBtn) {
    sendBtn.classList.toggle("hidden", !globalSendEnabled);
  }
  if (!globalSpeakerRecognitionEnabled) {
    transcriptHasSpeakerDetection = false;
    speakersCache = [];
    if (transcriptSpeakerToggle) {
      transcriptSpeakerToggle.checked = false;
    }
    speakerDetectionEnabled = false;
  }
  updateSpeakerControlsState();
  renderTranscript(transcriptCache);
  renderSpeakerEditor();
  renderWorkflow();
};

function buildFallbackMinutes(payload) {
  const summaryText = payload?.summary || "";
  const transcriptText = transcriptCache.map((segment) => segment.text).join(" ");
  const highlights = summaryText
    ? summaryText.split(/\.\s+/).slice(0, 3).filter(Boolean)
    : transcriptText.split(/\.\s+/).slice(0, 3).filter(Boolean);
  return {
    summary: summaryText || highlights.join(". ") || "Zusammenfassung folgt ...",
    agenda: highlights.slice(0, 2),
    highlights,
    decisions: [],
    action_items: [],
    risks: [],
    model: "fallback",
    chunk_count: 0,
  };
}

const buildSpeakersFromTranscript = (segments = []) => {
  const map = new Map();
  segments.forEach((segment) => {
    if (!segment) {
      return;
    }
    const identifier = segment.speaker_id || segment.speaker || `speaker_${map.size + 1}`;
    if (map.has(identifier)) {
      return;
    }
    const baseLabel = segment.speaker || `Speaker ${map.size + 1}`;
    map.set(identifier, {
      speaker_id: identifier,
      label: baseLabel,
      default_label: baseLabel,
    });
  });
  return Array.from(map.values());
};

const normalizeSpeakersList = (rawSpeakers, segments) => {
  if (Array.isArray(rawSpeakers) && rawSpeakers.length) {
    return rawSpeakers.map((speaker, index) => {
      const fallbackId = speaker?.speaker_id || `speaker_${index + 1}`;
      const fallbackLabel = speaker?.label || `Speaker ${index + 1}`;
      return {
        speaker_id: fallbackId,
        label: fallbackLabel,
        default_label: fallbackLabel,
      };
    });
  }
  return buildSpeakersFromTranscript(segments);
};

const escapeRegExp = (value) => value.replace(/[\\^$.*+?()[\]{}|]/g, "\\$&");
const escapeHtml = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const deepClone = (value) => JSON.parse(JSON.stringify(value));

const ensureStringList = (value) =>
  Array.isArray(value) ? value.map((entry) => String(entry ?? "").trim()).filter(Boolean) : [];

const extractStructuredMinutesFromSummary = (value) => {
  const raw = String(value ?? "").trim();
  if (!raw || (!raw.includes("{") && !raw.includes("```"))) {
    return null;
  }

  let candidate = raw;
  if (candidate.includes("```")) {
    candidate = candidate.replace(/```json/gi, "").replace(/```/g, "").trim();
  }

  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start < 0 || end <= start) {
    return null;
  }

  try {
    const parsed = JSON.parse(candidate.slice(start, end + 1));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }

    const decisions = Array.isArray(parsed.decisions)
      ? parsed.decisions
          .map((decision) => {
            if (decision && typeof decision === "object") {
              return {
                title: String(decision.title ?? "").trim(),
                details: String(decision.details ?? "").trim(),
              };
            }
            const text = String(decision ?? "").trim();
            return text ? { title: text, details: "" } : null;
          })
          .filter(Boolean)
      : [];

    const rawActions = Array.isArray(parsed.action_items)
      ? parsed.action_items
      : Array.isArray(parsed.next_steps)
        ? parsed.next_steps
        : [];
    const actionItems = rawActions
      .map((action) => {
        if (action && typeof action === "object") {
          return {
            owner: String(action.owner ?? "Offen").trim() || "Offen",
            description: String(action.description ?? "").trim(),
            due_date: String(action.due_date ?? "").trim() || null,
          };
        }
        const text = String(action ?? "").trim();
        return text ? { owner: "Offen", description: text, due_date: null } : null;
      })
      .filter(Boolean);

    const summary = String(parsed.summary ?? "").trim();
    if (
      !summary &&
      !ensureStringList(parsed.agenda).length &&
      !ensureStringList(parsed.highlights).length &&
      !decisions.length &&
      !actionItems.length &&
      !ensureStringList(parsed.risks).length
    ) {
      return null;
    }

    return {
      summary,
      agenda: ensureStringList(parsed.agenda),
      highlights: ensureStringList(parsed.highlights),
      decisions,
      action_items: actionItems,
      risks: ensureStringList(parsed.risks),
    };
  } catch (_error) {
    return null;
  }
};

const buildMinutesSections = (minutes) => {
  const decisions = (minutes.decisions || []).map((decision) => {
    const title = (decision?.title || "Entscheidung").trim();
    const details = (decision?.details || "").trim();
    return details ? `${title}: ${details}` : title;
  });
  const actionItems = (minutes.action_items || []).map((action) => {
    const owner = (action?.owner || "Unbekannt").trim();
    const description = (action?.description || "Aufgabe offen").trim();
    const due = action?.due_date ? ` (fällig: ${String(action.due_date).trim()})` : "";
    return `${owner}: ${description}${due}`;
  });
  return [
    {
      title: "Kurzzusammenfassung",
      entries: minutes.summary ? [minutes.summary] : ["Keine Kurzzusammenfassung vorhanden."],
    },
    {
      title: "Agenda",
      entries: minutes.agenda.length ? minutes.agenda : ["Keine Agenda erkannt."],
    },
    {
      title: "Highlights",
      entries: minutes.highlights.length ? minutes.highlights : ["Keine Highlights vorhanden."],
    },
    {
      title: "Entscheidungen",
      entries: decisions.length ? decisions : ["Keine Entscheidungen dokumentiert."],
    },
    {
      title: "Action Items",
      entries: actionItems.length ? actionItems : ["Keine Action Items erfasst."],
    },
    {
      title: "Risiken & offene Punkte",
      entries: minutes.risks.length ? minutes.risks : ["Keine Risiken oder offenen Punkte dokumentiert."],
    },
  ];
};

const normalizeMinutes = (minutes) => {
  const normalized = {
    summary: String(minutes?.summary ?? "").trim(),
    agenda: ensureStringList(minutes?.agenda),
    highlights: ensureStringList(minutes?.highlights),
    decisions: Array.isArray(minutes?.decisions)
      ? minutes.decisions
          .map((decision) => ({
            title: String(decision?.title ?? "").trim(),
            details: String(decision?.details ?? "").trim(),
          }))
          .filter((decision) => decision.title || decision.details)
      : [],
    action_items: Array.isArray(minutes?.action_items)
      ? minutes.action_items
          .map((action) => ({
            owner: String(action?.owner ?? "").trim(),
            description: String(action?.description ?? "").trim(),
            due_date: String(action?.due_date ?? "").trim() || null,
          }))
          .filter((action) => action.owner || action.description || action.due_date)
      : [],
    risks: ensureStringList(minutes?.risks),
    model: minutes?.model || "n/a",
    chunk_count: Number.isFinite(minutes?.chunk_count) ? minutes.chunk_count : 0,
  };

  const embeddedMinutes = extractStructuredMinutesFromSummary(normalized.summary);
  if (embeddedMinutes) {
    normalized.summary = embeddedMinutes.summary || normalized.summary;
    if (!normalized.agenda.length) normalized.agenda = embeddedMinutes.agenda;
    if (!normalized.highlights.length) normalized.highlights = embeddedMinutes.highlights;
    if (!normalized.decisions.length) normalized.decisions = embeddedMinutes.decisions;
    if (!normalized.action_items.length) normalized.action_items = embeddedMinutes.action_items;
    if (!normalized.risks.length) normalized.risks = embeddedMinutes.risks;
  }

  normalized.sections = buildMinutesSections(normalized);
  return normalized;
};

const replaceSpeakerLabelInText = (text, fromLabel, toLabel) => {
  if (!text || !fromLabel || !toLabel || fromLabel === toLabel) {
    return text;
  }
  const pattern = new RegExp(escapeRegExp(fromLabel), "g");
  return text.replace(pattern, toLabel);
};

const renameSpeakerInMinutes = (minutes, fromLabel, toLabel) => {
  if (!minutes || !fromLabel || !toLabel || fromLabel === toLabel) {
    return;
  }
  const replace = (value) => replaceSpeakerLabelInText(value, fromLabel, toLabel);
  minutes.summary = replace(minutes.summary);
  minutes.agenda = (minutes.agenda || []).map(replace);
  minutes.highlights = (minutes.highlights || []).map(replace);
  minutes.risks = (minutes.risks || []).map(replace);
  minutes.decisions = (minutes.decisions || []).map((decision) => ({
    ...decision,
    title: replace(decision?.title),
    details: replace(decision?.details),
  }));
  minutes.action_items = (minutes.action_items || []).map((action) => ({
    ...action,
    description: replace(action?.description),
    owner: replace(action?.owner),
  }));
  Object.assign(minutes, normalizeMinutes(minutes));
};

const buildMinutesExportDocument = (
  minutes,
  { durationSeconds = 0, recordedAt, transcript = [] } = {}
) => {
  if (!minutes) {
    return "Keine Minutes vorhanden.";
  }
  const now = new Date();
  const recordedDate = recordedAt ? new Date(recordedAt) : null;
  const recordedLabel =
    recordedDate && !Number.isNaN(recordedDate.getTime())
      ? recordedDate.toLocaleString("de-DE")
      : "unbekannt";
  const lines = [
    `${getAppName()} Meeting Minutes`,
    "======================",
    "",
    `Erstellt: ${now.toLocaleString("de-DE")}`,
    `Aufnahme: ${recordedLabel}`,
    "",
    "ZUSAMMENFASSUNG",
    minutes.summary || "Keine Zusammenfassung vorhanden.",
    "",
  ];

  const pushListSection = (title, items, fallback) => {
    lines.push(title.toUpperCase());
    if (items && items.length) {
      items.forEach((entry) => lines.push(`- ${entry}`));
    } else {
      lines.push(`- ${fallback}`);
    }
    lines.push("");
  };

  pushListSection("Agenda", minutes.agenda, "Keine Agenda vorhanden.");
  pushListSection("Highlights", minutes.highlights, "Keine Highlights vorhanden.");

  const decisionEntries = (minutes.decisions || []).map((decision, index) => {
    const title = decision.title || `Entscheidung ${index + 1}`;
    const details = decision.details || "Keine Details";
    return `${title}: ${details}`;
  });
  pushListSection("Entscheidungen", decisionEntries, "Keine Entscheidungen dokumentiert.");

  const actionEntries = (minutes.action_items || []).map((action, index) => {
    const label = action.description || `Aufgabe ${index + 1}`;
    const owner = action.owner ? `Owner: ${action.owner}` : null;
    const due = action.due_date ? `Fällig: ${action.due_date}` : null;
    return [label, owner, due].filter(Boolean).join(" | ");
  });
  pushListSection("Action Items", actionEntries, "Keine Aufgaben erkannt.");

  pushListSection("Risiken & offene Punkte", minutes.risks, "Keine Risiken erkannt.");

  const transcriptEntries = (transcript || []).map(
    (segment) =>
      `[${formatTime(segment.start * 1000)} - ${formatTime(segment.end * 1000)}] ${
        segment.speaker || "Speaker"
      }: ${segment.text}`,
  );
  pushListSection("Transkript", transcriptEntries, "Kein Transkript vorhanden.");

  return lines.join("\n");
};

const buildMinutesFilename = () => {
  const referenceDate = recordingStartedAtUtc ? new Date(recordingStartedAtUtc) : new Date();
  const safeDate = Number.isNaN(referenceDate.getTime()) ? new Date() : referenceDate;
  return `meeting-minutes-${safeDate.toISOString().replace(/[:.]/g, "-")}.txt`;
};

const downloadMinutes = () => {
  if (!hasMinutesData() || typeof document === "undefined") {
    return;
  }
  const content = buildMinutesExportDocument(minutesCache, {
    durationSeconds: durationCache,
    recordedAt: recordingStartedAtUtc,
    transcript: transcriptCache,
  });
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const urlObject = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = urlObject;
  link.download = buildMinutesFilename();
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(urlObject), 0);
};

const updateSpeakerControlsState = () => {
  const hideSpeakerUi = !globalSpeakerRecognitionEnabled;
  if (transcriptSpeakerControls) {
    transcriptSpeakerControls.classList.toggle(
      "hidden",
      hideSpeakerUi || !transcriptCache.length,
    );
  }
  if (transcriptSpeakerHint) {
    transcriptSpeakerHint.classList.toggle(
      "hidden",
      hideSpeakerUi || !transcriptCache.length,
    );
  }
  if (speakerPanel) {
    speakerPanel.classList.toggle("hidden", !shouldDisplaySpeakerDetection());
  }
};

const setMinutesEditMode = (enabled) => {
  minutesEditMode = Boolean(enabled && hasMinutesData());
  draftMinutesCache = minutesEditMode ? normalizeMinutes(deepClone(minutesCache)) : null;
  updateActionButtonsState();
  renderMinutes(minutesEditMode ? draftMinutesCache : minutesCache, durationCache);
};

const applyTranscriptPayload = (
  payload,
  { speakerDetection = false, audioDurationSeconds = 0, statusMessage = "Transkript aktualisiert" } = {}
) => {
  currentSessionId = payload.session_id ?? null;
  transcriptHasSpeakerDetection = globalSpeakerRecognitionEnabled && speakerDetection;
  transcriptCache = payload.transcript || [];
  minutesCache = normalizeMinutes(
    (payload.minutes && Object.keys(payload.minutes).length ? payload.minutes : buildFallbackMinutes(payload)) || {}
  );
  minutesEditMode = false;
  draftMinutesCache = null;
  durationCache = payload.duration_seconds || durationCache;
  speakersCache =
    globalSpeakerRecognitionEnabled && speakerDetection
      ? normalizeSpeakersList(payload.speakers, transcriptCache)
      : [];
  completeWorkflowTracking(payload.processing);
  renderTranscript(transcriptCache);
  renderMinutes(minutesCache, durationCache);
  renderSpeakerEditor();
  updateSpeakerControlsState();
  const deviceLabel = payload.processing?.device ? ` (${String(payload.processing.device).toUpperCase()})` : "";
  statusText.textContent = `${statusMessage}${deviceLabel}`;
};

const pollAsyncTranscriptionJob = async (jobId, audioDurationSeconds = 0) => {
  if (!jobId) {
    throw new Error("Kein Job wurde von der API zurückgegeben.");
  }
  currentJobId = jobId;
  persistSelectedMeetingId(jobId);
  stopAsyncJobPolling();
  const runPoll = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/transcribe/jobs/${jobId}`, withClientScope());
      if (!response.ok) {
        let detail = `API Fehler ${response.status}`;
        try {
          const errorPayload = await response.json();
          detail = errorPayload?.detail || detail;
        } catch (_error) {
          // Ignore parse errors and keep generic status text.
        }
        throw new Error(detail);
      }
      const job = await response.json();
      currentJobId = job.job_id || jobId;
      currentMeetingName = job.meeting_name || currentMeetingName;
      syncMeetingIntoCacheV2(job);
      if (currentJobId === job.job_id) {
        applySelectedMeetingProgress(job);
      }
      if (job.status === "queued") {
        setAsyncJobStatus(job.message || "Job eingereiht. Verarbeitung startet gleich.");
        statusText.textContent = job.message || "Aufnahme wurde zur Verarbeitung eingereiht ...";
      } else if (job.status === "running") {
        syncWorkflowStateFromJob(job);
        setAsyncJobStatus(job.message || "Job läuft im Hintergrund. Du kannst die Seite offen lassen.");
        statusText.textContent = job.message || "Transkription läuft im Hintergrund ...";
      } else if (job.status === "completed" && job.result) {
        stopAsyncJobPolling();
        setAsyncJobStatus("Job abgeschlossen.", { hidden: false });
        applyTranscriptPayload(job.result, {
          speakerDetection: Array.isArray(job.result.speakers) && job.result.speakers.length > 0,
          audioDurationSeconds: job.result.duration_seconds || audioDurationSeconds,
          statusMessage: "Transkript aktualisiert im asynchronen Schnellmodus",
        });
        setRecordButtonState({ recording: false, busy: false });
        showToast("Transkription abgeschlossen.", { variant: "success", duration: 3000 });
        await notifyProcessingFinished(`${getAppName()} Minutes`, "Die Transkription ist abgeschlossen.");
        await fetchMeetings({ preserveSelection: true });
        return;
      } else if (job.status === "failed") {
        stopAsyncJobPolling();
        await notifyProcessingFinished(`${getAppName()} Minutes`, `Die Transkription ist fehlgeschlagen: ${job.message}`);
        throw new Error(job.message || "Transkription fehlgeschlagen.");
      } else if (job.status === "cancelled") {
        stopAsyncJobPolling();
        statusText.textContent = "Verarbeitung gestoppt.";
        setAsyncJobStatus(job.message || "Job wurde gestoppt.");
        await fetchMeetings({ preserveSelection: true });
        return;
      }
      const waitMs = Math.max(Number(job.poll_after_ms) || 1500, 500);
      asyncJobPollTimeoutId = window.setTimeout(() => {
        void runPoll();
      }, waitMs);
    } catch (error) {
      handleError(error?.message || "Asynchrone Transkription fehlgeschlagen.");
    }
  };
  await runPoll();
};

const uploadBlob = async (blob, filename = "recording.webm") => {
  const diarize = globalSpeakerRecognitionEnabled && speakerDetectionEnabled;
  const formData = new FormData();
  formData.append("audio", blob, filename);
  // Keep the field for backward compatibility with older backend processes.
  formData.append("meeting_name", "");
  formData.append("diarize", String(diarize));
  currentAudioBlob = blob;
  currentAudioFilename = filename;
  currentSessionId = null;
  currentJobId = null;
  currentMeetingName = "";
  reprocessInFlight = true;
  updateSpeakerControlsState();
  stopAsyncJobPolling();
  setAsyncJobStatus("", { hidden: true });
  statusText.textContent = "Verarbeite Aufnahme ...";
  setAudioSource(blob);
  beginWorkflowTracking();
  statusText.textContent = "Transkription wird im Hintergrund gestartet ...";

  try {
    const estimatedAudioDurationSeconds = await resolveInitialAudioDurationSeconds(blob);
    formData.append("estimated_audio_duration_seconds", String(estimatedAudioDurationSeconds || 0));

    const response = await fetch(`${API_BASE}/api/transcribe/jobs`, withClientScope({
      method: "POST",
      body: formData,
    }));
    if (!response.ok) {
      let detail = `API Fehler ${response.status}`;
      try {
        const errorPayload = await response.json();
        detail = errorPayload?.detail || detail;
      } catch (_error) {
        // Ignore parse errors and keep generic status text.
      }
      if (response.status === 504) {
        detail = "Die Transkription hat das Gateway-Timeout erreicht. Bitte den asynchronen Job-Status pruefen.";
      }
      throw new Error(detail);
    }
    const job = await response.json();
    syncMeetingIntoCacheV2(job);
    setSelectedMeetingHeaderV2(job);
    setAsyncJobStatus(job.message || "Job eingereiht. Verarbeitung startet gleich.");
    statusText.textContent = job.message || "Aufnahme wurde zur Verarbeitung eingereiht ...";
    await pollAsyncTranscriptionJob(job.job_id, estimatedAudioDurationSeconds || 0);
  } catch (error) {
    console.error(error);
    handleError(error?.message || "Upload fehlgeschlagen. Bitte erneut versuchen.");
  } finally {
    reprocessInFlight = false;
    updateSpeakerControlsState();
  }
};

const renderTranscript = (segments = []) => {
  transcriptContainer.innerHTML = "";
  if (!segments.length) {
    transcriptContainer.innerHTML = '<p class="hint">Noch keine Daten.</p>';
    return;
  }

  const wrapper = document.createElement("article");
  wrapper.className = "segment transcript-block";

  if (!shouldDisplaySpeakerDetection()) {
    wrapper.innerHTML = `<p>${escapeHtml(segments.map((segment) => segment.text).join(" "))}</p>`;
    transcriptContainer.appendChild(wrapper);
    return;
  }

  const content = segments
    .map((segment, index) => {
      const speaker = escapeHtml(segment.speaker || `Speaker ${index + 1}`);
      const text = escapeHtml(segment.text || "");
      return `
        <section class="transcript-entry">
          <div class="transcript-entry-speaker">${speaker}:</div>
          <p class="transcript-entry-text">${text}</p>
        </section>
      `;
    })
    .join("");

  wrapper.innerHTML = `<div class="transcript-entry-list">${content}</div>`;
  transcriptContainer.appendChild(wrapper);
};

const renderTaskBoard = (boardPayload) => {
  const entries = Array.isArray(boardPayload?.entries) ? boardPayload.entries : [];
  const analytics = boardPayload?.analytics || {};
  if (taskBoardSummary) {
    taskBoardSummary.innerHTML = `
      <section class="minutes-grid">
        <div class="minutes-section">
          <h3>Aufgaben</h3>
          <p>${Number(analytics.total_tasks || 0)}</p>
        </div>
        <div class="minutes-section">
          <h3>Meetings</h3>
          <p>${Number(analytics.total_meetings || 0)}</p>
        </div>
        <div class="minutes-section">
          <h3>E-Mails versendet</h3>
          <p>${Number(analytics.emailed_tasks || 0)}</p>
        </div>
        <div class="minutes-section">
          <h3>E-Mails fehlgeschlagen</h3>
          <p>${Number(analytics.failed_emails || 0)}</p>
        </div>
      </section>
    `;
  }

  if (taskBoardEntries) {
    if (!entries.length) {
      taskBoardEntries.innerHTML =
        '<p class="hint">Noch keine Aufgaben gespeichert. Versende Minutes, dann erscheinen die Aufgaben hier.</p>';
    } else {
      taskBoardEntries.innerHTML = entries
        .slice(0, 40)
        .map((entry) => {
          const emailBadgeClass =
            entry.email_status === "sent"
              ? "meeting-status-completed"
              : entry.email_status === "failed"
                ? "meeting-status-failed"
                : "meeting-status-queued";
          const due = entry.due_date ? ` | Faellig: ${escapeHtml(entry.due_date)}` : "";
          return `
            <article class="meeting-list-item meeting-list-item-single">
              <div class="meeting-list-item-header">
                <h3>${escapeHtml(entry.task_description || "Aufgabe")}</h3>
                <span class="meeting-status-badge ${emailBadgeClass}">${escapeHtml(entry.email_status || "offen")}</span>
              </div>
              <p class="meeting-list-meta">
                <span>Owner: ${escapeHtml(entry.task_owner || "Unbekannt")}${due}</span>
                <span>Meeting: ${escapeHtml(entry.meeting_name || "Meeting")} | Raum: ${escapeHtml(entry.room || "unknown")}</span>
                <span>Zeitpunkt: ${escapeHtml(formatRecordedAtForEmail(entry.recorded_at))}</span>
                <span>E-Mail: ${escapeHtml(entry.recipient_email || "-")} | ${escapeHtml(entry.email_detail || "Kein Versand ausgefuehrt.")}</span>
              </p>
            </article>
          `;
        })
        .join("");
    }
  }

  if (taskBoardInsights) {
    const repeatedTasks = Array.isArray(analytics.repeated_tasks) ? analytics.repeated_tasks : [];
    const ownerWorkload = Array.isArray(analytics.owner_workload) ? analytics.owner_workload : [];
    const similarMeetings = Array.isArray(analytics.similar_meetings) ? analytics.similar_meetings : [];

    const repeatedHtml = repeatedTasks.length
      ? `<ul>${repeatedTasks
          .slice(0, 6)
          .map(
            (item) =>
              `<li>${escapeHtml(item.task_description)} (${Number(item.occurrences || 0)}x in ${Number(item.meetings || 0)} Meetings)</li>`
          )
          .join("")}</ul>`
      : '<p class="hint">Noch keine wiederkehrenden Aufgaben erkannt.</p>';
    const ownersHtml = ownerWorkload.length
      ? `<ul>${ownerWorkload
          .slice(0, 6)
          .map(
            (item) =>
              `<li>${escapeHtml(item.owner)}: ${Number(item.tasks || 0)} Aufgaben, ${Number(item.sent_emails || 0)} E-Mails gesendet, ${Number(item.failed_emails || 0)} fehlgeschlagen</li>`
          )
          .join("")}</ul>`
      : '<p class="hint">Noch keine Owner-Auslastung verfuegbar.</p>';
    const similarHtml = similarMeetings.length
      ? `<ul>${similarMeetings
          .slice(0, 6)
          .map(
            (item) =>
              `<li>${escapeHtml(item.left_meeting_name)} <-> ${escapeHtml(item.right_meeting_name)} (Score ${Number(item.similarity_score || 0).toFixed(2)}; Keywords: ${escapeHtml((item.common_keywords || []).join(", "))})</li>`
          )
          .join("")}</ul>`
      : '<p class="hint">Noch keine aehnlichen Meetings erkannt.</p>';

    taskBoardInsights.innerHTML = `
      <h3>Intelligente Auswertungen</h3>
      <div class="minutes-grid">
        <div class="minutes-section">
          <h3>Wiederkehrende Aufgaben</h3>
          ${repeatedHtml}
        </div>
        <div class="minutes-section">
          <h3>Owner-Auslastung</h3>
          ${ownersHtml}
        </div>
      </div>
      <div class="minutes-section">
        <h3>Aehnliche Meetings</h3>
        ${similarHtml}
      </div>
    `;
  }
};

const setTaskBoardVisible = (visible) => {
  if (!TASK_BOARD_FEATURE_ENABLED) {
    return;
  }
  if (!taskBoardPanel) {
    return;
  }
  const nextVisible = Boolean(visible);
  taskBoardPanel.classList.toggle("hidden", !nextVisible);
  if (openTaskBoardBtn) {
    openTaskBoardBtn.textContent = nextVisible
      ? "Aufgaben-Auswertung ausblenden"
      : "Aufgaben-Auswertung anzeigen";
  }
};

const stopTaskBoardAutoRefresh = () => {
  if (!TASK_BOARD_FEATURE_ENABLED) {
    return;
  }
  if (taskBoardAutoRefreshIntervalId) {
    window.clearInterval(taskBoardAutoRefreshIntervalId);
    taskBoardAutoRefreshIntervalId = null;
  }
};

const startTaskBoardAutoRefresh = () => {
  if (!TASK_BOARD_FEATURE_ENABLED) {
    return;
  }
  stopTaskBoardAutoRefresh();
  if (!isAuthenticated()) {
    return;
  }
  taskBoardAutoRefreshIntervalId = window.setInterval(() => {
    void fetchTaskBoard();
  }, 30000);
};

const fetchTaskBoard = async () => {
  if (!TASK_BOARD_FEATURE_ENABLED) {
    return;
  }
  if (!isAuthenticated()) {
    return;
  }
  try {
    const response = await fetch(TASK_BOARD_ENDPOINT, withClientScope());
    if (!response.ok) {
      throw new Error(`API Fehler ${response.status}`);
    }
    taskBoardCache = await response.json();
    renderTaskBoard(taskBoardCache);
  } catch (_error) {
    if (taskBoardEntries) {
      taskBoardEntries.innerHTML = '<p class="hint">Aufgaben-Board konnte nicht geladen werden.</p>';
    }
  }
};


const setAudioSource = (blob) => {
  if (!audioPlayer || !audioCard || !blob) return;
  stopSpeakerSamplePlayback();
  if (audioUrl) {
    URL.revokeObjectURL(audioUrl);
  }
  audioUrl = URL.createObjectURL(blob);
  audioPlayer.src = audioUrl;
  audioPlayer.load();
  audioCard.classList.remove("hidden");
};

const hideAudioPlayer = () => {
  if (!audioCard) return;
  audioCard.classList.add("hidden");
  stopSpeakerSamplePlayback();
  if (audioUrl) {
    URL.revokeObjectURL(audioUrl);
    audioUrl = undefined;
  }
  if (audioPlayer) {
    audioPlayer.removeAttribute("src");
    audioPlayer.load();
  }
};

const hasMinutesData = () => Boolean(minutesCache && Object.keys(minutesCache).length);

const splitActionItemOwners = (rawOwner) => {
  const value = String(rawOwner || "").trim();
  if (!value) {
    return [];
  }
  if (EMAIL_PATTERN.test(value)) {
    return [value];
  }
  return value
    .split(OWNER_SPLIT_PATTERN)
    .map((entry) => entry.trim().replace(/\s+/g, " "))
    .filter(Boolean);
};

const toOwnerEmailLocalpart = (owner) =>
  String(owner || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ".")
    .replace(/^\.+|\.+$/g, "")
    .slice(0, 64);

const getCurrentUserEmailDomain = () => {
  const email = String(currentUser?.email || "").trim().toLowerCase();
  const atIndex = email.lastIndexOf("@");
  if (atIndex <= 0 || atIndex >= email.length - 1) {
    return "";
  }
  return email.slice(atIndex + 1);
};

const buildSuggestedOwnerEmail = (owner) => {
  const normalizedOwner = String(owner || "").trim();
  if (!normalizedOwner) {
    return "";
  }
  if (EMAIL_PATTERN.test(normalizedOwner)) {
    return normalizedOwner;
  }
  const localPart = toOwnerEmailLocalpart(normalizedOwner);
  const domain = getCurrentUserEmailDomain();
  if (!localPart || !domain) {
    return "";
  }
  return `${localPart}@${domain}`;
};

const buildActionItemEntryKey = ({ owner, action_item_description, due_date }) =>
  `${String(owner || "").trim().toLowerCase()}|${String(action_item_description || "")
    .trim()
    .toLowerCase()}|${String(due_date || "")
    .trim()
    .toLowerCase()}`;

const formatRecordedAtForEmail = (value) => {
  const date = new Date(String(value || ""));
  if (Number.isNaN(date.getTime())) {
    return String(value || "").trim() || "unbekannt";
  }
  return date.toLocaleString("de-DE");
};

const buildDefaultActionItemEmailBody = ({
  owner,
  action_item_description,
  due_date,
  room,
  recorded_at,
  minutes,
}) => {
  const summary = String(minutes?.summary || "").trim() || "Keine Kurzzusammenfassung vorhanden.";
  const decisions = Array.isArray(minutes?.decisions)
    ? minutes.decisions
        .slice(0, 2)
        .map((decision) => {
          const title = String(decision?.title || "").trim();
          const details = String(decision?.details || "").trim();
          if (!title && !details) {
            return "";
          }
          return details ? `- ${title || "Entscheidung"}: ${details}` : `- ${title}`;
        })
        .filter(Boolean)
    : [];
  const dueLine = String(due_date || "").trim() ? `Faelligkeit: ${String(due_date).trim()}` : "Faelligkeit: offen";
  const lines = [
    `Hallo ${owner},`,
    "",
    "aus dem aktuellen Meeting wurde folgende Aufgabe fuer dich erfasst:",
    "",
    `Aufgabe: ${String(action_item_description || "Keine Beschreibung").trim() || "Keine Beschreibung"}`,
    dueLine,
    "",
    "Kontext:",
    `- Raum: ${room || "unknown"}`,
    `- Zeitpunkt: ${formatRecordedAtForEmail(recorded_at)}`,
    `- Kurzzusammenfassung: ${summary}`,
  ];
  if (decisions.length) {
    lines.push("- Wichtige Entscheidungen:");
    lines.push(...decisions);
  }
  lines.push("");
  lines.push("Bitte pruefe die Aufgabe und gib bei Bedarf Rueckmeldung.");
  lines.push("");
  lines.push("Viele Gruesse");
  lines.push(getAppName());
  return lines.join("\n");
};

const createActionItemNotificationEntries = (
  minutes,
  { room, recorded_at, previousEntries = [] } = {}
) => {
  const previousByKey = new Map(
    (Array.isArray(previousEntries) ? previousEntries : []).map((entry) => [
      buildActionItemEntryKey(entry),
      entry,
    ])
  );
  const items = Array.isArray(minutes?.action_items) ? minutes.action_items : [];
  const entries = [];
  items.forEach((item) => {
    const description = String(item?.description || "").trim();
    if (!description) {
      return;
    }
    const dueDate = String(item?.due_date || "").trim() || null;
    const owners = splitActionItemOwners(item?.owner);
    const normalizedOwners = owners.length ? owners : [String(item?.owner || "Unbekannt").trim() || "Unbekannt"];
    normalizedOwners.forEach((owner) => {
      const baseEntry = {
        owner,
        action_item_description: description,
        due_date: dueDate,
      };
      const key = buildActionItemEntryKey(baseEntry);
      const previous = previousByKey.get(key);
      const recipientEmail = String(previous?.recipient_email || "").trim() || buildSuggestedOwnerEmail(owner);
      const emailBody =
        String(previous?.email_body || "").trim() ||
        buildDefaultActionItemEmailBody({
          ...baseEntry,
          room,
          recorded_at,
          minutes,
        });
      entries.push({
        ...baseEntry,
        recipient_email: recipientEmail,
        email_body: emailBody,
      });
    });
  });
  return entries;
};

const closeActionItemDraftModal = () => {
  if (!actionItemDraftModal) {
    return;
  }
  actionItemDraftModal.classList.add("hidden");
  activeActionItemDraftIndex = null;
};

const openActionItemDraftModal = (entryIndex) => {
  if (!actionItemDraftModal || !actionItemDraftMeta || !actionItemDraftText) {
    return;
  }
  const index = Number.parseInt(String(entryIndex), 10);
  if (!Number.isInteger(index) || !actionItemNotificationEntries[index]) {
    return;
  }
  const entry = actionItemNotificationEntries[index];
  const duePart = entry.due_date ? ` | Faellig: ${entry.due_date}` : "";
  actionItemDraftMeta.textContent = `Owner: ${entry.owner}${duePart}`;
  actionItemDraftText.value = String(entry.email_body || "");
  activeActionItemDraftIndex = index;
  actionItemDraftModal.classList.remove("hidden");
  actionItemDraftText.focus();
};

const renderActionItemNotifyList = () => {
  if (!actionItemNotifyList) {
    return;
  }
  if (!actionItemNotificationEntries.length) {
    actionItemNotifyList.innerHTML = '<p class="hint">Keine Action Items erkannt.</p>';
    return;
  }
  actionItemNotifyList.innerHTML = actionItemNotificationEntries
    .map((entry, index) => {
      const dueText = entry.due_date ? ` | Faellig: ${escapeHtml(entry.due_date)}` : "";
      return `
        <article class="meeting-list-item meeting-list-item-single action-item-notify-item" data-action-item-entry-index="${index}">
          <div class="meeting-list-item-header">
            <h3 class="action-item-notify-task">${escapeHtml(entry.action_item_description)}</h3>
            <button class="ghost action-item-draft-btn" type="button" data-action-item-draft-open="${index}">
              Entwurf
            </button>
          </div>
          <p class="meeting-list-meta">Owner: ${escapeHtml(entry.owner)}${dueText}</p>
          <label class="minutes-field action-item-email-field" for="action-item-email-${index}">
            <span>E-Mail-Adresse</span>
            <input
              id="action-item-email-${index}"
              type="email"
              value="${escapeHtml(entry.recipient_email || "")}"
              placeholder="name@firma.de"
              data-action-item-email-index="${index}"
            />
          </label>
        </article>
      `;
    })
    .join("");
};

const syncActionItemNotifyUi = () => {
  if (!actionItemNotifyDetails || !notifyActionItemsToggle) {
    return;
  }
  const enabled = Boolean(notifyActionItemsToggle.checked);
  actionItemNotifyDetails.classList.toggle("hidden", !enabled);
  if (!enabled) {
    closeActionItemDraftModal();
    return;
  }
  renderActionItemNotifyList();
};

const updateActionButtonsState = () => {
  const disabled = !hasMinutesData() || minutesEditMode;
  if (sendBtn) {
    sendBtn.disabled = disabled || !globalSendEnabled;
    sendBtn.classList.toggle("hidden", !globalSendEnabled);
  }
  if (downloadBtn) {
    downloadBtn.disabled = disabled;
  }
  if (editMinutesBtn) {
    editMinutesBtn.disabled = !hasMinutesData();
    editMinutesBtn.textContent = minutesEditMode ? "Bearbeitung aktiv" : "Minutes bearbeiten";
  }
};

const hasAudioSource = () => Boolean(audioUrl);

const shouldDisplaySpeakerDetection = () =>
  globalSpeakerRecognitionEnabled && speakerDetectionEnabled && transcriptHasSpeakerDetection;

const hideToast = () => {
  if (!toast) {
    return;
  }
  toast.classList.add("hidden");
  toast.textContent = "";
  toast.classList.remove("toast-success", "toast-error", "toast-info");
  if (toastTimeoutId) {
    clearTimeout(toastTimeoutId);
    toastTimeoutId = null;
  }
};

const showToast = (message, { variant = "info", duration = 2000 } = {}) => {
  if (!toast) {
    return;
  }
  if (toastTimeoutId) {
    clearTimeout(toastTimeoutId);
    toastTimeoutId = null;
  }
  toast.textContent = message;
  toast.classList.remove("hidden", "toast-success", "toast-error", "toast-info");
  const variantClass = variant === "error" ? "toast-error" : variant === "success" ? "toast-success" : "toast-info";
  toast.classList.add(variantClass);
  toastTimeoutId = window.setTimeout(() => {
    hideToast();
  }, duration);
};

const stopSpeakerSamplePlayback = () => {
  if (speakerSampleTimeoutId) {
    clearTimeout(speakerSampleTimeoutId);
    speakerSampleTimeoutId = null;
  }
  if (activeSampleSpeakerId && audioPlayer) {
    audioPlayer.pause();
  }
  activeSampleSpeakerId = null;
};

const waitForAudioReady = () =>
  new Promise((resolve, reject) => {
    if (!audioPlayer) {
      reject(new Error("Kein Audioplayer verfügbar"));
      return;
    }
    if (audioPlayer.readyState >= 1) {
      resolve();
      return;
    }
    let settled = false;
    const handleReady = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };
    const handleError = () => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error("Audio konnte nicht geladen werden"));
    };
    const cleanup = () => {
      audioPlayer.removeEventListener("loadedmetadata", handleReady);
      audioPlayer.removeEventListener("error", handleError);
    };
    audioPlayer.addEventListener("loadedmetadata", handleReady);
    audioPlayer.addEventListener("error", handleError);
  });

const getSpeakerSampleWindow = (speakerId) => {
  if (!speakerId || !transcriptCache.length) {
    return null;
  }
  const segment = transcriptCache.find((item) => item.speaker_id === speakerId);
  if (!segment) {
    return null;
  }
  const start = Math.max(segment.start - SPEAKER_SAMPLE_PREROLL, 0);
  const naturalDuration = Math.max(segment.end - segment.start, 0);
  const duration = Math.min(
    Math.max(naturalDuration || SPEAKER_SAMPLE_MIN_DURATION, SPEAKER_SAMPLE_MIN_DURATION),
    SPEAKER_SAMPLE_MAX_DURATION,
  );
  return { start, duration };
};

const playSpeakerSample = async (speakerId) => {
  if (!hasAudioSource() || !audioPlayer) {
    return;
  }
  const window = getSpeakerSampleWindow(speakerId);
  if (!window) {
    return;
  }
  try {
    await waitForAudioReady();
  } catch (error) {
    console.warn("Audioplayer nicht bereit", error);
    return;
  }
  stopSpeakerSamplePlayback();
  try {
    audioPlayer.currentTime = window.start;
    const playPromise = audioPlayer.play();
    activeSampleSpeakerId = speakerId;
    if (playPromise && typeof playPromise.then === "function") {
      await playPromise;
    }
    speakerSampleTimeoutId = setTimeout(() => {
      if (audioPlayer) {
        audioPlayer.pause();
      }
      activeSampleSpeakerId = null;
    }, window.duration * 1000);
  } catch (error) {
    console.error("Hörprobe konnte nicht abgespielt werden", error);
    activeSampleSpeakerId = null;
  }
};

const handleSpeakerRename = (speakerId, nextLabel) => {
  if (!speakerId || !hasMinutesData()) {
    return;
  }
  const index = speakersCache.findIndex((speaker) => speaker.speaker_id === speakerId);
  if (index === -1) {
    return;
  }
  const current = speakersCache[index];
  const baseLabel = current.default_label || current.label || `Speaker ${index + 1}`;
  const sanitized = (nextLabel || "").trim();
  const updatedLabel = sanitized || baseLabel;
  if (updatedLabel === current.label) {
    return;
  }
  const previousLabel = current.label || baseLabel;
  speakersCache.splice(index, 1, { ...current, label: updatedLabel });
  transcriptCache = transcriptCache.map((segment) => {
    if (segment.speaker_id === speakerId) {
      return { ...segment, speaker: updatedLabel };
    }
    return segment;
  });
  if (minutesCache) {
    renameSpeakerInMinutes(minutesCache, previousLabel, updatedLabel);
    if (draftMinutesCache) {
      renameSpeakerInMinutes(draftMinutesCache, previousLabel, updatedLabel);
    }
  }
  renderTranscript(transcriptCache);
  renderMinutes(minutesEditMode ? draftMinutesCache : minutesCache, durationCache);
};

const renderSpeakerEditor = () => {
  if (!speakerEditor) {
    return;
  }
  speakerEditor.innerHTML = "";
  if (!hasMinutesData()) {
    return;
  }
  if (!shouldDisplaySpeakerDetection()) {
    return;
  }
  if (!speakersCache.length) {
    speakerEditor.innerHTML = '<p class="hint">Keine Sprecher erkannt.</p>';
    return;
  }

  speakersCache.forEach((speaker, index) => {
    const row = document.createElement("div");
    row.className = "speaker-row";
    const label = document.createElement("label");
    const inputId = `speaker-input-${index + 1}`;
    label.setAttribute("for", inputId);
    label.textContent = speaker.default_label || `Speaker ${index + 1}`;
    const input = document.createElement("input");
    input.id = inputId;
    input.type = "text";
    input.value = speaker.label || "";
    input.placeholder = "Name eingeben";
    input.addEventListener("change", (event) => {
      handleSpeakerRename(speaker.speaker_id, event.target.value);
    });
    const sampleButton = document.createElement("button");
    sampleButton.type = "button";
    sampleButton.className = "ghost speaker-audio-btn";
    sampleButton.textContent = "Hörprobe";
    sampleButton.disabled = !hasAudioSource();
    sampleButton.addEventListener("click", () => {
      playSpeakerSample(speaker.speaker_id);
    });
    row.appendChild(label);
    row.appendChild(input);
    row.appendChild(sampleButton);
    speakerEditor.appendChild(row);
  });
};

const getRecordedAtTimestamp = () => recordingStartedAtUtc || new Date().toISOString();

const getSelectedRoom = () => {
  if (typeof document === "undefined") {
    return "E01-115 SWS";
  }
  const selected = document.querySelector('input[name="sendTarget"]:checked');
  return selected?.value || "E01-115 SWS";
};

const openRoomModal = () => {
  if (!roomModal || !hasMinutesData()) {
    return;
  }
  actionItemNotificationEntries = createActionItemNotificationEntries(minutesCache, {
    room: getSelectedRoom(),
    recorded_at: getRecordedAtTimestamp(),
    previousEntries: actionItemNotificationEntries,
  });
  syncActionItemNotifyUi();
  roomModal.classList.remove("hidden");
};

const closeRoomModal = () => {
  if (!roomModal) {
    return;
  }
  roomModal.classList.add("hidden");
  closeActionItemDraftModal();
  if (confirmSendBtn) {
    confirmSendBtn.disabled = false;
    confirmSendBtn.textContent = confirmSendDefaultLabel;
  }
};

const sendMinutesToWebhook = async () => {
  if (!hasMinutesData()) {
    return;
  }
  if (confirmSendBtn) {
    confirmSendBtn.disabled = true;
    confirmSendBtn.textContent = "Sendet ...";
  }
  statusText.textContent = "Minutes werden gesendet ...";
  statusText.classList.remove("error");
  const payload = {
    meeting_name: currentMeetingName || selectedMeetingTitle?.textContent || "Meeting",
    meeting_key: currentJobId || null,
    recorded_at: getRecordedAtTimestamp(),
    duration_seconds: durationCache || 0,
    minutes: minutesCache,
    room: getSelectedRoom(),
    notify_action_items: notifyActionItemsToggle ? Boolean(notifyActionItemsToggle.checked) : true,
    action_item_notification_overrides: [],
  };
  if (payload.notify_action_items) {
    actionItemNotificationEntries = createActionItemNotificationEntries(minutesCache, {
      room: payload.room,
      recorded_at: payload.recorded_at,
      previousEntries: actionItemNotificationEntries,
    });
    payload.action_item_notification_overrides = actionItemNotificationEntries.map((entry) => ({
      owner: entry.owner,
      action_item_description: entry.action_item_description,
      recipient_email: String(entry.recipient_email || "").trim() || null,
      email_body: String(entry.email_body || "").trim() || null,
    }));
  }
  try {
    const response = await fetch(MEETING_FORWARD_ENDPOINT, withClientScope({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }));
    if (!response.ok) {
      throw new Error(`API Fehler ${response.status}`);
    }
    const responsePayload = await response.json();
    const delivered = Boolean(responsePayload?.webhook?.delivered);
    const detail = responsePayload?.webhook?.detail || "";
    if (!delivered) {
      throw new Error(detail || "Webhook-Zustellung fehlgeschlagen.");
    }
    const notificationStatuses = Array.isArray(responsePayload?.action_item_notifications)
      ? responsePayload.action_item_notifications
      : [];
    const deliveredNotifications = notificationStatuses.filter((item) => item?.delivered).length;
    const failedNotifications = notificationStatuses.length - deliveredNotifications;
    let successMessage = "Meeting Minutes wurden erfolgreich versendet.";
    if (payload.notify_action_items) {
      successMessage =
        failedNotifications > 0
          ? `Minutes versendet. Aufgaben-Mails: ${deliveredNotifications} erfolgreich, ${failedNotifications} fehlgeschlagen.`
          : `Minutes versendet. Aufgaben-Mails: ${deliveredNotifications} erfolgreich.`;
    }
    statusText.textContent = successMessage;
    showToast(successMessage, { variant: "success" });
    closeRoomModal();
  } catch (error) {
    console.error(error);
    statusText.textContent = "Senden fehlgeschlagen";
    statusText.classList.add("error");
    showToast("Versand fehlgeschlagen. Bitte erneut versuchen.", { variant: "error" });
    setTimeout(() => statusText.classList.remove("error"), 4000);
  } finally {
    if (confirmSendBtn) {
      confirmSendBtn.disabled = false;
      confirmSendBtn.textContent = confirmSendDefaultLabel;
    }
  }
};

const parseMultilineList = (value) =>
  String(value ?? "")
    .split("\n")
    .map((entry) => entry.trim())
    .filter(Boolean);

const updateDraftMinutesField = (field, value) => {
  if (!draftMinutesCache) {
    return;
  }
  if (field === "summary") {
    draftMinutesCache.summary = String(value ?? "");
  } else if (field === "agenda" || field === "highlights" || field === "risks") {
    draftMinutesCache[field] = parseMultilineList(value);
  }
  draftMinutesCache = normalizeMinutes(draftMinutesCache);
};

const updateDraftMinutesItem = (collection, index, field, value) => {
  if (!draftMinutesCache || !Array.isArray(draftMinutesCache[collection])) {
    return;
  }
  const item = draftMinutesCache[collection][index];
  if (!item) {
    return;
  }
  item[field] = value;
  draftMinutesCache = normalizeMinutes(draftMinutesCache);
};

const addDraftMinutesItem = (collection) => {
  if (!draftMinutesCache) {
    return;
  }
  if (collection === "decisions") {
    draftMinutesCache.decisions.push({ title: "", details: "" });
  } else if (collection === "action_items") {
    draftMinutesCache.action_items.push({ owner: "", description: "", due_date: "" });
  }
  renderMinutes(draftMinutesCache, durationCache);
};

const removeDraftMinutesItem = (collection, index) => {
  if (!draftMinutesCache || !Array.isArray(draftMinutesCache[collection])) {
    return;
  }
  draftMinutesCache[collection].splice(index, 1);
  draftMinutesCache = normalizeMinutes(draftMinutesCache);
  renderMinutes(draftMinutesCache, durationCache);
};

const saveDraftMinutes = () => {
  if (!draftMinutesCache) {
    return;
  }
  minutesCache = normalizeMinutes(deepClone(draftMinutesCache));
  minutesEditMode = false;
  draftMinutesCache = null;
  updateActionButtonsState();
  renderMinutes(minutesCache, durationCache);
  renderSpeakerEditor();
  showToast("Bearbeitete Minutes wurden übernommen.", { variant: "success" });
};

const cancelDraftMinutes = () => {
  minutesEditMode = false;
  draftMinutesCache = null;
  updateActionButtonsState();
  renderMinutes(minutesCache, durationCache);
};


const renderMinutes = (minutes, _duration = 0) => {
  updateActionButtonsState();
  if (!minutes) {
    minutesContainer.innerHTML = '<p class="hint">Noch keine Auswertung vorhanden.</p>';
    return;
  }

  const renderList = (items, emptyLabel) => {
    if (!items || !items.length) {
      return `<p class="hint">${escapeHtml(emptyLabel)}</p>`;
    }
    return `
      <ul>
        ${items
          .map((item) => `<li>${escapeHtml(item)}</li>`)
          .join("")}
      </ul>
    `;
  };

  const renderDecisions = (decisions = []) => {
    if (!decisions.length) return '<p class="hint">Keine Entscheidungen dokumentiert.</p>';
    return `
      <ul>
        ${decisions
          .map(
            (decision) => `
              <li>
                <strong>${escapeHtml(decision.title)}</strong>
                <p>${escapeHtml(decision.details || "Keine Details")}</p>
              </li>
            `,
          )
          .join("")}
      </ul>
    `;
  };

  const renderActions = (actions = []) => {
    if (!actions.length) return '<p class="hint">Keine Aufgaben erkannt.</p>';
    return `
      <ul>
        ${actions
          .map(
            (action) => `
              <li>
                <div>
                  <strong>${escapeHtml(action.description || "Aufgabe")}</strong>
                  <p>Owner: ${escapeHtml(action.owner || "NN")}${
                    action.due_date ? ` • Fällig: ${escapeHtml(action.due_date)}` : ""
                  }</p>
                </div>
              </li>
            `,
          )
          .join("")}
      </ul>
    `;
  };

  if (minutesEditMode) {
    minutesContainer.innerHTML = `
      <div class="minutes-toolbar">
        <p class="hint">Änderungen wirken sich direkt auf Export und Versand aus.</p>
        <div class="minutes-edit-actions">
          <button id="cancelMinutesEditBtn" class="ghost" type="button">Verwerfen</button>
          <button id="saveMinutesEditBtn" class="primary" type="button">Änderungen speichern</button>
        </div>
      </div>
      <div class="minutes-editor">
        <section class="minutes-section">
          <div class="minutes-field">
            <label for="minutesSummaryInput">Kurzzusammenfassung</label>
            <textarea id="minutesSummaryInput" data-minutes-field="summary">${escapeHtml(
              minutes.summary || ""
            )}</textarea>
          </div>
        </section>
        <section class="minutes-grid">
          <div class="minutes-section">
            <div class="minutes-field">
              <label for="minutesAgendaInput">Agenda</label>
              <textarea id="minutesAgendaInput" data-minutes-field="agenda" placeholder="Ein Punkt pro Zeile">${escapeHtml(
                (minutes.agenda || []).join("\n")
              )}</textarea>
            </div>
          </div>
          <div class="minutes-section">
            <div class="minutes-field">
              <label for="minutesHighlightsInput">Highlights</label>
              <textarea id="minutesHighlightsInput" data-minutes-field="highlights" placeholder="Ein Punkt pro Zeile">${escapeHtml(
                (minutes.highlights || []).join("\n")
              )}</textarea>
            </div>
          </div>
        </section>
        <section class="minutes-repeatable-group">
          <div class="minutes-repeatable-header">
            <h3>Entscheidungen</h3>
            <button class="ghost" type="button" data-minutes-add="decisions">Eintrag hinzufügen</button>
          </div>
          ${
            (minutes.decisions || []).length
              ? minutes.decisions
                  .map(
                    (decision, index) => `
                      <div class="minutes-repeatable-item">
                        <div class="minutes-field">
                          <label for="decision-title-${index}">Titel</label>
                          <input id="decision-title-${index}" type="text" value="${escapeHtml(
                            decision.title || ""
                          )}" data-minutes-collection="decisions" data-minutes-index="${index}" data-minutes-prop="title" />
                        </div>
                        <div class="minutes-field">
                          <label for="decision-details-${index}">Details</label>
                          <textarea id="decision-details-${index}" data-minutes-collection="decisions" data-minutes-index="${index}" data-minutes-prop="details">${escapeHtml(
                            decision.details || ""
                          )}</textarea>
                        </div>
                        <div class="minutes-repeatable-item-actions">
                          <button class="ghost minutes-remove-btn" type="button" data-minutes-remove="decisions" data-minutes-index="${index}">Löschen</button>
                        </div>
                      </div>
                    `
                  )
                  .join("")
              : '<p class="hint">Noch keine Entscheidungen vorhanden.</p>'
          }
        </section>
        <section class="minutes-repeatable-group">
          <div class="minutes-repeatable-header">
            <h3>Action Items</h3>
            <button class="ghost" type="button" data-minutes-add="action_items">Eintrag hinzufügen</button>
          </div>
          ${
            (minutes.action_items || []).length
              ? minutes.action_items
                  .map(
                    (action, index) => `
                      <div class="minutes-repeatable-item">
                        <div class="minutes-field">
                          <label for="action-owner-${index}">Owner</label>
                          <input id="action-owner-${index}" type="text" value="${escapeHtml(
                            action.owner || ""
                          )}" data-minutes-collection="action_items" data-minutes-index="${index}" data-minutes-prop="owner" />
                        </div>
                        <div class="minutes-field">
                          <label for="action-description-${index}">Aufgabe</label>
                          <textarea id="action-description-${index}" data-minutes-collection="action_items" data-minutes-index="${index}" data-minutes-prop="description">${escapeHtml(
                            action.description || ""
                          )}</textarea>
                        </div>
                        <div class="minutes-field">
                          <label for="action-due-date-${index}">Fällig am</label>
                          <input id="action-due-date-${index}" type="text" value="${escapeHtml(
                            action.due_date || ""
                          )}" placeholder="Optional" data-minutes-collection="action_items" data-minutes-index="${index}" data-minutes-prop="due_date" />
                        </div>
                        <div class="minutes-repeatable-item-actions">
                          <button class="ghost minutes-remove-btn" type="button" data-minutes-remove="action_items" data-minutes-index="${index}">Löschen</button>
                        </div>
                      </div>
                    `
                  )
                  .join("")
              : '<p class="hint">Noch keine Action Items vorhanden.</p>'
          }
        </section>
        <section class="minutes-section">
          <div class="minutes-field">
            <label for="minutesRisksInput">Risiken & offene Punkte</label>
            <textarea id="minutesRisksInput" data-minutes-field="risks" placeholder="Ein Punkt pro Zeile">${escapeHtml(
              (minutes.risks || []).join("\n")
            )}</textarea>
          </div>
        </section>
      </div>
    `;
    return;
  }

  minutesContainer.innerHTML = `
    <section class="minutes-section">
      <h3>Kurzzusammenfassung</h3>
      <p>${escapeHtml(minutes.summary || "Zusammenfassung folgt ...")}</p>
    </section>
    <section class="minutes-grid">
      <div class="minutes-section">
        <h3>Agenda</h3>
        ${renderList(minutes.agenda, "Keine Agenda gefunden.")}
      </div>
      <div class="minutes-section">
        <h3>Highlights</h3>
        ${renderList(minutes.highlights, "Noch keine Highlights extrahiert.")}
      </div>
    </section>
    <section class="minutes-grid">
      <div class="minutes-section">
        <h3>Entscheidungen</h3>
        ${renderDecisions(minutes.decisions)}
      </div>
      <div class="minutes-section">
        <h3>Action Items</h3>
        ${renderActions(minutes.action_items)}
      </div>
    </section>
    <section class="minutes-section">
      <h3>Risiken & offene Punkte</h3>
      ${renderList(minutes.risks, "Keine Risiken erkannt.")}
    </section>
  `;
};

minutesContainer?.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) || !minutesEditMode) {
    return;
  }
  const field = target.dataset.minutesField;
  if (field) {
    updateDraftMinutesField(field, target.value);
    return;
  }
  const collection = target.dataset.minutesCollection;
  const prop = target.dataset.minutesProp;
  const index = Number.parseInt(target.dataset.minutesIndex || "", 10);
  if (collection && prop && Number.isInteger(index)) {
    updateDraftMinutesItem(collection, index, prop, target.value);
  }
});

minutesContainer?.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if (target.id === "saveMinutesEditBtn") {
    saveDraftMinutes();
    return;
  }
  if (target.id === "cancelMinutesEditBtn") {
    cancelDraftMinutes();
    return;
  }
  const addCollection = target.dataset.minutesAdd;
  if (addCollection) {
    addDraftMinutesItem(addCollection);
    return;
  }
  const removeCollection = target.dataset.minutesRemove;
  const index = Number.parseInt(target.dataset.minutesIndex || "", 10);
  if (removeCollection && Number.isInteger(index)) {
    removeDraftMinutesItem(removeCollection, index);
  }
});


const resetWorkflow = () => {
  stopWorkflowTicker();
  workflowState = {
    activeKey: null,
    completed: false,
    actualStepDurationsMs: {},
    device: null,
    progressRatio: 0,
    startedAt: null,
    tickerId: null,
  };
  renderWorkflow();
};

const hasCompletedSpeakerDetection = () => transcriptHasSpeakerDetection;

const renderWorkflow = () => {
  if (!workflowStepsList || !progressFill || !progressLabel) {
    return;
  }
  const derivedActiveKey = workflowState.activeKey;
  const activeIndex = WORKFLOW_STEPS.findIndex((step) => step.key === derivedActiveKey);
  const derivedRatio = activeIndex >= 0 ? (activeIndex + 1) / WORKFLOW_STEPS.length : 0;
  const ratio = workflowState.completed ? 1 : Math.max(workflowState.progressRatio || 0, derivedRatio);
  progressFill.style.width = `${ratio * 100}%`;
  if (workflowState.completed) {
    progressLabel.textContent = workflowState.device
      ? `Abgeschlossen auf ${String(workflowState.device).toUpperCase()}`
      : "Verarbeitung abgeschlossen";
  } else if (activeIndex >= 0) {
    progressLabel.textContent = `${WORKFLOW_STEPS[activeIndex].label} läuft`;
  } else {
    progressLabel.textContent = "Bereit";
  }
  if (progressRuntime) {
    if (workflowState.startedAt && !workflowState.completed && activeIndex >= 0) {
      progressRuntime.textContent = `Verarbeitung läuft seit ${formatShortDuration(Date.now() - workflowState.startedAt)}`;
      progressRuntime.classList.remove("hidden");
    } else if (workflowState.completed && workflowState.startedAt) {
      progressRuntime.textContent = `Verarbeitung dauerte ${formatShortDuration(Date.now() - workflowState.startedAt)}`;
      progressRuntime.classList.remove("hidden");
    } else {
      progressRuntime.textContent = "";
      progressRuntime.classList.add("hidden");
    }
  }
  const visibleSteps = WORKFLOW_STEPS.filter(
    (step) => globalSpeakerRecognitionEnabled || step.key !== "diarize",
  );
  workflowStepsList.innerHTML = visibleSteps
    .map((step) => {
      const originalIndex = WORKFLOW_STEPS.findIndex((item) => item.key === step.key);
      let stateClass = "pending";
      if (step.key === "diarize" && !transcriptHasSpeakerDetection && !workflowState.activeKey) {
        stateClass = "disabled";
      } else if (
        workflowState.completed &&
        step.key === "diarize" &&
        !hasCompletedSpeakerDetection()
      ) {
        stateClass = "disabled";
      } else if (
        workflowState.completed ||
        (activeIndex >= 0 && originalIndex < activeIndex)
      ) {
        stateClass = "completed";
      } else if (originalIndex === activeIndex) {
        stateClass = "active";
      }
      let detail = "";
      if (workflowState.completed && step.key === "diarize" && !hasCompletedSpeakerDetection()) {
        detail = "Optional";
      } else if (originalIndex === activeIndex && workflowState.activeKey) {
        detail = "Läuft";
      } else if (stateClass === "disabled") {
        detail = "Optional";
      } else if (stateClass === "completed") {
        detail = "Erledigt";
      }
      return `
      <li class="workflow-step ${stateClass}">
        <span>${step.label}</span>
        <p>${detail}</p>
      </li>
    `;
    })
    .join("");
};

const stopRecording = () => {
  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    return false;
  }
  statusText.textContent = "Aufnahme wird gestoppt ...";
  setRecordButtonState({ recording: false, busy: true });
  mediaRecorder.stop();
  return true;
};

const startRecording = async () => {
  recordedChunks = [];
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  activeRecordingStream = stream;
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) {
      recordedChunks.push(event.data);
    }
  };
  mediaRecorder.onstart = () => {
    statusText.textContent = "Aufnahme läuft";
    recordingStartedAtUtc = new Date().toISOString();
    startTimer();
    setRecordButtonState({ recording: true, busy: false });
  };
  mediaRecorder.onstop = async () => {
    stopTimer();
    stopActiveRecordingTracks();
    setRecordButtonState({ recording: false, busy: true });
    const blob = new Blob(recordedChunks, { type: "audio/webm" });
    try {
      await uploadBlob(blob, "meeting.webm");
    } finally {
      setRecordButtonState({ recording: false, busy: false });
    }
  };
  mediaRecorder.start(1000);
};

recordBtn.addEventListener("click", async () => {
  if (!requireAuthentication()) {
    return;
  }
  if (recordBtn.disabled) {
    return;
  }
  if (stopRecording()) {
    return;
  }
  try {
    await startRecording();
  } catch (error) {
    console.error(error);
    stopTimer();
    stopActiveRecordingTracks();
    setRecordButtonState({ recording: false, busy: false });
    handleError("Mikrofonzugriff verweigert");
  }
});

stopBtn?.addEventListener("click", () => {
  stopRecording();
});

fileInput.addEventListener("change", async (event) => {
  if (!requireAuthentication()) {
    fileInput.value = "";
    return;
  }
  const file = event.target.files?.[0];
  if (!file) return;
  recordingStartedAtUtc = null;
  setRecordButtonState({ recording: false, busy: true });
  try {
    await uploadBlob(file, file.name);
  } finally {
    fileInput.value = "";
    setRecordButtonState({ recording: false, busy: false });
  }
});

refreshMeetingsBtn?.addEventListener("click", async () => {
  if (!requireAuthentication()) {
    return;
  }
  await fetchMeetings({ preserveSelection: true });
});

openTaskBoardBtn?.addEventListener("click", async () => {
  if (!TASK_BOARD_FEATURE_ENABLED) {
    return;
  }
  if (!requireAuthentication()) {
    return;
  }
  const shouldShow = taskBoardPanel ? taskBoardPanel.classList.contains("hidden") : true;
  setTaskBoardVisible(shouldShow);
  if (shouldShow) {
    await fetchTaskBoard();
    taskBoardPanel?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

cancelMeetingBtn?.addEventListener("click", async () => {
  if (!requireAuthentication()) {
    return;
  }
  if (!currentJobId) {
    return;
  }
  try {
    const response = await fetch(
      `${API_BASE}/api/transcribe/jobs/${currentJobId}/cancel`,
      withClientScope({ method: "POST" })
    );
    if (!response.ok) {
      let detail = `API Fehler ${response.status}`;
      try {
        const errorPayload = await response.json();
        detail = errorPayload?.detail || detail;
      } catch (_error) {
        // Ignore parse errors.
      }
      throw new Error(detail);
    }
    const job = await response.json();
    syncMeetingIntoCacheV2(job);
    applySelectedMeetingProgress(job);
    if (job.status === "cancelled") {
      stopAsyncJobPolling();
      statusText.textContent = "Verarbeitung gestoppt.";
    } else {
      statusText.textContent = job.message || "Stopp angefordert.";
    }
    showToast(job.message || "Verarbeitung wurde gestoppt.", { variant: "info" });
  } catch (error) {
    handleError(error?.message || "Meeting konnte nicht gestoppt werden.");
  }
});

deleteMeetingBtn?.addEventListener("click", async () => {
  if (!requireAuthentication()) {
    return;
  }
  if (!currentJobId) {
    return;
  }
  const meetingId = currentJobId;
  try {
    const response = await fetch(
      `${API_BASE}/api/transcribe/jobs/${meetingId}`,
      withClientScope({ method: "DELETE" })
    );
    if (!response.ok) {
      let detail = `API Fehler ${response.status}`;
      try {
        const errorPayload = await response.json();
        detail = errorPayload?.detail || detail;
      } catch (_error) {
        // Ignore parse errors.
      }
      throw new Error(detail);
    }
    meetingsCache = meetingsCache.filter((meeting) => meeting.job_id !== meetingId);
    if (currentJobId === meetingId) {
      currentJobId = null;
      currentSessionId = null;
      transcriptCache = [];
      minutesCache = null;
      draftMinutesCache = null;
      durationCache = 0;
      transcriptHasSpeakerDetection = false;
      stopAsyncJobPolling();
      resetWorkflow();
      renderTranscript();
      renderMinutes();
      renderSpeakerEditor();
      updateActionButtonsState();
    }
    persistSelectedMeetingId(null);
    renderMeetingsListV2();
    setSelectedMeetingHeaderV2(null);
    setAsyncJobStatus("", { hidden: true });
    showToast("Meeting wurde gelöscht.", { variant: "success" });
  } catch (error) {
    handleError(error?.message || "Meeting konnte nicht gelöscht werden.");
  }
});


transcriptSpeakerToggle?.addEventListener("change", (event) => {
  speakerDetectionEnabled = Boolean(event.target.checked);
  renderTranscript(transcriptCache);
  renderSpeakerEditor();
  updateSpeakerControlsState();
});

sendBtn?.addEventListener("click", () => {
  if (!hasMinutesData()) {
    return;
  }
  openRoomModal();
});

editMinutesBtn?.addEventListener("click", () => {
  if (!hasMinutesData() || minutesEditMode) {
    return;
  }
  setMinutesEditMode(true);
});

downloadBtn?.addEventListener("click", () => {
  downloadMinutes();
});

roomModalClose?.addEventListener("click", () => closeRoomModal());
roomModalCancel?.addEventListener("click", () => closeRoomModal());

roomModal?.addEventListener("click", (event) => {
  if (event.target === roomModal) {
    closeRoomModal();
  }
});

actionItemDraftModal?.addEventListener("click", (event) => {
  if (event.target === actionItemDraftModal) {
    closeActionItemDraftModal();
  }
});

actionItemNotifyList?.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }
  const index = Number.parseInt(target.dataset.actionItemEmailIndex || "", 10);
  if (!Number.isInteger(index) || !actionItemNotificationEntries[index]) {
    return;
  }
  actionItemNotificationEntries[index].recipient_email = target.value;
});

actionItemNotifyList?.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const explicitButton = target.closest("[data-action-item-draft-open]");
  if (explicitButton) {
    const index = explicitButton.getAttribute("data-action-item-draft-open");
    openActionItemDraftModal(index);
    return;
  }
  if (target.closest("input") || target.closest("button")) {
    return;
  }
  const row = target.closest("[data-action-item-entry-index]");
  if (!row) {
    return;
  }
  const index = row.getAttribute("data-action-item-entry-index");
  openActionItemDraftModal(index);
});

notifyActionItemsToggle?.addEventListener("change", () => {
  if (!hasMinutesData()) {
    return;
  }
  if (notifyActionItemsToggle.checked) {
    actionItemNotificationEntries = createActionItemNotificationEntries(minutesCache, {
      room: getSelectedRoom(),
      recorded_at: getRecordedAtTimestamp(),
      previousEntries: actionItemNotificationEntries,
    });
  }
  syncActionItemNotifyUi();
});

actionItemDraftClose?.addEventListener("click", () => closeActionItemDraftModal());
actionItemDraftCancel?.addEventListener("click", () => closeActionItemDraftModal());
actionItemDraftSave?.addEventListener("click", () => {
  if (!actionItemDraftText) {
    return;
  }
  if (
    !Number.isInteger(activeActionItemDraftIndex) ||
    !actionItemNotificationEntries[activeActionItemDraftIndex]
  ) {
    closeActionItemDraftModal();
    return;
  }
  actionItemNotificationEntries[activeActionItemDraftIndex].email_body = actionItemDraftText.value;
  closeActionItemDraftModal();
});

logoutBtn?.addEventListener("click", async () => {
  try {
    if (authToken) {
      await fetch(AUTH_LOGOUT_ENDPOINT, withClientScope({ method: "POST" }));
    }
  } catch (_error) {
    // Ignore logout transport errors.
  } finally {
    setAuthState({ token: "", user: null });
    meetingsCache = [];
    currentJobId = null;
    currentSessionId = null;
    transcriptCache = [];
    minutesCache = null;
    draftMinutesCache = null;
    durationCache = 0;
    resetUIV2();
    renderTranscript();
    renderMinutes();
    renderSpeakerEditor();
    renderMeetingsListV2();
    window.location.replace("login.html");
  }
});

profileMenuTrigger?.addEventListener("click", () => {
  if (!isAuthenticated()) {
    return;
  }
  setProfileMenuOpen(!profileMenuOpen);
});

meetingList?.addEventListener("click", async (event) => {
  if (!requireAuthentication()) {
    return;
  }
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const card = target.closest("[data-meeting-id]");
  const meetingId = card?.getAttribute("data-meeting-id");
  if (!meetingId || meetingId === currentJobId) {
    return;
  }
  await selectMeeting(meetingId, { loadFromServer: true });
});

meetingList?.addEventListener("keydown", async (event) => {
  if (!requireAuthentication()) {
    return;
  }
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const card = target.closest("[data-meeting-id]");
  const meetingId = card?.getAttribute("data-meeting-id");
  if (!meetingId || meetingId === currentJobId) {
    return;
  }
  event.preventDefault();
  await selectMeeting(meetingId, { loadFromServer: true });
});

if (typeof document !== "undefined") {
  document.addEventListener("click", (event) => {
    if (!profileMenuOpen || !profileMenu) {
      return;
    }
    const target = event.target;
    if (target instanceof Node && profileMenu.contains(target)) {
      return;
    }
    setProfileMenuOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeRoomModal();
      closeActionItemDraftModal();
      setProfileMenuOpen(false);
    }
  });
}

confirmSendBtn?.addEventListener("click", async () => {
  await sendMinutesToWebhook();
});

resetUIV2();
renderTranscript();
renderMinutes();
renderSpeakerEditor();
renderWorkflow();
updateSpeakerControlsState();
void checkApiAvailability();
void loadGlobalSpeakerRecognitionSetting();
void ensureAuthSession().then((active) => {
  if (!active) {
    window.location.replace("login.html");
    return;
  }
  updateAuthUi();
  void fetchMeetings({ preserveSelection: true });
  void startTaskBoardAutoRefresh();
});




