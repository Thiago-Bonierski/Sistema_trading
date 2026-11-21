"""
Controle visual do ML e integridade do score persistento na entrada.

Cobre:
- ml_score da abertura preservado em qualquer motivo de fechamento;
- endpoint POST /api/ml/toggle com validação de modelo válido;
- parâmetros booleanos no runtime_config.
"""

import copy
import types

import pytest

import app as app_module
import config
import simular
from equity import EquityManager
from position_manager import PositionManager
from risk_control import RiskController
from runtime_config import (
    ConfigValidationError,
    PARAMETER_GUIDANCE,
    PARAMETER_SPECS,
    RuntimeConfigManager,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def manager(tmp_path):
    module = types.SimpleNamespace(
        **{
            spec.key: copy.deepcopy(getattr(config, spec.key))
            for spec in PARAMETER_SPECS
        }
    )
    isolated = RuntimeConfigManager(
        tmp_path / "runtime_config.json", config_module=module
    )
    return isolated, module


class _FakeClassifier:
    threshold = 0.58
    shadow_mode = True

    def reload_model(self):
        return True


@pytest.fixture
def client(monkeypatch, manager, tmp_path):
    isolated, _ = manager
    monkeypatch.setattr(app_module, "runtime_config", isolated)
    monkeypatch.setattr(app_module, "classifier", _FakeClassifier())

    reports_dir = tmp_path / "simulation_reports"
    reports_dir.mkdir()
    monkeypatch.setattr(config, "SIMULATION_REPORTS_DIR", reports_dir)
    monkeypatch.setattr(simular, "salvar_trade", lambda *a, **k: None)

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


# ============================================================================
# (a) PRESERVAÇÃO DO ml_score DE ENTRADA
# ============================================================================

def _open_position(manager, *, score):
    return manager.open_position(
        symbol="USD",
        side="COMPRA",
        price=100.0,
        regime="CONSOLIDACAO",
        engine="MeanReversion",
        confidence=0.72,
        details="preco abaixo da media",
        entry_tick=10,
        regime_metrics={"slope": 0.0, "momentum": -0.001},
        ml_score=score,
    )


class TestMlScoreDeEntrada:
    @pytest.mark.parametrize("reason", ["regime_risk", "max_age"])
    def test_close_position_preserva_score(self, reason):
        manager = PositionManager(
            equity_manager=EquityManager(initial_capital=10000),
            risk_controller=RiskController(),
            symbol="USD",
        )
        position = _open_position(manager, score=0.73)
        assert position is not None
        assert position.ml_score == pytest.approx(0.73)

        result = manager.close_position("USD", 101.0, "TRANSICAO", reason)

        assert result is not None
        assert result["reason"] == reason
        assert result["ml_score"] == pytest.approx(0.73)

    def test_estado_persistido_roundtrip_mantem_score(self):
        manager = PositionManager(symbol="USD")
        position = _open_position(manager, score=0.8123)

        restored = type(position).from_dict(position.to_dict())
        assert restored.ml_score == pytest.approx(0.8123)

    def test_relatorio_da_simulacao_usa_score_da_abertura(self, monkeypatch, tmp_path):
        # A simulação precisa gerar trades: o runtime_config.json local pode ter
        # ML_SHADOW_MODE=false (toggle feito pelo painel), o que bloquearia as
        # entradas e deixaria `captured` vazio.
        monkeypatch.setattr(config, "ML_SHADOW_MODE", True, raising=False)
        captured = []
        real_close = PositionManager.close_position

        def spy(self, symbol, exit_price, exit_regime, reason):
            result = real_close(self, symbol, exit_price, exit_regime, reason)
            if result:
                captured.append(result)
            return result

        monkeypatch.setattr(PositionManager, "close_position", spy)
        monkeypatch.setattr(simular, "salvar_trade", lambda *a, **k: None)
        reports_dir = tmp_path / "simulation_reports"
        reports_dir.mkdir()
        monkeypatch.setattr(config, "SIMULATION_REPORTS_DIR", reports_dir)

        bundle = simular.run_dual_simulation(
            ticks=5000,
            seed=42,
            data_source="synthetic",
            save_report=False,
        )

        report_trades = (
            bundle["research"]["trades"] + bundle["paper_trading"]["trades"]
        )
        assert report_trades
        assert captured
        # Garante que o cenário que causava a regressão foi exercitado:
        # fechamento por regime_risk/max_age com score de entrada positivo.
        assert any(
            trade["reason"] in ("regime_risk", "max_age")
            and (trade.get("ml_score") or 0) > 0
            for trade in report_trades
        )

        for trade in report_trades:
            matches = [
                item
                for item in captured
                if item["entry_tick"] == trade["entry_tick"]
                and item["exit_tick"] == trade["exit_tick"]
                and item["engine"] == trade["engine"]
            ]
            assert matches, trade
            assert trade["ml_score"] == matches[0]["ml_score"]


# ============================================================================
# (b) ENDPOINT /api/ml/toggle
# ============================================================================

def _status(monkeypatch, *, usable, shadow, reason=None):
    monkeypatch.setattr(
        app_module,
        "_ml_status_payload",
        lambda: {
            "usable": usable,
            "shadow_mode": shadow,
            "disabled_reason": reason,
        },
    )


class TestMlToggleApi:
    def test_bloqueia_ativacao_sem_modelo_valido(self, client, monkeypatch):
        _status(monkeypatch, usable=False, shadow=True, reason="degenerate_scores")

        response = client.post("/api/ml/toggle", json={"enabled": True})

        assert response.status_code == 400
        body = response.get_json()
        assert body["ok"] is False
        assert "modelo" in body["error"].lower()
        assert body["enabled"] is False

    def test_permite_ativacao_com_modelo_aceito(self, client, monkeypatch):
        _status(monkeypatch, usable=True, shadow=True)

        response = client.post("/api/ml/toggle", json={"enabled": True})

        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["enabled"] is True
        assert body["shadow_mode"] is False
        assert app_module.runtime_config.get_value("ML_SHADOW_MODE") is False
        assert app_module.classifier.shadow_mode is False

    def test_desativacao_volta_para_shadow(self, client, monkeypatch):
        _status(monkeypatch, usable=True, shadow=False)

        response = client.post("/api/ml/toggle", json={"enabled": False})

        assert response.status_code == 200
        assert response.get_json()["shadow_mode"] is True
        assert app_module.runtime_config.get_value("ML_SHADOW_MODE") is True

    def test_toggle_sem_payload_alterna_estado(self, client, monkeypatch):
        _status(monkeypatch, usable=True, shadow=True)

        response = client.post("/api/ml/toggle", json={})

        assert response.status_code == 200
        assert response.get_json()["enabled"] is True

    def test_payload_invalido_retorna_400(self, client, monkeypatch):
        _status(monkeypatch, usable=True, shadow=True)

        response = client.post("/api/ml/toggle", json={"enabled": "talvez"})

        assert response.status_code == 400


# ============================================================================
# (c) BOOLEANOS NO RUNTIME CONFIG
# ============================================================================

class TestParametrosBooleanos:
    def test_padrao_fabrica_mantem_filtro_ml_ativo(self):
        assert config.ML_SHADOW_MODE is False

    def test_spec_boolean_existe_com_metadados(self):
        spec = next(
            item for item in PARAMETER_SPECS if item.key == "ML_SHADOW_MODE"
        )
        assert spec.kind == "bool"
        assert spec.description
        assert "ML_SHADOW_MODE" in PARAMETER_GUIDANCE

    def test_update_aceita_bool_e_texto(self, manager):
        isolated, _ = manager

        assert isolated.update({"ML_SHADOW_MODE": False})[
            "values"
        ]["ML_SHADOW_MODE"] is False
        assert isolated.update({"ML_SHADOW_MODE": "true"})[
            "values"
        ]["ML_SHADOW_MODE"] is True
        assert isolated.update({"ML_SHADOW_MODE": "nao"})[
            "values"
        ]["ML_SHADOW_MODE"] is False

    def test_update_rejeita_valor_nao_booleano(self, manager):
        isolated, _ = manager

        with pytest.raises(ConfigValidationError):
            isolated.update({"ML_SHADOW_MODE": 1})

    def test_snapshot_expõe_tipo_e_recomendacao(self, manager):
        isolated, _ = manager
        ml_category = next(
            category
            for category in isolated.get_snapshot()["categories"]
            if category["key"] == "ml"
        )
        spec = next(
            item
            for item in ml_category["parameters"]
            if item["key"] == "ML_SHADOW_MODE"
        )

        assert spec["type"] == "bool"
        assert spec["guidance"]["recommended"]
        assert spec["guidance"]["impact_up"]
        assert spec["guidance"]["impact_down"]
