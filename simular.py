"""
Sistema de simulação do trading bot — Arquitetura Orientada a Estado Único.

Executa simulações usando EXATAMENTE os mesmos componentes da produção:
- Engines reais: TrendFollowing, MeanReversion, BreakoutMomentum, ProtectFlat
- Filtros reais: confirmação de tendência, exaustão, ML classifier
- PositionManager oficial (parametrizado)
- EquityManager e RiskController oficiais

Dois modos:
- RESEARCH: Modo agressivo para teste de estratégias
- PAPER_TRADING: Modo conservador com controle de risco

IMPORTANTE: Não há mock_strategy_signal. A simulação roda as mesmas engines
que o monitor usa em produção, garantindo que os resultados sejam comparáveis.

Fontes de dados:
- synthetic: Dados sintéticos estruturados com blocos de regime
- db: Dados históricos da tabela cotacoes do SQLite local
- api: Dados da AwesomeAPI com cache local
"""

import argparse
import json
import random
import sqlite3
import csv
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

import config
from database import (
    salvar_trade, save_all_state, load_all_state,
)
from equity import EquityManager
from features import FEATURE_COLUMNS, build_feature_row
from logging_config import setup_logging
from market_regime import analyze_regime
from ml_classifier import MLClassifier
from position_manager import PositionManager
from risk_control import RiskController
from strategy_unified import StrategyOrchestrator
from exhaustion_filter import check_exhaustion
from simulation_telemetry import (
    SimulationTelemetry,
    TradeRecord,
    Regime as TelemetryRegime,
    SignalSource as TelemetrySignalSource,
    create_default_raw_signals,
    create_default_filter_details,
)

# Configurar logging
logger = setup_logging("simulator", config.LOG_LEVEL)


# ============================================================================
# DATA SOURCE ENUM
# ============================================================================

class DataSource(Enum):
    """Fontes de dados disponíveis para simulação."""
    SYNTHETIC = "synthetic"
    DB = "db"
    API = "api"


# ============================================================================
# DATA LOADING UTILITIES
# ============================================================================

def load_historical_data_from_db(
    db_path: Path = config.DB_PATH,
    symbol: str = "USD",
    n_points: Optional[int] = None,
) -> pd.Series:
    """
    Carrega dados históricos reais da tabela `cotacoes` do SQLite.

    Args:
        db_path: Caminho do banco de dados SQLite
        symbol: Símbolo da moeda (ex: "USD", "BTC")
        n_points: Número de pontos a retornar (None = todos disponíveis)

    Returns:
        Série pandas de preços (índice temporal, valores decrescentes mais recentes)
    """
    conn = sqlite3.connect(db_path)
    try:
        query = f"""
            SELECT preco, horario FROM cotacoes 
            WHERE moeda = '{symbol}' 
            ORDER BY id DESC 
            LIMIT {n_points if n_points else 10000}
        """
        df = pd.read_sql_query(query, conn)

        if df.empty:
            logger.warning(f"Nenhum dado encontrado para {symbol} em cotacoes")
            return pd.Series(dtype=float)

        # Converter para Série - mais recente primeiro
        prices = pd.Series(df['preco'].values, index=df['horario'].values)

        logger.info(
            f"Carregados {len(prices)} pontos de histórico para {symbol} "
            f"da tabela cotacoes (db={db_path})"
        )
        return prices

    except Exception as e:
        logger.error(f"Erro ao carregar dados históricos do DB: {e}", exc_info=True)
        return pd.Series(dtype=float)
    finally:
        conn.close()


def download_and_cache_binance(
    symbol: str = "BTCBRL",
    interval: str = "1m",
    limit: int = 5000,
    force_download: bool = False,
) -> pd.Series:
    """
    Baixa histórico de candles da Binance API REST pública (/api/v3/klines)
    e salva em cache local para backtest offline.

    Não exige chave de API. Suporta coleta paginada para atingir a quantidade
    solicitada de candles (máximo 1000 por requisição na Binance).

    Mapeamento de pares para BRL:
        USD -> USDTBRL
        BTC -> BTCBRL
        ETH -> ETHBRL
        SOL -> SOLBRL

    Args:
        symbol: Par na Binance (ex: "BTCBRL", "USDTBRL")
        interval: Intervalo do candle ("1m", "5m", "1h", etc.)
        limit: Número total de candles desejado
        force_download: Se True, ignora cache existente e baixa novamente

    Returns:
        Série pandas de preços de fechamento (mais recente primeiro)
    """
    cache_dir = Path(config.BASE_DIR) / "data_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"{symbol}_{interval}_{limit}.csv"

    # Verificar se cache existe e não é forçado download
    if not force_download and cache_file.exists():
        logger.info(f"Usando cache existente: {cache_file}")
        try:
            df = pd.read_csv(cache_file, parse_dates=['timestamp'])
            prices = pd.Series(df['close'].values, index=df['timestamp'].values)
            logger.info(f"Carregados {len(prices)} pontos do cache")
            return prices
        except Exception as e:
            logger.warning(f"Falha ao ler cache, baixando novamente: {e}")

    # URL da Binance API REST pública
    base_url = "https://api.binance.com/api/v3/klines"

    # Mapeamento de interval para limite máximo por requisição
    # Binance permite máximo 1000 candles por requisição
    max_per_request = 1000

    try:
        import requests

        all_candles = []
        remaining = limit
        end_time = None  # None = buscar os mais recentes primeiro

        while remaining > 0:
            fetch_limit = min(remaining, max_per_request)

            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": fetch_limit,
            }
            if end_time is not None:
                params["endTime"] = end_time

            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data or not isinstance(data, list):
                logger.error(f"Dados inválidos retornados da Binance para {symbol}")
                break

            # Binance retorna [open_time, open, high, low, close, volume, ...]
            # Formato: [0]=open_time, [4]=close
            candles = [(int(c[0]), float(c[4])) for c in data]
            all_candles.extend(candles)

            if len(candles) < fetch_limit:
                # Não há mais dados disponíveis
                break

            # Para a próxima página, usar o open_time do candle mais antigo - 1ms
            end_time = candles[0][0] - 1
            remaining -= len(candles)

        if not all_candles:
            logger.error(f"Nenhum candle baixado da Binance para {symbol}")
            return pd.Series(dtype=float)

        # Remover duplicatas (pode haver sobreposição entre páginas)
        seen = set()
        unique_candles = []
        for ts, close in all_candles:
            if ts not in seen:
                seen.add(ts)
                unique_candles.append((ts, close))

        # Ordenar por timestamp (mais antigo primeiro) e depois inverter para mais recente primeiro
        unique_candles.sort(key=lambda x: x[0])
        closes = [c for _, c in unique_candles]
        timestamps = [ts for ts, _ in unique_candles]

        # Pegar apenas os 'limit' mais recentes
        if len(closes) > limit:
            closes = closes[-limit:]
            timestamps = timestamps[-limit:]

        prices = pd.Series(closes, index=timestamps)

        # Salvar em cache
        df_cache = pd.DataFrame({
            'timestamp': timestamps,
            'close': closes
        })
        df_cache.to_csv(cache_file, index=False)

        logger.info(
            f"Baixado e cacheado {len(prices)} pontos da Binance para {symbol} "
            f"em {cache_file}"
        )
        return prices

    except ImportError:
        logger.error("módulo 'requests' não disponível. Instale avec: pip install requests")
        return pd.Series(dtype=float)
    except Exception as e:
        logger.error(f"Erro ao baixar da Binance: {e}", exc_info=True)
        return pd.Series(dtype=float)


