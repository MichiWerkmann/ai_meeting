from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from .defaults import MAX_LLM_CONTEXT_SIZE


class SpeakerProfile(BaseModel):
    speaker_id: str
    label: str


class MinutesDecision(BaseModel):
    title: str
    details: str


class MinutesActionItem(BaseModel):
    owner: str
    description: str
    due_date: str | None = None


class MinutesSection(BaseModel):
    title: str
    entries: List[str] = Field(default_factory=list)


class MeetingMinutes(BaseModel):
    summary: str = ""
    agenda: List[str] = Field(default_factory=list)
    highlights: List[str] = Field(default_factory=list)
    decisions: List[MinutesDecision] = Field(default_factory=list)
    action_items: List[MinutesActionItem] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    sections: List[MinutesSection] = Field(default_factory=list)
    model: str | None = None
    chunk_count: int = 0


class WebhookDeliveryStatus(BaseModel):
    delivered: bool = False
    url: str
    attempts: int = 0
    status_code: int | None = None
    detail: str = ""


class TranscriptSegment(BaseModel):
    speaker_id: str
    speaker: str
    start: float
    end: float
    text: str


class ProcessingStepTiming(BaseModel):
    key: str
    label: str
    duration_seconds: float = 0.0


class ProcessingMetadata(BaseModel):
    device: str | None = None
    total_seconds: float = 0.0
    steps: List[ProcessingStepTiming] = Field(default_factory=list)


class ManualSegment(BaseModel):
    speaker: str
    text: str
    start: float | None = None
    end: float | None = None


class TranscriptResponse(BaseModel):
    transcript: List[TranscriptSegment]
    summary: str
    duration_seconds: float
    minutes: MeetingMinutes
    speakers: List[SpeakerProfile] = Field(default_factory=list)
    processing: ProcessingMetadata | None = None
    session_id: str | None = None


class AsyncTranscriptionJobResponse(BaseModel):
    job_id: str
    meeting_name: str
    audio_filename: str
    status: str
    message: str = ""
    active_step: str | None = None
    progress_percent: float = 0.0
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    poll_after_ms: int = 1500
    estimated_audio_duration_seconds: float = 0.0
    queue_position: int | None = None
    result: TranscriptResponse | None = None


class AnalysisResponse(BaseModel):
    requested_outputs: List[str] = Field(default_factory=list)
    transcript: List[TranscriptSegment] | None = None
    summary: str | None = None
    minutes: MeetingMinutes | None = None
    speakers: List[SpeakerProfile] | None = None
    duration_seconds: float = 0.0
    processing: ProcessingMetadata | None = None
    session_id: str | None = None


class SegmentPrediction(BaseModel):
    row_index: int
    label: str
    rationale: str | None = None


class MinutesEvaluationRequest(BaseModel):
    segments: List[ManualSegment]


class MinutesEvaluationResponse(BaseModel):
    minutes: MeetingMinutes
    predictions: List[SegmentPrediction]


class ActionItemNotificationStatus(BaseModel):
    owner: str
    action_item_description: str | None = None
    recipient_email: str | None = None
    action_items_count: int = 0
    delivered: bool = False
    detail: str = ""


class ActionItemNotificationOverride(BaseModel):
    owner: str
    action_item_description: str
    recipient_email: str | None = None
    email_body: str | None = None


class MeetingSubmitResponse(BaseModel):
    room: str
    recorded_at: str
    minutes: MeetingMinutes
    webhook: WebhookDeliveryStatus
    action_item_notifications: List[ActionItemNotificationStatus] = Field(default_factory=list)


class TaskBoardEntry(BaseModel):
    id: str
    meeting_key: str
    meeting_name: str
    room: str
    recorded_at: str
    minutes_summary: str = ""
    task_owner: str
    task_description: str
    due_date: str | None = None
    email_requested: bool = False
    email_sent: bool = False
    email_status: str = "not_requested"
    recipient_email: str | None = None
    email_detail: str = ""
    updated_at: float


class RepeatedTaskInsight(BaseModel):
    task_description: str
    occurrences: int = 0
    meetings: int = 0
    owners: List[str] = Field(default_factory=list)


class OwnerWorkloadInsight(BaseModel):
    owner: str
    tasks: int = 0
    sent_emails: int = 0
    failed_emails: int = 0


class SimilarMeetingInsight(BaseModel):
    left_meeting_key: str
    left_meeting_name: str
    right_meeting_key: str
    right_meeting_name: str
    similarity_score: float = 0.0
    common_keywords: List[str] = Field(default_factory=list)


