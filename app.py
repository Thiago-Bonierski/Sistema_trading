"""
API Flask para dashboard web do sistema de trading.

Fornece endpoints para visualizar:
- Cotações recentes (USD e BTC)
- Resumo de status atual
- KPIs de performance
- Histórico de trades
"""
import threading
import hmac
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import pandas as pd

import config
from database import db_manager, init_database
from logging_config import setup_logging
from runtime_config import ConfigValidationError, runtime_config
from monitor import (
    loop_monitoramento,
    stop_event,
    training_loop,
    get_state_snapshot,
    kpi_tracker,
    position_manager,
    equity_manager,
    risk_controller,
    classifier,
    persist_state,
    salvar_trade_history,
    state_lock,
)
from ml_training import MLTrainer

# Configurar logging
logger = setup_logging("flask_app", config.LOG_LEVEL)

# Criar app Flask
app = Flask(__name__)

# CORS para o painel React/Vite (frontend em outra porta)
CORS(app, resources={r"/api/*": {"origins": "*"}})


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
    """Valida token simples para ações críticas pelo dashboard.

    Rejeita tokens vazios, placeholders (ex: "password") e usa comparação
    em tempo constante (hmac.compare_digest) para evitar timing attack.
    """
    token_configurado = getattr(config, "CONTROL_TOKEN", "") or ""

    # Rejeitar se não houver token configurado ou se for um placeholder óbvio
    if not token_configurado:
        return False
    if token_configurado.strip().lower() in (
        "password",
        "123456",
        "seu_token_aqui",
        "changeme",
        "default",
        "token",
    ):
        logger.warning("CONTROL_TOKEN é um placeholder — ação bloqueada por segurança")
        return False

    token_recebido = request.headers.get("X-Control-Token", "") or ""

    # Rejeitar se o token recebido estiver vazio
    if not token_recebido:
        return False

    return hmac.compare_digest(token_recebido, token_configurado)


def _montar_resumo_shutdown():
    """Monta resumo simples do estado do sistema antes de parar."""
    try:
        from monitor import kpi_tracker, get_state_snapshot

        kpis = kpi_tracker.summary()
        snapshot = get_state_snapshot()
        risk = snapshot["risk"]
        equity = snapshot["equity"]
        open_positions = list(snapshot["positions"].keys())

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
        from monitor_base import enviar_mensagem

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
        from monitor_base import enviar_mensagem

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


# ============================================================================
# PAINEL DE CONTROLE — API REST
# ============================================================================

# Lock e threads do ciclo de vida do monitor. O Flask permanece no ar
# enquanto o loop de mercado é iniciado/pausado sob demanda.
_monitor_lock = threading.RLock()
_monitor_thread: Optional[threading.Thread] = None
_training_thread: Optional[threading.Thread] = None

# Simulações são serializadas: o motor usa estado global de exaustão e
# componentes de risco, então duas execuções concorrentes se corromperiam.
_simulation_lock = threading.Lock()

# Treinamentos ML são serializados para não disputar o arquivo do modelo.
_ml_training_lock = threading.Lock()

_ALLOWED_SIM_SOURCES = {"synthetic", "db", "api"}
_ALLOWED_SIM_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}
_LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}
_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - "
    r"(.+?) - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - (.*)$"
)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _monitor_is_running() -> bool:
    with _monitor_lock:
        thread = _monitor_thread
    return bool(thread and thread.is_alive() and not stop_event.is_set())


def _training_worker() -> None:
    """Executa o loop de treinamento periódico em background."""
    try:
        trainer = MLTrainer()
        training_loop(trainer, kpi_tracker)
    except Exception:
        logger.exception("Erro no loop de treinamento ML")


def _start_monitor_thread() -> bool:
    """
    Inicia o monitor (e o treinamento periódico) sem derrubar o Flask.

    Returns:
        True se uma nova thread foi iniciada; False se já estava ativo.

    Raises:
        RuntimeError: se a thread anterior ainda não terminou de encerrar.
    """
    global _monitor_thread, _training_thread

    with _monitor_lock:
        if _monitor_thread is not None and _monitor_thread.is_alive():
            if not stop_event.is_set():
                return False
            _monitor_thread.join(timeout=5.0)
            if _monitor_thread.is_alive():
                raise RuntimeError(
                    "O monitor anterior ainda está finalizando; tente novamente"
                )

        stop_event.clear()
        _monitor_thread = threading.Thread(
            target=loop_monitoramento,
            daemon=True,
            name="MonitorThread",
        )
        _monitor_thread.start()

        if _training_thread is None or not _training_thread.is_alive():
            _training_thread = threading.Thread(
                target=_training_worker,
                daemon=True,
                name="MLTrainingThread",
            )
            _training_thread.start()

    logger.info("▶️ Monitor iniciado via painel")
    return True


