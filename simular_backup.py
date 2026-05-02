import json
import math
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from enum import Enum
from position_manager import simple_position_manager, advanced_position_manager, Position
from market_regime import REGIMES_OCULTOS, analisar_tendencia_simulacao

# Importar funções do sistema real
from monitor import salvar_no_db, iniciar_db, kpi_tracker
from market_regime import analyze_regime
from strategy_unified import StrategyOrchestrator
from kpis import KPITracker

DB_PATH = "historico.db"
REPORTS_DIR = Path('simulation_reports')
MOEDA = "BTC"

class SimulationMode(Enum):
    """Modos de simulação disponíveis."""
    RESEARCH = "research"  # Sem risco, sem filtros - foco em entender comportamento
    PAPER_TRADING = "paper_trading"  # Com risco completo - foco em sobrevivência

# Inicializar orchestrator para simulação
orchestrator = StrategyOrchestrator()

class EquityManager:
    """Gerenciador de equity da estratégia."""
    def __init__(self, initial_capital=100000.0):
        self.initial_capital = initial_capital
        self.current_equity = initial_capital
        self.peak_equity = initial_capital
        self.equity_history = [initial_capital]  # Por tick
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0

    def update_equity(self, pnl_amount):
        """Atualiza equity com PnL de um trade."""
        self.current_equity += pnl_amount
        self.equity_history.append(self.current_equity)

        # Atualizar peak equity
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

        # Calcular drawdown atual
        if self.peak_equity > 0:
            self.current_drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, self.current_drawdown)

    def get_equity_drawdown(self):
        """Retorna drawdown baseado em equity."""
        return self.current_drawdown

    def get_max_equity_drawdown(self):
        """Retorna máximo drawdown de equity."""
        return self.max_drawdown

    def get_equity_curve(self):
        """Retorna histórico completo de equity."""
        return self.equity_history.copy()

# Mapeamento entre regimes ocultos e regimes detectados pelo sistema
REGIME_MAPPING = {
    "UPTREND": ["TENDENCIA_ALTA"],
    "DOWNTREND": ["TENDENCIA_BAIXA"],
    "RANGE": ["CONSOLIDACAO", "TRANSICAO"],
    "CHAOS": ["ALTA_VOLATILIDADE"],
}

class BaseSimulationEngine:
    """Classe base para engines de simulação."""
    def __init__(self, mode: SimulationMode, initial_price=50000.0, seed=None):
        self.mode = mode
        self.simulator = MarketSimulator(initial_price=initial_price, seed=seed)
        self.equity_mgr = EquityManager()
        self.position_mgr = None
        self.risk_controller = None
        self.ml_classifier = None
        self.exhaustion_filter = None

    def initialize_components(self):
        """Inicializa componentes baseado no modo."""
        if self.mode == SimulationMode.RESEARCH:
            # Research Mode: sem filtros de risco
            self.position_mgr = SimplePositionManager()
        elif self.mode == SimulationMode.PAPER_TRADING:
            # Paper Trading Mode: sistema completo
            from risk_control import RiskController
            from ml_classifier import MLClassifier
            from exhaustion_filter import ExhaustionFilter

            self.position_mgr = AdvancedPositionManager(self.equity_mgr)
            self.risk_controller = RiskController()
            self.ml_classifier = MLClassifier()
            self.exhaustion_filter = ExhaustionFilter()

    def analyze_market(self, price):
        """Análise de mercado - implementada pelas subclasses."""
        raise NotImplementedError

    def should_trade(self, analysis_result):
        """Decide se deve fazer trade baseado no modo."""
        if self.mode == SimulationMode.RESEARCH:
            # Research: sempre permite trade se houver sinal
            return analysis_result["acao"] in ["COMPRA", "VENDA"]
        elif self.mode == SimulationMode.PAPER_TRADING:
            # Paper Trading: passa por todos os filtros
            if not self.risk_controller.can_trade():
                return False
            if not self.exhaustion_filter.is_safe_to_trade():
                return False
            if not self.ml_classifier.approve_trade(analysis_result):
                return False
            return analysis_result["acao"] in ["COMPRA", "VENDA"]
        return False

    def execute_trade_cycle(self, price, tick_num):
        """Executa um ciclo completo de trading."""
        # Análise de mercado
        analysis = self.analyze_market(price)

        # Decidir se deve fazer trade
        if self.should_trade(analysis):
            # Executar position management
            position_action = self.position_mgr.evaluate(analysis["acao"], price, tick_num)

            # Se fechou posição, atualizar equity
            if position_action.startswith("CLOSE_"):
                last_trade = self.position_mgr.trades[-1]
                pnl_amount = last_trade['pnl'] * self.equity_mgr.current_equity  # PnL em valor absoluto
                self.equity_mgr.update_equity(pnl_amount)

                # Atualizar risk controller com equity drawdown
                if self.risk_controller:
                    self.risk_controller.update_drawdown(self.equity_mgr.get_equity_drawdown())
        else:
            position_action = "HOLD"

        # Registrar métricas
        self.simulator.record_metrics(
            detected_regime=analysis["regime"],
            engine=analysis.get("engine", "N/A"),
            confidence=analysis.get("confidence", 0.0),
            action=analysis.get("acao", "NEUTRO")
        )

        return analysis, position_action

