import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BrainCircuit,
  CircleDollarSign,
  Gauge,
  History,
  Pause,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Siren,
  TrendingUp,
  Wallet,
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
  Stat,
  StatusDot,
} from '../components/ui.jsx'
import {
  MlModeBadge,
  RecommendationBadge,
  RegimeBadge,
  RiskBadge,
  SideBadge,
} from '../components/badges.jsx'
import {
  clamp,
  formatCurrency,
  formatDateTime,
  formatFractionPercent,
  formatNumber,
  formatPercent,
  formatSignedCurrency,
  formatSignedPercent,
  pnlClass,
  timeAgo,
} from '../lib/format.js'

function SymbolCard({ item }) {
  const position = item.position
  const pnl = position?.unrealized_pnl
  const confidencePct = clamp((Number(item.confidence) || 0) * 100, 0, 100)

  const progress = useMemo(() => {
    if (!position) return null
    const entry = Number(position.entry_price)
    const stop = Number(position.stop_loss)
    const target = Number(position.take_profit)
    const price = Number(position.current_price ?? item.price)
    if (![entry, stop, target, price].every((value) => Number.isFinite(value))) {
      return null
    }
    const span = Math.abs(target - stop)
    if (span <= 0) return null
    return clamp(((price - stop) / span) * 100, 0, 100)
  }, [item.price, position])

  return (
    <Card className="panel-hover animate-rise-in p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold tracking-tight text-slate-50">
              {item.symbol}
            </h3>
            {position ? <SideBadge side={position.side} /> : null}
          </div>
          <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-white">
            {formatCurrency(item.price)}
          </p>
        </div>
        <RegimeBadge regime={item.regime} />
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2 text-slate-500">
          <span className="rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
            {item.engine || '—'}
          </span>
          <span>{timeAgo(item.quote_time)}</span>
        </div>
        <RecommendationBadge recommendation={item.recommendation} />
      </div>

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
          <span>Confiança do sinal</span>
          <span className="font-semibold tabular-nums text-slate-300">
            {formatPercent(confidencePct, 1)}
          </span>
        </div>
        <ProgressBar
          value={confidencePct}
          tone={confidencePct >= 70 ? 'emerald' : confidencePct >= 50 ? 'amber' : 'rose'}
        />
      </div>

      <div className="mt-3 rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
        {position ? (
          <>
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500">PnL flutuante</span>
              <span className={`font-semibold tabular-nums ${pnlClass(pnl)}`}>
                {formatSignedCurrency(pnl)}{' '}
                <span className="text-[10px] opacity-80">
                  ({formatSignedPercent(position.unrealized_pnl_pct, 2)})
                </span>
              </span>
            </div>
            <div className="mt-2.5 flex items-center justify-between text-[11px] text-slate-500">
              <span>
                Entrada{' '}
                <span className="tabular-nums text-slate-300">
                  {formatCurrency(position.entry_price)}
                </span>
              </span>
              <span className="tabular-nums">{position.age ?? 0} ticks</span>
            </div>
            <div className="mt-2">
              <div className="position-track">
                {progress !== null ? (
                  <span className="position-marker" style={{ left: `${progress}%` }} />
                ) : null}
              </div>
              <div className="mt-1 flex items-center justify-between text-[10px] text-slate-600">
                <span>SL {formatCurrency(position.stop_loss)}</span>
                <span>TP {formatCurrency(position.take_profit)}</span>
              </div>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center gap-2 py-3 text-xs text-slate-600">
            <Activity size={13} />
            Sem posição aberta
          </div>
        )}
      </div>
    </Card>
  )
}

