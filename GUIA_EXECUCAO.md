# 🚀 GUIA COMPLETO DE EXECUÇÃO - Sistema de Trading v2.0

## 📋 Índice
1. [Instalação](#instalação)
2. [Estrutura do Projeto](#estrutura-do-projeto)
3. [Configuração](#configuração)
4. [Execução](#execução)
5. [Testes](#testes)
6. [Manutenção](#manutenção)
7. [Troubleshooting](#troubleshooting)

---

## 🔧 Instalação

### Opção 1: Script Automatizado (Recomendado)

```bash
# Dar permissão de execução
chmod +x install.sh

# Executar instalação
./install.sh
```

### Opção 2: Manual

```bash
# 1. Criar ambiente virtual (opcional mas recomendado)
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Criar diretórios
mkdir -p logs reports simulation_reports

# 4. Inicializar banco de dados
python3 -c "from database import init_database; init_database()"

# 5. Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com suas credenciais

# 6. Executar testes (opcional)
pytest tests/ -v

# 7. Limpeza inicial
python3 utils/maintenance.py
```

---

## 📁 Estrutura do Projeto

```
Sistema_Refatorado/
│
├── 📦 MÓDULOS BASE
│   ├── config.py              # Configurações centralizadas
│   ├── database.py            # DB thread-safe
│   ├── equity.py              # Gerenciamento de capital
│   ├── logging_config.py      # Logging profissional
│
├── 🎯 COMPONENTES PRINCIPAIS
│   ├── market_regime.py       # Detecção de regimes
│   ├── position_manager.py    # Gestão de posições
│   ├── risk_control.py        # Controle de risco
│   ├── monitor.py             # Loop principal
│
├── 🧠 ESTRATÉGIAS
│   ├── strategy_engines.py    # Engines de trading
│   ├── strategy_orchestrator.py  # Orquestrador
│   ├── ml_classifier.py       # Filtro ML
│   ├── ml_training.py         # Treinamento ML
│
├── 🛠️ UTILITÁRIOS
│   ├── kpis.py                # Rastreamento de KPIs
│   ├── exhaustion_filter.py  # Filtro de exaustão
│   ├── monitor_dolar.py       # API de cotações
│   └── utils/
│       └── maintenance.py     # Manutenção automática
│
├── 🌐 WEB
│   ├── app.py                 # API Flask
│   └── templates/             # Templates HTML
│
├── 🧪 TESTES
│   └── tests/
│       ├── test_market_regime.py
│       └── test_equity.py
│
├── 📊 SIMULAÇÃO
│   └── simular.py             # Sistema de simulação
│
├── 📚 DOCUMENTAÇÃO
│   ├── README.md              # Guia completo
│   ├── GUIA_RAPIDO.md         # Quick start
│   ├── GUIA_EXECUCAO.md       # Este arquivo
│   ├── RELATORIO_REFATORACAO.md
│   ├── FASE_2_RELATORIO.md
│   └── FASE_3_RELATORIO.md
│
├── 🎯 DEMONSTRAÇÃO
│   └── demo.py                # Demonstração do sistema
│
├── ⚙️ CONFIGURAÇÃO
│   ├── .env.example           # Template de variáveis
│   ├── requirements.txt       # Dependências
│   └── install.sh             # Script de instalação
│
└── 📂 DADOS (criados em runtime)
    ├── logs/                  # Logs rotativos
    ├── reports/               # Relatórios
    ├── simulation_reports/    # Simulações
    └── historico.db           # Banco SQLite
```

---

## ⚙️ Configuração

### 1. Configurações Principais (config.py)

Edite `config.py` para ajustar:

```python
# Trading
DEFAULT_STOP_LOSS_PCT = 0.025     # Stop-loss padrão (2.5%)
DEFAULT_TAKE_PROFIT_PCT = 0.05    # Take-profit padrão (5%)

# Risk
EQUITY_DRAWDOWN_LIMIT = 0.25      # Limite de drawdown (25%)
DAILY_LOSS_LIMIT = 0.03           # Limite de perda diária (3%)
KILL_SWITCH_HOURS = 2             # Horas de pausa após kill-switch

# Capital
INITIAL_CAPITAL = 100000.0        # Capital inicial para simulações
```

### 2. Variáveis de Ambiente (.env)

```bash
# Copiar template
cp .env.example .env

# Editar .env
nano .env  # ou seu editor preferido
```

**Variáveis opcionais:**
- `TELEGRAM_TOKEN`: Token do bot Telegram (para notificações)
- `CHAT_ID`: ID do chat Telegram
- `FLASK_DEBUG`: Debug do Flask (sempre False em produção!)
- `LOG_LEVEL`: Nível de logging (DEBUG, INFO, WARNING, ERROR)

### 3. Telegram (Opcional)

Para receber notificações:

1. Criar bot com [@BotFather](https://t.me/BotFather)
2. Copiar token fornecido
3. Enviar mensagem para seu bot
4. Acessar `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Copiar `chat_id` do resultado
6. Adicionar ao `.env`

---

## 🚀 Execução

### Modo 1: Demonstração (Recomendado para primeiro uso)

```bash
python demo.py
```

**O que faz:**
- Demonstra todos os módulos
- Executa testes rápidos
- Mostra funcionalidades
- NÃO executa trades reais

### Modo 2: Simulação

```bash
python simular.py
```

**O que faz:**
- Executa simulação com dados sintéticos
- Testa estratégias em diferentes regimes
- Gera relatórios de performance
- NÃO usa dinheiro real

### Modo 3: Sistema Completo (Produção)

```bash
# Iniciar servidor web + monitoramento
python app.py
```

**O que faz:**
- Inicia API Flask em http://localhost:5000
- Inicia loop de monitoramento em background
- Busca cotações reais de USD e BTC
- Executa estratégias em tempo real
- Salva trades no banco de dados

**Acessar dashboard:**
```
http://localhost:5000
```

### Modo 4: Apenas Monitoramento

```bash
python monitor.py
```

**O que faz:**
- Apenas loop de monitoramento
- Sem interface web
- Ideal para rodar em servidor

---

## 🧪 Testes

### Executar Todos os Testes

```bash
pytest tests/ -v
```

### Executar Testes Específicos

```bash
# Testes de regime
pytest tests/test_market_regime.py -v

# Testes de equity
pytest tests/test_equity.py -v

# Teste específico
pytest tests/test_equity.py::TestEquityManager::test_update_equity_com_lucro -v
```

### Testes com Cobertura

```bash
pytest tests/ --cov=. --cov-report=html
# Relatório em htmlcov/index.html
```

---

## 🔧 Manutenção

### Limpeza de Arquivos Antigos

```bash
python utils/maintenance.py
```

**O que faz:**
- Deleta relatórios com mais de 7 dias
- Mantém apenas últimos 10 relatórios
- Valida integridade de JSONs
- Mostra estatísticas de disco

### Treinar Modelo ML

```bash
python ml_training.py
```

**Requisitos:**
- Mínimo 30 trades no histórico
- sklearn instalado

### Verificar Logs

```bash
# Logs em tempo real
tail -f logs/monitor.log
tail -f logs/flask_app.log

# Logs de erro
grep ERROR logs/*.log

# Estatísticas
wc -l logs/*.log
```

---

## 🐛 Troubleshooting

### Problema: "ModuleNotFoundError: No module named 'X'"

**Solução:**
```bash
pip install -r requirements.txt
```

### Problema: "sqlite3.OperationalError: database is locked"

**Solução:**
- Sistema já usa locks thread-safe
- Se persistir, verificar se há outro processo usando o banco
```bash
lsof historico.db  # Linux/Mac
```

### Problema: Relatórios muito grandes (> 100MB)

**Solução:**
- Sistema refatorado já corrige isso
- Se ainda ocorrer, executar manutenção:
```bash
python utils/maintenance.py
```

### Problema: API de cotações retorna erro 429 (Too Many Requests)

**Solução:**
- Aumentar `MONITORING_INTERVAL_SECONDS` em `config.py`
- API gratuita tem limite de requisições

### Problema: Telegram não envia mensagens

**Solução:**
1. Verificar variáveis no .env:
```bash
python -c "from monitor_dolar import verificar_configuracao; verificar_configuracao()"
```

2. Testar envio:
```bash
python monitor_dolar.py
```

### Problema: Testes falhando

**Solução:**
```bash
# Verificar dependências
pip install -r requirements.txt

# Executar com verbose
pytest tests/ -v -s

# Ver logs de erro
cat logs/test*.log
```

---

## 📊 Monitoramento de Performance

### Ver KPIs

```bash
# KPIs salvos em reports/latest_kpi_report.json
cat reports/latest_kpi_report.json | python -m json.tool
```

### Analisar Trades

```bash
# Acessar banco de dados
sqlite3 historico.db

# Queries úteis:
SELECT COUNT(*) FROM trade_history;
SELECT AVG(pnl) FROM trade_history;
SELECT * FROM trade_history WHERE pnl > 0;
```

---

## 🔄 Atualização do Sistema

```bash
# Fazer backup
cp -r . ../backup_$(date +%Y%m%d)

# Atualizar dependências
pip install -r requirements.txt --upgrade

# Re-executar testes
pytest tests/ -v

# Limpar arquivos antigos
python utils/maintenance.py
```

---

## 🛑 Parar o Sistema

### Parada Graceful (Recomendado)

```bash
# Ctrl+C no terminal onde está rodando
# Sistema salvará estado e fechará posições
```

### Parada Forçada

```bash
# Encontrar processo
ps aux | grep python

# Matar processo (use com cuidado!)
kill -9 <PID>
```

---

## 📈 Próximos Passos

1. ✅ Executar `demo.py` para familiarização
2. ✅ Rodar `simular.py` para testar estratégias
3. ✅ Ajustar `config.py` conforme necessário
4. ✅ (Opcional) Configurar Telegram
5. ✅ Iniciar `app.py` para produção
6. ✅ Monitorar logs em `logs/`
7. ✅ Executar manutenção periodicamente

---

## 📞 Suporte

**Documentação:**
- README.md - Visão geral
- GUIA_RAPIDO.md - Quick start
- RELATORIO_REFATORACAO.md - Detalhes técnicos

**Logs:**
- `logs/monitor.log` - Loop principal
- `logs/flask_app.log` - API web
- `logs/simulator.log` - Simulações
- `logs/ml_training.log` - Treinamento ML

**Comandos Úteis:**
```bash
python demo.py              # Demonstração
pytest tests/ -v            # Testes
python utils/maintenance.py # Limpeza
python ml_training.py       # Treinar ML
python monitor_dolar.py     # Testar API
```

---

**Versão:** 2.0 Refatorada  
**Última atualização:** 2026-04-17  
**Status:** ✅ 100% Refatorado e Pronto para Produção
