<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { checked, display, errorMessage, languages, locale, m, t } from './i18n'
import type { BridgeResult, Language, Locale, Message } from './i18n'
import { version as appVersion } from '../package.json'
import {
  ArrowLeft, ArrowRight, Bot, Check, CheckCircle2, ChevronDown, ChevronRight,
  CircleHelp, Copy, Cpu, Eye, EyeOff, KeyRound, LoaderCircle,
  LockKeyhole, MessageCircle, Plus, RefreshCw, Save,
  Settings2, ShieldCheck, Sparkles, Trash2, X,
} from '@lucide/vue'

type Profile = {
  id: string; name: string; base_url: string; model: string; max_tokens: number | null
  key_configured?: boolean; api_key?: string; protocol: string
}
type Suggestion = { text: string; probability: number | null; confidence: number | null; recommended: boolean }
type UiState = {
  language: Language; resolved_language: Locale; status_message?: Message; error_message?: Message;
  revision: number; status: string; phase: string; preview: { side: string; text: string }[]
  analysis: Record<string, any> | null; suggestions: Suggestion[]; error: string
  version: string; chat_rect: Record<string, number> | null; chat_rect_mode: string; jev_key_configured: boolean
  relationship: string; allowed_titles: string[]; profiles: Profile[]; active_model_id: string
}
type Progress = { revision: number } & Partial<Pick<UiState, 'status' | 'phase' | 'preview' | 'analysis' | 'suggestions' | 'error' | 'status_message' | 'error_message'>>
type Bridge = {
  set_language(language: Language): Promise<BridgeResult & { language: Language; resolved_language: Locale }>
  get_state(): Promise<UiState>
  get_progress(knownRevision: number): Promise<Progress>
  fetch_models(payload: string): Promise<BridgeResult & { models: string[] }>
  test_model(payload: string): Promise<BridgeResult & { message: string; message_message?: Message }>
  save_settings(payload: string): Promise<UiState & BridgeResult>
  start_calibration(): Promise<BridgeResult>
  analyze(): Promise<BridgeResult>
  set_on_top(value: boolean): Promise<{ ok: boolean }>
  set_active_model(profileId: string): Promise<BridgeResult>
  copy_text(value: string): Promise<BridgeResult>
}
declare global { interface Window { pywebview?: { api: Bridge } } }

const bridge = () => window.pywebview?.api
const initial: UiState = {
  language: 'system', resolved_language: 'zh-CN', status_message: m('status.initial'),
  revision: 0, status: '', phase: 'idle', preview: [], analysis: null,
  suggestions: [], error: '', version: appVersion, chat_rect: null, chat_rect_mode: 'screen', jev_key_configured: false,
  relationship: '对方是我的朋友；from=me 是我发的，from=other 是对方发的', allowed_titles: [],
  profiles: [], active_model_id: '',
}
const state = reactive<UiState>({ ...initial })
const page = ref<'home' | 'settings'>('home')
const showModel = ref(false)
const pendingDelete = ref<Profile | null>(null)
const languageBusy = ref(false)
const editingId = ref('')
const busy = ref(false)
const topmost = ref(true)
const toast = ref<Message | string>('')
const toastError = ref(false)
let toastTimer: number | undefined
let pollTimer: number | undefined
let trackingState = false
let progressRevision = -1
let polling = false

