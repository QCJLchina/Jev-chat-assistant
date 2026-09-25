import { ref } from 'vue'
import zh from '../../locales/zh-CN.json'
import en from '../../locales/en.json'
import fr from '../../locales/fr.json'
import ru from '../../locales/ru.json'
import ja from '../../locales/ja.json'

export type Locale = 'zh-CN' | 'en' | 'fr' | 'ru' | 'ja'
export type Language = Locale | 'system'
export type Message = { key: string; params?: Record<string, string | number | Message> }
export type BridgeResult = { ok?: boolean; error?: string; error_message?: Message }
const catalogs: Record<Locale, Record<string, string>> = { 'zh-CN': zh, en, fr, ru, ja }
export const locale = ref<Locale>('zh-CN')
export const languages: { value: Locale; label: string }[] = [
  { value: 'zh-CN', label: '简体中文' }, { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' }, { value: 'ru', label: 'Русский' }, { value: 'ja', label: '日本語' },
]
export const m = (key: string, params?: Message['params']): Message => ({ key, params })
export function t(key: string, params: Message['params'] = {}): string {
  const text = catalogs[locale.value]?.[key] ?? (zh as Record<string, string>)[key] ?? key
  return text.replace(/\{([A-Za-z_][A-Za-z_0-9]*)\}/g, (placeholder, name: string) => {
    const value = params[name]
    return value === undefined ? placeholder : typeof value === 'object' ? display(value) :
      typeof value === 'number' ? new Intl.NumberFormat(locale.value).format(value) : value
  })
}
export function display(value: Message | string | null | undefined): string {
  return typeof value === 'object' && value ? t(value.key, value.params) : value ?? ''
}
export function errorMessage(error: unknown): Message {
  if (error && typeof error === 'object' && 'key' in error) return error as Message
  return m('error.unexpected', { detail: String(error).replace(/^\w*Error:\s*/, '') })
}
export function checked<T extends BridgeResult>(result: T): T {
  if (result.ok === false || result.error) throw result.error_message ?? errorMessage(result.error)
  return result
}
