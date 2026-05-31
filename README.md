# Sistema de Trading Automatizado — Python

Bot de trading algoritmico para monitoramento e operacao em multiplos pares de ativos financeiros (USD/BRL, BTC/BRL, ETH/BRL, SOL/BRL), com deteccao de regime de mercado, multiplas estrategias, filtro por Machine Learning, controle de risco adaptativo e dashboard web em tempo real.

---

## Visao Geral

O sistema opera em ciclos de monitoramento a cada 20 segundos, coletando cotacoes via API publica (AwesomeAPI), identificando o regime de mercado vigente, executando as estrategias adequadas para aquele regime e filtrando os sinais gerados por um classificador ML antes de tomar qualquer decisao de entrada ou saida de posicao. Todo o fluxo e auditado em logs rotativos e pode ser acompanhado em tempo real por um dashboard Flask com graficos interativos.

O projeto foi construido com foco em separacao de responsabilidades, seguranca de threads, tolerancia a falhas e configurabilidade total — sem magic numbers espalhados pelo codigo.

---

## Arquitetura

```
Coleta de dados (AwesomeAPI)
         |
         v
Deteccao de Regime de Mercado
         |
         v
Orquestrador de Estrategias
  |          |           |
Trend     MeanRev   Breakout
Following  ersion   Momentum
         |
         v
Filtro ML (RandomForest / Heuristica)
         |
         v
Controle de Risco (NORMAL / REDUCED / PROTECT)
         |
         v
Gerenciador de Posicoes (SL / TP / Age)
         |
         v
Banco de Dados SQLite + Telegram + Dashboard Flask
```

Cada camada e isolada em seu proprio modulo. O monitor.py e o ponto de entrada do loop principal, orquestrando todos os componentes sem acoplar suas implementacoes.

---

## Funcionalidades

### Monitoramento Multi-Ativo

- Coleta cotacoes de quatro pares simultaneamente: USD/BRL, BTC/BRL, ETH/BRL e SOL/BRL
- Intervalo configuravel (padrao: 20 segundos)
- Protecao contra data gaps: detecta ausencia de dados por mais de 10 minutos e fecha posicoes abertas automaticamente para evitar distorcao de PnL e risco oculto
- Tratamento de rate limit (HTTP 429) com backoff automatico

### Deteccao de Regime de Mercado

O modulo `market_regime.py` classifica o mercado em cinco estados com base em slope, range relativo, volatilidade, momentum e persistencia de tendencia:

| Regime | Descricao |
|---|---|
| TENDENCIA_ALTA | Movimento ascendente com persistencia confirmada |
| TENDENCIA_BAIXA | Movimento descendente com persistencia confirmada |
| CONSOLIDACAO | Amplitude baixa, sem direcao clara |
| TRANSICAO | Mudanca de regime em curso |
| ALTA_VOLATILIDADE | Movimento forte sem momentum consistente |

Parametros de deteccao sao todos configurados em `config.py` (thresholds de slope, range, chaos, etc.).

### Engines de Estrategia

Implementadas em `strategy_unified.py` com heranca de `BaseStrategyEngine`. Cada engine retorna uma sugestao com acao, nivel de confianca e justificativa.

**TrendFollowing** — opera em TENDENCIA_ALTA e TENDENCIA_BAIXA. Usa media movel longa (15 periodos) e confirmacao por momentum. Confianca padrao: 0.82.

**MeanReversion** — opera em CONSOLIDACAO. Compra na borda inferior de uma banda de preco e vende na superior. Confianca padrao: 0.74.

**BreakoutMomentum** — detecta rompimentos acima do maximo ou abaixo do minimo recente com range minimo definido. Confianca padrao: 0.68.

**ProtectFlat** — modo defensivo ativado em regimes de alta volatilidade ou transicao. Retorna NEUTRO com confianca zero.

O **StrategyOrchestrator** seleciona quais engines sao pertinentes ao regime atual, as executa e escolhe a sugestao com maior confianca. Em caso de conflito ou regime arriscado, ativa o modo ProtectFlat como fallback.

