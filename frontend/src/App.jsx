import { useEffect, useState } from 'react'
import {
  Activity,
  BrainCircuit,
  FlaskConical,
  LayoutDashboard,
  SlidersHorizontal,
} from 'lucide-react'
import { api } from './api.js'
import { StatusDot } from './components/ui.jsx'
import ControlRoom from './tabs/ControlRoom.jsx'
import SimulationLab from './tabs/SimulationLab.jsx'
import Calibration from './tabs/Calibration.jsx'
import MlConsole from './tabs/MlConsole.jsx'

const TABS = [
  {
    id: 'control',
    label: 'Sala de Controle',
    short: 'Controle',
    icon: LayoutDashboard,
    component: ControlRoom,
  },
  {
    id: 'simulation',
    label: 'Laboratório de Simulação',
    short: 'Simulação',
    icon: FlaskConical,
    component: SimulationLab,
  },
  {
    id: 'calibration',
    label: 'Calibragem Visual',
    short: 'Calibragem',
    icon: SlidersHorizontal,
    component: Calibration,
  },
  {
    id: 'ml',
    label: 'ML & Console',
    short: 'ML & Logs',
    icon: BrainCircuit,
    component: MlConsole,
  },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('control')
  const [status, setStatus] = useState(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let mounted = true

    async function loadStatus() {
      try {
        const data = await api.status()
        if (mounted) {
          setStatus(data)
          setOffline(false)
        }
      } catch {
        if (mounted) setOffline(true)
      }
    }

    loadStatus()
    const timer = setInterval(loadStatus, 12000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  }, [])

  const running = Boolean(status?.monitor_running) && !status?.monitor_paused
  const ActiveComponent = TABS.find((tab) => tab.id === activeTab)?.component

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-white/[0.07] bg-[#070b12]/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-3 px-4 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl border border-emerald-400/25 bg-emerald-400/10 text-emerald-300 shadow-[0_0_40px_-12px_rgba(16,185,129,0.8)]">
                <Activity size={20} />
              </span>
              <div>
                <p className="text-sm font-semibold tracking-tight text-slate-100">
                  Trading Requiem
                </p>
                <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  Painel de Controle
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 lg:hidden">
              <StatusDot active={!offline && running} />
              <span className="text-[11px] font-semibold text-slate-300">
                {offline ? 'API offline' : running ? 'Ativo' : 'Pausado'}
              </span>
            </div>
          </div>

          <nav className="flex items-center gap-1 overflow-x-auto rounded-xl border border-white/[0.07] bg-white/[0.02] p-1">
            {TABS.map((tab) => {
              const Icon = tab.icon
              const active = tab.id === activeTab
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition ${
                    active
                      ? 'bg-white/[0.09] text-white shadow-sm'
                      : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                  }`}
                >
                  <Icon size={15} className={active ? 'text-emerald-300' : ''} />
                  <span className="hidden sm:inline">{tab.label}</span>
                  <span className="sm:hidden">{tab.short}</span>
                </button>
              )
            })}
          </nav>

          <div className="hidden items-center gap-3 lg:flex">
            <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5">
              <StatusDot active={!offline && running} />
              <span className="text-[11px] font-semibold text-slate-300">
                {offline ? 'API offline' : running ? 'Motor ativo' : 'Motor pausado'}
              </span>
            </div>
            {status?.ml ? (
              <div className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11px] font-medium text-slate-400">
                ML:{' '}
                <span className={status.ml.trained ? 'text-emerald-300' : 'text-amber-300'}>
                  {status.ml.trained ? 'modelo' : 'heurística'}
                </span>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6 sm:py-7">
        {ActiveComponent ? <ActiveComponent key={activeTab} /> : null}
      </main>

      <footer className="mx-auto max-w-[1500px] px-4 pb-8 pt-2 text-center text-[11px] text-slate-600 sm:px-6">
        Motor Python preservado · Configuração aplicada em tempo real · Dados
        locais
      </footer>
    </div>
  )
}
