# pairs-ibra

Modelo de pairs trading / arbitragem estatística em ações do IBRA (B3), com backtest walk-forward
desde 2008, execução no fechamento de t+1 e custos realistas. A documentação de metodologia e as
decisões estão em [`CLAUDE.md`](CLAUDE.md).

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Dados de entrada (`data/raw/`, nunca versionados)

Exports do Bloomberg em `.txt`, layout wide, separador `,`, datas `dd/mm/aaaa`, faltantes `#N/A`:

```
Dates,Petr4 BZ Equity,Vale3 BZ Equity,...
02/01/2008,10.51,#N/A,...
```

| Arquivo | Conteúdo |
|---|---|
| `prices_adj.txt` | fechamento ajustado (RT116) |
| `prices_raw.txt` | fechamento sem ajuste |
| `volume.txt` | quantidade negociada |
| `market.txt` | `Dates,BZACCETP Index,IBOV Index,IBRA Index` (CDI em índice acumulado). Os nomes das colunas ficam em `data.market_columns` no yaml |
| `ibra_composition.txt` | `data;ticker;peso`, uma linha por ação em cada rebalanceamento. Opcional: sem ele, use `universe.source: liquidity_proxy` |

Setores: `configs/sectors.xlsx` (abas `setores`, `de_para`, `exclusoes`).

## Como rodar

```bash
python scripts/make_sectors_template.py --prices data/raw/prices_adj.txt   # cria/completa o Excel de setores
python scripts/build_dataset.py --config configs/base.yaml                 # .txt → parquet + data/processed/quality_report.md
python scripts/run_backtest.py  --config configs/base.yaml                 # resultados em results/<run_id>/
python scripts/run_backtest.py  --config configs/experiments/intra_setor.yaml
```

Cada rodada grava em `results/<run_id>/`: `report.html`, `trades.parquet`, `positions.parquet`,
`nav.parquet`, `pairs_selected.parquet`, `metrics.json`, `subperiods.csv`, `calibration_oos.csv`
e uma cópia do `config.yaml`.

### Testar sem dados reais

```bash
python scripts/build_dataset.py --config configs/experiments/sample.yaml
python scripts/run_backtest.py  --config configs/experiments/sample.yaml
```

## Desenvolvimento

```bash
ruff check src tests scripts && mypy && pytest
```