# ============================================================================
# DATA FACTORY
# ============================================================================

def get_historical_prices(
    source: DataSource = DataSource.SYNTHETIC,
    symbol: str = "USD",
    n_points: Optional[int] = None,
    **kwargs,
) -> pd.Series:
    """
    Factory function to get historical prices from the specified source.

    Args:
        source: DataSource.SYNTHETIC, DataSource.DB, ou DataSource.API
        symbol: Símbolo da moeda
        n_points: Número de pontos (None = usar todos disponíveis)
        **kwargs: Argumentos passados para a fonte específica

    Returns:
        Série pandas de preços
    """
    if source == DataSource.SYNTHETIC:
        market = SyntheticMarket(seed=kwargs.get('seed', 42))
        prices_list = []
        for _ in range(n_points if n_points else 10000):
            price, _ = market.generate_price()
            prices_list.append(price)
        # Inverter para mais recente primeiro (como o banco)
        prices_list.reverse()
        return pd.Series(prices_list)

    elif source == DataSource.DB:
        return load_historical_data_from_db(
            db_path=config.DB_PATH,
            symbol=symbol,
            n_points=n_points,
        )

    elif source == DataSource.API:
        # Mapeamento de símbolos para Binance API
        binance_symbol_map = {
            "USD": "USDTBRL",
            "BTC": "BTCBRL",
            "ETH": "ETHBRL",
            "SOL": "SOLBRL",
        }
        binance_symbol = binance_symbol_map.get(symbol.upper(), symbol.upper())
        logger.debug(f"get_historical_prices: symbol={symbol} -> binance_symbol={binance_symbol}, source=API")
        return download_and_cache_binance(
            symbol=binance_symbol,
            interval=kwargs.get('interval', '1m'),
            limit=kwargs.get('limit', n_points if n_points else 5000),
            force_download=kwargs.get('force_download', False),
        )

    else:
        logger.warning(f"Source {source} não suportado, usando synthetic")
        market = SyntheticMarket(seed=kwargs.get('seed', 42))
        prices_list = []
        for _ in range(n_points if n_points else 10000):
            price, _ = market.generate_price()
            prices_list.append(price)
        prices_list.reverse()
        return pd.Series(prices_list)


# ============================================================================
# ENHANCED SYNTHETIC MARKET
# ============================================================================

