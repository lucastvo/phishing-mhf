# Avaliação no conjunto de teste — plano de implementação (etapa 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** medir o detector da etapa 5 no conjunto de teste (métricas, intervalos de confiança, recortes, experimentos E0–E5 e latência) e gerar tabelas LaTeX e figuras para o Cap. 5.

**Architecture:** as funções de treino e calibração saem de `scripts/treinar.py` para `src/mhf/treino.py` (reuso nos experimentos); `src/mhf/avaliacao.py` (bootstrap, grupos, recortes, datas, filtros de templates, tabelas LaTeX) e `src/mhf/figuras.py` (matplotlib); `scripts/avaliar.py` roda E0–E5 de uma vez; `scripts/medir_latencia.py` mede páginas brutas.

**Tech Stack:** numpy, scikit-learn, matplotlib 3.11 (backend Agg), unittest.

**Spec:** `docs/especificacoes/2026-11-22-avaliacao.md`

## Global Constraints

- O teste só é lido por `avaliar.py` e `medir_latencia.py`; nenhuma escolha (τ, θ_h, modelo, características) usa o teste.
- Detector principal: `data/modelos/boosting` (gradient boosting, h+e+s, estágio único).
- Bootstrap: 1.000 reamostras das estruturas do teste, semente 0, percentis 2,5 e 97,5.
- Datas: template do Wayback = timestamp; ao vivo = 2026-11-21; amostra do Phishpedia = data no nome da pasta; corte das legítimas no E4b = 2020-10-31.
- Tabelas LaTeX: booktabs, vírgula decimal, "—" para valor ausente.
- Cada execução de `avaliar.py` acrescenta uma linha a `data/avaliacao/registro.jsonl`.
- Commits só de código sem trailer; com documentação, com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Experimento com filtro de templates que deixa uma marca sem template numa classe: a marca sai da disputa (NaN), sem quebrar nem virar similaridade 0. Teste na Task 1.
2. Bootstrap com um grupo só ou sem positivos numa reamostra: o intervalo sai NaN em vez de quebrar. Teste na Task 2.
3. Marca nova (E5): nenhum par das marcas excluídas entra no treino nem na calibração das dobras. Teste na Task 1.
4. Amostra do Phishpedia sem data reconhecível no nome: tratada como legítima no corte padrão (E4b), sem exceção. Teste na Task 2.
5. Página bruta sem HTML na latência: o DOM conta como ausente e a medição segue. Teste na Task 4.

---

### Task 1: treino na biblioteca, filtro de templates e marcas excluídas

**Files:** Create `src/mhf/treino.py`; modify `src/mhf/conjuntos.py`, `scripts/treinar.py`; test `tests/test_treino.py`.

**Interfaces — produz:**
- `treino.pares_de_treino(c, mascara, entidades_excluidas=())`, `treinar_modelo(tipo, c, mascara, entidades_excluidas=(), iteracoes=150, **floresta)`, `escores_fora_da_dobra(c, tipo, progresso=print, entidades_excluidas=(), **kw)`, `calibrar(c, escores, alvo_fpr=0.01, alvo_rev1=0.99, estagio1="nenhum")`, `metricas_cascata(c, escores, theta_h, tau, mascara=None)` (agora também com `acuracia`). `scripts/treinar.py` reexporta.
- `conjuntos.carregar_conjunto(..., filtro_templates=None)`: `filtro_templates(meta_linha, itens_colunas) -> bool array (T,)`; templates fora do filtro têm sinais NaN e distância 255 para aquela amostra.

- [ ] Testes que falham: `test_marcas_excluidas_saem_dos_pares` (nenhum par das marcas excluídas, positivas ou negativas); `test_filtro_de_templates_tira_a_marca` (filtro que remove todos os templates da Netflix → linha NaN da Netflix e d₁ calculado sem eles); `test_metricas_com_acuracia`.
- [ ] Implementar; suíte inteira passa (os testes de `test_treinar.py` continuam).
- [ ] Commit (código): `Treino e calibração na biblioteca; filtro de templates e marcas excluídas`.

