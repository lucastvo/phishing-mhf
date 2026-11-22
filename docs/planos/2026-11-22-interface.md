# Interface de demonstração — plano de implementação (etapa 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** uma página local no navegador que analisa exemplos prontos do conjunto de teste e URLs ao vivo com o detector principal e mostra o veredito e o porquê.

**Architecture:** `Detector.analisar_pagina` ganha `detalhes=True`; `src/mhf/captura.py` abre URLs com o Playwright; `src/mhf/exemplos.py` cuida dos exemplos (rótulo real, arquivos, candidatos); `src/mhf/apresentacao.py` transforma um `Veredito` no JSON da tela; `src/mhf/servidor.py` (biblioteca padrão `http.server`) junta tudo; a tela é `src/mhf/web/` (HTML, CSS e JS puros). `scripts/escolher_exemplos.py` propõe os exemplos; `scripts/interface.py` sobe o servidor.

**Tech Stack:** Python 3.13, `http.server`, Playwright (Chromium já instalado), Pillow, numpy, unittest; HTML/CSS/JavaScript sem bibliotecas.

**Spec:** `docs/especificacoes/2026-11-22-interface.md`

## Global Constraints

- Nenhum pacote novo; a tela não carrega nada de fora (sem CDN, fontes externas ou bibliotecas).
- Servidor só em `127.0.0.1`, porta padrão 8000, uma requisição por vez (`http.server.HTTPServer`, sem threads).
- Detector: `data/modelos/boosting`, base `data/base`, marcas `config/marcas.json`, capturas dos templates em `data/templates/<id sem @classe>/shot_<classe>.png`.
- Classes de tela: `1280x960`, `1366x768` (padrão), `1920x1080`. Idiomas: `en-US` (padrão), `pt-BR`.
- Captura ao vivo: contexto novo por análise, `viewport` = classe, `accept_downloads=False`, `goto(wait_until="load", timeout=30000)`, campo de credencial visível (`templates.SELETOR_CREDENCIAL`, qualquer frame) por até 20 s, `networkidle` por até 10 s, `screenshot(full_page=False)`, DOM = `page.content()`.
- Exemplos só do conjunto de teste; o HTML é lido das pastas dos datasets e nunca copiado. `config/exemplos_interface.json` não guarda caminhos locais; `data/interface/` é local.
- Rótulo real = `estrato` de `data/divisao.csv`; nada reetiquetado à mão.
- Números na tela: vírgula decimal; escore, τ e sinais com 3 casas; tempos em ms inteiros.
- Nenhum tempo medido pela interface vai para README, PR ou monografia.
- Commits só de código sem trailer; com documentação, com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. URL ao vivo que redireciona para outro domínio (ex.: `microsoft.com` → `login.microsoftonline.com`): a análise usa a URL final e a tela mostra as duas. Teste na Task 2 (`test_captura_usa_url_final`).
2. Página que não abre (endereço inexistente, tempo esgotado): erro 502 com mensagem em português e o servidor continua atendendo. Teste na Task 5 (`test_url_que_nao_abre_vira_502_e_servidor_segue`).
3. Exemplo cujo arquivo sumiu do disco (o antivírus pode pôr em quarentena): o estado marca o exemplo como indisponível com o motivo, e analisá-lo dá 400 legível em vez de quebrar. Testes nas Tasks 3 e 5.
4. Domínio simulado digitado sem esquema (`microsoft-verificacao.test`) vira `https://microsoft-verificacao.test/`; esquema que não é http/https (`javascript:alert(1)`, `file:///c:/`) é recusado. Teste na Task 2.
5. Página ao vivo com DOM vazio (só `<body>`): s ausente, o veredito sai e os sinais do DOM aparecem como "—" e "DOM ausente: sim". Teste na Task 4.

---

### Task 1: detalhes do veredito no Detector

**Files:** Modify `src/mhf/cascata.py` (`Veredito`, `Detector.decidir`, `Detector.analisar_pagina`); test `tests/test_verificar.py`.