class ResearchModeEngine(BaseSimulationEngine):
    """Engine para Research Mode - foco em entender comportamento bruto."""
    def __init__(self, initial_price=50000.0, seed=None):
        super().__init__(SimulationMode.RESEARCH, initial_price, seed)
        self.initialize_components()

    def analyze_market(self, price):
        """Análise simplificada sem filtros."""
        return analisar_tendencia_simulacao(MOEDA, price)

class PaperTradingModeEngine(BaseSimulationEngine):
    """Engine para Paper Trading Mode - sistema completo com risco."""
    def __init__(self, initial_price=50000.0, seed=None):
        super().__init__(SimulationMode.PAPER_TRADING, initial_price, seed)
        self.initialize_components()

    def analyze_market(self, price):
        """Análise completa usando monitor.py."""
        from monitor import analisar_tendencia
        return analisar_tendencia(MOEDA, price)

class TradeQualityGate:
    """Portão de qualidade para reduzir overtrading."""
    def __init__(self):
        self.min_confidence = 0.6  # Confiança mínima da engine
        self.min_regime_stability = 3  # Ticks mínimos no mesmo regime
        self.min_momentum_consistency = 0.02  # Momentum mínimo consistente
        self.last_regime = None
        self.regime_stability_counter = 0

    def update_regime_stability(self, current_regime):
        """Atualiza contador de estabilidade do regime."""
        if current_regime == self.last_regime:
            self.regime_stability_counter += 1
        else:
            self.regime_stability_counter = 1
            self.last_regime = current_regime

    def passes_quality_check(self, analysis_result, price_history):
        """Verifica se o trade passa pelos critérios de qualidade."""
        confidence = analysis_result.get("confidence", 0.0)

        # Critério 1: Confiança da engine
        if confidence < self.min_confidence:
            return False

        # Critério 2: Estabilidade do regime
        if self.regime_stability_counter < self.min_regime_stability:
            return False

        # Critério 3: Momentum consistente (simplificado)
        if len(price_history) >= 5:
            recent_prices = price_history[-5:]
            if analysis_result["acao"] == "COMPRA":
                # Para compra, verificar se há tendência de alta recente
                momentum = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
                if momentum < self.min_momentum_consistency:
                    return False
            elif analysis_result["acao"] == "VENDA":
                # Para venda, verificar se há tendência de baixa recente
                momentum = (recent_prices[0] - recent_prices[-1]) / recent_prices[0]
                if momentum < self.min_momentum_consistency:
                    return False

        return True