class SyntheticMarket:
    """
    Gerador de preços sintéticos com regimes estruturados e seed reproduzível.

    Gera cenários deliberadamente ricos em blocos de regime:
    - Tendência de alta sustentada
    - Tendência de baixa sustentada
    - Consolidação lateral estreita
    - Rompimentos (breakout)
    - Alta volatilidade

    Mantém suporte a seed fixo para reprodutibilidade,
    mas agora com padrões de regime intencionais que garantem
    todas as engines sejam testadas durante a simulação.
    """

    REGIME_BLOCKS = [
        # (regime, duracao_minima, drift, volatilidade, descricao)
        ("TENDENCIA_ALTA", 200, 0.0005, 0.008, "High positive drift, low vol"),
        ("TENDENCIA_BAIXA", 200, -0.0005, 0.008, "High negative drift, low vol"),
        ("CONSOLIDACAO", 150, 0.0, 0.003, "Range-bound, low vol"),
        ("ROMPE_HIGH", 30, 0.002, 0.015, "Quick high breakout"),
        ("ROMPE_LOW", 30, -0.002, 0.015, "Quick low breakout"),
        ("ALTA_VOLATILIDADE", 100, 0.0, 0.025, "High vol, no clear direction"),
        ("TRANSICAO", 50, 0.0, 0.01, "Regime change period"),
    ]

    def __init__(
        self,
        initial_price: float = 100000.0,
        seed: Optional[int] = None,
        n_ticks: int = 10000,
    ):
        self.initial_price = initial_price
        self.rng = random.Random(seed) if seed is not None else random.Random()
        self.price = initial_price
        self.n_ticks = n_ticks
        self.tick_count = 0

        # Build structured regime sequence
        self.regime_sequence = self._build_regime_sequence(n_ticks)
        self.regime_index = 0
        self.current_regime = self.regime_sequence[0][0] if self.regime_sequence else "TENDENCIA_ALTA"

        logger.debug(
            f"SyntheticMarket criado: price={initial_price:.2f}, "
            f"seed={seed}, n_ticks={n_ticks}, "
            f"first_regime={self.current_regime}"
        )

    def _build_regime_sequence(self, n_ticks: int) -> List[Tuple[str, float]]:
        """
        Build a structured sequence of regimes that covers all types
        ensuring all engines get tested.

        Returns list of (regime_name, duration) tuples.
        """
        sequence = []
        remaining = n_ticks
        idx = 0

        while remaining > 0 and idx < len(self.REGIME_BLOCKS):
            regime_name, dur_min, _, _, _ = self.REGIME_BLOCKS[idx]
            # Use minimum duration or remaining, whichever is smaller
            dur = min(max(int(dur_min * 2), 10), remaining)
            sequence.append((regime_name, dur))
            remaining -= dur
            idx = (idx + 1) % len(self.REGIME_BLOCKS)  # Cycle through regimes

        # If we have ticks left after cycling, distribute evenly
        if remaining > 0:
            # Add remaining ticks to the last regime
            if sequence:
                last_regime, last_dur = sequence[-1]
                sequence[-1] = (last_regime, last_dur + remaining)

        return sequence

    def _get_current_block_info(self) -> Tuple[str, float, float]:
        """Get current block's regime, drift and volatility."""
        if self.regime_index < len(self.regime_sequence):
            regime_name, dur = self.regime_sequence[self.regime_index]
            # Find params for this regime
            params = {
                "TENDENCIA_ALTA": {'drift': 0.0005, 'volatility': 0.008},
                "TENDENCIA_BAIXA": {'drift': -0.0005, 'volatility': 0.008},
                "CONSOLIDACAO": {'drift': 0.0, 'volatility': 0.003},
                "ROMPE_HIGH": {'drift': 0.002, 'volatility': 0.015},
                "ROMPE_LOW": {'drift': -0.002, 'volatility': 0.015},
                "ALTA_VOLATILIDADE": {'drift': 0.0, 'volatility': 0.025},
                "TRANSICAO": {'drift': 0.0, 'volatility': 0.01},
            }
            p = params.get(regime_name, {'drift': 0.0, 'volatility': 0.01})
            return regime_name, p['drift'], p['volatility']
        else:
            return "TENDENCIA_ALTA", 0.0, 0.008

    def generate_price(self) -> Tuple[float, str]:
        """
        Gera próximo preço seguindo regime estruturado.

        Returns:
            Tuple (preço, regime_nome)
        """
        if self.tick_count >= self.n_ticks:
            # Return last price deterministically
            return self.price, self.current_regime

        # Get current block info
        regime_name, drift, volatility = self._get_current_block_info()

        # Update regime index if block is exhausted
        block_idx = min(self.regime_index + 1, len(self.regime_sequence) - 1)
        if self.tick_count > 0 and self.tick_count % max(1, 20) == 0:
            self.regime_index = block_idx

        self.current_regime = self.regime_sequence[self.regime_index][0] if self.regime_index < len(self.regime_sequence) else "TENDENCIA_ALTA"
        regime_name, drift, volatility = self._get_current_block_info()

        # Generate price move
        shock = self.rng.gauss(0, 1)
        self.price *= (1 + drift + volatility * shock)

        self.tick_count += 1
        return self.price, self.current_regime

    def get_current_regime_name(self) -> str:
        """Return the current regime name."""
        return self.current_regime

    def reset(self) -> None:
        """Reset the market for a new simulation with same seed."""
        self.price = self.initial_price
        self.tick_count = 0
        self.regime_index = 0
        # Rebuild sequence for reproducibility
        self.regime_sequence = self._build_regime_sequence(self.n_ticks)


# ============================================================================
# SIMULATION MODE
# ============================================================================

class SimulationMode(Enum):
    """Modos de simulação disponíveis."""
    RESEARCH = 'research'
    PAPER_TRADING = 'paper_trading'


# ============================================================================
# MAIN SIMULATION FUNCTION
# ============================================================================

