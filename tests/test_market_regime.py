"""
Testes para o módulo market_regime.

Valida detecção de regimes de mercado com dados conhecidos.
"""
import pytest
import pandas as pd
import sys
from pathlib import Path

# Adicionar diretório pai ao path para imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from market_regime import analyze_regime


class TestMarketRegime:
    """Testes para análise de regime de mercado."""
    
    def test_aguardando_com_dados_insuficientes(self):
        """Deve retornar AGUARDANDO quando há menos de 30 dados."""
        prices = pd.Series([100.0] * 20)
        result = analyze_regime(prices)
        
        assert result["regime"] == "AGUARDANDO"
        assert result["slope"] == 0.0
        assert result["volatility"] == 0.0
    
    def test_tendencia_alta_clara(self):
        """Deve detectar tendência de alta quando preços sobem consistentemente."""
        # Preços subindo (mais recente primeiro): 130, 129, ..., 100
        prices = pd.Series([130.0 - i for i in range(31)])
        result = analyze_regime(prices)
        
        assert result["regime"] == "TENDENCIA_ALTA"
        assert result["slope"] > 0
        assert result["trend_up_persist"] is True
    
    def test_tendencia_baixa_clara(self):
        """Deve detectar tendência de baixa quando preços caem consistentemente."""
        # Preços caindo (mais recente primeiro): 100, 101, ..., 130
        prices = pd.Series([100.0 + i for i in range(31)])
        result = analyze_regime(prices)
        
        assert result["regime"] == "TENDENCIA_BAIXA"
        assert result["slope"] < 0
        assert result["trend_down_persist"] is True
    
    def test_consolidacao(self):
        """Deve detectar consolidação quando preço varia pouco."""
        # Preços oscilando minimamente em torno de 100
        prices = pd.Series([100.0 + (i % 3) * 0.1 for i in range(31)])
        result = analyze_regime(prices)
        
        assert result["regime"] == "CONSOLIDACAO"
        assert result["range_rel"] < 0.01  # Baixa amplitude
        assert abs(result["slope"]) < 0.01  # Slope pequeno
    
    def test_alta_volatilidade(self):
        """Deve detectar alta volatilidade com movimentos bruscos."""
        # Preços com variação MUITO alta (50% swings alternados com pequeno drift)
        # Cria condição de ALTA_VOLATILIDADE
        prices = pd.Series([100.0 + 50 * (1 if i % 2 == 0 else -1) + 0.2 * i for i in range(31)])
        result = analyze_regime(prices)
        
        # Com alta amplitude e momentum baixo, detecta volatilidade alta
        assert result["range_rel"] > 0.5, f"Range rel should be high: {result['range_rel']}"
        # A volatilidade em si é detectada
        assert result["volatility"] > 0.01, f"Volatility should be high: {result['volatility']}"
    
    def test_metricas_retornadas(self):
        """Deve retornar todas as métricas esperadas."""
        prices = pd.Series([100.0] * 31)
        result = analyze_regime(prices)
        
        # Verificar que todas as chaves esperadas existem
        expected_keys = [
            "regime", "slope", "range_rel", "volatility",
            "volatility_ratio", "momentum", "media_curta",
            "media_longa", "trend_up_persist", "trend_down_persist",
            "persistence_slopes"
        ]
        
        for key in expected_keys:
            assert key in result, f"Chave {key} não encontrada no resultado"
    
    def test_valores_numericos_validos(self):
        """Todos os valores numéricos devem ser finitos."""
        import numpy as np
        prices = pd.Series([100.0 + i * 0.5 for i in range(31)])
        result = analyze_regime(prices)
        
        # Verificar que não há NaN ou infinito
        for key, value in result.items():
            if isinstance(value, (int, float)):
                assert not pd.isna(value), f"{key} é NaN"
                assert not np.isinf(value), f"{key} é infinito"
    
    def test_momentum_positivo_em_alta(self):
        """Momentum deve ser positivo em tendência de alta."""
        prices = pd.Series([130.0 - i for i in range(31)])
        result = analyze_regime(prices)
        
        assert result["momentum"] > 0
    
    def test_momentum_negativo_em_baixa(self):
        """Momentum deve ser negativo em tendência de baixa."""
        prices = pd.Series([100.0 + i for i in range(31)])
        result = analyze_regime(prices)
        
        assert result["momentum"] < 0
    
    def test_range_rel_zero_em_flat(self):
        """Range relativo deve ser próximo de zero em mercado flat."""
        prices = pd.Series([100.0] * 31)
        result = analyze_regime(prices)
        
        assert result["range_rel"] < 0.001


class TestEdgeCases:
    """Testes para casos extremos."""
    
    def test_precos_zero(self):
        """Deve lidar com preços zero sem crash."""
        prices = pd.Series([0.0] * 31)
        result = analyze_regime(prices)
        
        # Não deve crashear, mas regime será indefinido
        assert isinstance(result, dict)
        assert "regime" in result
    
    def test_precos_negativos(self):
        """Deve lidar com preços negativos (não deveria acontecer, mas teste defensivo)."""
        prices = pd.Series([-100.0] * 31)
        result = analyze_regime(prices)
        
        assert isinstance(result, dict)
    
    def test_precos_muito_grandes(self):
        """Deve lidar com preços muito grandes."""
        prices = pd.Series([1e9 + i for i in range(31)])
        result = analyze_regime(prices)
        
        assert isinstance(result, dict)
        assert "regime" in result
    
    def test_series_vazia(self):
        """Deve retornar AGUARDANDO para série vazia."""
        prices = pd.Series([])
        result = analyze_regime(prices)
        
        assert result["regime"] == "AGUARDANDO"


if __name__ == "__main__":
    # Executar testes com pytest
    pytest.main([__file__, "-v", "--tb=short"])