class AdvancedPositionManager:
    """Gerenciador de posições avançado com equity-based sizing."""
    def __init__(self, equity_manager, position_size_pct=0.02):  # 2% por trade
        self.equity_mgr = equity_manager
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = 0.015  # Reduzido para 1.5%
        self.take_profit_pct = 0.04  # Reduzido para 4%
        self.max_age_ticks = 15  # Reduzido para 15 ticks
        self.position = None
        self.trades = []
        self.quality_gate = TradeQualityGate()
        self.price_history = []

    def evaluate(self, action, price, current_tick, regime=None):
        """Avalia se deve abrir/fechar posição com quality gate."""
        self.price_history.append(price)
        if len(self.price_history) > 50:  # Manter histórico limitado
            self.price_history.pop(0)

        # Atualizar estabilidade do regime
        if regime:
            self.quality_gate.update_regime_stability(regime)

        if self.position is None:
            # Não há posição - verificar se pode abrir
            if action in ("COMPRA", "VENDA"):
                # Verificar quality gate
                analysis_result = {"acao": action, "confidence": 0.7, "regime": regime}
                if not self.quality_gate.passes_quality_check(analysis_result, self.price_history):
                    return "QUALITY_REJECT"

                # Calcular position size baseado em equity
                position_value = self.equity_mgr.current_equity * self.position_size_pct
                position_size = position_value / price

                self.position = {
                    'side': action,
                    'price': price,
                    'tick': current_tick,
                    'age': 0,
                    'size': position_size,
                    'value': position_value,
                    'regime_at_entry': regime
                }
                return f"OPEN_{action}"
        else:
            # Há posição - verifica se deve fechar
            self.position['age'] += 1
            side = self.position['side']
            entry_price = self.position['price']

            # Calcular stop loss e take profit
            if side == "COMPRA":
                stop_loss = entry_price * (1 - self.stop_loss_pct)
                take_profit = entry_price * (1 + self.take_profit_pct)
                if price <= stop_loss:
                    reason = "STOP_LOSS"
                elif price >= take_profit:
                    reason = "TAKE_PROFIT"
                elif self.position['age'] >= self.max_age_ticks:
                    reason = "MAX_AGE"
                else:
                    return "HOLD"
            else:  # VENDA
                stop_loss = entry_price * (1 + self.stop_loss_pct)
                take_profit = entry_price * (1 - self.take_profit_pct)
                if price >= stop_loss:
                    reason = "STOP_LOSS"
                elif price <= take_profit:
                    reason = "TAKE_PROFIT"
                elif self.position['age'] >= self.max_age_ticks:
                    reason = "MAX_AGE"
                else:
                    return "HOLD"

            # Fechar posição
            pnl_pct = 0.0
            if side == "COMPRA":
                pnl_pct = (price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - price) / entry_price

            pnl_amount = pnl_pct * self.position['value']

            trade = {
                'symbol': 'BTC',
                'side': side,
                'entry_price': entry_price,
                'exit_price': price,
                'entry_tick': self.position['tick'],
                'exit_tick': current_tick,
                'pnl_pct': float(pnl_pct),
                'pnl_amount': float(pnl_amount),
                'duration_ticks': self.position['age'],
                'reason': reason,
                'position_size': self.position['size'],
                'regime_at_entry': self.position.get('regime_at_entry', 'UNKNOWN')
            }
            self.trades.append(trade)
            self.position = None
            return f"CLOSE_{reason}"

        return "NEUTRO"
            side = self.position['side']
            entry_price = self.position['price']

            # Calcular stop loss e take profit
            if side == "COMPRA":
                stop_loss = entry_price * (1 - self.stop_loss_pct)
                take_profit = entry_price * (1 + self.take_profit_pct)
                if price <= stop_loss:
                    reason = "STOP_LOSS"
                elif price >= take_profit:
                    reason = "TAKE_PROFIT"
                elif self.position['age'] >= self.max_age_ticks:
                    reason = "MAX_AGE"
                else:
                    return "HOLD"
            else:  # VENDA
                stop_loss = entry_price * (1 + self.stop_loss_pct)
                take_profit = entry_price * (1 - self.take_profit_pct)
                if price >= stop_loss:
                    reason = "STOP_LOSS"
                elif price <= take_profit:
                    reason = "TAKE_PROFIT"
                elif self.position['age'] >= self.max_age_ticks:
                    reason = "MAX_AGE"
                else:
                    return "HOLD"

            # Fechar posição
            pnl = 0.0
            if side == "COMPRA":
                pnl = (price - entry_price) / entry_price
            else:
                pnl = (entry_price - price) / entry_price

            trade = {
                'symbol': 'BTC',
                'side': side,
                'entry_price': entry_price,
                'exit_price': price,
                'entry_tick': self.position['tick'],
                'exit_tick': current_tick,
                'pnl': float(pnl),
                'duration_ticks': self.position['age'],
                'reason': reason
            }
            self.trades.append(trade)
            self.position = None
            return f"CLOSE_{reason}"

        return "NEUTRO"