function RecentTrades({ trades }) {
  if (!trades?.length) {
    return (
      <EmptyState
        icon={History}
        title="Nenhum trade registrado"
        description="Os trades executados pelo monitor aparecerão aqui automaticamente."
      />
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-left">
        <thead>
          <tr>
            <th className="table-head">Ativo</th>
            <th className="table-head">Lado</th>
            <th className="table-head">Engine</th>
            <th className="table-head">Entrada → Saída</th>
            <th className="table-head">Regime</th>
            <th className="table-head">Duração</th>
            <th className="table-head">PnL</th>
            <th className="table-head">Motivo</th>
          </tr>
        </thead>
        <tbody>
          {trades.slice(0, 12).map((trade, index) => (
            <tr key={trade.id ?? `${trade.symbol}-${index}`} className="table-row">
              <td className="table-cell font-semibold text-slate-100">{trade.symbol}</td>
              <td className="table-cell">
                <SideBadge side={trade.side} />
              </td>
              <td className="table-cell font-mono text-[11px] text-slate-400">
                {trade.engine || '—'}
              </td>
              <td className="table-cell tabular-nums text-slate-400">
                {formatCurrency(trade.entry_price)} → {formatCurrency(trade.exit_price)}
              </td>
              <td className="table-cell text-xs text-slate-400">{trade.entry_regime || '—'}</td>
              <td className="table-cell tabular-nums text-slate-400">
                {trade.duration_ticks ?? '—'}t
              </td>
              <td className={`table-cell font-semibold tabular-nums ${pnlClass(trade.pnl)}`}>
                {formatSignedCurrency(trade.pnl)}
              </td>
              <td className="table-cell text-xs text-slate-500">
                {trade.reason || '—'}
                <span className="ml-2 text-[10px] text-slate-600">
                  {trade.created_at ? timeAgo(trade.created_at) : ''}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function HealthPanel({ data }) {
  const risk = data.risk || {}
  const ml = data.ml || {}
  const equity = data.equity || {}
  const kpis = data.kpis || {}
  const riskLimit = Number(risk.global_limit) || 0
  const riskUsed = Number(risk.global_trades) || 0
  const riskPct = riskLimit > 0 ? clamp((riskUsed / riskLimit) * 100, 0, 100) : 0

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BrainCircuit size={15} className="text-sky-300" />
            <span className="text-xs font-semibold text-slate-300">Saúde do ML</span>
          </div>
          <MlModeBadge mode={ml.mode} trained={ml.trained} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Stat
            label="Acurácia"
            value={ml.accuracy != null ? formatFractionPercent(ml.accuracy, 1) : '—'}
          />
          <Stat label="Amostras" value={formatNumber(ml.samples_trained, 0)} />
          <Stat label="Threshold" value={formatPercent((ml.threshold || 0) * 100, 1)} />
          <Stat label="Trades p/ treino" value={formatNumber(ml.trade_count, 0)} />
        </div>
      </div>

      <div className="rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck size={15} className="text-emerald-300" />
            <span className="text-xs font-semibold text-slate-300">Risco</span>
          </div>
          <RiskBadge level={risk.aggressiveness_level} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Stat label="Posições abertas" value={risk.total_open_positions ?? 0} />
          <Stat
            label="Kill switch"
            value={risk.kill_switch_active ? 'Ativo' : 'Inativo'}
            tone={risk.kill_switch_active ? 'negative' : 'default'}
          />
          <Stat label="Equity" value={formatCurrency(equity.current_equity)} />
          <Stat
            label="Drawdown atual"
            value={formatPercent(equity.current_drawdown_pct)}
            tone={
              Number(equity.current_drawdown_pct) > 10 ? 'negative' : 'default'
            }
          />
        </div>
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
            <span>Limite global de trades</span>
            <span className="tabular-nums text-slate-300">
              {riskUsed}/{riskLimit || '—'}
            </span>
          </div>
          <ProgressBar value={riskPct} tone={riskPct > 80 ? 'rose' : 'emerald'} />
        </div>
        <p className="mt-3 text-[11px] text-slate-600">
          Win rate consolidado:{' '}
          <span className="font-semibold text-slate-400">
            {formatFractionPercent(kpis.win_rate, 1)}
          </span>{' '}
          · {kpis.trade_count ?? 0} trades no histórico
        </p>
      </div>
    </div>
  )
}

export default function ControlRoom() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [lastUpdated, setLastUpdated] = useState(null)

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading((current) => current && true)
    try {
      const payload = await api.live()
      setData(payload)
      setLastUpdated(new Date())
      setError('')
    } catch (exc) {
      setError(exc.message || 'Falha ao carregar o estado ao vivo')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let mounted = true

    async function poll() {
      try {
        const payload = await api.live()
        if (!mounted) return
        setData(payload)
        setLastUpdated(new Date())
        setError('')
      } catch (exc) {
        if (mounted) setError(exc.message || 'Falha ao carregar o estado ao vivo')
      } finally {
        if (mounted) setLoading(false)
      }
    }

    poll()
    const timer = setInterval(poll, 4000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  }, [])

  const running = Boolean(data?.monitor_running) && !data?.monitor_paused

  async function handleRefresh() {
    setBusy('refresh')
    try {
      await refresh()
    } finally {
      setBusy('')
    }
  }

  async function handleToggle() {
    setBusy('toggle')
    setNotice(null)
    try {
      const action = running ? 'pause' : 'start'
      const result = await api.toggleMonitor(action)
      const messages = {
        started: 'Monitor iniciado com sucesso.',
        already_running: 'O monitor já estava ativo.',
        paused: 'Monitor pausado. O servidor continua no ar.',
        pausing: 'Pausa solicitada; o loop está finalizando o ciclo atual.',
        already_paused: 'O monitor já estava pausado.',
      }
      setNotice({
        type: result.action === 'paused' || result.action === 'pausing' ? 'warning' : 'success',
        message: messages[result.action] || 'Comando aplicado.',
      })
      await refresh({ silent: true })
    } catch (exc) {
      setNotice({ type: 'error', message: exc.message })
    } finally {
      setBusy('')
    }
  }

  async function handlePanicClose() {
    const confirmed = window.confirm(
      'Panic Close: fechar TODAS as posições abertas ao último preço conhecido?\n\nEsta ação é imediata e não pode ser desfeita.',
    )
    if (!confirmed) return

    setBusy('panic')
    setNotice(null)
    try {
      const result = await api.panicClose()
      setNotice({
        type: result.errors?.length ? 'warning' : 'success',
        message:
          result.closed_count > 0
            ? `${result.closed_count} posição(ões) fechada(s) via Panic Close.`
            : 'Nenhuma posição aberta para fechar.',
      })
      await refresh({ silent: true })
    } catch (exc) {
      setNotice({ type: 'error', message: exc.message })
    } finally {
      setBusy('')
    }
  }

  if (loading && !data) {
    return <LoadingBlock label="Conectando ao motor…" />
  }

  if (error && !data) {
    return (
      <div className="space-y-4">
        <Alert type="error">{error}</Alert>
        <Button onClick={() => refresh()} className="mx-auto">
          <RefreshCw size={15} /> Tentar novamente
        </Button>
      </div>
    )
  }

  const equity = data?.equity || {}
  const risk = data?.risk || {}
  const kpis = data?.kpis || {}
  const ml = data?.ml || {}
  const symbols = data?.symbols || []
  const recentTrades = data?.recent_trades || []

  const pnlTone =
    Number(equity.total_pnl) > 0
      ? 'positive'
      : Number(equity.total_pnl) < 0
        ? 'negative'
        : 'default'

  return (
    <div className="space-y-5 animate-rise-in">
      <Card className="flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-3">
            <span
              className={`grid h-11 w-11 place-items-center rounded-xl border ${
                running
                  ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300'
                  : 'border-amber-400/25 bg-amber-400/10 text-amber-300'
              }`}
            >
              <Activity size={20} />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <StatusDot active={running} />
                <span className="text-sm font-semibold text-slate-100">
                  {running ? 'Motor ativo' : 'Motor pausado'}
                </span>
                <RiskBadge level={risk.aggressiveness_level} />
              </div>
              <p className="mt-0.5 text-xs text-slate-500">
                {running
                  ? 'Coletando cotações e avaliando sinais em tempo real.'
                  : 'Operações paradas. O servidor Flask permanece disponível.'}
              </p>
            </div>
          </div>

          <div className="hidden h-10 w-px bg-white/10 lg:block" />

          <div className="flex items-center gap-2">
            <MlModeBadge mode={ml.mode} trained={ml.trained} />
            <Badge variant={risk.kill_switch_active ? 'rose' : 'emerald'}>
              {risk.kill_switch_active ? 'Kill switch ativo' : 'Risco liberado'}
            </Badge>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 hidden text-[11px] text-slate-600 sm:inline">
            {lastUpdated ? `Atualizado ${timeAgo(lastUpdated)}` : '—'}
          </span>
          <Button onClick={handleRefresh} loading={busy === 'refresh'}>
            <RefreshCw size={15} /> Atualizar
          </Button>
          <Button
            variant={running ? 'ghost' : 'primary'}
            onClick={handleToggle}
            loading={busy === 'toggle'}
          >
            {running ? <Pause size={15} /> : <Play size={15} />}
            {running ? 'Pausar' : 'Iniciar'}
          </Button>
          <Button
            variant="danger"
            onClick={handlePanicClose}
            loading={busy === 'panic'}
            disabled={!risk.total_open_positions}
            title={
              risk.total_open_positions
                ? 'Fechar todas as posições abertas'
                : 'Nenhuma posição aberta'
            }
          >
            <Siren size={15} /> Panic Close
          </Button>
        </div>
      </Card>

      {error ? <Alert type="error">{error}</Alert> : null}
      {notice ? <Alert type={notice.type}>{notice.message}</Alert> : null}

      <Card className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 sm:p-5 xl:grid-cols-6">
        <Stat
          icon={Wallet}
          label="Equity atual"
          value={formatCurrency(equity.current_equity)}
          hint={`Inicial ${formatCurrency(equity.initial_capital)}`}
        />
        <Stat
          icon={CircleDollarSign}
          label="PnL total"
          value={formatSignedCurrency(equity.total_pnl)}
          hint={`${formatSignedPercent(equity.total_return_pct)} de retorno`}
          tone={pnlTone}
        />
        <Stat
          icon={TrendingUp}
          label="Win rate"
          value={formatFractionPercent(kpis.win_rate, 1)}
          hint={`${kpis.trade_count ?? 0} trades registrados`}
        />
        <Stat
          icon={ArrowUpRight}
          label="PnL médio"
          value={formatSignedCurrency(kpis.avg_pnl)}
          hint={`Duração média ${formatNumber(kpis.avg_duration, 1)} ticks`}
          tone={Number(kpis.avg_pnl) >= 0 ? 'positive' : 'negative'}
        />
        <Stat
          icon={ArrowDownRight}
          label="Drawdown atual"
          value={formatPercent(equity.current_drawdown_pct)}
          hint={`Máximo ${formatPercent(equity.max_drawdown_pct)}`}
          tone={Number(equity.current_drawdown_pct) > 10 ? 'negative' : 'default'}
        />
        <Stat
          icon={Gauge}
          label="Posições abertas"
          value={risk.total_open_positions ?? 0}
          hint={`${risk.global_trades ?? 0}/${risk.global_limit ?? '—'} trades no limite`}
        />
      </Card>

      <div>
        <SectionTitle
          icon={CircleDollarSign}
          title="Mercados monitorados"
          subtitle="Preço, regime, sinal e posição aberta por ativo."
          right={
            <span className="text-[11px] text-slate-600">
              USD · BTC · ETH · SOL
            </span>
          }
        />
        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {symbols.map((item) => (
            <SymbolCard key={item.symbol} item={item} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(0,1fr)]">
        <Card className="p-4 sm:p-5">
          <SectionTitle
            icon={History}
            title="Trades recentes"
            subtitle="Últimos resultados registrados pelo motor em produção."
            right={
              <Badge variant="slate">
                {kpis.trade_count ?? 0} no histórico
              </Badge>
            }
          />
          <div className="mt-4">
            <RecentTrades trades={recentTrades} />
          </div>
        </Card>

        <Card className="p-4 sm:p-5">
          <SectionTitle
            icon={ShieldAlert}
            title="Saúde operacional"
            subtitle="Risco, equity e classificador em um só lugar."
            right={
              <span className="text-[11px] text-slate-600">
                {data?.server_time ? formatDateTime(data.server_time) : '—'}
              </span>
            }
          />
          <div className="mt-4">
            <HealthPanel data={data} />
          </div>
        </Card>
      </div>
    </div>
  )
}
