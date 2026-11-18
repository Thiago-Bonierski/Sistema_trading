import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from 'lucide-react'

export function Card({ className = '', children, ...props }) {
  return (
    <section className={`panel ${className}`} {...props}>
      {children}
    </section>
  )
}

export function SectionTitle({ icon: Icon, title, subtitle, right }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-3">
        {Icon ? (
          <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/[0.04] text-emerald-300">
            <Icon size={17} />
          </span>
        ) : null}
        <div>
          <h2 className="text-base font-semibold tracking-tight text-slate-100">
            {title}
          </h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {right}
    </div>
  )
}

const BADGE_VARIANTS = {
  emerald: 'border border-emerald-400/20 bg-emerald-400/10 text-emerald-300',
  rose: 'border border-rose-400/20 bg-rose-400/10 text-rose-300',
  amber: 'border border-amber-400/20 bg-amber-400/10 text-amber-300',
  sky: 'border border-sky-400/20 bg-sky-400/10 text-sky-300',
  violet: 'border border-violet-400/20 bg-violet-400/10 text-violet-300',
  slate: 'border border-white/10 bg-white/[0.04] text-slate-300',
}

export function Badge({ variant = 'slate', className = '', children }) {
  return (
    <span className={`chip ${BADGE_VARIANTS[variant] || BADGE_VARIANTS.slate} ${className}`}>
      {children}
    </span>
  )
}

export function StatusDot({ active, className = '' }) {
  return (
    <span className={`relative flex h-2.5 w-2.5 ${className}`}>
      {active ? (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
      ) : null}
      <span
        className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
          active ? 'bg-emerald-400' : 'bg-amber-400'
        }`}
      />
    </span>
  )
}

export function Spinner({ size = 16, className = '' }) {
  return <Loader2 size={size} className={`animate-spin ${className}`} />
}

export function Button({
  children,
  variant = 'ghost',
  loading = false,
  className = '',
  ...props
}) {
  const variantClass =
    variant === 'primary'
      ? 'btn-primary'
      : variant === 'danger'
        ? 'btn-danger'
        : 'btn-ghost'
  return (
    <button
      type="button"
      className={`${variantClass} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? <Spinner size={15} /> : null}
      {children}
    </button>
  )
}

const ALERT_STYLES = {
  error: {
    wrapper: 'border-rose-400/20 bg-rose-400/[0.08] text-rose-200',
    Icon: XCircle,
  },
  success: {
    wrapper: 'border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-200',
    Icon: CheckCircle2,
  },
  warning: {
    wrapper: 'border-amber-400/20 bg-amber-400/[0.08] text-amber-200',
    Icon: AlertTriangle,
  },
  info: {
    wrapper: 'border-sky-400/20 bg-sky-400/[0.08] text-sky-200',
    Icon: Info,
  },
}

export function Alert({ type = 'info', children, className = '' }) {
  const style = ALERT_STYLES[type] || ALERT_STYLES.info
  const Icon = style.Icon
  if (!children) return null
  return (
    <div
      className={`flex items-start gap-2.5 rounded-xl border px-3.5 py-3 text-sm ${style.wrapper} ${className}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 leading-relaxed">{children}</div>
    </div>
  )
}

export function EmptyState({ icon: Icon, title, description, className = '' }) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 px-6 py-10 text-center ${className}`}
    >
      {Icon ? <Icon size={26} className="text-slate-600" /> : null}
      <p className="text-sm font-medium text-slate-400">{title}</p>
      {description ? <p className="max-w-sm text-xs text-slate-600">{description}</p> : null}
    </div>
  )
}

export function Stat({ label, value, hint, tone = 'default', icon: Icon }) {
  const toneClass =
    tone === 'positive'
      ? 'text-emerald-400'
      : tone === 'negative'
        ? 'text-rose-400'
        : tone === 'warning'
          ? 'text-amber-300'
          : 'text-slate-50'
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5">
        {Icon ? <Icon size={12} className="text-slate-600" /> : null}
        <p className="stat-label truncate">{label}</p>
      </div>
      <p className={`stat-value ${toneClass}`}>{value}</p>
      {hint ? <p className="mt-0.5 truncate text-[11px] text-slate-600">{hint}</p> : null}
    </div>
  )
}

export function ProgressBar({ value, className = '', tone = 'emerald' }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0))
  const toneClass =
    tone === 'rose'
      ? 'bg-rose-400'
      : tone === 'amber'
        ? 'bg-amber-400'
        : tone === 'sky'
          ? 'bg-sky-400'
          : 'bg-emerald-400'
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-white/10 ${className}`}>
      <div
        className={`h-full rounded-full ${toneClass} transition-[width] duration-500`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function LoadingBlock({ label = 'Carregando…', className = '' }) {
  return (
    <div className={`flex items-center justify-center gap-3 py-12 text-sm text-slate-500 ${className}`}>
      <Spinner />
      {label}
    </div>
  )
}

export function ToggleSwitch({
  checked,
  onChange,
  disabled = false,
  size = 'sm',
  label = 'Alternar',
}) {
  const large = size === 'lg'
  const track = large ? 'h-8 w-14' : 'h-5 w-9'
  const thumb = large ? 'h-6 w-6' : 'h-3.5 w-3.5'
  const shift = large ? 'translate-x-6' : 'translate-x-4'

  return (
    <button
      type="button"
      role="switch"
      aria-checked={Boolean(checked)}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex shrink-0 items-center rounded-full border transition-colors ${track} ${
        checked
          ? 'border-emerald-400/40 bg-emerald-500/80'
          : 'border-white/10 bg-slate-700/80'
      } ${
        disabled
          ? 'cursor-not-allowed opacity-40'
          : 'cursor-pointer hover:border-white/25 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/50'
      }`}
    >
      <span
        className={`inline-block transform rounded-full bg-white shadow transition-transform ${thumb} ${
          checked ? shift : 'translate-x-1'
        }`}
      />
    </button>
  )
}
