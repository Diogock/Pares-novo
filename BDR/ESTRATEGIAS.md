# Estratégias com BDRs não patrocinados

Ideias para um fundo L&S que opera na B3. A seleção levou em conta o que o fundo já roda: tendência setorial e temática, mean reverting, arbitragem de OPA e momentum.
Cada ideia tem mecânica, o que precisa, onde está o risco e uma prioridade.

## 0. A mecânica que importa

```
BDR_justo (R$) = P_lastro (US$) × USDBRL / bdrs_por_acao
prêmio_t      = ln(BDR_t) − ln(BDR_justo_t)
```

- **Lastro.** Na maioria dos programas é uma ação americana. Em 93 deles é um ADR (ASML, AB InBev, Rio Tinto, Barclays...). Veja `bdr_master.csv`, colunas `lastro_via` e `bdrs_por_acao`.
- **Câmbio embutido.** Comprado em BDR = comprado na ação **e** comprado em dólar. Qualquer estratégia que não queira a exposição cambial precisa de hedge, com WDO/DOL ou com outra perna em BDR.
- **Emissão e cancelamento.** São feitos pela depositária: no Banco B3, US$ 15 por operação mais uma tabela percentual (Anexo II do PDF). É isso que amarra o prêmio a zero, mas só para quem tem conta no exterior e corretora que opere a conversão.
- **Formadores de mercado.** Nos BDRs líquidos eles mantêm o prêmio estreito (o índice BDRX só inclui BDRs com formador). Nos ilíquidos, o fechamento costuma ser velho ou ruidoso.
- **Horário.** A B3 muda o horário junto com o horário de verão americano, então os fechamentos ficam próximos. O dólar usado no preço justo deve ser o **do mesmo instante**, não a PTAX das 13h.
- **Aluguel (BTC).** Vender BDR descoberto depende de doador. A disponibilidade e a taxa de cada BDR são a primeira restrição prática.
- **Tributação.** Há retenção na origem sobre dividendos (em geral 30% nos EUA), e o tratamento no fundo é diferente do da ação local. **Validar com o jurídico e o tributário antes de operar.**

---

## 1. Monitor de prêmio/desconto (base de tudo) — prioridade **alta**

Série diária de `prêmio_t` para os 813 códigos, com média, desvio, z-score e meia-vida do prêmio por BDR.

- **Para que serve:**
  1. Validar a paridade. Prêmio persistente perto de ±50%, ou um múltiplo exato, indica paridade errada ou desdobramento não refletido.
  2. Mapear onde o prêmio é estável (BDR "bom" para operar) e onde é ruído.
  3. Alimentar as estratégias 2 a 5.
- **Dados:** Bloomberg, com fechamento de `XXXX34 BZ Equity`, `lastro US Equity` e `USDBRL` no fechamento da B3 (`bloomberg_tickers.csv` já tem os tickers). Volume do BDR para filtrar liquidez.
- **Esforço:** baixo. Reaproveita `loaders.py` (mesmo formato wide) e `validation.py`.

## 2. Pares cruzados BDR × ação do IBRA — prioridade **alta**

Estende o pipeline de cointegração deste repositório para pares em que uma perna é BDR.
Concorrentes globais de empresas locais:

| Tema | Perna local | Perna BDR |
|---|---|---|
| Minério | VALE3 | RIOT34 (Rio Tinto) |
| Petróleo | PETR4, PRIO3 | EXXO34, CHVX34, SLBG34, VLOE34 |
| Papel e celulose | SUZB3, KLBN11 | I1PC34 (International Paper) |
| Siderurgia | GGBR4, CSNA3 | N1UE34 (Nucor) |
| Bebidas | ABEV3 | ABUD34 (AB InBev), C2CA34, FMXB34, COCA34 |
| Bancos e fintechs | ITUB4, BBDC4, BPAC11 | ROXO34 (Nubank), INBR34 (Inter) |
| Pagamentos e e-commerce | — | STOC34 × PAGS34, MELI34 |

- **Detalhe técnico:** o spread `ln P_local − γ ln P_BDR` carrega exposição cambial. Há três saídas:
  - a. Johansen com três variáveis (local, lastro em US$, USDBRL).
  - b. Hedge do resíduo cambial com WDO.
  - c. Aceitar o câmbio como fator e medir a exposição.