def run_simulation(
    mode: SimulationMode,
    ticks: int = 10000,
    initial_capital: float = config.INITIAL_CAPITAL,
    seed: Optional[int] = None,
    data_source: str = "synthetic",
    symbol: str = "USD",
    force_download: bool = False,
    interval: str = "1m",
) -> Dict[str, Any]:
    """
    Executa simulação completa usando os componentes reais de produção.

    Args:
        mode: Modo de simulação (RESEARCH ou PAPER_TRADING)
        ticks: Número de ticks a simular
        initial_capital: Capital inicial
        seed: Seed para reproduzibilidade
        data_source: Fonte de dados ("synthetic", "db", "api")
        symbol: Símbolo da moeda (usado para fontes db e api)
        force_download: Se True, ignora cache e baixa novamente da API
        interval: Intervalo do candle para fonte API (default: "1m")

    Returns:
        Dicionário com resultados da simulação
    """
    is_paper = mode == SimulationMode.PAPER_TRADING
    logger.info(
        f"Iniciando simulação em modo {mode.value} "
        f"({ticks} ticks, seed={seed}, source={data_source})"
    )

    # Componentes oficiais de produção
    equity_mgr = EquityManager(initial_capital=initial_capital)
    risk_ctrl = RiskController()

    # Configurar PositionManager com parâmetros por modo
    if is_paper:
        # Modo conservador: 1 posição, REDUCED
        risk_ctrl.aggressiveness_level = "REDUCED"
        risk_ctrl.max_trades_by_regime = config.get_regime_limits("REDUCED")
        max_positions = 1
        max_age = 15
    else:
        # Modo agressivo: até 5 posições, NORMAL
        risk_ctrl.aggressiveness_level = "NORMAL"
        risk_ctrl.max_trades_by_regime = config.get_regime_limits("NORMAL")
        max_positions = 5
        max_age = 100

    position_mgr = PositionManager(equity_mgr, risk_ctrl, symbol=symbol)
    # Sobrescrever max_age via config do PositionManager (usa _get_max_age_for_level
    # do risk_controller, mas para simulação fixamos aqui):
    position_mgr._max_age_override = max_age  # type: ignore[attr-defined]

    orchestrator = StrategyOrchestrator()
    classifier = MLClassifier(threshold=config.ML_APPROVAL_THRESHOLD)

    # Inicializar telemetry para rastreamento de funil de decisões
    telemetry = SimulationTelemetry(symbol=symbol, enable_detailed_log=False, enable_funnel_stats=True)

    # Estado de confirmação de tendência (paridade com monitor.py)
    trend_confirmation_count: Dict[str, int] = {symbol: 0, "SIM": 0}
    last_trend_regime: Dict[str, Optional[str]] = {symbol: None, "SIM": None}

    # Obter preços da fonte especificada
    data_source_enum = DataSource(data_source)

    # Para fonte sintética, usamos SyntheticMarket diretamente para ter
    # controle do regime em cada tick
    if data_source_enum == DataSource.SYNTHETIC:
        market = SyntheticMarket(seed=seed, n_ticks=ticks)
        prices_series = None
    else:
        from simular import get_historical_prices as _ghp
        prices_series = _ghp(
            source=data_source_enum,
            symbol=symbol,
            n_points=ticks,
            seed=seed,
            force_download=force_download,
            interval=interval,
        )
        market = None

        if prices_series is None or prices_series.empty:
            logger.error("Falha ao obter dados - usando SyntheticMarket como fallback")
            market = SyntheticMarket(seed=seed)
            data_source_enum = DataSource.SYNTHETIC

    # Histórico de preços para análise de regime
    price_history: List[float] = []

    trade_count = 0
    total_pnl = 0.0
    win_count = 0
    total_duration = 0

    last_kpi_time = 0

    # Contadores por engine e regime para performance
    engine_trades: Dict[str, int] = {}
    engine_pnl: Dict[str, float] = {}
    regime_trades: Dict[str, int] = {}
    regime_pnl: Dict[str, float] = {}

    for tick in range(ticks):
        # Obter preço e regime conforme fonte
        if data_source_enum == DataSource.SYNTHETIC:
            price, regime = market.generate_price()
            price_history.insert(0, price)
            if len(price_history) > 100:
                price_history = price_history[:100]

            # Calcular métricas reais do histórico para dados sintéticos,
            # garantindo que engines como TrendFollowing (que exigem momentum > 0)
            # funcionem corretamente.
            if len(price_history) >= config.MIN_HISTORY_FOR_REGIME:
                regime_info = analyze_regime(pd.Series(price_history), symbol=symbol)
                regime = regime_info["regime"]
                regime_metrics = {
                    "regime": regime,
                    "slope": regime_info.get("slope", 0.0),
                    "momentum": regime_info.get("momentum", 0.0),
                    "range_rel": regime_info.get("range_rel", 0.0),
                    "volatility_ratio": regime_info.get("volatility_ratio", 1.0),
                }
            else:
                regime_metrics = {
                    "regime": regime,
                    "slope": 0.0, "momentum": 0.0,
                    "range_rel": 0.0, "volatility_ratio": 1.0,
                }
        else:
            # Usar preços da fonte db/api
            if prices_series is not None and not prices_series.empty and tick < len(prices_series):
                price = float(prices_series.iloc[tick])
            else:
                price = 0.0

            # Adicionar preço ao histórico para análise de regime
            price_history.insert(0, price)
            if len(price_history) > 100:
                price_history = price_history[:100]

            # Determinar regime usando analyze_regime a cada 5 ticks
            if tick % 5 == 0 or tick == 0 or tick == ticks - 1:
                if not prices_series is None and len(prices_series) > tick:
                    window_start = max(0, tick - 20)
                    window_end = min(tick + 1, len(prices_series))
                    window_prices = prices_series[window_start : window_end]
                    if len(window_prices) >= config.MIN_HISTORY_FOR_REGIME:
                        regime_info = analyze_regime(pd.Series(window_prices), symbol=symbol)
                        regime = regime_info["regime"]
                        regime_metrics = {
                            "regime": regime,
                            "slope": regime_info.get("slope", 0.0),
                            "momentum": regime_info.get("momentum", 0.0),
                            "range_rel": regime_info.get("range_rel", 0.0),
                            "volatility_ratio": regime_info.get("volatility_ratio", 1.0),
                        }
                    else:
                        regime = "CONSOLIDACAO"
                        regime_metrics = {
                            "regime": regime,
                            "slope": 0.0, "momentum": 0.0,
                            "range_rel": 0.0, "volatility_ratio": 1.0,
                        }
                else:
                    regime = "CONSOLIDACAO"
                    regime_metrics = {
                        "regime": regime,
                        "slope": 0.0, "momentum": 0.0,
                        "range_rel": 0.0, "volatility_ratio": 1.0,
                    }
            else:
                regime = "CONSOLIDACAO"
                regime_metrics = {
                    "regime": regime,
                    "slope": 0.0, "momentum": 0.0,
                    "range_rel": 0.0, "volatility_ratio": 1.0,
                }

        prices_series_local = pd.Series(price_history) if price_history else pd.Series([price])

        # Detectar regime com o módulo real (só se não for synthetic direto)
        if data_source_enum != DataSource.SYNTHETIC and len(prices_series_local) >= config.MIN_HISTORY_FOR_REGIME:
            regime_info = analyze_regime(prices_series_local, symbol=symbol)
            regime = regime_info["regime"]
            # Atualizar regime_metrics com os valores reais do analysis
            regime_metrics = {
                "regime": regime,
                "slope": regime_info.get("slope", 0.0),
                "momentum": regime_info.get("momentum", 0.0),
                "range_rel": regime_info.get("range_rel", 0.0),
                "volatility_ratio": regime_info.get("volatility_ratio", 1.0),
            }

        # Registrar tick na telemetry antes dos filtros
        # Coletar sinais brutos das engines para o funil
        # Primeiro executamos o orchestrator para ter o resultado final
        # depois rastreamos

        # Executar orquestrador de estratégias reais
        resultado = orchestrator.evaluate(
            price=price,
            regime=regime,
            regime_metrics=regime_metrics,
            prices=prices_series_local,
        )

        # Capturar sinais brutos antes dos filtros para telemetry
        raw_signals = create_default_raw_signals()
        # Sobrescrever com o sinal do orchestrator
        engine_name = resultado.get("engine", "ProtectFlat")
        if engine_name in raw_signals:
            raw_signals[engine_name] = {
                "action": resultado.get("action", "NEUTRO"),
                "confidence": resultado.get("confidence", 0.0),
                "engine": engine_name,
            }

        # Atualizar confirmação de tendência (paridade com monitor.py)
        if regime in ("TENDENCIA_ALTA", "TENDENCIA_BAIXA"):
            if last_trend_regime.get("SIM") == regime:
                trend_confirmation_count["SIM"] = trend_confirmation_count.get("SIM", 0) + 1
            else:
                last_trend_regime["SIM"] = regime
                trend_confirmation_count["SIM"] = 1
        else:
            trend_confirmation_count["SIM"] = 0
            last_trend_regime["SIM"] = None

        # Filtro de confirmação de tendência (mesmo do monitor)
        action = resultado.get("action", "NEUTRO")
        filter_details = create_default_filter_details()

        if action in ("COMPRA", "VENDA"):
            required_ticks = getattr(config, "TREND_CONFIRMATION_TICKS", 2)
            confirmation_count = trend_confirmation_count.get("SIM", 0)
            expected = "TENDENCIA_ALTA" if action == "COMPRA" else "TENDENCIA_BAIXA"

            if regime != expected:
                resultado["action"] = "NEUTRO"
                resultado["confidence"] = 0.0
                resultado["details"] = f"Sinal {action} bloqueado: regime {regime} não confirma {expected}"
                resultado["engine"] = "TrendConfirmationFilter"
                filter_details["trend_confirmation"] = {
                    "blocked": True,
                    "reason": "regime não confirma ação",
                }
            elif position_mgr.get_position("SIM") is not None:
                # Slot de posição ocupado - não pode entrar em nova posição
                filter_details["position_slot"] = {
                    "blocked": True,
                    "reason": "slot_ocupado",
                }
            elif confirmation_count < required_ticks:
                resultado["action"] = "NEUTRO"
                resultado["confidence"] = 0.0
                resultado["details"] = (
                    f"Aguardando confirmação de tendência ({confirmation_count}/{required_ticks})"
                )
                resultado["engine"] = "TrendConfirmationFilter"
                filter_details["trend_confirmation"] = {
                    "blocked": True,
                    "reason": f"confirmação insuficiente ({confirmation_count}/{required_ticks})",
                }

        # Guarda explícito: nunca abrir nova posição com ProtectFlat ou regimes voláteis/transição
        if resultado.get("action") in ("COMPRA", "VENDA"):
            if resultado.get("engine") == "ProtectFlat" or regime in ("TRANSICAO", "ALTA_VOLATILIDADE"):
                resultado["action"] = "NEUTRO"
                resultado["confidence"] = 0.0
                resultado["details"] = "Entrada bloqueada: ProtectFlat/regime volátil ou transição"
                if resultado.get("engine") != "ProtectFlat":
                    resultado["engine"] = "TrendConfirmationFilter"
                filter_details["trend_confirmation"] = {
                    "blocked": True,
                    "reason": "protectflat_ou_regime_volatil_transicao",
                }

        # Filtro de exaustão real (check_exhaustion)
        if resultado.get("action") in ("COMPRA", "VENDA"):
            exhausted, ex_reason = check_exhaustion(
                prices=prices_series_local,
                regime_metrics=regime_metrics,
                suggestion=resultado,
                symbol=symbol,
            )
            if exhausted:
                resultado["action"] = "NEUTRO"
                resultado["confidence"] = 0.0
                resultado["details"] = f"Exaustão: {ex_reason}"
                resultado["engine"] = "ExhaustionFilter"
                filter_details["exhaustion"] = {
                    "blocked": True,
                    "reason": ex_reason,
                }

        # Filtro ML real (se treinado; caso contrário heurística)
        ml_score = None
        if classifier.is_trained():
            resultado = classifier.filter_signal(resultado, regime_metrics)
            ml_score = resultado.get("ml_score")
            if resultado.get("action") == "NEUTRO" and resultado.get("ml_score") is not None:
                filter_details["ml"] = {
                    "blocked": True,
                    "score": resultado.get("ml_score", 0.0),
                    "threshold": config.ML_APPROVAL_THRESHOLD,
                }

        # Registrar decisão de tick na telemetry
        telemetry.tick(
            price=price,
            regime=TelemetryRegime(regime) if regime in [r.value for r in TelemetryRegime] else TelemetryRegime.AGUARDANDO,
            raw_signals=raw_signals,
            filtered_signals={"final": resultado},
            final_action=resultado.get("action", "NEUTRO"),
            final_engine=resultado.get("engine", "ProtectFlat"),
            final_confidence=resultado.get("confidence", 0.0),
            ml_score=ml_score,
            filter_details=filter_details,
        )

        # Avaliar posição (abrir/fechar/manter) — PositionManager oficial
        position_decision = position_mgr.evaluate(
            symbol="SIM",
            signal=resultado["action"],
            price=price,
            regime=regime,
            suggestion=resultado,
            current_tick=tick,
        )

        status_ia = position_decision["action"]

        # Rastrear bloqueio por risco (slot ocupado, limite global, etc.)
        if status_ia == "NEUTRO" and position_decision.get("event") == "RISK_BLOCK":
            filter_details["risk_controller"] = {
                "blocked": True,
                "reason": "risco_bloqueado",
            }

        if status_ia == "SAIR":
            trade_result = position_decision.get("result")
            if trade_result:
                pnl_amount = trade_result["pnl"]
                equity_mgr.update_equity(pnl_amount)
                risk_ctrl.close_position("SIM")
                total_pnl += pnl_amount
                trade_count += 1
                total_duration += trade_result.get("duration_ticks", 0)
                if pnl_amount >= 0:
                    win_count += 1

                # Atribuição correta: usar metadados da abertura (trade_result)
                entry_engine_name = trade_result.get("engine", engine_name)
                entry_regime_name = trade_result.get("entry_regime", regime)
                entry_confidence = trade_result.get("confidence", resultado.get("confidence", 0.0))
                entry_tick = trade_result.get("entry_tick", tick - trade_result.get("duration_ticks", 0))
                exit_tick = trade_result.get("exit_tick", tick)

                try:
                    entry_regime_enum = TelemetryRegime(entry_regime_name)
                except ValueError:
                    entry_regime_enum = TelemetryRegime.CONSOLIDACAO
                try:
                    entry_engine_enum = TelemetrySignalSource(entry_engine_name)
                except ValueError:
                    entry_engine_enum = TelemetrySignalSource.PROTECT_FLAT
                try:
                    final_regime_enum = TelemetryRegime(regime)
                except ValueError:
                    final_regime_enum = TelemetryRegime.CONSOLIDACAO
                try:
                    final_engine_enum = TelemetrySignalSource(engine_name)
                except ValueError:
                    final_engine_enum = TelemetrySignalSource.PROTECT_FLAT

                # Registrar na telemetry (entrada = abertura, final = fechamento)
                trade_record = TradeRecord(
                    entry_tick=entry_tick,
                    exit_tick=exit_tick,
                    symbol="SIM",
                    regime_entry=entry_regime_enum,
                    engine_entry=entry_engine_enum,
                    confidence_entry=entry_confidence,
                    ml_score_entry=ml_score,
                    entry_price=trade_result.get("entry_price", price),
                    exit_price=trade_result.get("exit_price", price),
                    exit_reason=trade_result.get("reason", "UNKNOWN"),
                    pnl=pnl_amount,
                    duration_ticks=trade_result.get("duration_ticks", 0),
                    final_regime=final_regime_enum,
                    final_engine=final_engine_enum,
                )
                telemetry.record_trade(trade_record)

                # Contadores por engine e regime de ENTRADA (origem do trade)
                engine_trades[entry_engine_name] = engine_trades.get(entry_engine_name, 0) + 1
                engine_pnl[entry_engine_name] = engine_pnl.get(entry_engine_name, 0.0) + pnl_amount
                regime_trades[entry_regime_name] = regime_trades.get(entry_regime_name, 0) + 1
                regime_pnl[entry_regime_name] = regime_pnl.get(entry_regime_name, 0.0) + pnl_amount

                # Salvar trade no banco separado de simulação
                try:
                    salvar_trade({
                        **trade_result,
                        "symbol": "SIM_SIMULATION",
                        "aggressiveness": risk_ctrl.aggressiveness_level,
                    })
                except Exception as e:
                    logger.debug(f"Não foi possível salvar trade de simulação: {e}")

        elif status_ia in ("COMPRA", "VENDA"):
            risk_ctrl.register_trade("SIM", regime, status_ia)

        # Decrementar cooldowns do risk controller a cada tick
        risk_ctrl.tick()

        # Log de progresso (apenas DEBUG para não poluir a saída do terminal)
        if tick % 500 == 0:
            logger.debug(
                f"Tick {tick:4d} | "
                f"Price: {price:,.0f} | "
                f"Equity: {equity_mgr.current_equity:,.0f} | "
                f"DD: {equity_mgr.get_max_equity_drawdown():.1%} | "
                f"Posições: {len(position_mgr.positions)}"
            )

    # Estatísticas finais
    win_rate = (win_count / trade_count) if trade_count else 0.0
    avg_pnl = (total_pnl / trade_count) if trade_count else 0.0
    avg_duration = (total_duration / trade_count) if trade_count else 0.0

    trade_statistics = {
        'total_trades': trade_count,
        'win_trades': win_count,
        'loss_trades': trade_count - win_count,
        'win_rate': round(win_rate, 4),
        'avg_pnl_amount': round(avg_pnl, 6),
        'avg_duration': round(avg_duration, 2),
    }

    # Relatório de funil
    funnel_report = telemetry.get_funnel_report()

    # Estatísticas por engine e regime para performance
    engine_stats = {}
    for eng in engine_trades:
        engine_stats[eng] = {
            'trades': engine_trades[eng],
            'total_pnl': round(engine_pnl.get(eng, 0.0), 2),
            'avg_pnl': round(engine_pnl.get(eng, 0.0) / engine_trades[eng], 2) if engine_trades[eng] > 0 else 0.0,
        }

    regime_stats = {}
    for reg in regime_trades:
        regime_stats[reg] = {
            'trades': regime_trades[reg],
            'total_pnl': round(regime_pnl.get(reg, 0.0), 2),
            'avg_pnl': round(regime_pnl.get(reg, 0.0) / regime_trades[reg], 2) if regime_trades[reg] > 0 else 0.0,
        }

    logger.info(
        f"Simulação concluída: "
        f"{trade_count} trades, win_rate={win_rate:.1%}"
    )

    return {
        'mode': mode.value,
        'ticks': ticks,
        'seed': seed,
        'data_source': data_source,
        'final_equity': equity_mgr.current_equity,
        'total_return': equity_mgr.get_total_return(),
        'max_drawdown': equity_mgr.get_max_equity_drawdown(),
        'trade_statistics': trade_statistics,
        'risk_level': risk_ctrl.aggressiveness_level,
        '_funnel_report': funnel_report,
        'engine_stats': engine_stats,
        'regime_stats': regime_stats,
    }


