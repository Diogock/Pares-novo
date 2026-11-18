# pairs-ibra — Modelo de Pairs Trading na B3 (universo IBRA)

> Documento-mestre do projeto. O Claude Code lê este arquivo no início de cada sessão.
> Ele é a fonte da verdade para escopo, metodologia, arquitetura e convenções.
> Quando uma decisão mudar, atualize este arquivo no mesmo PR.

---

## 1. Objetivo

Construir, testar e operar um modelo sistemático de **pairs trading / arbitragem estatística** em ações da B3. O universo é a carteira do **Índice Brasil Amplo (IBRA)**.

O modelo precisa:

1. Gerar sinais diários de abertura e fechamento de pares market neutral.
2. Ter backtest walk-forward sem look-ahead, com custos realistas da B3 (corretagem, slippage, aluguel BTC).
3. Ser **complementar** às estratégias que o fundo L&S já roda (tendência setorial, tendência temática, mean reverting, arbitragem de OPA, momentum). A correlação com elas é uma métrica de aceite.
4. Rodar em produção: um script diário lê os dados, atualiza os pares e emite o book de ordens sugerido.

Fora do escopo na v1: intraday, opções, futuros de índice como hedge e execução automática na corretora.

---

## 2. Base acadêmica (resumo do que o modelo replica)

| Bloco | Referência principal | O que usamos |
|---|---|---|
| Distância | Perlin (2009), Pontuschka & Perlin (2015) | Seleção por menor SSD de preços normalizados; frequência diária |
| Cointegração | Caldeira & Moura (2013), RBFin 11(1) | EG + Johansen, ranking por Sharpe in-sample, top 20, z ±2, saída −0,5/+0,75, stop 7% e 50 dias |
| Estacionariedade robusta | Cavalcanti et al. (2021), RCF | Res. estacionário em ≥2 de 3 testes (ADF, PP, KPSS); stop 4σ; stop de tempo |
| Mesmo setor / ON-PN | Takimoto (2007) | Restrição setorial opcional; separar pares ON/PN; execução em D+1 |
| Meia-vida OU | Venturini & Moraes (2024) | Filtro de meia-vida; stop de tempo proporcional |
| Hedge dinâmico | Moura & Pizzinga (2016), Senna (2007) | γ via Kalman (fase 2) |
| Cestas | Soto & Ruilova (2017) | PCA + VECM (fase 3, opcional) |

Lição central da literatura brasileira: **os custos e a execução em D+1 destroem boa parte do retorno.** No Takimoto, o top 5 cai de ~20,9% para ~4,7% a.a. Toda decisão do modelo deve ser avaliada **líquida de custos e com execução defasada**.

---

## 3. Universo

### 3.1 Definição
- Ações que compõem o **IBRA** em cada data. A composição é **point-in-time**, pela carteira teórica vigente no quadrimestre, para evitar viés de sobrevivência.
- Uma ação só entra em um par na data *t* se estiver no IBRA em *t*.

### 3.2 Filtros de elegibilidade (aplicados em cada janela de formação)
| Filtro | Default | Parâmetro |
|---|---|---|
| Volume financeiro médio 63d (antes de *t*) | ≥ R$ 10 mi/dia | `universe.min_adtv_brl` |
| Dias com negócio na janela de formação | ≥ 98% | `universe.min_trading_days_pct` |
| Preço mínimo (fechamento **sem ajuste** em t−1) | ≥ R$ 2,00 | `universe.min_price` |
| Disponível para aluguel (BTC) | Taxa ≤ 5% a.a. Sem base histórica: usa o fallback de 3% (todos passam) | `universe.max_btc_rate` |
| Evento corporativo pendente (OPA, fusão, cisão) | Desligado na v1 (sem base de eventos) | `universe.exclude_events` |

Sem composição histórica do IBRA, o plano B é `universe.source: liquidity_proxy`: a cada quadrimestre (jan/mai/set) entram os `proxy_top_n` (150) maiores em volume financeiro médio da janela anterior.

