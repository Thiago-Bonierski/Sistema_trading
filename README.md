# Sistema de Trading Automatizado — Python

Bot de trading algoritmico para monitoramento e operacao em multiplos pares de ativos financeiros (USD/BRL, BTC/BRL, ETH/BRL, SOL/BRL), com deteccao de regime de mercado, multiplas estrategias, filtro por Machine Learning, controle de risco adaptativo e dashboard web em tempo real.

---

## Visao Geral

O sistema opera em ciclos de monitoramento a cada 20 segundos, coletando cotacoes via API publica (AwesomeAPI), identificando o regime de mercado vigente, executando as estrategias adequadas para aquele regime e filtrando os sinais gerados por um classificador ML antes de tomar qualquer decisao de entrada ou saida de posicao. Todo o fluxo e auditado em logs rotativos e pode ser acompanhado em tempo real por um painel moderno em React (ou pelo dashboard Flask legado).

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

### Painel de Controle (React + Flask API)

O projeto inclui um painel moderno em `frontend/` (Vite + React + TailwindCSS +
Lucide) que conversa com o motor Python por uma API REST em Flask. O motor
permanece 100% intacto: o painel apenas orquestra os mesmos modulos de producao.

O painel e dividido em quatro abas:

| Aba | Conteudo |
|---|---|
| **Sala de Controle** | Status do motor (Ativo/Pausado), Start/Pause, **Panic Close**, saude do ML, cards de USD/BTC/ETH/SOL (preco, regime, sinal, posicao e SL/TP), KPIs de equity/win rate/drawdown e trades recentes. |
| **Laboratorio de Simulacao** | Formulario de Ativo, Fonte (sintetico/banco/API), Ticks, Seed e Capital; funil de decisoes (sinais brutos → aprovados → executados e bloqueios por filtro); comparativo **RESEARCH vs PAPER_TRADING**; tabela auditavel de trades e historico de relatorios. |
| **Calibragem Visual** | Secoes Stop/TP, Multiplicador Cripto, Limites de Risco, Filtros de Regime, Filtros de Exaustao e ML. Alteracoes so entram em vigor em **Salvar e Aplicar** (atomico) e podem ser revertidas com **Restaurar Padroes**. |
| **ML & Console** | Status do RandomForest (modo modelo/heuristica, acuracia, amostras, threshold, features), botao **Retreinar Agora** e console de logs com filtro INFO/WARNING/ERROR, busca textual e auto-refresh. |

O frontend roda em `http://127.0.0.1:5173` e faz proxy de `/api` para o Flask em
`http://127.0.0.1:5000` (configurado em `frontend/vite.config.js`). A API habilita
CORS para permitir acesso direto quando necessario.

Endpoints REST disponiveis:

| Rota | Metodo | Descricao |
|---|---|---|
| `/` | GET | Dashboard legado (template Flask) |
| `/dados_atualizados` | GET | JSON com dados de todos os ativos e KPIs |
| `/health` | GET | Health check da aplicacao |
| `/api/status` | GET | Status consolidado: motor, ML, equity e risco |
| `/api/live` | GET | Snapshot ao vivo: cards por ativo, KPIs e trades recentes |
| `/api/config` | GET/POST | Le e aplica a configuracao dinamica (validada e aplicada em tempo real) |
| `/api/config/reset` | POST | Restaura todos os parametros para os padroes de `config.py` |
| `/api/simulate` | POST | Executa RESEARCH + PAPER_TRADING no motor real |
| `/api/simulations` | GET | Lista os relatorios de simulacao salvos |
| `/api/simulations/<arquivo>` | GET | Conteudo de um relatorio especifico (apenas `.json`) |
| `/api/monitor/toggle` | POST | Inicia, pausa ou alterna o loop de monitoramento |
| `/api/positions/close-all` | POST | Panic Close: fecha todas as posicoes abertas |
| `/api/ml/status` | GET | Estado do classificador (modelo/heuristica, metricas) |
| `/api/ml/train` | POST | Retreina o RandomForest e recarrega o modelo no monitor |
| `/api/logs` | GET | Ultimas linhas de log com filtros `level`, `search`, `lines` e `file` |
| `/api/shutdown_monitor` | POST | Para o loop de monitoramento (Flask continua ativo) |
| `/api/exit_process` | POST | Encerra o processo inteiro |

Operacoes pesadas sao serializadas: simulacoes e treinos concorrentes retornam
`HTTP 409`, e payloads invalidos retornam `HTTP 400` sem alterar o estado.

