<script setup lang="ts">
import { computed, ref } from 'vue'
import { t } from './i18n'
import { contextInputLimit, unicodeLength } from './contextOptions'
import type { AnalysisContext, ContextStats, MessageLimit } from './contextOptions'

const props = defineProps<{ modelValue: AnalysisContext; disabled?: boolean; stats?: ContextStats | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: AnalysisContext] }>()
const open = ref(false)
const priorCount = computed(() => unicodeLength(props.modelValue.prior_text))
const backgroundCount = computed(() => unicodeLength(props.modelValue.background))
function update(field: 'prior_text' | 'background', event: Event) {
  emit('update:modelValue', { ...props.modelValue, [field]: (event.target as HTMLTextAreaElement).value })
}
function setLimit(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  emit('update:modelValue', { ...props.modelValue, message_limit: value === 'all' ? null : Number(value) as MessageLimit })
}
</script>

<template>
  <div class="context-options">
    <label class="field-label" for="context-message-limit">{{ t('context.messageLimit') }}</label>
    <div class="select-wrap">
      <select id="context-message-limit" :aria-label="t('context.title')" :value="modelValue.message_limit ?? 'all'" :disabled="disabled" @change="setLimit">
        <option value="all">{{ t('context.all') }}</option>
        <option v-for="count in [10, 20, 50]" :key="count" :value="count">{{ t('context.lastMessages', { count }) }}</option>
      </select>
    </div>
    <p class="field-hint">{{ t('context.help') }}</p>
    <button class="text-action" :aria-expanded="open" aria-controls="context-supplements" @click="open = !open">{{ t('context.supplement') }}</button>
    <div v-show="open" id="context-supplements">
      <label class="field-label" for="context-prior-text">{{ t('context.priorText') }}</label>
      <textarea id="context-prior-text" :value="modelValue.prior_text" rows="5" :disabled="disabled" :placeholder="t('context.priorPlaceholder')" :aria-invalid="priorCount > contextInputLimit" aria-describedby="context-prior-count context-safety" @input="update('prior_text', $event)"></textarea>
      <p id="context-prior-count" class="field-hint">{{ t('context.inputCount', { count: priorCount, limit: contextInputLimit }) }}</p>
      <label class="field-label" for="context-background">{{ t('context.background') }}</label>
      <textarea id="context-background" :value="modelValue.background" rows="3" :disabled="disabled" :placeholder="t('context.backgroundPlaceholder')" :aria-invalid="backgroundCount > contextInputLimit" aria-describedby="context-background-count context-safety" @input="update('background', $event)"></textarea>
      <p id="context-background-count" class="field-hint">{{ t('context.inputCount', { count: backgroundCount, limit: contextInputLimit }) }}</p>
      <p id="context-safety" class="field-hint">{{ t('context.safetyNote') }}</p>
      <button class="button button-quiet" :disabled="disabled" @click="emit('update:modelValue', { ...modelValue, prior_text: '', background: '' })">{{ t('context.clear') }}</button>
    </div>
    <p v-if="priorCount > contextInputLimit || backgroundCount > contextInputLimit" class="text-input-error" role="alert">{{ t('context.tooLong', { limit: contextInputLimit }) }}</p>
    <div v-if="stats" class="context-stats" role="status">
      <span>{{ t('context.totalMessages', { count: stats.total_messages }) }}</span>
      <span>{{ t('context.usedMessages', { count: stats.used_messages }) }}</span>
      <span>{{ t('context.characters', { count: stats.characters }) }}</span>
      <span>{{ t('context.appliedLimit', { limit: stats.message_limit ?? t('context.all') }) }}</span>
      <span>{{ t('context.omittedMessages', { count: stats.omitted_messages }) }}</span>
    </div>
  </div>
</template>

<style scoped>
.context-options{margin-top:16px;border-top:1px solid #e6edf4;padding-top:4px}
.context-stats{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:12px;color:#52647b;font-size:12px}
</style>