### 3.3 Classificação
- Setor, subsetor e segmento pela **classificação setorial B3**, mantida no Excel auxiliar editável `configs/sectors.xlsx` (estática, sem histórico na v1).
  - Aba `setores`: `ticker | setor | subsetor | segmento | emissor`. Ticker sem linha recebe `SEM_SETOR`.
  - Aba `de_para`: `ticker_antigo | ticker_novo | data_troca`. O ticker antigo é descartado (o export tem a história inteira duplicada nos dois).
  - Aba `exclusoes`: tickers ignorados manualmente.
  - `scripts/make_sectors_template.py` gera ou completa o Excel a partir dos tickers do export.
- Flag `same_issuer` pela coluna `emissor`, que por default é a raiz do ticker (PETR3/PETR4 → PETR). Esses pares **entram no book** (D3) e são reportados **separadamente**.

## 4. Dados

### 4.1 Fonte e formato
- Primária: **Bloomberg**, exportada em `.txt` para `data/raw/`. Toda leitura passa por `src/pairs_ibra/data/loaders.py`.
- Formato wide dos `.txt` de ativos (cerca de 300 colunas):
  ```
  Dates,Petr4 BZ Equity,Vale3 BZ Equity,...
  02/01/2008,10.51,#N/A,...
  ```
  - Separador `,`. Datas `dd/mm/aaaa`. Faltantes `#N/A`. Tickers `Xxxx4 BZ Equity`, normalizados para `XXXX4`.
  - As datas incluem **todos os dias úteis da semana**. Feriados B3 são removidos pelo calendário `BVMF` (`exchange_calendars`).
  - Ações deslistadas fazem parte do export (sem viés de sobrevivência).

| Arquivo em `data/raw/` | Conteúdo | Campo Bloomberg |
|---|---|---|
| `prices_adj.txt` | Fechamento ajustado por **todos** os proventos e eventos | RT116 |
| `prices_raw.txt` | Fechamento **sem ajuste** (lote, preço mínimo, volume financeiro) | PX_LAST sem ajuste |
| `volume.txt` | Quantidade negociada. Volume financeiro = qtd × preço sem ajuste (`data.volume_kind: shares`; `brl` se já vier em R$) | PX_VOLUME |
| `market.txt` | `Dates`, CDI em **índice acumulado**, IBOV e IBRA em fechamento | colunas em `data.market_columns` |
| `ibra_composition.txt` | Longo `data;ticker;peso`, uma linha por ação em cada rebalanceamento (jan/mai/set) | `INDX_MWEIGHT_HIST` + `END_DATE_OVERRIDE` |
| `configs/sectors.xlsx` | Excel auxiliar (seção 3.3) | — |

- Não há VWAP nem abertura na v1: o modelo opera **só no fechamento**. A execução por VWAP fica como opção (`data.files.vwap` + `signal.execution: vwap_t1`).
- Não há série de NAV das estratégias do fundo na v1: a correlação com elas fica para quando houver dados.

### 4.2 Tabelas (parquet em `data/processed/`, gerado por `scripts/build_dataset.py`)
| Tabela | Chave | Colunas |
|---|---|---|
| `prices` | `date, ticker` | `close_adj, close_raw, volume_brl, traded` |
| `ibra_composition` | `date, ticker` | `in_index` (vigência quadrimestral expandida para diário) |
| `sectors` | `ticker` | `setor, subsetor, segmento, emissor` |
| `market` | `date` | `cdi_daily, ibov_close, ibra_close, cdi_index` |

### 4.3 Regras de dados
- Preços **ajustados por proventos e eventos**. Teste: nenhum retorno diário > |40%| (`data.max_abs_daily_return`). Se aparecer, é erro crítico no `quality_report.md`.
- Dados faltantes: forward-fill de no máximo 1 dia (`data.max_ffill_days`). Acima disso, o ativo fica inelegível na janela. Se uma perna aberta fica sem preço, o par é fechado (`dado_faltante`).
- Séries duplicadas (retornos idênticos em ≥ 90% dos dias) são detectadas. A de menor histórico é removida, com aviso (`data.auto_drop_duplicates`).
- `data/raw/` e `data/processed/` nunca são versionados. Só `data/sample/` (sintético, gerado por `scripts/generate_sample.py`) é versionado.

