"""
API Flask para dashboard web do sistema de trading.

Fornece endpoints para visualizar:
- Cotações recentes (USD e BTC)
- Resumo de status atual
- KPIs de performance
- Histórico de trades
"""
import threading
import os
from typing import Dict, List, Any, Optional
import logging

from flask import Flask, render_template, jsonify, request
import pandas as pd

import config
from database import db_manager, init_database
from logging_config import setup_logging

# Configurar logging
logger = setup_logging("flask_app", config.LOG_LEVEL)

# Criar app Flask
app = Flask(__name__)


def buscar_dados(moeda: str, limit: int = 50) -> pd.DataFrame:
    """
    Busca histórico recente de cotações para uma moeda.
    
    Args:
        moeda: Símbolo da moeda (USD, BTC)
        limit: Número máximo de registros a retornar
        
    Returns:
        DataFrame com histórico de cotações (ordem cronológica)
    """
    query = """
        SELECT 
            horario as hora,
            preco,
            recomendacao,
            regime,
            engine,
            confidence,
            details,
            created_at as timestamp
        FROM cotacoes
        WHERE moeda = ?
        ORDER BY id DESC
        LIMIT ?
    """
    
    try:
        with db_manager.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(moeda, limit))
        
        # Processar DataFrame
        if not df.empty:
            # Substituir NaN por None
            df = df.where(pd.notnull(df), None)
            
            # Converter tipos
            if 'preco' in df.columns:
                df['preco'] = df['preco'].astype(float)
            
            if 'confidence' in df.columns:
                df['confidence'] = df['confidence'].fillna(0.0).astype(float)
        
        # Inverter ordem (mais antigo primeiro para gráficos)
        df = df.iloc[::-1]
        
        logger.debug(f"Dados carregados para {moeda}: {len(df)} registros")
        return df
        
    except Exception as e:
        logger.error(f"Erro ao buscar dados de {moeda}: {e}", exc_info=True)
        return pd.DataFrame()


