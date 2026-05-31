"""
Loop principal de monitoramento do sistema de trading.

Responsável por:
- Coletar cotações em tempo real
- Analisar regime de mercado
- Executar estratégias
- Gerenciar posições
- Controlar risco
- Treinar ML periodicamente
- Gerar relatórios de KPIs
"""
import json
import time
import threading
from pathlib import Path
from typing import Dict, Optional, Any
import logging

import pandas as pd

import config
from database import db_manager, salvar_cotacao, salvar_trade
from equity import EquityManager
from logging_config import (
    setup_logging,
    log_trade_execution,
    log_regime_change,
    log_risk_event,
)
from monitor_base import pegar_cotacao, enviar_mensagem
from market_regime import analyze_regime
from strategy_unified import StrategyOrchestrator
from ml_classifier import MLClassifier
from risk_control import RiskController
from position_manager import PositionManager
from exhaustion_filter import is_exhausted
from kpis import KPITracker

# Configurar logging
logger = setup_logging("monitor", config.LOG_LEVEL)

# Estado global do sistema
ultimo_status: Dict[str, str] = {
    "USD": "NEUTRO",
    "BTC": "NEUTRO",
    "ETH": "NEUTRO",
    "SOL": "NEUTRO",
}
ultimo_regime: Dict[str, Optional[str]] = {
    "USD": None,
    "BTC": None,
    "ETH": None,
    "SOL": None,
}
trend_confirmation_count: Dict[str, int] = {
    "USD": 0,
    "BTC": 0,
    "ETH": 0,
    "SOL": 0,
}

last_trend_regime: Dict[str, Optional[str]] = {
    "USD": None,
    "BTC": None,
    "ETH": None,
    "SOL": None,
}

# Stop event para shutdown gracioso
stop_event = threading.Event()

# Componentes do sistema
orchestrator = StrategyOrchestrator()
classifier = MLClassifier(threshold=config.ML_APPROVAL_THRESHOLD)
risk_controller = RiskController()
equity_manager = EquityManager(initial_capital=config.INITIAL_CAPITAL)
position_manager = PositionManager(equity_manager, risk_controller)
kpi_tracker = KPITracker()


def get_last_collection_epoch(symbol: str) -> Optional[int]:
    """
    Retorna o horário epoch da última coleta salva para o símbolo.
    Usado para detectar buracos temporais entre execuções.
    """
    query = """
        SELECT collected_at_epoch
        FROM cotacoes
        WHERE moeda = ?
          AND collected_at_epoch IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
    """

    try:
        row = db_manager.fetch_one(query, (symbol,))
        if row and row["collected_at_epoch"]:
            return int(row["collected_at_epoch"])
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar última coleta de {symbol}: {e}", exc_info=True)
        return None


def close_position_due_to_data_gap(
    symbol: str,
    preco: float,
    collected_at_epoch: int,
    gap_seconds: int
) -> None:
    """
    Fecha posição aberta quando ocorre DATA_GAP.

    Isso evita que uma posição fique aberta após horas sem dados,
    o que poderia distorcer PnL, duração e lógica de risco.
    """
    position = position_manager.get_position(symbol)

    if position is None:
        return

    logger.warning(
        f"🔴 Fechando posição em {symbol} por DATA_GAP "
        f"({gap_seconds}s sem coleta)."
    )

    trade_result = position_manager.close_position(
        symbol=symbol,
        exit_price=preco,
        exit_regime="DATA_GAP",
        reason=f"data_gap_{gap_seconds}s"
    )

    if not trade_result:
        return

    # Atualizar equity
    pnl_amount = trade_result["pnl"]
    equity_manager.update_equity(pnl_amount)

    # Atualizar RiskController
    risk_controller.close_position(symbol)

    # Registrar KPI
    kpi_tracker.record_trade_result(trade_result)

    # Salvar no banco
    salvar_trade_history(trade_result)

    # Log estruturado
    log_trade_execution(logger, trade_result)

    # Notificar Telegram
    try:
        enviar_mensagem(
            f"⚠️ POSIÇÃO FECHADA POR DATA GAP ({symbol})\n"
            f"Gap: {gap_seconds}s sem coleta\n"
            f"Preço de saída: R$ {preco:.2f}\n"
            f"PnL: {trade_result['pnl']:+.2f}"
        )
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de DATA_GAP: {e}")


