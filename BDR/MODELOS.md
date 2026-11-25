# Especificação dos modelos BDR (v1)

> Fonte da verdade dos modelos da pasta `BDR/`. Status: **especificação validada; implementação em `BDR/src/bdr_models/`, aguardando dados reais**.
> As convenções de código, custos e caixa seguem o `CLAUDE.md` da raiz, salvo quando indicado aqui.

## 0. Base comum

| Item | Decisão |
|---|---|
| Preço | **Sempre sintético em R$**: `P_R$ = TR_US$ × USDBRL`. Vale para ETFs, ações e também para o IVVB11 (sintético via IVV). O BDR real não é usado no backtest |
| Retorno total | `TOT_RETURN_INDEX_GROSS_DVDS` do ativo nos EUA. O componente de dividendos entra **líquido da retenção de 30%**: `r_div_líq = 0,7 × (r_TR − r_preço)` |
| Câmbio | `USDBRL Curncy`, fechamento |
| Execução | Sinal no fechamento de *t*, execução no fechamento de *t+1* |
| Custos | 4 bps por R$ negociado. Aluguel do IVVB11 a 3% a.a. sobre a perna vendida |
| Caixa | Todo o caixa, inclusive o da venda descoberta, rende CDI − 4 bps a.a. |
| Beta | 252 dias de retornos diários, **calculado em US$** (ativo vs. IVV), recalculado no último pregão do mês e limitado a [0,5; 2,0]. Sem histórico (< 126 dias), usa 1,0 |
| Período | Dados desde 2008, calibração em 2009–2012 e OOS de 2013 em diante (como no modelo do IBRA) |
| Métricas | As do `CLAUDE.md` §6.1, mais a exposição líquida a dólar, a correlação entre os modelos e o Sharpe sobre o CDI |

### 0.1 Variantes de hedge (valem para os modelos 1 e 2)

| Variante | Perna vendida | Dólar |
|---|---|---|
| `long_only` | Nenhuma, consome caixa | Comprado em dólar (aberto) |
| `ls_beta` | IVVB11 = Σ βᵢ × notionalᵢ | Residual de (1 − β) × notional |
| `ls_notional` | IVVB11 = Σ notionalᵢ | Neutro |

O hedge é **agregado** no book e ajustado a cada entrada ou saída, ou quando o descasamento passa de 5% do book.

### 0.2 Sinal de tendência relativa

A regra é aplicada sobre a série que é o PnL de cada variante:

| Variante | Série `R_t` |
|---|---|
| `long_only` | `P_R$ / índice CDI` |
| `ls_beta`, `ls_notional` | `P_R$ / P_IVVB11_R$` |

Parâmetros: médias móveis de **5, 10 e 20** dias, máxima de 20 e mínima de 10. Há também uma versão "lenta" com janelas ×4 (20/40/80). A regra está em 4.1.

## 1. Modelo 1: tendência setorial em ETFs

- **Universo**:
  - **Amplo (11)**: BIYW39 (IYW), BIYF39 (IYF), BIYE39 (IYE), BIYJ39 (IYJ), BIYK39 (IYK), BIYC39 (IYC), BIYM39 (IYM), BUTL39 (IDU), BIYZ39 (IYZ), BUSR39 (USRT) e BIXJ39 (IXJ).
  - **Completo (+12)**: BBMR39 (BBRE), BIHE39 (IHE), BIHI39 (IHI), BIHF39 (IHF), BIYP39 (IYT), BAER39 (ITA), BIAK39 (IAK), BIEO39 (IEO), BITB39 (ITB), BSOX39 (SOXX), BIAT39 (IAT) e BIBB39 (IBB).
  - Um ETF só entra no universo a partir da data em que o ETF americano tem 252 dias de histórico.
- **Sinal**: tendência relativa (0.2), avaliada diariamente. Liga e desliga.
- **Peso**: **1/n**, com *n* = número de ETFs no universo na data. A exposição comprada vai de 0% a 100% do NAV, e o que não está comprado fica no CDI.
- **Hedge**: as três variantes de 0.1.

## 2. Modelo 2: single names, dividendos e tendência

- **Universo**: todos os BDRs não patrocinados com ativo-objeto identificado (`bdr_master.csv`), **sem REITs** (pela indústria GICS da Bloomberg). O default é o **S&P 500 point-in-time** (`dividend.universe: spx_pit`, decisão 4.2c). A lista atual de BDRs (`bdr_list`) roda só como comparação, porque tem viés de sobrevivência.
- **Elegível em t**:
  1. DY de 12 meses (bruto, point-in-time, `EQY_DVD_YLD_12M`) **> 0**;
  2. DY no **1º quartil** (os 25% maiores) do universo em *t*;
  3. sinal de tendência relativa ligado.
- **Book**: no máximo **20 papéis**. Cada entrada recebe **5% do book** em notional, e o peso deriva depois (sem rebalancear). Vaga não ocupada fica no CDI.
- **Fila**: quem está no book só sai pelo stop. Quando uma vaga abre, entra o elegível de **maior DY**.
- **Teto setorial**: no máximo 5 papéis por setor GICS.
- **Stop (única saída)**: série relativa `R = P_ação / P_IVVB11`. Sai quando `R_t / máx(R desde a entrada) − 1 ≤ −6%`. Se o papel nunca andou, o stop é −6% desde a entrada.
- **Cooldown**: 15 pregões após o stop, sem reentrada no mesmo papel.
- O stop é **sempre contra o IVVB11**, inclusive na variante `long_only`. Nela, só o sinal de entrada usa `P / CDI`.
- **Hedge**: as três variantes de 0.1.

## 3. Dados (export Bloomberg)