# ============================================================================
# SAVE SIMULATION REPORT
# ============================================================================

def save_simulation_report(
    research: Dict[str, Any],
    paper: Dict[str, Any],
) -> str:
    """
    Salva relatório de comparação entre modos (apenas estatísticas agregadas).

    Args:
        research: Resultados do modo research
        paper: Resultados do modo paper trading

    Returns:
        Caminho do arquivo salvo
    """
    report_dir = config.SIMULATION_REPORTS_DIR
    report_dir.mkdir(exist_ok=True)

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
        'risk_control_passed': paper['max_drawdown'] < 0.25,
    }

    report = {
        'timestamp': datetime.now().isoformat(),
        'research': research,
        'paper_trading': paper,
        'comparison': comparison,
    }

    report_path = report_dir / f"dual_mode_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    size_mb = report_path.stat().st_size / (1024 * 1024)
    if size_mb > config.MAX_REPORT_SIZE_MB:
        logger.warning(
            f"Relatório grande: {size_mb:.2f} MB > {config.MAX_REPORT_SIZE_MB} MB"
        )
    else:
        logger.info(f"Relatório salvo: {report_path} ({size_mb:.2f} MB)")

    return str(report_path)


# ============================================================================
# PRINT REPORT FUNCTIONS
# ============================================================================