## 5. Metodologia

### 5.1 Pipeline (walk-forward)

```
Universo(t) → Formação [t−F, t) → Seleção → Spread/z → Sinal → Trading [t, t+T) → rola
```

| Parâmetro | Default | Origem |
|---|---|---|
| Janela de formação `F` | 252 dias úteis | Caldeira; Cavalcanti |
| Janela de trading `T` | 63 dias úteis (rebalanceamento trimestral de pares) | Caldeira usa 84 |
| Reestimação | A cada `T`, com pares abertos herdados até fechar | — |

### 5.2 Seleção de pares

Etapa A, pré-filtro (reduz combinações):
- Todos os pares do universo elegível ou só intra-setor (`selection.same_sector: true|false`).
- Correlação de retornos na formação ≥ `selection.min_corr` (default 0,5).

Etapa B, métodos (plugáveis, um módulo cada):
1. **`distance`**: SSD entre preços normalizados (base 1 no início da janela). Ranking crescente.
2. **`cointegration`** (default):
   - Log-preços I(1) por ADF.
   - Regressão `ln P_A = α + γ ln P_B + ε`. Teste nos dois sentidos e fica com a ordem de menor p-valor.
   - Resíduo estacionário em ≥ 2 de 3 testes (ADF, PP, KPSS) a 5%.
   - Exclui γ ≤ 0.
3. **`kalman`** (fase 2): γ_t e α_t como estados (random walk) e spread como inovação.

Etapa C, filtros de qualidade do spread:
| Filtro | Default |
|---|---|
| Meia-vida OU | 3 ≤ HL ≤ 40 dias |
| Expoente de Hurst do spread | < 0,5 |
| Cruzamentos da média na formação | ≥ 12 |
| γ (hedge ratio) | 0,2 ≤ γ ≤ 5 |

Etapa D, ranking e carteira:
- Score = Sharpe in-sample da própria regra de trading simulada na formação, líquido de custos (Caldeira).
- Top `portfolio.n_pairs` (default 20).
- Restrições: cada ação em no máximo `portfolio.max_pairs_per_stock` = 2 pares, cada setor em no máximo `portfolio.max_sector_pct` = 30% dos pares.

### 5.3 Spread e normalização

```
ε_t = ln P_A,t − γ · ln P_B,t − α
z_t = (ε_t − μ_ε) / σ_ε
```

- `μ_ε` e `σ_ε` vêm da formação e ficam **fixos** no trading (default).
- Alternativa configurável: EWMA móvel (`signal.zscore_mode: fixed|ewma`, λ = 0,97).

Meia-vida OU:
```
Δε_t = a + b · ε_{t−1} + u_t ;  HL = −ln(2) / ln(1 + b)
```

### 5.4 Regras de sinal (máquina de estados por par)

| Estado atual | Condição | Novo estado / ação |
|---|---|---|
| FLAT | z ≤ −`entry_z` (2,0) | LONG_SPREAD: compra A, vende γ·B |
| FLAT | z ≥ +`entry_z` | SHORT_SPREAD: vende A, compra γ·B |
| LONG_SPREAD | z ≥ −`exit_z_long` (0,5) | FLAT (convergência) |
| SHORT_SPREAD | z ≤ `exit_z_short` (0,75) | FLAT (convergência) |
| Qualquer aberto | \|z\| ≥ `stop_z` (4,0) | FLAT (stop de spread) |
| Qualquer aberto | Perda do par ≥ `stop_loss_pct` (7%) | FLAT (stop financeiro) |
| Qualquer aberto | Dias abertos ≥ `time_stop_days` (50; ver D6) | FLAT (stop de tempo) |
| Qualquer aberto | Par perde cointegração no reteste rolante | FLAT (quebra estrutural) |
| Qualquer | Ação sai do IBRA ou entra em evento corporativo | FLAT |

