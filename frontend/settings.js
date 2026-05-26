const toast = document.getElementById("toast");
const modelSettingsForm = document.getElementById("modelSettingsForm");
const settingsStatus = document.getElementById("settingsStatus");
const reloadSettingsBtn = document.getElementById("reloadSettingsBtn");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");
const executionDeviceInput = document.getElementById("executionDeviceInput");
const transcriptionProviderInput = document.getElementById("transcriptionProviderInput");
const whisperModelInput = document.getElementById("whisperModelInput");
const speakerRecognitionEnabledInput = document.getElementById("speakerRecognitionEnabledInput");
const sendEnabledInput = document.getElementById("sendEnabledInput");
const diarizationModelInput = document.getElementById("diarizationModelInput");
const azureTranscriptionEndpointInput = document.getElementById("azureTranscriptionEndpointInput");
const azureTranscriptionDeploymentInput = document.getElementById("azureTranscriptionDeploymentInput");
const azureTranscriptionApiVersionInput = document.getElementById("azureTranscriptionApiVersionInput");
const azureTranscriptionApiKeyInput = document.getElementById("azureTranscriptionApiKeyInput");
const azureSpeechEndpointInput = document.getElementById("azureSpeechEndpointInput");
const azureSpeechRegionInput = document.getElementById("azureSpeechRegionInput");
const azureSpeechLocalesInput = document.getElementById("azureSpeechLocalesInput");
const azureSpeechMaxSpeakersInput = document.getElementById("azureSpeechMaxSpeakersInput");
const azureSpeechApiVersionInput = document.getElementById("azureSpeechApiVersionInput");
const azureSpeechApiKeyInput = document.getElementById("azureSpeechApiKeyInput");
const llmProviderInput = document.getElementById("llmProviderInput");
const llmModelInput = document.getElementById("llmModelInput");
const summaryModelInput = document.getElementById("summaryModelInput");
const llmAzureEndpointInput = document.getElementById("llmAzureEndpointInput");
const llmAzureApiVersionInput = document.getElementById("llmAzureApiVersionInput");
const llmAzureApiKeyInput = document.getElementById("llmAzureApiKeyInput");
const llmBaseUrlInput = document.getElementById("llmBaseUrlInput");
const summaryLlmBaseUrlInput = document.getElementById("summaryLlmBaseUrlInput");
const llmCompletionsPathInput = document.getElementById("llmCompletionsPathInput");
const summaryLlmCompletionsPathInput = document.getElementById("summaryLlmCompletionsPathInput");
const llmApiKeyInput = document.getElementById("llmApiKeyInput");
const summaryLlmApiKeyInput = document.getElementById("summaryLlmApiKeyInput");
const azureTranscriptionFields = document.getElementById("azureTranscriptionFields");
const azureSpeechFields = document.getElementById("azureSpeechFields");
const azureLlmFields = document.getElementById("azureLlmFields");
const httpLlmFields = document.getElementById("httpLlmFields");
const hardwareBadge = document.getElementById("hardwareBadge");
const hardwareDeviceValue = document.getElementById("hardwareDeviceValue");
const hardwareMemoryValue = document.getElementById("hardwareMemoryValue");
const hardwareRecommendationValue = document.getElementById("hardwareRecommendationValue");
const hardwareMessage = document.getElementById("hardwareMessage");

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
const MODEL_SETTINGS_API = `${API_BASE}/api/settings/models`;
const HEALTH_API = `${API_BASE}/health`;

let toastTimeoutId = null;

const setSettingsBusy = (busy) => {
  if (reloadSettingsBtn) {
    reloadSettingsBtn.disabled = busy;
  }
  if (saveSettingsBtn) {
    saveSettingsBtn.disabled = busy;
  }
};

const setSettingsStatus = (message) => {
  if (settingsStatus) {
    settingsStatus.textContent = message;
  }
};

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