def get_latest_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Extrai resumo do último registro.
    
    Args:
        df: DataFrame com histórico de cotações
        
    Returns:
        Dicionário com resumo da última cotação
    """
    if df.empty:
        return {
            "preco": "---",
            "recomendacao": "AGUARDANDO",
            "regime": "AGUARDANDO",
            "engine": "-",
            "confidence": 0.0,
            "details": "Sem dados suficientes",
        }
    
    # Último registro (mais recente)
    last = df.iloc[-1]
    
    return {
        "preco": f"{last['preco']:,.2f}",
        "recomendacao": last["recomendacao"],
        "regime": last["regime"],
        "engine": last.get("engine", "-") or "-",
        "confidence": round(last.get("confidence", 0.0) or 0.0, 2),
        "details": last.get("details", "-") or "-",
    }


def obter_kpis() -> Dict[str, Any]:
    """
    Obtém KPIs de performance dos trades.
    
    Calcula:
    - Total de trades
    - Win rate (% de trades lucrativos)
    - PnL médio
    - Duração média
    - Últimos 20 trades
    
    Returns:
        Dicionário com KPIs calculados
    """
    try:
        # Verificar se tabela existe
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='trade_history'"
            )
            has_history = cursor.fetchone() is not None
        
        if not has_history:
            logger.debug("Tabela trade_history não existe ainda")
            return _empty_kpis()
        
        # Buscar últimos trades
        query = "SELECT * FROM trade_history ORDER BY id DESC LIMIT 20"
        with db_manager.get_connection() as conn:
            df = pd.read_sql_query(query, conn)
        
        if df.empty:
            logger.debug("Nenhum trade no histórico")
            return _empty_kpis()
        
        # Calcular métricas
        total = len(df)
        wins = int((df["pnl"] >= 0).sum())
        avg_pnl = float(df["pnl"].mean())
        avg_duration = float(df["duration_ticks"].mean())
        
        # Converter últimos trades para dicts
        latest_trades = df.to_dict("records")
        
        kpis = {
            "trade_count": total,
            "win_rate": round(wins / total if total else 0.0, 4),
            "avg_pnl": round(avg_pnl, 6),
            "avg_duration": round(avg_duration, 2),
            "latest_trades": latest_trades,
        }
        
        logger.debug(f"KPIs calculados: {total} trades, win_rate={kpis['win_rate']:.1%}")
        return kpis
        
    except Exception as e:
        logger.error(f"Erro ao obter KPIs: {e}", exc_info=True)
        return _empty_kpis()


def _empty_kpis() -> Dict[str, Any]:
    """
    Retorna estrutura de KPIs vazia.
    
    Returns:
        Dict com valores zerados
    """
    return {
        "trade_count": 0,
        "win_rate": 0.0,
        "avg_pnl": 0.0,
        "avg_duration": 0.0,
        "latest_trades": [],
    }


@app.route('/')
def index():
    """
    Página principal do dashboard.
    
    Renderiza template com dados de USD, BTC, ETH, SOL e KPIs.
    
    Returns:
        HTML renderizado
    """
    try:
        # Buscar dados
        df_usd = buscar_dados("USD")
        df_btc = buscar_dados("BTC")
        df_eth = buscar_dados("ETH")
        df_sol = buscar_dados("SOL")
        
        # Resumos
        summary_usd = get_latest_summary(df_usd)
        summary_btc = get_latest_summary(df_btc)
        summary_eth = get_latest_summary(df_eth)
        summary_sol = get_latest_summary(df_sol)
        
        # KPIs
        kpi_data = obter_kpis()
        
        logger.debug("Página principal renderizada com sucesso")
        
        return render_template(
            'index.html',
            summary_usd=summary_usd,
            summary_btc=summary_btc,
            summary_eth=summary_eth,
            summary_sol=summary_sol,
            kpi=kpi_data,
        )
        
    except Exception as e:
        logger.error(f"Erro ao renderizar página principal: {e}", exc_info=True)
        return f"Erro ao carregar dashboard: {str(e)}", 500


@app.route('/dados_atualizados')
def dados_atualizados():
    """
    Endpoint JSON com dados atualizados.
    
    Usado para atualização automática do dashboard via AJAX.
    
    Returns:
        JSON com dados de USD, BTC, ETH, SOL, resumos e KPIs
    """
    try:
        # Buscar dados
        df_usd = buscar_dados("USD")
        df_btc = buscar_dados("BTC")
        df_eth = buscar_dados("ETH")
        df_sol = buscar_dados("SOL")
        
        # Resumos
        summary_usd = get_latest_summary(df_usd)
        summary_btc = get_latest_summary(df_btc)
        summary_eth = get_latest_summary(df_eth)
        summary_sol = get_latest_summary(df_sol)
        
        # KPIs
        kpi_data = obter_kpis()
        
        response = {
            "dolar": df_usd.to_dict('records'),
            "btc": df_btc.to_dict('records'),
            "eth": df_eth.to_dict('records'),
            "sol": df_sol.to_dict('records'),
            "summary_usd": summary_usd,
            "summary_btc": summary_btc,
            "summary_eth": summary_eth,
            "summary_sol": summary_sol,
            "kpi": kpi_data,
        }
        
        logger.debug("Dados atualizados fornecidos via API")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Erro ao fornecer dados atualizados: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health():
    """
    Health check endpoint.
    
    Verifica se a aplicação está respondendo.
    
    Returns:
        JSON com status
    """
    return jsonify({
        "status": "healthy",
        "service": "trading-dashboard"
    })


def _validar_token_controle():
    """Valida token simples para ações críticas pelo dashboard."""
    token_configurado = getattr(config, "CONTROL_TOKEN", "")

    if not token_configurado:
        return False

    token_recebido = request.headers.get("X-Control-Token", "")

    return token_recebido == token_configurado


def _montar_resumo_shutdown():
    """Monta resumo simples do estado do sistema antes de parar."""
    try:
        from monitor import kpi_tracker, risk_controller, equity_manager, position_manager

        kpis = kpi_tracker.summary()
        risk = risk_controller.get_risk_status()
        equity = equity_manager.get_summary()
        open_positions = list(position_manager.positions.keys())

        resumo = (
            "🛑 SISTEMA ENCERRADO PELO DASHBOARD\n\n"
            f"📊 Trades: {kpis.get('trade_count', 0)}\n"
            f"🎯 Win rate: {kpis.get('win_rate', 0.0) * 100:.1f}%\n"
            f"💰 PnL total: {kpis.get('total_pnl', 0.0):+.2f}\n"
            f"📈 Equity atual: R$ {equity.get('current_equity', 0.0):,.2f}\n"
            f"📉 Drawdown atual: {equity.get('current_drawdown_pct', 0.0):.2f}%\n"
            f"🧯 Modo risco: {risk.get('aggressiveness_level', 'UNKNOWN')}\n"
            f"🚫 Trades bloqueados: {risk.get('blocked_trades', 0)}\n"
            f"📌 Posições abertas: {open_positions if open_positions else 'nenhuma'}"
        )

        return resumo

    except Exception as e:
        logger.error(f"Erro ao montar resumo de shutdown: {e}", exc_info=True)
        return "🛑 SISTEMA ENCERRADO PELO DASHBOARD\n\nResumo indisponível por erro interno."


@app.route("/api/shutdown_monitor", methods=["POST"])
def shutdown_monitor():
    """
    Para apenas o loop de monitoramento.
    O Flask continua rodando e o site permanece acessível.
    """
    if not _validar_token_controle():
        return jsonify({"ok": False, "error": "Token inválido"}), 403

    try:
        from monitor import shutdown_gracefully, stop_event
        from monitor_dolar import enviar_mensagem

        if stop_event.is_set():
            return jsonify({"ok": True, "message": "Monitor já estava parado"})

        resumo = _montar_resumo_shutdown()
        enviar_mensagem(resumo)

        shutdown_gracefully()

        logger.warning("🛑 Monitor parado via dashboard")

        return jsonify({
            "ok": True,
            "message": "Monitor parado com sucesso. Flask continua ativo."
        })

    except Exception as e:
        logger.error(f"Erro ao parar monitor via dashboard: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/exit_process", methods=["POST"])
def exit_process():
    """
    Encerra o processo inteiro.
    Isso libera a porta 5000.

    Use somente em ambiente local/controlado.
    """
    if not _validar_token_controle():
        return jsonify({"ok": False, "error": "Token inválido"}), 403

    try:
        from monitor import shutdown_gracefully
        from monitor_dolar import enviar_mensagem

        resumo = _montar_resumo_shutdown()
        enviar_mensagem(resumo)

        shutdown_gracefully()

        logger.critical("🛑 Processo inteiro será encerrado via dashboard")

        def matar_processo():
            os._exit(0)

        # Dá tempo de retornar a resposta HTTP antes de matar o processo
        timer = threading.Timer(1.0, matar_processo)
        timer.daemon = True
        timer.start()

        return jsonify({
            "ok": True,
            "message": "Processo será encerrado em 1 segundo. A porta será liberada."
        })

    except Exception as e:
        logger.error(f"Erro ao encerrar processo via dashboard: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
    

def start_flask_app() -> None:
    """
    Inicia servidor Flask.
    
    Configurações vêm de config.py e variáveis de ambiente.
    """
    logger.info(
        f"🌍 Iniciando servidor Flask em "
        f"{config.FLASK_HOST}:{config.FLASK_PORT} "
        f"(debug={config.FLASK_DEBUG})"
    )
    
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        use_reloader=False  # Reloader causa problemas com threads
    )


if __name__ == '__main__':
    logger.info("🚀 Iniciando aplicação em modo standalone...")
    
    try:
        # Inicializar banco de dados
        logger.info("Inicializando banco de dados...")
        init_database()
        
        # Importar monitor apenas quando necessário
        from monitor import loop_monitoramento
        
        # Iniciar monitor em thread separada
        logger.info("Iniciando thread de monitoramento...")
        monitor_thread = threading.Thread(
            target=loop_monitoramento,
            daemon=True,
            name="MonitorThread"
        )
        monitor_thread.start()
        
        # Iniciar Flask
        start_flask_app()
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Aplicação interrompida pelo usuário")
    except Exception as e:
        logger.critical(f"Erro fatal na aplicação: {e}", exc_info=True)
        raise