Regras adicionais:
- **Sem reentrada** no mesmo par por `cooldown_days` (5) após stop.
- O sinal é calculado no fechamento de *t* e **executado no fechamento de t+1** (default; alternativa: VWAP de t+1 se houver arquivo). Nunca no mesmo fechamento.
- Não entra se |z| ≥ `stop_z`.
- Cooldown só após stops (spread, financeiro, tempo, quebra estrutural); convergência permite reentrada.
- Stop financeiro: PnL do par / notional médio por perna na entrada.
- Quebra estrutural: a cada rebalanceamento, os pares abertos herdados são retestados (≥ 2 de 3 testes) com o γ e α originais na janela de formação mais recente (`signal.retest_on_rebalance`).
- Pares abertos que saem da seleção continuam com γ, α, μ e σ originais até fechar, sem novas entradas.

### 5.5 Sizing

- Cada perna recebe, em média, **1% do NAV** (`sizing.leg_pct_nav`), no NAV do dia da execução. O bruto por par é de 2% do NAV, e 20 pares somam ~40% bruto.
- Proporção entre as pernas, configurável (`sizing.mode`), sempre preservando o bruto de 2%:
  - `gamma` (default): valor de B = γ × valor de A (A = 2/(1+γ), B = 2γ/(1+γ) da base).
  - `dollar`: pernas iguais em R$.
  - `beta`: neutro em beta contra o IBRA (β de 252d).
- Teto de exposição bruta: `portfolio.max_gross_leverage` (2× NAV). Entradas que estourariam o teto não são feitas.
- Lote padrão da B3 (100), arredondado pelo preço **sem ajuste**. Resíduo < 1 lote é ignorado.
- Sem rebalancear as pernas durante a vida do par (Caldeira).

### 5.6 Custos (modelo único em `costs.py`)
| Item | Default |
|---|---|
| Negociação (corretagem + emolumentos + slippage) | **4 bps sobre cada R$ negociado**: girar 100% do NAV custa 4 bps (`costs.trading_cost_bps`) |
| Aluguel BTC | 3% a.a. sobre a perna vendida, por pregão (base 252). Sem taxa histórica na v1 |
| Caixa | Todo o caixa (inclusive o da venda a descoberto) rende **CDI − 4 bps a.a.** (`costs.cash_spread_bps`) |

O mesmo custo vale para o período inteiro desde 2008.

## 6. Backtest

- Motor event-driven diário em `src/pairs_ibra/backtest/engine.py`.
- Walk-forward estrito: nenhuma função de seleção recebe dados com `date ≥ t`. Isso é garantido por teste (`tests/test_no_lookahead.py`).
- Período: dados desde **2008-01-02**. A primeira formação usa 2008 e o trading começa em jan/2009.
  - **2009–2012: calibração** (onde se testam parâmetros).
  - **2013 em diante: OOS puro**, que não é usado para escolher nada.
- Contabilidade: NAV = caixa + Σ valor das pernas (com sinal). Retorno reportado total e em excesso de CDI. Sharpe em excesso de CDI, calculado **sobre o capital**.
- Saídas por rodada em `results/<run_id>/`: `trades.parquet`, `positions.parquet`, `nav.parquet`, `pairs_selected.parquet`, `config.yaml` (cópia exata) e `report.html`.

### 6.1 Métricas
- Retorno anual líquido, vol, Sharpe (excesso sobre CDI), Sortino, drawdown máximo e duração.
- Hit rate, retorno médio por trade, duração média, % de saídas por convergência, stop ou tempo.
- Turnover e custo total (% do retorno bruto consumido).
- Beta e correlação contra Ibovespa e IBRA.
- **Correlação com as estratégias do fundo** (NAV diário, uma coluna por estratégia, em `data/external/`). Ainda sem dados na v1.
- Decomposição: pares ON/PN vs demais, intra-setor vs cross-setor, por setor.