### Filtro de Confirmacao de Tendencia

Camada de seguranca aplicada em `monitor.py` antes de qualquer entrada em operacoes de tendencia. Exige que o regime `TENDENCIA_ALTA` ou `TENDENCIA_BAIXA` apareca por pelo menos 2 ciclos consecutivos (configuravel via `TREND_CONFIRMATION_TICKS`) antes de liberar COMPRA ou VENDA. Enquanto a contagem de confirmacoes nao for atingida, o sinal e convertido para NEUTRO automaticamente. O contador e zerado sempre que o regime muda, prevenindo entradas precipitadas em transicoes de curta duracao. Posicoes ja abertas nao sao afetadas por esse filtro — apenas novas entradas.

### Filtro de Exaustao

O `exhaustion_filter.py` avalia, antes de qualquer entrada, se o movimento em curso esta perdendo forca. Criterios: momentum acelerando mas desacelerando na ponta, rompimento com momentum fraco, ou alta volatilidade sem consistencia direcional. Previne entradas no final de movimentos.

### Classificador Machine Learning

O `ml_classifier.py` usa um modelo `RandomForestClassifier` (com fallback para `LogisticRegression`) treinado em historico real de trades. Features utilizadas:

- Confianca da engine
- Regime de mercado de entrada
- Engine geradora do sinal
- Direcao do trade (COMPRA / VENDA)
- Metricas de volatilidade e momentum do regime

O threshold de aprovacao e configuravel (padrao: 0.58). Se o modelo nao estiver disponivel, o sistema opera via heuristica que avalia as mesmas metricas sem dependencia de biblioteca de ML.

O `ml_training.py` retreina o modelo automaticamente a cada hora (configuravel) desde que haja pelo menos 30 trades no historico. O pipeline de treino inclui `ColumnTransformer` com `StandardScaler` para variaveis numericas e `OneHotEncoder` para variaveis categoricas. O treinamento roda em thread separada para nao bloquear o loop principal de monitoramento.

### Controle de Risco

O `RiskController` em `risk_control.py` opera em tres niveis de agressividade que se ajustam dinamicamente conforme o desempenho:

| Nivel | Condicao de ativacao | Efeito |
|---|---|---|
| NORMAL | Estado padrao | Limites completos por regime |
| REDUCED | Drawdown em elevacao | Limites reduzidos a metade, confianca minima de 0.70 |
| PROTECT | Drawdown >= 25% | Bloqueio total de novas entradas |

Mecanismos adicionais:

- **Kill-Switch diario**: bloqueia trades por 2 horas se a perda do dia atingir 3% do capital inicial
- **Limite global de trades**: maximo de 8 trades por dia (configuravel)
- **Limites por regime**: cada regime tem um teto de trades diarios independente
- **Cooldown por stop-loss**: pausa apos saida por stop varia por nivel (5 / 10 / 20 ticks)
- **Reativacao progressiva**: saida do nivel REDUCED exige 3 novos maximos de equity consecutivos

### Gerenciamento de Posicoes

O `PositionManager` controla o ciclo de vida completo de cada posicao:

- **Stop-Loss**: 2.5% abaixo (COMPRA) ou acima (VENDA) do preco de entrada
- **Take-Profit**: 5.0% em sentido favoravel
- **Position sizing**: percentual do equity atual (10% por padrao), multiplicado pela confianca do sinal (fator de 0.4 a 1.0)
- **Envelhecimento**: posicoes sao encerradas por idade maxima, que varia por nivel de risco (50 / 25 / 15 ticks)
- **Saida por mudanca de regime**: posicao pode ser fechada se o regime mudar para um incompativel com a direcao aberta

### Gerenciamento de Equity

O `EquityManager` rastreia capital atual, pico historico, drawdown maximo e retorno total. E a fonte de verdade para o RiskController e para o sizing de posicoes.

### Rastreamento de KPIs

O `KPITracker` agrega metricas de forma continua por:

