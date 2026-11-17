import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Database,
  FlaskConical,
  FolderOpen,
  Gauge,
  History,
  Layers,
  Play,
  RefreshCw,
  Sigma,
  Trophy,
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
  Stat,
} from '../components/ui.jsx'
import { ModeBadge, ResultBadge, SideBadge } from '../components/badges.jsx'
import {
  formatCurrency,
  formatDateTime,
  formatFractionPercent,
  formatNumber,
  formatPercent,
  formatSignedCurrency,
  formatSignedPercent,
  pnlClass,
} from '../lib/format.js'

const SOURCES = [
  { value: 'synthetic', label: 'Sintético', hint: 'Dados gerados com blocos de regime' },
  { value: 'db', label: 'Banco local', hint: 'Histórico da tabela de cotações' },
  { value: 'api', label: 'Binance / API', hint: 'Cotações reais com cache local' },
]

const TICK_PRESETS = [500, 5000, 20000]

function buildFunnel(report) {
  if (!report) return null
  const engineBreakdown = report.engine_signal_breakdown || {}
  const rawSignals = Object.values(engineBreakdown).reduce(
    (total, value) => total + (Number(value) || 0),
    0,
  )
  const approved = Number(report.total_signals_approved) || 0
  const executed = Number(report.trades_executed) || 0
  const filters = report.filter_stats || {}
  const filterRows = [
    { label: 'Confirmação de tendência', value: filters.blocked_trend_confirmation || 0 },
    { label: 'Exaustão', value: filters.blocked_exhaustion || 0 },
    { label: 'Classificador ML', value: filters.blocked_ml || 0 },
    { label: 'Risk controller', value: filters.blocked_risk_controller || 0 },
    { label: 'Sem vaga de posição', value: filters.blocked_position_slot || 0 },
  ]
  const blockedTotal = filterRows.reduce((total, row) => total + row.value, 0)
  const scale = Math.max(rawSignals, approved, executed, blockedTotal, 1)

  return {
    totalTicks: Number(report.total_ticks) || 0,
    rawSignals,
    approved,
    executed,
    blockedTotal,
    filterRows,
    scale,
    engineBreakdown,
    approvalsByEngine: report.trades_by_engine || {},
    regimeBreakdown: report.regime_breakdown || {},
    winRate: report.win_rate,
    approvalRate: report.approval_rate,
  }
}

