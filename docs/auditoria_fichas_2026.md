# Auditoria da base — Mapeamento Parlamentar 2027–2031

**Data da auditoria:** 18/11/2026
**Base auditada:** `output/eleicoes2026/` (coleta de 05–06/10/2026, commit `15a46f7`)
**Planilha de pendências por parlamentar:** [`docs/pendencias_fichas_2026.csv`](pendencias_fichas_2026.csv) (594 linhas)

---

## 1. Resumo executivo

| Indicador | Valor |
|---|---|
| Parlamentares na composição 2027 | **594** (513 deputados + 81 senadores) |
| Eleitos em 2026 / senadores com mandato até 2031 | 567 / 27 |
| Com ID legislativo (histórico cruzável) | 368 (309 Câmara + 59 Senado) |
| **Sem nenhum histórico legislativo cruzado (novatos)** | **226** (204 deputados + 22 senadores) — 38% da base |
| Fichas de interesse (IIP) | 369 (368 válidas + 1 órfã) |
| Fichas de triagem de afinidade | 325 — **todas por palavra-chave, 0 evidências, confiança BAIXA** |
| Campos demográficos da Etapa 1 presentes | **0 de 6** |

**Diagnóstico em uma frase:** a parte de histórico legislativo dos incumbentes está completa e consistente. As três lacunas que comprometem o projeto são: a Etapa 1 (dados demográficos e distribuição municipal de votos) **não foi coletada**; 38% dos eleitos (os novatos) **não têm nenhum sinal temático**; e a "afinidade" é hoje só uma triagem por palavra-chave, sem avaliação qualitativa.

---

## 2. Etapa 1 — Dados eleitorais

### 2.1 O que está completo e consistente
| Campo | Cobertura (567 eleitos em 2026) | Observação |
|---|---|---|
| Nome completo, nome de urna | 100% | — |
| SQ_CANDIDATO, número | 100% | Sem duplicidades |
| Partido | 100% | — |
| Federação | 223 (39%) | **Consistente:** os nulos são todos de partidos fora de federação (PL, MDB, PSD, Republicanos, PODE, PSB, PDT, NOVO, Avante, Missão) |
| Votos nominais | 100% | — |
| Situação de totalização | 100% | QP 385 · média 128 · eleito (Senado) 54 |

Os 27 senadores de 2022 não têm SQ_CANDIDATO nem votos, o que é esperado (não disputaram em 2026). Os votos de 2022 podem ser incluídos, se forem úteis.

### 2.2 Campos obrigatórios ausentes em toda a base
Nenhum dos campos abaixo existe no schema `Parlamentar` (`eleicoes/schemas.py`). Para os 594 parlamentares, eles ficam como **[Dado não localizado na base]**:

- Data de nascimento / idade na posse
- Gênero
- Grau de instrução
- Ocupação declarada
- Naturalidade (município e UF)
- **Distribuição de votos por município** (redutos e % de concentração)

**Correção:** os cinco primeiros vêm do arquivo `consulta_cand_2026_<UF>.csv` do Portal de Dados Abertos do TSE (colunas `DT_NASCIMENTO`, `DS_GENERO`, `DS_GRAU_INSTRUCAO`, `DS_OCUPACAO`, `NM_MUNICIPIO_NASCIMENTO`, `SG_UF_NASCIMENTO`), cruzado por `SQ_CANDIDATO`. A distribuição municipal vem de `votacao_candidato_munzona_2026_<UF>.csv`. Os dois arquivos podem ser incorporados ao `eleicoes/tse_resultados.py` e ao schema.

### 2.3 Alertas de composição desatualizados (coleta de 06/10)
| Situação | Parlamentares | Ação |
|---|---|---|
| PE: TSE em reprocessamento na data da coleta | 25 deputados de PE | Reconferir a lista contra a totalização final do TSE |
| Disputou o 2º turno para governador (25/10) | Alan Rick (AC), Omar Aziz (AM) | Atualizar com o resultado. Se eleitos, mapear o suplente que assume no Senado |
| Eleito governador | Sergio Moro (PR) | Mapear o suplente que assumirá a vaga no Senado |
| Suplentes em exercício | Ana Paula Lobato (MA), Jussara Lima (PI) | Confirmar quem ocupa a vaga em 2027 |
| Troca de casa | 2 senadores → Câmara (Izalci, Jader Filho); 18 deputados → Senado | O histórico da casa anterior deve alimentar a ficha (já ocorre via ID) |

---

## 3. Etapa 2 — Interesse (IIP) e afinidade

### 3.1 Índice de Interesse na Pauta (IIP) — 368 incumbentes
| Faixa | Nº |
|---|---|
| A — Prioridade alta (≥ 50) | 10 |
| B — Prioridade média (30–50) | 69 |
| C — Interesse pontual (15–30) | 130 |
| D — Interesse baixo (> 0) | 143 |
| Sem interesse identificado | 17 |

Cobertura: os 368 parlamentares com ID legislativo têm ficha. Nenhum ficou de fora.