class MarketSimulator:
    def __init__(self, initial_price=50000.0, seed=None):
        self.price = initial_price
        self.volatility = 0.01  # volatilidade atual
        self.hidden_regime = "RANGE"  # regime interno inicial
        self.tick_count = 0
        self.start_time = time.time()

        # Métricas de validação
        self.regime_accuracy = defaultdict(int)
        self.regime_total = defaultdict(int)
        self.engine_expectancy = defaultdict(list)
        self.drawdowns = []
        self.max_drawdown = 0.0
        self.peak_price = initial_price

        if seed:
            random.seed(seed)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def _update_hidden_regime(self):
        """Atualiza regime oculto probabilisticamente."""
        if random.random() < REGIMES_OCULTOS[self.hidden_regime]["prob_change"]:
            new_regime = random.choice(list(REGIMES_OCULTOS.keys()))
            self.hidden_regime = new_regime
            print(f"🔄 Regime oculto mudou para: {self.hidden_regime}")

    def _generate_volatility_shock(self):
        """Gera choques de volatilidade ocasionais."""
        if random.random() < 0.005:  # 0.5% chance por tick
            shock_factor = random.uniform(1.5, 3.0)
            self.volatility *= shock_factor
            print(f"⚡ Choque de volatilidade: {self.volatility:.4f}")
            # Volatilidade volta gradualmente
            self.volatility = max(self.volatility * 0.98, 0.005)

    def _generate_price_jump(self):
        """Gera saltos de preço ocasionais (gaps)."""
        if random.random() < 0.001:  # 0.1% chance
            jump_pct = random.uniform(-0.05, 0.05)  # -5% a +5%
            self.price *= (1 + jump_pct)
            print(f"💥 Gap de preço: {jump_pct:.2%}")

    def generate_next_price(self):
        """Gera próximo preço usando GBM."""
        self._update_hidden_regime()
        self._generate_volatility_shock()
        self._generate_price_jump()

        regime_params = REGIMES_OCULTOS[self.hidden_regime]
        drift = regime_params["drift"]
        vol_base = regime_params["vol_base"]

        # Ajustar volatilidade atual baseada no regime
        target_vol = vol_base + random.gauss(0, 0.002)  # variação pequena
        self.volatility = 0.9 * self.volatility + 0.1 * target_vol  # suavização

        # GBM: preço(t+1) = preço(t) * exp(drift + vol * ruido)
        ruido = random.gauss(0, 1)
        growth_factor = math.exp(drift + self.volatility * ruido)
        self.price *= growth_factor

        # Evitar preços negativos ou extremos
        self.price = max(self.price, 1000.0)

        return self.price

    def record_metrics(self, detected_regime, engine, confidence, action):
        """Registra métricas para validação posterior."""
        # Acurácia de regime
        self.regime_total[self.hidden_regime] += 1
        expected_regimes = REGIME_MAPPING.get(self.hidden_regime, [])
        if detected_regime in expected_regimes:
            self.regime_accuracy[self.hidden_regime] += 1

        # Expectancy por engine
        if action in ["COMPRA", "VENDA"]:
            self.engine_expectancy[engine].append(confidence)

        # REMOVIDO: Drawdown baseado em preço - agora feito pelo EquityManager

    def generate_report(self, equity_manager=None, position_manager=None, mode=SimulationMode.RESEARCH):
        """Gera relatório final da simulação."""
        accuracy_by_regime = {}
        for regime in REGIMES_OCULTOS:
            total = self.regime_total.get(regime, 0)
            correct = self.regime_accuracy.get(regime, 0)
            accuracy_by_regime[regime] = correct / total if total > 0 else 0.0

        expectancy_by_engine = {}
        for engine, confidences in self.engine_expectancy.items():
            expectancy_by_engine[engine] = sum(confidences) / len(confidences) if confidences else 0.0

        report = {
            "simulation_mode": mode.value,
            "simulation_duration_ticks": self.tick_count,
            "final_price": self.price,
            "regime_accuracy": accuracy_by_regime,
            "engine_expectancy": expectancy_by_engine,
            "generated_at": datetime.now().isoformat(),
        }

        # Adicionar métricas de equity se disponível
        if equity_manager:
            report["equity_metrics"] = {
                "initial_capital": equity_manager.initial_capital,
                "final_equity": equity_manager.current_equity,
                "peak_equity": equity_manager.peak_equity,
                "max_equity_drawdown": equity_manager.get_max_equity_drawdown(),
                "total_return": (equity_manager.current_equity - equity_manager.initial_capital) / equity_manager.initial_capital,
                "equity_curve_length": len(equity_manager.equity_history)
            }

        # Adicionar métricas de trading se disponível
        if position_manager and hasattr(position_manager, 'trades') and position_manager.trades:
            trades = position_manager.trades

            # Métricas gerais
            win_trades = [t for t in trades if t['pnl_pct'] > 0]
            loss_trades = [t for t in trades if t['pnl_pct'] <= 0]

            report["trading_metrics"] = {
                "total_trades": len(trades),
                "win_trades": len(win_trades),
                "loss_trades": len(loss_trades),
                "win_rate": len(win_trades) / len(trades) if trades else 0.0,
                "avg_win": sum(t['pnl_pct'] for t in win_trades) / len(win_trades) if win_trades else 0.0,
                "avg_loss": sum(t['pnl_pct'] for t in loss_trades) / len(loss_trades) if loss_trades else 0.0,
                "profit_factor": abs(sum(t['pnl_pct'] for t in win_trades) / sum(t['pnl_pct'] for t in loss_trades)) if loss_trades and sum(t['pnl_pct'] for t in loss_trades) != 0 else float('inf'),
                "avg_trade_duration": sum(t['duration_ticks'] for t in trades) / len(trades),
                "total_pnl_pct": sum(t['pnl_pct'] for t in trades),
            }

            # Métricas por regime
            regime_metrics = {}
            for regime in set(t.get('regime_at_entry', 'UNKNOWN') for t in trades):
                regime_trades = [t for t in trades if t.get('regime_at_entry') == regime]
                if regime_trades:
                    regime_win_rate = sum(1 for t in regime_trades if t['pnl_pct'] > 0) / len(regime_trades)
                    regime_avg_pnl = sum(t['pnl_pct'] for t in regime_trades) / len(regime_trades)
                    regime_metrics[regime] = {
                        "trades": len(regime_trades),
                        "win_rate": regime_win_rate,
                        "avg_pnl": regime_avg_pnl
                    }
            report["regime_trading_metrics"] = regime_metrics

        # Salvar relatório
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"simulation_report_{mode.value}_{timestamp}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"📊 Relatório de simulação salvo: {report_path}")
        return report


