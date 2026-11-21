"""
Configurações centralizadas do sistema de trading.

Todas as constantes e magic numbers devem ser definidas aqui,
não espalhadas pelo código.
"""
import os
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

# ============================================================================
# PATHS E ARQUIVOS
# ============================================================================
BASE_DIR = Path(__file__).parent

# Carregar .env explicitamente a partir da pasta do projeto
load_dotenv(BASE_DIR / ".env")

# ============================================================================
# DATA GAP PROTECTION
# ============================================================================

MAX_DATA_GAP_SECONDS = 600  # 10 minutos
DATA_GAP_RECOMMENDATION = "DATA_GAP"

# Se True, fecha posição aberta automaticamente quando detectar DATA_GAP
CLOSE_POSITION_ON_DATA_GAP = True

# ============================================================================
# PATHS E ARQUIVOS
# ============================================================================
BASE_DIR = Path(__file__).parent


def _env_path(name: str, default: Path) -> Path:
    """Diretório configurável por ambiente (usado pelo Docker Compose)."""
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


# Os defaults preservam o layout local histórico. No Docker, o compose aponta
# cada caminho para um volume persistente (/app/data, /app/models, /app/logs).
DATA_DIR = _env_path("TRADING_DATA_DIR", BASE_DIR)
MODELS_DIR = _env_path("TRADING_MODELS_DIR", BASE_DIR)
DB_PATH = DATA_DIR / 'historico.db'
RUNTIME_CONFIG_PATH = DATA_DIR / 'runtime_config.json'
REPORTS_DIR = _env_path("TRADING_REPORTS_DIR", BASE_DIR / 'reports')
SIMULATION_REPORTS_DIR = _env_path(
    "TRADING_SIMULATION_REPORTS_DIR", BASE_DIR / 'simulation_reports'
)
ML_MODEL_PATH = MODELS_DIR / 'ml_model.joblib'
LOG_DIR = _env_path("TRADING_LOG_DIR", BASE_DIR / 'logs')

