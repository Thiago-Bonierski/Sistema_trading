"""
Testes da Etapa 1 — configuração dinâmica e API REST do painel.

Cobrem:
- RuntimeConfigManager: agrupamento, validação, persistência, reset e load.
- Endpoints Flask: /api/config, /api/simulate, /api/simulations,
  /api/monitor/toggle, /api/positions/close-all, /api/ml/*, /api/logs,
  /api/status e /api/live.

Os testes nunca tocam o `runtime_config.json` real: cada teste usa um
gerenciador isolado apontando para `tmp_path`.
"""

import copy
import json
import types

import pytest

import config
import app as app_module
from runtime_config import (
    ConfigValidationError,
    PARAMETER_SPECS,
    RuntimeConfigManager,
)


# ============================================================================
# HELPERS
# ============================================================================

def make_isolated_manager(tmp_path):
    """Cria um manager isolado, sem tocar no config global real."""
    module = types.SimpleNamespace(
        **{
            spec.key: copy.deepcopy(getattr(config, spec.key))
            for spec in PARAMETER_SPECS
        }
    )
    manager = RuntimeConfigManager(
        tmp_path / "runtime_config.json",
        config_module=module,
    )
    return manager, module


@pytest.fixture
def manager(tmp_path):
    return make_isolated_manager(tmp_path)


@pytest.fixture
def client(monkeypatch, manager):
    isolated, _module = manager
    monkeypatch.setattr(app_module, "runtime_config", isolated)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


# ============================================================================
# RUNTIME CONFIG MANAGER
# ============================================================================