**Interfaces — produz:**
- `Veredito.detalhes: dict | None = None` (último campo).
- `Detector.decidir(..., detalhes=False)` e `Detector.analisar_pagina(imagem, html, url, classe=None, embedder=None, detalhes=False)`.
- Com `detalhes=True`, `v.detalhes` = `{"caracteristicas": {entidade: {nome: float}}, "melhor_template": {entidade: {"indice": int, "id": str, "cosseno": float}}, "s_ausente": bool, "elementos": int | None}`; `analisar_pagina` acrescenta `"dobra": PIL.Image` e `"classe": str`. Entidade sem template na classe não aparece. `melhor_template` usa `cos_<embedding do modelo>`, ignorando NaN. Página liberada no estágio 1 (só modelos com estágio 1): `caracteristicas` e `melhor_template` vazios.

- [ ] **Teste que falha** `test_detalhes_nao_mudam_o_veredito`: com a base sintética e `_detector(b, theta_h=64, tau=0.0)`, `analisar_pagina` com e sem `detalhes` dá os mesmos `rotulo, entidade, estagio, motivo, escore, escores`; `v.detalhes["caracteristicas"].keys() == {"Netflix", "PayPal"}`, cada uma com as 7 chaves de `cascata.nomes_caracteristicas()`; `v.detalhes["melhor_template"]["PayPal"]["id"]` é um id de item PayPal da classe; `v.detalhes["dobra"].size == (1366, 768)`; `v.detalhes["classe"] == "1366x768"`; sem `detalhes`, `v.detalhes is None`.
- [ ] **Teste que falha** `test_detalhes_sem_dom`: HTML `"<html><body></body></html>"` → `v.detalhes["s_ausente"] is True` e `caracteristicas[...]["s_ausente"] == 1.0`.
- [ ] Rodar `python -m unittest tests.test_verificar -v`: os dois falham.
- [ ] Implementar (guardar `X[0]`, `colunas` e `r2` dentro de `decidir` quando `detalhes`).
- [ ] `python -m unittest discover -s tests`: tudo passa (187 + 2).
- [ ] Commit (código): `Detector: detalhes do veredito (características por marca e template mais parecido)`.

### Task 2: captura ao vivo

**Files:** Create `src/mhf/captura.py`, `tests/test_captura.py`; modify `scripts/capturar_templates.py` (importa `esperar_credencial` de `mhf.captura` em vez de defini-la).

**Interfaces — produz:**
- `normalizar_url(texto: str) -> str`: tira espaços; sem esquema → prefixa `https://`; só `http`/`https` e com host, senão `ValueError` com mensagem em português.
- `esperar_credencial(pagina, seletor, tempo_ms) -> bool` (movida sem mudança de comportamento).
- `@dataclass PaginaCapturada(imagem: bytes, html: str, url_digitada: str, url_final: str, titulo: str, status: int | None, credencial: bool, tempo_s: float)`.
- `class ErroCaptura(RuntimeError)`.
- `capturar_pagina(navegador, url, classe="1366x768", idioma="en-US", espera_credencial_ms=20000) -> PaginaCapturada`: `navegador` é um `Browser` do Playwright (ou um falso com a mesma interface: `new_context(...)`, `new_page()`, `goto`, `frames`, `wait_for_load_state`, `wait_for_timeout`, `screenshot`, `content`, `url`, `title`, `close`); classe fora de `visual.CLASSES_TELA` ou idioma fora de `("en-US", "pt-BR")` → `ValueError`; erro de navegação → `ErroCaptura("não foi possível abrir a página: …")`; o contexto é sempre fechado.
- `class NavegadorAoVivo`: `capturar(url, classe, idioma) -> PaginaCapturada` (inicia `sync_playwright().start()` e `chromium.launch()` na primeira chamada) e `fechar()`.

