<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { checked, display, errorMessage, languages, locale, m, t } from './i18n'
import type { BridgeResult, Language, Locale, Message } from './i18n'
import { version as appVersion } from '../package.json'
import ContextOptions from './ContextOptions.vue'
import { contextInputLimit, defaultContext, unicodeLength } from './contextOptions'
import type { AnalysisContext, BindingCandidate, ContextStats, SelectionBinding, SelectionMode } from './contextOptions'
import ReplyPreferencesFields from './ReplyPreferences.vue'
import { defaultReplyPreferences } from './replyPreferences'
import type { ReplyPreferences } from './replyPreferences'
import {
  ArrowLeft, ArrowRight, Bot, Check, CheckCircle2, ChevronDown, ChevronRight,
  CircleHelp, Copy, Cpu, Download, Eye, EyeOff, KeyRound, LoaderCircle,
  LockKeyhole, MessageCircle, Plus, RefreshCw, RotateCw, Save,
  Settings2, ShieldCheck, Sparkles, Trash2, X,
} from '@lucide/vue'

type ProviderPreset = { id: string; name: string; base_url: string; protocol: string; default_model: string; models: string[]; key_site: string; local: boolean }
type Profile = {
  id: string; name: string; base_url: string; model: string; max_tokens: number | null
  key_configured?: boolean; key_required?: boolean; api_key?: string; protocol: string
}
type Suggestion = { text: string; probability: number | null; confidence: number | null; recommended: boolean }
type RetryStage = 'capture' | 'judge' | 'generate' | 'rank'
type AnalysisResult = BridgeResult & { task_id?: string }
type UiState = {
  language: Language; resolved_language: Locale; status_message?: Message; error_message?: Message;
  revision: number; status: string; phase: string; preview: { side: string; text: string }[]
  analysis: Record<string, any> | null; suggestions: Suggestion[]; error: string
  selection_mode?: SelectionMode; selection_binding?: SelectionBinding; selection_revision?: number
  context_stats?: ContextStats | null
  version: string; chat_rect: Record<string, number> | null; jev_key_configured: boolean
  relationship: string; allowed_titles: string[]; profiles: Profile[]; active_model_id: string
  provider_presets?: ProviderPreset[]; update_info?: UpdateInfo | null
  reply_preferences: ReplyPreferences; task_id: string | null; input_source: 'desktop' | 'text' | null
  failed_stage: RetryStage | null; retryable_stages: RetryStage[]
}
type UpdateInfo = {
  update_available: boolean; latest_version: string; current_version: string;
  download_url: string; size: number; sha256?: string
}
type SelectionState = {
  selection_mode: SelectionMode; selection_binding: SelectionBinding
  selection_revision: number; chat_rect: UiState['chat_rect']
}
type Progress = { revision: number } & Partial<Pick<UiState, 'status' | 'phase' | 'preview' | 'analysis' | 'suggestions' | 'error' | 'status_message' | 'error_message' | 'update_info' | 'task_id' | 'input_source' | 'failed_stage' | 'retryable_stages' | 'context_stats' | 'selection_mode' | 'selection_binding' | 'selection_revision' | 'chat_rect'>>
type Bridge = {
  set_language(language: Language): Promise<BridgeResult & { language: Language; resolved_language: Locale }>
  get_state(): Promise<UiState>
  get_progress(knownRevision: number): Promise<Progress>
  fetch_models(payload: string): Promise<BridgeResult & { models: string[] }>
  test_model(payload: string): Promise<BridgeResult & { message: string; message_message?: Message }>
  save_settings(payload: string): Promise<UiState & BridgeResult>
  start_calibration(mode?: SelectionMode): Promise<BridgeResult>
  get_selection_state?(): Promise<SelectionState>
  set_selection_mode?(mode: SelectionMode): Promise<BridgeResult>
  get_binding_candidates?(): Promise<BridgeResult & { candidates: BindingCandidate[] }>
  confirm_binding?(id: string): Promise<BridgeResult>
  analyze(preferences?: Partial<ReplyPreferences>, context?: AnalysisContext): Promise<AnalysisResult>
  analyze_text(payload: { text: string; preferences: ReplyPreferences; context: AnalysisContext }): Promise<AnalysisResult>
  cancel_analysis(taskId: string): Promise<BridgeResult>
  retry_analysis(taskId: string, stage: RetryStage): Promise<AnalysisResult>
  set_on_top(value: boolean): Promise<{ ok: boolean }>
  set_active_model(profileId: string): Promise<BridgeResult>
  copy_text(value: string): Promise<BridgeResult>
  check_for_updates(): Promise<BridgeResult & UpdateInfo>
  download_update(): Promise<BridgeResult>
  cancel_update(): Promise<BridgeResult>
  apply_update(): Promise<BridgeResult>
}
declare global { interface Window { pywebview?: { api: Bridge } } }

const bridge = () => window.pywebview?.api
const initial: UiState = {
  language: 'system', resolved_language: 'zh-CN', status_message: m('status.initial'),
  revision: 0, status: '', phase: 'idle', preview: [], analysis: null,
  suggestions: [], error: '', version: appVersion, chat_rect: null, jev_key_configured: false,
  relationship: '对方是我的朋友；from=me 是我发的，from=other 是对方发的', allowed_titles: [],
  profiles: [], active_model_id: '',
  reply_preferences: { ...defaultReplyPreferences }, task_id: null, input_source: null,
  failed_stage: null, retryable_stages: [],
}
const state = reactive<UiState>({ ...initial })
const page = ref<'home' | 'settings'>('home')
const showModel = ref(false)
const pendingDelete = ref<Profile | null>(null)
const languageBusy = ref(false)
const editingId = ref('')
const busy = ref(false)
const inputSource = ref<'desktop' | 'text'>('desktop')
const textInput = ref('')
const context = ref<AnalysisContext>({ ...defaultContext })
const contextTooLong = computed(() => unicodeLength(context.value.prior_text) > contextInputLimit || unicodeLength(context.value.background) > contextInputLimit)
const bindingBusy = ref(false)
const showBinding = ref(false)
const bindingCandidates = ref<BindingCandidate[]>([])
const selectedBindingId = ref('')
let selectionRevision: number | undefined
const selectionMode = computed<SelectionMode>(() => state.selection_mode ?? (state.chat_rect ? 'screen' : 'window'))
const bindingStatus = computed(() => state.selection_binding?.status ?? 'none')
const fixedRectValid = computed(() => !!state.chat_rect)
const desktopReady = computed(() => selectionMode.value === 'window' ? bindingStatus.value === 'bound' : fixedRectValid.value)
const bindingStatusText = computed(() => selectionMode.value === 'screen'
  ? t(fixedRectValid.value ? 'capture.ready' : 'binding.fixedRequired')
  : bindingStatus.value === 'bound'
    ? t('binding.bound', { name: state.selection_binding?.display_name ?? '' })
    : t(`binding.${bindingStatus.value === 'needs_confirmation' ? 'needsConfirmation' : bindingStatus.value}`))
const textLimit = 20_000
const textCount = computed(() => Array.from(textInput.value).length)
const textTooLong = computed(() => textCount.value > textLimit)
const analysisBusy = ref(false)
const cancelBusy = ref(false)
const calibrationBusy = ref(false)
const activeModelBusy = ref(false)
const temporaryEnabled = ref(false)
const temporaryOpen = ref(false)
// Session-only overrides survive navigation and subsequent runs, without saving settings.
const temporaryOverrides = ref<Partial<ReplyPreferences>>({})
const effectivePreferences = computed<ReplyPreferences>(() => ({ ...state.reply_preferences, ...temporaryOverrides.value }))
const analysisRunning = computed(() => ['capturing', 'recognizing', 'judging', 'generating', 'ranking'].includes(state.phase))
const operationsLocked = computed(() => bindingBusy.value || showBinding.value || analysisRunning.value || state.phase === 'calibrating' || analysisBusy.value || calibrationBusy.value || cancelBusy.value || activeModelBusy.value || busy.value || languageBusy.value || updateBusy.value || updateChecking.value || updateRunning.value || updateReady.value)
const canAnalyze = computed(() => !operationsLocked.value && !contextTooLong.value && (inputSource.value === 'text'
  ? !!textInput.value.trim() && !textTooLong.value : desktopReady.value))