def _pause_monitor_thread(timeout: float = 30.0) -> bool:
    """
    Pausa o loop de monitoramento sem encerrar o Flask.
    """
    stop_event.set()
    with _monitor_lock:
        thread = _monitor_thread

    if thread is not None and thread.is_alive():
        if thread is threading.current_thread():
            return True
        thread.join(timeout=timeout)

    paused = not (thread is not None and thread.is_alive())
    if paused:
        logger.info("⏸️ Monitor pausado via painel")
    else:
        logger.warning("Monitor ainda não finalizou após o timeout de pausa")
    return paused


# ----------------------------------------------------------------------------
# CONFIGURAÇÃO DINÂMICA
# ----------------------------------------------------------------------------

@app.route("/api/config", methods=["GET"])
def api_get_config():
    """Retorna todos os parâmetros calibráveis agrupados por categoria."""
    return jsonify({"ok": True, **runtime_config.get_snapshot()})


@app.route("/api/config", methods=["POST"])
def api_update_config():
    """
    Valida, persiste e aplica parâmetros em tempo real.

    Payload aceito:
        {"values": {"PARAM": 123, ...}}
    ou o objeto de parâmetros diretamente.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    updates = payload.get("values", payload)
    if not isinstance(updates, dict):
        return jsonify(
            {"ok": False, "error": "'values' deve ser um objeto"}
        ), 400

    try:
        snapshot = runtime_config.update(updates)
    except ConfigValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({
        "ok": True,
        "message": "Configuração validada e aplicada em tempo real",
        **snapshot,
    })


@app.route("/api/config/reset", methods=["POST"])
def api_reset_config():
    """Restaura todos (ou uma lista) de parâmetros para os padrões."""
    payload = request.get_json(silent=True) or {}
    keys = payload.get("keys")
    if keys is not None and not isinstance(keys, (list, dict)):
        return jsonify(
            {"ok": False, "error": "'keys' deve ser uma lista"}
        ), 400

    try:
        snapshot = runtime_config.reset(keys)
    except ConfigValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({
        "ok": True,
        "message": "Padrões restaurados",
        **snapshot,
    })


# ----------------------------------------------------------------------------
# SIMULAÇÃO INTERATIVA
# ----------------------------------------------------------------------------

def _parse_simulation_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(payload.get("symbol", "USD")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}", symbol):
        raise ValueError("symbol inválido")

    source = str(payload.get("source", "synthetic")).strip().lower()
    if source not in _ALLOWED_SIM_SOURCES:
        raise ValueError(
            f"source deve ser um de: {', '.join(sorted(_ALLOWED_SIM_SOURCES))}"
        )

    try:
        ticks = int(payload.get("ticks", 5000))
    except (TypeError, ValueError):
        raise ValueError("ticks deve ser inteiro")
    if not 1 <= ticks <= 50000:
        raise ValueError("ticks deve estar entre 1 e 50000")

    seed_raw = payload.get("seed", 42)
    if seed_raw is None or seed_raw == "":
        seed = None
    else:
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            raise ValueError("seed deve ser inteiro")

    try:
        capital = float(payload.get("capital", config.INITIAL_CAPITAL))
    except (TypeError, ValueError):
        raise ValueError("capital deve ser numérico")
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("capital deve ser maior que zero")

    refresh = bool(payload.get("refresh", False))

    interval = str(payload.get("interval", "1m")).strip().lower()
    if interval not in _ALLOWED_SIM_INTERVALS:
        raise ValueError(
            f"interval deve ser um de: {', '.join(sorted(_ALLOWED_SIM_INTERVALS))}"
        )

    return {
        "symbol": symbol,
        "source": source,
        "ticks": ticks,
        "seed": seed,
        "capital": capital,
        "refresh": refresh,
        "interval": interval,
    }


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """
    Executa o motor real em RESEARCH e PAPER_TRADING e retorna o relatório
    completo (funil, estatísticas por engine/regime e trades).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "JSON inválido"}), 400

    try:
        params = _parse_simulation_payload(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not _simulation_lock.acquire(blocking=False):
        return jsonify({
            "ok": False,
            "error": "Já existe uma simulação em andamento",
        }), 409

    try:
        import simular

        bundle = simular.run_dual_simulation(
            ticks=params["ticks"],
            initial_capital=params["capital"],
            seed=params["seed"],
            data_source=params["source"],
            symbol=params["symbol"],
            force_download=params["refresh"],
            interval=params["interval"],
        )
        return jsonify({
            "ok": True,
            "generated_at": _now_iso(),
            **bundle,
        })
    except Exception as exc:
        logger.exception("Falha na simulação via API")
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        _simulation_lock.release()


def _mode_summary(mode_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    mode_data = mode_data or {}
    stats = mode_data.get("trade_statistics", {}) or {}
    return {
        "total_trades": stats.get("total_trades", 0),
        "win_rate": stats.get("win_rate", 0.0),
        "win_trades": stats.get("win_trades", 0),
        "loss_trades": stats.get("loss_trades", 0),
        "avg_pnl_amount": stats.get("avg_pnl_amount", 0.0),
        "avg_duration": stats.get("avg_duration", 0.0),
        "final_equity": mode_data.get("final_equity"),
        "total_pnl": mode_data.get("total_pnl"),
        "total_return": mode_data.get("total_return"),
        "max_drawdown": mode_data.get("max_drawdown"),
        "risk_level": mode_data.get("risk_level"),
        "trades_count": len(mode_data.get("trades") or []),
    }


@app.route("/api/simulations", methods=["GET"])
def api_list_simulations():
    """Lista os relatórios salvos em simulation_reports/ (mais recentes primeiro)."""
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "limit inválido"}), 400
    limit = max(1, min(limit, 500))

    report_dir = Path(config.SIMULATION_REPORTS_DIR)
    reports: List[Dict[str, Any]] = []

    try:
        paths = sorted(
            report_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]
    except OSError:
        paths = []

    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stat = path.stat()
        except Exception as exc:
            logger.warning(f"Relatório inválido ignorado ({path.name}): {exc}")
            continue

        reports.append({
            "filename": path.name,
            "timestamp": data.get("timestamp"),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
                timespec="seconds"
            ),
            "size_bytes": stat.st_size,
            "ticks": (data.get("research") or {}).get("ticks"),
            "symbol": (data.get("research") or {}).get("symbol"),
            "data_source": (data.get("research") or {}).get("data_source"),
            "seed": (data.get("research") or {}).get("seed"),
            "research": _mode_summary(data.get("research")),
            "paper_trading": _mode_summary(data.get("paper_trading")),
            "comparison": data.get("comparison", {}),
        })

    return jsonify({"ok": True, "reports": reports, "count": len(reports)})