def _print_funnel_report(
    research_results: Dict[str, Any],
    paper_results: Dict[str, Any],
) -> None:
    """Imprime o Funil de Decisões no terminal."""
    print()
    print("=" * 60)
    print("🔍 FUNIL DE DECISÕES")
    print("=" * 60)

    for mode_key, res, label in [
        ("RESEARCH", research_results, "RESEARCH"),
        ("PAPER_TRADING", paper_results, "PAPER_TRADING"),
    ]:
        funnel = res.get('_funnel_report', {})
        total_ticks = funnel.get('total_ticks', 0)
        signals_approved = funnel.get('total_signals_approved', 0)
        approval_rate = funnel.get('approval_rate', 0)
        trades_executed = funnel.get('trades_executed', 0)
        win_rate = funnel.get('win_rate', 0)

        # Total signals generated (raw signals by engine)
        engine_breakdown = funnel.get('engine_signal_breakdown', {})
        total_signals = sum(engine_breakdown.values())

        # Filter stats
        filter_stats = funnel.get('filter_stats', {})
        blocked_tc = filter_stats.get('blocked_trend_confirmation', 0)
        blocked_exh = filter_stats.get('blocked_exhaustion', 0)
        blocked_ml = filter_stats.get('blocked_ml', 0)
        blocked_rc = filter_stats.get('blocked_risk_controller', 0)
        total_blocked = blocked_tc + blocked_exh + blocked_ml + blocked_rc

        print(f"\n  📊 {label}:")
        print(f"     Ticks analisados: {total_ticks}")
        print(f"     Sinais gerados (brutos): {total_signals}")
        print(f"     Sinais aprovados: {signals_approved}")
        print(f"     Taxa de aprovação: {approval_rate:.1f}%")
        print(f"     Sinais bloqueados (total): {total_blocked}")
        print(f"       • Confirmação de tendência: {blocked_tc}")
        print(f"       • Exaustão: {blocked_exh}")
        print(f"       • ML/Heurística: {blocked_ml}")
        print(f"       • Risk Controller: {blocked_rc}")
        print(f"     Trades executados: {trades_executed}")
        print(f"     Win rate (telemetry): {win_rate:.1f}%")


