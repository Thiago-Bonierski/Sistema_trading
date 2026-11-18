import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  BrainCircuit,
  Bitcoin,
  Gauge,
  Info,
  Lightbulb,
  RotateCcw,
  Save,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Undo2,
  Waves,
} from 'lucide-react'
import { api } from '../api.js'
import {
  Alert,
  Badge,
  Button,
  Card,
  LoadingBlock,
  SectionTitle,
  ToggleSwitch,
} from '../components/ui.jsx'
import { formatDateTime, formatNumber } from '../lib/format.js'

const DICT_KEY_LABELS = {
  NORMAL: 'Normal',
  REDUCED: 'Reduzido',
  PROTECT: 'Proteção',
  TENDENCIA_ALTA: 'Tendência alta',
  TENDENCIA_BAIXA: 'Tendência baixa',
  CONSOLIDACAO: 'Consolidação',
  TRANSICAO: 'Transição',
  ALTA_VOLATILIDADE: 'Alta volatilidade',
}

const PERCENT_HINTS = new Set([
  'DEFAULT_STOP_LOSS_PCT',
  'DEFAULT_TAKE_PROFIT_PCT',
  'BASE_POSITION_SIZE_PCT',
  'EQUITY_DRAWDOWN_LIMIT',
  'DAILY_LOSS_LIMIT',
])

const SECTION_ICONS = {
  stops: ShieldAlert,
  crypto: Bitcoin,
  risk: ShieldCheck,
  regime: Gauge,
  exhaustion: Waves,
  ml: BrainCircuit,
}

function cloneValue(value) {
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value))
}

function toDraftValues(values) {
  const draft = {}
  Object.entries(values || {}).forEach(([key, value]) => {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      draft[key] = Object.fromEntries(
        Object.entries(value).map(([innerKey, innerValue]) => [
          innerKey,
          String(innerValue),
        ]),
      )
    } else {
      draft[key] = String(value)
    }
  })
  return draft
}

function normalizeValue(raw, type) {
  if (type === 'bool') {
    if (typeof raw === 'boolean') return raw
    if (typeof raw === 'string') {
      return ['true', '1', 'sim', 'yes', 'on'].includes(raw.trim().toLowerCase())
    }
    return Boolean(raw)
  }
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return Object.fromEntries(
      Object.entries(raw).map(([key, value]) => [key, Number(value)]),
    )
  }
  return Number(raw)
}

function sameValue(a, b) {
  return JSON.stringify(a) === JSON.stringify(b)
}

function percentHint(key, rawValue) {
  if (!PERCENT_HINTS.has(key)) return null
  const numeric = Number(rawValue)
  if (!Number.isFinite(numeric)) return null
  return `${formatNumber(numeric * 100, 2)}%`
}

