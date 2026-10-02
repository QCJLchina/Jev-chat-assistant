<script setup lang="ts">
import { computed } from 'vue'
import { t } from './i18n'
import type { ReplyPreferences } from './replyPreferences'

const props = defineProps<{ modelValue: ReplyPreferences; idPrefix: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ReplyPreferences] }>()
const fields = computed(() => [
  { name: 'length' as const, label: t('feature.preferenceLength'), options: [
    { value: 'short', label: t('feature.lengthShort') },
    { value: 'detailed', label: t('feature.lengthDetailed') },
  ] },
  { name: 'style' as const, label: t('feature.preferenceStyle'), options: [
    { value: 'natural', label: t('feature.styleNatural') },
    { value: 'formal', label: t('feature.styleFormal') },
    { value: 'gentle', label: t('feature.styleGentle') },
    { value: 'direct', label: t('feature.styleDirect') },
  ] },
  { name: 'language' as const, label: t('feature.preferenceLanguage'), options: [
    { value: 'interface', label: t('feature.languageInterface') },
    { value: 'zh-CN', label: t('feature.languageZhCN') },
    { value: 'en', label: t('feature.languageEn') },
    { value: 'fr', label: t('feature.languageFr') },
    { value: 'ru', label: t('feature.languageRu') },
    { value: 'ja', label: t('feature.languageJa') },
    { value: 'ko', label: t('feature.languageKo') },
  ] },
])
function update(name: keyof ReplyPreferences, event: Event) {
  emit('update:modelValue', { ...props.modelValue, [name]: (event.target as HTMLSelectElement).value })
}
</script>

<template>
  <div class="reply-preference-fields">
    <div v-for="field in fields" :key="field.name">
      <label class="field-label" :for="`${idPrefix}-${field.name}`">{{ field.label }}</label>
      <div class="select-wrap">
        <select :id="`${idPrefix}-${field.name}`" :value="modelValue[field.name]" :disabled="disabled" @change="update(field.name, $event)">
          <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </div>
    </div>
  </div>
</template>