def handle_data_gap(
    symbol: str,
    preco: float,
    horario: str,
    collected_at_epoch: int,
    gap_seconds: int
) -> None:
    """
    Registra um gap de dados e impede que o sistema misture histórico antigo
    com dados novos.

    Se houver posição aberta, pode fechá-la automaticamente para evitar
    comportamento inconsistente após retorno da API.
    """
    logger.warning(
        f"⏸️ DATA GAP detectado em {symbol}: {gap_seconds}s sem coleta. "
        f"Resetando continuidade do histórico."
    )

    # Fechar posição aberta, se configurado
    if getattr(config, "CLOSE_POSITION_ON_DATA_GAP", False):
        close_position_due_to_data_gap(
            symbol=symbol,
            preco=preco,
            collected_at_epoch=collected_at_epoch,
            gap_seconds=gap_seconds
        )

    # Registrar ponto de quebra no banco
    salvar_cotacao(
        horario=horario,
        preco=preco,
        moeda=symbol,
        recomendacao=config.DATA_GAP_RECOMMENDATION,
        regime="AGUARDANDO",
        engine="GapGuard",
        confidence=0.0,
        details=f"Gap de dados detectado: {gap_seconds}s sem coleta",
        ml_score=None,
        collected_at_epoch=collected_at_epoch,
    )

    # Resetar estados internos para evitar continuidade falsa
    ultimo_status[symbol] = "NEUTRO"
    ultimo_regime[symbol] = None
    trend_confirmation_count[symbol] = 0
    last_trend_regime[symbol] = None
    

def ensure_reports_dir() -> Path:
    """
    Garante que diretório de relatórios existe.
    
    Returns:
        Path do diretório
    """
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return config.REPORTS_DIR


def save_json_report(data: Dict[str, Any], filename: str) -> str:
    """
    Salva relatório JSON no diretório apropriado.
    
    Args:
        data: Dados para salvar
        filename: Nome do arquivo
        
    Returns:
        Caminho completo do arquivo salvo
    """
    ensure_reports_dir()
    report_path = config.REPORTS_DIR / filename
    
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Relatório salvo: {report_path}")
        return str(report_path)
    except Exception as e:
        logger.error(f"Erro ao salvar relatório {filename}: {e}", exc_info=True)
        raise


def training_loop(trainer, kpi_tracker_ref: KPITracker) -> None:
    """
    Loop de treinamento ML em thread separada.
    
    Treina o modelo periodicamente sem bloquear o monitoramento principal.
    
    Args:
        trainer: Instância do trainer ML
        kpi_tracker_ref: Referência ao KPI tracker
    """
    logger.info("🤖 Thread de treinamento ML iniciada")
    
    while not stop_event.is_set():
        # Aguardar intervalo (interruptível)
        if stop_event.wait(timeout=config.TRAINING_INTERVAL_SECONDS):
            break  # Stop event foi setado
        
        try:
            # Verificar se há dados suficientes
            if kpi_tracker_ref.trade_count < config.MIN_TRADES_FOR_TRAINING:
                logger.info(
                    f"Dados insuficientes para treino: "
                    f"{kpi_tracker_ref.trade_count} < {config.MIN_TRADES_FOR_TRAINING}"
                )
                continue
            
            # Treinar modelo
            logger.info("Iniciando treinamento periódico do ML...")
            resultado = trainer.train_model()
            
            logger.info(
                f"✅ Treino concluído: score={resultado.get('test_score', 0.0):.4f}"
            )
            
            # Salvar relatórios
            relatorio = {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "success",
                "result": resultado,
                "trade_count": kpi_tracker_ref.trade_count,
            }
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            save_json_report(relatorio, f"training_report_{timestamp}.json")
            save_json_report(relatorio, "latest_training_report.json")
            
        except Exception as exc:
            logger.error(f"Falha no treino periódico: {exc}", exc_info=True)
            
            relatorio = {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "error",
                "error": str(exc),
            }
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            save_json_report(relatorio, f"training_report_{timestamp}.json")
            save_json_report(relatorio, "latest_training_report.json")
    
    logger.info("Thread de treinamento ML finalizada")


def analisar_tendencia(moeda_nome: str, preco_atual: float) -> pd.Series:
    """
    Busca histórico recente de preços, ignorando dados anteriores ao último DATA_GAP.
    """
    try:
        # Buscar último ponto de quebra de continuidade
        gap_row = db_manager.fetch_one(
            """
            SELECT MAX(id) as last_gap_id
            FROM cotacoes
            WHERE moeda = ?
              AND recomendacao = ?
            """,
            (moeda_nome, config.DATA_GAP_RECOMMENDATION)
        )

        last_gap_id = gap_row["last_gap_id"] if gap_row and gap_row["last_gap_id"] else 0

        query = """
            SELECT preco 
            FROM cotacoes 
            WHERE moeda = ?
              AND id > ?
            ORDER BY id DESC 
            LIMIT 50
        """

        rows = db_manager.fetch_all(query, (moeda_nome, last_gap_id))

        historico = [preco_atual] + [row["preco"] for row in rows]

        logger.debug(
            f"Histórico carregado para {moeda_nome}: {len(historico)} pontos "
            f"(após gap_id={last_gap_id})"
        )

        return pd.Series(historico)

    except Exception as e:
        logger.error(
            f"Erro ao buscar histórico de {moeda_nome}: {e}",
            exc_info=True
        )
        
        return pd.Series([preco_atual])


