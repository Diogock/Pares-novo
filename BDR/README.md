# BDR — BDRs não patrocinados na B3

Frente de pesquisa **separada** do modelo de pares do IBRA (raiz do repositório).
Aqui ficam a lista de BDRs, os scripts de coleta e as ideias de estratégia.
Nada desta pasta é importado por `src/pairs_ibra/`.

## O que tem aqui

| Arquivo | Conteúdo |
|---|---|
| `data/bdr_nao_patrocinados.csv` | **Lista oficial dos 810 emissores de BDR não patrocinado (DRN)**, da API de empresas listadas da B3: ticker, ISIN, empresa, depositária, site e data de listagem |
| `data/bdr_todos.csv` | Todos os 1.144 emissores de BDR: DRN (810), ETF/DRE (321) e patrocinados DR1/DR2/DR3 (13) |
| `data/bdr_master.csv` | Lista DRN (813 códigos) cruzada com os programas: ativo-objeto, bolsa, país, setor, **paridade BDR:ação**, lastro em ação ou em ADR |
| `data/programas_banco_b3*.csv` | Programas cuja depositária é o Banco B3 (762), com o link do PDF e os campos do Formulário de Identificação |
| `data/lastro_manual.csv` | Ativo-objeto preenchido à mão para os 44 programas do Bradesco e do Itaú (COCA34, VISA34, AMZO34 etc.), que não têm PDF público. **Paridade em branco** |
| `data/bloomberg_tickers.csv` | Pronto para o export Bloomberg: `XXXX34 BZ Equity`, `AAPL US Equity` e a paridade |
| `data/resumo.md` | Contagens por depositária, bolsa, país, setor e tipo de lastro |
| `ESTRATEGIAS.md` | Ideias de estratégia, priorizadas |
| `MODELOS.md` | Especificação dos modelos em teste: tendência setorial em ETFs e single names com dividendos e tendência |
| `data/bloomberg_request/` | Listas de tickers para o export Bloomberg desses modelos (`scripts/make_bloomberg_request.py`) |

Coleta de 2026-11-25.

## Como atualizar

```bash
python BDR/scripts/fetch_b3_bdr_list.py        # API B3 → bdr_todos.csv e bdr_nao_patrocinados.csv (~2 min)
python BDR/scripts/fetch_banco_b3_programs.py  # página de programas do Banco B3 → programas_banco_b3.csv
python BDR/scripts/enrich_from_programs.py     # baixa os PDFs (cache em data/pdfs/, ~220 MB, não versionado) e lê o Anexo I
python BDR/scripts/build_master.py             # junta tudo → bdr_master.csv
python BDR/scripts/summarize.py                # resumo.md e bloomberg_tickers.csv
```

Requer só a biblioteca padrão do Python e o `pdftotext` (pacote `poppler-utils`).

## Fontes e ressalvas

- **Lista oficial**: API pública `sistemaswebb3-listados.b3.com.br/.../GetCompaniesBDR` (`typeBDR = DRN`) e `GetDetail` (código e ISIN).
- **Programas**: `finservices.b3.com.br/pt/bdr-nao-patrocinado/programas`. Essa página só mostra programas **do Banco B3** (755 dos 810 emissores). Os 34 do Bradesco e os 11 do Itaú não aparecem nela.
- 8 emissores DRN não têm código de negociação na API, por exemplo Mirati e Inari (empresas adquiridas) ou programas recém-criados (OpenAI, Rubrik). Eles estão no CSV com `ticker` vazio.
- **A paridade vem do PDF publicado.** Depois de um desdobramento ou grupamento, o PDF pode estar desatualizado. Antes de usar, confira contra o preço: `BDR ≈ lastro_USD × USDBRL / bdrs_por_acao`. O monitor de prêmio (estratégia 1) já faz essa checagem.
- O setor é o declarado no programa, não a classificação B3 usada no IBRA.
