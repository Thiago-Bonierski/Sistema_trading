# 🚀 COMO EXECUTAR O SISTEMA DE TRADING

## 📋 Requisitos

### Python
- Python 3.8 ou superior
- pip (gerenciador de pacotes)

### Sistema Operacional
- Linux, macOS ou Windows
- 2GB de RAM mínimo
- 1GB de espaço em disco

---

## ⚙️ INSTALAÇÃO

### 1. Instalar Dependências

```bash
# Navegar até o diretório do projeto
cd "Assistente Pessoal de Finanças"

# Instalar dependências
pip install -r requirements.txt
```

### 2. Configurar Variáveis de Ambiente (Opcional)

```bash
# Copiar template
cp .env.example .env

# Editar .env com suas credenciais
nano .env  # ou vim, code, etc
```

**Configuração do Telegram (Opcional):**
- Se NÃO configurar: Sistema funciona normalmente, mas sem notificações
- Se configurar: Receberá alertas de trades via Telegram

---

## 🎯 MODOS DE EXECUÇÃO

### Modo 1: Demonstração Completa

```bash
python demo.py
```

**O que faz:**
- ✅ Testa logging
- ✅ Mostra configurações
- ✅ Demonstra database thread-safe
- ✅ Testa equity manager
- ✅ Demonstra detecção de regime
- ✅ Mostra position manager
- ✅ Executa manutenção

**Tempo:** ~30 segundos  
**Ideal para:** Entender o sistema

---

### Modo 2: Testes Automatizados

```bash
# Todos os testes
pytest tests/ -v

# Com cobertura
pytest tests/ --cov=. --cov-report=html

# Teste específico
pytest tests/test_equity.py -v
```

**O que faz:**
- ✅ Executa 28 testes automatizados
- ✅ Valida market_regime
- ✅ Valida equity manager
- ✅ Gera relatório de cobertura

**Tempo:** ~5 segundos  
**Ideal para:** Validar refatoração

---

### Modo 3: Simulação

```bash
python simular.py
```

**O que faz:**
- ✅ Executa simulação em modo RESEARCH
- ✅ Executa simulação em modo PAPER_TRADING
- ✅ Compara resultados
- ✅ Gera relatório JSON (< 1MB!)

**Tempo:** ~10 segundos  
**Ideal para:** Testar estratégias

---

### Modo 4: Dashboard Web + Monitor (Principal)

```bash
python app.py
```

