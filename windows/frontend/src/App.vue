<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
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
  revision: number; status: string; phase: string; preview: { side: string; text: string }[]
  analysis: Record<string, any> | null; suggestions: Suggestion[]; error: string
  version: string; chat_rect: Record<string, number> | null; chat_rect_mode: string; jev_key_configured: boolean
  relationship: string; allowed_titles: string[]; profiles: Profile[]; active_model_id: string
}
type Progress = { revision: number } & Partial<Pick<UiState, 'status' | 'phase' | 'preview' | 'analysis' | 'suggestions' | 'error'>>
type Bridge = {
  get_state(): Promise<UiState>
  get_progress(knownRevision: number): Promise<Progress>
  fetch_models(payload: string): Promise<{ models: string[] }>
  test_model(payload: string): Promise<{ message: string }>
  save_settings(payload: string): Promise<UiState>
  start_calibration(): Promise<{ ok: boolean; error?: string }>
  analyze(): Promise<{ ok: boolean; error?: string }>
  set_on_top(value: boolean): Promise<{ ok: boolean }>
  set_active_model(profileId: string): Promise<{ ok: boolean }>
  copy_text(value: string): Promise<{ ok: boolean }>
}
declare global { interface Window { pywebview?: { api: Bridge } } }

const bridge = () => window.pywebview?.api
const initial: UiState = {
  revision: 0, status: '请先配置 Jev API 并框选聊天区域', phase: 'idle', preview: [], analysis: null,
  suggestions: [], error: '', version: '1.0.0', chat_rect: null, chat_rect_mode: 'screen', jev_key_configured: false,
  relationship: '对方是我的朋友；from=me 是我发的，from=other 是对方发的', allowed_titles: [],
  profiles: [], active_model_id: '',
}
const state = reactive<UiState>({ ...initial })
const page = ref<'home' | 'settings'>('home')
const showModel = ref(false)
const editingId = ref('')
const busy = ref(false)
const topmost = ref(true)
const toast = ref('')
const toastError = ref(false)
let toastTimer: number | undefined
let pollTimer: number | undefined
let trackingState = false
let progressRevision = -1
let polling = false

const draft = reactive<Profile>({ id: '', name: '', base_url: '', model: '', max_tokens: 400, key_configured: false, api_key: '', protocol: 'openai-chat' })
const draftKeyVisible = ref(false)
const modelOptions = ref<string[]>([])
const modelStatus = ref('填写接口地址后自动读取模型列表')
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