### 6.2 Robustez
- Bootstrap de pares aleatórios com o mesmo nº de trades e a mesma duração (Perlin, Caldeira).
- White's Reality Check e Hansen SPA sobre o grid de parâmetros.
- Sensibilidade: `entry_z` ∈ {1,5; 2,0; 2,5}, `F` ∈ {126, 252, 504}, `n_pairs` ∈ {10, 20, 30}, execução em close t+1 vs VWAP t+1.
- Subperíodos: 2009–2012, 2013–2016, 2017–2019, 2020–2022, 2023 em diante.

---

## 7. Arquitetura do repositório

```
pairs-ibra/
├── CLAUDE.md                  # este arquivo
├── README.md                  # visão para humanos: como instalar e rodar
├── pyproject.toml
├── configs/
│   ├── base.yaml              # defaults deste documento
│   ├── sectors.xlsx           # Excel auxiliar de setores (editável)
│   └── experiments/           # um yaml por experimento
├── data/
│   ├── raw/                   # (gitignored) exports Bloomberg
│   ├── processed/             # (gitignored) parquet normalizado
│   ├── external/              # (gitignored) séries do fundo
│   └── sample/                # dados sintéticos para testes (versionado)
├── src/pairs_ibra/
│   ├── config.py              # pydantic: carrega e valida yaml
│   ├── data/
│   │   ├── loaders.py         # Bloomberg → DataFrame padronizado
│   │   ├── universe.py        # IBRA point-in-time + filtros
│   │   ├── validation.py      # checagens de qualidade
│   │   └── synthetic.py       # dados sintéticos no formato Bloomberg
│   ├── selection/
│   │   ├── base.py            # interface PairSelector
│   │   ├── scoring.py         # Sharpe in-sample da regra (ranking)
│   │   ├── distance.py
│   │   ├── cointegration.py
│   │   └── kalman.py
│   ├── spread/
│   │   ├── stats.py           # z-score, meia-vida, Hurst, crossings
│   │   └── tests.py           # ADF, PP, KPSS, Johansen wrappers
│   ├── signal/
│   │   └── state_machine.py   # regras da seção 5.4
│   ├── portfolio/
│   │   ├── sizing.py
│   │   └── constraints.py
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── costs.py
│   │   ├── metrics.py
│   │   ├── report.py          # relatório HTML
│   │   └── io.py              # grava results/<run_id>/
│   ├── research/
│   │   ├── bootstrap.py
│   │   └── spa.py
│   └── live/
│       └── daily_run.py       # gera book do dia
├── notebooks/                 # exploração; nada de lógica de produção aqui
├── scripts/
│   ├── build_dataset.py
│   ├── generate_sample.py
│   ├── make_sectors_template.py
│   ├── run_backtest.py        # --config configs/experiments/x.yaml
│   └── daily_signals.py
├── tests/
└── results/                   # (gitignored)
```

### 7.1 Interfaces-chave

```python
class PairSelector(Protocol):
    # log-preços; só usa datas < asof (assert em formation_window). Devolve candidatos
    # ranqueados por score; as restrições de carteira são aplicadas depois (constraints.py).
    def select(self, log_prices: pd.DataFrame, universe: list[str], asof: pd.Timestamp,
               cfg: Config, sectors: pd.DataFrame) -> list[PairSpec]: ...

@dataclass(frozen=True)
class PairSpec:
    leg_a: str
    leg_b: str
    gamma: float
    alpha: float
    mu: float
    sigma: float
    half_life: float
    method: str
    formation_start: pd.Timestamp
    formation_end: pd.Timestamp
    same_issuer: bool
    same_sector: bool
    score: float
    sector_a: str = ""
    sector_b: str = ""
    pvalue: float = nan          # Engle-Granger (cointegração) ou SSD (distância)
    n_trades_in_sample: int = 0
```

