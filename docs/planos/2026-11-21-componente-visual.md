# Componente visual (etapa 3) — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** templates aprovados também em 1920×1080 (PR 1) e a parte visual de φ(w): classe de tela, primeira dobra, pHash e embedding MobileNetV3 Small/Large, com extração em lote e latência (PR 2).

**Arquitetura:**
- PR 1 estende `src/mhf/templates.py` e `scripts/capturar_templates.py` com **resoluções extras**: capturadas depois, num arquivo de metadados próprio, revisadas e aprovadas uma a uma, sem tocar na captura e na aprovação que já existem.
- PR 2 cria `src/mhf/visual.py` (funções puras e o `Embedder`) e `scripts/extrair_visual.py` (lote, saída em JSONL + `.npy`, latência por etapa).

**Stack:** Python 3.13, Pillow, imagehash, torch/torchvision (CPU), numpy, Playwright (já instalados), `unittest`.

**Spec:** `docs/especificacoes/2026-11-21-componente-visual.md`

## Restrições globais

- Nomes em português. Testes sem rede e sem baixar pesos: `python -m unittest discover -s tests`.
- Pesos em `data/torch` (`TORCH_HOME`); nunca em `~/.cache` (acesso negado na máquina do Lucas).
- As decisões marcadas como [decidido] no spec são do Lucas: **não mudar** sem perguntar.
- **Avisar o Lucas antes da Task 1** e esperar o "pode codar".
- Trailer `Co-Authored-By: Claude …` **só** em commits que não sejam só de código (docs, config, plano de templates). Nunca commitar `CLAUDE.md`, `data/`, `*.csv`, `*.npy`.
- Descrições de PR em tom de documentação, sem perguntas ao Lucas e sem a linha "Generated with Claude Code". O PR 2 traz a justificativa do tamanho de tela (spec §4), a pedido do Lucas.
- PR 1 na branch `templates-1920` (já tem o spec). PR 2 na branch `visual`, criada da `main` depois do merge do PR 1.

## Foco da revisão

1. Aprovações existentes (191) continuam válidas e intactas depois do PR 1: `entradas_aprovadas` igual antes e depois.
2. Uma captura extra refeita invalida só a aprovação dela (mesma regra da aprovação presa à captura vista).
3. `mesclar_plano` preserva as decisões das resoluções extras quando o snapshot é o mesmo, e as descarta quando muda.
4. Imagens problemáticas dos datasets: PNG truncado, página inteira de 85 mil px, captura menor que a dobra, largura fora das três classes.
5. O embedding é determinístico e tem norma 1; Small e Large não se misturam no mesmo `.npy`.

---

## PR 1 — templates em 1920×1080

### Task 1: resoluções extras em `templates.py`

**Arquivos:** modificar `src/mhf/templates.py`; testes em `tests/test_templates.py`.

**Interfaces produzidas:**
- `RESOLUCOES_EXTRAS = {"1920x1080": (1920, 1080)}` (a captura principal continua com `RESOLUCOES`).
- `meta_extra_caminho(raiz, id_, resolucao) -> str`: `<pasta>/extra_<resolucao>.json`.
- `arquivos_extra(resolucao) -> list[str]`: `shot_<r>.png`, `dom_<r>.html`.
- Campo novo na entrada do plano: `"extras": {"1920x1080": {"aprovado": bool|None, "motivo": str, "aprovado_captura": str|None}}` (ausente = nada decidido).
- `extras_pendentes(plano, raiz, resolucao) -> list[dict]`: entradas **aprovadas e válidas** (`entradas_aprovadas`) sem decisão nessa resolução e sem captura extra completa com status `ok`.
- `marcar_aprovacao_extra(plano, id_, resolucao, aprovado, motivo="", data_captura=None)`: as mesmas recusas de `marcar_aprovacao` (buraco, aprovar sem captura) e também resolução desconhecida.
- `templates_aprovados(plano, raiz) -> list[tuple[dict, str]]`: pares (entrada, resolução) utilizáveis. As duas de `RESOLUCOES` para cada entrada de `entradas_aprovadas`; uma extra quando `extras[r].aprovado` é True e `aprovado_captura` é igual ao `data_captura` do `extra_<r>.json`, que precisa ser do mesmo snapshot (`_mesmo_snapshot`) e ter os arquivos.
- `mesclar_plano` passa a herdar também `extras` quando herda a decisão principal.

- [ ] Testes que falham primeiro:
  - `test_extras_nao_mexem_nas_aprovacoes_existentes`;
  - `test_extras_pendentes_so_de_aprovadas`;
  - `test_aprovacao_extra_presa_a_captura`;
  - `test_templates_aprovados_pares`;
  - `test_mescla_herda_extras_so_no_mesmo_snapshot`;
  - `test_marcar_extra_recusa_resolucao_desconhecida`.
- [ ] Implementar e rodar a suíte.
- [ ] Commit (só código, sem trailer).

### Task 2: subcomandos no script

**Arquivos:** modificar `scripts/capturar_templates.py` e o README (passo 2).

- `capturar-extra --plano --raiz --resolucao 1920x1080 [--so ID ...]`:
  - renderiza só essa resolução para `extras_pendentes`, com a mesma lógica da captura (modo comum do Wayback com `url_da_captura`, barra removida, DOM limpo, espera pelo seletor);
  - grava `shot_`/`dom_` e, por último, `extra_<r>.json` (status, `url_final`, `timestamp_efetivo`, `residuos_wayback`, `data_captura`, mais `url_login`/`url_arquivada`/`timestamp`/`origem` para a checagem de mesmo snapshot);
  - não toca em `meta.json` nem em `html_original.html`.
  - Reaproveitar o laço de resolução da `capturar_entrada` extraindo uma função comum, sem mudar o comportamento da captura principal.