const showToast = (message, { variant = "info", duration = 2400 } = {}) => {
  if (!toast) {
    return;
  }
  if (toastTimeoutId) {
    clearTimeout(toastTimeoutId);
    toastTimeoutId = null;
  }
  toast.textContent = message;
  toast.classList.remove("hidden", "toast-success", "toast-error", "toast-info");
  const variantClass =
    variant === "error" ? "toast-error" : variant === "success" ? "toast-success" : "toast-info";
  toast.classList.add(variantClass);
  toastTimeoutId = window.setTimeout(() => {
    hideToast();
  }, duration);
};

const readErrorMessage = async (response, fallback) => {
  try {
    const payload = await response.json();
    return payload?.detail || fallback;
  } catch (_error) {
    return fallback;
  }
};

const setHardwareBadge = (tier, text) => {
  if (!hardwareBadge) {
    return;
  }
  hardwareBadge.textContent = text;
  hardwareBadge.classList.remove(
    "hardware-badge-high",
    "hardware-badge-medium",
    "hardware-badge-low",
    "hardware-badge-neutral"
  );
  const className =
    tier === "high"
      ? "hardware-badge-high"
      : tier === "medium"
      ? "hardware-badge-medium"
      : tier === "low"
      ? "hardware-badge-low"
      : "hardware-badge-neutral";
  hardwareBadge.classList.add(className);
};

const renderHardwareProfile = (health = {}) => {
  const device = String(health.device || "unbekannt").toUpperCase();
  const gpuAvailable = Boolean(health.gpu_available);
  const memory = gpuAvailable ? `${Number(health.gpu_memory_gb || 0).toFixed(1)} GB` : "keine CUDA-GPU";
  const recommendedExecution = health.recommended_execution === "api" ? "API empfohlen" : "Lokal empfohlen";
  const tier = String(health.performance_tier || "unknown");
  const badgeText =
    tier === "high"
      ? "Starke Hardware"
      : tier === "medium"
      ? "Solide Hardware"
      : tier === "low"
      ? "Begrenzte Hardware"
      : "Unbekannt";

  if (hardwareDeviceValue) {
    hardwareDeviceValue.textContent = device;
  }
  if (hardwareMemoryValue) {
    hardwareMemoryValue.textContent = memory;
  }
  if (hardwareRecommendationValue) {
    hardwareRecommendationValue.textContent = recommendedExecution;
  }
  if (hardwareMessage) {
    hardwareMessage.textContent =
      health.performance_message || "Keine Performance-Einschätzung verfügbar.";
  }
  setHardwareBadge(tier, badgeText);
};

