"""
Sistema de simulação do trading bot.

Executa simulações em dois modos:
- RESEARCH: Modo agressivo para teste de estratégias
- PAPER_TRADING: Modo conservador com controle de risco

IMPORTANTE: Este módulo corrige o problema de relatórios gigantes.
Ao invés de salvar todos os trades detalhados, salva apenas estatísticas
agregadas. Para análise detalhada, trades são salvos em SQLite separado.
"""
import random
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple
import logging

import config
from equity import EquityManager
from logging_config import setup_logging

# Configurar logging
logger = setup_logging("simulator", config.LOG_LEVEL)


class SimulationMode(Enum):
    """Modos de simulação disponíveis."""
    RESEARCH = 'research'
    PAPER_TRADING = 'paper_trading'


class PositionManager:
    """
    Gerenciador de posições para simulação.
    
    Versão simplificada focada em simulações rápidas.
    
    Attributes:
        equity_manager: Gerenciador de equity
        mode: Modo de simulação
        positions: Lista de posições abertas
        trades: Lista de trades executados
        max_positions: Máximo de posições simultâneas
        max_age: Idade máxima de posição (ticks)
        aggressiveness_level: Nível de agressividade
    """
    
    def __init__(
        self,
        equity_manager: EquityManager,
        mode: SimulationMode = SimulationMode.RESEARCH
    ):
        """
        Inicializa position manager para simulação.
        
        Args:
            equity_manager: Gerenciador de equity
            mode: Modo de simulação
        """
        self.equity_manager = equity_manager
        self.mode = mode
        self.positions: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
        
        # Configurações por modo
        if mode == SimulationMode.PAPER_TRADING:
            self.max_positions = 1
            self.max_age = 15
            self.aggressiveness_level = "REDUCED"
        else:
            self.max_positions = 5
            self.max_age = 100
            self.aggressiveness_level = "NORMAL"
        
        logger.debug(
            f"PositionManager criado em modo {mode.value}: "
            f"max_pos={self.max_positions}, max_age={self.max_age}"
        )
    
    def _position_size_pct(self) -> float:
        """
        Retorna % do equity a usar por posição.
        
        Returns:
            Percentual de posição (0.0 a 1.0)
        """
        if self.aggressiveness_level == "PROTECT":
            return 0.02  # 2%
        if self.aggressiveness_level == "REDUCED":
            return 0.05  # 5%
        return 0.10  # 10%
    
    def open_position(
        self,
        price: float,
        direction: str,
        tick: int
    ) -> bool:
        """
        Abre nova posição se houver espaço.
        
        Args:
            price: Preço de entrada
            direction: Direção ('long' ou 'short')
            tick: Tick atual
            
        Returns:
            True se posição foi aberta
        """
        if len(self.positions) >= self.max_positions:
            return False
        
        # Calcular tamanho da posição
        size = self.equity_manager.current_equity * self._position_size_pct()
        
        # Calcular stops (3% de distância)
        if direction == 'long':
            stop_loss = price * 0.97
            take_profit = price * 1.03
        else:
            stop_loss = price * 1.03
            take_profit = price * 0.97
        
        position = {
            'entry_price': price,
            'direction': direction,
            'size': size,
            'entry_tick': tick,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'age': 0
        }
        
        self.positions.append(position)
        logger.debug(
            f"Posição aberta: {direction} @ {price:.2f}, size={size:.2f}"
        )
        return True
    
    def close_position(
        self,
        position: Dict[str, Any],
        exit_price: float,
        tick: int,
        reason: str
    ) -> Dict[str, Any]:
        """
        Fecha posição e calcula resultado.
        
        Args:
            position: Dicionário da posição
            exit_price: Preço de saída
            tick: Tick atual
            reason: Razão do fechamento
            
        Returns:
            Dicionário com resultado do trade
        """
        # Calcular PnL
        if position['direction'] == 'long':
            pnl_amount = (
                (exit_price - position['entry_price']) *
                position['size'] / position['entry_price']
            )
        else:
            pnl_amount = (
                (position['entry_price'] - exit_price) *
                position['size'] / position['entry_price']
            )
        
        pnl_pct = pnl_amount / position['size'] if position['size'] else 0.0
        
        trade = {
            'entry_tick': position['entry_tick'],
            'exit_tick': tick,
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'direction': position['direction'],
            'size': position['size'],
            'pnl_amount': pnl_amount,
            'pnl_pct': pnl_pct,
            'duration': tick - position['entry_tick'],
            'exit_reason': reason
        }
        
        self.trades.append(trade)
        self.equity_manager.update_equity(pnl_amount)
        
        logger.debug(
            f"Posição fechada: {position['direction']} "
            f"PnL={pnl_amount:+.2f} ({reason})"
        )
        
        return trade
    
    def evaluate(self, current_price: float, tick: int) -> None:
        """
        Avalia posições abertas e fecha se necessário.
        
        Verifica:
        - Stop-loss
        - Take-profit
        - Idade máxima
        
        Args:
            current_price: Preço atual
            tick: Tick atual
        """
        closes = []
        
        for index, position in enumerate(self.positions):
            position['age'] = tick - position['entry_tick']
            direction = position['direction']
            
            # Verificar stop-loss
            stop_loss_hit = (
                (direction == 'long' and current_price <= position['stop_loss']) or
                (direction == 'short' and current_price >= position['stop_loss'])
            )
            
            # Verificar take-profit
            take_profit_hit = (
                (direction == 'long' and current_price >= position['take_profit']) or
                (direction == 'short' and current_price <= position['take_profit'])
            )
            
            # Verificar idade máxima
            max_age_hit = position['age'] >= self.max_age
            
            # Determinar razão de saída
            if stop_loss_hit:
                closes.append((index, 'STOP_LOSS'))
            elif take_profit_hit:
                closes.append((index, 'TAKE_PROFIT'))
            elif max_age_hit:
                closes.append((index, 'TIME_EXIT'))
        
        # Fechar posições (do final para o início para não invalidar índices)
        for index, reason in reversed(closes):
            position = self.positions.pop(index)
            self.close_position(position, current_price, tick, reason)
    
    def get_trade_statistics(self) -> Dict[str, Any]:
        """
        Calcula estatísticas agregadas dos trades.
        
        IMPORTANTE: Retorna apenas estatísticas, não a lista completa
        de trades (para evitar relatórios gigantes).
        
        Returns:
            Dicionário com estatísticas dos trades
        """
        if not self.trades:
            return {
                'total_trades': 0,
                'win_trades': 0,
                'loss_trades': 0,
                'win_rate': 0.0,
                'avg_pnl_amount': 0.0,
                'avg_pnl_pct': 0.0,
                'max_win': 0.0,
                'max_loss': 0.0,
                'avg_duration': 0.0,
                'best_trade': None,
                'worst_trade': None,
            }
        
        total = len(self.trades)
        wins = [t for t in self.trades if t['pnl_pct'] > 0]
        losses = [t for t in self.trades if t['pnl_pct'] <= 0]
        
        return {
            'total_trades': total,
            'win_trades': len(wins),
            'loss_trades': len(losses),
            'win_rate': len(wins) / total if total else 0.0,
            'avg_pnl_amount': sum(t['pnl_amount'] for t in self.trades) / total,
            'avg_pnl_pct': sum(t['pnl_pct'] for t in self.trades) / total,
            'max_win': max((t['pnl_amount'] for t in wins), default=0.0),
            'max_loss': min((t['pnl_amount'] for t in losses), default=0.0),
            'avg_duration': sum(t['duration'] for t in self.trades) / total,
            'best_trade': max(self.trades, key=lambda t: t['pnl_amount']),
            'worst_trade': min(self.trades, key=lambda t: t['pnl_amount']),
        }