const stageLabels = computed<Record<RetryStage, string>>(() => ({
  capture: t('feature.stageCapture'), judge: t('feature.stageJudge'),
  generate: t('feature.stageGenerate'), rank: t('feature.stageRank'),
}))
const retryStages = computed(() => (['capture', 'judge', 'generate', 'rank'] as RetryStage[])
  .filter(stage => state.retryable_stages.includes(stage) && (stage !== 'capture' || (state.input_source === 'desktop' && desktopReady.value))))
const topmost = ref(true)
const toast = ref<Message | string>('')
const toastError = ref(false)
let toastTimer: number | undefined
let pollTimer: number | undefined
let selectionPollTimer: number | undefined
let selectionPolling = false
// Which operation is driving the progress poll. Analysis runs on the home page
// and updates run on the settings page, so the poller cannot be page-scoped.
let trackingState: 'analysis' | 'update' | null = null
let progressRevision = -1
let polling = false
let progressFlight: Promise<void> | null = null

const draft = reactive<Profile>({ id: '', name: '', base_url: '', model: '', max_tokens: 400, key_configured: false, api_key: '', protocol: 'openai-chat' })
const draftPreset = ref('custom')
const selectedPreset = computed(() => state.provider_presets?.find(p => p.id === draftPreset.value))
const draftKeyVisible = ref(false)
const modelOptions = ref<string[]>([])
const modelStatus = ref<Message | string>(m('model.listHint'))
const modelBusy = ref(false)
const testing = ref(false)
const showModelList = ref(false)
const modelListIndex = ref(-1)
const modelNameInput = ref<HTMLInputElement | null>(null)
let requestNo = 0
let addressTimer: number | undefined
let keyTimer: number | undefined
const jevKey = ref('')
const jevKeyVisible = ref(false)
const clearJevKey = ref(false)

const updateInfo = ref<UpdateInfo | null>(null)
const updateChecking = ref(false)
const updateBusy = ref(false)
const updateProgress = ref(-1)

const updatePhase = computed(() => state.phase)
const updateReady = computed(() => updatePhase.value === 'updateReady')
const updateRunning = computed(() => updatePhase.value === 'updating')
const updatePercent = computed(() => (updateRunning.value && updateProgress.value >= 0 ? updateProgress.value : null))
const updateStatusText = computed(() => display(state.status_message ?? state.status))

async function checkForUpdates(manual = true) {
  if (operationsLocked.value || !bridge()) return
  updateChecking.value = true
  try {
    const result = await bridge()!.check_for_updates()
    updateInfo.value = result
    if (manual) notify(result.update_available ? m('update.available', { version: result.latest_version }) : m('update.latest'))
  } catch (error) {
    if (manual) notify(errorMessage(error), true)
  } finally { updateChecking.value = false }
}
async function startUpdateDownload() {
  if (operationsLocked.value) return
  updateBusy.value = true
  updateProgress.value = 0
  trackingState = 'update'
  try {
    await bridge()!.download_update()
  } catch (error) {
    trackingState = null
    notify(errorMessage(error), true)
  } finally { updateBusy.value = false }
}
async function cancelUpdateDownload() {
  try { await bridge()!.cancel_update() } catch { /* state will settle */ }
}
async function applyUpdateNow() {
  if (updateBusy.value || analysisRunning.value || analysisBusy.value || busy.value || languageBusy.value || calibrationBusy.value || activeModelBusy.value || updateChecking.value) return
  updateBusy.value = true
  try { await bridge()!.apply_update() } catch (error) { notify(errorMessage(error), true) }
  finally { updateBusy.value = false }
}

const activeProfile = computed(() => state.profiles.find(p => p.id === state.active_model_id))
const statusTone = computed(() => state.phase === 'error' ? 'danger' : state.phase === 'idle' ? 'neutral' : 'working')
const endpointSuffixes: Record<string, string> = { 'openai-chat': '/chat/completions', 'openai-responses': '/responses', anthropic: '/messages' }
const endpointPlaceholder = computed(() => draft.protocol === 'anthropic'
  ? 'https://api.anthropic.com/v1'
  : draft.protocol === 'openai-responses'
    ? 'https://api.openai.com/v1'
    : 'https://api.example.com/v1')

function normalizeEndpointUrl(url: string, protocol: string) {
  const suffix = endpointSuffixes[protocol]
  if (!suffix) return url
  let value = url.trim().replace(/\/+$/, '')
  for (const known of Object.values(endpointSuffixes)) {
    if (value.toLowerCase().endsWith(known)) { value = value.slice(0, -known.length); break }
  }
  if (/\/v\d+$/i.test(value)) value += suffix
  return value
}

function notify(message: Message | string, isError = false) {
  toast.value = message
  toastError.value = isError
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 3000)
}
function readableError(error: unknown) { return errorMessage(error) }
function applySelection(next: Partial<UiState>, full = false) {
  if (next.selection_revision !== undefined && selectionRevision !== undefined && next.selection_revision < selectionRevision) return
  // Seed the initial revision without clearing session input. Ignore stale polls.
  if (next.selection_revision !== undefined) {
    if (selectionRevision !== undefined && next.selection_revision > selectionRevision) {
      clearContextSupplements()
      clearAnalysisState()
    }
    selectionRevision = Math.max(selectionRevision ?? next.selection_revision, next.selection_revision)
    state.selection_revision = selectionRevision
  }
  if (full || next.selection_mode !== undefined) state.selection_mode = next.selection_mode ?? (next.chat_rect ? 'screen' : 'window')
  if (full || next.selection_binding !== undefined) state.selection_binding = next.selection_binding ?? { status: 'none' }
  if (full || 'chat_rect' in next) state.chat_rect = next.chat_rect ?? null
}
function clearContextSupplements() {
  context.value = { ...context.value, prior_text: '', background: '' }
}
function clearAnalysisState() {
  state.task_id = null
  state.input_source = null
  state.preview = []
  state.analysis = null
  state.suggestions = []
  state.context_stats = null
  state.failed_stage = null
  state.retryable_stages = []
  state.error = ''
  state.error_message = undefined
  state.status = ''
  state.status_message = undefined
}
function applyState(next: UiState) {
  progressRevision = next.revision
  const { selection_mode, selection_binding, selection_revision, chat_rect, ...rest } = next
  applySelection({ selection_mode, selection_binding, selection_revision, chat_rect }, true)
  // Selection invalidation comes first; this snapshot may already contain a new task.
  Object.assign(state, rest)
  state.context_stats = next.context_stats ?? null
  state.reply_preferences = { ...defaultReplyPreferences, ...next.reply_preferences }
  state.retryable_stages = next.retryable_stages ?? []
  state.task_id = next.task_id ?? null
  state.input_source = next.input_source ?? null
  state.failed_stage = next.failed_stage ?? null
  if (analysisRunning.value) trackingState = 'analysis'
  state.status_message = next.status_message
  state.error_message = next.error_message
  if (next.update_info) updateInfo.value = next.update_info
  locale.value = next.resolved_language ?? 'zh-CN'
  if (trackingState && (next.phase === 'idle' || next.phase === 'error' || next.phase === 'updateReady')) {
    trackingState = null
  }
}
async function loadState() {
  try {
    if (bridge()) applyState(await bridge()!.get_state())
  } catch (error) { notify(errorMessage(error), true) }
}
async function pollProgress() {
  if (!trackingState || polling || !bridge()) return
  await readProgress(false)
}
async function readProgress(force: boolean) {
  // Forced refreshes and timer polls share one flight, including slow bridges.
  if (!force && progressFlight) { await progressFlight; return }
  while (progressFlight) await progressFlight
  polling = true
  progressFlight = (async () => {
    try {
      const wasCalibrating = state.phase === 'calibrating'
      applyProgress(await bridge()!.get_progress(force ? -1 : progressRevision))
      if (wasCalibrating && state.phase === 'idle') await refreshCalibrationRectangle()
    } catch { /* Retry after the window reappears from capture. */ }
    finally { polling = false; progressFlight = null }
  })()
  await progressFlight
}