- [ ] **Testes que falham:** `test_normalizar_url` (`"microsoft-verificacao.test"` → `"https://microsoft-verificacao.test/"`, `" https://a.com/x "` → `"https://a.com/x"`, `"javascript:alert(1)"`, `"file:///c:/"`, `"https://"` e `""` levantam `ValueError`); `test_captura_usa_url_final` (falso cujo `page.url` é `https://login.microsoftonline.com/x` depois do `goto("https://microsoft.com/")` → `url_final` é a do redirecionamento e `url_digitada` a original); `test_captura_parametros_do_contexto` (o falso registra `viewport={"width": 1920, "height": 1080}`, `locale="pt-BR"`, `accept_downloads=False`, `full_page=False` e `timeout=30000`); `test_captura_sem_credencial_segue` (nenhum campo visível → `credencial is False` e a captura sai); `test_erro_de_navegacao_vira_erro_captura` (o `goto` do falso levanta → `ErroCaptura` e `close()` chamado); `test_classe_e_idioma_invalidos`.
- [ ] Teste real `test_captura_real` só com `MHF_TESTE_NAVEGADOR=1` (`unittest.skipUnless`): captura `https://example.com/` em 1366×768 e confere PNG 1366×768 e `"<body"` no HTML.
- [ ] Rodar `python -m unittest tests.test_captura -v`: falham.
- [ ] Implementar; mover `esperar_credencial`; tempo de espera do falso controlável (o falso não deve fazer o teste esperar 20 s: use `espera_credencial_ms` pequeno nos testes).
- [ ] Suíte inteira passa.
- [ ] Commit (código): `Captura ao vivo de uma página com o Playwright`.

### Task 3: exemplos — rótulo real, arquivos e candidatos

**Files:** Create `src/mhf/exemplos.py`, `tests/test_exemplos.py`; modify `scripts/medir_latencia.py` (`sortear_paginas` passa a usar `ler_pagina_do_dataset`).

**Interfaces — produz:**
- `ler_pagina_do_dataset(linha: dict, raiz: str, classe: str | None) -> dict` com `imagem` (PNG da primeira dobra, como em `medir_latencia.sortear_paginas` hoje), `html` (bytes ou None se `html_util != "1"`), `url` (`linha["url"]` ou o id), `classe`. Arquivo ausente → `FileNotFoundError` com o caminho.
- `situacao_real(estrato: str, rotulo: str, entidade: str | None, simulado: bool) -> str` ∈ `acertou`, `errou`, `marca_errada`, `marca_desconhecida`, `sem_comparacao` (regras da seção 6.1 do desenho).
- `texto_real(estrato: str, marca_dataset: str) -> str`: entidade → `"phishing de X"` (+ `" (rótulo do dataset: M)"` se M ≠ X); `fora` → `"phishing de marca fora da base (M)"`; `sem_marca` → `"phishing (o dataset não informa a marca)"`; `benigno` → `"legítima"`.
- `frase_situacao(situacao: str, estrato: str, entidade_real: str | None) -> str`: `acertou` → `"✓ acertou"`; `errou` → `"✗ errou: alerta falso"` (benigno) ou `"✗ errou: phishing não detectado"`; `marca_errada` → `"✗ detectou o phishing, mas errou a marca (real: X)"`; `marca_desconhecida` → `"detectado como phishing; o dataset não informa a marca"` (sem_marca) ou `"detectado como phishing; a marca real está fora da base"` (fora); `sem_comparacao` → `"domínio simulado: a página foi tirada do lugar dela, então não há rótulo real para comparar"`.
- `@dataclass Exemplo(numero: int, dataset: str, id: str, grupo: str, titulo: str, nota: str, estrato: str | None, marca_dataset: str, linha: dict | None, raiz: str | None, classe: str | None, disponivel: bool, motivo: str)`.
- `ler_exemplos(caminho_config, caminho_datasets, divisao) -> tuple[list[Exemplo], list[dict]]` (exemplos numerados a partir de 1 e URLs sugeridas). Indisponível (com `motivo`) quando: `datasets.json` ausente (motivo exato: `"data/interface/datasets.json não existe; gere com scripts/escolher_exemplos.py (README, passo 7)"`), dataset sem índice, id fora do índice ou da divisão, id fora do conjunto de teste, captura ou HTML útil ausente no disco.
- `gravar_datasets(caminho, datasets: dict)` e `ler_datasets(caminho) -> dict` (`{nome: {"indice", "raiz", "classe"}}`).
- `tipo_do_candidato(estrato, rotulo, entidade, motivo, s_ausente) -> str` ∈ `phishing_marca_certa`, `phishing_marca_errada`, `phishing_nao_detectado_sem_dom`, `phishing_nao_detectado`, `phishing_sem_marca_nao_detectado`, `phishing_sem_marca_detectado`, `legitima_dominio_oficial`, `legitima_sem_dom`, `legitima_comum`, `alerta_falso`.
- `folha_de_contato(itens: list[dict], saida: str, colunas=4, largura=400)`: grade JPEG das dobras (`itens[i]["imagem"]`, PNG) com legenda `itens[i]["legenda"]`.