class MarketSimulator:
    """
    Simulador de mercado com diferentes regimes.
    
    Gera preços sintéticos com mudanças de regime aleatórias.
    """
    
    def __init__(self, initial_price: float = 100000.0):
        """
        Inicializa simulador de mercado.
        
        Args:
            initial_price: Preço inicial
        """
        self.regimes = ['UPTREND', 'DOWNTREND', 'RANGE', 'CHAOS']
        self.current_regime = random.choice(self.regimes)
        self.regime_change_prob = 0.02  # 2% de chance por tick
        self.price = initial_price
        
        logger.debug(
            f"MarketSimulator criado: price={initial_price:.2f}, "
            f"regime={self.current_regime}"
        )
    
    def get_regime_params(self, regime: str) -> Dict[str, float]:
        """
        Retorna parâmetros de drift e volatilidade por regime.
        
        Args:
            regime: Nome do regime
            
        Returns:
            Dict com 'drift' e 'volatility'
        """
        return {
            'UPTREND': {'drift': 0.0002, 'volatility': 0.010},
            'DOWNTREND': {'drift': -0.0002, 'volatility': 0.010},
            'RANGE': {'drift': 0.0, 'volatility': 0.005},
            'CHAOS': {'drift': 0.0, 'volatility': 0.020}
        }[regime]
    
    def generate_price(self) -> Tuple[float, str]:
        """
        Gera próximo preço com possível mudança de regime.
        
        Returns:
            Tupla (preço, regime)
        """
        # Mudança de regime aleatória
        if random.random() < self.regime_change_prob:
            old_regime = self.current_regime
            self.current_regime = random.choice(self.regimes)
            logger.debug(f"Mudança de regime: {old_regime} → {self.current_regime}")
        
        # Gerar movimento de preço
        params = self.get_regime_params(self.current_regime)
        shock = random.gauss(0, 1)
        self.price *= (1 + params['drift'] + params['volatility'] * shock)
        
        return self.price, self.current_regime