@app.route("/api/simulations/<filename>", methods=["GET"])
def api_get_simulation(filename: str):
    """Retorna o relatório completo de uma simulação salva."""
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".json"):
        return jsonify({"ok": False, "error": "nome de arquivo inválido"}), 400

    path = Path(config.SIMULATION_REPORTS_DIR) / safe_name
    if not path.is_file():
        return jsonify({"ok": False, "error": "relatório não encontrado"}), 404

    try:
        return jsonify({
            "ok": True,
            "filename": safe_name,
            "report": json.loads(path.read_text(encoding="utf-8")),
        })
    except Exception as exc:
        logger.error(f"Erro ao ler relatório {safe_name}: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": "relatório inválido"}), 500


# ----------------------------------------------------------------------------
# CONTROLE OPERACIONAL
# ----------------------------------------------------------------------------

@app.route("/api/status", methods=["GET"])
def api_status():
    """Status consolidado do motor para o header do painel."""
    snapshot = get_state_snapshot()
    return jsonify({
        "ok": True,
        "server_time": _now_iso(),
        "monitor_running": _monitor_is_running(),
        "monitor_paused": stop_event.is_set(),
        "ml": _ml_status_payload(),
        "equity": snapshot["equity"],
        "risk": snapshot["risk"],
        "open_positions": sorted(snapshot["positions"].keys()),
    })


