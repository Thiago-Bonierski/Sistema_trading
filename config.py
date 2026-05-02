"""
Configurações centralizadas do sistema de trading.

Todas as constantes e magic numbers devem ser definidas aqui,
não espalhadas pelo código.
"""
import os
from pathlib import Path
from typing import Dict

# ============================================================================
# PATHS E ARQUIVOS
# ============================================================================
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'historico.db'
REPORTS_DIR = BASE_DIR / 'reports'
SIMULATION_REPORTS_DIR = BASE_DIR / 'simulation_reports'
ML_MODEL_PATH = BASE_DIR / 'ml_model.joblib'
LOG_DIR = BASE_DIR / 'logs'

# Criar diretórios se não existirem
for directory in [REPORTS_DIR, SIMULATION_REPORTS_DIR, LOG_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# ============================================================================
# DATABASE
# ============================================================================
DB_CONNECTION_TIMEOUT = 30.0  # segundos
DB_MAX_RETRIES = 3

# ============================================================================
# TRADING PARAMETERS
# ============================================================================

# Position Management
DEFAULT_STOP_LOSS_PCT = 0.025  # 2.5% max loss per trade
DEFAULT_TAKE_PROFIT_PCT = 0.05  # 5% profit target
MAX_POSITION_AGE_TICKS = {
    "NORMAL": 50,      # Mais tempo para winners
    "REDUCED": 25,     # Médio
    "PROTECT": 15      # Mais curto em modo proteção
}

# Position Sizing
BASE_POSITION_SIZE_PCT = 0.10  # 10% do equity por posição
MIN_CONFIDENCE_FACTOR = 0.4    # Mínimo 40% mesmo com baixa confiança
MAX_CONFIDENCE_FACTOR = 1.0    # Máximo 100%

# ============================================================================
# RISK CONTROL
# ============================================================================

# Trade Limits por Regime
BASE_MAX_TRADES_BY_REGIME: Dict[str, int] = {
    "TENDENCIA_ALTA": 3,
    "TENDENCIA_BAIXA": 3,
    "CONSOLIDACAO": 2,
    "TRANSICAO": 1,
    "ALTA_VOLATILIDADE": 1,
}

GLOBAL_TRADE_LIMIT = 8  # Máximo de trades por dia

# Position Limits
MAX_OPEN_POSITIONS = {
    "NORMAL": 2,
    "REDUCED": 1,
    "PROTECT": 0,
}

MAX_OPEN_POSITIONS_BY_SYMBOL = {
    "NORMAL": 1,
    "REDUCED": 1,
    "PROTECT": 0,
}

# Equity Risk Rules
EQUITY_DRAWDOWN_LIMIT = 0.25  # 25% DD bloqueia trades
MIN_CONFIDENCE_FOR_REDUCED = 0.70

# Kill-Switch (freio de emergência)
DAILY_LOSS_LIMIT = 0.03  # 3% da equity inicial
KILL_SWITCH_HOURS = 2    # Horas de pausa após kill-switch

# Cooldown após stop-loss (ticks)
COOLDOWN_AFTER_STOP = {
    "NORMAL": 5,
    "REDUCED": 10,
    "PROTECT": 20,
}

# Reativação de modo REDUCED -> NORMAL
MIN_NEW_HIGHS_FOR_REACTIVATION = 3

# ============================================================================
# MARKET REGIME DETECTION
# ============================================================================

MIN_HISTORY_FOR_REGIME = 30  # Mínimo de dados para análise

# Thresholds para detecção de regime
RANGE_THRESHOLD = 0.004           # Amplitude relativa baixa
SLOPE_THRESHOLD_SMALL = 0.0015    # Slope muito pequeno
SLOPE_THRESHOLD_MEDIUM = 0.0025   # Para persistência de tendência
SLOPE_THRESHOLD_LARGE = 0.003     # Para tendência clara

VOLATILITY_RATIO_THRESHOLD = 1.2  # Volatilidade não excessiva
CHAOS_VOLATILITY_THRESHOLD = 1.8  # Volatilidade muito alta
CHAOS_RANGE_THRESHOLD = 0.006     # Amplitude alta
CHAOS_MOMENTUM_THRESHOLD = 0.015  # Momentum fraco

# ============================================================================
# STRATEGY ENGINES
# ============================================================================

# Trend Following
TREND_PRICE_THRESHOLD = 0.001     # 0.1% acima/abaixo da média
TREND_CONFIDENCE = 0.82

# Mean Reversion
MEAN_REVERSION_BAND_WIDTH = 0.006  # 0.6% de largura da banda
MEAN_REVERSION_CONFIDENCE = 0.74

# Breakout Momentum
BREAKOUT_THRESHOLD = 0.003         # 0.3% acima máximo/abaixo mínimo
BREAKOUT_MIN_RANGE = 0.003         # Range mínimo necessário
BREAKOUT_CONFIDENCE = 0.68

# ML Classifier
ML_APPROVAL_THRESHOLD = 0.58       # Threshold para aprovar trades

# ============================================================================
# MONITORING
# ============================================================================

MONITORING_INTERVAL_SECONDS = 20   # Intervalo entre checks
TRAINING_INTERVAL_SECONDS = 3600   # Treinar ML a cada 1 hora
KPI_REPORT_INTERVAL_SECONDS = 900  # KPIs a cada 15 minutos

MIN_TRADES_FOR_TRAINING = 30       # Mínimo de trades para treinar ML

# APIs
API_PAIRS = {
    "USD": "USD-BRL",
    "BTC": "BTC-BRL",
    "ETH": "ETH-BRL",
    "SOL": "SOL-BRL",
}

# ============================================================================
# REPORTS & MAINTENANCE
# ============================================================================

# Rotação de arquivos de relatório
MAX_SIMULATION_REPORTS = 10        # Manter apenas últimos 10 relatórios
MAX_TRAINING_REPORTS = 20          # Manter últimos 20 relatórios de treino
REPORT_MAX_AGE_DAYS = 7            # Deletar relatórios com mais de 7 dias

# Tamanho máximo de relatórios JSON (prevenir arquivos gigantes)
MAX_REPORT_SIZE_MB = 10            # Alertar se relatório > 10MB
MAX_TRADES_IN_REPORT = 1000        # Máximo de trades detalhados em relatório

# ============================================================================
# FLASK
# ============================================================================

FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
FLASK_HOST = os.getenv('FLASK_HOST', '127.0.0.1')
FLASK_PORT = int(os.getenv('FLASK_PORT', '5000'))

# ============================================================================
# SIMULATION
# ============================================================================

INITIAL_CAPITAL = 10000.0  # Capital inicial para simulações

# ============================================================================
# LOGGING
# ============================================================================

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Rotação de logs
LOG_MAX_BYTES = 10 * 1024 * 1024   # 10MB
LOG_BACKUP_COUNT = 5                # Manter 5 backups

# ============================================================================
# TOLERANCE FOR FLOAT COMPARISONS
# ============================================================================

FLOAT_TOLERANCE = 1e-9  # Epsilon para comparações de float

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_regime_limits(aggressiveness_level: str) -> Dict[str, int]:
    """
    Retorna limites de trades baseado no nível de agressividade.
    
    Args:
        aggressiveness_level: "NORMAL", "REDUCED", ou "PROTECT"
        
    Returns:
        Dicionário com limites por regime
    """
    if aggressiveness_level == "PROTECT":
        return {k: 1 for k in BASE_MAX_TRADES_BY_REGIME}
    if aggressiveness_level == "REDUCED":
        return {k: max(1, v // 2) for k, v in BASE_MAX_TRADES_BY_REGIME.items()}
    return BASE_MAX_TRADES_BY_REGIME.copy()


def is_close(a: float, b: float, tolerance: float = FLOAT_TOLERANCE) -> bool:
    """
    Compara dois floats com tolerância para evitar bugs de arredondamento.
    
    Args:
        a: Primeiro número
        b: Segundo número
        tolerance: Tolerância aceitável
        
    Returns:
        True se os números são "iguais" dentro da tolerância
    """
    return abs(a - b) < tolerance
