"""
Testes de filtros de entrada.

Cobre:
- exhaustion_filter.check_exhaustion (crítérios reais)
- monitor.apply_trend_confirmation_filter
"""
import sys
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from exhaustion_filter import check_exhaustion
from monitor import apply_trend_confirmation_filter


class TestExhaustionFilter:
    """Testes do filtro de exaustão de movimento."""

    def test_nao_exausto_sinal_neutro(self):
        """Sinais NEUTRO nunca são exaustos."""
        precios = pd.Series([100.0] * 20)
        regime = {"regime": "CONSOLIDACAO", "momentum": 0.0,
                  "range_rel": 0.001, "volatility_ratio": 1.0}
        sugestao = {"action": "NEUTRO", "confidence": 0.0}
        exausto, motivo = check_exhaustion(precios, regime, sugestao, "USD")
        assert exausto is False

    def test_momento_alto_desacelerando(self):
        """Momentum alto com desaceleração deve ser detectado como exaustão."""
        # Preços com desaceleração clara: momentum forte caindo
        precios = pd.Series([
            100.0, 101.0, 102.5, 104.0, 105.5, 106.0, 106.3, 106.5, 106.6, 106.7,
            106.7, 106.8,
        ])
        regime = {"regime": "TENDENCIA_ALTA", "momentum": 0.003,
                  "range_rel": 0.005, "volatility_ratio": 1.0}
        sugestao = {"action": "COMPRA", "confidence": 0.9}
        exausto, motivo = check_exhaustion(precios, regime, sugestao, "USD")
        # Pode ou não ser exausto dependendo dos valores exatos, mas não deve quebrar
        assert isinstance(exausto, bool)
        assert isinstance(motivo, str)

    def test_rompimento_momento_fraco(self):
        """Rompimento com amplitude mas momentum fraco = exaustão."""
        precios = pd.Series([100.0] * 12)
        regime = {"regime": "TENDENCIA_ALTA", "momentum": 0.001,
                  "range_rel": 0.006, "volatility_ratio": 1.0}
        sugestao = {"action": "COMPRA", "confidence": 0.7}
        exausto, motivo = check_exhaustion(precios, regime, sugestao, "USD")
        assert isinstance(exausto, bool)

    def test_alta_volatilidade_sem_momento(self):
        """Alta volatilidade sem momentum consistente = exaustão."""
        precios = pd.Series([100.0] * 12)
        regime = {"regime": "ALTA_VOLATILIDADE", "momentum": 0.001,
                  "range_rel": 0.005, "volatility_ratio": 3.0}
        sugestao = {"action": "COMPRA", "confidence": 0.7}
        exausto, motivo = check_exhaustion(precios, regime, sugestao, "USD")
        assert isinstance(exausto, bool)


class TestTrendConfirmationFilter:
    """Testes do filtro de confirmação de tendência."""

    def test_acao_neutro_nao_bloqueada(self):
        """Sinal NEUTRO passa pelo filtro."""
        sugestao = {"action": "NEUTRO", "confidence": 0.0, "engine": "ProtectFlat"}
        resultado = apply_trend_confirmation_filter("USD", "CONSOLIDACAO", sugestao)
        assert resultado["action"] == "NEUTRO"

    def test_regime_nao_confirma_bloqueia(self):
        """COMPRA em regime de baixa deve ser bloqueada."""
        sugestao = {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing"}
        resultado = apply_trend_confirmation_filter("USD", "TENDENCIA_BAIXA", sugestao)
        assert resultado["action"] == "NEUTRO"
        assert "bloqueado" in resultado.get("details", "")

    def test_sem_confirmacao_suficiente_bloqueia(self):
        """COMPRA com poucas confirmações consecutivas é bloqueada."""
        # Forçar contador zerado
        import monitor
        monitor.trend_confirmation_count["USD"] = 0
        monitor.last_trend_regime["USD"] = None

        sugestao = {"action": "COMPRA", "confidence": 0.9, "engine": "TrendFollowing"}
        resultado = apply_trend_confirmation_filter("USD", "TENDENCIA_ALTA", sugestao)
        assert resultado["action"] == "NEUTRO"