const updateProviderUi = () => {
  const transcriptionProvider = transcriptionProviderInput?.value || "local";
  const useAzureTranscription = transcriptionProvider === "azure_openai";
  const useAzureSpeech = transcriptionProvider === "azure_speech";
  const provider = llmProviderInput?.value || "http";
  const useAzureLlm = provider === "azure_openai";
  const useHttpLlm = provider === "http";
  const speakerRecognitionEnabled = speakerRecognitionEnabledInput
    ? Boolean(speakerRecognitionEnabledInput.checked)
    : true;
  if (diarizationModelInput) {
    diarizationModelInput.disabled = !speakerRecognitionEnabled;
  }
  if (azureSpeechMaxSpeakersInput) {
    azureSpeechMaxSpeakersInput.disabled = !speakerRecognitionEnabled || !useAzureSpeech;
  }
  azureTranscriptionFields?.classList.toggle("hidden", !useAzureTranscription);
  azureSpeechFields?.classList.toggle("hidden", !useAzureSpeech);
  azureLlmFields?.classList.toggle("hidden", !useAzureLlm);
  httpLlmFields?.classList.toggle("hidden", !useHttpLlm);

  document.getElementById("whisperModelField")?.classList.toggle("hidden", useAzureSpeech);
  document.getElementById("diarizationModelField")?.classList.toggle("hidden", useAzureSpeech);

  [whisperModelInput, executionDeviceInput].forEach((element) => {
    if (element) {
      element.disabled = useAzureTranscription || useAzureSpeech;
    }
  });
  if (diarizationModelInput) {
    diarizationModelInput.disabled =
      !speakerRecognitionEnabled || useAzureTranscription || useAzureSpeech;
  }

  [
    azureTranscriptionEndpointInput,
    azureTranscriptionDeploymentInput,
    azureTranscriptionApiVersionInput,
    azureTranscriptionApiKeyInput,
  ].forEach((element) => {
    if (element) {
      element.disabled = !useAzureTranscription;
    }
  });

  [
    azureSpeechEndpointInput,
    azureSpeechRegionInput,
    azureSpeechLocalesInput,
    azureSpeechApiVersionInput,
    azureSpeechApiKeyInput,
  ].forEach((element) => {
    if (element) {
      element.disabled = !useAzureSpeech;
    }
  });
  if (azureSpeechMaxSpeakersInput) {
    azureSpeechMaxSpeakersInput.disabled = !useAzureSpeech || !speakerRecognitionEnabled;
  }

  [llmAzureEndpointInput, llmAzureApiVersionInput, llmAzureApiKeyInput].forEach((element) => {
    if (element) {
      element.disabled = !useAzureLlm;
    }
  });

  [
    llmBaseUrlInput,
    summaryLlmBaseUrlInput,
    llmCompletionsPathInput,
    summaryLlmCompletionsPathInput,
    llmApiKeyInput,
    summaryLlmApiKeyInput,
  ].forEach((element) => {
    if (element) {
      element.disabled = !useHttpLlm;
    }
  });
};

const loadHardwareProfile = async ({ silent = false } = {}) => {
  try {
    const response = await fetch(HEALTH_API);
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, `API Fehler ${response.status}`));
    }
    const payload = await response.json();
    renderHardwareProfile(payload);
    return payload;
  } catch (error) {
    console.error(error);
    renderHardwareProfile({
      device: "unbekannt",
      gpu_available: false,
      gpu_memory_gb: 0,
      performance_tier: "unknown",
      recommended_execution: "local",
      performance_message: "Hardwareprofil konnte nicht geladen werden.",
    });
    if (!silent) {
      showToast("Hardwareprofil konnte nicht geladen werden.", { variant: "error" });
    }
    return null;
  }
};