- [ ] **Testes que falham:** `test_situacao_real` (uma linha por caso: Microsoft/phishing/Microsoft → acertou; Microsoft/phishing/PayPal → marca_errada; Microsoft/legitima → errou; benigno/legitima → acertou; benigno/phishing → errou; sem_marca/phishing → marca_desconhecida; fora/legitima → errou; qualquer com simulado → sem_comparacao); `test_texto_e_frase`; `test_tipo_do_candidato` (um caso por tipo); `test_ler_pagina_recorta_a_dobra` (PNG 1366×3000 com classe `1366x768` → dobra 1366×768; `html_util="0"` → `html is None`); `test_exemplo_indisponivel_quando_arquivo_some` (índice e divisão sintéticos; apagar a captura → `disponivel False` e `motivo` com o caminho); `test_exemplo_fora_do_teste_indisponivel`; `test_datasets_ida_e_volta`; `test_folha_de_contato` (3 itens → JPEG que abre, largura 4×400).
- [ ] Rodar `python -m unittest tests.test_exemplos -v`: falham.
- [ ] Implementar; trocar o recorte inline de `medir_latencia.sortear_paginas` por `ler_pagina_do_dataset`.
- [ ] Suíte inteira passa (inclui `tests/test_medir_latencia.py` sem mudança).
- [ ] Commit (código): `Exemplos da interface: rótulo real, páginas dos datasets e tipos de candidato`.

### Task 4: apresentação do resultado

**Files:** Create `src/mhf/apresentacao.py`, `tests/test_apresentacao.py`.

**Interfaces — consome:** `Veredito` com `detalhes` (Task 1); `Exemplo`, `situacao_real`, `texto_real`, `frase_situacao` (Task 3); `PaginaCapturada` (Task 2).

**Interfaces — produz:**
- `numero(v, casas=3) -> str` (vírgula decimal; NaN/None → `"—"`).
- `frase_do_motivo(v: Veredito, tau: float, tabela) -> str`, com o texto exato:
  - `phishing`: `"Parece {X} (escore {e}, limiar {τ}) e o domínio {d} não é de {X}."`
  - `dominio_legitimo_estagio2`: `"Parece {X}, mas está num domínio oficial de {X} ({d})."`
  - `abaixo_do_limiar`: `"Não se parece o bastante com nenhuma marca protegida (mais próxima: {X}, escore {e} < {τ})."`
  - `sem_template_proximo`: `"Nenhum template visualmente parecido (pHash)."`
  - `dominio_legitimo_estagio1`: `"O template mais parecido pelo pHash é de {X}, e o domínio {d} é oficial de {X}."`
- `sinais_legiveis(caracteristicas: dict) -> list[dict]` (`{"nome", "rotulo", "valor", "texto"}`), na ordem e com os rótulos: `sim_h64` "Semelhança do pHash" (texto `"0,859 (9 de 64 bits diferentes)"`, bits = round((1 − v)·64)); `cos_small` "Cosseno do embedding (MobileNetV3)"; `jaccard_caminhos` "Caminhos do DOM em comum (Jaccard)"; `jaccard_criticos` "Elementos críticos em comum (formulário, senha, envio)"; `sim_contagens` "Semelhança das contagens do DOM"; `hash_igual` "DOM idêntico a um template" (sim/não); `s_ausente` "DOM ausente ou com até 5 elementos" (sim/não). NaN → `"—"`.
- `template_exibido(v: Veredito, base) -> dict | None`: `{"id", "marca", "variante", "ano", "origem", "cosseno", "url": "/api/template?id=<id codificado>"}` a partir de `v.detalhes["melhor_template"][v.entidade]` (ano = 4 primeiros dígitos do `timestamp`; origem `"Wayback"` ou `"ao vivo"`).
- `montar_resultado(v, tau, base, tabela, url_analisada, simulado, exemplo=None, pagina=None) -> dict` com as chaves: `veredito` (`rotulo`, `titulo` = `"PHISHING — imita {X}"` ou `"Legítima"`, `frase`, `motivo`), `marca`, `escore`, `tau`, `escores` (5 maiores, `[{"marca", "escore"}]`, decrescente), `sinais`, `template`, `dominio`, `dominio_simulado`, `dominios_oficiais` (da `v.entidade` em `config/marcas.json`), `tempos_ms` (inteiros), `captura` (`"data:image/png;base64,…"` da dobra), `classe`, `real` (None ou `{"texto", "situacao", "frase", "nota", "titulo"}`), `pagina` (None ou `{"url_digitada", "url_final", "url_analisada", "titulo", "status", "credencial", "tempo_abrir_s"}`), `legenda_template` = `"O classificador usa o melhor valor de cada sinal entre todos os templates da marca; esta é a imagem mais parecida."`.