- Regime de mercado
- Engine geradora do sinal
- Nivel de agressividade

Metricas calculadas: total de trades, win rate, PnL medio, PnL total e duracao media em ticks. Relatorio de KPIs e emitido via Telegram a cada 15 minutos (configuravel).

### Dashboard Web

Aplicacao Flask em `app.py` com atualizacao automatica via AJAX a cada 30 segundos. A interface renderiza:

- Graficos de linha interativos (Plotly.js) para cada par monitorado
- Status atual de recomendacao, regime e confianca por ativo
- Tabela com ultimos 20 trades e metricas de performance
- Dois botoes de controle remoto (Pausar monitor / Encerrar processo) protegidos por token de autenticacao configuravel

Endpoints REST disponiveis:

| Rota | Metodo | Descricao |
|---|---|---|
| `/` | GET | Dashboard principal |
| `/dados_atualizados` | GET | JSON com dados de todos os ativos e KPIs |
| `/health` | GET | Health check da aplicacao |
| `/api/shutdown_monitor` | POST | Para o loop de monitoramento (Flask continua ativo) |
| `/api/exit_process` | POST | Encerra o processo inteiro |

### Banco de Dados

O `DatabaseManager` em `database.py` resolve o problema classico de race conditions em SQLite com multiplas threads: usa um lock global e context manager que garante commit e rollback automaticos. A `row_factory` retorna dicionarios em vez de tuplas, facilitando o acesso por nome de coluna.

Tabelas principais: `cotacoes` (historico de preco e recomendacao por ativo) e `trade_history` (resultado de cada trade executado com PnL, duracao e regime).

### Notificacoes Telegram

O `monitor_base.py` envia alertas de abertura e fechamento de trades, mudancas de regime relevantes, relatorios de KPIs periodicos e resumo completo de estado ao encerrar o sistema.

### Simulacao

O `simular.py` oferece dois modos de execucao sobre dados historicos:

- **RESEARCH**: modo agressivo com ate 5 posicoes simultaneas, max_age de 100 ticks, sem controle de risco rigoroso — para explorar o potencial de estrategias
- **PAPER_TRADING**: modo conservador com 1 posicao, max_age de 15 ticks, nivel REDUCED — simula comportamento proximo ao ambiente de producao

Os relatorios de simulacao salvam apenas estatisticas agregadas (nao todos os trades detalhados) para evitar arquivos gigantes. Trades completos ficam em SQLite separado para analise pontual.

### Manutencao Automatica

O `utils/maintenance.py` rotaciona automaticamente relatorios antigos (limite de 10 simulacoes e 20 relatorios de treino), remove arquivos com mais de 7 dias e monitora uso de disco.

---

## Estrutura do Projeto

```
Sistema_trading/
|
|-- app.py                  # API Flask + rotas do dashboard
|-- config.py               # Todas as configuracoes e constantes
|-- database.py             # DatabaseManager thread-safe
|-- equity.py               # EquityManager (capital, drawdown, retorno)
|-- exhaustion_filter.py    # Filtro de exaustao de movimento
|-- kpis.py                 # KPITracker (metricas de performance)
|-- logging_config.py       # Logging com rotacao, niveis e funcoes estruturadas (trade, regime, risco)
|-- market_regime.py        # Deteccao de regime de mercado
|-- ml_classifier.py        # Filtro ML de sinais
|-- ml_training.py          # Treinamento periodico do modelo
|-- monitor.py              # Loop principal de monitoramento
|-- monitor_base.py         # Cliente de API e Telegram
|-- position_manager.py     # Ciclo de vida de posicoes
|-- risk_control.py         # RiskController com kill-switch
|-- simular.py              # Engine de simulacao
|-- strategy_unified.py     # Engines + Orquestrador de estrategias
|-- demo.py                 # Script de demonstracao dos modulos
|-- requirements.txt
|-- install.sh
|
|-- templates/
|   |-- index.html          # Template do dashboard
|
|-- static/
|   |-- dashboard.js        # Logica de graficos e atualizacao
|   |-- style.css           # Estilo do dashboard
|
|-- tests/
|   |-- test_equity.py
|   |-- test_market_regime.py
|
|-- utils/
    |-- maintenance.py      # Limpeza e rotacao de arquivos
```