const populateModelSettingsForm = (settings = {}) => {
  if (executionDeviceInput) executionDeviceInput.value = settings.execution_device || "auto";
  if (transcriptionProviderInput) transcriptionProviderInput.value = settings.transcription_provider || "local";
  if (whisperModelInput) whisperModelInput.value = settings.whisper_model || "turbo";
  if (speakerRecognitionEnabledInput) {
    speakerRecognitionEnabledInput.checked =
      settings.speaker_recognition_enabled === undefined
        ? true
        : Boolean(settings.speaker_recognition_enabled);
  }
  if (sendEnabledInput) {
    sendEnabledInput.checked =
      settings.send_enabled === undefined
        ? true
        : Boolean(settings.send_enabled);
  }
  if (diarizationModelInput) diarizationModelInput.value = settings.diarization_model || "";
  if (azureTranscriptionEndpointInput) azureTranscriptionEndpointInput.value = settings.azure_transcription_endpoint || "";
  if (azureTranscriptionDeploymentInput) azureTranscriptionDeploymentInput.value = settings.azure_transcription_deployment || "";
  if (azureTranscriptionApiVersionInput) azureTranscriptionApiVersionInput.value = settings.azure_transcription_api_version || "2024-02-01";
  if (azureTranscriptionApiKeyInput) azureTranscriptionApiKeyInput.value = settings.azure_transcription_api_key || "";
  if (azureSpeechEndpointInput) azureSpeechEndpointInput.value = settings.azure_speech_endpoint || "";
  if (azureSpeechRegionInput) azureSpeechRegionInput.value = settings.azure_speech_region || "";
  if (azureSpeechLocalesInput) azureSpeechLocalesInput.value = settings.azure_speech_locales || "";
  if (azureSpeechMaxSpeakersInput) {
    azureSpeechMaxSpeakersInput.value = settings.azure_speech_max_speakers ?? "";
  }
  if (azureSpeechApiVersionInput) {
    azureSpeechApiVersionInput.value = settings.azure_speech_api_version || settings.azure_transcription_api_version || "2024-11-15";
  }
  if (azureSpeechApiKeyInput) {
    azureSpeechApiKeyInput.value = settings.azure_transcription_api_key || "";
  }
  if (llmProviderInput) llmProviderInput.value = settings.llm_provider || "azure_openai";
  if (llmModelInput) llmModelInput.value = settings.llm_model || "gpt-4.1-mini";
  if (summaryModelInput) summaryModelInput.value = settings.summary_model || "gpt-4.1-mini";
  if (llmAzureEndpointInput) llmAzureEndpointInput.value = settings.llm_azure_endpoint || "https://modelle-michi.openai.azure.com";
  if (llmAzureApiVersionInput) llmAzureApiVersionInput.value = settings.llm_azure_api_version || "2025-01-01-preview";
  if (llmAzureApiKeyInput) llmAzureApiKeyInput.value = settings.llm_azure_api_key || "";
  if (llmBaseUrlInput) llmBaseUrlInput.value = settings.llm_base_url || "";
  if (summaryLlmBaseUrlInput) summaryLlmBaseUrlInput.value = settings.summary_llm_base_url || "";
  if (llmCompletionsPathInput) llmCompletionsPathInput.value = settings.llm_completions_path || "";
  if (summaryLlmCompletionsPathInput) summaryLlmCompletionsPathInput.value = settings.summary_llm_completions_path || "";
  if (llmApiKeyInput) llmApiKeyInput.value = settings.llm_api_key || "";
  if (summaryLlmApiKeyInput) summaryLlmApiKeyInput.value = settings.summary_llm_api_key || "";
  updateProviderUi();
};

const collectModelSettingsPayload = () => ({
  execution_device: executionDeviceInput?.value?.trim() || "auto",
  transcription_provider: transcriptionProviderInput?.value || "local",
  whisper_model: whisperModelInput?.value?.trim() || "auto",
  speaker_recognition_enabled: speakerRecognitionEnabledInput
    ? Boolean(speakerRecognitionEnabledInput.checked)
    : true,
  send_enabled: sendEnabledInput
    ? Boolean(sendEnabledInput.checked)
    : true,
  diarization_model: diarizationModelInput?.value?.trim() || "auto",
  azure_transcription_endpoint: azureTranscriptionEndpointInput?.value?.trim() || "",
  azure_transcription_api_key:
    (transcriptionProviderInput?.value || "local") === "azure_speech"
      ? azureSpeechApiKeyInput?.value || ""
      : azureTranscriptionApiKeyInput?.value || "",
  azure_transcription_api_version: azureTranscriptionApiVersionInput?.value?.trim() || "2024-02-01",
  azure_speech_api_version: azureSpeechApiVersionInput?.value?.trim() || "2024-11-15",
  azure_transcription_deployment: azureTranscriptionDeploymentInput?.value?.trim() || "",
  azure_speech_endpoint: azureSpeechEndpointInput?.value?.trim() || "",
  azure_speech_region: azureSpeechRegionInput?.value?.trim() || "",
  azure_speech_locales: azureSpeechLocalesInput?.value?.trim() || "",
  azure_speech_max_speakers:
    Number.parseInt(azureSpeechMaxSpeakersInput?.value || "", 10) || null,
  llm_provider: llmProviderInput?.value || "azure_openai",
  llm_model: llmModelInput?.value?.trim() || "gpt-4.1-mini",
  llm_azure_endpoint: llmAzureEndpointInput?.value?.trim() || "https://modelle-michi.openai.azure.com",
  llm_azure_api_key: llmAzureApiKeyInput?.value || "",
  llm_azure_api_version: llmAzureApiVersionInput?.value?.trim() || "2025-01-01-preview",
  llm_base_url: llmBaseUrlInput?.value?.trim() || "",
  llm_api_key: llmApiKeyInput?.value || "",
  llm_completions_path: llmCompletionsPathInput?.value?.trim() || "",
  summary_model: summaryModelInput?.value?.trim() || "gpt-4.1-mini",
  summary_llm_base_url: summaryLlmBaseUrlInput?.value?.trim() || "",
  summary_llm_api_key: summaryLlmApiKeyInput?.value || "",
  summary_llm_completions_path: summaryLlmCompletionsPathInput?.value?.trim() || "",
});