def salvar_trade_history(trade_result: Dict[str, Any]) -> None:
    """
    Salva resultado de trade no histórico.
    
    Args:
        trade_result: Dicionário com resultado do trade
    """
    try:
        salvar_trade(trade_result)
        logger.debug(f"Trade salvo no histórico: {trade_result['symbol']}")
    except Exception as e:
        logger.error(f"Erro ao salvar trade no histórico: {e}", exc_info=True)


def loop_monitoramento() -> None:
    """
    Loop principal de monitoramento.
    
    Executa continuamente até receber sinal de parada:
    - Coleta cotações
    - Analisa regime
    - Executa estratégias
    - Gerencia posições
    - Atualiza risco
    """
    logger.info("🚀 Loop de monitoramento iniciado")
    
    # Inicializar contador de ticks
    tick_count = 0
    last_kpi_report_time = time.time()
    
    # Símbolos a monitorar
    symbols = list(config.API_PAIRS.keys())
    
    try:
        while not stop_event.is_set():
            tick_count += 1
            current_time = time.time()
            
            # Atualizar tick do risk controller
            risk_controller.tick()
            
            # Processar cada símbolo
            for symbol in symbols:
                try:
                    process_symbol(
                        symbol=symbol,
                        tick_count=tick_count,
                    )
                except Exception as e:
                    logger.error(
                        f"Erro ao processar {symbol}: {e}",
                        exc_info=True
                    )
                    continue
            
            # Gerar relatório de KPIs periodicamente
            if current_time - last_kpi_report_time >= config.KPI_REPORT_INTERVAL_SECONDS:
                generate_kpi_report()
                last_kpi_report_time = current_time
            
            # Aguardar próximo tick (interruptível)
            logger.debug(f"Tick {tick_count} concluído, aguardando {config.MONITORING_INTERVAL_SECONDS}s")
            if stop_event.wait(timeout=config.MONITORING_INTERVAL_SECONDS):
                logger.info("Stop event recebido, finalizando loop...")
                break
                
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt recebido, finalizando...")
    except Exception as e:
        logger.critical(f"Erro crítico no loop de monitoramento: {e}", exc_info=True)
        raise
    finally:
        logger.info("Loop de monitoramento finalizado")


def update_trend_confirmation(symbol: str, regime: str) -> int:
    """
    Atualiza contador de confirmação de tendência.

    A ideia é exigir que TENDENCIA_ALTA ou TENDENCIA_BAIXA apareça
    por alguns ciclos consecutivos antes de permitir nova entrada.

    Args:
        symbol: Símbolo do ativo.
        regime: Regime atual detectado.

    Returns:
        Número atual de confirmações consecutivas.
    """
    if regime not in ("TENDENCIA_ALTA", "TENDENCIA_BAIXA"):
        trend_confirmation_count[symbol] = 0
        last_trend_regime[symbol] = None
        return 0

    if last_trend_regime[symbol] == regime:
        trend_confirmation_count[symbol] += 1
    else:
        last_trend_regime[symbol] = regime
        trend_confirmation_count[symbol] = 1

    return trend_confirmation_count[symbol]


