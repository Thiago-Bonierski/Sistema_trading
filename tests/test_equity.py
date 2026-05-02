"""
Testes para o módulo equity (EquityManager).

Valida cálculo de drawdown, retornos e gestão de capital.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from equity import EquityManager


class TestEquityManager:
    """Testes para o gerenciador de equity."""
    
    def test_inicializacao_com_capital_padrao(self):
        """Deve inicializar com capital padrão."""
        em = EquityManager()
        
        assert em.initial_capital == 100000.0
        assert em.current_equity == 100000.0
        assert em.peak_equity == 100000.0
        assert em.max_drawdown == 0.0
    
    def test_inicializacao_com_capital_customizado(self):
        """Deve inicializar com capital customizado."""
        em = EquityManager(initial_capital=50000.0)
        
        assert em.initial_capital == 50000.0
        assert em.current_equity == 50000.0
    
    def test_update_equity_com_lucro(self):
        """Deve atualizar equity corretamente com lucro."""
        em = EquityManager(initial_capital=100000.0)
        
        em.update_equity(5000.0)  # +5k
        
        assert em.current_equity == 105000.0
        assert em.peak_equity == 105000.0
        assert em.max_drawdown == 0.0  # Sem drawdown ainda
    
    def test_update_equity_com_prejuizo(self):
        """Deve atualizar equity corretamente com prejuízo."""
        em = EquityManager(initial_capital=100000.0)
        
        em.update_equity(-10000.0)  # -10k
        
        assert em.current_equity == 90000.0
        assert em.peak_equity == 100000.0
        assert em.max_drawdown == 0.10  # 10% drawdown
    
    def test_calculo_drawdown_maximo(self):
        """Deve calcular drawdown máximo corretamente."""
        em = EquityManager(initial_capital=100000.0)
        
        # Subir para 120k
        em.update_equity(20000.0)
        assert em.peak_equity == 120000.0
        
        # Cair para 90k (drawdown de 25% do pico)
        em.update_equity(-30000.0)
        
        assert em.current_equity == 90000.0
        assert em.max_drawdown == 0.25  # 25% DD
        
        # Recuperar parcialmente para 100k
        em.update_equity(10000.0)
        
        # Max drawdown deve permanecer 25%
        assert em.max_drawdown == 0.25
    
    def test_calculo_retorno_total(self):
        """Deve calcular retorno total corretamente."""
        em = EquityManager(initial_capital=100000.0)
        
        # Aumentar para 150k (+50%)
        em.update_equity(50000.0)
        
        assert em.get_total_return() == 0.5  # 50%
        
        # Reduzir para 80k (-20% do inicial)
        em.update_equity(-70000.0)
        
        assert em.get_total_return() == -0.2  # -20%
    
    def test_drawdown_atual_vs_maximo(self):
        """Deve distinguir drawdown atual de máximo."""
        em = EquityManager(initial_capital=100000.0)
        
        # Subir para 150k
        em.update_equity(50000.0)
        
        # Cair para 100k (DD de 33.33%)
        em.update_equity(-50000.0)
        assert abs(em.get_current_drawdown() - 0.3333) < 0.01
        
        # Recuperar para 140k (DD atual menor)
        em.update_equity(40000.0)
        current_dd = em.get_current_drawdown()
        max_dd = em.get_max_equity_drawdown()
        
        assert current_dd < max_dd
        assert abs(current_dd - 0.0666) < 0.01  # ~6.66%
        assert abs(max_dd - 0.3333) < 0.01      # Max permanece 33.33%
    
    def test_get_total_pnl(self):
        """Deve calcular PnL total absoluto."""
        em = EquityManager(initial_capital=100000.0)
        
        em.update_equity(15000.0)
        em.update_equity(-5000.0)
        
        assert em.get_total_pnl() == 10000.0
    
    def test_reset_equity(self):
        """Deve resetar equity para novo capital."""
        em = EquityManager(initial_capital=100000.0)
        
        # Fazer trades
        em.update_equity(20000.0)
        em.update_equity(-15000.0)
        
        # Reset
        em.reset()
        
        assert em.current_equity == 100000.0
        assert em.peak_equity == 100000.0
        assert em.max_drawdown == 0.0
        assert len(em.equity_history) == 1
    
    def test_reset_com_novo_capital(self):
        """Deve resetar com novo capital."""
        em = EquityManager(initial_capital=100000.0)
        
        em.update_equity(50000.0)
        em.reset(new_capital=200000.0)
        
        assert em.initial_capital == 200000.0
        assert em.current_equity == 200000.0
    
    def test_historico_equity(self):
        """Deve manter histórico de equity."""
        em = EquityManager(initial_capital=100000.0)
        
        em.update_equity(5000.0)
        em.update_equity(-3000.0)
        em.update_equity(8000.0)
        
        assert len(em.equity_history) == 4  # Inicial + 3 updates
        assert em.equity_history[0] == 100000.0
        assert em.equity_history[-1] == 110000.0
    
    def test_historico_pnl(self):
        """Deve manter histórico de PnLs."""
        em = EquityManager(initial_capital=100000.0)
        
        em.update_equity(5000.0)
        em.update_equity(-3000.0)
        
        assert len(em.pnl_history) == 2
        assert em.pnl_history[0] == 5000.0
        assert em.pnl_history[1] == -3000.0
    
    def test_get_summary(self):
        """Deve retornar resumo completo."""
        em = EquityManager(initial_capital=100000.0)
        
        em.update_equity(10000.0)
        em.update_equity(-5000.0)
        
        summary = em.get_summary()
        
        assert summary["initial_capital"] == 100000.0
        assert summary["current_equity"] == 105000.0
        assert summary["total_pnl"] == 5000.0
        assert summary["trade_count"] == 2
        assert "total_return_pct" in summary
        assert "max_drawdown_pct" in summary


class TestEdgeCases:
    """Testes para casos extremos."""
    
    def test_capital_inicial_zero(self):
        """Deve lidar com capital inicial zero."""
        em = EquityManager(initial_capital=0.0)
        
        assert em.get_total_return() == 0.0
        assert em.get_max_equity_drawdown() == 0.0
    
    def test_sequencia_apenas_perdas(self):
        """Deve lidar com sequência de apenas perdas."""
        em = EquityManager(initial_capital=100000.0)
        
        for _ in range(10):
            em.update_equity(-5000.0)
        
        assert em.current_equity == 50000.0
        assert em.max_drawdown == 0.5  # 50% DD
    
    def test_sequencia_apenas_ganhos(self):
        """Deve lidar com sequência de apenas ganhos."""
        em = EquityManager(initial_capital=100000.0)
        
        for _ in range(10):
            em.update_equity(5000.0)
        
        assert em.current_equity == 150000.0
        assert em.max_drawdown == 0.0  # Sem DD
        assert em.get_total_return() == 0.5  # +50%


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
