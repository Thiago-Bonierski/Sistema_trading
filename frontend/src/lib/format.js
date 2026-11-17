export function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

export function formatCurrency(value, { maximumFractionDigits = 2 } = {}) {
  if (!isNumber(value)) return '—'
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits,
  }).format(value)
}

export function formatNumber(value, digits = 2) {
  if (!isNumber(value)) return '—'
  return new Intl.NumberFormat('pt-BR', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value)
}

export function formatCompact(value) {
  if (!isNumber(value)) return '—'
  return new Intl.NumberFormat('pt-BR', {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value)
}

/** Formata um valor que JÁ está em pontos percentuais (ex.: 12.3 -> 12,30%). */
export function formatPercent(value, digits = 2) {
  if (!isNumber(value)) return '—'
  return `${formatNumber(value, digits)}%`
}

/** Formata uma fração (0.123 -> 12,30%). */
export function formatFractionPercent(value, digits = 2) {
  if (!isNumber(value)) return '—'
  return `${formatNumber(value * 100, digits)}%`
}

export function formatSignedCurrency(value, options) {
  if (!isNumber(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatCurrency(value, options)}`
}

export function formatSignedPercent(value, digits = 2) {
  if (!isNumber(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatNumber(value, digits)}%`
}

export function pnlClass(value) {
  if (!isNumber(value) || value === 0) return 'text-slate-300'
  return value > 0 ? 'text-emerald-400' : 'text-rose-400'
}

export function formatRegime(regime) {
  if (!regime) return 'Aguardando'
  return String(regime)
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase())
}

export function formatDateTime(value) {
  if (!value) return '—'
  const normalized = String(value).includes('T')
    ? value
    : String(value).replace(' ', 'T')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

export function formatTime(value) {
  if (!value) return '—'
  const normalized = String(value).includes('T')
    ? value
    : String(value).replace(' ', 'T')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

export function timeAgo(value) {
  if (!value) return '—'
  const normalized = String(value).includes('T')
    ? value
    : String(value).replace(' ', 'T')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return '—'
  const diff = Math.max(0, Date.now() - date.getTime())
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s atrás`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}min atrás`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h atrás`
  const days = Math.floor(hours / 24)
  return `${days}d atrás`
}

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

export function truncate(value, length = 80) {
  if (!value) return ''
  const text = String(value)
  return text.length > length ? `${text.slice(0, length - 1)}…` : text
}