def run_research_simulation(ticks=1000, initial_price=50000.0, seed=None):
    """Executa simulação em Research Mode."""
    print("🔬 Iniciando simulação RESEARCH MODE...")
    print("🎯 Foco: Entender regimes, engines e comportamento bruto")
    print("🚫 Sem: RiskController, ML, filtros de exaustão")
    print(f"💰 Preço inicial: R$ {initial_price:,.2f}")
    print(f"⏱️ Ticks totais: {ticks}")

    iniciar_db()
    engine = ResearchModeEngine(initial_price=initial_price, seed=seed)

    for tick_num in range(ticks):
        engine.simulator.tick_count = tick_num + 1

        # Gerar preço
        price = engine.simulator.generate_next_price()

        # Executar ciclo de trading
        analysis, position_action = engine.execute_trade_cycle(price, tick_num)

        # Salvar no banco
        horario = datetime.now().strftime("%H:%M:%S")
        salvar_no_db(
            horario=horario,
            preco=price,
            moeda=MOEDA,
            recomendacao=position_action,
            regime=analysis["regime"],
            engine=analysis.get("engine", "N/A"),
            confidence=analysis.get("confidence", 0.0),
            details=analysis.get("details", ""),
            ml_score=analysis.get("confidence", 0.0),
        )

        # Log periódico
        if tick_num % 200 == 0:
            print(f"Tick {tick_num}: BTC R$ {price:,.2f} | Regime oculto: {engine.simulator.hidden_regime} | Detectado: {analysis['regime']} | Posição: {position_action}")

    # Relatório final
    report = engine.simulator.generate_report(
        equity_manager=engine.equity_mgr,
        position_manager=engine.position_mgr,
        mode=SimulationMode.RESEARCH
    )

    print("✅ Simulação Research concluída!")
    print(f"Preço final: R$ {engine.simulator.price:,.2f}")
    print(f"Trades executados: {len(engine.position_mgr.trades)}")
    if engine.position_mgr.trades:
        wins = sum(1 for t in engine.position_mgr.trades if t['pnl_pct'] > 0)
        print(f"Win rate: {wins}/{len(engine.position_mgr.trades)} ({wins/len(engine.position_mgr.trades):.1%})")
        print(f"PnL médio: {sum(t['pnl_pct'] for t in engine.position_mgr.trades) / len(engine.position_mgr.trades):.2%}")

    return report