@app.route("/api/monitor/toggle", methods=["POST"])
def api_monitor_toggle():
    """
    Inicia, pausa ou alterna o loop de monitoramento.

    Body opcional: {"action": "start" | "pause" | "toggle"}
    """
    payload = request.get_json(silent=True) or {}
    requested = str(payload.get("action", "toggle")).strip().lower()
    if requested not in ("start", "pause", "stop", "toggle"):
        return jsonify({"ok": False, "error": "action inválida"}), 400

    running = _monitor_is_running()
    action = requested
    if action == "toggle":
        action = "pause" if running else "start"
    if action == "stop":
        action = "pause"

    result = None
    try:
        if action == "start":
            started = _start_monitor_thread()
            result = "started" if started else "already_running"
        else:
            if not running:
                result = "already_paused"
            else:
                paused = _pause_monitor_thread()
                result = "paused" if paused else "pausing"
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409

    return jsonify({
        "ok": True,
        "action": result,
        "monitor_running": _monitor_is_running(),
        "monitor_paused": stop_event.is_set(),
    })


def _latest_cotacao(symbol: str) -> Optional[Dict[str, Any]]:
    query = """
        SELECT horario, preco, recomendacao, regime, engine, confidence,
               details, ml_score, collected_at_epoch, created_at
        FROM cotacoes
        WHERE moeda = ?
        ORDER BY id DESC
        LIMIT 1
    """
    try:
        row = db_manager.fetch_one(query, (symbol,))
    except Exception as exc:
        logger.debug(f"Sem cotação para {symbol}: {exc}")
        return None
    return dict(row) if row is not None else None


def _latest_price(symbol: str) -> Optional[float]:
    quote = _latest_cotacao(symbol)
    if not quote or quote.get("preco") is None:
        return None
    try:
        return float(quote["preco"])
    except (TypeError, ValueError):
        return None


@app.route("/api/live", methods=["GET"])
def api_live():
    """
    Cards ao vivo por símbolo + KPIs e últimos trades.

    Inclui posição aberta e PnL flutuante calculado com o último preço.
    """
    snapshot = get_state_snapshot()
    positions = snapshot["positions"]
    cards: List[Dict[str, Any]] = []

    for symbol in config.API_PAIRS:
        quote = _latest_cotacao(symbol)
        position = positions.get(symbol)

        price = None
        if quote and quote.get("preco") is not None:
            try:
                price = float(quote["preco"])
            except (TypeError, ValueError):
                price = None
        if price is None and position:
            price = float(position.get("entry_price") or 0.0)

        card = {
            "symbol": symbol,
            "price": price,
            "regime": (quote or {}).get("regime", "AGUARDANDO"),
            "recommendation": (quote or {}).get("recommendacao", "AGUARDANDO"),
            "engine": (quote or {}).get("engine") or "-",
            "confidence": float((quote or {}).get("confidence") or 0.0),
            "details": (quote or {}).get("details") or "",
            "ml_score": (quote or {}).get("ml_score"),
            "quote_time": (quote or {}).get("horario"),
            "position": None,
        }

        if position:
            card["position"] = _position_view(position, price)

        cards.append(card)

    kpis = obter_kpis()
    return jsonify({
        "ok": True,
        "server_time": _now_iso(),
        "monitor_running": _monitor_is_running(),
        "monitor_paused": stop_event.is_set(),
        "ml": _ml_status_payload(),
        "equity": snapshot["equity"],
        "risk": snapshot["risk"],
        "symbols": cards,
        "kpis": kpis,
        "recent_trades": kpis.get("latest_trades", []),
    })


def _position_view(
    position: Dict[str, Any],
    current_price: Optional[float],
) -> Dict[str, Any]:
    entry_price = float(position.get("entry_price") or 0.0)
    position_size = float(position.get("position_size") or 0.0)
    side = position.get("side")
    price = float(current_price or entry_price or 0.0)

    unrealized_pnl = 0.0
    unrealized_pct = 0.0
    if entry_price > 0 and price > 0:
        direction = 1.0 if side == "COMPRA" else -1.0
        unrealized_pct = (price - entry_price) / entry_price * direction
        unrealized_pnl = position_size * unrealized_pct

    return {
        **position,
        "current_price": price,
        "unrealized_pnl": round(unrealized_pnl, 6),
        "unrealized_pnl_pct": round(unrealized_pct * 100, 4),
    }


