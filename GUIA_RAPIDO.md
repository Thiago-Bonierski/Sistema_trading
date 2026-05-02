# 🚀 Guia Rápido de Uso - Sistema Refatorado

## ✅ Arquivos Refatorados (Completos)

### Módulos Base
- ✅ **config.py** - Configurações centralizadas
- ✅ **database.py** - DB thread-safe
- ✅ **equity.py** - Gerenciamento de capital
- ✅ **logging_config.py** - Logging profissional

### Componentes Principais
- ✅ **market_regime.py** - Detecção de regimes (refatorado)
- ✅ **position_manager.py** - Gestão de posições (refatorado)
- ✅ **risk_control.py** - Controle de risco (refatorado)
- ✅ **monitor.py** - Loop principal (refatorado)

### Utilitários
- ✅ **utils/maintenance.py** - Limpeza de arquivos

### Testes
- ✅ **tests/test_market_regime.py** - 13 testes
- ✅ **tests/test_equity.py** - 15 testes

### Documentação
- ✅ **README.md** - Guia completo
- ✅ **requirements.txt** - Dependências
- ✅ **demo.py** - Demonstrações

---

## 📝 Arquivos Pendentes

### Alta Prioridade
- ⏳ **app.py** (138 linhas) - API Flask
- ⏳ **simular.py** (199 linhas) - Sistema de simulação

### Baixa Prioridade
- ⏳ **strategy_engines.py** (120 linhas)
- ⏳ **strategy_orchestrator.py** (43 linhas)
- ⏳ **ml_classifier.py** (88 linhas)
- ⏳ **ml_training.py** (81 linhas)
- ⏳ **kpis.py** (82 linhas)
- ⏳ **exhaustion_filter.py** (24 linhas)
- ⏳ **monitor_dolar.py** (55 linhas)

---

## 🎯 Como Usar Agora

### 1. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 2. Executar Demonstração
```bash
python demo.py
```

### 3. Executar Testes
```bash
# Todos os testes
pytest tests/ -v

# Com cobertura
pytest tests/ --cov=. --cov-report=html

# Teste específico
pytest tests/test_equity.py::TestEquityManager::test_update_equity_com_lucro -v
```

### 4. Rodar Manutenção
```bash
python utils/maintenance.py
```

### 5. Verificar Configurações
```python
import config

print(f"Stop-Loss: {config.DEFAULT_STOP_LOSS_PCT:.1%}")
print(f"Take-Profit: {config.DEFAULT_TAKE_PROFIT_PCT:.1%}")
print(f"DD Limit: {config.EQUITY_DRAWDOWN_LIMIT:.1%}")
```

### 6. Usar Novo Sistema de Logging
```python
from logging_config import setup_logging

logger = setup_logging("meu_modulo", "DEBUG")

logger.debug("Debug info")
logger.info("Informação importante")
logger.warning("Alerta")
logger.error("Erro", exc_info=True)
```

### 7. Conectar ao Banco (Thread-Safe)
```python
from database import db_manager

# Context manager (recomendado)
with db_manager.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cotacoes LIMIT 10")
    for row in cursor.fetchall():
        print(dict(row))

# Ou usar métodos de conveniência
from database import salvar_cotacao

salvar_cotacao(
    horario="14:30:00",
    preco=5.85,
    moeda="USD",
    recomendacao="COMPRA",
    regime="TENDENCIA_ALTA",
)
```

### 8. Usar EquityManager
```python
from equity import EquityManager, format_currency

em = EquityManager(initial_capital=100000.0)

# Simular trades
em.update_equity(5000.0)   # +R$ 5k
em.update_equity(-2000.0)  # -R$ 2k

# Consultar status
print(f"Equity: {format_currency(em.current_equity)}")
print(f"Retorno: {em.get_total_return():.1%}")
print(f"Drawdown: {em.get_current_drawdown():.1%}")
print(f"Max DD: {em.get_max_equity_drawdown():.1%}")

# Resumo completo
summary = em.get_summary()
print(summary)
```

### 9. Testar Detecção de Regime
```python
import pandas as pd
from market_regime import analyze_regime

# Preços em tendência de alta
prices = pd.Series([100 + i*0.5 for i in range(35)])

result = analyze_regime(prices)

print(f"Regime: {result['regime']}")
print(f"Slope: {result['slope']:.4f}")
print(f"Volatility: {result['volatility']:.4f}")
```

