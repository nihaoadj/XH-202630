import type { AxiosResponse } from 'axios'
import type {
  CoursewareLearningEvent, CoursewareLearningEventAck, CoursewareJobCreateRequest, CoursewareBatchCreateRequest,
  CoursewareJobResponse, CoursewareBatchJobResponse, CoursewareJobListResponse, CoursewareJobDetail,
  CurrentReportResponse, ReportInvalidation, ReportWindowDays, PublicRunSnapshot, PublicRunEvent,
} from './generated/contracts'

export interface CoursewareApi {
  createJob(data: CoursewareJobCreateRequest): Promise<AxiosResponse<CoursewareJobResponse>>
  createJobs(data: CoursewareBatchCreateRequest): Promise<AxiosResponse<CoursewareBatchJobResponse>>
  listJobs(learnerId: string): Promise<AxiosResponse<CoursewareJobListResponse>>
  getJob(runId: string): Promise<AxiosResponse<CoursewareJobResponse>>
  getJobDetail(runId: string): Promise<AxiosResponse<CoursewareJobDetail>>
  eventsUrl(runId: string, afterSequence?: number): string
  retryJob(runId: string): Promise<AxiosResponse<CoursewareJobResponse>>
  retryScene(runId: string, sceneId: string): Promise<AxiosResponse<unknown>>
  getSceneReview(runId: string, sceneId: string): Promise<AxiosResponse<unknown>>
  get(resourceId: string): Promise<AxiosResponse<unknown>>
  previewUrl(resourceId: string, releaseId?: string): string
  downloadUrl(resourceId: string): string
  packageUrl(resourceId: string, format: string): string
  ingestLearningEvents(resourceId: string, events: CoursewareLearningEvent[]): Promise<AxiosResponse<CoursewareLearningEventAck>>
  learningProgress(resourceId: string, releaseId: string): Promise<AxiosResponse<unknown>>
}
export interface EventContext { account: string; resourceId: string; releaseId: string }
export interface QueueSnapshot {
  pending: CoursewareLearningEvent[]; blocked: number; unassigned: number; unsaved: number; error: string; lastSuccess: string | null
}
export interface EventQueuePort {
  error: string
  migrateLegacy(): Promise<void>
  snapshot(context: EventContext): Promise<QueueSnapshot>
  enqueue(account: string, event: CoursewareLearningEvent): Promise<boolean>
  acknowledge(context: EventContext, sent: CoursewareLearningEvent[], ids: string[]): Promise<number>
  quarantine(context: EventContext, events: CoursewareLearningEvent[], reason: string): Promise<void>
  retryPersistence(): Promise<void>
  close(): void
}
export interface SyncState {
  pending: number; blocked: number; unassigned: number; unsaved: number; sending: boolean; paused: boolean
  attempts: number; error: string; storageError: string; lastSuccess: string | null
}
export interface SenderOptions {
  queue: EventQueuePort
  send: (resourceId: string, events: CoursewareLearningEvent[]) => Promise<AxiosResponse<CoursewareLearningEventAck>>
  changed?: (state: SyncState) => void
  locks?: LockManager | null
  online?: () => boolean
  schedule?: (callback: () => void, delay: number) => number
  cancel?: (timer: number) => void
  broadcast?: BroadcastChannel | null
}
export type ReportHttpResponse = (AxiosResponse<CurrentReportResponse> & { status: 200 }) | (AxiosResponse<unknown> & { status: 304 })
export interface ReportContext { learnerId: string; windowDays: ReportWindowDays; revision?: string | null }
export interface ReportFetchRequest { learnerId: string; windowDays: ReportWindowDays; etag?: string | null }
export interface ReportSnapshot { data: CurrentReportResponse; revision: string }
// Earlier receive envelopes omit metadata, while identity/window/revision remain required.
export type ReportInvalidationInput = Pick<ReportInvalidation, 'learner_id' | 'window_days' | 'report_revision'>
export type RunSnapshotInput = Partial<PublicRunSnapshot> & { run_id?: string; status?: string }
export type RunEventInput = Partial<Omit<PublicRunEvent, 'payload'>> & { event_type: string; sequence?: number; event_sequence?: number; payload?: Record<string, unknown> }
export interface StreamError { code?: string; consecutive_errors?: number }
export interface RunClientOptions {
  runId: string; afterSequence?: number; maxConsecutiveErrors?: number
  onSnapshot?: (value: RunSnapshotInput) => void
  onWorkflowEvent?: (value: RunEventInput) => void
  onPing?: (value: unknown) => void
  onTerminal?: (value: RunEventInput | RunSnapshotInput) => void
  onError?: (value: StreamError) => void
  onFallback?: (value: StreamError) => void
}