@app.route("/api/positions/close-all", methods=["POST"])
def api_close_all_positions():
    """
    Panic Close: fecha todas as posições abertas ao último preço conhecido.

    Atualiza equity, risco, KPI e histórico exatamente como um fechamento
    normal do motor, e persiste o estado resultante.
    """
    closed: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    with state_lock:
        positions = position_manager.positions_to_dict()

        for symbol in list(positions.keys()):
            try:
                quote = _latest_cotacao(symbol)
                price = float((quote or {}).get("preco") or 0.0)
                exit_regime = (quote or {}).get("regime") or "PANIC_CLOSE"
                if price <= 0:
                    price = float(positions[symbol].get("entry_price") or 0.0)

                trade = position_manager.close_position(
                    symbol=symbol,
                    exit_price=price,
                    exit_regime=exit_regime,
                    reason="PANIC_CLOSE",
                )
                if not trade:
                    continue

                equity_manager.update_equity(trade["pnl"])
                risk_controller.close_position(symbol)
                kpi_tracker.record_trade_result(trade)
                salvar_trade_history(trade)
                closed.append(trade)
            except Exception as exc:
                logger.exception(f"Falha no panic close de {symbol}")
                errors.append({"symbol": symbol, "error": str(exc)})

        try:
            persist_state()
        except Exception as exc:
            logger.exception("Falha ao persistir estado após panic close")
            errors.append({"symbol": "*", "error": str(exc)})

    logger.warning(
        f"🚨 Panic Close executado: {len(closed)} posição(ões) fechada(s)"
    )

    return jsonify({
        "ok": not errors,
        "closed": closed,
        "closed_count": len(closed),
        "errors": errors,
        "positions_remaining": len(position_manager.positions),
    })


# ----------------------------------------------------------------------------
# MACHINE LEARNING
# ----------------------------------------------------------------------------

def _count_trades() -> int:
    try:
        row = db_manager.fetch_one(
            "SELECT COUNT(*) AS total FROM trade_history"
        )
        return int(row["total"]) if row else 0
    except Exception:
        return 0


def _read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug(f"Falha ao ler {path}: {exc}")
        return None


def _ml_status_payload() -> Dict[str, Any]:
    status = (
        classifier.ml_status()
        if hasattr(classifier, "ml_status")
        else {"trained": classifier.is_trained()}
    )
    trained = bool(status.get("trained"))
    usable = bool(status.get("usable", trained))
    model_path = Path(config.ML_MODEL_PATH)
    model_stat = None
    if model_path.exists():
        stat = model_path.stat()
        model_stat = {
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(
                timespec="seconds"
            ),
            "size_bytes": stat.st_size,
        }

    latest_report = _read_json_file(
        Path(config.REPORTS_DIR) / "latest_training_report.json"
    )
    result = (latest_report or {}).get("result", {}) or {}

    return {
        "trained": trained,
        "usable": usable,
        "shadow_mode": bool(status.get("shadow_mode", False)),
        "disabled_reason": status.get("disabled_reason"),
        "mode": (
            "model" if usable else ("shadow" if trained else "heuristic")
        ),
        "label": (
            "Modelo validado"
            if usable
            else ("Modelo em observação" if trained else "Heurística")
        ),
        "threshold": float(getattr(classifier, "threshold", 0.0)),
        "model_path": str(model_path),
        "model_exists": model_path.exists(),
        "model": model_stat,
        "accuracy": result.get("test_score"),
        "samples_trained": result.get("samples_trained"),
        "samples_tested": result.get("samples_tested"),
        "n_features": result.get("n_features"),
        "trade_count": _count_trades(),
        "min_trades_for_training": config.MIN_TRADES_FOR_TRAINING,
        "latest_training": latest_report,
    }


@app.route("/api/ml/status", methods=["GET"])
def api_ml_status():
    return jsonify({"ok": True, **_ml_status_payload()})