---

## 8. Configuração

A fonte da verdade dos defaults é `configs/base.yaml`, validado por `config.py` (pydantic, chaves desconhecidas são erro). Experimentos ficam em `configs/experiments/*.yaml` com `extends: ../base.yaml`, e cada um sobrescreve só o que muda (ex.: `intra_setor.yaml`, `distancia.yaml`, `sample.yaml`).

Como rodar:
```
python scripts/make_sectors_template.py --prices data/raw/prices_adj.txt   # 1ª vez
python scripts/build_dataset.py --config configs/base.yaml                 # .txt → parquet + quality_report.md
python scripts/run_backtest.py  --config configs/base.yaml                 # results/<run_id>/
```

## 9. Convenções de código

- Python 3.11+, `pandas`, `numpy`, `statsmodels`, `arch` (testes PP/KPSS), `pydantic`, `pyarrow`. `numba` só se o profiling pedir.
- Formatação e lint com `ruff`. Tipagem com `mypy --strict` em `src/`. Testes com `pytest`.
- Funções puras sempre que possível. Estado só no `engine` e na `state_machine`.
- Datas sempre em `pd.Timestamp` sem timezone, no calendário B3 (`exchange_calendars`, `BVMF`).
- Nada de parâmetro mágico no código: tudo vem do yaml validado pelo `config.py`.
- Logs com `logging`. Prints não entram em `src/`.
- Cada PR que muda resultado de backtest anexa a tabela de métricas antes e depois.

### 9.1 Regras para o Claude Code
1. Antes de implementar um módulo, ler a seção correspondente deste arquivo e os testes existentes.
2. Implementar com teste junto (TDD quando possível). Todo cálculo estatístico tem teste contra caso sintético com resposta conhecida (ex.: par OU simulado com HL conhecida).
3. Nunca usar dados de `t` ou posteriores na seleção ou no sinal de `t`. Em caso de dúvida, adicionar assert.
4. Não alterar defaults deste documento sem pedido explícito. Se um teste empírico sugerir mudança, propor no PR.
5. Commits pequenos, em português, com prefixo: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `research:`.

---

## 10. Roadmap (cada item vira issue no GitHub)

### Fase 0: fundação
- [x] Estrutura do repo, `pyproject`, CI (GitHub Actions: ruff + mypy + pytest)
- [x] `config.py` com pydantic e `base.yaml`
- [x] Gerador de dados sintéticos (`data/sample/`) com pares cointegrados conhecidos

### Fase 1: dados e universo
- [x] Loader Bloomberg → parquet (preços, volume, composição IBRA, setores, CDI). BTC e eventos: sem base na v1
- [x] `universe.py`: IBRA point-in-time + filtros da 3.2 (+ plano B por liquidez)
- [x] `validation.py`: checagens de ajuste, gaps, outliers e duplicatas
- **Aceite:** universo elegível por data reproduzível; relatório de qualidade sem erro crítico

### Fase 2: seleção e sinal (cointegração)
- [x] `spread/tests.py` e `spread/stats.py` com testes sintéticos
- [x] `selection/cointegration.py` e `selection/distance.py`
- [x] `signal/state_machine.py` (seção 5.4 completa, 100% de cobertura)
- **Aceite:** em dados sintéticos, recupera ≥ 90% dos pares plantados; máquina de estados com 100% de cobertura de transições
  - Status: recall de ~77% no default e ~87% sem o pré-teste I(1) (HL plantada de 4–7 dias). Ver D9.

### Fase 3: backtest
- [x] `engine.py`, `costs.py`, `sizing.py`, `constraints.py`
- [x] `metrics.py` + relatório HTML
- [x] `test_no_lookahead.py`
- **Aceite:** replicar a ordem de grandeza de Caldeira & Moura (2013) no período 2006–2012 com os parâmetros deles (sanity check, não meta de retorno)