Os arquivos vão em `BDR/data/raw/` (não versionado). O formato é o mesmo do repo: wide, `Dates` em `dd/mm/aaaa`, desde 02/01/2008, com as colunas `XXX US Equity`.

Ordem do export:
1. Composição histórica do `SPX Index` (`INDX_MWEIGHT_HIST` com `END_DATE_OVERRIDE` em cada fim de mês) → `spx_composition.txt` (`data;ticker;peso`).
2. Todos os tickers que aparecem nela (inclusive os deslistados), mais os de `BDR/data/bloomberg_request/tickers_us.txt` (ETFs, IVV e ações dos BDRs atuais).

| Arquivo | Tickers | Campo |
|---|---|---|
| `spx_composition.txt` | `SPX Index`, um bloco por fim de mês | `INDX_MWEIGHT_HIST` |
| `bdr_us_px.txt` | ETFs + IVV + ações (`XXX US Equity`) | `PX_LAST` |
| `bdr_us_tr.txt` | Mesmos tickers | `TOT_RETURN_INDEX_GROSS_DVDS` |
| `bdr_us_dy.txt` | Ações-objeto | `EQY_DVD_YLD_12M` |
| `bdr_static.csv` | Ações-objeto | `GICS_SECTOR_NAME`, `GICS_INDUSTRY_NAME` (estático) |
| `bdr_fx.txt` | `USDBRL Curncy` | `PX_LAST` |
| `market.txt` | O mesmo do modelo do IBRA (coluna `CDI` em índice acumulado) | — |

## 4. Decisões

### 4.1 Combinação das médias e das máximas/mínimas (confirmado)
Default (5/10/20):
- **Liga** quando `MA5 > MA10 > MA20` (médias alinhadas) **e** `R_t` supera a máxima dos 20 pregões anteriores (rompimento Donchian).
- **Desliga** quando `MA5 < MA10` **ou** `R_t` fica abaixo da mínima dos 10 pregões anteriores. Só vale para o modelo 1; no modelo 2 a saída é só pelo stop.
- **Versão lenta**: as mesmas regras com janelas ×4 (20/40/80).

### 4.2 Viés de sobrevivência do universo de single names — **decidido: (c)**
A lista de BDRs é a **de hoje**. Usá-la em 2010 é escolher empresas que sobreviveram e cresceram o bastante para ganhar BDR. Opções:
- (a) Usar a lista atual e aceitar o viés, que fica reportado.
- (b) Só permitir o papel a partir da data de listagem do BDR. Como a maioria foi listada em 2019 ou depois, o backtest útil fica curto.
- (c) Universo point-in-time do S&P 500 (`INDX_MWEIGHT_HIST`), sem REITs, como proxy do que "seria BDR", com (a) como comparação.

### 4.3 Beta em US$ vs. R$ — **decidido: US$**
Em R$ as duas pernas carregam o mesmo dólar. O beta fica puxado para 1 e mistura câmbio com sensibilidade ao S&P. A proposta é o beta em **US$**, que mede só a sensibilidade de mercado. O residual cambial (1 − β) da variante `ls_beta` fica reportado; quem não o quiser usa a `ls_notional`.

## 5. Como rodar

```bash
python BDR/scripts/generate_sample.py                     # dados sintéticos em BDR/data/sample (já versionados)
python BDR/scripts/run_bdr_backtest.py --config BDR/configs/experiments/sample.yaml
# com os dados reais em BDR/data/raw/:
python BDR/scripts/run_bdr_backtest.py --config BDR/configs/experiments/setorial_amplo.yaml
python BDR/scripts/run_bdr_backtest.py --config BDR/configs/experiments/dividendos_spx.yaml
```

Experimentos em `BDR/configs/experiments/`:

| yaml | O que roda |
|---|---|
| `setorial_amplo` | 11 ETFs, janelas 5/10/20 |
| `setorial_amplo_lento` | 11 ETFs, janelas 20/40/80 |
| `setorial_completo` | 23 ETFs (amplo + subsetores) |
| `dividendos_spx` | S&P 500 point-in-time, janelas 5/10/20 |
| `dividendos_spx_lento` | Igual, com janelas 20/40/80 |
| `dividendos_lista_bdr` | Lista atual de BDRs (com viés de sobrevivência, só para comparação) |

Cada rodada roda as três variantes (`long_only`, `ls_beta`, `ls_notional`) e grava em `BDR/results/<run_id>/`:
- `nav_*.parquet`, `trades_*.parquet` e `positions_*.parquet`;
- `book_*.parquet` (só no modelo de dividendos: ocupação do book por dia);
- `summary.json`, `metrics.md` (total, calibração e OOS) e `config.yaml`.

### Código

| Módulo | Papel |
|---|---|
| `config.py` | yaml validado (pydantic; chave desconhecida é erro) |
| `data.py` | Export Bloomberg → preço sintético em R$ no calendário B3; beta móvel |
| `signals.py` | Tendência relativa (médias alinhadas + Donchian), estado liga/desliga |
| `strategies.py` | `SectorStrategy` (1/n) e `DividendStrategy` (20 vagas, DY, stop, cooldown, teto setorial) |
| `engine.py` | Motor diário: execução em t+1, custos, CDI, aluguel e hedge agregado |
| `runner.py` | Monta universo, sinais e betas, roda as variantes, métricas e gravação |
| `synthetic.py` | Dados sintéticos no formato Bloomberg |

Testes em `BDR/bdr_tests/`: fórmulas do preço sintético e do beta, sinal e histerese, execução em t+1, custos, CDI, hedge e aluguel, stop de 6% do pico, cooldown, prioridade por DY, quartil, teto setorial e look-ahead no pipeline inteiro.