def mock_strategy_signal(regime: str) -> Optional[str]:
    """
    Estratégia mock que gera sinais baseados em regime.
    
    Args:
        regime: Regime atual de mercado
        
    Returns:
        'long', 'short', ou None
    """
    if regime == 'UPTREND':
        return 'long' if random.random() < 0.6 else None
    
    if regime == 'DOWNTREND':
        return 'short' if random.random() < 0.6 else None
    
    if regime == 'RANGE':
        rand = random.random()
        if rand < 0.35:
            return 'long'
        elif rand < 0.70:
            return 'short'
        return None
    
    # CHAOS
    rand = random.random()
    if rand < 0.3:
        return 'long'
    elif rand < 0.6:
        return 'short'
    return None


def run_simulation(
    mode: SimulationMode,
    ticks: int = 10000,
    initial_capital: float = config.INITIAL_CAPITAL
) -> Dict[str, Any]:
    """
    Executa simulação completa.
    
    Args:
        mode: Modo de simulação
        ticks: Número de ticks a simular
        initial_capital: Capital inicial
        
    Returns:
        Dicionário com resultados da simulação
    """
    is_paper = mode == SimulationMode.PAPER_TRADING
    logger.info(f"Iniciando simulação em modo {mode.value} ({ticks} ticks)")
    
    # Inicializar componentes
    equity_mgr = EquityManager(initial_capital=initial_capital)
    position_mgr = PositionManager(equity_mgr, mode)
    market_sim = MarketSimulator()
    
    # Loop de simulação
    for tick in range(ticks):
        price, regime = market_sim.generate_price()
        
        # Em paper trading, parar se drawdown > 25%
        if is_paper and equity_mgr.get_max_equity_drawdown() > 0.25:
            position_mgr.evaluate(price, tick)
            continue
        
        # Gerar sinal de estratégia
        signal = mock_strategy_signal(regime)
        
        # Abrir posição se houver sinal
        if signal:
            position_mgr.open_position(price, signal, tick)
        
        # Avaliar posições existentes
        position_mgr.evaluate(price, tick)
        
        # Log de progresso
        if tick % 500 == 0:
            logger.info(
                f"Tick {tick:4d} | "
                f"Price: {price:,.0f} | "
                f"Equity: {equity_mgr.current_equity:,.0f} | "
                f"DD: {equity_mgr.get_max_equity_drawdown():.1%}"
            )
    
    # Calcular estatísticas finais
    trade_stats = position_mgr.get_trade_statistics()
    
    logger.info(
        f"Simulação concluída: "
        f"{trade_stats['total_trades']} trades, "
        f"win_rate={trade_stats['win_rate']:.1%}"
    )
    
    # IMPORTANTE: Retornar apenas estatísticas, NÃO a lista completa de trades
    return {
        'mode': mode.value,
        'ticks': ticks,
        'final_equity': equity_mgr.current_equity,
        'total_return': equity_mgr.get_total_return(),
        'max_drawdown': equity_mgr.get_max_equity_drawdown(),
        'trade_statistics': trade_stats,
        # ❌ NÃO incluir: 'trades_detail': position_mgr.trades
        # ✅ Se precisar dos trades, salvar em SQLite separado
    }