function applyProgress(result: Progress) {
  // An earlier in-flight poll may complete after a fresh task snapshot.
  if (result.revision < progressRevision) return
  if (result.selection_revision !== undefined && selectionRevision !== undefined && result.selection_revision < selectionRevision) return
  progressRevision = result.revision
  state.revision = result.revision
  const { revision, ...changes } = result
  const { selection_mode, selection_binding, selection_revision, chat_rect, ...rest } = changes
  applySelection(changes)
  Object.assign(state, rest)
  if ('status' in changes) state.status_message = changes.status_message
  if ('error' in changes) state.error_message = changes.error_message
  if (changes.update_info) updateInfo.value = changes.update_info
  if (typeof changes.status === 'string') {
    const match = /(\d{1,3})%/.exec(changes.status)
    if (match) updateProgress.value = Number(match[1])
    else if (state.phase !== 'updating') updateProgress.value = -1
  }
  if (state.phase === 'idle' || state.phase === 'error') { trackingState = null; updateProgress.value = -1 }
  if (state.phase === 'updateReady') { trackingState = null; updateProgress.value = 100 }
}
async function refreshAnalysisProgress() {
  // Full progress only: do not overwrite unsaved settings/model edits.
  await readProgress(true)
}
async function refreshCalibrationRectangle() {
  const api = bridge()!
  const next = typeof api.get_selection_state === 'function'
    ? await api.get_selection_state() : await api.get_state()
  applySelection(next, true)
}
async function pollSelection() {
  const api = bridge()
  if (selectionPolling || page.value !== 'home' || inputSource.value !== 'desktop'
    || operationsLocked.value || trackingState || polling || state.phase !== 'idle'
    || typeof api?.get_selection_state !== 'function') return
  selectionPolling = true
  try {
    const next = await api.get_selection_state()
    // An idle poll may finish after the user begins another operation.
    if (!operationsLocked.value && !trackingState) applySelection(next, true)
  } catch { /* A transient descriptor failure must not erase a confirmed selection. */ }
  finally { selectionPolling = false }
}
function resetDraft() {
  Object.assign(draft, { id: '', name: '', base_url: '', model: '', max_tokens: 400, key_configured: false, api_key: '', protocol: 'openai-chat' })
  draftKeyVisible.value = false
  closeModelList()
  modelOptions.value = []
  modelStatus.value = m('model.listHint')
}
function closeModelList() { showModelList.value = false; modelListIndex.value = -1 }
function filteredModelOptions() {
  const query = draft.model.trim().toLowerCase()
  if (!query) return modelOptions.value
  return modelOptions.value.filter(model => model.toLowerCase().includes(query))
}
function chooseModel(model: string) {
  draft.model = model
  closeModelList()
  modelNameInput.value?.focus()
}
function onModelNameKeydown(event: KeyboardEvent) {
  const options = filteredModelOptions()
  if (!showModelList.value || !options.length) return
  if (event.key === 'ArrowDown') { event.preventDefault(); modelListIndex.value = (modelListIndex.value + 1) % options.length }
  else if (event.key === 'ArrowUp') { event.preventDefault(); modelListIndex.value = modelListIndex.value <= 0 ? options.length - 1 : modelListIndex.value - 1 }
  else if (event.key === 'Enter' && modelListIndex.value >= 0) { event.preventDefault(); chooseModel(options[modelListIndex.value]) }
  else if (event.key === 'Escape') { event.preventDefault(); closeModelList() }
}
function addModel() {
  editingId.value = ''
  resetDraft()
  chooseProvider(state.provider_presets?.[0]?.id || 'custom')
  showModel.value = true
}
function editModel(item: Profile) {
  editingId.value = item.id
  Object.assign(draft, { ...item, api_key: '' })
  draftPreset.value = matchPreset()?.id || 'custom'
  modelOptions.value = [...(selectedPreset.value?.models || [])]
  modelStatus.value = item.key_configured ? m('key.savedHint') : m('model.listHintEdit')
  showModel.value = true
}
function presetUrl(url: string) { return url.trim().replace(/\/+$/, '').replace(/\/(chat\/completions|responses|messages|models)$/, '') }
function localUrl(url: string) {
  try { return ['localhost', '127.0.0.1', '[::1]', '::1'].includes(new URL(url).hostname) } catch { return false }
}
function matchPreset() { return state.provider_presets?.find(p => p.protocol === draft.protocol && presetUrl(p.base_url) === presetUrl(draft.base_url)) }
function canAutoFetch() { return canFetchModels() && (!!draft.api_key?.trim() || !!(editingId.value && draft.key_configured) || localUrl(draft.base_url)) }
function chooseProvider(value: string) {
  requestNo++
  window.clearTimeout(addressTimer)
  window.clearTimeout(keyTimer)
  modelBusy.value = false
  closeModelList()
  draftPreset.value = value
  const preset = selectedPreset.value
  if (!preset) return
  draft.api_key = ''
  draft.key_configured = false
  Object.assign(draft, { protocol: preset.protocol, name: preset.name, base_url: preset.base_url, model: preset.default_model })
  modelOptions.value = [...preset.models]
  modelStatus.value = m('model.presetModels')
}
function canFetchModels() { return /^https?:\/\//i.test(draft.base_url.trim()) }
async function refreshModels() {
  if (!canFetchModels()) { modelStatus.value = m('model.listHint'); return }
  const url = draft.base_url.trim()
  const token = ++requestNo
  modelBusy.value = true
  modelStatus.value = m('model.loading')
  try {
    if (!bridge()) throw m('bridge.unavailable')
    const result = checked(await bridge()!.fetch_models(JSON.stringify({ profile_id: editingId.value, base_url: url, api_key: draft.api_key?.trim() || '', protocol: draft.protocol })))
    if (token !== requestNo || url !== draft.base_url.trim()) return
    modelOptions.value = result.models
    modelStatus.value = m('model.found', { count: result.models.length })
  } catch (error) {
    if (token !== requestNo || url !== draft.base_url.trim()) return
    modelOptions.value = [...(selectedPreset.value?.models || [])]
    modelStatus.value = m('model.manual', { detail: readableError(error) })
  } finally {
    if (token === requestNo) modelBusy.value = false
  }
}
watch(() => draft.base_url, (value, old) => {
  const normalized = normalizeEndpointUrl(value, draft.protocol)
  if (normalized !== value.trim()) { draft.base_url = normalized; return }
  if (old && presetUrl(value) !== presetUrl(old)) {
    draftPreset.value = matchPreset()?.id || 'custom'
    draft.api_key = ''
    modelOptions.value = [...(selectedPreset.value?.models || [])]
    closeModelList()
    modelStatus.value = selectedPreset.value ? m('model.presetModels') : m('model.urlChanged')
    requestNo++
    modelBusy.value = false
  }
  window.clearTimeout(addressTimer)
  if (showModel.value && canAutoFetch()) addressTimer = window.setTimeout(() => refreshModels(), 700)
})
watch(() => draft.api_key, value => {
  window.clearTimeout(keyTimer)
  if (value?.trim() && /^https?:\/\//i.test(draft.base_url.trim())) keyTimer = window.setTimeout(() => refreshModels(), 700)
})
watch(() => draft.protocol, () => {
  requestNo++
  modelOptions.value = [...(selectedPreset.value?.models || [])]
  closeModelList()
  const normalized = normalizeEndpointUrl(draft.base_url, draft.protocol)
  if (normalized !== draft.base_url.trim()) draft.base_url = normalized
  window.clearTimeout(addressTimer)
  if (showModel.value && canAutoFetch()) addressTimer = window.setTimeout(() => refreshModels(), 700)
})
async function testConnection() {
  if (!draft.model.trim()) { notify(m('model.nameRequired'), true); return }
  testing.value = true
  try {
    const result = checked(await bridge()!.test_model(JSON.stringify({ profile_id: editingId.value, base_url: draft.base_url.trim(), model: draft.model.trim(), api_key: draft.api_key?.trim() || '', protocol: draft.protocol })))
    notify(m('model.connected', { detail: result.message_message ?? result.message ?? m('model.responded') }))
  } catch (error) { notify(readableError(error), true) }
  finally { testing.value = false }
}
function saveModel() {
  if (!draft.name.trim() || !draft.base_url.trim() || !draft.model.trim()) { notify(m('model.required'), true); return }
  const id = editingId.value || crypto.randomUUID()
  const next: Profile = { ...draft, id, name: draft.name.trim(), base_url: draft.base_url.trim(), model: draft.model.trim(), max_tokens: Number(draft.max_tokens) || null }
  delete next.key_configured
  const index = state.profiles.findIndex(item => item.id === id)
  if (index >= 0) state.profiles.splice(index, 1, next)
  else state.profiles.push(next)
  if (!state.active_model_id) state.active_model_id = id
  showModel.value = false
  notify(m('model.staged'))
}
function removeModel(item: Profile) {
  pendingDelete.value = item
}
function confirmDelete() {
  const item = pendingDelete.value
  if (!item) return
  pendingDelete.value = null
  state.profiles = state.profiles.filter(profile => profile.id !== item.id)
  if (state.active_model_id === item.id) state.active_model_id = state.profiles[0]?.id || ''
}
async function saveSettings() {
  if (operationsLocked.value) return
  busy.value = true
  try {
    const next = checked(await bridge()!.save_settings(JSON.stringify({
      jev_api_key: jevKey.value, clear_jev_key: clearJevKey.value,
      relationship: state.relationship,
      allowed_titles: state.allowed_titles,
      active_model_id: state.active_model_id,
      profiles: state.profiles,
      reply_preferences: { ...state.reply_preferences },
    })))
    applyState(next)
    jevKey.value = ''
    clearJevKey.value = false
    page.value = 'home'
    notify(m('settings.saved'))
  } catch (error) { notify(readableError(error), true) }
  finally { busy.value = false }
}
async function changeSelectionMode(event: Event) {
  const select = event.target as HTMLSelectElement
  if (operationsLocked.value || typeof bridge()?.set_selection_mode !== 'function') { select.value = selectionMode.value; return }
  bindingBusy.value = true
  try {
    checked(await bridge()!.set_selection_mode!(select.value as SelectionMode))
    await refreshCalibrationRectangle()
  } catch (error) { notify(errorMessage(error), true) }
  finally { bindingBusy.value = false; select.value = selectionMode.value }
}
async function refreshBindingCandidates() {
  if (bindingBusy.value || typeof bridge()?.get_binding_candidates !== 'function') return
  bindingBusy.value = true
  selectedBindingId.value = ''
  bindingCandidates.value = []
  try {
    bindingCandidates.value = checked(await bridge()!.get_binding_candidates!()).candidates
  } catch (error) { notify(errorMessage(error), true) }
  finally { bindingBusy.value = false }
}
async function chooseBinding() {
  if (operationsLocked.value || typeof bridge()?.get_binding_candidates !== 'function') return
  showBinding.value = true
  await refreshBindingCandidates()
}
async function confirmBinding() {
  if (bindingBusy.value || typeof bridge()?.confirm_binding !== 'function' || !bindingCandidates.value.some(item => item.id === selectedBindingId.value)) return
  bindingBusy.value = true
  try {
    checked(await bridge()!.confirm_binding!(selectedBindingId.value))
    await refreshCalibrationRectangle()
    showBinding.value = false
  } catch (error) { notify(errorMessage(error), true) }
  finally { bindingBusy.value = false }
}
async function calibrate() {
  if (operationsLocked.value) return
  calibrationBusy.value = true
  const previousPhase = state.phase
  state.phase = 'calibrating'
  try {
    checked(await bridge()!.start_calibration(selectionMode.value))
    trackingState = 'analysis'
    notify(m('capture.drag'))
    await refreshAnalysisProgress()
    if (state.phase === 'idle') await refreshCalibrationRectangle()
  } catch (error) { state.phase = previousPhase; notify(errorMessage(error), true) }
  finally { calibrationBusy.value = false }
}
async function analyze() {
  if (!canAnalyze.value) return
  await runAnalysis(() => inputSource.value === 'text'
    ? bridge()!.analyze_text({ text: textInput.value, preferences: { ...(temporaryEnabled.value ? effectivePreferences.value : state.reply_preferences) }, context: { ...context.value } })
    : bridge()!.analyze({ ...(temporaryEnabled.value ? effectivePreferences.value : state.reply_preferences) }, { ...context.value }),
  inputSource.value === 'desktop' ? 'capturing' : 'judging', true)
}
async function runAnalysis(start: () => Promise<AnalysisResult>, phase: string, newTask = false) {
  analysisBusy.value = true
  const previousPhase = state.phase
  const previousRevision = progressRevision
  let accepted = false
  state.phase = phase
  try {
    if (!bridge()) throw m('bridge.unavailable')
    const result = checked(await start())
    accepted = true
    if (progressRevision === previousRevision) {
      state.task_id = result.task_id ?? (newTask ? null : state.task_id)
      if (newTask) state.input_source = inputSource.value
      state.failed_stage = null
      state.retryable_stages = []
      state.error = ''
      state.error_message = undefined
      if (newTask) state.context_stats = null
    }
    trackingState = 'analysis'
    // Fetch the authoritative task/phase even if the worker finished before polling.
    await refreshAnalysisProgress()
  } catch (error) { notify(errorMessage(error), true) }
  finally {
    if (!accepted && progressRevision === previousRevision) state.phase = previousPhase
    analysisBusy.value = false
  }
}
async function cancelAnalysis() {
  if (!state.task_id || !analysisRunning.value || analysisBusy.value || cancelBusy.value) return
  cancelBusy.value = true
  try {
    checked(await bridge()!.cancel_analysis(state.task_id))
    trackingState = 'analysis'
    await refreshAnalysisProgress()
  } catch (error) { notify(errorMessage(error), true) }
  finally { cancelBusy.value = false }
}
async function retryAnalysis(stage: RetryStage) {
  if (operationsLocked.value || !state.task_id || !retryStages.value.includes(stage)) return
  const taskId = state.task_id
  const phases: Record<RetryStage, string> = { capture: 'capturing', judge: 'judging', generate: 'generating', rank: 'ranking' }
  await runAnalysis(() => bridge()!.retry_analysis(taskId, stage), phases[stage])
}
async function toggleTopmost() {
  topmost.value = !topmost.value
  try { await bridge()?.set_on_top(topmost.value) } catch { /* browser preview */ }
}
async function selectActiveModel() {
  if (operationsLocked.value) return
  activeModelBusy.value = true
  try { if (bridge()) checked(await bridge()!.set_active_model(state.active_model_id)) }
  catch (error) { notify(errorMessage(error), true) }
  finally { activeModelBusy.value = false }
}
async function copyReply(reply: string) {
  try {
    if (bridge()) checked(await bridge()!.copy_text(reply))
    else await navigator.clipboard.writeText(reply)
    notify(m('replies.copied'))
  } catch { notify(m('replies.copyFailed'), true) }
}
const intentLabels = computed<Record<string, string>>(() => ({
  confirm_you_care: t('intent.confirm_you_care'), vent_anger: t('intent.vent_anger'), request_action: t('intent.request_action'),
  seek_explanation: t('intent.seek_explanation'), casual_chat: t('intent.casual_chat'), close_topic: t('intent.close_topic'),
}))
const needLabels = computed<Record<string, string>>(() => ({ apology: t('need.apology'), action: t('need.action'), explanation: t('need.explanation'), care: t('need.care'), nothing: t('need.nothing') }))
const actionLabels = computed<Record<string, string>>(() => ({
  check_history: t('action.check_history'), apologize: t('action.apologize'), give_commitment: t('action.give_commitment'),
  explain: t('action.explain'), acknowledge: t('action.acknowledge'), say_less: t('action.say_less'), make_plan: t('action.make_plan'),
}))
function percent(value: number | null | undefined) { return value == null ? '—' : new Intl.NumberFormat(locale.value, { style: 'percent', maximumFractionDigits: 0 }).format(value) }
function danger(value: number | null | undefined) { return value == null ? '—' : `${new Intl.NumberFormat(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value)}/9` }

watch([locale, () => state.version], () => {
  document.documentElement.lang = locale.value
  document.title = t('app.title', { version: state.version })
}, { immediate: true })

async function changeLanguage(event: Event) {
  const select = event.target as HTMLSelectElement
  if (languageBusy.value || busy.value) { select.value = state.language; return }
  const chosen = select.value as Language
  languageBusy.value = true
  try {
    if (!bridge()) throw m('bridge.unavailable')
    const result = checked(await bridge()!.set_language(chosen))
    state.language = result.language
    state.resolved_language = result.resolved_language
    locale.value = result.resolved_language
    notify(m('language.saved'))
  } catch (error) { notify(errorMessage(error), true) }
  finally {
    select.value = state.language
    languageBusy.value = false
  }
}

onMounted(() => {
  if (bridge()) void loadState()
  else window.addEventListener('pywebviewready', loadState, { once: true })
  selectionPollTimer = window.setInterval(() => { void pollSelection() }, 1500)
  pollTimer = window.setInterval(() => { void pollProgress() }, 850)
  window.setTimeout(() => { if (updateInfo.value === null) void checkForUpdates(false) }, 4000)
})
onBeforeUnmount(() => { window.removeEventListener('pywebviewready', loadState); window.clearInterval(pollTimer); window.clearInterval(selectionPollTimer); window.clearTimeout(toastTimer); window.clearTimeout(addressTimer); window.clearTimeout(keyTimer) })
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div class="brand-lockup">
        <div class="brand-mark"><Sparkles :size="19" /></div>
        <div><div class="brand-name">Jev <span>{{ t('app.short') }}</span></div><div class="brand-caption">{{ t('app.caption') }}</div></div>
      </div>
      <div class="top-actions">
        <button class="icon-button" :class="{ selected: topmost }" :title="topmost ? t('common.unpin') : t('common.pin')" @click="toggleTopmost"><Eye :size="17" /></button>
        <button class="button button-quiet" @click="page = page === 'settings' ? 'home' : 'settings'"><Settings2 :size="16" /> {{ t('common.settings') }}</button>
      </div>
    </header>

    <template v-if="page === 'home'">
      <button v-if="updateInfo?.update_available" class="update-banner" @click="page = 'settings'">
        <Download :size="16" /><span>{{ t('update.banner', { version: updateInfo.latest_version }) }}</span><ArrowRight :size="15" />
      </button>
      <section class="welcome-row">
        <div><div class="eyebrow">{{ t('home.eyebrow') }} <span class="version-pill">v{{ state.version }}</span></div><h1>{{ t('home.title') }}</h1><p>{{ t('home.subtitle') }}</p></div>
        <div class="jev-badge"><ShieldCheck :size="18" /><span>{{ t('home.safety') }}</span></div>
      </section>

      <section class="surface input-source-panel">
        <div class="input-source-toggle" role="group" :aria-label="t('feature.inputSource')">
          <button class="button" :class="inputSource === 'desktop' ? 'button-primary' : 'button-outline'" :aria-pressed="inputSource === 'desktop'" :disabled="operationsLocked" @click="inputSource = 'desktop'">{{ t('feature.inputDesktop') }}</button>
          <button class="button" :class="inputSource === 'text' ? 'button-primary' : 'button-outline'" :aria-pressed="inputSource === 'text'" :disabled="operationsLocked" @click="inputSource = 'text'">{{ t('feature.inputText') }}</button>
        </div>
        <template v-if="inputSource === 'text'">
          <label class="field-label" for="analysis-text">{{ t('feature.textLabel') }}</label>
          <textarea id="analysis-text" v-model="textInput" rows="7" :disabled="operationsLocked" :placeholder="t('feature.textPlaceholder')" :aria-invalid="textTooLong" :aria-describedby="textTooLong ? 'text-input-hint text-input-count text-input-error' : 'text-input-hint text-input-count'"></textarea>
          <div class="field-hint text-input-meta"><span id="text-input-hint">{{ t('feature.textHint') }}</span><span id="text-input-count">{{ t('feature.textCount', { count: textCount, limit: textLimit }) }}</span></div>
          <p v-if="textTooLong" id="text-input-error" class="text-input-error" role="alert">{{ t('feature.textTooLong', { count: textCount, limit: textLimit }) }}</p>
        </template>
        <div class="temporary-heading">
          <button class="text-action" :aria-expanded="temporaryOpen" aria-controls="temporary-preferences" @click="temporaryOpen = !temporaryOpen"><ChevronDown :size="15" :class="{ collapsed: !temporaryOpen }" />{{ t('feature.temporaryPreferences') }}</button>
          <span>{{ temporaryEnabled ? t('feature.temporaryActive') : t('feature.usingDefaults') }}</span>
        </div>
        <div v-show="temporaryOpen" id="temporary-preferences">
          <label class="temporary-enable"><input v-model="temporaryEnabled" type="checkbox" :disabled="operationsLocked" />{{ t('feature.temporaryEnable') }}</label>
          <ReplyPreferencesFields :model-value="effectivePreferences" id-prefix="temporary" :disabled="operationsLocked || !temporaryEnabled" @update:model-value="temporaryOverrides = $event" />
          <p class="field-hint">{{ t('feature.temporaryHint') }}</p>
          <button class="button button-quiet" :disabled="operationsLocked" @click="temporaryOverrides = {}; temporaryEnabled = false">{{ t('feature.resetOverrides') }}</button>
        </div>
        <ContextOptions v-model="context" :disabled="operationsLocked" :stats="state.context_stats" />
      </section>

      <section v-if="inputSource === 'desktop'" class="setup-card surface">
        <div class="setup-copy"><div class="setup-icon"><MessageCircle :size="18" /></div><div><h2>{{ t('capture.title') }}</h2><p>{{ bindingStatusText }}</p><p v-if="state.selection_binding?.reason && selectionMode === 'window'">{{ t(state.selection_binding.reason) }}</p></div></div>
        <div class="binding-controls">
          <label class="field-label" for="selection-mode">{{ t('binding.mode') }}</label>
          <div class="select-wrap"><select id="selection-mode" :value="selectionMode" :disabled="operationsLocked || typeof bridge()?.set_selection_mode !== 'function'" @change="changeSelectionMode"><option value="window">{{ t('binding.window') }}</option><option value="screen">{{ t('binding.screen') }}</option></select></div>
          <p class="field-hint">{{ t(selectionMode === 'window' ? 'binding.windowHelp' : 'binding.screenHelp') }}</p>
          <div class="setup-actions"><span v-if="desktopReady" class="ready-chip"><CheckCircle2 :size="15" />{{ t('capture.calibrated') }}</span><button v-if="selectionMode === 'window'" class="button button-outline" :disabled="operationsLocked || typeof bridge()?.get_binding_candidates !== 'function' || typeof bridge()?.confirm_binding !== 'function'" @click="chooseBinding">{{ t('binding.chooseWindow') }}</button><button class="button button-outline" :disabled="operationsLocked" @click="calibrate">{{ t('binding.reselect') }} <ArrowRight :size="15" /></button></div>
        </div>
      </section>

      <div class="content-grid">
        <section class="surface analysis-card">
          <div class="section-heading"><div class="heading-icon blue"><Sparkles :size="17" /></div><div><h2>{{ t('analysis.title') }}</h2><p>{{ t(inputSource === 'text' ? 'feature.textAnalysisHelp' : 'analysis.help') }}</p></div></div>
          <div class="status-line" :class="statusTone"><span class="status-dot"><LoaderCircle v-if="state.phase !== 'idle' && state.phase !== 'error'" :size="15" class="spin" /><span v-else></span></span><span>{{ display(state.status_message ?? state.status) }}</span></div>
          <button class="button button-primary analyze-button" :disabled="!canAnalyze" @click="analyze"><Sparkles :size="17" />{{ analysisRunning || analysisBusy ? t('analysis.busy') : t(inputSource === 'text' ? 'feature.analyzeText' : 'analysis.start') }}<ArrowRight v-if="!analysisRunning && !analysisBusy" :size="17" /></button>
          <div v-if="state.input_source" class="analysis-task-meta">
            <span>{{ t('feature.taskSource', { source: state.input_source === 'text' ? t('feature.inputText') : t('feature.inputDesktop') }) }}</span>
          </div>
          <button v-if="analysisRunning && state.task_id" class="button button-outline cancel-analysis" :disabled="cancelBusy || analysisBusy" @click="cancelAnalysis"><X :size="15" />{{ cancelBusy ? t('feature.cancelling') : t('feature.cancelAnalysis') }}</button>
          <div v-if="!analysisRunning && (state.failed_stage || state.error || state.error_message || retryStages.length)" class="analysis-recovery" role="status">
            <p v-if="state.failed_stage">{{ t('feature.failedStage', { stage: stageLabels[state.failed_stage] ?? state.failed_stage }) }}</p>
            <p v-if="state.error || state.error_message" class="analysis-error">{{ display(state.error_message ?? state.error) }}</p>
            <div v-if="state.task_id" class="retry-actions"><button v-for="stage in retryStages" :key="stage" class="button button-outline" :disabled="operationsLocked" @click="retryAnalysis(stage)"><RefreshCw :size="14" />{{ t('feature.retryStage', { stage: stageLabels[stage] }) }}</button></div>
          </div>
          <div class="privacy-note"><LockKeyhole :size="14" />{{ t(inputSource === 'text' ? 'feature.textPrivacy' : 'analysis.privacy') }}</div>
        </section>

        <section class="surface model-card">
          <div class="section-heading"><div class="heading-icon violet"><Cpu :size="17" /></div><div><h2>{{ t('model.title') }}</h2><p>{{ t('model.help') }}</p></div></div>
          <label class="field-label" for="active-model">{{ t('model.current') }}</label>
          <div class="select-wrap"><select id="active-model" v-model="state.active_model_id" :disabled="operationsLocked || !state.profiles.length" @change="selectActiveModel"><option value="" disabled>{{ t('model.choose') }}</option><option v-for="profile in state.profiles" :key="profile.id" :value="profile.id">{{ profile.name }} · {{ profile.model }}</option></select><ChevronDown :size="16" /></div>
          <div v-if="activeProfile" class="model-meta"><span class="online-dot"></span><span>{{ activeProfile.name }}</span><span class="meta-separator">/</span><span class="model-id">{{ activeProfile.model }}</span></div>
          <button class="text-action" @click="page = 'settings'"><Settings2 :size="15" />{{ t('model.manage') }} <ArrowRight :size="14" /></button>
        </section>
      </div>

      <div class="results-grid">
        <section class="surface result-card messages-card">
          <div class="result-heading"><div><span class="eyebrow">{{ t('messages.eyebrow') }}</span><h2>{{ t('messages.title') }}</h2></div><span class="count-pill">{{ t('messages.count', { count: state.preview.length }) }}</span></div>
          <div v-if="state.preview.length" class="message-list"><div v-for="(message, index) in state.preview" :key="index" class="message-row" :class="message.side"><span class="message-avatar">{{ message.side === 'me' ? t('messages.me') : t('messages.avatarOther') }}</span><div class="message-bubble"><span class="speaker">{{ message.side === 'me' ? t('messages.me') : t('messages.other') }}</span><span>{{ message.text }}</span></div></div></div>
          <div v-else class="empty-state"><div class="empty-icon"><MessageCircle :size="20" /></div><span>{{ t('messages.empty') }}</span></div>
        </section>
        <section class="surface result-card judgement-card">
          <div class="result-heading"><div><span class="eyebrow">{{ t('insight.eyebrow') }}</span><h2>{{ t('insight.title') }}</h2></div><span v-if="state.analysis" class="confidence-pill"><ShieldCheck :size="14" /> {{ t('common.done') }}</span></div>
          <template v-if="state.analysis">
            <div class="insight-primary"><div class="insight-label">{{ t('insight.intent') }}</div><div class="intent-value">{{ intentLabels[state.analysis.true_intent] || state.analysis.true_intent || '—' }}</div><div class="danger-meter"><span>{{ t('insight.danger') }}</span><strong>{{ danger(state.analysis.danger_level) }}</strong></div></div>
            <div class="insight-stats"><div><span>{{ t('insight.need') }}</span><strong>{{ needLabels[state.analysis.need] || state.analysis.need || '—' }}</strong></div><div><span>{{ t('insight.action') }}</span><strong>{{ actionLabels[state.analysis.best_action] || state.analysis.best_action || '—' }}</strong></div><div><span>{{ t('insight.reply') }}</span><strong>{{ percent(state.analysis.should_reply_now) }}</strong></div><div><span>{{ t('insight.resolved') }}</span><strong>{{ percent(state.analysis.tension_resolved) }}</strong></div></div>
            <div class="latency">{{ t('insight.latency', { count: state.analysis.latency_ms }) }}</div>
          </template>
          <div v-else class="empty-state"><div class="empty-icon"><ShieldCheck :size="20" /></div><span>{{ t('insight.empty') }}</span></div>
        </section>
      </div>

      <section class="surface suggestions-section">
        <div class="result-heading"><div><span class="eyebrow">{{ t('replies.eyebrow') }}</span><h2>{{ t('replies.title') }}</h2></div><span class="suggestion-caption">{{ t('replies.caption') }}</span></div>
        <div v-if="state.suggestions.length" class="suggestion-list"><article v-for="(suggestion, index) in state.suggestions" :key="index" class="suggestion-item"><span class="suggestion-number">0{{ index + 1 }}</span><div class="suggestion-copy"><p>{{ suggestion.text }}<span v-if="suggestion.recommended" class="recommend-badge">{{ t('replies.recommended') }}</span></p><div class="suggestion-confidence"><span>{{ t('replies.score') }} <strong>{{ percent(suggestion.probability) }}</strong></span><span v-if="suggestion.confidence !== null">{{ t('replies.confidence') }} <strong>{{ percent(suggestion.confidence) }}</strong></span></div></div><button class="copy-button" @click="copyReply(suggestion.text)"><Copy :size="15" />{{ t('common.copy') }}</button></article></div>
        <div v-else class="suggestion-empty"><Sparkles :size="16" />{{ state.profiles.length ? t('replies.empty') : t('replies.setup') }}<button class="inline-link" @click="page = 'settings'">{{ t('replies.configure') }} <ArrowRight :size="13" /></button></div>
      </section>
    </template>

    <template v-else>
      <section class="settings-heading"><button class="back-button" :aria-label="t('common.back')" @click="page = 'home'"><ArrowLeft :size="17" /></button><div><div class="eyebrow">{{ t('settings.eyebrow') }}</div><h1>{{ t('common.settings') }}</h1><p>{{ t('settings.help') }}</p></div></section>
      <div class="settings-layout">
        <nav class="settings-nav"><a class="nav-item current"><ShieldCheck :size="16" /> {{ t('settings.judge') }} <ChevronRight :size="15" /></a><a class="nav-item"><Bot :size="16" /> {{ t('model.title') }} <ChevronRight :size="15" /></a><a class="nav-item"><MessageCircle :size="16" /> {{ t('settings.preferences') }} <ChevronRight :size="15" /></a><div class="nav-tip"><LockKeyhole :size="15" /><span>{{ t('settings.keyNote') }}</span></div></nav>
        <div class="settings-content">
          <section class="surface settings-panel language-panel">
            <h2><label for="interface-language">{{ t('language.title') }}</label></h2>
            <div class="select-wrap"><select id="interface-language" :value="state.language" :disabled="languageBusy || busy" @change="changeLanguage">
              <option value="system">{{ t('language.system') }}</option>
              <option v-for="item in languages" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select><ChevronDown :size="16" /></div>
            <p class="field-hint">{{ t('language.hint') }}</p>
          </section>
        <fieldset class="settings-content settings-fields" :disabled="operationsLocked">
          <section class="surface settings-panel">
            <div class="panel-heading"><div class="heading-icon blue"><ShieldCheck :size="17" /></div><div><h2>{{ t('settings.service') }}</h2><p>{{ t('settings.serviceHelp') }}</p></div><span class="required-tag">{{ t('settings.independent') }}</span></div>
          <label class="field-label" for="jev-key">Jev / TypeSafe API Key</label><div class="input-with-icon"><KeyRound :size="16" /><input id="jev-key" v-model="jevKey" :type="jevKeyVisible ? 'text' : 'password'" autocomplete="new-password" :placeholder="state.jev_key_configured ? t('key.savedHint') : t('key.jevPlaceholder')" /><button class="field-icon-button" :aria-label="jevKeyVisible ? t('key.hide') : t('key.show')" @click="jevKeyVisible = !jevKeyVisible"><EyeOff v-if="jevKeyVisible" :size="16" /><Eye v-else :size="16" /></button></div>
            <div class="field-hint"><span><span class="online-dot"></span>{{ state.jev_key_configured && !clearJevKey ? t('key.local') : t('key.jevOnly') }}</span><button v-if="state.jev_key_configured" class="danger-link" @click="clearJevKey = !clearJevKey">{{ clearJevKey ? t('key.undo') : t('key.clear') }}</button></div>
          </section>

          <section class="surface settings-panel models-panel">
            <div class="panel-heading"><div class="heading-icon violet"><Cpu :size="17" /></div><div><h2>{{ t('model.title') }}</h2><p>{{ t('model.protocolHelp') }}</p></div><span class="count-pill">{{ t('model.count', { count: state.profiles.length }) }}</span></div>
            <div v-if="state.profiles.length" class="configured-models"><article v-for="profile in state.profiles" :key="profile.id" class="configured-model" :class="{ active: profile.id === state.active_model_id }"><button class="radio-mark" :aria-label="t('common.select', { name: profile.name })" @click="state.active_model_id = profile.id"><Check v-if="profile.id === state.active_model_id" :size="13" /></button><button class="configured-main" @click="state.active_model_id = profile.id"><span class="configured-name">{{ profile.name }}<span v-if="profile.id === state.active_model_id" class="active-tag">{{ t('model.active') }}</span></span><span class="configured-model-id">{{ profile.model }}</span><span class="configured-endpoint">{{ profile.base_url }}</span></button><span class="key-state" :class="{ ready: profile.key_configured || !!profile.api_key }"><KeyRound :size="13" />{{ profile.key_required === false || localUrl(profile.base_url) ? t('key.notRequired') : profile.key_configured || profile.api_key ? t('key.configured') : t('key.missing') }}</span><button class="small-icon" :title="t('common.edit')" @click="editModel(profile)"><Settings2 :size="15" /></button><button class="small-icon delete-icon" :title="t('common.delete')" @click="removeModel(profile)"><Trash2 :size="15" /></button></article></div>
            <div v-else class="models-empty"><Bot :size="20" /><span>{{ t('model.empty') }}</span><small>{{ t('model.emptyHelp') }}</small></div>
            <button class="add-model-button" @click="addModel"><Plus :size="16" />{{ t('model.addConfig') }}</button>
          </section>

          <section class="surface settings-panel">
            <div class="panel-heading"><div class="heading-icon amber"><MessageCircle :size="17" /></div><div><h2>{{ t('settings.preferences') }}</h2><p>{{ t('settings.contextHelp') }}</p></div></div>
            <h3 class="reply-default-heading">{{ t('feature.defaultPreferences') }}</h3>
            <ReplyPreferencesFields v-model="state.reply_preferences" id-prefix="default" :disabled="operationsLocked" />
            <p class="field-hint">{{ t('feature.defaultPreferencesHint') }}</p>
            <label class="field-label" for="relationship">{{ t('settings.relationship') }}</label><textarea id="relationship" v-model="state.relationship" rows="3" :placeholder="t('settings.relationshipHint')"></textarea>
            <label class="field-label spaced" for="allowed-titles">{{ t('settings.allowlist') }}</label><input id="allowed-titles" class="plain-input" :value="state.allowed_titles.join('，')" :placeholder="t('settings.allowlistHint')" @input="state.allowed_titles = ($event.target as HTMLInputElement).value.replaceAll(',', '，').split('，').map(item => item.trim()).filter(Boolean)" />
            <div class="field-hint">{{ t('settings.allowlistHelp') }}</div>
          </section>

          </fieldset>
          <section class="surface settings-panel update-panel">
            <div class="panel-heading"><div class="heading-icon green"><RotateCw :size="17" /></div><div><h2>{{ t('update.title') }}</h2><p>{{ t('update.help') }}</p></div><span class="count-pill">v{{ state.version }}</span></div>
            <div class="update-row">
              <span class="update-status">{{ updateStatusText || t('update.idleHint') }}</span>
              <div class="update-actions">
                <button v-if="!updateReady && !updateRunning" class="button button-outline" :disabled="operationsLocked" @click="checkForUpdates()">
                  <LoaderCircle v-if="updateChecking" :size="15" class="spin" /><RefreshCw v-else :size="15" />{{ t('update.check') }}
                </button>
                <button v-if="updateReady" class="button button-primary" :disabled="updateBusy || analysisRunning || analysisBusy || busy || languageBusy || calibrationBusy || activeModelBusy || updateChecking" @click="applyUpdateNow">
                  <LoaderCircle v-if="updateBusy" :size="15" class="spin" /><RotateCw v-else :size="15" />{{ t('update.applyRestart') }}
                </button>
                <button v-if="updateRunning" class="button button-outline" :disabled="updateBusy" @click="cancelUpdateDownload"><X :size="15" />{{ t('update.cancel') }}</button>
              </div>
            </div>
            <div v-if="updatePercent !== null" class="update-progress"><div class="update-progress-fill" :style="{ width: updatePercent + '%' }"></div></div>
            <div v-if="updateInfo?.update_available && !updateRunning && !updateReady" class="update-available-row">
              <span>{{ t('update.availableLong', { version: updateInfo.latest_version }) }}</span>
              <button class="button button-primary" :disabled="operationsLocked" @click="startUpdateDownload"><Download :size="15" />{{ t('update.download') }}</button>
            </div>
            <p class="field-hint">{{ t('update.privacyNote') }}</p>
          </section>
          <div class="save-bar"><span><LockKeyhole :size="14" />{{ t('settings.storage') }}</span><button class="button button-primary" :disabled="operationsLocked" @click="saveSettings"><LoaderCircle v-if="busy" :size="16" class="spin" /><Save v-else :size="16" />{{ busy ? t('settings.saving') : t('settings.save') }}</button></div>
        </div>
      </div>
    </template>

    <footer class="app-footer"><span>{{ t('app.name') }} <span class="footer-divider">·</span> {{ t('footer.promise') }}</span><button @click="notify(m('footer.notice'))"><CircleHelp :size="14" /> {{ t('footer.help') }}</button></footer>

    <div v-if="showModel" class="modal-backdrop">
      <section class="model-dialog" role="dialog" aria-modal="true" :aria-label="editingId ? t('model.edit') : t('model.add')">
        <header class="dialog-header"><div><div class="dialog-kicker">{{ t('model.eyebrow') }}</div><h2>{{ editingId ? t('model.edit') : t('model.add') }}</h2></div><button class="small-icon" :aria-label="t('common.close')" @click="showModel = false"><X :size="19" /></button></header>
        <div class="dialog-scroll">
          <label class="field-label" for="provider">{{ t('model.provider') }}</label><div class="select-wrap provider-select"><select id="provider" :value="draftPreset" @change="chooseProvider(($event.target as HTMLSelectElement).value)"><option v-for="preset in state.provider_presets || []" :key="preset.id" :value="preset.id">{{ preset.name }}</option><option value="custom">{{ t('model.presetCustom') }}</option></select><ChevronDown :size="16" /></div>
          <p v-if="selectedPreset" class="field-hint">{{ t('model.presetAuto') }}</p>
          <p v-if="selectedPreset?.key_site" class="field-hint">{{ t('model.keyHint', { site: selectedPreset.key_site }) }}</p>
          <p v-if="draftPreset === 'ark'" class="field-hint">{{ t('model.arkHint') }}</p>
          <p v-if="localUrl(draft.base_url)" class="field-hint">{{ t('model.localNoKey') }}</p>
          <template v-if="draftPreset === 'custom'"><label class="field-label" for="protocol">{{ t('model.protocolField') }}</label><div class="select-wrap"><select id="protocol" v-model="draft.protocol"><option value="openai-chat">openai-chat</option><option value="openai-responses">openai-responses</option><option value="anthropic">anthropic</option></select><ChevronDown :size="16" /></div></template>
          <label class="field-label" for="provider-name">{{ t('model.displayName') }}</label><input id="provider-name" v-model="draft.name" class="plain-input" :placeholder="t('model.displayHint')" />
          <label class="field-label" for="base-url">{{ t('model.url') }}</label><input id="base-url" v-model="draft.base_url" class="plain-input" :placeholder="endpointPlaceholder" autocomplete="url" />
          <label class="field-label" for="model-key">API Key</label><div class="key-entry-row"><div class="input-with-icon key-input"><KeyRound :size="16" /><input id="model-key" v-model="draft.api_key" :type="draftKeyVisible ? 'text' : 'password'" autocomplete="new-password" :placeholder="editingId && draft.key_configured ? t('key.savedHint') : t('key.modelPlaceholder')" /><button class="field-icon-button" :aria-label="draftKeyVisible ? t('key.hide') : t('key.show')" @click="draftKeyVisible = !draftKeyVisible"><EyeOff v-if="draftKeyVisible" :size="16" /><Eye v-else :size="16" /></button></div><button class="button button-outline test-button" :disabled="testing || !draft.base_url || !draft.model" @click="testConnection"><LoaderCircle v-if="testing" :size="15" class="spin" /><span v-else>{{ t('model.test') }}</span></button></div>
          <label class="field-label" for="model-name">{{ t('model.name') }}</label>
          <div class="model-name-wrap">
            <input id="model-name" ref="modelNameInput" v-model="draft.model" class="plain-input" :placeholder="t('model.nameHint')" autocomplete="off"
              @focus="modelOptions.length && (showModelList = true)"
              @input="modelListIndex = -1; showModelList = !!filteredModelOptions().length"
              @blur="closeModelList()"
              @keydown="onModelNameKeydown" />
            <button v-if="modelOptions.length" class="field-icon-button" tabindex="-1" :aria-label="t('model.expand')"
              @mousedown.prevent="showModelList = !showModelList" @click="modelNameInput?.focus()"><ChevronDown :size="16" /></button>
            <ul v-if="showModelList && filteredModelOptions().length" class="model-dropdown" @mousedown.prevent>
              <li v-for="(model, index) in filteredModelOptions()" :key="model" :class="{ selected: index === modelListIndex }"
                @mouseenter="modelListIndex = index" @mousedown.prevent="chooseModel(model)">{{ model }}</li>
            </ul>
          </div>
          <div class="model-list-row"><span :class="{ 'success-text': modelOptions.length }"><LoaderCircle v-if="modelBusy" :size="13" class="spin" /><CheckCircle2 v-else-if="modelOptions.length" :size="13" /><span v-else class="soft-dot"></span>{{ display(modelStatus) }}</span><button class="refresh-button" :disabled="modelBusy || !canFetchModels()" @click="refreshModels()"><RefreshCw :size="14" :class="{ spin: modelBusy }" />{{ t('model.refresh') }}</button></div>
          <div class="advanced-heading"><span>{{ t('model.advanced') }}</span><span class="muted">{{ t('common.optional') }}</span></div>
          <label class="field-label" for="max-tokens">{{ t('model.tokens') }}</label><div class="token-input-wrap"><input id="max-tokens" v-model.number="draft.max_tokens" class="plain-input" type="number" min="1" max="131072" :placeholder="t('model.defaultTokens')" /><span>tokens</span></div>
          <div class="token-presets"><button v-for="amount in [800, 2000, 4000, 8000]" :key="amount" @click="draft.max_tokens = amount">{{ amount.toLocaleString(locale) }}</button></div>
        </div>
        <footer class="dialog-footer"><span class="dialog-safe"><LockKeyhole :size="14" />{{ t('model.keyStorage') }}</span><div><button class="button button-quiet" @click="showModel = false">{{ t('common.cancel') }}</button><button class="button button-primary" @click="saveModel"><Check :size="16" />{{ t('common.save') }}</button></div></footer>
      </section>
    </div>
    <div v-if="showBinding" class="modal-backdrop" @keydown.esc="!bindingBusy && (showBinding = false)">
      <section class="model-dialog confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="binding-dialog-title">
        <header class="dialog-header"><h2 id="binding-dialog-title">{{ t('binding.confirmTitle') }}</h2><button class="small-icon" :disabled="bindingBusy" :aria-label="t('common.close')" @click="showBinding = false"><X :size="19" /></button></header>
        <div class="dialog-scroll">
          <p class="field-hint">{{ t('binding.confirmHelp') }}</p>
          <label v-for="candidate in bindingCandidates" :key="candidate.id" class="binding-candidate"><input v-model="selectedBindingId" type="radio" name="binding-candidate" :value="candidate.id" :disabled="bindingBusy" />{{ candidate.title }}</label>
          <p v-if="!bindingBusy && !bindingCandidates.length" class="field-hint">{{ t('binding.noCandidates') }}</p>
          <button class="button button-outline" :disabled="bindingBusy" @click="refreshBindingCandidates"><RefreshCw :size="15" />{{ t('binding.refresh') }}</button>
        </div>
        <footer class="dialog-footer"><button class="button button-quiet" :disabled="bindingBusy" @click="showBinding = false">{{ t('common.cancel') }}</button><button class="button button-primary" :disabled="bindingBusy || !selectedBindingId" @click="confirmBinding"><LoaderCircle v-if="bindingBusy" :size="15" class="spin" />{{ t('binding.confirm') }}</button></footer>
      </section>
    </div>
    <div v-if="pendingDelete" class="modal-backdrop" @keydown.esc="pendingDelete = null">
      <section class="model-dialog confirm-dialog" role="alertdialog" aria-modal="true" :aria-label="t('common.delete')">
        <div class="dialog-header"><h2>{{ t('model.confirmDelete', { name: pendingDelete.name }) }}</h2></div>
        <footer class="dialog-footer"><button class="button button-quiet" @click="pendingDelete = null">{{ t('common.cancel') }}</button><button class="button button-primary" @click="confirmDelete">{{ t('common.delete') }}</button></footer>
      </section>
    </div>
    <Transition name="toast"><div v-if="toast" class="toast-message" :class="{ error: toastError }"><CheckCircle2 v-if="!toastError" :size="17" /><CircleHelp v-else :size="17" />{{ display(toast) }}</div></Transition>
  </main>
</template>

<style>
.binding-controls{min-width:240px;max-width:100%}
.binding-candidate{display:flex;align-items:center;gap:10px;padding:10px 0;color:#45596f;font-size:13px;overflow-wrap:anywhere}
.setup-card{flex-wrap:wrap;gap:16px}
.settings-fields{min-width:0;margin:0;padding:0;border:0}
.input-source-panel{padding:17px 19px;margin-bottom:14px}
.input-source-toggle,.retry-actions{display:flex;flex-wrap:wrap;gap:8px}
.text-input-meta{gap:12px;align-items:flex-start;line-height:1.6}
.text-input-meta span:last-child{flex-shrink:0}
.text-input-error{color:#bc5d55;font-size:12px;line-height:1.6}
.reply-preference-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.temporary-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px}
.temporary-heading .text-action{margin:0}
.temporary-heading>span{color:#8593a4;font-size:11px}
.temporary-heading .collapsed{transform:rotate(-90deg)}
.temporary-enable{display:flex;align-items:center;gap:8px;margin-top:14px;color:#52647b;font-size:12px}
.reply-default-heading{margin:16px 0 0;color:#52647b;font-size:12px}
.analysis-task-meta{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:10px;color:#8593a4;font-size:10px;overflow-wrap:anywhere}
.cancel-analysis{width:100%;margin-top:10px}
.analysis-recovery{margin-top:12px;color:#bc5d55;font-size:12px;overflow-wrap:anywhere}
.analysis-recovery p{margin:0 0 8px;white-space:pre-wrap}
.retry-actions .button{font-size:11px;padding:8px 10px}
@media(max-width:760px){.reply-preference-fields{grid-template-columns:1fr}.text-input-meta{flex-direction:column;gap:4px}}
.update-banner{display:flex;align-items:center;gap:10px;width:100%;margin-bottom:14px;padding:10px 16px;border:1px solid #bcd9ef;border-radius:12px;background:linear-gradient(90deg,#eaf6ff,#f6fbff);color:#1f6fa8;font-size:13px;font-weight:600;cursor:pointer;text-align:left}
.update-banner:hover{background:#e0f1fd}
.update-panel .update-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:4px}
.update-panel .update-status{font-size:13px;color:#45596f}
.update-panel .update-actions{display:flex;gap:8px;flex-shrink:0}
.update-progress{height:6px;border-radius:999px;background:#e6edf4;overflow:hidden;margin-top:10px}
.update-progress-fill{height:100%;border-radius:999px;background:#2f8fd0;transition:width .3s ease}
.update-available-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:10px;font-size:13px;color:#1f6fa8;font-weight:600}
.heading-icon.green{background:#e5f6ec;color:#1f9d55}
.model-name-wrap{position:relative}
.model-name-wrap .plain-input{width:100%;padding-right:42px}
.model-name-wrap .field-icon-button{position:absolute;right:6px;top:50%;transform:translateY(-50%)}
.model-dropdown{position:absolute;z-index:10;left:0;right:0;top:calc(100% + 4px);max-height:220px;overflow-y:auto;margin:0;padding:5px;list-style:none;border:1px solid #dfe7ef;border-radius:9px;background:#fff;box-shadow:0 10px 30px rgba(30,49,72,.14)}
.model-dropdown li{padding:8px 10px;border-radius:6px;color:#45596f;font-size:12px;cursor:pointer}
.model-dropdown li.selected{background:#eaf6ff;color:#2585bf}
.suggestion-copy{flex:1;min-width:0}
.suggestion-copy p{display:block;margin:0}
.recommend-badge{display:inline-flex;align-items:center;margin-left:8px;padding:2px 7px;border-radius:10px;background:#fff0ef;color:#d94d49;font-size:9px;font-weight:700;vertical-align:1px}
.suggestion-confidence{display:flex;flex-wrap:wrap;gap:12px;margin-top:5px;color:#8292a3;font-size:10px}
.suggestion-confidence strong{color:#4d7595;font-weight:700}
</style>