function FunnelStage({ label, value, scale, tone, hint }) {
  const pct = value > 0 ? Math.max(2, (value / scale) * 100) : 0
  const toneClass =
    tone === 'sky'
      ? 'from-sky-400/80 to-sky-500/40'
      : tone === 'violet'
        ? 'from-violet-400/80 to-violet-500/40'
        : 'from-emerald-400/80 to-emerald-500/40'
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="text-xs font-medium text-slate-400">{label}</span>
        <span className="text-sm font-semibold tabular-nums text-slate-100">
          {formatNumber(value, 0)}
          {hint ? <span className="ml-2 text-[10px] font-normal text-slate-600">{hint}</span> : null}
        </span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className={`h-full rounded-full bg-gradient-to-r ${toneClass} transition-[width] duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function FunnelView({ report }) {
  const funnel = useMemo(() => buildFunnel(report), [report])

  if (!funnel) {
    return (
      <EmptyState
        icon={BarChart3}
        title="Nenhuma simulação executada"
        description="Rode um backtest para visualizar o funil de decisões, o comparativo entre modos e a lista auditável de trades."
      />
    )
  }

  const conversionRaw = funnel.rawSignals
    ? (funnel.approved / funnel.rawSignals) * 100
    : 0
  const conversionExec = funnel.approved
    ? (funnel.executed / funnel.approved) * 100
    : 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <Stat icon={Gauge} label="Ticks processados" value={formatNumber(funnel.totalTicks, 0)} />
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <Stat icon={Sigma} label="Sinais brutos" value={formatNumber(funnel.rawSignals, 0)} />
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <Stat
            icon={CheckCircle2}
            label="Sinais aprovados"
            value={formatNumber(funnel.approved, 0)}
            hint={`${formatPercent(funnel.approvalRate, 1)} dos ticks`}
          />
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <Stat
            icon={Trophy}
            label="Trades executados"
            value={formatNumber(funnel.executed, 0)}
            hint={`Win rate ${formatPercent(funnel.winRate, 1)}`}
          />
        </div>
      </div>

      <div className="space-y-3 rounded-xl border border-white/[0.07] bg-slate-950/40 p-4">
        <FunnelStage
          label="Sinais brutos das engines"
          value={funnel.rawSignals}
          scale={funnel.scale}
          tone="sky"
        />
        <div className="flex items-center gap-2 pl-2 text-[10px] text-slate-600">
          <ArrowRight size={12} />
          conversão {formatPercent(conversionRaw, 1)}
        </div>
        <FunnelStage
          label="Sinais aprovados pelos filtros"
          value={funnel.approved}
          scale={funnel.scale}
          tone="emerald"
        />
        <div className="flex items-center gap-2 pl-2 text-[10px] text-slate-600">
          <ArrowRight size={12} />
          conversão {formatPercent(conversionExec, 1)}
        </div>
        <FunnelStage
          label="Trades executados"
          value={funnel.executed}
          scale={funnel.scale}
          tone="violet"
        />
      </div>

      <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-4">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs font-semibold text-slate-300">Bloqueios por filtro</p>
          <Badge variant="rose">{formatNumber(funnel.blockedTotal, 0)} bloqueios</Badge>
        </div>
        <div className="space-y-2.5">
          {funnel.filterRows.map((row) => (
            <div key={row.label}>
              <div className="mb-1 flex items-center justify-between text-[11px]">
                <span className="text-slate-500">{row.label}</span>
                <span className="font-semibold tabular-nums text-slate-300">
                  {formatNumber(row.value, 0)}
                </span>
              </div>
              <ProgressBar
                value={row.value > 0 ? Math.max(1.5, (row.value / funnel.scale) * 100) : 0}
                tone="rose"
              />
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-4">
          <p className="text-xs font-semibold text-slate-300">Sinais por engine</p>
          <div className="mt-2 space-y-1.5">
            {Object.entries(funnel.engineBreakdown).length ? (
              Object.entries(funnel.engineBreakdown).map(([engine, count]) => (
                <div key={engine} className="flex items-center justify-between text-[11px]">
                  <span className="font-mono text-slate-500">{engine}</span>
                  <span className="tabular-nums text-slate-300">{count}</span>
                </div>
              ))
            ) : (
              <p className="text-[11px] text-slate-600">Sem sinais no período.</p>
            )}
          </div>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-4">
          <p className="text-xs font-semibold text-slate-300">Ticks por regime</p>
          <div className="mt-2 space-y-1.5">
            {Object.entries(funnel.regimeBreakdown).length ? (
              Object.entries(funnel.regimeBreakdown).map(([regime, count]) => (
                <div key={regime} className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-500">{regime.replaceAll('_', ' ')}</span>
                  <span className="tabular-nums text-slate-300">{count}</span>
                </div>
              ))
            ) : (
              <p className="text-[11px] text-slate-600">Sem dados de regime.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function ModeCard({ title, subtitle, data, icon: Icon, tone }) {
  const stats = data?.trade_statistics || {}
  const toneRing =
    tone === 'violet'
      ? 'border-violet-400/20 bg-violet-400/[0.04]'
      : 'border-sky-400/20 bg-sky-400/[0.04]'

  return (
    <div className={`rounded-xl border p-4 ${toneRing}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`grid h-8 w-8 place-items-center rounded-lg border ${
              tone === 'violet'
                ? 'border-violet-400/20 bg-violet-400/10 text-violet-300'
                : 'border-sky-400/20 bg-sky-400/10 text-sky-300'
            }`}
          >
            <Icon size={15} />
          </span>
          <div>
            <p className="text-sm font-semibold text-slate-100">{title}</p>
            <p className="text-[10px] uppercase tracking-[0.14em] text-slate-600">
              {subtitle}
            </p>
          </div>
        </div>
        <ModeBadge mode={data?.mode} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <Stat label="Trades" value={formatNumber(stats.total_trades, 0)} />
        <Stat
          label="Win rate"
          value={formatFractionPercent(stats.win_rate, 1)}
          tone={Number(stats.win_rate) >= 0.5 ? 'positive' : 'negative'}
        />
        <Stat label="Equity final" value={formatCurrency(data?.final_equity)} />
        <Stat
          label="PnL total"
          value={formatSignedCurrency(data?.total_pnl)}
          tone={Number(data?.total_pnl) >= 0 ? 'positive' : 'negative'}
        />
        <Stat
          label="Retorno"
          value={formatSignedPercent((Number(data?.total_return) || 0) * 100)}
          tone={Number(data?.total_return) >= 0 ? 'positive' : 'negative'}
        />
        <Stat
          label="Drawdown máx."
          value={formatPercent((Number(data?.max_drawdown) || 0) * 100)}
          tone={Number(data?.max_drawdown) > 0.1 ? 'negative' : 'default'}
        />
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-slate-600">
        <span>PnL médio {formatSignedCurrency(stats.avg_pnl_amount)}</span>
        <span>Duração média {formatNumber(stats.avg_duration, 1)}t</span>
      </div>
    </div>
  )
}