---

## Stack Tecnologica

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.8+ |
| Web Framework | Flask 3.x |
| Banco de Dados | SQLite (built-in) com threading.Lock |
| Machine Learning | scikit-learn (RandomForest, LogisticRegression, Pipeline) |
| Serializacao de Modelo | joblib |
| Graficos (frontend) | Plotly.js |
| Notificacoes | Telegram Bot API |
| Cotacoes | AwesomeAPI (economia.awesomeapi.com.br) |
| Testes | pytest + pytest-cov |
| Manipulacao de Dados | pandas, numpy |

---

## Instalacao

**Prerequisito**: Python 3.8 ou superior.

**Instalacao rapida com script:**

```bash
git clone https://github.com/Thiago-Bonierski/Sistema_trading.git
cd Sistema_trading
bash install.sh
```

O script cria o ambiente virtual (opcional), instala dependencias, inicializa o banco de dados SQLite e configura o `.env` a partir do `.env.example`.

**Instalacao manual:**

```bash
git clone https://github.com/Thiago-Bonierski/Sistema_trading.git
cd Sistema_trading

python -m venv venv
source venv/bin/activate      # Linux/Mac
# ou: venv\Scripts\activate   # Windows

pip install -r requirements.txt
python -c "from database import init_database; init_database()"
cp .env.example .env
```

---

## Configuracao

Copie `.env.example` para `.env` e preencha as variaveis necessarias:

```env
# Telegram (opcional — sistema funciona sem)
TELEGRAM_TOKEN=seu_token_aqui
CHAT_ID=seu_chat_id_aqui

# Dashboard
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=False

# Token de controle remoto do dashboard
CONTROL_TOKEN=escolha_um_token_seguro

# Logging
LOG_LEVEL=INFO
```

Todos os parametros operacionais (stop-loss, take-profit, thresholds de regime, limites de risco, intervalo de monitoramento, etc.) sao configurados diretamente em `config.py` com documentacao inline.

---

## Uso

**Iniciar o sistema completo (monitor + dashboard):**

```bash
python app.py
```

O monitor inicia em thread separada e o dashboard fica acessivel em `http://127.0.0.1:5000`.

**Executar simulacao:**

```bash
python simular.py
```

**Executar demonstracao dos modulos:**

```bash
python demo.py
```

**Executar testes:**

```bash
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

---

## Decisoes de Design

**Thread safety no SQLite**: SQLite nao suporta multiplas conexoes simultaneas com seguranca. O `DatabaseManager` resolve isso com um `threading.Lock` global e context manager que garante atomicidade de cada operacao, sem depender de ORMs.

**Fallback de ML sem dependencia**: O `MLClassifier` opera com heuristica propria quando `scikit-learn` ou `joblib` nao estao instalados. O sistema nunca para por ausencia de dependencias opcionais.

**Configuracao centralizada**: Todos os magic numbers estao em `config.py`. Nenhum threshold de estrategia, parametro de risco ou configuracao de API esta embutido no codigo das classes.

**Protecao por data gap**: Posicoes abertas sao encerradas automaticamente se mais de 10 minutos se passarem sem dados validos. Isso evita que o sistema fique "cego" com posicoes ativas durante quedas de API ou rede.

**Separacao entre simulacao e producao**: O modulo `simular.py` tem seu proprio `PositionManager` e `EquityManager` desacoplados das instancias de producao em `monitor.py`. Nao ha estado compartilhado entre os dois modos.

**Shutdown gracioso**: O controle de `stop_event` (threading.Event) permite encerrar o loop de monitoramento sem matar o processo Flask, mantendo o dashboard disponivel para auditoria pos-shutdown.

---

## Licenca

Uso pessoal e educacional. Nao constitui recomendacao de investimento.