class TestRuntimeConfigManager:
    def test_snapshot_groups_all_categories(self, manager):
        isolated, _ = manager
        snapshot = isolated.get_snapshot()
        keys = [category["key"] for category in snapshot["categories"]]
        assert keys == ["stops", "regime", "exhaustion", "risk", "costs", "ml"]
        assert len(snapshot["values"]) == len(PARAMETER_SPECS)
        assert snapshot["overrides"] == {}
        assert snapshot["updated_at"] is None

    def test_update_effective_value_and_persistence(self, manager, tmp_path):
        isolated, module = manager
        snapshot = isolated.update({"DEFAULT_STOP_LOSS_PCT": 0.012})

        assert snapshot["values"]["DEFAULT_STOP_LOSS_PCT"] == pytest.approx(0.012)
        assert snapshot["overrides"]["DEFAULT_STOP_LOSS_PCT"] == pytest.approx(0.012)
        assert module.DEFAULT_STOP_LOSS_PCT == pytest.approx(0.012)
        assert snapshot["updated_at"] is not None

        payload = json.loads(
            (tmp_path / "runtime_config.json").read_text(encoding="utf-8")
        )
        assert payload["values"]["DEFAULT_STOP_LOSS_PCT"] == pytest.approx(0.012)

    def test_updating_back_to_default_removes_override(self, manager):
        isolated, _ = manager
        default = isolated.get_value("DEFAULT_STOP_LOSS_PCT")
        isolated.update({"DEFAULT_STOP_LOSS_PCT": 0.012})
        snapshot = isolated.update({"DEFAULT_STOP_LOSS_PCT": default})

        assert "DEFAULT_STOP_LOSS_PCT" not in snapshot["overrides"]

    def test_invalid_type_is_rejected_atomically(self, manager):
        isolated, _ = manager
        before = isolated.get_value("DEFAULT_STOP_LOSS_PCT")

        with pytest.raises(ConfigValidationError):
            isolated.update(
                {
                    "DEFAULT_STOP_LOSS_PCT": 0.012,
                    "GLOBAL_TRADE_LIMIT": "muitos",
                }
            )

        assert isolated.get_value("DEFAULT_STOP_LOSS_PCT") == pytest.approx(before)
        assert isolated.get_snapshot()["overrides"] == {}

    def test_out_of_bounds_is_rejected(self, manager):
        isolated, _ = manager
        with pytest.raises(ConfigValidationError):
            isolated.update({"DEFAULT_STOP_LOSS_PCT": 5.0})

    def test_unknown_key_is_rejected(self, manager):
        isolated, _ = manager
        with pytest.raises(ConfigValidationError):
            isolated.update({"NAO_EXISTE": 1})

    def test_consistency_rule_is_enforced(self, manager):
        isolated, _ = manager
        with pytest.raises(ConfigValidationError):
            isolated.update(
                {
                    "MIN_CONFIDENCE_FACTOR": 0.9,
                    "MAX_CONFIDENCE_FACTOR": 0.5,
                }
            )

    def test_dict_int_partial_merge(self, manager):
        isolated, _ = manager
        snapshot = isolated.update({"MAX_POSITION_AGE_TICKS": {"NORMAL": 77}})
        merged = snapshot["values"]["MAX_POSITION_AGE_TICKS"]
        # Chave informada é sobrescrita; as demais permanecem nos padrões.
        assert merged["NORMAL"] == 77
        assert "REDUCED" in merged

    def test_dict_int_rejects_unknown_keys(self, manager):
        isolated, _ = manager
        with pytest.raises(ConfigValidationError):
            isolated.update({"MAX_POSITION_AGE_TICKS": {"INEXISTENTE": 10}})

    def test_reset_restores_defaults(self, manager):
        isolated, _ = manager
        isolated.update({"DEFAULT_STOP_LOSS_PCT": 0.02})
        snapshot = isolated.reset()
        assert snapshot["overrides"] == {}
        assert snapshot["values"]["DEFAULT_STOP_LOSS_PCT"] == pytest.approx(
            isolated.get_snapshot()["defaults"]["DEFAULT_STOP_LOSS_PCT"]
        )

    def test_reset_specific_keys(self, manager):
        isolated, _ = manager
        isolated.update(
            {
                "DEFAULT_STOP_LOSS_PCT": 0.02,
                "GLOBAL_TRADE_LIMIT": 99,
            }
        )
        snapshot = isolated.reset(["GLOBAL_TRADE_LIMIT"])
        assert "GLOBAL_TRADE_LIMIT" not in snapshot["overrides"]
        assert "DEFAULT_STOP_LOSS_PCT" in snapshot["overrides"]

    def test_load_reads_persisted_values(self, tmp_path):
        isolated, _ = make_isolated_manager(tmp_path)
        isolated.update({"DEFAULT_STOP_LOSS_PCT": 0.011})

        loaded, module = make_isolated_manager(tmp_path)
        snapshot = loaded.load()
        assert snapshot["values"]["DEFAULT_STOP_LOSS_PCT"] == pytest.approx(0.011)
        assert module.DEFAULT_STOP_LOSS_PCT == pytest.approx(0.011)

    def test_load_ignores_invalid_file(self, tmp_path):
        path = tmp_path / "runtime_config.json"
        path.write_text("isto não é json", encoding="utf-8")

        loaded, _ = make_isolated_manager(tmp_path)
        snapshot = loaded.load()
        assert snapshot["overrides"] == {}

    def test_listener_notified_after_update(self, manager):
        isolated, _ = manager
        received = []
        isolated.register_listener(received.append)
        isolated.update({"DEFAULT_STOP_LOSS_PCT": 0.013})
        assert len(received) == 1
        assert received[0]["values"]["DEFAULT_STOP_LOSS_PCT"] == pytest.approx(0.013)


# ============================================================================
# API — CONFIGURAÇÃO
# ============================================================================