**O que faz:**
- ✅ Inicia servidor Flask (http://localhost:5000)
- ✅ Inicia loop de monitoramento em background
- ✅ Coleta cotações em tempo real
- ✅ Analisa regimes
- ✅ Executa estratégias
- ✅ Gerencia posições
- ✅ Atualiza dashboard automaticamente

**Acesso:** http://localhost:5000  
**Ideal para:** Operação principal

**Para parar:** `Ctrl+C`

---

### Modo 5: Apenas Monitor (Sem Web)

```bash
python monitor.py
```

**O que faz:**
- ✅ Loop de monitoramento puro
- ✅ Coleta cotações
- ✅ Analisa e opera
- ✅ Salva no banco
- ✅ Gera KPIs periodicamente

**Ideal para:** Rodar em servidor sem interface web

**Para parar:** `Ctrl+C`

---

### Modo 6: Treinar Modelo ML

```bash
python ml_training.py
```

**O que faz:**
- ✅ Carrega histórico de trades
- ✅ Processa features
- ✅ Treina LogisticRegression
- ✅ Avalia performance
- ✅ Salva modelo em ml_model.joblib

**Requisitos:** Mínimo 30 trades no histórico  
**Tempo:** ~5 segundos  
**Ideal para:** Melhorar filtro ML

---

### Modo 7: Manutenção de Arquivos

```bash
python utils/maintenance.py
```

**O que faz:**
- ✅ Lista uso de disco
- ✅ Deleta relatórios antigos (>7 dias)
- ✅ Mantém apenas últimos 10 arquivos
- ✅ Remove arquivos corrompidos
- ✅ Mostra espaço liberado

**Tempo:** ~2 segundos  
**Ideal para:** Limpeza periódica

---

### Modo 8: Testes Individuais de Módulos

```bash
# Testar API de cotações
python monitor_dolar.py

# Ver estrutura do projeto
python -c "from pathlib import Path; import config; print(config.BASE_DIR)"
```

---

## 📊 VERIFICANDO LOGS

### Logs em Tempo Real

```bash
# Monitor principal
tail -f logs/monitor.log

# Flask app
tail -f logs/flask_app.log

# Simulador
tail -f logs/simulator.log

# ML training
tail -f logs/ml_training.log
```

### Ver Últimas Linhas

```bash
# Últimas 50 linhas do monitor
tail -50 logs/monitor.log

# Últimas 100 linhas de todos os logs
tail -100 logs/*.log
```

---

## 🗄️ ACESSANDO O BANCO DE DADOS

```bash
# Abrir banco SQLite
sqlite3 historico.db

# Ver tabelas
.tables

# Ver últimas cotações
SELECT * FROM cotacoes ORDER BY id DESC LIMIT 10;

# Ver histórico de trades
SELECT * FROM trade_history ORDER BY id DESC LIMIT 10;

# Sair
.quit
```

---

## 🔧 CUSTOMIZAÇÃO

### Ajustar Parâmetros de Trading

Edite `config.py`:

```python
# Stop-loss e take-profit
DEFAULT_STOP_LOSS_PCT = 0.025    # 2.5% → ajuste aqui
DEFAULT_TAKE_PROFIT_PCT = 0.05   # 5.0% → ajuste aqui

# Limites de risco
EQUITY_DRAWDOWN_LIMIT = 0.25     # 25% → ajuste aqui
DAILY_LOSS_LIMIT = 0.03          # 3% → ajuste aqui

# Intervalo de monitoramento
MONITORING_INTERVAL_SECONDS = 20  # 20s → ajuste aqui
```

### Ajustar Thresholds de Regime

Edite `config.py`:

```python
# Detecção de regime
RANGE_THRESHOLD = 0.004
SLOPE_THRESHOLD_LARGE = 0.003
CHAOS_VOLATILITY_THRESHOLD = 1.8
```

---

## 🐛 TROUBLESHOOTING

### Erro: "Module not found"

```bash
# Instalar dependências novamente
pip install -r requirements.txt --force-reinstall
```

### Erro: "Database is locked"

```bash
# Fechar todas as instâncias do app
pkill -f "python.*app.py"
pkill -f "python.*monitor.py"

# Reiniciar
python app.py
```

### Erro: "Port already in use"

```bash
# Linux/Mac - matar processo na porta 5000
lsof -ti:5000 | xargs kill -9

# Windows
netstat -ano | findstr :5000
taskkill /PID <PID> /F

# Ou mudar porta em .env
FLASK_PORT=5001
```

### Cotações não atualizam

```bash
# Testar API manualmente
python monitor_dolar.py

# Ver logs
tail -f logs/monitor.log
```

### Relatórios muito grandes

```bash
# Executar limpeza
python utils/maintenance.py

# Verificar tamanho
du -h simulation_reports/
```

---

## 📈 FLUXO RECOMENDADO

### Primeira Execução

```bash
# 1. Instalar
pip install -r requirements.txt

# 2. Demonstração
python demo.py

# 3. Testes
pytest tests/ -v

# 4. Simulação
python simular.py

# 5. Iniciar sistema
python app.py

# 6. Acessar dashboard
open http://localhost:5000
```

### Uso Diário

```bash
# Manhã: verificar logs
tail -100 logs/monitor.log

# Durante o dia: monitorar dashboard
# http://localhost:5000

# Fim do dia: gerar relatório
# (automático via /latest_kpi_report.json)

# Semanal: limpeza
python utils/maintenance.py
```

### Otimização

```bash
# 1. Coletar dados (deixar rodar por dias/semanas)
python app.py

# 2. Treinar ML quando tiver 30+ trades
python ml_training.py

# 3. Ajustar configs baseado em performance
nano config.py

# 4. Rodar simulações
python simular.py

# 5. Comparar resultados
cat simulation_reports/latest_report.json
```

---

## 🔒 SEGURANÇA

### Em Produção

1. **NUNCA** usar `FLASK_DEBUG=True`
2. **SEMPRE** manter `.env` no `.gitignore`
3. **NUNCA** commitar credenciais
4. Usar HTTPS se expor na web
5. Firewall apropriado

### Backup

```bash
# Backup do banco
cp historico.db historico.db.backup

# Backup dos logs
tar -czf logs_backup.tar.gz logs/

# Backup dos relatórios
tar -czf reports_backup.tar.gz reports/ simulation_reports/
```

---

## 📞 SUPORTE

### Documentação

- `README.md` - Guia completo
- `GUIA_RAPIDO.md` - Quick start
- `RELATORIO_REFATORACAO.md` - Detalhes técnicos
- Docstrings inline - Em todas as funções

### Logs

- `logs/monitor.log` - Log principal
- `logs/flask_app.log` - Web server
- `logs/simulator.log` - Simulações
- `logs/ml_training.log` - Treinamento ML

### Testes

```bash
# Validar se tudo funciona
pytest tests/ -v
```

---

## ✅ CHECKLIST DE EXECUÇÃO

- [ ] Python 3.8+ instalado
- [ ] Dependências instaladas (`pip install -r requirements.txt`)
- [ ] `.env` configurado (opcional)
- [ ] Demonstração executada (`python demo.py`)
- [ ] Testes passando (`pytest tests/ -v`)
- [ ] Sistema iniciado (`python app.py`)
- [ ] Dashboard acessível (http://localhost:5000)
- [ ] Logs sendo gerados (`ls -lh logs/`)

---

**Pronto para operar!** 🚀

**Versão:** 2.0 - Sistema Refatorado  
**Última atualização:** 2026-04-17