### Task 2: avaliação — bootstrap, grupos, recortes, datas e tabelas

**Files:** Create `src/mhf/avaliacao.py`, `tests/test_avaliacao.py`.

**Interfaces — produz:**
- `ic_bootstrap(grupos, calcular, n=1000, semente=0) -> dict[str, tuple[float, float]]` (`calcular(multiplicidade) -> dict[str, float]`, multiplicidade = vezes que o grupo da amostra foi sorteado).
- `grupos_fpr(c, cos_max) -> dict[str, np.ndarray]`: `todas`, `phish360`, `phishpedia_benign`, `paginas_das_marcas`, `mais_parecidas` (decil superior do cosseno máximo entre as legítimas).
- `por_marca(c, decisao, pesos) -> list[dict]` (entidade, amostras, estruturas, revocação por amostra e por estrutura, top-1 nos detectados).
- `tipo_de_pagina(c, campos_senha) -> np.ndarray[str]` (`com_senha`, `sem_senha`, `sem_dom`).
- `data_da_amostra(id) -> date | None`, `data_do_template(item) -> date`, `filtro_2026`, `filtro_ate_data(corte_padrao)`.
- `numero(v, casas=3)`, `tabela_latex(cabecalho, linhas, legenda, rotulo) -> str`.

- [ ] Testes que falham: bootstrap de métrica constante (intervalo de largura zero) e com um grupo só sem positivos (NaN); máscaras dos grupos de FPR; tipos de página; datas (Phishpedia, Wayback, ao vivo, id sem data); filtros; `numero(0.8491)` → `"0,849"`, NaN → `"—"`; `tabela_latex` com `\toprule`, `\midrule`, `\bottomrule`, legenda e rótulo.
- [ ] Implementar; suíte passa.
- [ ] Commit (código): `Avaliação: bootstrap por estrutura, grupos de falso positivo, recortes e tabelas LaTeX`.

### Task 3: avaliar.py — experimentos E0–E5, figuras e registro

**Files:** Create `src/mhf/figuras.py`, `scripts/avaliar.py`, `tests/test_avaliar.py`.

**Interfaces — produz:**
- `figuras.roc(curvas, caminho)`, `figuras.barras_por_marca(linhas, caminho)`, `figuras.latencia(partes, caminho)` (PDF, backend Agg).
- `avaliar.py --tabelas ... --estrutural ... --divisao --base --marcas --modelos data/modelos --saida data/avaliacao --bootstrap 1000 --n-jobs 4 [--experimentos E0,E1,...]`. Grava `resultados.json`, `relatorio.md`, `tabelas/*.tex`, `figuras/*.pdf` e acrescenta a `registro.jsonl`.

- [ ] Teste que falha: `test_main_gera_saidas` no cenário sintético da etapa 5 (2 marcas; sem datas → E4b registrado como "sem amostras com data"); confere as chaves E0–E5 no JSON, ao menos uma tabela `.tex` e uma figura `.pdf`, e uma linha nova no registro a cada execução.
- [ ] Implementar; suíte passa.
- [ ] Commit (código): `Avaliação no teste: experimentos, tabelas, figuras e registro`.

### Task 4: latência em páginas brutas

**Files:** Create `scripts/medir_latencia.py`, `tests/test_medir_latencia.py`.

- [ ] Teste que falha: 4 páginas sintéticas (uma sem HTML) num índice temporário, `--sem-pesos`; o JSON tem mediana e p95 de cada parte e o total; a tabela `.tex` e a figura são gravadas.
- [ ] Implementar (`--dataset NOME INDICE RAIZ [CLASSE]` repetível, `--divisao`, `--por-dataset 100`, `--semente 0`).
- [ ] Commit (código): `Latência por página em páginas brutas do teste`.

### Task 5: rodada, revisão e documentação

- [ ] `avaliar.py` e `medir_latencia.py` com o PC livre; conferir números e figuras.
- [ ] Revisão independente; correções com testes.
- [ ] README (passo 6), desenho com os resultados, PR #9 (base `cascata`).