- **Por que complementa:** são pares que o universo IBRA não enxerga. A correlação com o mean reverting atual deve ser baixa, mas é preciso medir.
- **Risco:** a relação entre a local e a global muitas vezes é por commodity ou macro (a cointegração quebra em choque de câmbio ou de risco-país). O BTC do BDR pode não existir.

## 3. Pares entre BDRs (stat arb "S&P na B3") — prioridade **média**

Mesmo pipeline, com o universo formado pelos BDRs líquidos e o setor do programa.
Exemplos clássicos: KO × PEP (COCA34 × PEPB34), V × MA (VISA34 × MSCD34), bancos americanos (JPMC34, BOAC34, MSBR34) e semicondutores.

- **Vantagem:** com γ ≈ 1, o câmbio quase se cancela. O resíduo cambial é `(1−γ)·ln USDBRL`.
- **Dica:** estimar a cointegração com os preços **do lastro em US$**, que têm histórico mais longo e sem preço velho, e executar nos BDRs.
- **Risco:** liquidez e BTC. É um mercado em que muita gente já opera pares lá fora. Aqui a vantagem é só de acesso, não de informação.

## 4. Classes duplicadas (o "ON/PN" dos BDRs) — prioridade **média**, esforço baixo

O mesmo emissor com duas classes listadas: **GOGL34 × GOGL35** (Alphabet A × C), **N1WS34 × N1WS35** (News Corp A × B) e **Z2LL34 × Z2LL35** (Zillow A × C).

- O spread entre as classes é estreito no lastro. O spread **entre os BDRs** pode abrir mais, por liquidez local e pelo formador.
- Encaixa direto na flag `same_issuer` do pipeline (D3).

## 5. Merger arb via BDR (complementa a mesa de OPA) — prioridade **média**

Quando uma empresa com BDR é alvo de aquisição em dinheiro, o BDR passa a valer `preço_do_deal × USDBRL / paridade` menos o spread do deal.
Na liquidação, o programa é cancelado e o investidor recebe o caixa.

- **Oportunidade:** o BDR pode demorar a refletir o anúncio, e o prêmio pode desancorar (formador sai, liquidez some).
- **Exemplos recentes no cadastro:** Mirati e Inari, programas DRN que ficaram sem código depois da aquisição.
- **O que precisa:** um alerta de eventos sobre a lista (a mesa de OPA já monitora deals) e o monitor da estratégia 1.

## 6. Feriados descasados — prioridade **baixa**, oportunística

Em feriado americano com a B3 aberta (por exemplo, Thanksgiving), o BDR negocia sem o lastro. A descoberta de preço vem do futuro de S&P e do câmbio, e o formador alarga o spread.
Em feriado brasileiro, o BDR abre com gap.
É uma estratégia de reversão do prêmio em dias específicos e precisa da série do monitor.

## 7. Momentum ou fatores em BDRs com hedge cambial — prioridade **baixa**

Momentum cross-section no universo de BDRs líquidos, com WDO para tirar o dólar.
Dá diversificação geográfica, mas tende a ser correlacionado com o momentum que o fundo já roda e com o fator global. Só vale se a correlação medida for baixa.

## 8. Arbitragem pura BDR × lastro (emissão/cancelamento) — **fora do escopo** sem conta offshore

Comprar o BDR com desconto, vender o lastro em NY e cancelar (ou o inverso).
É o que os formadores fazem: margem fina, exige conta no exterior, câmbio e operação intraday.
Fica registrada como referência. O prêmio dela é o insumo da estratégia 1.

---

## Próximos passos sugeridos

1. Pedir à Bloomberg o export de `bloomberg_tickers.csv`: fechamento ajustado e sem ajuste, volume, USDBRL e WDO1, desde 2012 (o mercado de BDR não patrocinado para varejo é de 2020; antes disso o histórico é ralo).
2. Implementar o monitor de prêmio (estratégia 1) e corrigir as paridades erradas.
3. Ver com a mesa de aluguel quais BDRs têm doador e a que taxa. Isso define o universo real das estratégias 2 a 4.
4. Rodar a estratégia 2 como experimento do pipeline existente, com um `configs/experiments/bdr_cruzado.yaml` que amplia o universo. Essa é a ponte natural entre as duas frentes.
