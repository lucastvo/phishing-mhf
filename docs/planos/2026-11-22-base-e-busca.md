# Base de templates e busca — plano de implementação (etapa 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** montar a base de templates (h, e, s, domínios por par template × tamanho de tela), a busca exaustiva, a tabela de similaridades das amostras e a medição exaustiva × FAISS.

**Architecture:** `src/mhf/base.py` concentra construção, gravação, leitura e busca; três scripts finos (`construir_base.py`, `similaridades.py`, `medir_busca.py`) usam a classe `Base`. Hamming com `np.bitwise_count` sobre palavras de 64 bits; cosseno como produto interno; s com `estrutural.comparar`.

**Tech Stack:** Python 3.13, numpy 2.3 (`np.bitwise_count`), lxml (via `estrutural`), faiss-cpu só em `medir_busca.py`, unittest.

**Spec:** `docs/especificacoes/2026-11-22-base-e-busca.md`

## Global Constraints

- Busca exaustiva em numpy; o FAISS só pode ser importado em `scripts/medir_busca.py`.
- Cada amostra só é comparada com templates da sua classe de tela (`visual.CLASSES_TELA`).
- s do template = `estrutural.extrair(dom_<tamanho>.html, url_login)` do mesmo par.
- Formato da base: `data/base/base.jsonl` + `base_small.npy` + `base_large.npy` (float32, norma 1) + `base_meta.json`.
- Tabela: distâncias de Hamming em inteiros (h64 `uint8`, h256 `uint16`), similaridades em `float16`, s ausente = NaN.
- Ler a base e a tabela confere que o JSONL e cada `.npy` têm o mesmo número de linhas.
- Testes sem rede e sem dados reais (`python -m unittest discover -s tests`); nomes e mensagens em português.
- Commits só de código sem trailer; commits com documentação levam `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Template aprovado sem linha em `visual_templates.jsonl` (aprovado depois da extração visual): a construção falha listando os ids, em vez de montar uma base incompleta. Teste na Task 1.
2. Classe de tela sem nenhum template: `similaridades` devolve arrays vazios e a tabela grava matrizes N × 0, sem quebrar. Teste nas Tasks 2 e 3.
3. pHash com zeros à esquerda (`"00ff..."`): a conversão para palavras de 64 bits preserva a largura e a distância sai certa. Teste na Task 2.
4. Amostra sem s (sem HTML útil) ou presente só no JSONL estrutural: a lista mestre é o JSONL visual; sem s → colunas de s NaN; s sem visual → ignorado. Teste na Task 3.
5. Empates no vizinho mais próximo: a concordância exaustiva × FAISS compara o valor da similaridade do primeiro vizinho, não só o índice. Teste na Task 4.

---

### Task 1: construção, gravação e leitura da base

**Files:**
- Create: `src/mhf/base.py`, `scripts/construir_base.py`, `tests/test_base.py`

**Interfaces:**
- Consumes: `templates.templates_aprovados(plano, raiz) -> list[tuple[dict, str]]`, `templates.pasta_entrada(raiz, id_)`, `estrutural.extrair(bytes, url) -> ImpressaoEstrutural | None`, `marcas.ler_tabela`.
- Produces:
  - `MODELOS = ("small", "large")`
  - `construir_itens(pares, raiz_templates, visual_linhas: list[dict], visual_emb: dict[str, np.ndarray], tabela: list[dict]) -> tuple[list[dict], dict[str, np.ndarray]]` — um item por par, na ordem de `pares`; embeddings reordenados para a ordem dos itens.
  - item: `id` (`<entrada>@<tamanho>`), `entidade`, `variante`, `origem`, `timestamp`, `classe`, `phash64`, `phash256`, `dominios` (lista), `s` (`ImpressaoEstrutural.para_dict()` ou `None`).
  - `gravar(pasta, itens, emb, meta: dict) -> None`; `Base.carregar(pasta) -> Base`.
  - `class Base`: `itens: list[dict]`, `emb: dict[str, np.ndarray]`, `indices(classe) -> np.ndarray[int]` (posições na base, em ordem).

- [ ] **Step 1: testes que falham**

`TestConstrucao` com `tempfile` (raiz de templates com `dom_1366x768.html` e `dom_1920x1080.html` gravados em `templates.pasta_entrada(raiz, id)`; tabela `[{"entidade": "PayPal", "dominios": ["paypal.com"]}, ...]`):
- `test_itens_na_ordem_dos_pares_com_embeddings_alinhados`: visual com as linhas em ordem diferente da dos pares; `emb["small"][i]` é a linha visual do id do item i; `itens[i]["classe"] == r`; `dominios == ["paypal.com"]`; `s["contagens"]["campos_senha"] == 1` para um DOM com `<input type=password>`.
- `test_template_sem_linha_visual_falha_listando_ids`: `assertRaisesRegex(ValueError, "paypal/login/2021-01-01@1920x1080")`.
- `test_dom_ausente_deixa_s_nulo`: par sem o `dom_<r>.html` → `s is None` (o item continua na base).
- `test_gravar_e_carregar`: ida e volta preserva itens e embeddings; `base_meta.json` existe.
- `test_carregar_recusa_npy_desalinhado`: `.npy` com uma linha a menos → `ValueError`.

- [ ] **Step 2:** `python -m unittest tests.test_base -v` → FAIL (módulo `mhf.base` não existe).

- [ ] **Step 3: implementar** `construir_itens`, `gravar`, `Base.__init__`, `Base.carregar`, `Base.indices` em `src/mhf/base.py`. Domínios vêm da entidade na tabela (`KeyError` se a entidade não estiver nela). `carregar` confere linhas do JSONL × linhas de cada `.npy` e normas ≈ 1 (tolerância 1e-3).

- [ ] **Step 4:** testes passam; suíte inteira passa.

- [ ] **Step 5: `scripts/construir_base.py`** — argumentos `--plano config/templates_snapshots.json --raiz-templates data/templates --visual data/visual_templates --marcas config/marcas.json --saida data/base`. Confere o alinhamento da saída visual (JSONL × `.npy`) antes de construir. `base_meta.json`: data, itens por classe, itens por entidade, templates sem s, versões de numpy e lxml. Imprime o resumo.

- [ ] **Step 6: commit** (código, sem trailer): `Base de templates: construção, gravação e leitura`.

### Task 2: busca

**Files:**
- Modify: `src/mhf/base.py`, `tests/test_base.py`

**Interfaces:**
- Produces:
  - `palavras_do_hash(h: str) -> np.ndarray[uint64]` — hex de 16 ou 64 caracteres → 1 ou 4 palavras, mais significativa primeiro.
  - `Base.similaridades(consulta: dict, classe: str, sinais=("h", "e", "s")) -> dict[str, np.ndarray]`. Consulta: `phash64`, `phash256` (hex), `small`, `large` (vetores), `s` (`ImpressaoEstrutural` ou `None`); campos ausentes → NaN (ou −1 nas distâncias). Chaves devolvidas: `indices` sempre; com `"h"`: `dist_h64` (int), `dist_h256` (int), `sim_h64`, `sim_h256`; com `"e"`: `cos_small`, `cos_large`; com `"s"`: `hash_igual`, `jaccard_caminhos`, `jaccard_criticos`, `sim_contagens`.
  - `Base.vizinhos(consulta, classe, sinal, k=5) -> list[tuple[int, float]]` — `sinal` ∈ {`h64`, `h256`, `small`, `large`, `caminhos`}; (índice na base, similaridade), do mais parecido para o menos; empates pela ordem da base.
  - `SINAIS_VIZINHOS` com esses cinco nomes.

- [ ] **Step 1: testes que falham** (`TestBusca`, base sintética de 4 itens: 3 em 1366x768 de duas entidades, 1 em 1920x1080):
- `test_palavras_do_hash_com_zeros_a_esquerda`: `palavras_do_hash("00000000000000ff")` → `[255]`; 64 caracteres → 4 palavras; distância entre `"0"*16` e `"0"*15+"f"` = 4.
- `test_so_templates_da_classe`: `indices` = os 3 da 1366x768.
- `test_consulta_igual_a_um_template`: dist 0, `sim_h64` 1, `cos_small` 1 (places=5), `jaccard_caminhos` 1, `hash_igual` 1 na coluna desse template.
- `test_sem_s_na_consulta_da_nan` e `test_template_sem_s_da_nan_na_coluna`.
- `test_sinais_restringe_as_chaves`: `sinais=("h",)` → só `indices` e chaves de h.
- `test_classe_sem_templates_devolve_vazio` (classe válida sem itens → arrays de tamanho 0) e `test_classe_desconhecida` (`ValueError`).
- `test_vizinhos_ordem_k_e_empate`: k=2; dois templates com a mesma distância → o de menor índice primeiro; `sinal="xyz"` → `ValueError`.

- [ ] **Step 2:** FAIL (métodos inexistentes).
- [ ] **Step 3: implementar.** Pré-calcular por classe, no `__init__`: índices, palavras de h64 (n×1) e h256 (n×4), embeddings (n×d), lista de `ImpressaoEstrutural | None`. Hamming: `np.bitwise_count(palavras ^ consulta).sum(axis=1)`.
- [ ] **Step 4:** testes e suíte passam.
- [ ] **Step 5: commit** (código): `Base de templates: busca exaustiva por classe de tela`.

### Task 3: tabela de similaridades das amostras

**Files:**
- Create: `scripts/similaridades.py`
- Test: `tests/test_similaridades.py`

**Interfaces:**
- Consumes: `Base`, `marcas.entidade_do_rotulo(tabela, dataset, rotulo)`, `estrutural.ImpressaoEstrutural.de_dict`.
- Produces:
  - `conferir_alinhamento(linhas: list, emb: dict[str, np.ndarray]) -> None` (`ValueError` se algum `.npy` tiver outro número de linhas).
  - `calcular_tabela(linhas_visual, emb_visual, s_por_id: dict, base, tabela, dataset) -> tuple[list[dict], dict[str, np.ndarray]]`.
  - meta por amostra, na ordem do JSONL visual: `id`, `classe`, `linha_na_classe`, `rotulo`, `particao`, `marca`, `entidade` (ou `None`), `url`, `elementos` (do s, ou `None`).
  - matrizes com chave `"<classe>__<sinal>"` para os sinais de `similaridades` (sem `sim_h*`, que são derivados) e `"<classe>__templates"` (índices na base das colunas).
  - saídas: `<saida>.jsonl` e `<saida>.npz` (`np.savez_compressed`).

- [ ] **Step 1: testes que falham** (base sintética da Task 2; 4 amostras: duas na 1366x768, uma na 1920x1080, uma na 1280x960 sem templates; uma sem s):
- `test_agrupa_por_classe_e_mapeia_linhas`: `linha_na_classe` correta; `m["1366x768__cos_small"].shape == (2, 3)`; a linha de uma amostra igual a um template tem `cos_small` ≈ 1 na coluna certa (`templates` indica a coluna).
- `test_classe_sem_templates_grava_matriz_vazia`: shape `(1, 0)`.
- `test_amostra_sem_s_fica_nan` e `test_s_sem_visual_e_ignorado`.
- `test_tipos`: `dist_h64` `uint8`, `dist_h256` `uint16`, `cos_small` `float16`.
- `test_entidade_da_amostra`: rótulo `"paypal"` com `dataset="phish360"` → `"PayPal"` (tabela sintética com `nomes_phish360`); benigno → `None`.
- `test_conferir_alinhamento`.

- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implementar.** Laço por amostra usando `Base.similaridades` (o mesmo caminho do uso real). `main`: `--visual data/visual_<ds> --estrutural data/estrutural_<ds>.jsonl --dataset {phish360,phishpedia} --base data/base --marcas config/marcas.json --saida data/similaridades_<ds>`; imprime amostras por classe, amostras sem s e o tempo total.
- [ ] **Step 4:** testes e suíte passam.
- [ ] **Step 5: commit** (código): `Tabela de similaridades das amostras com os templates`.

### Task 4: medição exaustiva × FAISS

**Files:**
- Create: `scripts/medir_busca.py`
- Test: `tests/test_medir_busca.py`

**Interfaces:**
- Consumes: `Base`, `palavras_do_hash`.
- Produces:
  - `topo_exaustivo(base, classe, consultas: dict[str, np.ndarray], sinal) -> tuple[np.ndarray, np.ndarray]` (índice e similaridade do 1º vizinho por consulta; `sinal` ∈ {`h64`, `small`, `large`}).
  - `topo_faiss(base, classe, consultas, sinal) -> tuple[np.ndarray, np.ndarray]` (`IndexBinaryFlat(64)` para h64, `IndexFlatIP` para e).
  - `concordancia(sim_a, sim_b) -> float` — fração de consultas com a mesma similaridade do 1º vizinho (tolerância 1e-5), robusta a empates.

- [ ] **Step 1: testes que falham:** `test_faiss_e_exaustiva_concordam` (base sintética, 20 consultas aleatórias com semente, os três sinais → concordância 1.0); `test_concordancia_com_empate` (índices diferentes, mesmo valor → 1.0).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implementar.** `main`: `--base data/base --consultas data/visual_phish360 data/visual_phishpedia_phish data/visual_phishpedia_benign --estrutural <jsonl correspondentes> --por-classe 2000 --semente 0`. Por classe e uma consulta de cada vez: mediana e p95 (µs) de h64, small e large nos dois métodos; mediana e p95 (ms) de `similaridades(..., sinais=("s",))` nas consultas com s; concordância. Imprime a tabela em Markdown.
- [ ] **Step 4:** testes e suíte passam.
- [ ] **Step 5: commit** (código): `Medição da busca: exaustiva × FAISS`.

### Task 5: rodada completa e documentação

- [ ] **Step 1:** `python scripts/construir_base.py ...` → 572 itens (191/191/190), 0 sem s.
- [ ] **Step 2:** `python scripts/similaridades.py` nos três datasets, com o PC livre; conferir contagens por classe contra os JSONL visuais.
- [ ] **Step 3:** `python scripts/medir_busca.py ...` com o PC livre.
- [ ] **Step 4:** sanidade: o vizinho mais próximo por `cos_small` na tabela reproduz o top-1 de referência do desenho (§5.2: 21,8% / 57,4%).
- [ ] **Step 5:** README (passo 4: comandos, saídas, tabela da medição) e desenho (números medidos); commit com trailer.