### 10. Usar RiskController
```python
from risk_control import RiskController

rc = RiskController()

# Atualizar drawdown
rc.update_drawdown(equity_drawdown=0.12, current_equity=95000.0)

# Verificar se pode operar
can_trade = rc.can_execute(
    symbol="USD",
    regime="TENDENCIA_ALTA",
    action="COMPRA",
    confidence=0.85
)

print(f"Pode operar: {can_trade}")
print(f"Modo: {rc.aggressiveness_level}")

# Status completo
status = rc.get_risk_status()
print(status)
```

---

## 🔧 Ajustar Configurações

Edite `config.py` para customizar:

```python
# Trading
DEFAULT_STOP_LOSS_PCT = 0.025     # 2.5%
DEFAULT_TAKE_PROFIT_PCT = 0.05    # 5.0%

# Risk
EQUITY_DRAWDOWN_LIMIT = 0.25      # 25%
DAILY_LOSS_LIMIT = 0.03           # 3%
KILL_SWITCH_HOURS = 2             # 2 horas

# Regime Detection
RANGE_THRESHOLD = 0.004
SLOPE_THRESHOLD_LARGE = 0.003
CHAOS_VOLATILITY_THRESHOLD = 1.8

# Monitoring
MONITORING_INTERVAL_SECONDS = 20   # 20s entre checks
TRAINING_INTERVAL_SECONDS = 3600   # 1h entre treinos
```

---

## 📊 Comparação: Antes vs Depois

| Aspecto | Antes | Depois |
|---------|-------|--------|
| **Race Conditions** | ❌ Múltiplas threads sem proteção | ✅ Lock global thread-safe |
| **Vazamento de Memória** | ❌ Arquivos de 1.6GB | ✅ Relatórios <1MB com rotação |
| **Logging** | ❌ prints espalhados | ✅ Logging estruturado com níveis |
| **Configuração** | ❌ 50+ magic numbers | ✅ Tudo centralizado em config.py |
| **Type Hints** | ❌ 0% | ✅ 90%+ nos arquivos refatorados |
| **Docstrings** | ❌ Ausentes | ✅ Completas em formato Google |
| **Testes** | ❌ 0 testes | ✅ 28 testes automatizados |
| **Float Comparison** | ❌ Comparação exata | ✅ Tolerância configurável |
| **Sleep Bloqueante** | ❌ time.sleep() bloqueia tudo | ✅ threading.Event interruptível |
| **Duplicação** | ❌ EquityManager em 2 lugares | ✅ Módulo único compartilhado |

---

## 🎓 Próximos Passos

1. **Executar testes para validar refatoração:**
   ```bash
   pytest tests/ -v
   ```

2. **Rodar demonstração:**
   ```bash
   python demo.py
   ```

3. **Limpar arquivos antigos:**
   ```bash
   python utils/maintenance.py
   ```

4. **Revisar logs gerados:**
   ```bash
   tail -f logs/monitor.log
   ```

5. **Customizar configurações:**
   - Editar `config.py`
   - Ajustar parâmetros de risco
   - Definir thresholds de regime

---

## ❓ FAQ

**Q: Meus arquivos antigos ainda funcionam?**  
A: Sim! Todos os .old são backups. Você pode reverter se necessário.

**Q: Como sei se os testes passam?**  
A: Execute `pytest tests/ -v`. Todos devem passar (PASSED).

**Q: E se eu quiser ajustar os limites de risco?**  
A: Edite `config.py` e reinicie o sistema.

**Q: Como limpo os arquivos gigantes de relatório?**  
A: Execute `python utils/maintenance.py`

**Q: Posso usar só parte das melhorias?**  
A: Sim! Cada módulo é independente. Importe só o que precisa.

---

## 📞 Suporte

- **Logs:** Verifique `logs/` para debugging
- **Testes:** Execute `pytest tests/ -v` para validar
- **Config:** Consulte `config.py` para parâmetros
- **Docs:** Leia `README.md` para guia completo

---

**Versão:** 2.0 Refatorada  
**Última atualização:** 2026-04-17
