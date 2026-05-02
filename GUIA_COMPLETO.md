# 🚀 GUIA COMPLETO - Sistema de Trading Refatorado

## 📋 Índice

1. [Estrutura do Projeto](#estrutura)
2. [Instalação](#instalação)
3. [Configuração](#configuração)
4. [Como Executar](#execução)
5. [Testes](#testes)
6. [Manutenção](#manutenção)
7. [Troubleshooting](#troubleshooting)

---

## 📁 Estrutura do Projeto {#estrutura}

```
Assistente_Pessoal_de_Finanças/
│
├── 📚 DOCUMENTAÇÃO
│   ├── README.md                      # Guia completo do sistema
│   ├── GUIA_RAPIDO.md                 # Quick start
│   ├── GUIA_COMPLETO.md              # Este arquivo
│   ├── RELATORIO_REFATORACAO.md      # Fase 1
│   ├── FASE_2_RELATORIO.md           # Fase 2
│   ├── FASE_3_RELATORIO.md           # Fase 3
│   └── FASE_4_RELATORIO.md           # Fase 4
│
├── 🏗️ INFRAESTRUTURA BASE
│   ├── config.py                      # ⭐ Configurações centralizadas
│   ├── database.py                    # ⭐ SQLite thread-safe
│   ├── equity.py                      # ⭐ Gerenciamento de capital
│   ├── logging_config.py              # ⭐ Logging profissional
│   └── utils/
│       └── maintenance.py             # ⭐ Limpeza automática
│
├── 🔧 COMPONENTES PRINCIPAIS
│   ├── market_regime.py               # ✅ Detecção de regimes
│   ├── position_manager.py            # ✅ Gestão de posições
│   ├── risk_control.py                # ✅ Controle de risco
│   └── monitor.py                     # ✅ Loop principal
│
├── 🎯 ESTRATÉGIAS
│   ├── strategy_engines.py            # ✅ 4 engines de trading
│   ├── strategy_orchestrator.py       # ✅ Orquestrador
│   ├── ml_classifier.py               # ✅ Filtro ML
│   └── ml_training.py                 # ✅ Treinamento ML
│
├── 🌐 INTERFACE
│   ├── app.py                         # ✅ API Flask (dashboard web)
│   └── simular.py                     # ✅ Sistema de simulação
│
├── 📊 UTILITÁRIOS
│   ├── kpis.py                        # ✅ Métricas de performance
│   ├── exhaustion_filter.py           # ✅ Filtro de exaustão
│   └── monitor_dolar.py               # ✅ APIs externas
│
├── 🧪 TESTES
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_market_regime.py      # 13 testes
│   │   └── test_equity.py             # 15 testes
│   └── demo.py                        # ⭐ Demonstração completa
│
├── 📦 CONFIGURAÇÃO
│   ├── requirements.txt               # ⭐ Dependências Python
│   └── .env.example                   # Exemplo de configuração
│
├── 💾 DADOS (gerados automaticamente)
│   ├── historico.db                   # Banco de dados SQLite
│   ├── ml_model.joblib               # Modelo ML treinado
│   ├── logs/                         # Logs rotativos
│   ├── reports/                      # Relatórios
│   └── simulation_reports/           # Relatórios de simulação
│
└── 🗂️ BACKUPS (.old)
    ├── app.py.old
    ├── simular.py.old
    ├── monitor.py.old
    └── ... (outros backups)
```

---

## ⚙️ Instalação {#instalação}

### 1. Pré-requisitos

- **Python 3.8+** (recomendado: 3.11)
- **pip** (gerenciador de pacotes Python)
- **git** (opcional, para versionamento)

### 2. Instalar Dependências

```bash
# Navegar para o diretório do projeto
cd "Assistente Pessoal de Finanças"

# Instalar dependências
pip install -r requirements.txt
```

**Dependências principais:**
- `pandas` - Manipulação de dados
- `flask` - API web
- `requests` - Chamadas HTTP
- `scikit-learn` - Machine learning
- `joblib` - Persistência de modelos
- `pytest` - Testes automatizados
- `python-dotenv` - Variáveis de ambiente

---

## 🔧 Configuração {#configuração}

### 1. Criar Arquivo .env

```bash
# Copiar exemplo
cp .env.example .env

# Editar configurações
nano .env  # ou seu editor preferido
```

**Conteúdo do .env:**
```bash
# ============================================================================
# FLASK
# ============================================================================
FLASK_DEBUG=False           # True apenas em desenvolvimento
FLASK_HOST=127.0.0.1       # 0.0.0.0 para acesso externo
FLASK_PORT=5000

# ============================================================================
# TELEGRAM (Opcional - para notificações)
# ============================================================================
TELEGRAM_TOKEN=seu_token_aqui
CHAT_ID=seu_chat_id

# ============================================================================
# LOGGING
# ============================================================================
LOG_LEVEL=INFO             # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### 2. Ajustar Configurações

Edite `config.py` para personalizar:

```python
# Trading
DEFAULT_STOP_LOSS_PCT = 0.025     # 2.5% stop-loss
DEFAULT_TAKE_PROFIT_PCT = 0.05    # 5% take-profit

# Risk
EQUITY_DRAWDOWN_LIMIT = 0.25      # 25% drawdown máximo
DAILY_LOSS_LIMIT = 0.03           # 3% perda diária máxima

# Regimes
RANGE_THRESHOLD = 0.004
SLOPE_THRESHOLD_LARGE = 0.003
```

### 3. Inicializar Banco de Dados

```bash
# O banco é criado automaticamente na primeira execução
# Mas você pode inicializá-lo manualmente:

python -c "from database import init_database; init_database()"
```

---

## 🚀 Como Executar {#execução}

### Modo 1: Dashboard Web (Flask)

```bash
# Iniciar servidor web + monitor
python app.py
```

**Acesso:**
- Dashboard: `http://localhost:5000`
- Health check: `http://localhost:5000/health`
- API dados: `http://localhost:5000/dados_atualizados`

**O que acontece:**
1. Flask inicia na porta 5000
2. Thread de monitoramento inicia em background
3. Thread de treinamento ML inicia em background
4. Dashboard atualiza a cada 20 segundos

### Modo 2: Apenas Monitoramento

```bash
# Loop de monitoramento standalone
python monitor.py
```

**O que acontece:**
1. Sistema busca cotações a cada 20s
2. Analisa regime de mercado
3. Executa estratégias
4. Gerencia posições
5. Controla risco
6. Gera relatórios de KPIs

### Modo 3: Simulação

```bash
# Executar simulação completa
python simular.py
```

**Output:**
- Relatórios em `simulation_reports/`
- Estatísticas no console
- Trades salvos em SQLite (se habilitado)

### Modo 4: Treinamento ML

```bash
# Treinar modelo ML
python ml_training.py
```

**Requer:**
- Mínimo 30 trades no histórico
- scikit-learn instalado

**Output:**
- Modelo salvo em `ml_model.joblib`
- Relatório de performance no console

---

## 🧪 Testes {#testes}

### Executar Todos os Testes

```bash
# Testes completos
pytest tests/ -v

# Com cobertura
pytest tests/ --cov=. --cov-report=html

# Teste específico
pytest tests/test_equity.py -v
```

### Demonstração Interativa

```bash
# Executar demonstração completa
python demo.py
```

**Demonstra:**
1. Logging profissional
2. Configurações centralizadas
3. Database thread-safe
4. Equity manager
5. Detecção de regime
6. Position manager
7. Manutenção automática

---

## 🔧 Manutenção {#manutenção}

### Limpeza Automática

```bash
# Executar rotina de manutenção
python utils/maintenance.py
```

**O que faz:**
- Remove relatórios antigos (>7 dias)
- Mantém apenas últimos 10 arquivos
- Remove arquivos corrompidos
- Mostra uso de disco

### Visualizar Logs

```bash
# Monitor principal
tail -f logs/monitor.log

# Flask
tail -f logs/flask_app.log

# Simulador
tail -f logs/simulator.log

# ML
tail -f logs/ml_training.log
```

### Backup do Banco

```bash
# Criar backup manual
cp historico.db historico_backup_$(date +%Y%m%d).db

# Restaurar de backup
cp historico_backup_20260417.db historico.db
```

---

## ❓ Troubleshooting {#troubleshooting}

### Problema: "Module not found"

**Solução:**
```bash
# Reinstalar dependências
pip install -r requirements.txt --upgrade
```

### Problema: "Database locked"

**Solução:**
```bash
# Fechar todas as conexões
pkill -f python

# Reiniciar
python app.py
```

### Problema: "Port 5000 already in use"

**Solução 1:** Mudar porta no .env
```bash
FLASK_PORT=8000
```

**Solução 2:** Matar processo na porta
```bash
# Linux/Mac
lsof -ti:5000 | xargs kill -9

# Windows
netstat -ano | findstr :5000
taskkill /PID <PID> /F
```

### Problema: Logs muito grandes

**Solução:**
```bash
# Limpar logs manualmente
rm -f logs/*.log

# Ou executar manutenção
python utils/maintenance.py
```

### Problema: ML não treina

**Causas comuns:**
1. Menos de 30 trades no histórico
2. scikit-learn não instalado
3. Dados corrompidos

**Solução:**
```bash
# Verificar trades
python -c "from database import db_manager; print(db_manager.fetch_one('SELECT COUNT(*) as c FROM trade_history'))"

# Reinstalar sklearn
pip install scikit-learn --upgrade

# Ver logs
tail -f logs/ml_training.log
```

---

## 📊 Comandos Úteis

### Verificar Status do Sistema

```python
# Python REPL
from database import db_manager
from equity import EquityManager
from risk_control import RiskController

# Trades no banco
result = db_manager.fetch_one("SELECT COUNT(*) as count FROM trade_history")
print(f"Total de trades: {result['count']}")

# Equity atual
em = EquityManager()
print(em.get_summary())

# Status de risco
rc = RiskController()
print(rc.get_risk_status())
```

### Resetar Sistema

```bash
# CUIDADO: Remove todos os dados!

# Deletar banco
rm historico.db

# Deletar modelo ML
rm ml_model.joblib

# Deletar relatórios
rm -rf simulation_reports/*
rm -rf reports/*

# Reiniciar
python app.py
```

---

## 🎯 Fluxo de Uso Recomendado

### Para Desenvolvimento

```bash
# 1. Ativar modo debug
echo "FLASK_DEBUG=True" > .env
echo "LOG_LEVEL=DEBUG" >> .env

# 2. Executar testes
pytest tests/ -v

# 3. Executar demo
python demo.py

# 4. Iniciar sistema
python app.py
```

### Para Produção

```bash
# 1. Configurar produção
echo "FLASK_DEBUG=False" > .env
echo "LOG_LEVEL=INFO" >> .env
echo "FLASK_HOST=0.0.0.0" >> .env

# 2. Executar testes
pytest tests/ -v

# 3. Limpar dados antigos
python utils/maintenance.py

# 4. Iniciar sistema
nohup python app.py > output.log 2>&1 &
```

### Para Análise

```bash
# 1. Executar simulação
python simular.py

# 2. Ver relatórios
ls -lh simulation_reports/

# 3. Treinar ML
python ml_training.py

# 4. Verificar performance
python -c "from kpis import KPITracker; print(KPITracker().summary())"
```

---

## 📞 Suporte Adicional

**Documentação:**
- README.md - Visão geral
- GUIA_RAPIDO.md - Quick start
- Docstrings inline - Detalhes de cada função

**Logs:**
- `logs/monitor.log` - Operação principal
- `logs/flask_app.log` - Dashboard web
- `logs/simulator.log` - Simulações
- `logs/ml_training.log` - Machine learning

**Testes:**
```bash
pytest tests/ -v --tb=short
```

---

## ✅ Checklist de Inicialização

- [ ] Python 3.8+ instalado
- [ ] Dependências instaladas (`pip install -r requirements.txt`)
- [ ] Arquivo .env criado e configurado
- [ ] Telegram configurado (opcional)
- [ ] Testes passando (`pytest tests/ -v`)
- [ ] Demo executada (`python demo.py`)
- [ ] Sistema iniciado (`python app.py`)
- [ ] Dashboard acessível (http://localhost:5000)

---

**Versão:** 2.0  
**Última atualização:** 2026-04-17  
**Status:** ✅ Production Ready