- `revisar --resolucao 1920x1080`: grade só dessa resolução, com o estado da aprovação extra. Arquivo `revisao_1920x1080.html`.
- `aprovar`/`rejeitar --resolucao 1920x1080`: usam `marcar_aprovacao_extra` com o `data_captura` do `extra_<r>.json`, só se for do mesmo snapshot.
- [ ] Teste de fumaça do parser (os subcomandos e opções existem); o resto é verificado na Task 3.
- [ ] Commit (só código, sem trailer). README em commit separado, com trailer.

### Task 3: captura, revisão e PR 1

- [ ] `capturar-extra` nas 191 entradas aprovadas, em segundo plano. Repetir só as falhas transitórias (`--so`).
- [ ] Folhas de contato das miniaturas de 1920×1080. Propor aprovar/rejeitar por grupo, **mostrar a proposta ao Lucas** e registrar depois do ok dele.
- [ ] Conferir: `entradas_aprovadas` continua com 191 e `templates_aprovados` = 2×191 + aprovadas em 1920.
- [ ] Commit do plano (`config/templates_snapshots.json`, com trailer), push e PR 1 com a contagem por marca e resolução.

---

## PR 2 — componente visual

### Task 4: classe de tela, dobra e pHash (`visual.py`)

**Arquivos:** criar `src/mhf/visual.py` e `tests/test_visual.py`.

**Interfaces:**
- `CLASSES_TELA = {"1280x960": (1280, 960), "1366x768": (1366, 768), "1920x1080": (1920, 1080)}`.
- `classe_de_tela(largura: int) -> str`: largura mais próxima; 800 → `1280x960`.
- `abrir_imagem(caminho) -> PIL.Image` em RGB, com `LOAD_TRUNCATED_IMAGES` e `MAX_IMAGE_PIXELS = None`.
- `primeira_dobra(img, classe) -> PIL.Image`: recorte do topo, com altura = `round(largura_img * H/W da classe)`, limitada à altura da imagem.
- `phash(img, bits=64) -> str` (hex; `bits` ∈ {64, 256}).
- `sim_hash(a: str, b: str) -> float` = 1 − d_H/n.

- [ ] Testes que falham primeiro, com imagens sintéticas do Pillow:
  - `test_classe_de_tela` (1280, 1366, 1920, 800, 997, 1374);
  - `test_primeira_dobra_pagina_inteira` (1366×85000 → 1366×768);
  - `test_primeira_dobra_imagem_menor`;
  - `test_phash_tamanhos_e_identidade` (64 → 16 hex, 256 → 64 hex; mesma imagem → 1.0);
  - `test_png_truncado_abre`.
- [ ] Implementar, suíte verde, commit (sem trailer).

### Task 5: `Embedder`

**Interfaces:**
- `class Embedder(modelo: str = "small", pesos: bool = True)`:
  - `modelo` ∈ {"small", "large"};
  - `pesos=False` cria a rede sem pesos, com `torch.manual_seed(0)`, para os testes;
  - `.dim` vale 576 ou 960;
  - `.embed(img) -> np.ndarray` (float32, norma 1), com entrada `Resize((224, 224))` + `ToTensor` + normalização da ImageNet;
  - saída = `avgpool(features(x))` achatado;
  - `eval()` e `inference_mode`.
- `cosseno(a, b) -> float`.

- [ ] Testes que falham primeiro (sem pesos):
  - `test_embedding_dimensao_e_norma`;
  - `test_embedding_deterministico`;
  - `test_modelo_desconhecido` (ValueError).
- [ ] Implementar, suíte verde, commit (sem trailer).

### Task 6: `scripts/extrair_visual.py`

- **Entradas:**
  - dataset: `--indice CSV --raiz DIR`; amostras com `shot_ok=1`; classe pela largura da imagem;
  - ou templates: `--plano --raiz-templates`, com os pares de `templates_aprovados`; classe = resolução.
- `--saida PREFIXO --modelos small,large`.
- **Saídas:**
  - `PREFIXO.jsonl`: id, classe, largura, altura, `phash64`, `phash256` e os tempos;
  - `PREFIXO_small.npy` e `PREFIXO_large.npy`: linhas na ordem do JSONL;
  - `PREFIXO.erros.tsv`: erros por amostra, sem interromper a rodada.
- **Tempos por imagem, uma de cada vez:** abrir+dobra, pHash, embedding Small e embedding Large. Resumo com mediana e p95 no fim.
- Define `TORCH_HOME=data/torch` se não estiver definido.
- [ ] Teste com 3 imagens sintéticas e uma ausente, usando `Embedder(pesos=False)` via mock: alinhamento JSONL × `.npy` e o erro registrado.
- [ ] Commit (sem trailer).

### Task 7: rodada completa e PR 2

- [ ] Extração nos três datasets e nos templates, em segundo plano. Relatar os tempos (mediana e p95 por etapa) e os erros.
- [ ] Sanidade: distância de pHash e cosseno entre os pares do mesmo template e de marcas diferentes, por classe de tela. Pode repetir a tabela do spec §4 com o embedding.
- [ ] README (passo 3) e notas para a monografia (2.4.3 e 2.6), com trailer.
- [ ] Revisão independente do código, correções com TDD, push, PR 2 com a justificativa do tamanho de tela.