@app.route("/api/ml/train", methods=["POST"])
def api_ml_train():
    """
    Dispara o treinamento do RandomForest sob demanda.

    Retorna as métricas do treino e recarrega o modelo no classificador
    usado pelo monitor (hot-reload).
    """
    if not _ml_training_lock.acquire(blocking=False):
        return jsonify({
            "ok": False,
            "error": "Já existe um treinamento em andamento",
        }), 409

    try:
        trainer = MLTrainer()
        try:
            result = trainer.train_model()
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 503

        model_loaded = classifier.reload_model()
        report = {
            "generated_at": _now_iso(),
            "status": "success",
            "result": result,
            "trade_count": _count_trades(),
        }

        try:
            from monitor import save_json_report

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_json_report(report, f"training_report_{timestamp}.json")
            save_json_report(report, "latest_training_report.json")
        except Exception:
            logger.exception("Treino concluído, mas falhou ao salvar relatório")

        logger.info(
            f"🤖 Treinamento ML via painel concluído: "
            f"score={result.get('test_score', 0.0):.4f}"
        )

        return jsonify({
            "ok": True,
            "model_loaded": model_loaded,
            "metrics": result,
            "report": report,
        })
    except Exception as exc:
        logger.exception("Falha no treinamento ML via painel")
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        _ml_training_lock.release()


# ----------------------------------------------------------------------------
# LOGS
# ----------------------------------------------------------------------------

def _tail_lines(path: Path, max_bytes: int = 2 * 1024 * 1024) -> List[str]:
    """Lê as últimas linhas de um arquivo sem carregá-lo inteiro."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines()


def _parse_log_line(raw: str, filename: str) -> Dict[str, Any]:
    match = _LOG_LINE_RE.match(raw)
    if not match:
        return {
            "timestamp": None,
            "level": None,
            "logger": None,
            "message": raw,
            "raw": raw,
            "file": filename,
        }
    timestamp, name, level, message = match.groups()
    return {
        "timestamp": timestamp,
        "level": level,
        "logger": name,
        "message": message,
        "raw": raw,
        "file": filename,
    }


@app.route("/api/logs", methods=["GET"])
def api_logs():
    """
    Retorna as últimas N linhas dos logs estruturados.

    Query params:
        lines: quantidade (default 200, máx 2000)
        level: nível mínimo (INFO, WARNING, ERROR, ...)
        search: filtro textual (case-insensitive)
        file: nome de um arquivo específico em logs/ (opcional)
    """
    try:
        lines = int(request.args.get("lines", 200))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "lines inválido"}), 400
    lines = max(1, min(lines, 2000))

    level = str(request.args.get("level", "")).strip().upper()
    if level and level not in _LOG_LEVELS:
        return jsonify({"ok": False, "error": "level inválido"}), 400

    search = str(request.args.get("search", "")).strip()
    file_param = request.args.get("file")

    log_dir = Path(config.LOG_DIR)
    if file_param:
        filename = Path(file_param).name
        if filename != file_param or not filename.endswith(".log"):
            return jsonify({"ok": False, "error": "arquivo inválido"}), 400
        path = log_dir / filename
        if not path.is_file():
            return jsonify({"ok": False, "error": "log não encontrado"}), 404
        paths = [path]
    else:
        try:
            paths = sorted(
                log_dir.glob("*.log"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            paths = []

    entries: List[Dict[str, Any]] = []
    min_level = _LOG_LEVELS.get(level, 0)

    for path in paths:
        try:
            raw_lines = _tail_lines(path)
        except OSError:
            continue
        for raw in raw_lines:
            entry = _parse_log_line(raw, path.name)
            entry_level = entry["level"]
            if level:
                if entry_level is None:
                    continue
                if _LOG_LEVELS.get(entry_level, 0) < min_level:
                    continue
            if search and search.lower() not in raw.lower():
                continue
            entries.append(entry)

    entries.sort(key=lambda item: (item["timestamp"] or "", item["file"]))
    entries = entries[-lines:]

    return jsonify({
        "ok": True,
        "entries": entries,
        "count": len(entries),
        "files": [path.name for path in paths],
        "level": level or None,
    })


# ----------------------------------------------------------------------------
# STARTUP
# ----------------------------------------------------------------------------

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
        
        # Restaurar estado vivo (posições, equity, risco) no boot
        try:
            from monitor import restore_state
            restore_state()
        except Exception as e:
            logger.warning(f"Não foi possível restaurar estado no boot: {e}")
        
        # Iniciar monitor + treinamento ML em threads gerenciadas
        logger.info("Iniciando monitor e treinamento ML...")
        _start_monitor_thread()

        # Iniciar Flask
        start_flask_app()
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Aplicação interrompida pelo usuário")
    except Exception as e:
        logger.critical(f"Erro fatal na aplicação: {e}", exc_info=True)
        raise