### Fase 4: robustez e complementaridade
- [ ] Bootstrap de pares aleatórios, Reality Check / SPA
- [ ] Grid de sensibilidade e subperíodos
- [ ] Correlação com as estratégias do fundo
- **Aceite:** Sharpe líquido OOS > 0,8 com execução t+1; correlação < 0,3 com a estratégia de mean reverting atual (metas a confirmar)

### Fase 5: extensões
- [ ] Hedge dinâmico via Kalman
- [ ] Cestas PCA + VECM
- [ ] Slippage como função de ADTV e participação no volume

### Fase 6: produção
- [ ] `daily_signals.py`: book do dia (pares abertos, novos sinais, saídas, ordens em lotes)
- [ ] Monitor: z-score, PnL por par, alertas de quebra de cointegração

---

## 11. Decisões

| # | Decisão | Opções | Situação |
|---|---|---|---|
| D1 | Composição histórica do IBRA | Bloomberg (`INDX_MWEIGHT_HIST`) vs carteiras teóricas da B3 | Bloomberg, a puxar. Plano B: proxy de liquidez |
| D2 | Pares só intra-setor? | Sim / não / ambos como experimentos | **Ambos** (`configs/experiments/intra_setor.yaml`) |
| D3 | Incluir pares ON/PN no book? | Sim / não / só em relatório | **Sim**, reportados à parte |
| D4 | Preço de execução | VWAP t+1 / abertura t+1 / fechamento t+1 | **Fechamento t+1**, com opção de VWAP |
| D5 | Sizing | gamma / dollar / beta | **1% do NAV por perna**, proporção por γ |
| D6 | Stop de tempo | Fixo de 50 dias vs múltiplo da meia-vida | **50 dias fixo**, configurável |
| D7 | Taxa BTC histórica | Fonte disponível? | **3% a.a.** fixo |
| D8 | Metas de aceite da fase 4 | Sharpe, correlação, capacidade | A definir com o gestor |
| D9 | Pré-teste I(1) por ADF em cada perna | Manter / remover | Em aberto: custa ~10% de recall em dados sintéticos (`selection.require_i1`) |
| D10 | Custos e caixa | — | **4 bps por R$ negociado**; caixa a CDI − 4 bps a.a. |

## 12. Referências

- Caldeira, J. F.; Moura, G. V. (2013). *Selection of a Portfolio of Pairs Based on Cointegration*. RBFin 11(1). https://periodicos.fgv.br/rbfin/article/view/4785
- Perlin, M. S. (2009). *Evaluation of pairs trading strategy at the Brazilian financial market*. JDHF 15(2). https://mpra.ub.uni-muenchen.de/8308/
- Pontuschka, M.; Perlin, M. S. (2015). *A estratégia de pares no mercado acionário brasileiro: o impacto da frequência de dados*. RAM 16(2).
- Cavalcanti, R. S. G. et al. (2021). *Composition of portfolios by pairs trading with volatility criteria in the Brazilian market*. RCF. https://scielo.br/j/rcf/a/9jSxzDNt5vDqQr3JXdyMS6G/
- Takimoto, E. (2007). *A estratégia pairs trading no mercado de ações brasileiro*. Ibmec SP.
- Soto, P. A.; Ruilova Teran, J. C. (2017). *Arbitragem Estatística: Uma Abordagem por VECM*. RBFin 15(4).
- Venturini, L. S.; Moraes, G. I. (2024). *Pairs trading aplicado ao mercado de capitais brasileiro: cointegração e Ornstein-Uhlenbeck*. RACEF 15(1).
- Moura, C. E. S.; Pizzinga, A. et al. (2016). *A pairs trading strategy based on linear state space models and the Kalman filter*. Quantitative Finance.
- Gatev, E.; Goetzmann, W.; Rouwenhorst, K. G. (2006). *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*. RFS 19(3).
- Vidyamurthy, G. (2004). *Pairs Trading: Quantitative Methods and Analysis*. Wiley.
