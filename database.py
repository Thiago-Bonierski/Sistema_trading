"""
Módulo de gerenciamento de banco de dados thread-safe.

Resolve o problema de race conditions ao acessar SQLite de múltiplas threads.
"""
import sqlite3
import threading
import logging
from contextlib import contextmanager
from typing import Optional, Any, List, Tuple
from pathlib import Path

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
    
    def __init__(self, db_path: Path = config.DB_PATH):
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
    
    def execute(self, query: str, params: Optional[Tuple] = None) -> sqlite3.Cursor:
        """
        Executa query e retorna cursor.
        
        Args:
            query: SQL query
            params: Parâmetros para query parametrizada
            
        Returns:
            Cursor com resultados
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor
    
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        ("cotacoes", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
        ("trade_history", "position_size", "REAL"),
        ("trade_history", "aggressiveness", "TEXT"),
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
                   ml_score: Optional[float] = None) -> None:
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
    """
    query = """
        INSERT INTO cotacoes 
        (horario, preco, moeda, recomendacao, regime, engine, confidence, details, ml_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    db_manager.execute(query, (
        horario, preco, moeda, recomendacao, regime, 
        engine, confidence, details, ml_score
    ))


def salvar_trade(trade_result: dict) -> None:
    """
    Salva resultado de trade no histórico.
    
    Args:
        trade_result: Dicionário com dados do trade
    """
    query = """
        INSERT INTO trade_history (
            symbol, side, entry_price, exit_price, entry_tick, exit_tick,
            entry_regime, exit_regime, engine, confidence, pnl, position_size,
            duration_ticks, reason, aggressiveness
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    db_manager.execute(query, (
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
    ))