- [ ] **Testes que falham** (com `Veredito` montado à mão, sem detector): `test_numero`; `test_frase_de_cada_motivo` (os 5 textos acima, com `numero`); `test_sinais_legiveis` (ordem, rótulos, `"0,859 (9 de 64 bits diferentes)"` para 0.859375, NaN → `"—"`, `hash_igual` 1.0 → `"sim"`); `test_sinais_dom_vazio` (Review Focus 5: características do DOM NaN e `s_ausente` 1.0 → três `"—"` e `"DOM ausente ou com até 5 elementos"` = `"sim"`); `test_template_exibido`; `test_resultado_exemplo` (`real.situacao == "acertou"`, `pagina is None`); `test_resultado_simulado` (`dominio_simulado True`, `real.situacao == "sem_comparacao"`); `test_resultado_url` (`pagina` preenchida, `real is None`); `test_resultado_e_json` (`json.dumps(resultado)` não falha nem usa NaN: `allow_nan=False`).
- [ ] Rodar `python -m unittest tests.test_apresentacao -v`: falham.
- [ ] Implementar.
- [ ] Suíte inteira passa.
- [ ] Commit (código): `Apresentação do veredito para a interface`.

### Task 5: servidor e comando

**Files:** Create `src/mhf/servidor.py`, `scripts/interface.py`, `tests/test_servidor.py`.

**Interfaces — consome:** Tasks 1–4.

**Interfaces — produz:**
- `class Aplicacao(detector, embedder, tabela, raiz_templates, exemplos, urls_sugeridas, navegador=None)`: `estado() -> dict` (`modelo`, `tau`, `templates`, `marcas`, `classes`, `classe_padrao`, `idiomas`, `exemplos` = `[{"numero", "grupo", "titulo", "disponivel", "motivo"}]`, `urls_sugeridas`, `navegador`, `aviso_url`); `analisar_exemplo(numero, url_simulada=None) -> dict`; `analisar_url(url, classe, idioma, url_simulada=None) -> dict`; `imagem_template(id_template) -> bytes`; `fechar()`. Entradas inválidas → `ValueError`; exemplo indisponível → `ValueError(motivo)`; `navegador=None` → `analisar_url` levanta `ValueError("a análise por URL está desligada (--sem-navegador)")`. `imagem_template` só aceita ids presentes em `detector.base.itens`.
- `aviso_url` = `"O navegador vai abrir a página de verdade. Não cole links suspeitos reais; para ver phishing, use os exemplos."`
- `criar_servidor(app, porta=8000, host="127.0.0.1") -> http.server.HTTPServer`. Rotas da seção 5 do desenho; `GET /` e `GET /estatico/<nome>` só para `index.html`, `estilo.css`, `app.js` de `src/mhf/web/`; `ValueError` → 400, `ErroCaptura` → 502, outra exceção → 500 (sempre `{"erro": mensagem}` e o servidor segue).
- `scripts/interface.py`: `--modelo data/modelos/boosting`, `--base data/base`, `--marcas config/marcas.json`, `--templates data/templates`, `--exemplos config/exemplos_interface.json`, `--datasets data/interface/datasets.json`, `--divisao data/divisao.csv`, `--porta 8000`, `--nao-abrir`, `--sem-navegador`. Carrega tudo, cria `visual.Embedder("small")`, aquece com uma imagem branca 1366×768, imprime `Pronto: http://127.0.0.1:<porta> (Ctrl+C para sair)`, abre o navegador (`webbrowser.open`) e fecha o Chromium e o servidor no Ctrl+C.

