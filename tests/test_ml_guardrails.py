"""
Testes dos guardrails do filtro ML.

Regra de ouro: um artefato degenerado/legado NUNCA pode bloquear entradas.
Ele deve operar em shadow mode, telemetrando o score sem neutralizar o sinal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import pytest

import config
import ml_classifier
from core.contracts import MarketEvent
from core.pipeline import DecisionPipeline, TrendConfirmationTracker
from features import FEATURE_COLUMNS, build_training_frame, deduplicate_trades


class _FakeModel:
    """Pipeline mínimo com a interface usada pelo classificador."""

    n_features_in_ = 8

    def predict_proba(self, X):
        n = len(X)
        return np.tile([0.4, 0.6], (n, 1))


def _accepted_metadata():
    return {
        "status": "accepted",
        "auc_oos": 0.61,
        "auc_ci_low": 0.53,
        "unique_train_scores": 42,
        "approval_rate_at_threshold": 0.35,
        "feature_schema_version": config.ML_FEATURE_SCHEMA_VERSION,
    }


def _degenerate_metadata():
    return {
        "status": "rejected",
        "auc_oos": 0.48,
        "auc_ci_low": 0.40,
        "unique_train_scores": 2,
        "approval_rate_at_threshold": 0.0,
        "feature_schema_version": config.ML_FEATURE_SCHEMA_VERSION,
    }


def _dump_model(path: Path, metadata=None):
    import joblib

    if metadata is None:
        payload = _FakeModel()
    else:
        payload = {"pipeline": _FakeModel(), "metadata": metadata}
    joblib.dump(payload, str(path))
    return path


def _suggestion():
    return {
        "action": "COMPRA",
        "confidence": 0.82,
        "engine": "TrendFollowing",
        "regime_metrics": {
            "regime": "TENDENCIA_ALTA",
            "slope": 0.01,
            "momentum": 0.02,
            "range_rel": 0.003,
            "volatility_ratio": 1.1,
        },
    }


class TestClassificadorGuardrails:
    def test_artefato_legado_nao_e_utilizavel(self, tmp_path):
        path = _dump_model(tmp_path / "legacy.joblib", metadata=None)
        clf = ml_classifier.MLClassifier(
            model_path=path, threshold=0.58, shadow_mode=False
        )

        assert clf.is_trained() is True
        assert clf.is_usable() is False
        assert "legacy_model_without_validation" in clf.disabled_reason

        filtrado = clf.filter_signal(_suggestion(), _suggestion()["regime_metrics"])
        assert filtrado["action"] == "COMPRA"
        assert filtrado["ml_shadow"] is True
        assert "ml_score" in filtrado

    def test_modelo_degenerado_nao_bloqueia(self, tmp_path):
        path = _dump_model(
            tmp_path / "degenerado.joblib", metadata=_degenerate_metadata()
        )
        clf = ml_classifier.MLClassifier(
            model_path=path, threshold=0.58, shadow_mode=False
        )

        assert clf.is_trained() is True
        assert clf.is_usable() is False
        assert "model_rejected_by_training" in clf.disabled_reason
        assert "degenerate_scores" in clf.disabled_reason
        assert "threshold_unreachable" in clf.disabled_reason

        filtrado = clf.filter_signal(_suggestion(), _suggestion()["regime_metrics"])
        assert filtrado["action"] == "COMPRA"
        assert filtrado["ml_shadow"] is True

    def test_modelo_validado_pode_bloquear(self, tmp_path):
        path = _dump_model(
            tmp_path / "aceito.joblib", metadata=_accepted_metadata()
        )
        clf = ml_classifier.MLClassifier(
            model_path=path, threshold=0.70, shadow_mode=False
        )

        assert clf.is_usable() is True
        filtrado = clf.filter_signal(_suggestion(), _suggestion()["regime_metrics"])
        # score sintético = 0.6 < 0.70 -> reprovado
        assert filtrado["action"] == "NEUTRO"
        assert "Filtrado por ML" in filtrado["reason"]

    def test_shadow_mode_global_nao_bloqueia(self, tmp_path):
        path = _dump_model(
            tmp_path / "aceito_shadow.joblib", metadata=_accepted_metadata()
        )
        clf = ml_classifier.MLClassifier(
            model_path=path, threshold=0.70, shadow_mode=True
        )

        assert clf.is_usable() is True
        filtrado = clf.filter_signal(_suggestion(), _suggestion()["regime_metrics"])
        assert filtrado["action"] == "COMPRA"
        assert filtrado["ml_shadow"] is True


class _FakeClassifier:
    """Classificador sem validação: deve ser observado, não aplicado."""

    threshold = 0.58
    shadow_mode = True
    disabled_reason = "legacy_model_without_validation"

    def is_trained(self):
        return True

    def is_usable(self):
        return False

    def filter_signal(self, suggestion, regime_metrics):
        filtrado = dict(suggestion)
        filtrado["ml_score"] = 0.99
        filtrado["ml_shadow"] = True
        return filtrado


class _FakeOrchestrator:
    def evaluate(self, **kwargs):
        return {
            "action": "COMPRA",
            "confidence": 0.82,
            "engine": "TrendFollowing",
            "details": "fake",
        }


class _FakePositionManager:
    def get_position(self, symbol):
        return None

    def evaluate(self, **kwargs):
        return {"action": "COMPRA", "event": "ENTRY", "position": None}


class _FakeRiskController:
    def register_trade(self, *args, **kwargs):
        return None

    def close_position(self, *args, **kwargs):
        return None

    def reset_regime_counts(self, *args, **kwargs):
        return None


class TestPipelineNaoBloqueia:
    def test_classificador_sem_validacao_nao_neutraliza_entrada(self):
        pipeline = DecisionPipeline(
            orchestrator=_FakeOrchestrator(),
            position_manager=_FakePositionManager(),
            risk_controller=_FakeRiskController(),
            classifier=_FakeClassifier(),
            check_exhaustion=lambda **kwargs: (False, ""),
            trend_tracker=TrendConfirmationTracker(
                counts={"SIM": 5}, last_regime={"SIM": "TENDENCIA_ALTA"}
            ),
            update_drawdown=False,
            reset_regime_counts=False,
            apply_ml=True,
        )

        event = MarketEvent(
            symbol="SIM",
            price=100.0,
            prices=[100.0, 99.5, 99.0],
            regime="TENDENCIA_ALTA",
            regime_metrics={"regime": "TENDENCIA_ALTA", "slope": 0.01},
        )
        result = pipeline.process(event)

        assert result.action == "COMPRA"
        assert result.blocked_by is None
        assert result.filter_details["ml"]["applied"] is False
        assert (
            result.filter_details["ml"]["reason"]
            == "legacy_model_without_validation"
        )


class TestDeduplicacaoFeatures:
    def _frame(self, n=2):
        base = {
            "symbol": "USD",
            "side": "COMPRA",
            "entry_price": 100.0,
            "exit_price": 101.0,
            "entry_tick": 1,
            "exit_tick": 11,
            "entry_regime": "TENDENCIA_ALTA",
            "engine": "TrendFollowing",
            "confidence": 0.82,
            "pnl": 10.0,
            "slope": 0.01,
            "momentum": 0.02,
            "range_rel": 0.003,
            "volatility_ratio": 1.1,
        }
        return pd.DataFrame([base for _ in range(n)])

    def test_deduplicacao_colapsa_execucoes_identicas(self):
        df = self._frame(n=5)
        deduped = deduplicate_trades(df)
        assert len(deduped) == 1

    def test_schema_completo_mantem_ordem_do_contrato(self):
        X, y = build_training_frame(
            self._frame(n=3),
            require_complete_features=True,
            deduplicate=True,
            min_samples=1,
        )
        assert len(X) == 1
        assert list(X.columns) == FEATURE_COLUMNS
        assert y.tolist() == [1]

    def test_schema_incompleto_falha_alto(self):
        df = self._frame(n=3).drop(columns=["slope", "momentum"])
        with pytest.raises(ValueError, match="Schema de features incompleto"):
            build_training_frame(df, require_complete_features=True)