def _print_engine_performance(
    research_results: Dict[str, Any],
    paper_results: Dict[str, Any],
) -> None:
    """Imprime Performance por Engine lado a lado."""
    print()
    print("=" * 60)
    print("📈 PERFORMANCE POR ENGINE (lado a lado)")
    print("=" * 60)

    # Coletar todas as engines
    all_engines = set()
    res_eng = research_results.get('engine_stats', {})
    pap_eng = paper_results.get('engine_stats', {})
    all_engines.update(res_eng.keys())
    all_engines.update(pap_eng.keys())

    if not all_engines:
        print("  Dados não disponíveis.")
        return

    print(f"\n  {'Engine':<22} | {'RESEARCH':>20} | {'PAPER_TRADING':>20}")
    print(f"  {'-'*22} | {'-'*20} | {'-'*20}")

    for eng in sorted(all_engines):
        rs = res_eng.get(eng, {'trades': 0, 'total_pnl': 0.0, 'avg_pnl': 0.0})
        ps = pap_eng.get(eng, {'trades': 0, 'total_pnl': 0.0, 'avg_pnl': 0.0})

        research_str = f"{rs['trades']} trades, PnL R$ {rs['total_pnl']:,.2f}"
        paper_str = f"{ps['trades']} trades, PnL R$ {ps['total_pnl']:,.2f}"

        print(f"  {eng:<22} | {research_str:>20} | {paper_str:>20}")