function ComparisonView({ result }) {
  if (!result) return null
  const comparison = result.comparison || {}
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ModeCard
          title="RESEARCH"
          subtitle="Agressivo · teste de estratégia"
          data={result.research}
          icon={FlaskConical}
          tone="violet"
        />
        <ModeCard
          title="PAPER_TRADING"
          subtitle="Conservador · controle de risco"
          data={result.paper_trading}
          icon={Layers}
          tone="sky"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <Stat
            label="Redução de trades"
            value={formatPercent(comparison.trade_reduction_pct, 1)}
            hint="PAPER vs RESEARCH"
          />
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <Stat
            label="Preservação de equity"
            value={formatPercent(comparison.equity_preservation_pct, 1)}
            hint="Capital final comparado"
          />
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
          <Stat
            label="Controle de risco"
            value={comparison.risk_control_passed ? 'Aprovado' : 'Atenção'}
            hint="Drawdown do PAPER abaixo de 25%"
            tone={comparison.risk_control_passed ? 'positive' : 'negative'}
          />
        </div>
      </div>
    </div>
  )
}

function TradesTable({ result, modeFilter, setModeFilter }) {
  const allTrades = useMemo(() => {
    const list = []
    ;(result?.research?.trades || []).forEach((trade) =>
      list.push({ ...trade, mode: 'RESEARCH' }),
    )
    ;(result?.paper_trading?.trades || []).forEach((trade) =>
      list.push({ ...trade, mode: 'PAPER_TRADING' }),
    )
    return list.sort((a, b) => (a.entry_tick || 0) - (b.entry_tick || 0))
  }, [result])

  const filtered = useMemo(() => {
    if (modeFilter === 'all') return allTrades
    if (modeFilter === 'research') {
      return allTrades.filter((trade) => trade.mode === 'RESEARCH')
    }
    return allTrades.filter((trade) => trade.mode === 'PAPER_TRADING')
  }, [allTrades, modeFilter])

  const visible = filtered.slice(0, 200)

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {[
          { id: 'all', label: `Todos (${allTrades.length})` },
          {
            id: 'research',
            label: `Research (${allTrades.filter((t) => t.mode === 'RESEARCH').length})`,
          },
          {
            id: 'paper',
            label: `Paper (${allTrades.filter((t) => t.mode === 'PAPER_TRADING').length})`,
          },
        ].map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setModeFilter(item.id)}
            className={`rounded-lg px-2.5 py-1.5 text-[11px] font-semibold transition ${
              modeFilter === item.id
                ? 'bg-white/[0.09] text-white'
                : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-300'
            }`}
          >
            {item.label}
          </button>
        ))}
        {filtered.length > visible.length ? (
          <span className="ml-auto text-[10px] text-slate-600">
            Exibindo {visible.length} de {filtered.length} trades
          </span>
        ) : null}
      </div>

      {visible.length ? (
        <div className="max-h-[430px] overflow-auto rounded-xl border border-white/[0.07]">
          <table className="w-full min-w-[980px] border-collapse text-left">
            <thead className="sticky top-0 z-10 bg-[#0b111b]">
              <tr>
                <th className="table-head">Tick</th>
                <th className="table-head">Modo</th>
                <th className="table-head">Lado</th>
                <th className="table-head">Engine</th>
                <th className="table-head">Entrada</th>
                <th className="table-head">Saída</th>
                <th className="table-head">Regime</th>
                <th className="table-head">Conf.</th>
                <th className="table-head">PnL</th>
                <th className="table-head">Dur.</th>
                <th className="table-head">Motivo</th>
                <th className="table-head">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((trade, index) => (
                <tr key={`${trade.mode}-${trade.entry_tick}-${index}`} className="table-row">
                  <td className="table-cell tabular-nums text-slate-500">{trade.entry_tick}</td>
                  <td className="table-cell">
                    <ModeBadge mode={trade.mode} />
                  </td>
                  <td className="table-cell">
                    <SideBadge side={trade.side} />
                  </td>
                  <td className="table-cell font-mono text-[11px] text-slate-400">
                    {trade.engine}
                  </td>
                  <td className="table-cell tabular-nums">{formatCurrency(trade.entry_price)}</td>
                  <td className="table-cell tabular-nums">{formatCurrency(trade.exit_price)}</td>
                  <td className="table-cell text-xs text-slate-400">
                    {String(trade.entry_regime || '').replaceAll('_', ' ')}
                  </td>
                  <td className="table-cell tabular-nums text-slate-400">
                    {formatFractionPercent(trade.confidence, 0)}
                  </td>
                  <td className={`table-cell font-semibold tabular-nums ${pnlClass(trade.pnl)}`}>
                    {formatSignedCurrency(trade.pnl)}
                  </td>
                  <td className="table-cell tabular-nums text-slate-400">
                    {trade.duration_ticks}t
                  </td>
                  <td className="table-cell text-xs text-slate-500">{trade.reason}</td>
                  <td className="table-cell">
                    <ResultBadge result={trade.result} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon={BarChart3}
          title="Nenhum trade neste filtro"
          description="Altere o filtro de modo ou rode uma simulação com mais ticks."
        />
      )}
    </div>
  )
}

