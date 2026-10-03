export type MessageLimit = null | 10 | 20 | 50
export type AnalysisContext = { prior_text: string; background: string; message_limit: MessageLimit }
export type ContextStats = {
  total_messages: number; used_messages: number; characters: number
  message_limit: MessageLimit; omitted_messages: number
}
export type SelectionMode = 'window' | 'screen'
export type SelectionBinding = {
  status: 'bound' | 'needs_confirmation' | 'invalid' | 'none'
  display_name?: string; reason?: string
}
export type BindingCandidate = { id: string; title: string }
export const contextInputLimit = 20_000
export const defaultContext: AnalysisContext = { prior_text: '', background: '', message_limit: null }
export const unicodeLength = (text: string) => Array.from(text).length
