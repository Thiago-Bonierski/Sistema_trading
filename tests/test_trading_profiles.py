"""
Testes dos perfis predefinidos de calibragem.

Garante que:
- todo perfil é aceito pelo RuntimeConfigManager (tipos, limites,
  consistência MIN/MAX);
- custos de execução nunca são alterados por perfil;
- os extremos (máximo lucro x proteção de capital) são realmente opostos;
- a API expõe os perfis e eles chegam ao snapshot via POST /api/config.
"""

import copy
import json
import types

import pytest

import app as app_module
import config
from runtime_config import PARAMETER_SPECS, RuntimeConfigManager
from trading_profiles import (
    PROTECTED_KEYS,
    TRADING_PROFILES,
    profiles_payload,
    validate_profiles,
)


@pytest.fixture
def isolated_manager(tmp_path):
    module = types.SimpleNamespace(
        **{
            spec.key: copy.deepcopy(getattr(config, spec.key))
            for spec in PARAMETER_SPECS
        }
    )
    return RuntimeConfigManager(
        tmp_path / "runtime_config.json",
        config_module=module,
    )


@pytest.fixture
def client(monkeypatch, isolated_manager):
    monkeypatch.setattr(app_module, "runtime_config", isolated_manager)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def profile_by_id(profile_id):
    return next(profile for profile in TRADING_PROFILES if profile.id == profile_id)


# ============================================================================
# DEFINIÇÃO DOS PERFIS
# ============================================================================

def test_all_profiles_validate_against_isolated_manager(isolated_manager):
    validate_profiles(isolated_manager)
    for profile in TRADING_PROFILES:
        validated = isolated_manager.validate(profile.values, use_defaults=True)
        assert set(validated) == set(profile.values)


def test_payload_is_strict_json_with_complete_metadata():
    payload = profiles_payload()
    json.dumps(payload, allow_nan=False)

    assert payload["preserves_other_parameters"] is True
    assert len(payload["profiles"]) == len(TRADING_PROFILES)

    required = {
        "id",
        "name",
        "tagline",
        "description",
        "risk",
        "icon",
        "tone",
        "upside",
        "downside",
        "highlights",
        "values",
        "reset",
    }
    for serialized in payload["profiles"]:
        assert required <= set(serialized)
        assert serialized["risk"] in {"baixo", "medio", "alto"}
        assert serialized["parameter_count"] == len(serialized["values"])


def test_ids_unique_and_both_risk_extremes_exist():
    ids = [profile.id for profile in TRADING_PROFILES]
    assert len(ids) == len(set(ids))
    risks = {profile.risk for profile in TRADING_PROFILES}
    assert {"baixo", "alto"} <= risks

    balanced = profile_by_id("balanced")
    assert balanced.reset is True
    assert balanced.values == {}


def test_profiles_never_override_execution_costs():
    for profile in TRADING_PROFILES:
        assert not PROTECTED_KEYS & profile.values.keys()


def test_aggressive_and_capital_guard_are_real_opposites():
    aggressive = profile_by_id("aggressive").values
    guard = profile_by_id("capital_guard").values

    assert aggressive["BASE_POSITION_SIZE_PCT"] > guard["BASE_POSITION_SIZE_PCT"]
    assert aggressive["DEFAULT_STOP_LOSS_PCT"] > guard["DEFAULT_STOP_LOSS_PCT"]
    assert aggressive["DEFAULT_TAKE_PROFIT_PCT"] > guard["DEFAULT_TAKE_PROFIT_PCT"]
    assert aggressive["EQUITY_DRAWDOWN_LIMIT"] > guard["EQUITY_DRAWDOWN_LIMIT"]
    assert aggressive["DAILY_LOSS_LIMIT"] > guard["DAILY_LOSS_LIMIT"]
    assert aggressive["GLOBAL_TRADE_LIMIT"] > guard["GLOBAL_TRADE_LIMIT"]
    assert aggressive["MIN_CONFIDENCE_FACTOR"] < guard["MIN_CONFIDENCE_FACTOR"]
    assert aggressive["ML_APPROVAL_THRESHOLD"] < guard["ML_APPROVAL_THRESHOLD"]


# ============================================================================
# API
# ============================================================================

def test_profiles_endpoint(client):
    response = client.get("/api/config/profiles")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    names = [profile["name"] for profile in body["profiles"]]
    assert "Máximo Lucro" in names
    assert "Proteção de Capital" in names


def test_applying_profile_via_config_endpoint(client):
    profile = profile_by_id("capital_guard")

    response = client.post("/api/config", json={"values": profile.values})
    assert response.status_code == 200

    snapshot = client.get("/api/config").get_json()
    assert snapshot["values"]["BASE_POSITION_SIZE_PCT"] == pytest.approx(0.02)
    assert snapshot["values"]["ML_SHADOW_MODE"] is False
    assert snapshot["values"]["ML_APPROVAL_THRESHOLD"] == pytest.approx(0.70)
    assert "BASE_POSITION_SIZE_PCT" in snapshot["overrides"]
