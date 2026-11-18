import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BrainCircuit,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Zap,
} from 'lucide-react'
import { api } from '../api.js'
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  LoadingBlock,
  ProgressBar,
  SectionTitle,
  Spinner,
  ToggleSwitch,
} from '../components/ui.jsx'
import { MlModeBadge, logLevelClass } from '../components/badges.jsx'
import {
  formatDateTime,
  formatFractionPercent,
  formatNumber,
  formatPercent,
  timeAgo,
} from '../lib/format.js'

const LEVELS = [
  { id: '', label: 'Tudo' },
  { id: 'INFO', label: 'INFO' },
  { id: 'WARNING', label: 'WARNING' },
  { id: 'ERROR', label: 'ERROR' },
]

function MlActivationCard({ ml, toggling, onToggle, notice }) {
  const usable = Boolean(ml?.usable)
  const active = usable && ml?.shadow_mode === false
  const disabled = !usable || toggling

  return (
    <Card className="p-4 sm:p-5">
      <SectionTitle
        icon={ShieldCheck}
        title="Ativação do Filtro ML"
        subtitle="Controle se o classificador bloqueia ou apenas observa os sinais."
      />

      <div
        className={`mt-4 rounded-xl border p-4 transition ${
          active
            ? 'border-emerald-400/25 bg-emerald-400/[0.05]'
            : 'border-amber-400/25 bg-amber-400/[0.05]'
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Badge variant={active ? 'emerald' : 'amber'}>
              {active
                ? 'FILTRO ATIVO — Bloqueando sinais ruins'
                : 'OBSERVAÇÃO (SHADOW) — Apenas registrando scores'}
            </Badge>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
              {active
                ? 'Sinais abaixo do threshold são convertidos em NEUTRO antes da execução.'
                : 'O classificador pontua cada sinal, mas nenhuma entrada é bloqueada.'}
            </p>
          </div>
          <ToggleSwitch
            checked={active}
            onChange={onToggle}
            disabled={disabled}
            size="lg"
            label="Filtro ML Ativo"
          />
        </div>

        <div className="mt-3 flex items-center justify-between border-t border-white/[0.06] pt-2.5">
          <span className="text-[10px] text-slate-600">
            {active ? 'Filtro ML Ativo' : 'Modo Observação / Shadow'}
          </span>
          <span className="text-[10px] font-semibold text-slate-400">
            {toggling ? 'Aplicando…' : 'Clique para alternar'}
          </span>
        </div>
      </div>

      {!usable ? (
        <Alert type="warning" className="mt-3">
          <span>
            Treine um modelo válido antes de ativar o bloqueio. O classificador
            só pode filtrar entradas com um artefato aprovado pelos guardrails.
            {ml?.disabled_reason
              ? ` Motivo: ${ml.disabled_reason}.`
              : ''}
          </span>
        </Alert>
      ) : null}
      {notice ? (
        <Alert type={notice.type} className="mt-3">
          {notice.message}
        </Alert>
      ) : null}
    </Card>
  )
}

function MlStatusCard({
  ml,
  loading,
  training,
  onTrain,
  notice,
}) {
  const accuracy =
    ml?.accuracy != null ? formatFractionPercent(ml.accuracy, 1) : '—'
  const samples = Number(ml?.samples_trained) || 0
  const tradeCount = Number(ml?.trade_count) || 0
  const minTrades = Number(ml?.min_trades_for_training) || 0
  const progress =
    minTrades > 0 ? Math.min(100, (tradeCount / minTrades) * 100) : 100
  const lastTraining = ml?.latest_training?.generated_at

  return (
    <Card className="p-4 sm:p-5">
      <SectionTitle
        icon={BrainCircuit}
        title="RandomForest"
        subtitle="Classificador que filtra sinais aprovados pelas engines."
        right={loading ? <Spinner size={15} /> : <MlModeBadge mode={ml?.mode} trained={ml?.trained} />}
      />

      <div
        className={`mt-4 rounded-xl border p-4 ${
          ml?.trained
            ? 'border-emerald-400/20 bg-emerald-400/[0.04]'
            : 'border-amber-400/20 bg-amber-400/[0.04]'
        }`}
      >
        <div className="flex items-center gap-3">
          <span
            className={`grid h-11 w-11 place-items-center rounded-xl border ${
              ml?.trained
                ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300'
                : 'border-amber-400/25 bg-amber-400/10 text-amber-300'
            }`}
          >
            {ml?.trained ? <CheckCircle2 size={20} /> : <Sparkles size={20} />}
          </span>
          <div>
            <p className="text-sm font-semibold text-slate-100">
              {ml?.trained ? 'Modelo treinado e ativo' : 'Modo heurística'}
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              {ml?.trained
                ? 'O monitor usa o RandomForest para aprovar ou bloquear sinais.'
                : 'Sem modelo carregado: o motor usa as regras heurísticas de confiança.'}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <p className="stat-label">Acurácia (teste)</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-slate-50">
            {accuracy}
          </p>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <p className="stat-label">Amostras de treino</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-slate-50">
            {formatNumber(samples, 0)}
          </p>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <p className="stat-label">Threshold</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-slate-50">
            {formatPercent((Number(ml?.threshold) || 0) * 100, 1)}
          </p>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <p className="stat-label">Features</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-slate-50">
            {ml?.n_features ?? '—'}
          </p>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-slate-500">Histórico para treino</span>
          <span className="tabular-nums text-slate-300">
            {formatNumber(tradeCount, 0)} / {formatNumber(minTrades, 0)}
          </span>
        </div>
        <ProgressBar
          value={progress}
          className="mt-2"
          tone={progress >= 100 ? 'emerald' : 'amber'}
        />
        <p className="mt-2 text-[10px] text-slate-600">
          {tradeCount >= minTrades
            ? 'Histórico mínimo atingido.'
            : `Faltam ${formatNumber(minTrades - tradeCount, 0)} trades para o mínimo configurado.`}
        </p>
        {ml?.training_samples ? (
          <p className="mt-2 border-t border-white/[0.06] pt-2 text-[10px] text-slate-500">
            No treino:{' '}
            <span className="text-emerald-300">
              {formatNumber(ml.training_samples.live, 0)} reais
            </span>{' '}
            ·{' '}
            <span className="text-sky-300">
              {formatNumber(ml.training_samples.simulated_historical, 0)} simulações históricas
            </span>
            {Number(ml.training_samples.synthetic_ignored) > 0 ? (
              <>
                {' '}·{' '}
                <span className="text-amber-300">
                  {formatNumber(ml.training_samples.synthetic_ignored, 0)} sintéticos ignorados
                </span>
              </>
            ) : null}
          </p>
        ) : null}
      </div>

      <div className="mt-3 space-y-1 text-[10px] text-slate-600">
        <p className="flex items-center gap-1.5">
          <Clock size={11} />
          Último treino:{' '}
          {lastTraining ? `${formatDateTime(lastTraining)} (${timeAgo(lastTraining)})` : '—'}
        </p>
        <p className="flex items-center gap-1.5">
          <Database size={11} />
          Modelo:{' '}
          {ml?.model?.modified_at ? formatDateTime(ml.model.modified_at) : 'não encontrado'}
        </p>
      </div>

      {notice ? (
        <Alert type={notice.type} className="mt-3">
          {notice.message}
        </Alert>
      ) : null}

      <Button
        variant="primary"
        className="mt-4 w-full"
        loading={training}
        onClick={onTrain}
        disabled={training}
      >
        {training ? (
          <>
            <Loader2 size={15} className="animate-spin" /> Treinando…
          </>
        ) : (
          <>
            <Zap size={15} /> Retreinar Agora
          </>
        )}
      </Button>
      <p className="mt-2 text-center text-[10px] text-slate-600">
        O treino usa o histórico real de trades e recarrega o modelo no monitor.
      </p>
    </Card>
  )
}

export default function MlConsole() {
  const [ml, setMl] = useState(null)
  const [mlLoading, setMlLoading] = useState(true)
  const [mlError, setMlError] = useState('')
  const [training, setTraining] = useState(false)
  const [trainNotice, setTrainNotice] = useState(null)
  const [toggling, setToggling] = useState(false)
  const [toggleNotice, setToggleNotice] = useState(null)

  const [logs, setLogs] = useState([])
  const [logFiles, setLogFiles] = useState([])
  const [logsLoading, setLogsLoading] = useState(true)
  const [logsError, setLogsError] = useState('')
  const [level, setLevel] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [autoScroll, setAutoScroll] = useState(true)

  const consoleRef = useRef(null)

  const loadMl = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setMlLoading(true)
    try {
      const payload = await api.mlStatus()
      setMl(payload)
      setMlError('')
    } catch (exc) {
      setMlError(exc.message)
    } finally {
      setMlLoading(false)
    }
  }, [])

  const loadLogs = useCallback(
    async ({ silent = false } = {}) => {
      if (!silent) setLogsLoading(true)
      try {
        const payload = await api.logs({ lines: 400, level, search })
        setLogs(payload.entries || [])
        setLogFiles(payload.files || [])
        setLogsError('')
      } catch (exc) {
        setLogsError(exc.message)
      } finally {
        setLogsLoading(false)
      }
    },
    [level, search],
  )

  useEffect(() => {
    loadMl()
    const timer = setInterval(() => loadMl({ silent: true }), 15000)
    return () => clearInterval(timer)
  }, [loadMl])

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 400)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  useEffect(() => {
    if (!autoRefresh) return undefined
    const timer = setInterval(() => loadLogs({ silent: true }), 3000)
    return () => clearInterval(timer)
  }, [autoRefresh, loadLogs])

  useEffect(() => {
    if (autoScroll && consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  async function handleToggle() {
    const next = !(ml?.usable && ml?.shadow_mode === false)
    setToggling(true)
    setToggleNotice(null)
    try {
      const payload = await api.toggleMl(next)
      setToggleNotice({
        type: 'success',
        message: payload.enabled
          ? 'Filtro ativado: sinais abaixo do threshold passarão a ser bloqueados.'
          : 'Modo observação ativado: os scores continuam sendo registrados.',
      })
    } catch (exc) {
      setToggleNotice({ type: 'error', message: exc.message })
    } finally {
      setToggling(false)
      await loadMl({ silent: true })
    }
  }

  async function handleTrain() {
    setTraining(true)
    setTrainNotice(null)
    try {
      const payload = await api.trainMl()
      const metrics = payload.metrics || {}
      setTrainNotice({
        type: 'success',
        message: `Treino concluído: acurácia ${formatFractionPercent(
          metrics.test_score,
          1,
        )} com ${formatNumber(metrics.samples_trained, 0)} amostras.${
          payload.model_loaded ? ' Modelo recarregado no monitor.' : ''
        }`,
      })
      await loadMl({ silent: true })
    } catch (exc) {
      setTrainNotice({ type: 'error', message: exc.message })
    } finally {
      setTraining(false)
    }
  }

  const stats = useMemo(() => {
    const counts = { INFO: 0, WARNING: 0, ERROR: 0 }
    logs.forEach((entry) => {
      if (counts[entry.level] !== undefined) counts[entry.level] += 1
    })
    return counts
  }, [logs])

  if (mlLoading && !ml) {
    return <LoadingBlock label="Carregando status do classificador…" />
  }

  return (
    <div className="space-y-5 animate-rise-in">
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="space-y-4">
          {mlError ? <Alert type="error">{mlError}</Alert> : null}
          <MlActivationCard
            ml={ml}
            toggling={toggling}
            onToggle={handleToggle}
            notice={toggleNotice}
          />
          <MlStatusCard
            ml={ml}
            loading={mlLoading}
            training={training}
            onTrain={handleTrain}
            notice={trainNotice}
          />
        </div>

        <Card className="flex min-h-[620px] flex-col p-4 sm:p-5">
          <SectionTitle
            icon={Terminal}
            title="Console de logs"
            subtitle="Últimas linhas do log estruturado, com filtro por nível."
            right={
              <div className="flex items-center gap-2">
                <Badge variant="slate">{logs.length} linhas</Badge>
                <Button
                  className="!px-2.5 !py-1.5 !text-[11px]"
                  onClick={() => loadLogs()}
                  loading={logsLoading}
                >
                  <RefreshCw size={12} /> Atualizar
                </Button>
              </div>
            }
          />

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-slate-950/50 p-1">
              {LEVELS.map((item) => (
                <button
                  key={item.id || 'all'}
                  type="button"
                  onClick={() => setLevel(item.id)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                    level === item.id
                      ? 'bg-white/[0.09] text-white'
                      : 'text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div className="relative min-w-[180px] flex-1">
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-600"
              />
              <input
                className="field !py-2 !pl-9 text-xs"
                placeholder="Buscar no log…"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </div>

            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-500">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-white/20 bg-slate-900 accent-emerald-500"
                checked={autoRefresh}
                onChange={(event) => setAutoRefresh(event.target.checked)}
              />
              Auto
            </label>
            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-500">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-white/20 bg-slate-900 accent-emerald-500"
                checked={autoScroll}
                onChange={(event) => setAutoScroll(event.target.checked)}
              />
              Rolar
            </label>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-slate-600">
            <span>INFO {stats.INFO}</span>
            <span className="text-amber-300/80">WARNING {stats.WARNING}</span>
            <span className="text-rose-300/80">ERROR {stats.ERROR}</span>
            <span className="ml-auto truncate">
              Arquivos: {logFiles.length ? logFiles.join(', ') : '—'}
            </span>
          </div>

          {logsError ? <Alert type="error" className="mt-3">{logsError}</Alert> : null}

          <div
            ref={consoleRef}
            className="mt-3 flex-1 overflow-auto rounded-xl border border-white/[0.07] bg-[#05080d]"
          >
            {logs.length ? (
              <div className="min-w-[640px] font-mono text-[11px] leading-relaxed">
                {logs.map((entry, index) => (
                  <div
                    key={`${entry.file || 'log'}-${entry.timestamp || index}-${index}`}
                    className="flex gap-2 border-b border-white/[0.03] px-3 py-1 hover:bg-white/[0.02]"
                  >
                    <span className="w-[68px] shrink-0 text-slate-700">
                      {entry.timestamp ? entry.timestamp.slice(11) : '--:--:--'}
                    </span>
                    <span
                      className={`w-[62px] shrink-0 font-semibold ${logLevelClass(entry.level)}`}
                    >
                      {entry.level || 'LOG'}
                    </span>
                    <span className="w-[110px] shrink-0 truncate text-slate-600">
                      {entry.logger || entry.file || '—'}
                    </span>
                    <span className="min-w-0 whitespace-pre-wrap break-words text-slate-300">
                      {entry.message}
                    </span>
                  </div>
                ))}
              </div>
            ) : logsLoading ? (
              <LoadingBlock label="Lendo logs…" className="py-16" />
            ) : (
              <EmptyState
                icon={FileText}
                title="Nenhuma linha encontrada"
                description="Ajuste o filtro de nível ou a busca textual."
                className="m-4"
              />
            )}
          </div>

          <p className="mt-2 text-[10px] text-slate-700">
            Atualização automática a cada 3s · {logs.length} linhas exibidas · limite
            máximo de 2.000 linhas por requisição.
          </p>
        </Card>
      </div>
    </div>
  )
}
