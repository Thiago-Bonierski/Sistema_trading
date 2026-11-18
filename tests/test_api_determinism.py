"""
Determinismo entre execuções consecutivas da simulação via API.

Regressão coberta: duas chamadas a ``POST /api/simulate`` com os mesmos
parâmetros, ``refresh=False`` e a mesma seed devem devolver relatórios
idênticos — inclusive ``ml_score``, funil de decisões e totais em centavos.

A causa raiz era o ``RandomForestClassifier(n_jobs=-1)``: a agregação das
probabilidades das árvores dependia do escalonamento de threads e variava
~1e-16 entre execuções com entradas bit a bit iguais.
"""

import copy
import json
import types

import pytest

import app as app_module
import config
import simular
from runtime_config import PARAMETER_SPECS, RuntimeConfigManager


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Client isolado: sem overrides reais, sem DB e sem relatórios reais."""
    module = types.SimpleNamespace(
        **{
            spec.key: copy.deepcopy(getattr(config, spec.key))
            for spec in PARAMETER_SPECS
        }
    )
    isolated = RuntimeConfigManager(
        tmp_path / "runtime_config.json", config_module=module
    )
    monkeypatch.setattr(app_module, "runtime_config", isolated)

    reports_dir = tmp_path / "simulation_reports"
    reports_dir.mkdir()
    monkeypatch.setattr(config, "SIMULATION_REPORTS_DIR", reports_dir)
    monkeypatch.setattr(simular, "salvar_trade", lambda *a, **k: None)

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def _stable_payload(body):
    """Remove somente carimbos temporais e caminhos de relatório."""
    stable = json.loads(json.dumps(body, default=str))
    stable.pop("generated_at", None)
    stable.pop("report_path", None)
    for mode in ("research", "paper_trading"):
        section = stable.get(mode) or {}
        for key in ("generated_at", "timestamp", "simulated_at", "report_path"):
            section.pop(key, None)
    return stable


def _payload(**overrides):
    payload = {
        "symbol": "USD",
        "source": "synthetic",
        "ticks": 400,
        "seed": 42,
        "capital": 10001,
        "refresh": False,
    }
    payload.update(overrides)
    return payload


def test_two_consecutive_api_simulations_are_identical(client):
    """Duas chamadas seguidas produzem exatamente o mesmo relatório."""
    first = client.post("/api/simulate", json=_payload())
    second = client.post("/api/simulate", json=_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["ok"] is True
    assert second.get_json()["ok"] is True

    a = _stable_payload(first.get_json())
    b = _stable_payload(second.get_json())
    assert a == b


def test_consecutive_runs_match_to_the_cent(client):
    """Totais monetários e scores são idênticos até os centavos."""
    first = client.post("/api/simulate", json=_payload()).get_json()
    second = client.post("/api/simulate", json=_payload()).get_json()

    for mode in ("research", "paper_trading"):
        a, b = first[mode], second[mode]
        for key in ("total_pnl", "final_equity", "total_return", "max_drawdown"):
            assert a.get(key) == b.get(key), (mode, key)

        a_scores = [t.get("ml_score") for t in a.get("trades", [])]
        b_scores = [t.get("ml_score") for t in b.get("trades", [])]
        assert a_scores == b_scores, mode


def test_exhaustion_cache_is_cleared_before_each_run(client, monkeypatch):
    """O cache global de exaustão é resetado no início de toda execução."""
    calls = []
    real_reset = simular.reset_exhaustion_state
    monkeypatch.setattr(
        simular,
        "reset_exhaustion_state",
        lambda *a, **k: calls.append(a) or real_reset(*a, **k),
    )

    client.post("/api/simulate", json=_payload())

    # Uma chamada pelo handler da API e uma por cada modo de simulação.
    assert len(calls) >= 3