### Configuracao Dinamica (runtime_config.py)

Os parametros operacionais (stops, take-profit, multiplicador cripto, limites de
risco, filtros de regime/exaustao e ML) podem ser ajustados **em tempo real**,
sem reiniciar o servidor, pela aba Calibragem ou pela API.

- `runtime_config.py` define um `ParameterSpec` por parametro (tipo, limites,
  descricao e categoria), valida tipos/limites/consistencia e aplica os valores
  no modulo `config` de forma thread-safe (`RLock`).
- Overrides persistentes ficam em `runtime_config.json` (gravacao atomica via
  `.tmp` + `os.replace`). O arquivo e ignorado pelo git.
- Ao salvar, o gerenciador sincroniza ao vivo `PositionManager`, `RiskController`,
  `MLClassifier` e as engines do orquestrador, sem tocar no codigo Python.
- A aplicacao e atomica: se qualquer valor for invalido, nada e alterado.
- `Restaurar Padroes` remove todos os overrides e reaplica os defaults de
  `config.py` imediatamente.

Parametros percentuais sao fracoes no arquivo: `0.008` equivale a `0,8%`.

### Banco de Dados

O `DatabaseManager` em `database.py` resolve o problema classico de race conditions em SQLite com multiplas threads: usa um lock global e context manager que garante commit e rollback automaticos. A `row_factory` retorna dicionarios em vez de tuplas, facilitando o acesso por nome de coluna.

Tabelas principais: `cotacoes` (historico de preco e recomendacao por ativo) e `trade_history` (resultado de cada trade executado com PnL, duracao e regime).

### Notificacoes Telegram

O `monitor_base.py` envia alertas de abertura e fechamento de trades, mudancas de regime relevantes, relatorios de KPIs periodicos e resumo completo de estado ao encerrar o sistema.

### Simulacao

O `simular.py` oferece dois modos de execucao sobre dados historicos:

- **RESEARCH**: modo agressivo com ate 5 posicoes simultaneas, max_age de 100 ticks, sem controle de risco rigoroso — para explorar o potencial de estrategias
- **PAPER_TRADING**: modo conservador com 1 posicao, max_age de 15 ticks, nivel REDUCED — simula comportamento proximo ao ambiente de producao

`run_dual_simulation()` roda os dois modos sobre os mesmos dados e devolve o
comparativo (`_build_comparison`), incluindo a lista auditavel de trades de cada
modo (entrada, saida, engine, regime, confianca, motivo e PnL) e o funil de
decisoes (`_funnel_report`). O painel usa exatamente esse payload para montar a
aba Laboratorio. Cada execucao gera um relatorio JSON em `simulation_reports/`;
trades completos tambem ficam em SQLite para analise pontual.

### Manutencao Automatica

O `utils/maintenance.py` rotaciona automaticamente relatorios antigos (limite de 10 simulacoes e 20 relatorios de treino), remove arquivos com mais de 7 dias e monitora uso de disco.

---

## Estrutura do Projeto

```
Sistema_trading/
|
|-- app.py                  # API Flask + orquestra Monitor + MLTraining + Flask
|-- run.sh                  # Sobe backend + painel React em paralelo
|-- config.py               # Configuracoes e defaults (fonte dos parametros)
|-- runtime_config.py       # Configuracao dinamica validada e persistida
|-- database.py             # DatabaseManager thread-safe
|-- equity.py               # EquityManager (capital, drawdown, retorno)
|-- exhaustion_filter.py    # Filtro de exaustao (thresholds via config)
|-- kpis.py                 # KPITracker (metricas de performance)
|-- logging_config.py       # Logging com rotacao, niveis e funcoes estruturadas
|-- market_regime.py        # Deteccao de regime de mercado
|-- ml_classifier.py        # Filtro ML de sinais
|-- ml_training.py          # Treinamento periodico do modelo
|-- monitor.py              # Loop principal de monitoramento
|-- monitor_base.py         # Cliente de API e Telegram
|-- position_manager.py     # Ciclo de vida de posicoes
|-- risk_control.py         # RiskController com kill-switch
|-- simular.py              # Engine de simulacao + run_dual_simulation
|-- strategy_unified.py     # Engines + Orquestrador de estrategias
|-- demo.py                 # Script de demonstracao dos modulos
|-- requirements.txt
|-- install.sh
|
|-- frontend/               # Painel moderno (Vite + React + TailwindCSS)
|   |-- index.html
|   |-- package.json
|   |-- vite.config.js      # Proxy /api -> http://127.0.0.1:5000
|   |-- tailwind.config.js
|   |-- src/
|       |-- main.jsx
|       |-- App.jsx         # Shell, header e navegacao das 4 abas
|       |-- api.js          # Cliente HTTP dos endpoints
|       |-- index.css       # Tema escuro e componentes base
|       |-- components/     # UI compartilhada (cards, badges, alertas)
|       |-- lib/format.js   # Formatadores pt-BR (moeda, percentual, datas)
|       |-- tabs/           # ControlRoom, SimulationLab, Calibration, MlConsole
|
|-- templates/              # Dashboard legado (Flask)
|   |-- index.html
|
|-- static/
|   |-- dashboard.js        # Logica do dashboard legado
|   |-- style.css
|
|-- tests/
|   |-- test_api.py             # Runtime config + 52 testes dos endpoints
|   |-- test_concurrency.py
|   |-- test_equity.py
|   |-- test_filters.py
|   |-- test_market_regime.py
|   |-- test_ml_pipeline.py
|   |-- test_persistence.py
|   |-- test_pipeline_parity.py
|   |-- test_simulation.py
|
|-- utils/
    |-- maintenance.py      # Limpeza e rotacao de arquivos
```