function ParameterField({ parameter, draftValue, currentValue, onChange, onRevert }) {
  const isDict =
    parameter.type === 'dict_int' ||
    (draftValue && typeof draftValue === 'object')
  const dirty = !sameValue(
    normalizeValue(draftValue, parameter.type),
    currentValue,
  )
  const hint = percentHint(parameter.key, draftValue)
  const guidance = parameter.guidance || {}
  const isBool = parameter.type === 'bool'
  const isOn = normalizeValue(draftValue, parameter.type) === true

  return (
    <div
      className={`rounded-xl border p-3 transition ${
        dirty
          ? 'border-amber-400/25 bg-amber-400/[0.03]'
          : 'border-white/[0.07] bg-slate-950/30'
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-semibold text-slate-200">
              {parameter.label}
            </span>
            {parameter.overridden ? (
              <Badge variant="emerald">Personalizado</Badge>
            ) : null}
            {dirty ? <Badge variant="amber">Alterado</Badge> : null}
            {guidance.recommended ? (
              <Badge variant="sky" title="Faixa recomendada pelo motor">
                Recomendado: {guidance.recommended}
              </Badge>
            ) : null}
          </div>
          {parameter.description ? (
            <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
              {parameter.description}
            </p>
          ) : null}
          {guidance.impact_up || guidance.impact_down ? (
            <div className="mt-2 space-y-1 rounded-lg border border-sky-400/10 bg-sky-400/[0.035] px-2.5 py-2">
              {guidance.impact_up ? (
                <p className="flex gap-1.5 text-[10px] leading-relaxed text-slate-400">
                  <ArrowUp size={11} className="mt-0.5 shrink-0 text-emerald-400" />
                  <span>
                    <span className="font-semibold text-emerald-300/90">
                      Ao aumentar:
                    </span>{' '}
                    {guidance.impact_up}
                  </span>
                </p>
              ) : null}
              {guidance.impact_down ? (
                <p className="flex gap-1.5 text-[10px] leading-relaxed text-slate-400">
                  <ArrowDown size={11} className="mt-0.5 shrink-0 text-amber-400" />
                  <span>
                    <span className="font-semibold text-amber-300/90">
                      Ao diminuir:
                    </span>{' '}
                    {guidance.impact_down}
                  </span>
                </p>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          {isBool ? (
            <div className="flex items-center gap-2">
              <span
                className={`text-[10px] font-semibold ${
                  isOn ? 'text-emerald-300' : 'text-slate-500'
                }`}
              >
                {isOn ? 'ATIVO' : 'DESATIVADO'}
              </span>
              <ToggleSwitch
                checked={isOn}
                onChange={(next) => onChange(String(next))}
                label={parameter.label}
              />
            </div>
          ) : !isDict ? (
            <div className="flex items-center gap-2">
              {hint ? (
                <span className="text-[10px] font-medium text-emerald-300/80">
                  {hint}
                </span>
              ) : null}
              <input
                className="field !w-28 !py-1.5 text-right text-xs"
                type="number"
                min={parameter.min}
                max={parameter.max}
                step={parameter.step || 'any'}
                value={draftValue}
                onChange={(event) => onChange(event.target.value)}
                aria-label={parameter.label}
              />
            </div>
          ) : null}
          {dirty ? (
            <button
              type="button"
              onClick={onRevert}
              className="grid h-7 w-7 place-items-center rounded-lg text-slate-500 transition hover:bg-white/[0.06] hover:text-slate-200"
              title="Desfazer alteração"
            >
              <RotateCcw size={13} />
            </button>
          ) : null}
        </div>
      </div>

      {isDict ? (
        <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {Object.entries(draftValue || {}).map(([innerKey, innerValue]) => (
            <div key={innerKey}>
              <span className="mb-1 block text-[10px] text-slate-600">
                {DICT_KEY_LABELS[innerKey] || innerKey}
              </span>
              <input
                className="field !py-1.5 text-right text-xs"
                type="number"
                min={parameter.min}
                max={parameter.max}
                step="1"
                value={innerValue}
                onChange={(event) => onChange(event.target.value, innerKey)}
                aria-label={`${parameter.label} ${innerKey}`}
              />
            </div>
          ))}
        </div>
      ) : null}

      {guidance.tip ? (
        <p className="mt-2 flex gap-1.5 border-t border-white/[0.05] pt-2 text-[10px] leading-relaxed text-slate-500">
          <Lightbulb size={11} className="mt-0.5 shrink-0 text-violet-400/80" />
          <span>{guidance.tip}</span>
        </p>
      ) : null}

      <div className="mt-1.5 flex items-center justify-between text-[9px] text-slate-700">
        <span>
          {isBool
            ? 'verdadeiro / falso'
            : `mín ${parameter.min ?? '—'} · máx ${parameter.max ?? '—'}`}
        </span>
        <span className="font-mono">{parameter.type}</span>
      </div>
    </div>
  )
}

export default function Calibration() {
  const [snapshot, setSnapshot] = useState(null)
  const [draft, setDraft] = useState({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const payload = await api.config()
      setSnapshot(payload)
      setDraft(toDraftValues(payload.values))
      setError('')
    } catch (exc) {
      setError(exc.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const sections = useMemo(() => {
    if (!snapshot) return []
    const categories = Object.fromEntries(
      (snapshot.categories || []).map((category) => [category.key, category]),
    )
    const stops = categories.stops?.parameters || []
    const regime = categories.regime?.parameters || []
    const exhaustion = categories.exhaustion?.parameters || []
    const risk = categories.risk?.parameters || []
    const ml = categories.ml?.parameters || []

    const crypto = regime.filter((parameter) => parameter.key === 'CRYPTO_VOL_MULTIPLIER')
    const regimeFilters = regime.filter(
      (parameter) => parameter.key !== 'CRYPTO_VOL_MULTIPLIER',
    )

    return [
      {
        id: 'stops',
        title: 'Stop / Take-Profit',
        subtitle: 'Alvos por trade, tamanho da posição e idade máxima.',
        parameters: stops,
      },
      {
        id: 'crypto',
        title: 'Multiplicador Cripto',
        subtitle: 'Amplia stops e thresholds para BTC, ETH e SOL.',
        parameters: crypto,
      },
      {
        id: 'risk',
        title: 'Limites de Risco',
        subtitle: 'Limites de trades, posições, drawdown e kill-switch.',
        parameters: risk,
      },
      {
        id: 'regime',
        title: 'Filtros de Regime',
        subtitle: 'Detecção de regime, confirmação e thresholds das engines.',
        parameters: regimeFilters,
      },
      {
        id: 'exhaustion',
        title: 'Filtros de Exaustão',
        subtitle: 'Critérios que bloqueiam entradas no fim do movimento.',
        parameters: exhaustion,
      },
      {
        id: 'ml',
        title: 'Machine Learning',
        subtitle: 'Threshold de aprovação, treino e periodicidade.',
        parameters: ml,
      },
    ]
  }, [snapshot])

  const parameterTypes = useMemo(() => {
    const types = {}
    ;(snapshot?.categories || []).forEach((category) => {
      ;(category.parameters || []).forEach((parameter) => {
        types[parameter.key] = parameter.type
      })
    })
    return types
  }, [snapshot])

  const dirtyKeys = useMemo(() => {
    if (!snapshot) return []
    return Object.keys(draft).filter(
      (key) =>
        !sameValue(
          normalizeValue(draft[key], parameterTypes[key]),
          snapshot.values?.[key],
        ),
    )
  }, [draft, snapshot, parameterTypes])

  const overriddenCount = Object.keys(snapshot?.overrides || {}).length

  function handleChange(key, value, innerKey = null) {
    setNotice(null)
    setDraft((current) => {
      if (innerKey) {
        return {
          ...current,
          [key]: {
            ...current[key],
            [innerKey]: value,
          },
        }
      }
      return { ...current, [key]: value }
    })
  }

  function handleRevert(key) {
    if (!snapshot) return
    setDraft((current) => ({
      ...current,
      [key]: cloneValue(
        toDraftValues({ [key]: snapshot.values[key] })[key],
      ),
    }))
  }

  function handleRevertAll() {
    if (!snapshot) return
    setDraft(toDraftValues(snapshot.values))
    setNotice(null)
  }

  async function handleSave() {
    if (!dirtyKeys.length) {
      setNotice({ type: 'info', message: 'Nenhuma alteração pendente.' })
      return
    }

    const values = {}
    for (const key of dirtyKeys) {
      const normalized = normalizeValue(draft[key], parameterTypes[key])
      if (typeof normalized === 'object') {
        const empty = Object.values(normalized).some(
          (value) => !Number.isFinite(value),
        )
        if (empty) {
          setError(`Preencha todos os valores de ${key} com números válidos.`)
          return
        }
      } else if (!Number.isFinite(normalized)) {
        setError(`O parâmetro ${key} precisa ser numérico.`)
        return
      }
      values[key] = normalized
    }

    setSaving(true)
    setError('')
    setNotice(null)
    try {
      const payload = await api.saveConfig(values)
      setSnapshot(payload)
      setDraft(toDraftValues(payload.values))
      setNotice({
        type: 'success',
        message: `Configuração aplicada em tempo real (${dirtyKeys.length} parâmetro(s)).`,
      })
    } catch (exc) {
      setError(exc.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleReset() {
    const confirmed = window.confirm(
      'Restaurar TODOS os parâmetros para os padrões de config.py?\n\nOs overrides salvos serão removidos e aplicados imediatamente.',
    )
    if (!confirmed) return

    setResetting(true)
    setError('')
    setNotice(null)
    try {
      const payload = await api.resetConfig()
      setSnapshot(payload)
      setDraft(toDraftValues(payload.values))
      setNotice({
        type: 'success',
        message: 'Padrões restaurados e aplicados em tempo real.',
      })
    } catch (exc) {
      setError(exc.message)
    } finally {
      setResetting(false)
    }
  }

  if (loading && !snapshot) {
    return <LoadingBlock label="Carregando parâmetros do motor…" />
  }

  if (error && !snapshot) {
    return (
      <div className="space-y-4">
        <Alert type="error">{error}</Alert>
        <div className="flex justify-center">
          <Button onClick={load}>
            <RotateCcw size={15} /> Tentar novamente
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5 animate-rise-in">
      <Card className="p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <SectionTitle
            icon={SlidersHorizontal}
            title="Calibragem Visual"
            subtitle="Edite os parâmetros e aplique no motor sem reiniciar o servidor."
            right={
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant="slate">
                  {Object.keys(snapshot?.values || {}).length} parâmetros
                </Badge>
                <Badge variant={overriddenCount ? 'amber' : 'emerald'}>
                  {overriddenCount} override(s)
                </Badge>
                {dirtyKeys.length ? (
                  <Badge variant="amber">{dirtyKeys.length} pendente(s)</Badge>
                ) : null}
              </div>
            }
          />

          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={handleRevertAll}
              disabled={!dirtyKeys.length || saving || resetting}
            >
              <Undo2 size={15} /> Descartar
            </Button>
            <Button
              onClick={handleReset}
              loading={resetting}
              disabled={saving}
              variant="ghost"
            >
              <RotateCcw size={15} /> Restaurar Padrões
            </Button>
            <Button
              variant="primary"
              onClick={handleSave}
              loading={saving}
              disabled={!dirtyKeys.length || resetting}
            >
              <Save size={15} /> Salvar e Aplicar
            </Button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[10px] text-slate-600">
          <span>
            Arquivo de overrides:{' '}
            <span className="font-mono text-slate-500">
              {snapshot?.config_file || 'runtime_config.json'}
            </span>
          </span>
          <span>
            Última alteração:{' '}
            {snapshot?.updated_at ? formatDateTime(snapshot.updated_at) : 'padrões de fábrica'}
          </span>
        </div>

        {error ? <Alert type="error" className="mt-3">{error}</Alert> : null}
        {notice ? (
          <Alert type={notice.type} className="mt-3">
            {notice.message}
          </Alert>
        ) : null}

        <Alert type="info" className="mt-3">
          <span className="inline-flex items-center gap-1.5">
            <Info size={13} /> Parâmetros percentuais são frações:{' '}
            <span className="font-mono">0,008 = 0,8%</span>. Cada campo explica o
            efeito de aumentar/diminuir e mostra a faixa recomendada. Campos
            “personalizado” já possuem override salvo. Alterações só chegam ao
            motor após “Salvar e Aplicar”.
          </span>
        </Alert>
      </Card>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        {sections.map((section) => {
          const Icon = SECTION_ICONS[section.id] || SlidersHorizontal
          return (
            <Card key={section.id} className="p-4 sm:p-5">
              <SectionTitle
                icon={Icon}
                title={section.title}
                subtitle={section.subtitle}
                right={
                  <Badge variant="slate">{section.parameters.length}</Badge>
                }
              />
              <div className="mt-4 space-y-2.5">
                {section.parameters.map((parameter) => (
                  <ParameterField
                    key={parameter.key}
                    parameter={parameter}
                    draftValue={draft[parameter.key]}
                    currentValue={snapshot?.values?.[parameter.key]}
                    onChange={(value, innerKey) =>
                      handleChange(parameter.key, value, innerKey)
                    }
                    onRevert={() => handleRevert(parameter.key)}
                  />
                ))}
              </div>
            </Card>
          )
        })}
      </div>

      <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="text-xs text-slate-500">
          <span className="font-semibold text-slate-300">
            {dirtyKeys.length
              ? `${dirtyKeys.length} alteração(ões) aguardando aplicação.`
              : 'Tudo sincronizado com o motor.'}
          </span>
          <p className="mt-0.5 text-[11px] text-slate-600">
            A aplicação é atômica: se um valor for inválido, nada é alterado.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={handleReset}
            loading={resetting}
            disabled={saving}
          >
            <RotateCcw size={15} /> Restaurar Padrões
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            loading={saving}
            disabled={!dirtyKeys.length || resetting}
          >
            <Save size={15} /> Salvar e Aplicar
          </Button>
        </div>
      </Card>
    </div>
  )
}