class TestConfigApi:
    def test_get_config(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert len(body["categories"]) == 6
        assert "values" in body and "defaults" in body

    def test_post_config_applies_and_persists(self, client, manager):
        isolated, module = manager
        response = client.post(
            "/api/config",
            json={"values": {"DEFAULT_STOP_LOSS_PCT": 0.012}},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert module.DEFAULT_STOP_LOSS_PCT == pytest.approx(0.012)
        assert isolated.get_value("DEFAULT_STOP_LOSS_PCT") == pytest.approx(0.012)

    def test_post_config_accepts_flat_payload(self, client, manager):
        _isolated, module = manager
        response = client.post(
            "/api/config", json={"DEFAULT_TAKE_PROFIT_PCT": 0.02}
        )
        assert response.status_code == 200
        assert module.DEFAULT_TAKE_PROFIT_PCT == pytest.approx(0.02)

    def test_post_config_invalid_returns_400(self, client):
        response = client.post(
            "/api/config", json={"values": {"DEFAULT_STOP_LOSS_PCT": 99}}
        )
        assert response.status_code == 400
        assert response.get_json()["ok"] is False

    def test_post_config_invalid_json_returns_400(self, client):
        response = client.post(
            "/api/config",
            data="não-json",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_reset_endpoint(self, client, manager):
        isolated, _ = manager
        client.post(
            "/api/config", json={"values": {"DEFAULT_STOP_LOSS_PCT": 0.012}}
        )
        response = client.post("/api/config/reset", json={})
        assert response.status_code == 200
        assert response.get_json()["overrides"] == {}
        assert isolated.get_value("DEFAULT_STOP_LOSS_PCT") == pytest.approx(
            config.DEFAULT_STOP_LOSS_PCT
        )

    def test_cors_header_present(self, client):
        response = client.get("/api/config", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert response.headers.get("Access-Control-Allow-Origin") in (
            "*",
            "http://localhost:5173",
        )


# ============================================================================
# API — SIMULAÇÃO
# ============================================================================

class TestSimulationApi:
    @pytest.mark.parametrize(
        "payload",
        [
            {"symbol": "INVALIDO!"},
            {"source": "planilha"},
            {"ticks": 0},
            {"ticks": 999999},
            {"ticks": "abc"},
            {"seed": "xyz"},
            {"capital": -10},
            {"interval": "2s"},
        ],
    )
    def test_invalid_payload_returns_400(self, client, payload):
        response = client.post("/api/simulate", json=payload)
        assert response.status_code == 400
        assert response.get_json()["ok"] is False

    def test_invalid_json_returns_400(self, client):
        response = client.post(
            "/api/simulate", data="x", content_type="application/json"
        )
        assert response.status_code == 400

    def test_simulate_runs_real_engine(
        self, client, monkeypatch, tmp_path
    ):
        reports_dir = tmp_path / "simulation_reports"
        reports_dir.mkdir()
        monkeypatch.setattr(config, "SIMULATION_REPORTS_DIR", reports_dir)

        import simular

        # Evita escrita no banco real durante o teste.
        monkeypatch.setattr(simular, "salvar_trade", lambda *a, **k: None)

        response = client.post(
            "/api/simulate",
            json={
                "symbol": "USD",
                "source": "synthetic",
                "ticks": 120,
                "seed": 42,
                "capital": 10000,
                "refresh": False,
            },
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["research"]["ticks"] == 120
        assert body["research"]["symbol"] == "USD"
        assert "trades" in body["research"]
        assert "_funnel_report" in body["research"]
        assert body["paper_trading"]["mode"] == "paper_trading"
        assert "comparison" in body
        assert body["report_path"]
        assert any(reports_dir.glob("*.json"))

    def test_simulations_listing(self, client, monkeypatch, tmp_path):
        reports_dir = tmp_path / "simulation_reports"
        reports_dir.mkdir()
        sample = {
            "timestamp": "2026-01-01T00:00:00",
            "research": {
                "ticks": 500,
                "symbol": "USD",
                "data_source": "synthetic",
                "seed": 42,
                "trade_statistics": {"total_trades": 4, "win_rate": 50.0},
            },
            "paper_trading": {
                "trade_statistics": {"total_trades": 2, "win_rate": 100.0}
            },
            "comparison": {"trade_reduction_pct": 50.0},
        }
        (reports_dir / "dual_mode_report_a.json").write_text(
            json.dumps(sample), encoding="utf-8"
        )
        (reports_dir / "broken.json").write_text("{oops", encoding="utf-8")
        monkeypatch.setattr(config, "SIMULATION_REPORTS_DIR", reports_dir)

        response = client.get("/api/simulations")
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["count"] == 1
        assert body["reports"][0]["filename"] == "dual_mode_report_a.json"
        assert body["reports"][0]["research"]["total_trades"] == 4

    def test_simulation_detail(self, client, monkeypatch, tmp_path):
        reports_dir = tmp_path / "simulation_reports"
        reports_dir.mkdir()
        (reports_dir / "dual_mode_report_a.json").write_text(
            json.dumps({"research": {"ticks": 10}}), encoding="utf-8"
        )
        monkeypatch.setattr(config, "SIMULATION_REPORTS_DIR", reports_dir)

        response = client.get("/api/simulations/dual_mode_report_a.json")
        assert response.status_code == 200
        assert response.get_json()["report"]["research"]["ticks"] == 10

    def test_simulation_detail_rejects_bad_extension(self, client):
        response = client.get("/api/simulations/arquivo.txt")
        assert response.status_code == 400

    def test_simulation_detail_missing_returns_404(self, client, monkeypatch, tmp_path):
        reports_dir = tmp_path / "simulation_reports"
        reports_dir.mkdir()
        monkeypatch.setattr(config, "SIMULATION_REPORTS_DIR", reports_dir)
        response = client.get("/api/simulations/nao_existe.json")
        assert response.status_code == 404


# ============================================================================
# API — CONTROLE OPERACIONAL
# ============================================================================

class TestControlApi:
    def test_toggle_start(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "_monitor_is_running", lambda: False)
        monkeypatch.setattr(app_module, "_start_monitor_thread", lambda: True)
        response = client.post("/api/monitor/toggle", json={"action": "start"})
        assert response.status_code == 200
        assert response.get_json()["action"] == "started"

    def test_toggle_already_running(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "_monitor_is_running", lambda: True)
        monkeypatch.setattr(app_module, "_start_monitor_thread", lambda: False)
        response = client.post("/api/monitor/toggle", json={"action": "start"})
        assert response.status_code == 200
        assert response.get_json()["action"] == "already_running"

    def test_toggle_pause(self, client, monkeypatch):
        monkeypatch.setattr(app_module, "_monitor_is_running", lambda: True)
        monkeypatch.setattr(app_module, "_pause_monitor_thread", lambda: True)
        response = client.post("/api/monitor/toggle", json={"action": "pause"})
        assert response.status_code == 200
        assert response.get_json()["action"] == "paused"

    def test_toggle_invalid_action(self, client):
        response = client.post("/api/monitor/toggle", json={"action": "explodir"})
        assert response.status_code == 400

    def test_panic_close_without_positions(self, client, monkeypatch):
        monkeypatch.setattr(
            app_module.position_manager, "positions_to_dict", lambda: {}
        )
        monkeypatch.setattr(app_module, "persist_state", lambda: None)

        response = client.post("/api/positions/close-all", json={})
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["closed_count"] == 0

    def test_panic_close_with_position(self, client, monkeypatch):
        position = {
            "side": "COMPRA",
            "entry_price": 100.0,
            "stop_loss": 99.0,
            "take_profit": 102.0,
            "entry_tick": 1,
            "position_size": 100.0,
            "regime": "TENDENCIA_ALTA",
            "engine": "TrendFollowing",
            "confidence": 0.8,
        }
        trade = {
            "symbol": "USD",
            "side": "COMPRA",
            "entry_price": 100.0,
            "exit_price": 101.0,
            "pnl": 1.0,
            "duration_ticks": 2,
            "reason": "PANIC_CLOSE",
        }

        monkeypatch.setattr(
            app_module.position_manager,
            "positions_to_dict",
            lambda: {"USD": position},
        )
        monkeypatch.setattr(
            app_module,
            "_latest_cotacao",
            lambda symbol: {"preco": 101.0, "regime": "TENDENCIA_ALTA"},
        )
        monkeypatch.setattr(
            app_module.position_manager,
            "close_position",
            lambda **kwargs: trade,
        )
        monkeypatch.setattr(
            app_module.equity_manager, "update_equity", lambda pnl: None
        )
        monkeypatch.setattr(
            app_module.risk_controller, "close_position", lambda symbol: None
        )
        monkeypatch.setattr(
            app_module.kpi_tracker, "record_trade_result", lambda t: None
        )
        monkeypatch.setattr(app_module, "salvar_trade_history", lambda t: None)
        monkeypatch.setattr(app_module, "persist_state", lambda: None)

        response = client.post("/api/positions/close-all", json={})
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["closed_count"] == 1
        assert body["closed"][0]["reason"] == "PANIC_CLOSE"

    def test_status_endpoint(self, client):
        response = client.get("/api/status")
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert "monitor_running" in body
        assert "equity" in body
        assert body["ml"]["mode"] in ("model", "heuristic")

    def test_live_endpoint_structure(self, client):
        response = client.get("/api/live")
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        symbols = [card["symbol"] for card in body["symbols"]]
        assert symbols == ["USD", "BTC", "ETH", "SOL"]
        assert "kpis" in body
        assert "recent_trades" in body


# ============================================================================
# API — MACHINE LEARNING
# ============================================================================

class TestMlApi:
    def test_ml_status(self, client):
        response = client.get("/api/ml/status")
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["mode"] in ("model", "heuristic")
        assert "threshold" in body

    def test_ml_train_returns_metrics(self, client, monkeypatch):
        class FakeTrainer:
            def train_model(self):
                return {
                    "test_score": 0.71,
                    "samples_trained": 50,
                    "samples_tested": 12,
                    "n_features": 16,
                }

        class FakeClassifier:
            threshold = 0.58

            def reload_model(self):
                return True

        import monitor

        monkeypatch.setattr(app_module, "MLTrainer", FakeTrainer)
        monkeypatch.setattr(app_module, "classifier", FakeClassifier())
        monkeypatch.setattr(monitor, "save_json_report", lambda *a, **k: None)

        response = client.post("/api/ml/train", json={})
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["model_loaded"] is True
        assert body["metrics"]["test_score"] == pytest.approx(0.71)

    def test_ml_train_conflict_returns_409(self, client):
        assert app_module._ml_training_lock.acquire(blocking=False)
        try:
            response = client.post("/api/ml/train", json={})
            assert response.status_code == 409
        finally:
            app_module._ml_training_lock.release()


# ============================================================================
# API — LOGS
# ============================================================================

class TestLogsApi:
    def _write_log(self, tmp_path, lines):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "trading.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        return log_dir

    def test_logs_returns_entries(self, client, monkeypatch, tmp_path):
        log_dir = self._write_log(
            tmp_path,
            [
                "2026-01-01 10:00:00 - monitor - INFO - começou",
                "2026-01-01 10:00:01 - monitor - WARNING - atenção",
                "2026-01-01 10:00:02 - monitor - ERROR - falhou",
            ],
        )
        monkeypatch.setattr(config, "LOG_DIR", log_dir)

        response = client.get("/api/logs?lines=10")
        assert response.status_code == 200
        body = response.get_json()
        assert body["count"] == 3
        assert [entry["level"] for entry in body["entries"]] == [
            "INFO",
            "WARNING",
            "ERROR",
        ]

    def test_logs_level_filter(self, client, monkeypatch, tmp_path):
        log_dir = self._write_log(
            tmp_path,
            [
                "2026-01-01 10:00:00 - monitor - INFO - começou",
                "2026-01-01 10:00:01 - monitor - WARNING - atenção",
                "2026-01-01 10:00:02 - monitor - ERROR - falhou",
            ],
        )
        monkeypatch.setattr(config, "LOG_DIR", log_dir)

        response = client.get("/api/logs?level=WARNING&lines=10")
        body = response.get_json()
        assert body["count"] == 2
        assert {entry["level"] for entry in body["entries"]} == {
            "WARNING",
            "ERROR",
        }

    def test_logs_search_filter(self, client, monkeypatch, tmp_path):
        log_dir = self._write_log(
            tmp_path,
            [
                "2026-01-01 10:00:00 - monitor - INFO - sinal USD",
                "2026-01-01 10:00:01 - monitor - INFO - sinal BTC",
            ],
        )
        monkeypatch.setattr(config, "LOG_DIR", log_dir)

        response = client.get("/api/logs?search=btc")
        body = response.get_json()
        assert body["count"] == 1
        assert "BTC" in body["entries"][0]["message"]

    def test_logs_invalid_level(self, client):
        response = client.get("/api/logs?level=TRACE")
        assert response.status_code == 400

    def test_logs_invalid_lines(self, client):
        response = client.get("/api/logs?lines=abc")
        assert response.status_code == 400

    def test_logs_specific_file_rejects_traversal(self, client):
        response = client.get("/api/logs?file=../secret.log")
        assert response.status_code == 400