function notify(message: string, isError = false) {
  toast.value = message
  toastError.value = isError
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 3000)
}
function readableError(error: unknown) {
  return String(error).replace(/^\w*Error:\s*/, '')
}
function applyState(next: UiState) {
  const previousRevision = progressRevision
  progressRevision = next.revision
  Object.assign(state, next)
  if (trackingState && next.revision !== previousRevision && (next.phase === 'idle' || next.phase === 'error')) {
    trackingState = false
  }
}
async function loadState() {
  try {
    if (bridge()) applyState(await bridge()!.get_state())
  } catch (error) { notify(String(error), true) }
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
  modelStatus.value = '填写接口地址后自动读取模型列表'
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
  modelStatus.value = item.key_configured ? '已保存密钥；留空保持不变' : '填写接口地址后拉取模型列表'
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
  draft.name = defaults[value] || '自定义模型'
}
function canFetchModels() { return /^https?:\/\//i.test(draft.base_url.trim()) }
async function refreshModels() {
  if (!canFetchModels()) { modelStatus.value = '填写接口地址后自动读取模型列表'; return }
  const url = draft.base_url.trim()
  const token = ++requestNo
  modelBusy.value = true
  modelStatus.value = '正在读取模型列表…'
  try {
    if (!bridge()) throw new Error('桌面连接不可用')
    const result = await bridge()!.fetch_models(JSON.stringify({ profile_id: editingId.value, base_url: url, api_key: draft.api_key?.trim() || '', protocol: draft.protocol }))
    if (token !== requestNo || url !== draft.base_url.trim()) return
    modelOptions.value = result.models
    modelStatus.value = `已找到 ${result.models.length} 个模型`
  } catch (error) {
    if (token !== requestNo || url !== draft.base_url.trim()) return
    modelOptions.value = []
    modelStatus.value = `${readableError(error)} 可手动填写模型名称。`
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
    modelStatus.value = '接口地址已变化，请重新读取模型列表'
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
  if (!draft.model.trim()) { notify('请先填写或选择模型名称', true); return }
  testing.value = true
  try {
    const result = await bridge()!.test_model(JSON.stringify({ profile_id: editingId.value, base_url: draft.base_url.trim(), model: draft.model.trim(), api_key: draft.api_key?.trim() || '', protocol: draft.protocol }))
    notify(`连接成功：${result.message || '模型已响应'}`)
  } catch (error) { notify(readableError(error), true) }
  finally { testing.value = false }
}
function saveModel() {
  if (!draft.name.trim() || !draft.base_url.trim() || !draft.model.trim()) { notify('请填写供应商名称、接口地址和模型名称', true); return }
  const id = editingId.value || crypto.randomUUID()
  const next: Profile = { ...draft, id, name: draft.name.trim(), base_url: draft.base_url.trim(), model: draft.model.trim(), max_tokens: Number(draft.max_tokens) || null }
  delete next.key_configured
  const index = state.profiles.findIndex(item => item.id === id)
  if (index >= 0) state.profiles.splice(index, 1, next)
  else state.profiles.push(next)
  if (!state.active_model_id) state.active_model_id = id
  showModel.value = false
  notify('模型配置已暂存，请保存设置')
}
function removeModel(item: Profile) {
  if (!window.confirm(`删除“${item.name}”模型配置？`)) return
  state.profiles = state.profiles.filter(profile => profile.id !== item.id)
  if (state.active_model_id === item.id) state.active_model_id = state.profiles[0]?.id || ''
}
async function saveSettings() {
  if (busy.value) return
  busy.value = true
  try {
    const next = await bridge()!.save_settings(JSON.stringify({
      jev_api_key: jevKey.value, clear_jev_key: clearJevKey.value,
      relationship: state.relationship,
      allowed_titles: state.allowed_titles,
      active_model_id: state.active_model_id,
      profiles: state.profiles,
    }))
    applyState(next)
    jevKey.value = ''
    clearJevKey.value = false
    page.value = 'home'
    notify('设置已安全保存')
  } catch (error) { notify(readableError(error), true) }
  finally { busy.value = false }
}
async function calibrate() {
  try {
    const result = await bridge()!.start_calibration()
    if (!result.ok) notify(result.error || '无法开始框选', true)
    else { trackingState = true; notify('请在微信窗口拖动框选聊天消息区域') }
  } catch (error) { notify(String(error), true) }
}
async function analyze() {
  try {
    trackingState = true
    const result = await bridge()!.analyze()
    if (!result.ok) { trackingState = false; notify(result.error || '无法开始分析', true) }
    else {
      state.phase = 'capturing'
      state.status = '正在截取对话…'
      notify('已开始分析当前对话')
    }
  } catch (error) { notify(String(error), true) }
}
async function toggleTopmost() {
  topmost.value = !topmost.value
  try { await bridge()?.set_on_top(topmost.value) } catch { /* browser preview */ }
}
async function selectActiveModel() {
  try { await bridge()?.set_active_model(state.active_model_id) }
  catch (error) { notify(String(error), true) }
}
async function copyReply(reply: string) {
  try {
    if (bridge()) await bridge()!.copy_text(reply)
    else await navigator.clipboard.writeText(reply)
    notify('建议回复已复制，请检查后自行发送')
  } catch { notify('复制失败，请手动选择文本', true) }
}
const intentLabels: Record<string, string> = {
  confirm_you_care: '确认你是否在乎', vent_anger: '表达生气或受伤', request_action: '要求具体行动',
  seek_explanation: '寻求解释', casual_chat: '轻松聊天', close_topic: '结束话题',
}
const needLabels: Record<string, string> = { apology: '道歉', action: '行动', explanation: '解释', care: '被重视', nothing: '无需追加' }
const actionLabels: Record<string, string> = {
  check_history: '先查聊天记录', apologize: '真诚道歉', give_commitment: '给出具体承诺',
  explain: '解释事实', acknowledge: '先接住情绪', say_less: '少说一点', make_plan: '确定计划',
}
function percent(value: number | null | undefined) { return value == null ? '—' : `${Math.round(value * 100)}%` }
function danger(value: number | null | undefined) { return value == null ? '—' : `${value.toFixed(1)}/9` }

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
        <div><div class="brand-name">Jev <span>对话助手</span></div><div class="brand-caption">CONVERSATION COMPANION</div></div>
      </div>
      <div class="top-actions">
        <button class="icon-button" :class="{ selected: topmost }" :title="topmost ? '取消窗口置顶' : '窗口置顶'" @click="toggleTopmost"><Eye :size="17" /></button>
        <button class="button button-quiet" @click="page = page === 'settings' ? 'home' : 'settings'"><Settings2 :size="16" /> 设置</button>
      </div>
    </header>

    <template v-if="page === 'home'">
      <section class="welcome-row">
        <div><div class="eyebrow">你的对话副驾 <span class="version-pill">v{{ state.version }}</span></div><h1>把对话看清楚，再决定怎么回应。</h1><p>只给建议，由你判断。所有消息不会自动发送。</p></div>
        <div class="jev-badge"><ShieldCheck :size="18" /><span>Jev 安全判断</span></div>
      </section>

      <section class="setup-card surface">
        <div class="setup-copy"><div class="setup-icon"><MessageCircle :size="18" /></div><div><h2>选择对话区域</h2><p>{{ state.chat_rect_mode === 'wechat-client' ? '升级后请重新框选一次，之后可在任意桌面聊天应用上使用。' : state.chat_rect ? '桌面区域已校准；移动窗口或切换显示器后可重新框选。' : '打开任意聊天应用，框选屏幕上可见的对话消息。' }}</p></div></div>
        <div class="setup-actions"><span v-if="state.chat_rect && state.chat_rect_mode !== 'wechat-client'" class="ready-chip"><CheckCircle2 :size="15" /> 已校准</span><button class="button button-outline" @click="calibrate">{{ state.chat_rect && state.chat_rect_mode !== 'wechat-client' ? '重新选择' : '框选对话区域' }} <ArrowRight :size="15" /></button></div>
      </section>

      <div class="content-grid">
        <section class="surface analysis-card">
          <div class="section-heading"><div class="heading-icon blue"><Sparkles :size="17" /></div><div><h2>对话分析</h2><p>读取已框选的桌面消息，获取 Jev 判断和建议回复</p></div></div>
          <div class="status-line" :class="statusTone"><span class="status-dot"><LoaderCircle v-if="state.phase !== 'idle' && state.phase !== 'error'" :size="15" class="spin" /><span v-else></span></span><span>{{ state.status }}</span></div>
          <button class="button button-primary analyze-button" :disabled="state.phase !== 'idle' && state.phase !== 'error'" @click="analyze"><Sparkles :size="17" />{{ state.phase !== 'idle' && state.phase !== 'error' ? '正在分析…' : '分析当前选区' }}<ArrowRight v-if="state.phase === 'idle' || state.phase === 'error'" :size="17" /></button>
          <div class="privacy-note"><LockKeyhole :size="14" />选区 OCR 在本机完成；点击分析后才发送识别文字进行判断和回复生成。</div>
        </section>

        <section class="surface model-card">
          <div class="section-heading"><div class="heading-icon violet"><Cpu :size="17" /></div><div><h2>回复模型</h2><p>独立选择生成建议的模型</p></div></div>
          <label class="field-label" for="active-model">当前模型</label>
          <div class="select-wrap"><select id="active-model" v-model="state.active_model_id" :disabled="!state.profiles.length" @change="selectActiveModel"><option value="" disabled>选择一个模型</option><option v-for="profile in state.profiles" :key="profile.id" :value="profile.id">{{ profile.name }} · {{ profile.model }}</option></select><ChevronDown :size="16" /></div>
          <div v-if="activeProfile" class="model-meta"><span class="online-dot"></span><span>{{ activeProfile.name }}</span><span class="meta-separator">/</span><span class="model-id">{{ activeProfile.model }}</span></div>
          <button class="text-action" @click="page = 'settings'"><Settings2 :size="15" />管理模型配置 <ArrowRight :size="14" /></button>
        </section>
      </div>

      <div class="results-grid">
        <section class="surface result-card messages-card">
          <div class="result-heading"><div><span class="eyebrow">RECENT MESSAGES</span><h2>识别到的对话</h2></div><span class="count-pill">{{ state.preview.length }} 条</span></div>
          <div v-if="state.preview.length" class="message-list"><div v-for="(message, index) in state.preview" :key="index" class="message-row" :class="message.side"><span class="message-avatar">{{ message.side === 'me' ? '我' : '对' }}</span><div class="message-bubble"><span class="speaker">{{ message.side === 'me' ? '我' : '对方' }}</span><span>{{ message.text }}</span></div></div></div>
          <div v-else class="empty-state"><div class="empty-icon"><MessageCircle :size="20" /></div><span>分析后，最近识别的消息会显示在这里</span></div>
        </section>
        <section class="surface result-card judgement-card">
          <div class="result-heading"><div><span class="eyebrow">JEV INSIGHT</span><h2>对话判断</h2></div><span v-if="state.analysis" class="confidence-pill"><ShieldCheck :size="14" /> 已完成</span></div>
          <template v-if="state.analysis">
            <div class="insight-primary"><div class="insight-label">对方的真实意图</div><div class="intent-value">{{ intentLabels[state.analysis.true_intent] || state.analysis.true_intent || '—' }}</div><div class="danger-meter"><span>危险程度</span><strong>{{ danger(state.analysis.danger_level) }}</strong></div></div>
            <div class="insight-stats"><div><span>对方需要</span><strong>{{ needLabels[state.analysis.need] || state.analysis.need || '—' }}</strong></div><div><span>建议动作</span><strong>{{ actionLabels[state.analysis.best_action] || state.analysis.best_action || '—' }}</strong></div><div><span>需要实质回复</span><strong>{{ percent(state.analysis.should_reply_now) }}</strong></div><div><span>紧张已化解</span><strong>{{ percent(state.analysis.tension_resolved) }}</strong></div></div>
            <div class="latency">判断耗时 {{ state.analysis.latency_ms }} ms</div>
          </template>
          <div v-else class="empty-state"><div class="empty-icon"><ShieldCheck :size="20" /></div><span>完成一次分析后，这里会显示 Jev 的判断</span></div>
        </section>
      </div>

      <section class="surface suggestions-section">
        <div class="result-heading"><div><span class="eyebrow">SUGGESTED REPLIES</span><h2>建议回复</h2></div><span class="suggestion-caption">参考建议，请按你的判断修改</span></div>
        <div v-if="state.suggestions.length" class="suggestion-list"><article v-for="(suggestion, index) in state.suggestions" :key="index" class="suggestion-item"><span class="suggestion-number">0{{ index + 1 }}</span><div class="suggestion-copy"><p>{{ suggestion.text }}<span v-if="suggestion.recommended" class="recommend-badge">推荐</span></p><div class="suggestion-confidence"><span>Jev 推荐度 <strong>{{ percent(suggestion.probability) }}</strong></span><span v-if="suggestion.confidence !== null">Jev 置信度 <strong>{{ percent(suggestion.confidence) }}</strong></span></div></div><button class="copy-button" @click="copyReply(suggestion.text)"><Copy :size="15" />复制</button></article></div>
        <div v-else class="suggestion-empty"><Sparkles :size="16" />{{ state.profiles.length ? '完成分析和 Jev 评估后，这里会显示回复建议及推荐度。' : '添加一个回复模型后，即可生成和比较候选回复。' }}<button class="inline-link" @click="page = 'settings'">配置模型 <ArrowRight :size="13" /></button></div>
      </section>
    </template>

    <template v-else>
      <section class="settings-heading"><button class="back-button" @click="page = 'home'"><ArrowLeft :size="17" /></button><div><div class="eyebrow">PREFERENCES</div><h1>设置</h1><p>管理判断服务、回复模型与对话偏好</p></div></section>
      <div class="settings-layout">
        <nav class="settings-nav"><a class="nav-item current"><ShieldCheck :size="16" /> Jev 判断 <ChevronRight :size="15" /></a><a class="nav-item"><Bot :size="16" /> 回复模型 <ChevronRight :size="15" /></a><a class="nav-item"><MessageCircle :size="16" /> 对话偏好 <ChevronRight :size="15" /></a><div class="nav-tip"><LockKeyhole :size="15" /><span>API Key 安全保存在 Windows 凭据管理器中，不会写入设置文件。</span></div></nav>
        <div class="settings-content">
          <section class="surface settings-panel">
            <div class="panel-heading"><div class="heading-icon blue"><ShieldCheck :size="17" /></div><div><h2>Jev 判断服务</h2><p>使用 TypeSafe Jev 进行结构化对话判断</p></div><span class="required-tag">独立配置</span></div>
          <label class="field-label" for="jev-key">Jev / TypeSafe API Key</label><div class="input-with-icon"><KeyRound :size="16" /><input id="jev-key" v-model="jevKey" :type="jevKeyVisible ? 'text' : 'password'" autocomplete="new-password" :placeholder="state.jev_key_configured ? '已保存密钥；留空保持不变' : '输入 TypeSafe API Key'" /><button class="field-icon-button" :aria-label="jevKeyVisible ? '隐藏密钥' : '显示密钥'" @click="jevKeyVisible = !jevKeyVisible"><EyeOff v-if="jevKeyVisible" :size="16" /><Eye v-else :size="16" /></button></div>
            <div class="field-hint"><span><span class="online-dot"></span>{{ state.jev_key_configured && !clearJevKey ? '密钥已保存在本机' : '密钥仅用于 Jev 判断' }}</span><button v-if="state.jev_key_configured" class="danger-link" @click="clearJevKey = !clearJevKey">{{ clearJevKey ? '撤销清除' : '清除密钥' }}</button></div>
          </section>

          <section class="surface settings-panel models-panel">
            <div class="panel-heading"><div class="heading-icon violet"><Cpu :size="17" /></div><div><h2>回复模型</h2><p>可按 OpenAI Chat、Responses 或 Anthropic 协议接入</p></div><span class="count-pill">{{ state.profiles.length }} 个配置</span></div>
            <div v-if="state.profiles.length" class="configured-models"><article v-for="profile in state.profiles" :key="profile.id" class="configured-model" :class="{ active: profile.id === state.active_model_id }"><button class="radio-mark" :aria-label="`选择 ${profile.name}`" @click="state.active_model_id = profile.id"><Check v-if="profile.id === state.active_model_id" :size="13" /></button><button class="configured-main" @click="state.active_model_id = profile.id"><span class="configured-name">{{ profile.name }}<span v-if="profile.id === state.active_model_id" class="active-tag">当前使用</span></span><span class="configured-model-id">{{ profile.model }}</span><span class="configured-endpoint">{{ profile.base_url }}</span></button><span class="key-state" :class="{ ready: profile.key_configured || !!profile.api_key }"><KeyRound :size="13" />{{ profile.key_configured || profile.api_key ? '密钥已设置' : '缺少密钥' }}</span><button class="small-icon" title="编辑" @click="editModel(profile)"><Settings2 :size="15" /></button><button class="small-icon delete-icon" title="删除" @click="removeModel(profile)"><Trash2 :size="15" /></button></article></div>
            <div v-else class="models-empty"><Bot :size="20" /><span>还没有配置回复模型</span><small>添加兼容 OpenAI API 的模型，用于起草候选回复。</small></div>
            <button class="add-model-button" @click="addModel"><Plus :size="16" />添加模型配置</button>
          </section>

          <section class="surface settings-panel">
            <div class="panel-heading"><div class="heading-icon amber"><MessageCircle :size="17" /></div><div><h2>对话偏好</h2><p>帮助 Jev 和回复模型更了解你的场景</p></div></div>
            <label class="field-label" for="relationship">关系说明</label><textarea id="relationship" v-model="state.relationship" rows="3" placeholder="例如：对方是我的朋友"></textarea>
            <label class="field-label spaced" for="allowed-titles">会话白名单</label><input id="allowed-titles" class="plain-input" :value="state.allowed_titles.join('，')" placeholder="逗号分隔；留空允许所有会话" @input="state.allowed_titles = ($event.target as HTMLInputElement).value.replaceAll(',', '，').split('，').map(item => item.trim()).filter(Boolean)" />
            <div class="field-hint">仅允许分析标题包含指定文字的会话</div>
          </section>
          <div class="save-bar"><span><LockKeyhole :size="14" />设置与密钥分别安全保存</span><button class="button button-primary" :disabled="busy" @click="saveSettings"><LoaderCircle v-if="busy" :size="16" class="spin" /><Save v-else :size="16" />{{ busy ? '正在保存…' : '保存设置' }}</button></div>
        </div>
      </div>
    </template>

    <footer class="app-footer"><span>Jev 对话助手 <span class="footer-divider">·</span> 只辅助，不代发</span><button @click="notify('所有建议都需要你自行判断，不会自动发送。')"><CircleHelp :size="14" /> 使用说明</button></footer>

    <div v-if="showModel" class="modal-backdrop">
      <section class="model-dialog">
        <header class="dialog-header"><div><div class="dialog-kicker">MODEL PROVIDER</div><h2>{{ editingId ? '编辑模型' : '添加模型' }}</h2></div><button class="small-icon" aria-label="关闭" @click="showModel = false"><X :size="19" /></button></header>
        <div class="dialog-scroll">
          <label class="field-label" for="provider">接口协议 / 供应商</label><div class="select-wrap provider-select"><select id="provider" :value="draft.name === 'DeepSeek' ? 'deepseek' : draft.protocol" @change="chooseProvider(($event.target as HTMLSelectElement).value)"><option value="openai-chat">openai-chat</option><option value="openai-responses">openai-responses</option><option value="anthropic">anthropic</option><option value="deepseek">DeepSeek（openai-chat）</option></select><ChevronDown :size="16" /></div>
          <label class="field-label" for="provider-name">显示名称</label><input id="provider-name" v-model="draft.name" class="plain-input" placeholder="例如：我的模型服务" />
          <label class="field-label" for="base-url">接口地址</label><input id="base-url" v-model="draft.base_url" class="plain-input" :placeholder="endpointPlaceholder" autocomplete="url" />
          <label class="field-label" for="model-key">API Key</label><div class="key-entry-row"><div class="input-with-icon key-input"><KeyRound :size="16" /><input id="model-key" v-model="draft.api_key" :type="draftKeyVisible ? 'text' : 'password'" autocomplete="new-password" :placeholder="editingId && draft.key_configured ? '已保存密钥；留空保持不变' : '输入此接口的 API Key'" /><button class="field-icon-button" @click="draftKeyVisible = !draftKeyVisible"><EyeOff v-if="draftKeyVisible" :size="16" /><Eye v-else :size="16" /></button></div><button class="button button-outline test-button" :disabled="testing || !draft.base_url || !draft.model" @click="testConnection"><LoaderCircle v-if="testing" :size="15" class="spin" /><span v-else>测试连接</span></button></div>
          <label class="field-label" for="model-name">模型名称</label>
          <div class="model-name-wrap">
            <input id="model-name" ref="modelNameInput" v-model="draft.model" class="plain-input" placeholder="输入或选择模型，例如 gpt-4o" autocomplete="off"
              @focus="modelOptions.length && (showModelList = true)"
              @input="modelListIndex = -1; showModelList = !!filteredModelOptions().length"
              @blur="closeModelList()"
              @keydown="onModelNameKeydown" />
            <button v-if="modelOptions.length" class="field-icon-button" tabindex="-1" aria-label="展开模型列表"
              @mousedown.prevent="showModelList = !showModelList" @click="modelNameInput?.focus()"><ChevronDown :size="16" /></button>
            <ul v-if="showModelList && filteredModelOptions().length" class="model-dropdown" @mousedown.prevent>
              <li v-for="(model, index) in filteredModelOptions()" :key="model" :class="{ selected: index === modelListIndex }"
                @mouseenter="modelListIndex = index" @mousedown.prevent="chooseModel(model)">{{ model }}</li>
            </ul>
          </div>
          <div class="model-list-row"><span :class="{ 'success-text': modelOptions.length }"><LoaderCircle v-if="modelBusy" :size="13" class="spin" /><CheckCircle2 v-else-if="modelOptions.length" :size="13" /><span v-else class="soft-dot"></span>{{ modelStatus }}</span><button class="refresh-button" :disabled="modelBusy || !canFetchModels()" @click="refreshModels()"><RefreshCw :size="14" :class="{ spin: modelBusy }" />刷新列表</button></div>
          <div class="advanced-heading"><span>高级配置</span><span class="muted">可选</span></div>
          <label class="field-label" for="max-tokens">输出长度</label><div class="token-input-wrap"><input id="max-tokens" v-model.number="draft.max_tokens" class="plain-input" type="number" min="1" max="131072" placeholder="使用服务商默认值" /><span>tokens</span></div>
          <div class="token-presets"><button v-for="amount in [800, 2000, 4000, 8000]" :key="amount" @click="draft.max_tokens = amount">{{ amount.toLocaleString() }}</button></div>
        </div>
        <footer class="dialog-footer"><span class="dialog-safe"><LockKeyhole :size="14" />密钥仅保存在 Windows 凭据管理器</span><div><button class="button button-quiet" @click="showModel = false">取消</button><button class="button button-primary" @click="saveModel"><Check :size="16" />保存</button></div></footer>
      </section>
    </div>
    <Transition name="toast"><div v-if="toast" class="toast-message" :class="{ error: toastError }"><CheckCircle2 v-if="!toastError" :size="17" /><CircleHelp v-else :size="17" />{{ toast }}</div></Transition>
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
