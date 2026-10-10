import type { ReviewMessage } from './MessageReview.vue'
import type { AnalysisContext, ContextStats } from './contextOptions'
import { unicodeLength } from './contextOptions'

export type ReplyIntent = 'general' | 'decline' | 'clarify' | 'close' | 'deescalate'
export const replyIntents: ReplyIntent[] = ['general', 'decline', 'clarify', 'close', 'deescalate']
export function draftWithinCapacity(messages: ReviewMessage[]): boolean {
  if (messages.length > 20000) return false
  let characters = 0
  for (const message of messages) {
    characters += unicodeLength(message.text)
    if (characters > 200000) return false
  }
  return true
}
export function reviewStats(messages: ReviewMessage[], context: AnalysisContext): ContextStats {
  // Mirrors the backend prefix parser for preview statistics only; backend is authoritative.
  const prior: string[] = []
  let pending = false
  for (const raw of context.prior_text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const prefix = /^(我|对方|me|other)\s*[:：]\s*(.*)$/i.exec(line)
    if (prefix) {
      pending = !prefix[2]?.trim()
      if (!pending) prior.push(prefix[2]!.trim())
    } else if (pending || !prior.length) { prior.push(line); pending = false }
    else prior[prior.length - 1] += '\n' + line
  }
  const all = [...prior, ...messages.filter(m => m.text.trim()).map(m => m.text)]
  const selected = context.message_limit === null ? all : all.slice(-context.message_limit)
  return { total_messages: all.length, used_messages: selected.length,
    characters: selected.reduce((n, text) => n + unicodeLength(text), unicodeLength(context.background)),
    message_limit: context.message_limit, omitted_messages: all.length - selected.length }
}