# Criar diretórios se não existirem
for directory in [DATA_DIR, MODELS_DIR, REPORTS_DIR, SIMULATION_REPORTS_DIR, LOG_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# ============================================================================
# DATABASE
# ============================================================================
DB_CONNECTION_TIMEOUT = 30.0  # segundos
DB_MAX_RETRIES = 3

# ============================================================================
# TRADING PARAMETERS
# ============================================================================

# Position Management — Valores base para fiduciárias (USD/BRL)
# Criptoativos aplicam multiplicador de volatilidade (ver market_regime.py e strategy_unified.py)
DEFAULT_STOP_LOSS_PCT = 0.008  # 0.8% max loss per trade (base fiduciária)
DEFAULT_TAKE_PROFIT_PCT = 0.015  # 1.5% profit target (base fiduciária)
MAX_POSITION_AGE_TICKS = {
    "NORMAL": 30,      # 30 minutos em candles de 1m
    "REDUCED": 30,     # 30 minutos (antes 15 — cortava trades vencedores)
    "PROTECT": 10      # 10 minutos
}

# Histerese da saída por risco de regime.
# TRANSICAO costuma durar 1-2 ticks de ruído; exigir N avaliações
# consecutivas evita fechar a posição antes do take-profit/stop-loss.
# ALTA_VOLATILIDADE (caos extremo) continua encerrando imediatamente.
REGIME_RISK_EXIT_TICKS = 3

# Position Sizing
BASE_POSITION_SIZE_PCT = 0.05  # 5% do equity por posição (base fiduciária)
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

GLOBAL_TRADE_LIMIT = 25  # Máximo de trades por dia (aumentado de 8 para 25)

# Um dia de negociação em candles de 1 minuto. Usado pelo relógio simulado
# do RiskController para virar o dia em backtests (o tempo real não avança).
SIMULATION_TICKS_PER_DAY = 1440

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
EQUITY_DRAWDOWN_LIMIT = 0.15  # 15% DD bloqueia trades (reduzido de 25%)
MIN_CONFIDENCE_FOR_REDUCED = 0.60  # Reduzido de 0.70 para ser mais flexível em REDUCED

# Kill-Switch (freio de emergência)
DAILY_LOSS_LIMIT = 0.02  # 2% da equity inicial (reduzido de 3%)
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

# Thresholds para detecção de regime — Valores BASE para fiduciárias (USD/BRL)
# Criptoativos (BTC, ETH, SOL) aplicam multiplicador CRYPTO_VOL_MULTIPLIER
# (default 2.5x) para ajustar sensibilidade à maior volatilidade.
CRYPTO_VOL_MULTIPLIER = 2.5  # Multiplicador de volatilidade para criptoativos

# Thresholds para detecção de regime (base fiduciária)
RANGE_THRESHOLD = 0.0015           # Amplitude relativa baixa (era 0,004)
SLOPE_THRESHOLD_SMALL = 0.0001     # Slope muito pequeno (era 0,0015)
SLOPE_THRESHOLD_MEDIUM = 0.0002    # Para persistência de tendência (era 0,0025)
SLOPE_THRESHOLD_LARGE = 0.0003     # Para tendência clara (era 0,003)

VOLATILITY_RATIO_THRESHOLD = 1.2   # Volatilidade não excessiva
CHAOS_VOLATILITY_THRESHOLD = 1.8   # Volatilidade muito alta
CHAOS_RANGE_THRESHOLD = 0.003      # Amplitude alta (era 0,006)
CHAOS_MOMENTUM_THRESHOLD = 0.005   # Momentum fraco (era 0,015)

# ============================================================================
# EXHAUSTION FILTER
# ============================================================================

# Thresholds do filtro de exaustão. Os valores abaixo preservam exatamente
# o comportamento histórico (antes eram literais em exhaustion_filter.py) e
# podem ser calibrados em tempo real pelo painel.
EXHAUSTION_MIN_HISTORY = 12
EXHAUSTION_MOMENTUM_HIGH = 0.025
EXHAUSTION_DECELERATION_MIN = 0.006
EXHAUSTION_WEAK_MOMENTUM = 0.008
EXHAUSTION_RANGE_HIGH = 0.0045
EXHAUSTION_VOLATILITY_RATIO_HIGH = 2.5
EXHAUSTION_VOLATILITY_MOMENTUM_MAX = 0.012

# ============================================================================
# CUSTOS DE EXECUÇÃO
# ============================================================================

# Taxa de corretagem cobrada em CADA perna da operação (entrada e saída).
# 0,10% é a taxa padrão Spot da Binance: ida e volta custam ~0,20%.
TRADING_FEE_PCT = 0.001

# Derrapagem média assumida em uma execução a mercado. É aplicada de forma
# desfavorável: + na compra e - na venda (e invertido no fechamento).
SLIPPAGE_PCT = 0.0002

# Em TRANSICAO / ALTA_VOLATILIDADE o spread abre; multiplica o slippage.
VOLATILE_SLIPPAGE_MULTIPLIER = 2.0

# ============================================================================
# STRATEGY ENGINES
# ============================================================================

# Trend Following — Valores base para fiduciárias.
# 0.4%: a 0,2% a engine abria em ruído (SOL/BTC) e só encontrava dois
# extremos em USDT/BRL, que revertiam e respondiam por todo o prejuízo
# do ativo. Com 0,4% as engines de reversão/rompimento assumem os sinais
# descartados e os três ativos fecham positivos em 5.000 ticks.
# ATENÇÃO: esta config é usada tanto pelo backtest quanto por monitor.py
# (operação ao vivo) — a calibração não é exclusiva da simulação.
TREND_PRICE_THRESHOLD = 0.004
TREND_CONFIDENCE = 0.82

# Mean Reversion — calibrado contra custos de execução.
# A banda de 0,10% capturava um movimento médio de ~0,11%, abaixo do custo
# ida-e-volta de ~0,25% (0,20% de taxa + 0,04%~0,08% de slippage): 53 trades
# no BTC fechavam com prejuízo líquido mesmo acertando a direção. Grid com
# 5.000 ticks reais e custos ativos: 0,20% -> +R$71, 0,25% -> +R$85,
# 0,30% -> +R$88 no BTC/PAPER. 0,25% é o ponto com melhor equilíbrio entre
# lucro líquido e volume (9 trades no BTC, 17 na SOL).
MEAN_REVERSION_BAND_WIDTH = 0.0025
MEAN_REVERSION_CONFIDENCE = 0.74

# Breakout Momentum — Valores base para fiduciárias
# Mantido em 0,10%: subir para 0,15%/0,20% no grid cortou o lucro líquido
# do BTC de +R$88 para +R$74/+R$26 sem ganhar precisão.
BREAKOUT_THRESHOLD = 0.0010         # 0.10% acima máximo/abaixo mínimo
# 0,15% deixava 11 trades de USD (stablecoin) com 0% de acerto e ~R$71 de
# prejuízo líquido. Com 0,20% nenhum rompimento de USD qualifica — o filtro
# evita operar onde a amplitude nunca paga os custos. SOL e BTC seguem ativos.
BREAKOUT_MIN_RANGE = 0.0020
BREAKOUT_CONFIDENCE = 0.68

# ML Classifier
# Grid: 0,65/0,68/0,70 reduziram o lucro líquido (menos trades, sem ganho
# de assertividade). Mantido em 0,58 para não estrangular o volume.
ML_APPROVAL_THRESHOLD = 0.58       # Threshold para aprovar trades

# Guardrails do filtro ML. A filtragem é essencial para o sistema e portanto
# fica ATIVA por padrão: sinais abaixo de ML_APPROVAL_THRESHOLD são bloqueados.
# Ainda assim, o classificador cai automaticamente em modo observador (shadow)
# quando o artefato em disco não comprova edge out-of-sample — os guardrails
# continuam protegendo contra modelos degenerados, legados ou em quarentena.
ML_SHADOW_MODE = False             # False = filtro ativo (bloqueia sinais fracos)
ML_FEATURE_SCHEMA_VERSION = 2      # v2 = slope/momentum/range_rel/volatility_ratio persistidos
ML_MODEL_SCHEMA_VERSION = 2        # Formato do artefato: {"pipeline", "metadata"}
ML_MIN_UNIQUE_SCORES = 3           # Menos scores distintos que isso = modelo degenerado
ML_MIN_AUC_OOS = 0.55              # AUC temporal mínima para aplicar o filtro
ML_MIN_AUC_CI_LOW = 0.50           # Limite inferior do IC95% do AUC
ML_MAX_BRIER_RATIO = 1.0           # Brier deve ser melhor que a taxa-base
ML_MIN_APPROVAL_RATE = 0.01        # Aprovação mínima no holdout no threshold atual
ML_MIN_VALIDATION_SAMPLES = 30     # Mínimo de amostras no holdout para validar
ML_VALIDATION_BOOTSTRAP = 1000     # Reamostragens para o IC do AUC
ML_REJECTED_MODEL_SUFFIX = ".rejected.joblib"

# ============================================================================
# MONITORING
# ============================================================================

MONITORING_INTERVAL_SECONDS = 20   # Intervalo entre checks
TRAINING_INTERVAL_SECONDS = 3600   # Treinar ML a cada 1 hora
KPI_REPORT_INTERVAL_SECONDS = 900  # KPIs a cada 15 minutos
TREND_CONFIRMATION_TICKS = 3       # Número de ticks para confirmar tendência (era 2)

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
CONTROL_TOKEN = os.getenv("CONTROL_TOKEN", None)  # Token para autenticação de controle

# ============================================================================
# SIMULATION
# ============================================================================

INITIAL_CAPITAL = 100000.0  # Capital inicial para simulações

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
# EXECUÇÃO (Binance Spot via ccxt)
# ============================================================================

# Modo efetivo do adaptador de execução: PAPER (padrão), TESTNET ou LIVE.
# Nenhuma ordem real sai do computador enquanto estiver em PAPER.
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "PAPER").strip().upper()

# Credenciais. As de TESTNET são usadas apenas com set_sandbox_mode(True).
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY", "")
BINANCE_TESTNET_API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET", "")

# Trava dupla: o modo LIVE é recusado a menos que isto seja explicitamente
# True no .env. Impede que uma variável isolada ligue negociação real.
ALLOW_LIVE_TRADING = os.getenv("ALLOW_LIVE_TRADING", "False").strip().lower() in (
    "1", "true", "yes", "on"
)

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