const draft = reactive<Profile>({ id: '', name: '', base_url: '', model: '', max_tokens: 400, key_configured: false, api_key: '', protocol: 'openai-chat' })
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
function applyState(next: UiState) {
  const previousRevision = progressRevision
  progressRevision = next.revision
  Object.assign(state, next)
  state.status_message = next.status_message
  state.error_message = next.error_message
  locale.value = next.resolved_language ?? 'zh-CN'
  if (trackingState && next.revision !== previousRevision && (next.phase === 'idle' || next.phase === 'error')) {
    trackingState = false
  }
}
async function loadState() {
  try {
    if (bridge()) applyState(await bridge()!.get_state())
  } catch (error) { notify(errorMessage(error), true) }
}
async function pollProgress() {
  if (!trackingState || page.value !== 'home' || polling || !bridge()) return
  polling = true
  try {
    const previousRevision = progressRevision
    const result = await bridge()!.get_progress(previousRevision)
    if (result.revision !== previousRevision) {
      progressRevision = result.revision
      state.revision = result.revision
      const { revision, ...changes } = result
      Object.assign(state, changes)
      if ('status' in changes) state.status_message = changes.status_message
      if ('error' in changes) state.error_message = changes.error_message
      if (state.phase === 'idle' || state.phase === 'error') trackingState = false
    }
  } catch { /* Retry after the window reappears from capture. */ }
  finally { polling = false }
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
  showModel.value = true
}
function editModel(item: Profile) {
  editingId.value = item.id
  Object.assign(draft, { ...item, api_key: '' })
  modelOptions.value = []
  modelStatus.value = item.key_configured ? m('key.savedHint') : m('model.listHintEdit')
  showModel.value = true
}
function chooseProvider(value: string) {
  if (value === 'deepseek') {
    draft.protocol = 'openai-chat'
    draft.name = 'DeepSeek'
    draft.base_url = 'https://api.deepseek.com'
    if (!draft.model) draft.model = 'deepseek-flash'
    return
  }
  draft.protocol = value
  const defaults: Record<string, string> = { 'openai-chat': 'OpenAI Chat', 'openai-responses': 'OpenAI Responses', anthropic: 'Anthropic' }
  draft.name = defaults[value] || t('model.custom')
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
    modelOptions.value = []
    modelStatus.value = m('model.manual', { detail: readableError(error) })
  } finally {
    if (token === requestNo) modelBusy.value = false
  }
}
watch(() => draft.base_url, (value, old) => {
  const normalized = normalizeEndpointUrl(value, draft.protocol)
  if (normalized !== value.trim()) { draft.base_url = normalized; return }
  if (old && value.trim() !== old.trim()) {
    draft.api_key = ''
    modelOptions.value = []
    closeModelList()
    modelStatus.value = m('model.urlChanged')
    requestNo++
    modelBusy.value = false
  }
  window.clearTimeout(addressTimer)
  if (value.trim() && canFetchModels()) addressTimer = window.setTimeout(() => refreshModels(), 700)
})
watch(() => draft.api_key, value => {
  window.clearTimeout(keyTimer)
  if (value?.trim() && /^https?:\/\//i.test(draft.base_url.trim())) keyTimer = window.setTimeout(() => refreshModels(), 700)
})
watch(() => draft.protocol, () => {
  requestNo++
  modelOptions.value = []
  closeModelList()
  const normalized = normalizeEndpointUrl(draft.base_url, draft.protocol)
  if (normalized !== draft.base_url.trim()) draft.base_url = normalized
  if (canFetchModels()) window.setTimeout(() => refreshModels(), 200)
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
  if (busy.value) return
  busy.value = true
  try {
    const next = checked(await bridge()!.save_settings(JSON.stringify({
      jev_api_key: jevKey.value, clear_jev_key: clearJevKey.value,
      relationship: state.relationship,
      allowed_titles: state.allowed_titles,
      active_model_id: state.active_model_id,
      profiles: state.profiles,
    })))
    applyState(next)
    jevKey.value = ''
    clearJevKey.value = false
    page.value = 'home'
    notify(m('settings.saved'))
  } catch (error) { notify(readableError(error), true) }
  finally { busy.value = false }
}
async function calibrate() {
  try {
    const result = await bridge()!.start_calibration()
    if (!result.ok) notify(result.error_message ?? m('capture.failed'), true)
    else { trackingState = true; notify(m('capture.drag')) }
  } catch (error) { notify(errorMessage(error), true) }
}
async function analyze() {
  try {
    trackingState = true
    const result = await bridge()!.analyze()
    if (!result.ok) { trackingState = false; notify(result.error_message ?? m('analysis.failed'), true) }
    else {
      state.phase = 'capturing'
      state.status_message = m('analysis.capturing')
      notify(m('analysis.started'))
    }
  } catch (error) { notify(errorMessage(error), true) }
}
async function toggleTopmost() {
  topmost.value = !topmost.value
  try { await bridge()?.set_on_top(topmost.value) } catch { /* browser preview */ }
}
async function selectActiveModel() {
  try { if (bridge()) checked(await bridge()!.set_active_model(state.active_model_id)) }
  catch (error) { notify(errorMessage(error), true) }
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
  pollTimer = window.setInterval(() => { void pollProgress() }, 850)
})
onBeforeUnmount(() => { window.removeEventListener('pywebviewready', loadState); window.clearInterval(pollTimer); window.clearTimeout(toastTimer); window.clearTimeout(addressTimer); window.clearTimeout(keyTimer) })
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
      <section class="welcome-row">
        <div><div class="eyebrow">{{ t('home.eyebrow') }} <span class="version-pill">v{{ state.version }}</span></div><h1>{{ t('home.title') }}</h1><p>{{ t('home.subtitle') }}</p></div>
        <div class="jev-badge"><ShieldCheck :size="18" /><span>{{ t('home.safety') }}</span></div>
      </section>

      <section class="setup-card surface">
        <div class="setup-copy"><div class="setup-icon"><MessageCircle :size="18" /></div><div><h2>{{ t('capture.title') }}</h2><p>{{ state.chat_rect_mode === 'wechat-client' ? t('capture.legacy') : state.chat_rect ? t('capture.ready') : t('capture.help') }}</p></div></div>
        <div class="setup-actions"><span v-if="state.chat_rect && state.chat_rect_mode !== 'wechat-client'" class="ready-chip"><CheckCircle2 :size="15" /> {{ t('capture.calibrated') }}</span><button class="button button-outline" @click="calibrate">{{ state.chat_rect && state.chat_rect_mode !== 'wechat-client' ? t('capture.again') : t('capture.select') }} <ArrowRight :size="15" /></button></div>
      </section>

      <div class="content-grid">
        <section class="surface analysis-card">
          <div class="section-heading"><div class="heading-icon blue"><Sparkles :size="17" /></div><div><h2>{{ t('analysis.title') }}</h2><p>{{ t('analysis.help') }}</p></div></div>
          <div class="status-line" :class="statusTone"><span class="status-dot"><LoaderCircle v-if="state.phase !== 'idle' && state.phase !== 'error'" :size="15" class="spin" /><span v-else></span></span><span>{{ display(state.status_message ?? state.status) }}</span></div>
          <button class="button button-primary analyze-button" :disabled="state.phase !== 'idle' && state.phase !== 'error'" @click="analyze"><Sparkles :size="17" />{{ state.phase !== 'idle' && state.phase !== 'error' ? t('analysis.busy') : t('analysis.start') }}<ArrowRight v-if="state.phase === 'idle' || state.phase === 'error'" :size="17" /></button>
          <div class="privacy-note"><LockKeyhole :size="14" />{{ t('analysis.privacy') }}</div>
        </section>

        <section class="surface model-card">
          <div class="section-heading"><div class="heading-icon violet"><Cpu :size="17" /></div><div><h2>{{ t('model.title') }}</h2><p>{{ t('model.help') }}</p></div></div>
          <label class="field-label" for="active-model">{{ t('model.current') }}</label>
          <div class="select-wrap"><select id="active-model" v-model="state.active_model_id" :disabled="!state.profiles.length" @change="selectActiveModel"><option value="" disabled>{{ t('model.choose') }}</option><option v-for="profile in state.profiles" :key="profile.id" :value="profile.id">{{ profile.name }} · {{ profile.model }}</option></select><ChevronDown :size="16" /></div>
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
          <section class="surface settings-panel">
            <div class="panel-heading"><div class="heading-icon blue"><ShieldCheck :size="17" /></div><div><h2>{{ t('settings.service') }}</h2><p>{{ t('settings.serviceHelp') }}</p></div><span class="required-tag">{{ t('settings.independent') }}</span></div>
          <label class="field-label" for="jev-key">Jev / TypeSafe API Key</label><div class="input-with-icon"><KeyRound :size="16" /><input id="jev-key" v-model="jevKey" :type="jevKeyVisible ? 'text' : 'password'" autocomplete="new-password" :placeholder="state.jev_key_configured ? t('key.savedHint') : t('key.jevPlaceholder')" /><button class="field-icon-button" :aria-label="jevKeyVisible ? t('key.hide') : t('key.show')" @click="jevKeyVisible = !jevKeyVisible"><EyeOff v-if="jevKeyVisible" :size="16" /><Eye v-else :size="16" /></button></div>
            <div class="field-hint"><span><span class="online-dot"></span>{{ state.jev_key_configured && !clearJevKey ? t('key.local') : t('key.jevOnly') }}</span><button v-if="state.jev_key_configured" class="danger-link" @click="clearJevKey = !clearJevKey">{{ clearJevKey ? t('key.undo') : t('key.clear') }}</button></div>
          </section>

          <section class="surface settings-panel models-panel">
            <div class="panel-heading"><div class="heading-icon violet"><Cpu :size="17" /></div><div><h2>{{ t('model.title') }}</h2><p>{{ t('model.protocolHelp') }}</p></div><span class="count-pill">{{ t('model.count', { count: state.profiles.length }) }}</span></div>
            <div v-if="state.profiles.length" class="configured-models"><article v-for="profile in state.profiles" :key="profile.id" class="configured-model" :class="{ active: profile.id === state.active_model_id }"><button class="radio-mark" :aria-label="t('common.select', { name: profile.name })" @click="state.active_model_id = profile.id"><Check v-if="profile.id === state.active_model_id" :size="13" /></button><button class="configured-main" @click="state.active_model_id = profile.id"><span class="configured-name">{{ profile.name }}<span v-if="profile.id === state.active_model_id" class="active-tag">{{ t('model.active') }}</span></span><span class="configured-model-id">{{ profile.model }}</span><span class="configured-endpoint">{{ profile.base_url }}</span></button><span class="key-state" :class="{ ready: profile.key_configured || !!profile.api_key }"><KeyRound :size="13" />{{ profile.key_configured || profile.api_key ? t('key.configured') : t('key.missing') }}</span><button class="small-icon" :title="t('common.edit')" @click="editModel(profile)"><Settings2 :size="15" /></button><button class="small-icon delete-icon" :title="t('common.delete')" @click="removeModel(profile)"><Trash2 :size="15" /></button></article></div>
            <div v-else class="models-empty"><Bot :size="20" /><span>{{ t('model.empty') }}</span><small>{{ t('model.emptyHelp') }}</small></div>
            <button class="add-model-button" @click="addModel"><Plus :size="16" />{{ t('model.addConfig') }}</button>
          </section>

          <section class="surface settings-panel">
            <div class="panel-heading"><div class="heading-icon amber"><MessageCircle :size="17" /></div><div><h2>{{ t('settings.preferences') }}</h2><p>{{ t('settings.contextHelp') }}</p></div></div>
            <label class="field-label" for="relationship">{{ t('settings.relationship') }}</label><textarea id="relationship" v-model="state.relationship" rows="3" :placeholder="t('settings.relationshipHint')"></textarea>
            <label class="field-label spaced" for="allowed-titles">{{ t('settings.allowlist') }}</label><input id="allowed-titles" class="plain-input" :value="state.allowed_titles.join('，')" :placeholder="t('settings.allowlistHint')" @input="state.allowed_titles = ($event.target as HTMLInputElement).value.replaceAll(',', '，').split('，').map(item => item.trim()).filter(Boolean)" />
            <div class="field-hint">{{ t('settings.allowlistHelp') }}</div>
          </section>
          <div class="save-bar"><span><LockKeyhole :size="14" />{{ t('settings.storage') }}</span><button class="button button-primary" :disabled="busy || languageBusy" @click="saveSettings"><LoaderCircle v-if="busy" :size="16" class="spin" /><Save v-else :size="16" />{{ busy ? t('settings.saving') : t('settings.save') }}</button></div>
        </div>
      </div>
    </template>

    <footer class="app-footer"><span>{{ t('app.name') }} <span class="footer-divider">·</span> {{ t('footer.promise') }}</span><button @click="notify(m('footer.notice'))"><CircleHelp :size="14" /> {{ t('footer.help') }}</button></footer>

    <div v-if="showModel" class="modal-backdrop">
      <section class="model-dialog" role="dialog" aria-modal="true" :aria-label="editingId ? t('model.edit') : t('model.add')">
        <header class="dialog-header"><div><div class="dialog-kicker">{{ t('model.eyebrow') }}</div><h2>{{ editingId ? t('model.edit') : t('model.add') }}</h2></div><button class="small-icon" :aria-label="t('common.close')" @click="showModel = false"><X :size="19" /></button></header>
        <div class="dialog-scroll">
          <label class="field-label" for="provider">{{ t('model.protocol') }}</label><div class="select-wrap provider-select"><select id="provider" :value="draft.name === 'DeepSeek' ? 'deepseek' : draft.protocol" @change="chooseProvider(($event.target as HTMLSelectElement).value)"><option value="openai-chat">openai-chat</option><option value="openai-responses">openai-responses</option><option value="anthropic">anthropic</option><option value="deepseek">DeepSeek（openai-chat）</option></select><ChevronDown :size="16" /></div>
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