function HistoryList({ reports, loading, onOpen, opening }) {
  if (loading) {
    return <LoadingBlock label="Carregando histórico…" className="py-6" />
  }

  if (!reports.length) {
    return (
      <EmptyState
        icon={FolderOpen}
        title="Nenhum relatório salvo"
        description="Cada backtest concluído gera um relatório JSON em simulation_reports/."
      />
    )
  }

  return (
    <div className="space-y-2">
      {reports.map((report) => (
        <div
          key={report.filename}
          className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/[0.07] bg-slate-950/40 px-3 py-2.5"
        >
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-slate-300">
              {report.symbol || '—'} · {report.ticks ?? '—'} ticks ·{' '}
              {report.data_source || '—'}
            </p>
            <p className="mt-0.5 text-[10px] text-slate-600">
              {report.timestamp ? formatDateTime(report.timestamp) : report.modified_at}
              {' · '}
              R {report.research?.total_trades ?? 0} / P {report.paper_trading?.total_trades ?? 0}
            </p>
          </div>
          <Button
            className="!px-2.5 !py-1.5 !text-[11px]"
            onClick={() => onOpen(report.filename)}
            loading={opening === report.filename}
          >
            Abrir
          </Button>
        </div>
      ))}
    </div>
  )
}

export default function SimulationLab() {
  const [form, setForm] = useState({
    symbol: 'USD',
    source: 'synthetic',
    ticks: 5000,
    seed: 42,
    capital: 100000,
    refresh: false,
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [opening, setOpening] = useState('')
  const [modeFilter, setModeFilter] = useState('all')
  const [showHistory, setShowHistory] = useState(false)

  async function loadHistory() {
    setHistoryLoading(true)
    try {
      const payload = await api.simulations(15)
      setHistory(payload.reports || [])
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    loadHistory()
  }, [])

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function handleRun(event) {
    event.preventDefault()
    setError('')

    const ticks = Number(form.ticks)
    const capital = Number(form.capital)
    if (!Number.isFinite(ticks) || ticks < 1 || ticks > 50000) {
      setError('Ticks deve ser um inteiro entre 1 e 50.000.')
      return
    }
    if (!Number.isFinite(capital) || capital <= 0) {
      setError('Capital deve ser maior que zero.')
      return
    }

    setRunning(true)
    try {
      const payload = await api.simulate({
        symbol: form.symbol,
        source: form.source,
        ticks,
        seed: form.seed === '' ? null : Number(form.seed),
        capital,
        refresh: form.refresh,
      })
      setResult(payload)
      setModeFilter('all')
      setError('')
      loadHistory()
      requestAnimationFrame(() => {
        document.getElementById('resultado-simulacao')?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        })
      })
    } catch (exc) {
      setError(exc.message)
    } finally {
      setRunning(false)
    }
  }

  async function handleOpenReport(filename) {
    setOpening(filename)
    setError('')
    try {
      const payload = await api.simulation(filename)
      setResult({
        research: payload.report?.research,
        paper_trading: payload.report?.paper_trading,
        comparison: payload.report?.comparison,
        report_path: filename,
        loaded_from: filename,
      })
      setModeFilter('all')
      requestAnimationFrame(() => {
        document.getElementById('resultado-simulacao')?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        })
      })
    } catch (exc) {
      setError(exc.message)
    } finally {
      setOpening('')
    }
  }

  const funnelReport = result?.research?._funnel_report
  const tradeCount = useMemo(() => {
    const research = result?.research?.trades?.length || 0
    const paper = result?.paper_trading?.trades?.length || 0
    return research + paper
  }, [result])

  return (
    <div className="space-y-5 animate-rise-in">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <Card className="p-4 sm:p-5">
          <SectionTitle
            icon={FlaskConical}
            title="Laboratório de Simulação"
            subtitle="Roda o motor real em RESEARCH e PAPER_TRADING, com seed reprodutível."
          />

          <form className="mt-4 space-y-4" onSubmit={handleRun}>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="field-label" htmlFor="sim-symbol">
                  Ativo
                </label>
                <select
                  id="sim-symbol"
                  className="field"
                  value={form.symbol}
                  onChange={(event) => updateField('symbol', event.target.value)}
                >
                  {['USD', 'BTC', 'ETH', 'SOL'].map((symbol) => (
                    <option key={symbol} value={symbol}>
                      {symbol}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="field-label" htmlFor="sim-ticks">
                  Ticks
                </label>
                <input
                  id="sim-ticks"
                  className="field"
                  type="number"
                  min="1"
                  max="50000"
                  step="1"
                  value={form.ticks}
                  onChange={(event) => updateField('ticks', event.target.value)}
                />
              </div>
            </div>

            <div>
              <span className="field-label">Fonte de dados</span>
              <div className="grid grid-cols-3 gap-1.5 rounded-xl border border-white/10 bg-slate-950/60 p-1">
                {SOURCES.map((source) => (
                  <button
                    key={source.value}
                    type="button"
                    onClick={() => updateField('source', source.value)}
                    className={`rounded-lg px-2 py-2 text-[11px] font-semibold transition ${
                      form.source === source.value
                        ? 'bg-white/[0.09] text-white'
                        : 'text-slate-500 hover:text-slate-300'
                    }`}
                    title={source.hint}
                  >
                    {source.label}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-[10px] text-slate-600">
                {SOURCES.find((source) => source.value === form.source)?.hint}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="field-label" htmlFor="sim-seed">
                  Seed
                </label>
                <input
                  id="sim-seed"
                  className="field"
                  type="number"
                  step="1"
                  placeholder="Aleatória"
                  value={form.seed}
                  onChange={(event) => updateField('seed', event.target.value)}
                />
              </div>
              <div>
                <label className="field-label" htmlFor="sim-capital">
                  Capital inicial
                </label>
                <input
                  id="sim-capital"
                  className="field"
                  type="number"
                  min="1"
                  step="1000"
                  value={form.capital}
                  onChange={(event) => updateField('capital', event.target.value)}
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-[10px] uppercase tracking-[0.14em] text-slate-600">
                Atalhos
              </span>
              {TICK_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => updateField('ticks', preset)}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                    Number(form.ticks) === preset
                      ? 'bg-emerald-400/10 text-emerald-300'
                      : 'bg-white/[0.04] text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {preset.toLocaleString('pt-BR')}
                </button>
              ))}
            </div>

            {form.source === 'api' ? (
              <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-white/20 bg-slate-900 accent-emerald-500"
                  checked={form.refresh}
                  onChange={(event) => updateField('refresh', event.target.checked)}
                />
                Forçar download novo (ignorar cache)
              </label>
            ) : null}

            {error ? <Alert type="error">{error}</Alert> : null}

            <Button
              type="submit"
              variant="primary"
              className="w-full"
              loading={running}
              disabled={running}
            >
              {running ? (
                <>Executando backtest…</>
              ) : (
                <>
                  <Play size={15} /> Rodar Backtest
                </>
              )}
            </Button>
            <p className="text-center text-[10px] text-slate-600">
              A simulação usa as engines, filtros e gestores reais de produção.
            </p>
          </form>

          <div className="mt-5 border-t border-white/[0.07] pt-4">
            <button
              type="button"
              onClick={() => setShowHistory((current) => !current)}
              className="flex w-full items-center justify-between text-left"
            >
              <span className="inline-flex items-center gap-2 text-xs font-semibold text-slate-300">
                <History size={14} className="text-slate-500" />
                Histórico de relatórios
                <Badge variant="slate">{history.length}</Badge>
              </span>
              {showHistory ? (
                <ChevronUp size={15} className="text-slate-500" />
              ) : (
                <ChevronDown size={15} className="text-slate-500" />
              )}
            </button>
            {showHistory ? (
              <div className="mt-3">
                <HistoryList
                  reports={history}
                  loading={historyLoading}
                  onOpen={handleOpenReport}
                  opening={opening}
                />
              </div>
            ) : null}
          </div>
        </Card>

        <Card className="p-4 sm:p-5">
          <SectionTitle
            icon={BarChart3}
            title="Funil de decisões"
            subtitle="Da geração de sinais até o trade executado, com cada filtro auditável."
            right={
              <Button
                className="!px-2.5 !py-1.5 !text-[11px]"
                onClick={loadHistory}
                loading={historyLoading}
              >
                <RefreshCw size={12} /> Atualizar
              </Button>
            }
          />
          <div className="mt-4">
            <FunnelView report={funnelReport} />
          </div>
        </Card>
      </div>

      <div id="resultado-simulacao" className="space-y-4">
        <Card className="p-4 sm:p-5">
          <SectionTitle
            icon={Layers}
            title="RESEARCH vs PAPER_TRADING"
            subtitle="Comparativo lado a lado dos dois modos sobre os mesmos dados."
            right={
              result ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="slate">
                    {result.research?.symbol || '—'} · {result.research?.ticks || '—'} ticks
                  </Badge>
                  <Badge variant="slate">Seed {result.research?.seed ?? '—'}</Badge>
                  {result.report_path ? (
                    <Badge variant="emerald">Relatório salvo</Badge>
                  ) : null}
                </div>
              ) : null
            }
          />
          <div className="mt-4">
            {result ? (
              <ComparisonView result={result} />
            ) : (
              <EmptyState
                icon={Layers}
                title="Comparativo indisponível"
                description="Execute um backtest ou abra um relatório do histórico."
              />
            )}
          </div>
        </Card>

        <Card className="p-4 sm:p-5">
          <SectionTitle
            icon={Database}
            title="Trades auditáveis"
            subtitle="Cada execução simulada, com engine, regime, confiança e motivo de saída."
            right={<Badge variant="slate">{tradeCount} trades</Badge>}
          />
          <div className="mt-4">
            {result ? (
              <TradesTable
                result={result}
                modeFilter={modeFilter}
                setModeFilter={setModeFilter}
              />
            ) : (
              <EmptyState
                icon={Database}
                title="Nenhum trade para auditar"
                description="Os trades simulados aparecerão aqui após o primeiro backtest."
              />
            )}
          </div>
        </Card>
      </div>

      {running ? (
        <div className="fixed bottom-5 right-5 z-40 flex items-center gap-2.5 rounded-xl border border-emerald-400/20 bg-[#0b111b]/95 px-4 py-3 text-xs text-emerald-200 shadow-2xl backdrop-blur">
          <Spinner size={15} />
          Simulando no motor real…
        </div>
      ) : null}
    </div>
  )
}
