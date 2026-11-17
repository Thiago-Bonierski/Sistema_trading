"""
Módulo de gerenciamento de banco de dados thread-safe.

Resolve o problema de race conditions ao acessar SQLite de múltiplas threads
e é a fonte única de verdade do estado vivo do sistema (cotações, trades,
posições abertas, equity e risco).

Estado vivo persistido:
- positions     -> posições abertas (1 linha por símbolo)
- system_state  -> equity corrente, pico, drawdown e histórico (singleton)
- risk_state    -> nível de risco, contadores, cooldown e kill-switch (singleton)
"""
import json
import sqlite3
import threading
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Any, Dict, List, Tuple

import config

logger = logging.getLogger(__name__)

# Lock global para operações no banco
_db_lock = threading.Lock()


class DatabaseManager:
    """
    Gerenciador thread-safe de conexões SQLite.

    Usa um lock global para garantir que apenas uma thread
    acesse o banco por vez, evitando race conditions.
    """

    def __init__(self, db_path: 'Path' = config.DB_PATH):
        """
        Inicializa o gerenciador.

        Args:
            db_path: Caminho para o arquivo do banco de dados
        """
        self.db_path = db_path
        self._initialized = False

    @contextmanager
    def get_connection(self):
        """
        Context manager para obter conexão thread-safe ao banco.

        Uso:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ...")

        Yields:
            Conexão SQLite thread-safe
        """
        with _db_lock:
            conn = None
            try:
                conn = sqlite3.connect(
                    str(self.db_path),
                    timeout=config.DB_CONNECTION_TIMEOUT
                )
                # Row factory para retornar dicts ao invés de tuplas
                conn.row_factory = sqlite3.Row
                yield conn
                conn.commit()
            except Exception as e:
                if conn:
                    conn.rollback()
                logger.error(f"Erro na conexão do banco: {e}", exc_info=True)
                raise
            finally:
                if conn:
                    conn.close()

    def execute(self, query: str, params: Optional[Tuple] = None) -> None:
        """
        Executa query de escrita (INSERT/UPDATE/DELETE).

        ATENÇÃO: não retorna cursor — a conexão é fechada ao sair do contexto.
        Para ler dados use fetch_one/fetch_all.

        Args:
            query: SQL query
            params: Parâmetros para query parametrizada
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

    def execute_many(self, query: str, params_list: List[Tuple]) -> None:
        """
        Executa query em batch.

        Args:
            query: SQL query
            params_list: Lista de tuplas de parâmetros
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)

    def fetch_one(self, query: str, params: Optional[Tuple] = None) -> Optional[sqlite3.Row]:
        """
        Executa query e retorna primeira linha.

        Args:
            query: SQL query
            params: Parâmetros para query parametrizada

        Returns:
            Primeira linha ou None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchone()

    def fetch_all(self, query: str, params: Optional[Tuple] = None) -> List[sqlite3.Row]:
        """
        Executa query e retorna todas as linhas.

        Args:
            query: SQL query
            params: Parâmetros para query parametrizada

        Returns:
            Lista de linhas
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()

    def initialize_schema(self) -> None:
        """
        Inicializa schema do banco de dados com todas as tabelas e índices.

        Cria tabelas se não existirem e adiciona índices para performance.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Tabela de cotações
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cotacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    horario TEXT NOT NULL,
                    preco REAL NOT NULL,
                    moeda TEXT NOT NULL,
                    recomendacao TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    engine TEXT,
                    confidence REAL DEFAULT 0.0,
                    details TEXT,
                    ml_score REAL,
                    collected_at_epoch INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Tabela de histórico de trades
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    entry_tick INTEGER NOT NULL,
                    exit_tick INTEGER NOT NULL,
                    entry_regime TEXT NOT NULL,
                    exit_regime TEXT NOT NULL,
                    engine TEXT,
                    confidence REAL,
                    pnl REAL NOT NULL,
                    position_size REAL,
                    duration_ticks INTEGER NOT NULL,
                    reason TEXT,
                    aggressiveness TEXT,
                    slope REAL,
                    momentum REAL,
                    range_rel REAL,
                    volatility_ratio REAL,
                    ml_score REAL,
                    feature_schema_version INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ------------------------------------------------------------------
            # ESTADO VIVO (fonte única de verdade)
            # ------------------------------------------------------------------

            # Posições abertas (1 linha por símbolo)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    entry_tick INTEGER NOT NULL,
                    position_size REAL NOT NULL,
                    age INTEGER NOT NULL DEFAULT 0,
                    regime TEXT,
                    engine TEXT,
                    confidence REAL,
                    details TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Equity / capital (singleton id=1)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_capital REAL NOT NULL,
                    current_equity REAL NOT NULL,
                    peak_equity REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    equity_history TEXT,
                    pnl_history TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Estado de risco (singleton id=1)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS risk_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    aggressiveness_level TEXT NOT NULL,
                    global_trade_count INTEGER NOT NULL,
                    trade_count_by_regime TEXT,
                    cooldown TEXT,
                    blocked_trades INTEGER NOT NULL,
                    new_high_counter INTEGER NOT NULL,
                    last_reset_day TEXT,
                    last_equity_high REAL,
                    daily_start_equity REAL,
                    kill_switch_activated INTEGER NOT NULL,
                    kill_switch_until TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Criar índices para performance (se não existirem)
            self._create_indexes(cursor)

            logger.info("Schema do banco inicializado com sucesso")
            self._initialized = True

    def _create_indexes(self, cursor: sqlite3.Cursor) -> None:
        """
        Cria índices para otimizar queries frequentes.

        Args:
            cursor: Cursor do banco
        """
        indexes = [
            # Índice composto para queries de cotações por moeda
            ("idx_cotacoes_moeda_id", "cotacoes", "(moeda, id DESC)"),

            # Índice para buscar por moeda
            ("idx_cotacoes_moeda", "cotacoes", "(moeda)"),

            # Índice para trade_history por símbolo
            ("idx_trade_symbol", "trade_history", "(symbol)"),

            # Índice para trade_history por data
            ("idx_trade_created", "trade_history", "(created_at DESC)"),

            # Índice composto para análise de performance
            ("idx_trade_symbol_created", "trade_history", "(symbol, created_at DESC)"),
        ]

        for index_name, table_name, columns in indexes:
            try:
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {index_name}
                    ON {table_name} {columns}
                """)
                logger.debug(f"Índice {index_name} criado/verificado")
            except sqlite3.Error as e:
                logger.warning(f"Erro ao criar índice {index_name}: {e}")

    def add_column_if_not_exists(self, table: str, column: str,
                                  column_type: str) -> None:
        """
        Adiciona coluna à tabela se ela não existir.

        Útil para migrações backward-compatible.

        Args:
            table: Nome da tabela
            column: Nome da coluna
            column_type: Tipo SQL da coluna
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Verificar se coluna existe
            cursor.execute(f"PRAGMA table_info({table})")
            existing_columns = [row[1] for row in cursor.fetchall()]

            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
                logger.info(f"Coluna {column} adicionada à tabela {table}")
            else:
                logger.debug(f"Coluna {column} já existe em {table}")


# Instância global do gerenciador
db_manager = DatabaseManager()


def init_database() -> None:
    """
    Inicializa o banco de dados.

    Cria schema, índices e migra colunas antigas se necessário.
    """
    logger.info("Inicializando banco de dados...")
    db_manager.initialize_schema()

    # Migrações para backward compatibility
    migrations = [
        ("cotacoes", "engine", "TEXT"),
        ("cotacoes", "confidence", "REAL"),
        ("cotacoes", "details", "TEXT"),
        ("cotacoes", "ml_score", "REAL"),
        ("cotacoes", "collected_at_epoch", "INTEGER"),
        ("cotacoes", "created_at", "TIMESTAMP"),
        ("trade_history", "position_size", "REAL"),
        ("trade_history", "aggressiveness", "TEXT"),
        # Features pré-trade persistidas (schema v2). Sem elas o ML treina
        # com colunas zeradas e produz um modelo degenerado.
        ("trade_history", "slope", "REAL"),
        ("trade_history", "momentum", "REAL"),
        ("trade_history", "range_rel", "REAL"),
        ("trade_history", "volatility_ratio", "REAL"),
        ("trade_history", "ml_score", "REAL"),
        ("trade_history", "feature_schema_version", "INTEGER"),
    ]

    for table, column, col_type in migrations:
        db_manager.add_column_if_not_exists(table, column, col_type)

    logger.info("Banco de dados pronto para uso")


# ============================================================================
# FUNÇÕES DE CONVENIÊNCIA (backwards compatibility)
# ============================================================================

def salvar_cotacao(horario: str, preco: float, moeda: str,
                   recomendacao: str, regime: str,
                   engine: Optional[str] = None,
                   confidence: float = 0.0,
                   details: str = "",
                   ml_score: Optional[float] = None,
                   collected_at_epoch: Optional[int] = None) -> None:
    """
    Salva cotação no banco.

    Args:
        horario: Horário da cotação
        preco: Preço
        moeda: Símbolo da moeda (USD, BTC)
        recomendacao: Recomendação (COMPRA, VENDA, NEUTRO, etc)
        regime: Regime de mercado
        engine: Engine que gerou a recomendação
        confidence: Confiança do sinal
        details: Detalhes adicionais
        ml_score: Score do classificador ML
        collected_at_epoch: Epoch da coleta (para detecção de data gap)
    """
    query = """
        INSERT INTO cotacoes 
        (horario, preco, moeda, recomendacao, regime, engine, confidence, details, ml_score, collected_at_epoch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    db_manager.execute(query, (
        horario, preco, moeda, recomendacao, regime,
        engine, confidence, details, ml_score, collected_at_epoch
    ))


def salvar_trade(trade_result: dict) -> None:
    """
    Salva resultado de trade no histórico.

    Args:
        trade_result: Dicionário com dados do trade
    """
    feature_defaults = {
        "slope": None,
        "momentum": None,
        "range_rel": None,
        "volatility_ratio": None,
        "ml_score": None,
        "feature_schema_version": config.ML_FEATURE_SCHEMA_VERSION,
    }

    base_params = (
        trade_result["symbol"],
        trade_result["side"],
        trade_result["entry_price"],
        trade_result["exit_price"],
        trade_result["entry_tick"],
        trade_result["exit_tick"],
        trade_result["entry_regime"],
        trade_result["exit_regime"],
        trade_result.get("engine"),
        trade_result.get("confidence"),
        trade_result["pnl"],
        trade_result.get("position_size"),
        trade_result["duration_ticks"],
        trade_result["reason"],
        trade_result.get("aggressiveness"),
    )

    query = """
        INSERT INTO trade_history (
            symbol, side, entry_price, exit_price, entry_tick, exit_tick,
            entry_regime, exit_regime, engine, confidence, pnl, position_size,
            duration_ticks, reason, aggressiveness,
            slope, momentum, range_rel, volatility_ratio, ml_score,
            feature_schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    params = base_params + tuple(
        trade_result.get(key, default)
        for key, default in feature_defaults.items()
    )

    try:
        db_manager.execute(query, params)
        return
    except sqlite3.OperationalError as exc:
        # Bancos antigos (sem a migração de features) continuam funcionando.
        if "no column named" not in str(exc):
            raise
        logger.warning(
            "trade_history sem colunas de features; gravando no schema legado"
        )

    legacy_query = """
        INSERT INTO trade_history (
            symbol, side, entry_price, exit_price, entry_tick, exit_tick,
            entry_regime, exit_regime, engine, confidence, pnl, position_size,
            duration_ticks, reason, aggressiveness
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    db_manager.execute(legacy_query, base_params)


# ============================================================================
# PERSISTÊNCIA DO ESTADO VIVO (fonte única de verdade)
# ============================================================================

def save_positions(positions: Dict[str, Dict[str, Any]]) -> None:
    """
    Persiste as posições abertas (substitui o conjunto atual).

    Args:
        positions: Dict {symbol: position_dict}
    """
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM positions")
        for symbol, p in positions.items():
            cursor.execute("""
                INSERT INTO positions
                (symbol, side, entry_price, stop_loss, take_profit, entry_tick,
                 position_size, age, regime, engine, confidence, details, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                p["side"],
                p["entry_price"],
                p["stop_loss"],
                p["take_profit"],
                p["entry_tick"],
                p["position_size"],
                p.get("age", 0),
                p.get("regime", ""),
                p.get("engine", ""),
                p.get("confidence", 0.0),
                p.get("details", ""),
                datetime.now().isoformat(),
            ))


def load_positions() -> Dict[str, Dict[str, Any]]:
    """
    Carrega as posições abertas persistidas.

    Returns:
        Dict {symbol: position_dict}
    """
    rows = db_manager.fetch_all("SELECT * FROM positions")
    return {row["symbol"]: dict(row) for row in rows}


def save_system_state(state: Dict[str, Any]) -> None:
    """
    Persiste o estado de equity (singleton id=1).

    Args:
        state: Dict com initial_capital, current_equity, peak_equity,
               max_drawdown, equity_history, pnl_history
    """
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM system_state")
        cursor.execute("""
            INSERT INTO system_state
            (id, initial_capital, current_equity, peak_equity, max_drawdown,
             equity_history, pnl_history, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        """, (
            state["initial_capital"],
            state["current_equity"],
            state["peak_equity"],
            state["max_drawdown"],
            json.dumps(state.get("equity_history", [])),
            json.dumps(state.get("pnl_history", [])),
            datetime.now().isoformat(),
        ))


def load_system_state() -> Optional[Dict[str, Any]]:
    """
    Carrega o estado de equity persistido.

    Returns:
        Dict com o estado ou None se inexistente
    """
    row = db_manager.fetch_one("SELECT * FROM system_state WHERE id = 1")
    if row is None:
        return None
    data = dict(row)
    try:
        data["equity_history"] = json.loads(data.get("equity_history") or "[]")
        data["pnl_history"] = json.loads(data.get("pnl_history") or "[]")
    except (TypeError, json.JSONDecodeError):
        data["equity_history"] = []
        data["pnl_history"] = []
    return data


def save_risk_state(state: Dict[str, Any]) -> None:
    """
    Persiste o estado de risco (singleton id=1).

    Args:
        state: Dict com o estado do RiskController
    """
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM risk_state")
        cursor.execute("""
            INSERT INTO risk_state
            (id, aggressiveness_level, global_trade_count, trade_count_by_regime,
             cooldown, blocked_trades, new_high_counter, last_reset_day,
             last_equity_high, daily_start_equity, kill_switch_activated,
             kill_switch_until, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            state["aggressiveness_level"],
            state["global_trade_count"],
            json.dumps(state.get("trade_count_by_regime", {})),
            json.dumps(state.get("cooldown", {})),
            state.get("blocked_trades", 0),
            state.get("new_high_counter", 0),
            state.get("last_reset_day"),
            state.get("last_equity_high"),
            state.get("daily_start_equity"),
            1 if state.get("kill_switch_activated") else 0,
            state.get("kill_switch_until"),
            datetime.now().isoformat(),
        ))


def load_risk_state() -> Optional[Dict[str, Any]]:
    """
    Carrega o estado de risco persistido.

    Returns:
        Dict com o estado ou None se inexistente
    """
    row = db_manager.fetch_one("SELECT * FROM risk_state WHERE id = 1")
    if row is None:
        return None
    data = dict(row)
    try:
        data["trade_count_by_regime"] = json.loads(data.get("trade_count_by_regime") or "{}")
        data["cooldown"] = json.loads(data.get("cooldown") or "{}")
    except (TypeError, json.JSONDecodeError):
        data["trade_count_by_regime"] = {}
        data["cooldown"] = {}
    data["kill_switch_activated"] = bool(data.get("kill_switch_activated"))
    return data


def save_all_state(
    positions: Dict[str, Any],
    equity_state: Dict[str, Any],
    risk_state: Dict[str, Any],
) -> None:
    """
    Persiste posições, equity e risco em uma ÚNICA transação.

    Garante que o estado vivo no disco seja sempre coerente.

    Args:
        positions: Dict {symbol: position_dict ou Position}
        equity_state: Dict do EquityManager
        risk_state: Dict do RiskController
    """
    # Normalizar posições para dict (aceita Position ou dict)
    posicoes_dict: Dict[str, Dict[str, Any]] = {}
    for symbol, p in positions.items():
        if hasattr(p, "to_dict"):
            posicoes_dict[symbol] = p.to_dict()
        elif isinstance(p, dict):
            posicoes_dict[symbol] = p
        else:
            posicoes_dict[symbol] = dict(p)

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Posições
        cursor.execute("DELETE FROM positions")
        for symbol, p in posicoes_dict.items():
            cursor.execute("""
                INSERT INTO positions
                (symbol, side, entry_price, stop_loss, take_profit, entry_tick,
                 position_size, age, regime, engine, confidence, details, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, p["side"], p["entry_price"], p["stop_loss"],
                p["take_profit"], p["entry_tick"], p["position_size"],
                p.get("age", 0), p.get("regime", ""), p.get("engine", ""),
                p.get("confidence", 0.0), p.get("details", ""),
                datetime.now().isoformat(),
            ))

        # Equity
        cursor.execute("DELETE FROM system_state")
        cursor.execute("""
            INSERT INTO system_state
            (id, initial_capital, current_equity, peak_equity, max_drawdown,
             equity_history, pnl_history, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        """, (
            equity_state["initial_capital"],
            equity_state["current_equity"],
            equity_state["peak_equity"],
            equity_state["max_drawdown"],
            json.dumps(equity_state.get("equity_history", [])),
            json.dumps(equity_state.get("pnl_history", [])),
            datetime.now().isoformat(),
        ))

        # Risco
        cursor.execute("DELETE FROM risk_state")
        cursor.execute("""
            INSERT INTO risk_state
            (id, aggressiveness_level, global_trade_count, trade_count_by_regime,
             cooldown, blocked_trades, new_high_counter, last_reset_day,
             last_equity_high, daily_start_equity, kill_switch_activated,
             kill_switch_until, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            risk_state["aggressiveness_level"],
            risk_state["global_trade_count"],
            json.dumps(risk_state.get("trade_count_by_regime", {})),
            json.dumps(risk_state.get("cooldown", {})),
            risk_state.get("blocked_trades", 0),
            risk_state.get("new_high_counter", 0),
            risk_state.get("last_reset_day"),
            risk_state.get("last_equity_high"),
            risk_state.get("daily_start_equity"),
            1 if risk_state.get("kill_switch_activated") else 0,
            risk_state.get("kill_switch_until"),
            datetime.now().isoformat(),
        ))


def load_all_state() -> Dict[str, Any]:
    """
    Carrega todo o estado vivo persistido.

    Returns:
        Dict com chaves: positions, equity, risk
    """
    return {
        "positions": load_positions(),
        "equity": load_system_state(),
        "risk": load_risk_state(),
    }