class TaskBoardAnalytics(BaseModel):
    total_tasks: int = 0
    total_meetings: int = 0
    emailed_tasks: int = 0
    failed_emails: int = 0
    repeated_tasks: List[RepeatedTaskInsight] = Field(default_factory=list)
    owner_workload: List[OwnerWorkloadInsight] = Field(default_factory=list)
    similar_meetings: List[SimilarMeetingInsight] = Field(default_factory=list)


class TaskBoardResponse(BaseModel):
    entries: List[TaskBoardEntry] = Field(default_factory=list)
    analytics: TaskBoardAnalytics = Field(default_factory=TaskBoardAnalytics)


class MeetingForwardRequest(BaseModel):
    room: str = "unknown"
    meeting_name: str | None = None
    meeting_key: str | None = None
    recorded_at: str | None = None
    duration_seconds: float | None = None
    notify_action_items: bool = True
    action_item_notification_overrides: List[ActionItemNotificationOverride] = Field(default_factory=list)
    minutes: MeetingMinutes


class HealthResponse(BaseModel):
    status: str
    transcription_provider: str = "local"
    whisper_model: str | None = None
    diarization_model: str | None = None
    summary_model: str | None = None
    llm_model: str | None = None
    device: str | None = None
    gpu_available: bool = False
    gpu_memory_gb: float = 0.0
    performance_tier: str = "unknown"
    recommended_execution: str = "local"
    performance_message: str = ""


class ModelSettings(BaseModel):
    execution_device: str = "auto"
    transcription_provider: str = "local"
    whisper_model: str = "turbo"
    speaker_recognition_enabled: bool = True
    send_enabled: bool = True
    diarization_model: str = "auto"
    azure_transcription_endpoint: str = ""
    azure_transcription_api_key: str = ""
    azure_transcription_api_version: str = "2024-02-01"
    azure_transcription_deployment: str = ""
    azure_speech_endpoint: str = ""
    azure_speech_region: str = ""
    azure_speech_api_version: str = "2024-11-15"
    azure_speech_locales: str = ""
    azure_speech_max_speakers: int | None = None
    llm_provider: str = "azure_openai"
    llm_model: str = "gpt-4.1-mini"
    llm_azure_endpoint: str = "https://modelle-michi.openai.azure.com"
    llm_azure_api_key: str = ""
    llm_azure_api_version: str = "2025-01-01-preview"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_completions_path: str = "/v1/chat/completions"
    llm_local_model_path: str = ""
    llm_local_context_size: int = MAX_LLM_CONTEXT_SIZE
    llm_local_gpu_layers: int = 0
    summary_model: str = "gpt-4.1-mini"
    summary_llm_base_url: str = ""
    summary_llm_api_key: str = ""
    summary_llm_completions_path: str = ""


class ModelSettingsUpdate(BaseModel):
    execution_device: str | None = None
    transcription_provider: str | None = None
    whisper_model: str | None = None
    speaker_recognition_enabled: bool | None = None
    send_enabled: bool | None = None
    diarization_model: str | None = None
    azure_transcription_endpoint: str | None = None
    azure_transcription_api_key: str | None = None
    azure_transcription_api_version: str | None = None
    azure_transcription_deployment: str | None = None
    azure_speech_endpoint: str | None = None
    azure_speech_region: str | None = None
    azure_speech_api_version: str | None = None
    azure_speech_locales: str | None = None
    azure_speech_max_speakers: int | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_azure_endpoint: str | None = None
    llm_azure_api_key: str | None = None
    llm_azure_api_version: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_completions_path: str | None = None
    llm_local_model_path: str | None = None
    llm_local_context_size: int | None = None
    llm_local_gpu_layers: int | None = None
    summary_model: str | None = None
    summary_llm_base_url: str | None = None
    summary_llm_api_key: str | None = None
    summary_llm_completions_path: str | None = None


class ModelDownloadRequest(BaseModel):
    model_id: str = "gemma3_4b_gguf"


class ModelDownloadResponse(BaseModel):
    model_id: str
    state: str = "idle"
    provider: str
    llm_model: str
    llm_local_model_path: str
    bytes_downloaded: int = 0
    total_bytes: int = 0
    downloaded: bool = False
    message: str = ""


class AuthRegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthenticatedUser(BaseModel):
    id: str
    name: str
    email: str
    created_at: float
    last_login_at: float | None = None


class AuthSessionResponse(BaseModel):
    token: str
    user: AuthenticatedUser
