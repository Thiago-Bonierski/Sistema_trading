import { Badge } from './ui.jsx'
import { formatRegime } from '../lib/format.js'

const REGIME_VARIANTS = {
  TENDENCIA_ALTA: 'emerald',
  TENDENCIA_BAIXA: 'rose',
  CONSOLIDACAO: 'sky',
  TRANSICAO: 'amber',
  ALTA_VOLATILIDADE: 'violet',
  AGUARDANDO: 'slate',
}

export function RegimeBadge({ regime }) {
  const variant = REGIME_VARIANTS[regime] || 'slate'
  return <Badge variant={variant}>{formatRegime(regime)}</Badge>
}

export function SideBadge({ side }) {
  const normalized = String(side || '').toUpperCase()
  if (normalized === 'COMPRA') return <Badge variant="emerald">Compra</Badge>
  if (normalized === 'VENDA') return <Badge variant="rose">Venda</Badge>
  return <Badge variant="slate">{side || '—'}</Badge>
}

export function RecommendationBadge({ recommendation }) {
  const normalized = String(recommendation || '').toUpperCase()
  if (normalized === 'COMPRA') return <Badge variant="emerald">Compra</Badge>
  if (normalized === 'VENDA') return <Badge variant="rose">Venda</Badge>
  if (normalized === 'AGUARDAR' || normalized === 'AGUARDANDO') {
    return <Badge variant="slate">Aguardar</Badge>
  }
  return <Badge variant="slate">{recommendation || '—'}</Badge>
}

const RISK_VARIANTS = {
  NORMAL: 'emerald',
  REDUCED: 'amber',
  PROTECT: 'rose',
  UNKNOWN: 'slate',
}

export function RiskBadge({ level }) {
  const normalized = String(level || 'UNKNOWN').toUpperCase()
  return (
    <Badge variant={RISK_VARIANTS[normalized] || 'slate'}>
      {normalized === 'UNKNOWN' ? 'Desconhecido' : normalized}
    </Badge>
  )
}

export function MlModeBadge({ mode, trained }) {
  const isModel = mode === 'model' || trained
  return (
    <Badge variant={isModel ? 'emerald' : 'amber'}>
      {isModel ? 'Modelo treinado' : 'Heurística'}
    </Badge>
  )
}

export function ResultBadge({ result }) {
  const normalized = String(result || '').toUpperCase()
  if (normalized === 'WIN') return <Badge variant="emerald">Win</Badge>
  if (normalized === 'LOSS') return <Badge variant="rose">Loss</Badge>
  return <Badge variant="slate">{result || '—'}</Badge>
}

export function ModeBadge({ mode }) {
  const normalized = String(mode || '').toUpperCase()
  if (normalized === 'RESEARCH') return <Badge variant="violet">Research</Badge>
  if (normalized === 'PAPER_TRADING') return <Badge variant="sky">Paper</Badge>
  return <Badge variant="slate">{mode || '—'}</Badge>
}

const LEVEL_VARIANTS = {
  DEBUG: 'text-slate-500',
  INFO: 'text-sky-300',
  WARNING: 'text-amber-300',
  ERROR: 'text-rose-300',
  CRITICAL: 'text-rose-200',
}

export function logLevelClass(level) {
  return LEVEL_VARIANTS[level] || 'text-slate-400'
}