def _print_regime_performance(
    research_results: Dict[str, Any],
    paper_results: Dict[str, Any],
) -> None:
    """Imprime Performance por Regime lado a lado."""
    print()
    print("=" * 60)
    print("📊 PERFORMANCE POR REGIME (lado a lado)")
    print("=" * 60)

    all_regimes = set()
    res_reg = research_results.get('regime_stats', {})
    pap_reg = paper_results.get('regime_stats', {})
    all_regimes.update(res_reg.keys())
    all_regimes.update(pap_reg.keys())

    if not all_regimes:
        print("  Dados não disponíveis.")
        return

    print(f"\n  {'Regime':<22} | {'RESEARCH':>20} | {'PAPER_TRADING':>20}")
    print(f"  {'-'*22} | {'-'*20} | {'-'*20}")

    for reg in sorted(all_regimes):
        rs = res_reg.get(reg, {'trades': 0, 'total_pnl': 0.0, 'avg_pnl': 0.0})
        ps = pap_reg.get(reg, {'trades': 0, 'total_pnl': 0.0, 'avg_pnl': 0.0})

        research_str = f"{rs['trades']} trades, PnL R$ {rs['total_pnl']:,.2f}"
        paper_str = f"{ps['trades']} trades, PnL R$ {ps['total_pnl']:,.2f}"

        print(f"  {reg:<22} | {research_str:>20} | {paper_str:>20}")


def _print_summary(
    research_results: Dict[str, Any],
    paper_results: Dict[str, Any],
    seed: int,
) -> None:
    """Imprime resumo final de ambos os modos."""
    print()
    print("=" * 60)
    print("📊 RESUMO DA SIMULAÇÃO (componentes reais)")
    print("=" * 60)

    print(f"\n  🔬 RESEARCH MODE (seed={seed}):")
    print(f"    • Trades:      {research_results['trade_statistics']['total_trades']}")
    print(f"    • Win Rate:    {research_results['trade_statistics']['win_rate']:.1%}")
    print(f"    • Max DD:      {research_results['max_drawdown']:.1%}")
    print(f"    • Return:      {research_results['total_return']:.1%}")
    print(f"    • Final Eq:    R$ {research_results['final_equity']:,.2f}")

    print(f"\n  📄 PAPER TRADING MODE (seed={seed}):")
    print(f"    • Trades:      {paper_results['trade_statistics']['total_trades']}")
    print(f"    • Win Rate:    {paper_results['trade_statistics']['win_rate']:.1%}")
    print(f"    • Max DD:      {paper_results['max_drawdown']:.1%}")
    print(f"    • Return:      {paper_results['total_return']:.1%}")
    print(f"    • Final Eq:    R$ {paper_results['final_equity']:,.2f}")

    research_trades = research_results['trade_statistics']['total_trades']
    paper_trades = paper_results['trade_statistics']['total_trades']

    if research_trades > 0:
        reduction = (research_trades - paper_trades) / research_trades * 100
        print(f"\n  📉 Trade Reduction: {reduction:.1f}%")

    print('=' * 60 + '\n')


# ============================================================================
# MAIN ENTRY POINT WITH CLI
# ============================================================================

def main():
    """Entry point da simulação com suporte a CLI."""
    parser = argparse.ArgumentParser(
        description="Simulação de trading - Motor com componentes reais de produção"
    )
    parser.add_argument(
        '--source',
        type=str,
        default='synthetic',
        choices=['synthetic', 'db', 'api'],
        help='Fonte de dados para a simulação (default: synthetic)',
    )
    parser.add_argument(
        '--symbol',
        type=str,
        default='USD',
        help='Símbolo da moeda para fontes db/api (default: USD)',
    )
    parser.add_argument(
        '--ticks',
        type=int,
        default=10000,
        help='Número de ticks a simular (default: 10000)',
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Seed para reproduzibilidade (default: 42)',
    )
    parser.add_argument(
        '--capital',
        type=float,
        default=config.INITIAL_CAPITAL,
        help=f'Capital inicial (default: {config.INITIAL_CAPITAL})',
    )
    parser.add_argument(
        '--refresh',
        action='store_true',
        default=False,
        help='Forçar novo download dos dados da API (ignorar cache)',
    )
    parser.add_argument(
        '--interval',
        type=str,
        default='1m',
        choices=['1m', '5m', '15m', '1h', '4h', '1d'],
        help='Intervalo do candle para fonte API (default: 1m)',
    )

    args = parser.parse_args()

    logger.info("🚀 Iniciando simulação dual-mode (componentes reais)...")
    logger.info(f"   Fonte: {args.source} | Símbolo: {args.symbol} | Ticks: {args.ticks} | Seed: {args.seed}")
    if args.source == 'api':
        logger.info(f"   Intervalo: {args.interval} | Refresh: {args.refresh}")

    # Normalizar símbolo para consistência (ex.: btc -> BTC)
    args.symbol = args.symbol.strip().upper()

    # Rodar ambos os modos
    research_results = run_simulation(
        SimulationMode.RESEARCH, ticks=args.ticks,
        initial_capital=args.capital, seed=args.seed,
        data_source=args.source, symbol=args.symbol,
        force_download=args.refresh,
        interval=args.interval,
    )
    paper_results = run_simulation(
        SimulationMode.PAPER_TRADING, ticks=args.ticks,
        initial_capital=args.capital, seed=args.seed,
        data_source=args.source, symbol=args.symbol,
        force_download=args.refresh,
        interval=args.interval,
    )

    # Imprimir relatórios no terminal
    _print_summary(research_results, paper_results, args.seed)
    _print_funnel_report(research_results, paper_results)
    _print_engine_performance(research_results, paper_results)
    _print_regime_performance(research_results, paper_results)

    # Salvar relatório JSON
    report_path = save_simulation_report(research_results, paper_results)
    print(f'✅ Relatório JSON salvo: {report_path}\n')


if __name__ == '__main__':
    main()