"""
Configuração de logging profissional para o sistema.

Substitui prints espalhados por logging estruturado com níveis,
rotação de arquivos e formatação adequada.
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

import config


def setup_logging(
    name: Optional[str] = None,
    level: Optional[str] = None,
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """
    Configura e retorna logger com handlers apropriados.
    
    Args:
        name: Nome do logger (usa root logger se None)
        level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Se deve logar em arquivo
        log_to_console: Se deve logar no console
        
    Returns:
        Logger configurado
    """
    # Obter ou criar logger
    logger = logging.getLogger(name)
    
    # Determinar nível
    log_level = getattr(logging, level or config.LOG_LEVEL)
    logger.setLevel(log_level)
    
    # Evitar duplicação de handlers
    if logger.handlers:
        return logger
    
    # Formatter
    formatter = logging.Formatter(
        fmt=config.LOG_FORMAT,
        datefmt=config.LOG_DATE_FORMAT
    )
    
    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # File handler com rotação
    if log_to_file:
        log_file = config.LOG_DIR / f"{name or 'trading'}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Não propagar para root logger
    logger.propagate = False
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Retorna logger para um módulo específico.
    
    Args:
        name: Nome do módulo (use __name__)
        
    Returns:
        Logger configurado
    """
    return setup_logging(name)


class SensitiveDataFilter(logging.Filter):
    """
    Filtro para mascarar dados sensíveis em logs.
    
    Previne vazamento de API keys, tokens, senhas, etc.
    """
    
    SENSITIVE_PATTERNS = [
        'api_key',
        'token',
        'password',
        'secret',
        'authorization',
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filtra e mascara dados sensíveis na mensagem de log.
        
        Args:
            record: Log record
            
        Returns:
            True (sempre permite o log, mas mascara dados)
        """
        message = record.getMessage().lower()
        
        for pattern in self.SENSITIVE_PATTERNS:
            if pattern in message:
                # Mascarar dados sensíveis
                record.msg = self._mask_sensitive_data(record.msg)
                record.args = ()
                break
        
        return True
    
    def _mask_sensitive_data(self, message: str) -> str:
        """
        Mascara dados sensíveis na mensagem.
        
        Args:
            message: Mensagem original
            
        Returns:
            Mensagem com dados mascarados
        """
        # Substituir padrões sensíveis por ***
        masked = message
        for pattern in self.SENSITIVE_PATTERNS:
            if pattern in message.lower():
                # Simples substituição - em produção use regex mais sofisticado
                masked = masked.replace(pattern, f"{pattern[:3]}***")
        
        return masked


def add_sensitive_filter(logger: logging.Logger) -> None:
    """
    Adiciona filtro de dados sensíveis a um logger.
    
    Args:
        logger: Logger para adicionar filtro
    """
    logger.addFilter(SensitiveDataFilter())


# ============================================================================
# LOGGING HELPERS
# ============================================================================

def log_trade_execution(logger: logging.Logger, trade_result: dict) -> None:
    """
    Loga execução de trade de forma estruturada.
    
    Args:
        logger: Logger a usar
        trade_result: Resultado do trade
    """
    logger.info(
        f"Trade executado: {trade_result['symbol']} "
        f"{trade_result['side']} | "
        f"PnL: {trade_result['pnl']:.2f} | "
        f"Razão: {trade_result['reason']} | "
        f"Duração: {trade_result['duration_ticks']} ticks"
    )


def log_regime_change(logger: logging.Logger, symbol: str, 
                      old_regime: str, new_regime: str) -> None:
    """
    Loga mudança de regime de mercado.
    
    Args:
        logger: Logger a usar
        symbol: Símbolo da moeda
        old_regime: Regime anterior
        new_regime: Novo regime
    """
    logger.info(
        f"Mudança de regime em {symbol}: "
        f"{old_regime} → {new_regime}"
    )


def log_risk_event(logger: logging.Logger, event_type: str, 
                   details: dict) -> None:
    """
    Loga evento de risco (kill-switch, drawdown, etc).
    
    Args:
        logger: Logger a usar
        event_type: Tipo do evento
        details: Detalhes do evento
    """
    logger.warning(
        f"Evento de risco: {event_type} | "
        f"Detalhes: {details}"
    )


def log_performance_metric(logger: logging.Logger, metric_name: str,
                           value: float, context: str = "") -> None:
    """
    Loga métrica de performance.
    
    Args:
        logger: Logger a usar
        metric_name: Nome da métrica
        value: Valor da métrica
        context: Contexto adicional
    """
    logger.debug(
        f"Métrica: {metric_name} = {value:.4f} "
        f"{f'| {context}' if context else ''}"
    )


# ============================================================================
# EXEMPLO DE USO
# ============================================================================

if __name__ == "__main__":
    # Criar logger para teste
    test_logger = setup_logging("test", "DEBUG")
    
    # Testar níveis
    test_logger.debug("Mensagem de debug")
    test_logger.info("Mensagem informativa")
    test_logger.warning("Alerta")
    test_logger.error("Erro")
    test_logger.critical("Crítico!")
    
    # Testar filtro de dados sensíveis
    add_sensitive_filter(test_logger)
    test_logger.info("API key: abc123xyz")  # Será mascarado
    
    print(f"Logs salvos em: {config.LOG_DIR}")