- [ ] **Testes que falham** (servidor em `porta=0` numa thread, com detector sintético de `tests/test_verificar._detector`, `Embedder("small", pesos=False)` e um navegador falso com `capturar(url, classe, idioma)`): `test_estado`; `test_exemplo` (200, `real` preenchido); `test_exemplo_com_dominio_simulado`; `test_exemplo_indisponivel_400` (Review Focus 3); `test_url` (200, `pagina.url_final`); `test_url_que_nao_abre_vira_502_e_servidor_segue` (o falso levanta `ErroCaptura`; depois `GET /api/estado` ainda responde 200 — Review Focus 2); `test_entradas_invalidas_400` (classe `800x600`, idioma `fr-FR`, URL `javascript:alert(1)`, exemplo 99, JSON quebrado); `test_template` (PNG de um id da base; `id=../../config/marcas.json` → 400); `test_estaticos` (`/` devolve HTML; `/estatico/../README.md` → 404); `test_sem_navegador_400`.
- [ ] Rodar `python -m unittest tests.test_servidor -v`: falham.
- [ ] Implementar (com `index.html` mínimo provisório para o teste de estáticos; a tela completa vem na Task 6).
- [ ] Suíte inteira passa.
- [ ] Commit (código): `Servidor local da interface e comando interface.py`.

### Task 6: a tela

**Files:** Create/replace `src/mhf/web/index.html`, `src/mhf/web/estilo.css`, `src/mhf/web/app.js`; test `tests/test_servidor.py` (um teste a mais).

**Interfaces — consome:** `GET /api/estado`, `POST /api/exemplo`, `POST /api/url`, `GET /api/template` (Task 5) e o JSON de `montar_resultado` (Task 4).

Layout e conteúdo da seção 8 do desenho (esboço 8.1). Textos fixos exatos:
- cabeçalho: `MHF · detector de phishing por impressão digital de layout` e a linha com modelo, nº de templates e marcas, `limiar τ = <tau>` e `local`;
- aba URL: o `aviso_url`; campo "analisar como se estivesse em…" (também na aba de exemplos); enquanto abre: `Abrindo a página e esperando o formulário de login (até 20 s)…`;
- linha de tempo da URL ao vivo: `Abrir a página no navegador automatizado: <x> s (na extensão a página já está aberta, então esse tempo não existe).`;
- "Como o MHF decide" (recolhido, `<details>`): 1. Captura da janela (a primeira dobra da página). 2. Impressão digital φ = (h, e, s): pHash, embedding da MobileNetV3 e estrutura do DOM. 3. Comparação com os templates da base no mesmo tamanho de tela. 4. Escore de cada marca pelo gradient boosting. 5. Limiar τ e checagem de domínio: phishing só se o escore passa de τ e o domínio não é da marca.

Vermelho/verde só no veredito, sempre com ícone e texto; fonte grande no veredito; legível em projetor.

- [ ] **Teste que falha** `test_tela_sem_recursos_externos`: em `index.html`, `estilo.css` e `app.js`, nenhum `src=`, `href=`, `url(` ou `@import` aponta para `http://`, `https://` ou `//`.
- [ ] Implementar a tela; o teste passa; suíte inteira passa.
- [ ] Verificação manual: `python scripts/interface.py --nao-abrir`, abrir `http://127.0.0.1:8000` no navegador do app, analisar `https://example.com/` com e sem domínio simulado; conferir veredito, imagens, barras com τ, sinais, domínios, tempos e o erro de uma URL inexistente. Capturas de tela guardadas no scratchpad.
- [ ] Commit (código): `Tela da interface (HTML, CSS e JavaScript sem dependências)`.

### Task 7: escolha dos exemplos

**Files:** Create `scripts/escolher_exemplos.py`, `tests/test_escolher_exemplos.py`, `config/exemplos_interface.json`.