---

## Stack Tecnologica

| Camada | Tecnologia |
|---|---|
| Linguagem (motor) | Python 3.8+ |
| Web Framework (API) | Flask 3.x + flask-cors |
| Banco de Dados | SQLite (built-in) com threading.Lock |
| Machine Learning | scikit-learn (RandomForest, LogisticRegression, Pipeline) |
| Serializacao de Modelo | joblib |
| Painel (frontend) | React 18 + Vite 5 |
| Estilo / Icones | TailwindCSS 3 + Lucide React |
| Dashboard legado | Flask templates + Plotly.js |
| Notificacoes | Telegram Bot API |
| Cotacoes | AwesomeAPI (economia.awesomeapi.com.br) |
| Testes | pytest + pytest-cov |
| Manipulacao de Dados | pandas, numpy |

---

## Instalacao

**Prerequisitos**: Python 3.8+ e, para o painel, Node.js 18+ (com npm).

**Instalacao rapida com script (recomendado):**

```bash
git clone https://github.com/Thiago-Bonierski/Sistema_trading.git
cd Sistema_trading
bash install.sh
```

O script cria o ambiente virtual, instala dependencias (incluindo `python-dotenv`
e `flask-cors`), inicializa o banco de dados SQLite com as tabelas de estado vivo,
cria o `.env` a partir do `.env.example` e executa os testes automatizados.

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

# Painel (o run.sh instala automaticamente na primeira execucao)
cd frontend && npm install && cd ..
```

---

## Arquitetura (Estado Unico e Contratos Rigidos)

O sistema segue uma **Arquitetura Orientada a Estado Unico** com tres garantias:

1. **SQLite como fonte unica de verdade**: posicoes abertas, equity e nivel de risco
   sao persistidos em tabelas `positions`, `system_state` e `risk_state`. No boot,
   o `restore_state()` recupera automaticamente o estado, sobrevivendo a
   reinicializacoes.

2. **Contrato unico de features ML**: o modulo `features.py` define as 8 colunas
   usadas tanto no treino (`ml_training.py`) quanto na inferencia
   (`ml_classifier.py`), eliminando desalinhamentos e data leakage
   (`duration_ticks` foi removido).

3. **Simulacao idêntica à producao**: `simular.py` usa exatamente as mesmas
   engines (`TrendFollowing`, `MeanReversion`, `BreakoutMomentum`),
   filtros (confirmacao de tendencia, exaustao, ML) e o `PositionManager`
   oficial da producao, com seed reproduzivel.

**Thread-safety real**: um `state_lock` (`threading.RLock`) protege o estado vivo
contra leitura concorrente do Flask e escrita do monitor. O Flask le um
snapshot imutavel via `get_state_snapshot()`, evitando `RuntimeError` por
dicionario mutado durante iteracao.

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

# Token de controle remoto do dashboard (use uma senha forte, nao deixe o placeholder)
CONTROL_TOKEN=escolha_um_token_seguro

# Logging
LOG_LEVEL=INFO
```

Obs.: `TELEGRAM_TOKEN` e `CHAT_ID` podem ficar vazios; o sistema desabilita o
Telegram silenciosamente. `CONTROL_TOKEN` nao deve ser o placeholder "password".