def apply_trend_confirmation_filter(
    symbol: str,
    regime: str,
    suggestion: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Bloqueia entradas em tendência antes de confirmação mínima.

    Não bloqueia:
    - NEUTRO
    - SAIR
    - HOLD
    - saída de posição existente

    Bloqueia apenas nova COMPRA/VENDA quando a tendência ainda não
    apareceu por ciclos suficientes.
    """
    action = suggestion.get("action", "NEUTRO")

    if action not in ("COMPRA", "VENDA"):
        return suggestion

    # Se já existe posição aberta, não bloquear.
    # A posição precisa continuar sendo gerenciada normalmente.
    if position_manager.get_position(symbol) is not None:
        return suggestion

    required_ticks = getattr(config, "TREND_CONFIRMATION_TICKS", 2)
    confirmation_count = trend_confirmation_count.get(symbol, 0)

    # Garantir alinhamento entre ação e regime
    expected_regime = "TENDENCIA_ALTA" if action == "COMPRA" else "TENDENCIA_BAIXA"

    if regime != expected_regime:
        filtered = suggestion.copy()
        filtered["action"] = "NEUTRO"
        filtered["confidence"] = 0.0
        filtered["details"] = (
            f"Sinal {action} bloqueado: regime {regime} não confirma {expected_regime}"
        )
        filtered["engine"] = "TrendConfirmationFilter"
        return filtered

    if confirmation_count < required_ticks:
        filtered = suggestion.copy()
        filtered["action"] = "NEUTRO"
        filtered["confidence"] = 0.0
        filtered["details"] = (
            f"Aguardando confirmação de tendência "
            f"({confirmation_count}/{required_ticks})"
        )
        filtered["engine"] = "TrendConfirmationFilter"

        logger.info(
            f"⏳ {symbol}: entrada {action} bloqueada por confirmação "
            f"({confirmation_count}/{required_ticks}) em {regime}"
        )

        return filtered

    return suggestion


def process_symbol(symbol: str, tick_count: int) -> None:
    """
    Processa um símbolo individual.
    
    Args:
        symbol: Símbolo da moeda (USD, BTC, ETH, SOL)
        tick_count: Contador de ticks atual
    """
    # Obter cotação
    try:
        pair = config.API_PAIRS[symbol]
        cotacao_data = pegar_cotacao(pair)
    except Exception as e:
        logger.error(f"Erro ao obter cotação de {symbol}: {e}")
        return
    
    if not cotacao_data or 'preco' not in cotacao_data:
        logger.warning(f"Cotação inválida para {symbol}: {cotacao_data}")
        return
    
    preco = float(cotacao_data['preco'])
    horario = cotacao_data.get('horario', time.strftime("%H:%M:%S"))
    nome_db = symbol
    collected_at_epoch = int(time.time())

    last_collection_epoch = get_last_collection_epoch(nome_db)

    if last_collection_epoch is not None:
        gap_seconds = collected_at_epoch - last_collection_epoch

        if gap_seconds > config.MAX_DATA_GAP_SECONDS:
            handle_data_gap(
                symbol=nome_db,
                preco=preco,
                horario=horario,
                collected_at_epoch=collected_at_epoch,
                gap_seconds=gap_seconds
            )
            return
    logger.debug(f"{symbol}: R$ {preco:.2f}")
    
    # Analisar tendência e regime
    historico_precos = analisar_tendencia(nome_db, preco)
    regime_info = analyze_regime(historico_precos)
    regime = regime_info["regime"]

    # Atualizar confirmação de tendência
    confirmation_count = update_trend_confirmation(nome_db, regime)
    
    # Detectar mudança de regime
    if regime != ultimo_regime[nome_db]:
        log_regime_change(logger, symbol, ultimo_regime[nome_db], regime)
        
        # Reset contadores do regime antigo
        if ultimo_regime[nome_db]:
            risk_controller.reset_regime_counts(ultimo_regime[nome_db])
        
        ultimo_regime[nome_db] = regime
    
    # Atualizar drawdown no risk controller
    equity_dd = equity_manager.get_current_drawdown()
    risk_controller.update_drawdown(equity_dd, equity_manager.current_equity)
    
    # Verificar exaustão
    if is_exhausted(symbol, regime):
        logger.debug(f"{symbol} está em estado de exaustão, aguardando...")

        salvar_cotacao(
            horario=horario,
            preco=preco,
            moeda=nome_db,
            recomendacao="NEUTRO",
            regime=regime,
            engine="ExhaustionFilter",
            confidence=0.0,
            details="Símbolo em exaustão",
            ml_score=None,
            collected_at_epoch=collected_at_epoch,
        )
        return
    
    # Executar estratégia
    resultado = orchestrator.evaluate(
        price=preco,
        regime=regime,
        regime_metrics=regime_info,
        prices=historico_precos
    )

    # Aplicar filtro de confirmação de tendência antes do ML e antes da posição
    resultado = apply_trend_confirmation_filter(
        symbol=nome_db,
        regime=regime,
        suggestion=resultado
    )
    
    # Aplicar filtro ML se disponível
    if classifier.is_trained():
        resultado = classifier.filter_signal(resultado, regime_info)
    
    # Registrar no KPI tracker
    kpi_tracker.record_signal(
        symbol=symbol,
        regime=regime,
        engine=resultado.get("engine", "N/A"),
        action=resultado.get("action", "NEUTRO"),
        confidence=resultado.get("confidence", 0.0),
    )
    
    # Avaliar posição (abrir/fechar/manter)
    position_decision = position_manager.evaluate(
        symbol=nome_db,
        signal=resultado["action"],
        price=preco,
        regime=regime,
        suggestion=resultado,
        current_tick=tick_count,
    )
    
    status_ia = position_decision["action"]
    
    # Processar decisão
    if status_ia == "HOLD":
        # Manter posição existente
        position = position_decision.get("position")
        if position:
            status_ia = f"HOLD_{position.side}"
    
    elif status_ia == "SAIR":
        # Fechar posição
        trade_result = position_decision.get("result")
        if trade_result:
            # Atualizar equity
            pnl_amount = trade_result["pnl"]
            equity_manager.update_equity(pnl_amount)
            
            # Registrar no risk controller
            risk_controller.close_position(nome_db)
            
            # Registrar no KPI tracker
            kpi_tracker.record_trade_result(trade_result)
            
            # Salvar no histórico
            salvar_trade_history(trade_result)
            
            # Log
            log_trade_execution(logger, trade_result)
    
    elif status_ia in ("COMPRA", "VENDA"):
        # Nova posição aberta - registrar no risk controller
        risk_controller.register_trade(nome_db, regime, status_ia)
    
    # Salvar cotação no banco
    salvar_cotacao(
        horario=horario,
        preco=preco,
        moeda=nome_db,
        recomendacao=status_ia,
        regime=regime,
        engine=resultado.get("engine", "N/A"),
        confidence=resultado.get("confidence", 0.0),
        details=resultado.get("details", ""),
        ml_score=resultado.get("ml_score"),
        collected_at_epoch=collected_at_epoch,
    )
    
    # Notificar mudança de status
    if status_ia != ultimo_status[nome_db]:
        logger.info(f"📢 Mudança detectada em {nome_db}: {status_ia} ({regime})")
        
        # Enviar mensagem para ações importantes
        if status_ia in ["COMPRA", "VENDA", "SAIR"]:
            try:
                enviar_mensagem(
                    f"🤖 RECOMENDAÇÃO ({nome_db}): {status_ia}\n"
                    f"Regime: {regime}\n"
                    f"Preço: R$ {preco:.2f}\n"
                    f"Confiança: {resultado.get('confidence', 0.0):.2f}"
                )
            except Exception as e:
                logger.error(f"Erro ao enviar mensagem: {e}")
        
        ultimo_status[nome_db] = status_ia
    
    # Log de status
    logger.info(
        f"✅ {nome_db}: R$ {preco:.2f} | {status_ia} | {regime} | "
        f"Engine: {resultado.get('engine', 'N/A')} | "
        f"Conf: {resultado.get('confidence', 0.0):.2f} | "
        f"Equity: R$ {equity_manager.current_equity:,.2f}"
    )
    
    # Mostrar KPIs após fechamento de trade
    if status_ia == "SAIR":
        logger.info(f"📊 KPI SUMMARY: {kpi_tracker.summary()}")


def generate_kpi_report() -> None:
    """Gera e salva relatório de KPIs."""
    try:
        kpi_summary = kpi_tracker.summary()
        risk_status = risk_controller.get_risk_status()
        equity_summary = equity_manager.get_summary()
        
        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kpis": kpi_summary,
            "risk": risk_status,
            "equity": equity_summary,
        }
        
        save_json_report(report, "latest_kpi_report.json")
        logger.debug("Relatório de KPIs gerado")
        
    except Exception as e:
        logger.error(f"Erro ao gerar relatório de KPIs: {e}", exc_info=True)


def shutdown_gracefully() -> None:
    """Finaliza sistema graciosamente."""
    logger.info("Iniciando shutdown gracioso...")
    
    # Setar stop event
    stop_event.set()
    
    # Gerar relatório final
    try:
        generate_kpi_report()
    except Exception as e:
        logger.error(f"Erro ao gerar relatório final: {e}")
    
    logger.info("✅ Shutdown concluído")


if __name__ == "__main__":
    logger.info("🚀 Iniciando o monitor manualmente...")
    
    try:
        # Iniciar thread de treinamento ML
        from ml_training import MLTrainer
        trainer = MLTrainer()
        training_thread = threading.Thread(
            target=training_loop,
            args=(trainer, kpi_tracker),
            daemon=True,
            name="MLTrainingThread"
        )
        training_thread.start()
        
        # Executar loop principal
        loop_monitoramento()
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ KeyboardInterrupt recebido")
    except Exception as e:
        logger.critical(f"Erro fatal: {e}", exc_info=True)
    finally:
        shutdown_gracefully()
