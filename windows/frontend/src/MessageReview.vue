<script setup lang="ts">
import { computed } from 'vue'
import { t } from './i18n'
export type ReviewMessage = { side: 'me' | 'other'; text: string }
const props = defineProps<{ modelValue: ReviewMessage[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ReviewMessage[]] }>()
const messages = computed(() => props.modelValue)
function update(index: number, field: keyof ReviewMessage, value: string) {
  const next = props.modelValue.map(m => ({ ...m }))
  next[index] = { ...next[index], [field]: value }
  emit('update:modelValue', next)
}
function move(index: number, offset: number) {
  const next = [...props.modelValue]
  const [item] = next.splice(index, 1)
  next.splice(index + offset, 0, item!)
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="review-messages">
    <div v-for="(message, index) in messages" :key="index" class="review-row">
      <label :for="`review-side-${index}`">{{ index + 1 }} · {{ t('review.speaker') }}</label>
      <select :id="`review-side-${index}`" :value="message.side" :disabled="disabled" @change="update(index, 'side', ($event.target as HTMLSelectElement).value)">
        <option value="me">{{ t('messages.me') }}</option><option value="other">{{ t('messages.other') }}</option>
      </select>
      <label :for="`review-text-${index}`">{{ t('review.body') }}</label>
      <textarea :id="`review-text-${index}`" :value="message.text" rows="3" :disabled="disabled" @input="update(index, 'text', ($event.target as HTMLTextAreaElement).value)"></textarea>
      <div class="review-actions">
        <button class="button button-outline" :disabled="disabled || index === 0" @click="move(index, -1)">{{ t('review.up') }}</button>
        <button class="button button-outline" :disabled="disabled || index === messages.length - 1" @click="move(index, 1)">{{ t('review.down') }}</button>
        <button class="button button-outline" :disabled="disabled" @click="emit('update:modelValue', messages.filter((_, i) => i !== index))">{{ t('common.delete') }}</button>
      </div>
    </div>
    <p v-if="!messages.length" role="status">{{ t('review.empty') }}</p>
    <button class="button button-outline" :disabled="disabled" @click="emit('update:modelValue', [...messages, { side: 'other', text: '' }])">{{ t('review.add') }}</button>
  </div>
</template>

<style scoped>
.review-messages{display:grid;gap:14px;margin:14px 0;max-height:560px;overflow:auto}
.review-row{display:grid;gap:8px;padding:12px;border:1px solid #e6edf4;border-radius:12px}
.review-row label{font-size:12px;color:#52647b}
.review-row textarea,.review-row select{font:inherit;padding:8px;border:1px solid #dce5ee;border-radius:8px;width:100%;box-sizing:border-box}
.review-actions{display:flex;flex-wrap:wrap;gap:8px}
</style>