Todos os parametros operacionais (stop-loss, take-profit, thresholds de regime,
limites de risco, intervalo de monitoramento, etc.) possuem defaults em
`config.py` com documentacao inline. Ajustes feitos pelo painel/API sao salvos
como overrides em `runtime_config.json` (ignorado pelo git) e reaplicados no boot
seguinte; `POST /api/config/reset` volta aos defaults.

---

## Uso

**Iniciar o painel completo (recomendado):**

```bash
./run.sh
```

O script:

1. ativa o `venv` (falha com instrucao clara se ele nao existir);
2. roda `npm install` automaticamente caso `frontend/node_modules` esteja ausente;
3. sobe o backend Flask (monitor + treinamento ML) e o frontend Vite em paralelo;
4. registra `trap 'kill ...' EXIT INT TERM'` para encerrar toda a arvore de
   processos com `Ctrl+C`, liberando as portas **5000** (API) e **5173** (painel).

Acesse o painel em **http://127.0.0.1:5173**. A API responde em
`http://127.0.0.1:5000`.

**Iniciar somente o motor Python (API + dashboard legado):**

```bash
python app.py
```

O monitor, a thread de treinamento ML e o Flask iniciam juntos. O dashboard
legado fica acessivel em `http://127.0.0.1:5000`.

**Executar simulacao (componentes reais de producao):**

```bash
python simular.py
```

A simulação roda as mesmas engines, filtros e regras de posicao da producao,
com seed reproduzivel.

**Executar demonstracao dos modulos:**

```bash
python demo.py
```

**Executar testes:**

```bash
pytest tests/ -v
pytest tests/ --cov=. --cov-report=term-missing
```

**Build de producao do painel:**

```bash
cd frontend
npm run build   # gera frontend/dist/
```

---

## Decisoes de Design

**Estado unico e persistido**: SQLite guarda posicoes, equity e risco. O sistema
restaura o estado no boot, evitando perda de posicoes abertas e equity em
reinicializacoes.

**Thread-safety no SQLite + estado vivo**: `DatabaseManager` usa um
`threading.Lock` global para SQLite. O `state_lock` (`threading.RLock`) protege
o estado vivo compartilhado entre monitor e Flask.

**Contrato unico de features ML**: `features.py` e a unica fonte de definicao
de features (8 colunas, sem `duration_ticks` — data leakage removido). Treino e
inferencia usam as mesmas colunas, ordem e transformacoes.

**Fallback de ML sem dependencia**: O `MLClassifier` opera com heuristica
quando `scikit-learn` ou `joblib` nao estao instalados. Erros de predicao
reais nao são silenciados (levantam `RuntimeError`).

**Gravacao atomica do modelo**: o pipeline salvo usa `.tmp` + `os.replace` para
evitar leitura de arquivo truncado. O `MLClassifier` recarrega automaticamente
quando o arquivo do modelo muda (hot-reload apos treino).

**Configuracao centralizada**: Todos os magic numbers estao em `config.py`.

**Protecao por data gap**: Posicoes abertas sao encerradas automaticamente se mais
de 10 minutos se passarem sem dados validos.

**Simulacao = producao**: `simular.py` nao usa mais `mock_strategy_signal`;
roda as engines reais e filtros reais do sistema de producao.

**Shutdown gracioso**: O controle de `stop_event` (threading.Event) permite
encerrar o loop de monitoramento sem matar o processo Flask.

**Configuracao dinamica validada**: `runtime_config.py` e a unica porta de entrada
para alterar parametros em tempo real. Tipos, limites e regras de consistencia sao
validados antes de qualquer escrita; a aplicacao e atomica e os overrides sao
persistidos com `os.replace` (sem arquivo truncado).

**Frontend separado do motor**: o painel React nao reimplementa nenhuma regra de
negocio. Ele apenas consome a API Flask, que por sua vez chama os mesmos modulos
usados pela producao — simulacao, filtros e risco permanecem identicos.

---

## Seguranca

- `/api/shutdown_monitor` e `/api/exit_process` exigem `CONTROL_TOKEN` valido,
  comparado com `hmac.compare_digest` (tempo constante).
- Tokens vazios ou placeholders (ex: "password") sao rejeitados.
- O dashboard e a API escutam apenas em `127.0.0.1` por padrao (portas 5000 e 5173).
- O CORS e habilitado na API para o painel em desenvolvimento; mantenha o servidor
  em localhost e nao exponha as portas publicamente.
- `runtime_config.json`, bancos SQLite, logs e relatorios sao ignorados pelo git.

---

## Licenca

Uso pessoal e educacional. Nao constitui recomendacao de investimento.