const loadModelSettings = async ({ silent = false } = {}) => {
  if (!modelSettingsForm) {
    return null;
  }
  if (!silent) {
    setSettingsStatus("Lade aktuelle Modellkonfiguration ...");
  }
  setSettingsBusy(true);
  try {
    const response = await fetch(MODEL_SETTINGS_API);
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, `API Fehler ${response.status}`));
    }
    const payload = await response.json();
    populateModelSettingsForm(payload);
    setSettingsStatus("Modellkonfiguration geladen.");
    return payload;
  } catch (error) {
    console.error(error);
    setSettingsStatus(error?.message || "Modellkonfiguration konnte nicht geladen werden.");
    if (!silent) {
      showToast("Modellkonfiguration konnte nicht geladen werden.", { variant: "error" });
    }
    return null;
  } finally {
    setSettingsBusy(false);
  }
};

const saveModelSettings = async (event) => {
  event?.preventDefault?.();
  if (!modelSettingsForm) {
    return;
  }
  setSettingsStatus("Speichere Modellkonfiguration ...");
  setSettingsBusy(true);
  try {
    const response = await fetch(MODEL_SETTINGS_API, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(collectModelSettingsPayload()),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, `API Fehler ${response.status}`));
    }
    const payload = await response.json();
    populateModelSettingsForm(payload);
    setSettingsStatus("Modellkonfiguration gespeichert. Neue Analysen nutzen die aktualisierten Werte.");
    showToast("Modelleinstellungen gespeichert.", { variant: "success" });
    await loadHardwareProfile({ silent: true });
  } catch (error) {
    console.error(error);
    setSettingsStatus(error?.message || "Modellkonfiguration konnte nicht gespeichert werden.");
    showToast(error?.message || "Modellkonfiguration konnte nicht gespeichert werden.", {
      variant: "error",
      duration: 3600,
    });
  } finally {
    setSettingsBusy(false);
  }
};

reloadSettingsBtn?.addEventListener("click", async () => {
  await loadHardwareProfile();
  await loadModelSettings();
});

llmProviderInput?.addEventListener("change", () => {
  updateProviderUi();
});

transcriptionProviderInput?.addEventListener("change", () => {
  updateProviderUi();
});

speakerRecognitionEnabledInput?.addEventListener("change", () => {
  updateProviderUi();
});

modelSettingsForm?.addEventListener("submit", async (event) => {
  await saveModelSettings(event);
});

updateProviderUi();
loadHardwareProfile({ silent: true });
loadModelSettings({ silent: true });

// ─── Theme selector ───────────────────────────────────────────────────────

const themeSelect = document.getElementById("themeSelect");
if (themeSelect) {
  const cfgTheme = (window.__APP_CONFIG__ || {}).UI_THEME || "aurora";
  themeSelect.value = cfgTheme || localStorage.getItem("app-theme") || "aurora";
  themeSelect.addEventListener("change", function () {
    const theme = this.value;
    localStorage.setItem("app-theme", theme);
    document.documentElement.dataset.theme = theme;
    document.title = theme === "meetingai" ? "Meeting AI Einstellungen" : "Aurora Minutes Einstellungen";
    showToast(
      theme === "meetingai" ? "Design: Meeting AI aktiviert." : "Design: Aurora aktiviert.",
      { variant: "success", duration: 2000 }
    );
  });
}