def run_paper_trading_simulation(ticks=1000, initial_price=50000.0, seed=None):
    """Executa simulação em Paper Trading Mode."""
    print("📈 Iniciando simulação PAPER TRADING MODE...")
    print("🎯 Foco: Sobrevivência e desempenho realista")
    print("✅ Com: RiskController, ML, filtros de exaustão, equity management")
    print(f"💰 Capital inicial: R$ 100,000.00")
    print(f"💰 Preço inicial: R$ {initial_price:,.2f}")
    print(f"⏱️ Ticks totais: {ticks}")

    iniciar_db()
    engine = PaperTradingModeEngine(initial_price=initial_price, seed=seed)

    for tick_num in range(ticks):
        engine.simulator.tick_count = tick_num + 1

        # Gerar preço
        price = engine.simulator.generate_next_price()

        # Executar ciclo de trading
        analysis, position_action = engine.execute_trade_cycle(price, tick_num, regime=analysis["regime"])

        # Tick do risk controller
        if engine.risk_controller:
            engine.risk_controller.tick()

        # Salvar no banco
        horario = datetime.now().strftime("%H:%M:%S")
        salvar_no_db(
            horario=horario,
            preco=price,
            moeda=MOEDA,
            recomendacao=position_action,
            regime=analysis["regime"],
            engine=analysis.get("engine", "N/A"),
            confidence=analysis.get("confidence", 0.0),
            details=analysis.get("details", ""),
            ml_score=analysis.get("confidence", 0.0),
        )

        # Log periódico com status de risco
        if tick_num % 200 == 0:
            risk_status = engine.risk_controller.get_risk_status() if engine.risk_controller else {}
            equity_dd = f"{engine.equity_mgr.get_equity_drawdown():.1%}" if hasattr(engine.equity_mgr, 'get_equity_drawdown') else "N/A"
            print(f"Tick {tick_num}: BTC R$ {price:,.2f} | Equity DD: {equity_dd} | Risk: {risk_status.get('aggressiveness_level', 'N/A')} | Posição: {position_action}")

    # Relatório final
    report = engine.simulator.generate_report(
        equity_manager=engine.equity_mgr,
        position_manager=engine.position_mgr,
        mode=SimulationMode.PAPER_TRADING
    )

    print("✅ Simulação Paper Trading concluída!")
    print(f"Preço final: R$ {engine.simulator.price:,.2f}")
    print(f"Equity final: R$ {engine.equity_mgr.current_equity:,.2f}")
    print(f"Max Equity DD: {engine.equity_mgr.get_max_equity_drawdown():.1%}")
    print(f"Trades executados: {len(engine.position_mgr.trades)}")
    if engine.position_mgr.trades:
        wins = sum(1 for t in engine.position_mgr.trades if t['pnl_pct'] > 0)
        print(f"Win rate: {wins}/{len(engine.position_mgr.trades)} ({wins/len(engine.position_mgr.trades):.1%})")
        print(f"PnL médio: {sum(t['pnl_pct'] for t in engine.position_mgr.trades) / len(engine.position_mgr.trades):.2%}")

    return report

def run_simulation(mode=SimulationMode.RESEARCH, ticks=1000, initial_price=50000.0, seed=None):
    """Função principal para executar simulação no modo especificado."""
    if mode == SimulationMode.RESEARCH:
        return run_research_simulation(ticks, initial_price, seed)
    elif mode == SimulationMode.PAPER_TRADING:
        return run_paper_trading_simulation(ticks, initial_price, seed)
    else:
        raise ValueError(f"Modo de simulação inválido: {mode}")

if __name__ == "__main__":
    # Exemplo de uso - Research Mode
    print("=" * 60)
    print("🔬 EXECUTANDO RESEARCH MODE (sem risco)")
    print("=" * 60)
    research_report = run_simulation(
        mode=SimulationMode.RESEARCH,
        ticks=2000,
        initial_price=50000.0,
        seed=452
    )

    print("\n" + "=" * 60)
    print("📈 EXECUTANDO PAPER TRADING MODE (com risco completo)")
    print("=" * 60)
    paper_report = run_simulation(
        mode=SimulationMode.PAPER_TRADING,
        ticks=2000,
        initial_price=50000.0,
        seed=452  # Mesmo seed para comparação
    )

    print("\n" + "=" * 60)
    print("📊 COMPARAÇÃO FINAL")
    print("=" * 60)
    print(f"Research - Trades: {research_report.get('trading_metrics', {}).get('total_trades', 0)}")
    print(f"Paper Trading - Trades: {paper_report.get('trading_metrics', {}).get('total_trades', 0)}")
    print(f"Research - Win Rate: {research_report.get('trading_metrics', {}).get('win_rate', 0):.1%}")
    print(f"Paper Trading - Win Rate: {paper_report.get('trading_metrics', {}).get('win_rate', 0):.1%}")
    print(f"Paper Trading - Max Equity DD: {paper_report.get('equity_metrics', {}).get('max_equity_drawdown', 0):.1%}")