**Fragilidades:**
1. **30 parlamentares têm IIP sustentado só por frentes parlamentares**, sem autoria, relatoria nem comissão. Frentes mistas reúnem mais de 100 signatários e são sinal fraco, e o código já reconhece isso (`SATURACAO_FRENTES`). Recomenda-se não classificar esses casos acima de "D" sem outra evidência.
2. **As ementas são gravadas truncadas em 220 caracteres** (`eleicoes/interesse.py`, linhas 146 e 166). A classificação temática usa a ementa completa e não é afetada. O problema é que a ficha salva não basta, sozinha, para a leitura humana nem para a avaliação qualitativa: será preciso buscar o texto de novo na API.
3. 98 fichas não têm nenhuma proposição de autoria. O sinal delas vem só de comissões e frentes.
4. 1 ficha órfã (`senado_MA_6359`, IIP 0), que não corresponde a ninguém da composição atual. É cache residual e pode ser apagada.
5. O componente *relatoria* só é calculado para o Senado. Na Câmara, o peso é renormalizado, o que torna o IIP de deputados e senadores **não diretamente comparável**.

### 3.2 Triagem de afinidade (IAT) — 325 fichas
- Todas usam `metodo = "triagem"` (palavra-chave). **Nenhuma** passou pela avaliação qualitativa (`metodo = "ia"`).
- **0 evidências** anexadas, e as 3.575 avaliações de tema têm confiança **BAIXA**.
- A posição +1 significa apenas "autor de proposição sobre o tema — direção a confirmar". **Ainda não se sabe se o parlamentar é favorável ou contrário à agenda.**
- 44 parlamentares têm IIP, mas não têm triagem.

### 3.3 Novatos — o ponto cego (226 parlamentares)
Sem ID na Câmara ou no Senado, os novatos não têm IIP nem triagem. Para eles, o sinal precisa vir de outras fontes:
- Propostas de governo / planos registrados no DivulgaCandContas (TSE)
- Mandatos anteriores em assembleias legislativas e câmaras municipais (muitos são ex-deputados estaduais ou ex-vereadores)
- Ocupação declarada (por exemplo, empresários de TI, engenheiros, professores), que depende da correção do item 2.2
- Atuação pública: entrevistas, redes sociais, artigos

### 3.4 Desalinhamento entre os eixos do projeto e a agenda ABES
A agenda (`eleicoes/agenda_abes.json`) tem 11 temas. Os 4 eixos de familiaridade definidos no projeto se distribuem assim:

| Eixo do projeto | Temas da agenda correspondentes | Lacuna |
|---|---|---|
| IA e inovação | `ia`, `incentivos_pd`, `startups` | — |
| Proteção de dados (LGPD) | `dados` | — |
| Plataformas, concorrência, mercados digitais | `plataformas` (peso 1) | Peso baixo em relação à relevância do PL 4.675/2025 |
| Telecom, cibersegurança e direitos digitais | `ciberseguranca`, `infra_digital` | **Telecomunicações e direitos digitais não têm tema próprio**. `infra_digital` cobre data centers |

Para entregar o índice nos 4 eixos do projeto, é preciso agregar os 11 temas nesses eixos, ou incluir temas para telecom e direitos digitais.

---

## 4. Plano de correção priorizado

| # | Ação | Impacto | Esforço |
|---|---|---|---|
| 1 | Incorporar `consulta_cand` e `votacao_candidato_munzona` do TSE (Etapa 1 completa) | Alto — requisito obrigatório do projeto | Baixo |
| 2 | Reconferir PE, os resultados do 2º turno e os suplentes (Moro, Alan Rick, Omar Aziz) | Alto — a composição pode estar errada | Baixo |
| 3 | Rodar a avaliação qualitativa (`metodo="ia"`) nos 79 parlamentares A+B, com evidências | Alto — passa de "engajado" para "aliado / atenção" | Médio |
| 4 | Enriquecer os 226 novatos (propostas no TSE + mandatos estaduais/municipais) | Alto — 38% da base sem sinal | Alto |
| 5 | Gravar a ementa completa e o link da proposição na ficha (remover o corte `[:220]`) | Médio | Trivial |
| 6 | Rebaixar os IIP sustentados só por frentes; tornar os IIP de Câmara e Senado comparáveis | Médio | Baixo |
| 7 | Mapear os 11 temas nos 4 eixos do projeto; criar temas de telecom e direitos digitais | Médio | Baixo |
| 8 | Apagar a ficha órfã `senado_MA_6359` | Baixo | Trivial |

---

## 5. Top 10 do IIP (referência)

| IIP | Parlamentar | Partido/UF | Base do sinal |
|---|---|---|---|
| 82,0 | Marcos Tavares | PDT/RJ | autoria + comissões + frentes |
| 81,7 | Duda Ramos | PODE/RR | autoria + comissões + frentes |
| 63,4 | Amom Mandel | Republicanos/AM | autoria forte |
| 59,8 | Rubens Pereira Jr | PT/MA | autoria + comissões |
| 58,3 | Aureo Ribeiro | Solidariedade/RJ | comissões + frentes |
| 58,3 | Cabo Gilberto Silva | PL/PB | comissões + frentes |
| 56,9 | Astronauta Marcos Pontes | PL/SP (Senado) | relatoria + comissões |
| 52,4 | Renata Abreu | PODE/SP | comissões + frentes |
| 51,4 | Adriana Ventura | NOVO/SP | comissões + frentes |
| 50,1 | Izalci Lucas | PL/DF (→ Câmara) | relatoria + comissões |

*IIP mede volume de engajamento com a pauta, não a direção da posição. Nenhum nome desta lista deve ser tratado como "aliado" antes da avaliação qualitativa (item 3 do plano).*

---

*Auditoria gerada a partir dos arquivos do repositório. Nenhum dado foi inferido; os campos ausentes estão sinalizados como tal.*