**Interfaces — consome:** `carregar_conjunto` (`mhf.conjuntos`), `cascata.pontuar_amostras`/`aplicar_cascata`, `exemplos.tipo_do_candidato`, `ler_pagina_do_dataset`, `folha_de_contato`, `gravar_datasets`, `Detector.analisar_pagina`.

`scripts/escolher_exemplos.py`: `--dataset NOME ÍNDICE RAIZ [CLASSE]` (repetível, como `medir_latencia.py`), `--tabelas` (padrão: as três `data/similaridades_*`), `--divisao data/divisao.csv`, `--modelo data/modelos/boosting`, `--base`, `--marcas`, `--por-grupo 3`, `--semente 0`, `--saida data/interface`.
1. **Fase A (tabelas):** `carregar_conjunto(..., conjunto="teste")`, veredito de cada amostra pela tabela (como `verificar_tabela`) e `tipo_do_candidato`; sorteia até `--por-grupo` amostras por (tipo, estrato, dataset).
2. **Fase B (páginas brutas):** analisa cada sorteada com `analisar_pagina` e grava em `<saida>/candidatos.json`: número, dataset, id, tipo, estrato, marca do dataset, veredito da tabela e da página (`rotulo`, `entidade`, `motivo`, `escore`), `concorda` e a URL; uma `folha_<tipo>.jpg` por tipo (legenda `"<número> · <veredito> (<escore>)"`); e `<saida>/datasets.json`.

- [ ] **Teste que falha** `test_escolher_exemplos_main` (cenário sintético: tabelas como em `tests/test_treinar.montar_cenario`, mais índice CSV, divisão e capturas PNG criados no teste para os mesmos ids): só ids do teste em `candidatos.json`; cada tipo presente tem sua folha; `datasets.json` ida e volta; nenhum id com `conjunto != "teste"`.
- [ ] Implementar; suíte passa. Commit (código): `Escolha dos exemplos da interface no conjunto de teste`.
- [ ] Rodar com os dados reais (comando da seção 11 do desenho, com os índices e raízes de `Downloads`).
- [ ] Montar a proposta dos 12 pelos critérios da seção 6.1 do desenho, só com candidatos de `concorda == true`, e **mostrar ao Lucas** (folhas de contato + tabela com tipo, veredito, escore e nota). Esperar a aprovação.
- [ ] Gravar `config/exemplos_interface.json` (`{"exemplos": [{"dataset", "id", "grupo", "titulo", "nota"}], "urls_sugeridas": []}`) com os aprovados; conferir na interface que os 12 aparecem disponíveis e dão o veredito de `candidatos.json`.
- [ ] Commit (com trailer): `Exemplos da interface: 8 acertos e 4 erros do conjunto de teste`.

### Task 8: URLs sugeridas

**Files:** Modify `config/exemplos_interface.json` (`urls_sugeridas`: `[{"titulo", "url", "url_simulada", "classe", "idioma"}]`).

- [ ] Pela interface, analisar cada candidata da seção 7.3 do desenho (`login.live.com`, `netflix.com/login`, `login.yahoo.com`, `dropbox.com/login`, `linkedin.com/login`, `itau.com.br`, este com `pt-BR`), uma por vez, com o domínio real e com `https://<marca>-verificacao.test/`.
- [ ] Entram só as que dão legítima no domínio real e phishing da marca certa no simulado; anotar as que saíram e por quê (para o PR).
- [ ] Commit (com trailer): `Interface: URLs sugeridas conferidas`.

### Task 9: README, revisão e PR

**Files:** Modify `README.md` (passo 7), `docs/especificacoes/2026-11-22-interface.md` (seção de resultados da implementação: exemplos escolhidos, URLs que ficaram, desvios do desenho, se houver).

- [ ] README: passo 7 com os dois comandos da seção 11 do desenho e o que a tela mostra; commit (com trailer).
- [ ] Revisão independente da branch inteira (subagente) contra o desenho e este plano; corrigir os achados importantes; listar os menores ao Lucas.
- [ ] Verificação completa: suíte inteira; interface aberta com os 12 exemplos e as URLs sugeridas (real e simulado); capturas de tela para o PR.
- [ ] `git push -u origin interface` e `gh pr create --base main` (PR #10), descrição em tom de documentação, sem a linha "Generated with Claude Code".