def save_trades_to_db(
    trades: List[Dict[str, Any]],
    db_path: Path = Path('simulation_trades.db'),
    simulation_id: Optional[str] = None
) -> None:
    """
    Salva trades detalhados em banco SQLite separado.
    
    Use esta função se precisar analisar trades individuais.
    Não inclua trades no relatório JSON!
    
    Args:
        trades: Lista de trades
        db_path: Caminho do banco
        simulation_id: ID da simulação (opcional)
    """
    sim_id = simulation_id or datetime.now().strftime('%Y%m%d_%H%M%S')
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Criar tabela se não existir
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS simulation_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simulation_id TEXT NOT NULL,
            entry_tick INTEGER,
            exit_tick INTEGER,
            entry_price REAL,
            exit_price REAL,
            direction TEXT,
            size REAL,
            pnl_amount REAL,
            pnl_pct REAL,
            duration INTEGER,
            exit_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Inserir trades
    for trade in trades:
        cursor.execute("""
            INSERT INTO simulation_trades (
                simulation_id, entry_tick, exit_tick, entry_price, exit_price,
                direction, size, pnl_amount, pnl_pct, duration, exit_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sim_id,
            trade['entry_tick'],
            trade['exit_tick'],
            trade['entry_price'],
            trade['exit_price'],
            trade['direction'],
            trade['size'],
            trade['pnl_amount'],
            trade['pnl_pct'],
            trade['duration'],
            trade['exit_reason']
        ))
    
    conn.commit()
    conn.close()
    
    logger.info(f"Salvos {len(trades)} trades em {db_path}")


def save_simulation_report(
    research: Dict[str, Any],
    paper: Dict[str, Any]
) -> str:
    """
    Salva relatório de comparação entre modos.
    
    IMPORTANTE: Salva apenas estatísticas agregadas, não trades individuais.
    
    Args:
        research: Resultados do modo research
        paper: Resultados do modo paper trading
        
    Returns:
        Caminho do arquivo salvo
    """
    # Criar diretório
    report_dir = config.SIMULATION_REPORTS_DIR
    report_dir.mkdir(exist_ok=True)
    
    # Calcular comparação
    research_trades = research['trade_statistics']['total_trades']
    paper_trades = paper['trade_statistics']['total_trades']
    
    comparison = {
        'trade_reduction_pct': (
            (research_trades - paper_trades) / research_trades * 100
            if research_trades else 0.0
        ),
        'equity_preservation_pct': (
            paper['final_equity'] / research['final_equity'] * 100
            if research['final_equity'] else 0.0
        ),
        'risk_control_passed': paper['max_drawdown'] < 0.25
    }
    
    # Montar relatório
    report = {
        'timestamp': datetime.now().isoformat(),
        'research': research,
        'paper_trading': paper,
        'comparison': comparison
    }
    
    # Salvar
    report_path = report_dir / f"dual_mode_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # Verificar tamanho
    size_mb = report_path.stat().st_size / (1024 * 1024)
    
    if size_mb > config.MAX_REPORT_SIZE_MB:
        logger.warning(
            f"Relatório grande: {size_mb:.2f} MB > {config.MAX_REPORT_SIZE_MB} MB"
        )
    else:
        logger.info(f"Relatório salvo: {report_path} ({size_mb:.2f} MB)")
    
    return str(report_path)


if __name__ == '__main__':
    logger.info("🚀 Iniciando simulação dual-mode...")
    
    # Executar simulações
    research_results = run_simulation(SimulationMode.RESEARCH)
    paper_results = run_simulation(SimulationMode.PAPER_TRADING)
    
    # Resumo no console
    print('\n' + '='*60)
    print('RESUMO DA SIMULAÇÃO')
    print('='*60)
    
    print(f"\n📊 RESEARCH MODE:")
    print(f"  • Trades: {research_results['trade_statistics']['total_trades']}")
    print(f"  • Win Rate: {research_results['trade_statistics']['win_rate']:.1%}")
    print(f"  • Max DD: {research_results['max_drawdown']:.1%}")
    print(f"  • Return: {research_results['total_return']:.1%}")
    
    print(f"\n📊 PAPER TRADING MODE:")
    print(f"  • Trades: {paper_results['trade_statistics']['total_trades']}")
    print(f"  • Win Rate: {paper_results['trade_statistics']['win_rate']:.1%}")
    print(f"  • Max DD: {paper_results['max_drawdown']:.1%}")
    print(f"  • Return: {paper_results['total_return']:.1%}")
    
    research_trades = research_results['trade_statistics']['total_trades']
    paper_trades = paper_results['trade_statistics']['total_trades']
    
    if research_trades > 0:
        reduction = (research_trades - paper_trades) / research_trades * 100
        print(f"\n📉 Trade Reduction: {reduction:.1f}%")
    
    print('='*60 + '\n')
    
    # Salvar relatório
    report_path = save_simulation_report(research_results, paper_results)
    print(f'✅ Relatório salvo: {report_path}\n')
