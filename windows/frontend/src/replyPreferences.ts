import type { Locale } from './i18n'

export type ReplyPreferences = {
  length: 'short' | 'detailed'
  style: 'natural' | 'formal' | 'gentle' | 'direct'
  language: Locale | 'interface'
}

export const defaultReplyPreferences: ReplyPreferences = {
  length: 'short', style: 'natural', language: 'zh-CN',
}
