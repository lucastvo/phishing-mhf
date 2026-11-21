# Captura de templates com vários anos — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** script que planeja (Wayback CDX), captura (Playwright) e organiza a revisão de templates de login das marcas de 𝒯 em vários anos (2019–2026), com uma "receita" versionada da base.

**Arquitetura:**
- Funções puras e testáveis sem rede ficam em `src/mhf/templates.py`.
- Rede (CDX, `id_`), Playwright e linha de comando ficam em `scripts/capturar_templates.py`.
- O plano/receita é um JSON versionado (`config/templates_snapshots.json`). Imagens e HTMLs vão para `data/templates/`, fora do git.

**Stack:** Python 3.13, stdlib (`urllib`, `json`, `re`, `unicodedata`, `datetime`), Playwright 1.65 (Chromium), `unittest`.

**Spec:** `docs/especificacoes/2026-11-20-base-de-templates.md`

## Restrições globais

- Nomes de código em **português**, como no resto do projeto. Testes com `unittest`, rodados por `python -m unittest discover -s tests`.
- Testes **não acessam a rede** nem abrem navegador.
- Anos-alvo **2019 a 2026**, alvo = **1º de janeiro**, tolerância **183 dias**. Resoluções **1280×960** e **1366×768**, screenshot só da área visível.
- Snapshots renderizados com o modificador **`if_`**; HTML original baixado com **`id_`**. Pausa de **1,5 s** entre requisições ao Wayback.
- O script **não clica** em nada e **não contorna** CAPTCHA/bloqueio.
- Nunca commitar `CLAUDE.md`, `data/` ou `*.csv`. Usar `.json` para arquivos versionados de configuração (o `.gitignore` ignora `*.csv`).
- **Antes do primeiro commit:** perguntar ao Lucas o formato de autoria dos commits. Mensagens de commit em português.
- **Refinamentos em relação ao spec:**
  - a pasta de um snapshot usa `AAAA-MM-DD`, não `AAAA-MM`, porque dois snapshots no mesmo mês colidiriam; a captura ao vivo usa `ao-vivo`;
  - os modos `--planejar/--capturar/--revisar` viram subcomandos `planejar/capturar/revisar`, mais `aprovar/rejeitar`.

## Foco da revisão

1. **API CDX fora do ar ou lenta** (503, timeout): `planejar` registra `buraco: "erro_consulta"` para os anos daquela variante e segue para a próxima. Uma nova rodada preenche. *(teste na Tarefa 2)*
2. **Captura interrompida no meio** (Ctrl-C, pasta sem `meta.json`): a próxima rodada refaz essa entrada. *(teste na Tarefa 4)*
3. **URLs reescritas pelo Wayback em todas as formas** (absoluta, `//web.archive.org`, relativa `/web/…`, modificadores `im_`/`js_`/`cs_`/`if_`): todas voltam à URL original. Caminhos legítimos como `/web/2020/` sem esquema depois **não** são tocados. *(teste na Tarefa 3)*
4. **Rodar `planejar` de novo depois de aprovações** não apaga `aprovado`/`motivo` das entradas com o mesmo id. *(teste na Tarefa 2)*
5. **Nomes com acento ou espaço** (Itaú, Bank of America) geram pastas e ids estáveis e válidos no Windows. *(teste na Tarefa 1)*

---

### Formato de uma entrada do plano (usado por todas as tarefas)

```json
{"id": "itau/pessoal/2019-06-30", "entidade": "Itaú", "variante": "pessoal",
 "url_login": "https://www.itau.com.br/", "locale": "pt-BR",
 "origem": "wayback", "timestamp": "20190630120000", "status_cdx": 200,
 "anos_alvo": [2019], "buraco": null, "aprovado": null, "motivo": ""}
```

- **Ao vivo:** `origem: "ao_vivo"`, `timestamp: null`, `status_cdx: null`, `anos_alvo: [2026]`, id `.../ao-vivo`.
- **Buraco:** `timestamp: null`, `buraco: "sem_snapshot" | "erro_consulta"`, id `.../buraco-<ano>`. Buracos nunca são capturados.

---

### Tarefa 1: variantes de login, slugs e ids

**Arquivos:**
- Criar: `src/mhf/templates.py`, `tests/test_templates.py` e `config/marcas.exemplo.json`.

**Interfaces:**
- Produz:
  - `VarianteLogin` (dataclass congelada: `entidade: str`, `variante: str`, `url: str`, `locale: str`);
  - `ler_marcas(caminho: str) -> list[VarianteLogin]`;
  - `slug(texto: str) -> str`;
  - `id_entrada(entidade: str, variante: str, rotulo: str) -> str`.
- `config/marcas.exemplo.json` segue o formato do spec §4.1 com duas variantes: PayPal `padrao` (`https://www.paypal.com/signin`, `en-US`) e Microsoft `pessoal` (`https://login.live.com/login.srf`, `en-US`). A etapa 1 criará o `config/marcas.json` completo no mesmo formato.

- [ ] **Passo 1: testes que falham**

```python
def test_slug(self):
    self.assertEqual(templates.slug("Itaú"), "itau")
    self.assertEqual(templates.slug("Bank of America"), "bank_of_america")
    self.assertEqual(templates.slug("Caixa Econômica Federal"), "caixa_economica_federal")

def test_id_entrada(self):
    self.assertEqual(templates.id_entrada("Itaú", "pessoal", "2019-06-30"), "itau/pessoal/2019-06-30")

def test_ler_marcas_exemplo(self):
    vs = templates.ler_marcas(CAMINHO_EXEMPLO)  # config/marcas.exemplo.json
    self.assertEqual([(v.entidade, v.variante) for v in vs], [("PayPal", "padrao"), ("Microsoft", "pessoal")])
    self.assertEqual(vs[1].url, "https://login.live.com/login.srf")
```

- [ ] **Passo 2:** `python -m unittest discover -s tests` → FALHA (módulo `mhf.templates` não existe).
- [ ] **Passo 3: implementar.** `slug` usa `unicodedata.normalize("NFKD")` para tirar acentos, deixa tudo em minúsculas e troca o que não for `[a-z0-9]` por `_`, sem `_` repetido nem nas pontas. `ler_marcas` lê com `encoding="utf-8"` e achata `logins` de cada entidade.
- [ ] **Passo 4:** testes → OK.
- [ ] **Passo 5: commit.** `git add src/mhf/templates.py tests/test_templates.py config/marcas.exemplo.json`, mensagem "Variantes de login e identificadores dos templates".

---

### Tarefa 2: escolha de snapshot, plano por variante e mescla com aprovações

**Arquivos:**
- Modificar: `src/mhf/templates.py`, `tests/test_templates.py`.

**Interfaces:**
- Consome: `VarianteLogin` e `id_entrada` (Tarefa 1).
- Produz:
  - `ANOS_PADRAO = range(2019, 2027)` e `TOLERANCIA = timedelta(days=183)`;
  - `escolher_snapshot(capturas: list[tuple[str, int]], alvo: datetime, tolerancia: timedelta = TOLERANCIA) -> tuple[str, int] | None`;
  - `planejar_variante(v: VarianteLogin, capturas: list[tuple[str, int]] | None, anos=ANOS_PADRAO) -> list[dict]`;
  - `mesclar_plano(novo: list[dict], antigo: list[dict]) -> list[dict]`.

Regras:
- `capturas` são linhas da CDX (`timestamp` de 14 dígitos, `status`).
- "Dentro da tolerância" significa |timestamp − alvo| ≤ 183 dias (inclusivo).
- `escolher_snapshot` prefere o status 200 mais próximo do alvo dentro da tolerância. Só se não houver 200, aceita o 3xx mais próximo. Devolve `None` se nada couber.
- Em `planejar_variante`, `capturas=None` significa que a consulta falhou: todos os anos viram buraco `erro_consulta`. Anos que escolhem o mesmo timestamp viram **uma** entrada, com `anos_alvo` somados. O rótulo do id é a data do timestamp (`AAAA-MM-DD`). Sempre acrescenta a entrada ao vivo.

- [ ] **Passo 1: testes que falham**

```python
def test_prefere_200_mais_proximo(self):
    caps = [("20181220000000", 200), ("20190105000000", 302), ("20190301000000", 200)]
    self.assertEqual(templates.escolher_snapshot(caps, datetime(2019, 1, 1)), ("20181220000000", 200))

def test_aceita_3xx_sem_200(self):
    self.assertEqual(templates.escolher_snapshot([("20190105000000", 301)], datetime(2019, 1, 1)), ("20190105000000", 301))

def test_fora_da_tolerancia(self):
    self.assertIsNone(templates.escolher_snapshot([("20190720000000", 200)], datetime(2019, 1, 1)))  # 200 dias

def test_planejar_deduplica_buraco_e_ao_vivo(self):
    v = templates.VarianteLogin("PayPal", "padrao", "https://www.paypal.com/signin", "en-US")
    caps = [("20190702000000", 200), ("20220110000000", 200)]  # 182 e 183 dias de 2019 e 2020: os dois caem no mesmo
    plano = templates.planejar_variante(v, caps, anos=range(2019, 2023))
    ids = {e["id"]: e for e in plano}
    self.assertEqual(ids["paypal/padrao/2019-07-02"]["anos_alvo"], [2019, 2020])
    self.assertEqual(ids["paypal/padrao/buraco-2021"]["buraco"], "sem_snapshot")
    self.assertEqual(ids["paypal/padrao/2022-01-10"]["anos_alvo"], [2022])
    self.assertEqual(ids["paypal/padrao/ao-vivo"]["origem"], "ao_vivo")

def test_planejar_erro_consulta(self):
    v = templates.VarianteLogin("PayPal", "padrao", "https://www.paypal.com/signin", "en-US")
    plano = templates.planejar_variante(v, None, anos=range(2019, 2021))
    self.assertEqual(sorted(e["buraco"] for e in plano if e["buraco"]), ["erro_consulta", "erro_consulta"])

def test_mescla_preserva_aprovacao(self):
    antigo = [{"id": "x/y/2019-07-01", "aprovado": True, "motivo": "ok"}]
    novo = [{"id": "x/y/2019-07-01", "aprovado": None, "motivo": ""}, {"id": "x/y/ao-vivo", "aprovado": None, "motivo": ""}]
    m = {e["id"]: e for e in templates.mesclar_plano(novo, antigo)}
    self.assertEqual((m["x/y/2019-07-01"]["aprovado"], m["x/y/2019-07-01"]["motivo"]), (True, "ok"))
    self.assertIsNone(m["x/y/ao-vivo"]["aprovado"])
```

- [ ] **Passo 2:** testes → FALHA.
- [ ] **Passo 3:** implementar as três funções em `src/mhf/templates.py`. A ordem das entradas segue o ano-alvo, com a entrada ao vivo no fim.
- [ ] **Passo 4:** testes → OK.
- [ ] **Passo 5: commit.** Mensagem "Escolha de snapshots do Wayback e plano por variante".

---

### Tarefa 3: URLs do Wayback e limpeza do DOM

**Arquivos:**
- Modificar: `src/mhf/templates.py`, `tests/test_templates.py`.

**Interfaces:**
- Produz:
  - `url_wayback(timestamp: str, url: str, modo: str = "if_") -> str`;
  - `remover_prefixo_wayback(html: str) -> str`;
  - `SELETOR_CREDENCIAL: str`.

`SELETOR_CREDENCIAL` vale `'input[type=password], input[type=email], input[name*=user i], input[name*=login i], input[name*=email i], input[id*=user i]'`.

- [ ] **Passo 1: testes que falham**

```python
def test_url_wayback(self):
    self.assertEqual(templates.url_wayback("20200601224504", "https://www.paypal.com/signin"),
                     "https://web.archive.org/web/20200601224504if_/https://www.paypal.com/signin")
    self.assertTrue(templates.url_wayback("20200601224504", "https://x.com/", "id_").endswith("20200601224504id_/https://x.com/"))

def test_remove_prefixos(self):
    casos = {
        'action="https://web.archive.org/web/20200601224504/https://login.live.com/ppsecure/post.srf"':
            'action="https://login.live.com/ppsecure/post.srf"',
        'src="//web.archive.org/web/20200601224504im_/https://x.com/a.png"': 'src="https://x.com/a.png"',
        'src="/web/20200601224504js_/https://x.com/a.js"': 'src="https://x.com/a.js"',
        'href="http://web.archive.org/web/20200601224504if_/http://x.com/"': 'href="http://x.com/"',
        'href="/web/2020/relatorio"': 'href="/web/2020/relatorio"',  # caminho legítimo: intocado
    }
    for entrada, esperado in casos.items():
        self.assertEqual(templates.remover_prefixo_wayback(entrada), esperado)
```

- [ ] **Passo 2:** testes → FALHA.
- [ ] **Passo 3:** implementar. Um único regex remove `(?:(?:https?:)?//web\.archive\.org)?/web/\d{1,14}(?:[a-z]{2}_)?/` **somente** quando o que vem depois começa com `http:` ou `https:` (lookahead).
- [ ] **Passo 4:** testes → OK.
- [ ] **Passo 5: commit.** Mensagem "URLs do Wayback e remoção do prefixo no DOM capturado".

---

### Tarefa 4: subcomandos `planejar` e `capturar`

**Arquivos:**
- Criar: `scripts/capturar_templates.py`.
- Modificar: `src/mhf/templates.py`, `tests/test_templates.py`.

**Interfaces:**
- Consome: tudo das Tarefas 1–3.
- Produz:
  - `entradas_pendentes(plano: list[dict], raiz: str) -> list[dict]`, em `templates.py`. Uma entrada é pendente quando não é buraco e quando `<raiz>/<id>/meta.json` não existe ou tem algum status ≠ `"ok"`;
  - `RESOLUCOES = {"1280x960": (1280, 960), "1366x768": (1366, 768)}`, em `templates.py`;
  - **CLI:**
    - `python scripts/capturar_templates.py planejar --marcas <json> --plano <json>`;
    - `python scripts/capturar_templates.py capturar --plano <json> --raiz <pasta> [--so ID ...]`.

`meta.json` traz as chaves: `entidade`, `variante`, `url_login`, `origem`, `url_snapshot`, `timestamp`, `anos_alvo`, `data_captura` (ISO), `resolucoes` e `versoes` (`{"playwright": …, "chromium": …}`). Cada item de `resolucoes` tem `{"status", "tempo_s", "url_final"}`.

- [ ] **Passo 1: testes que falham** (com `tempfile.TemporaryDirectory`)

```python
def test_pendentes(self):
    plano = [{"id": "a/p/2019-07-01", "buraco": None}, {"id": "a/p/2020-01-03", "buraco": None},
             {"id": "a/p/2021-01-02", "buraco": None}, {"id": "a/p/buraco-2022", "buraco": "sem_snapshot"}]
    # 2019: meta com os dois status "ok"; 2020: meta com "sem_formulario" em 1366x768; 2021: pasta sem meta.json
    ...
    self.assertEqual([e["id"] for e in templates.entradas_pendentes(plano, raiz)], ["a/p/2020-01-03", "a/p/2021-01-02"])
```

- [ ] **Passo 2:** teste → FALHA. **Passo 3:** implementar `entradas_pendentes`. **Passo 4:** teste → OK.
- [ ] **Passo 5: implementar `planejar`** no script:
  - `consultar_cdx(url) -> list[tuple[str, int]] | None` consulta `https://web.archive.org/cdx/search/cdx` com `from=201806`, `to=202612`, `fl=timestamp,statuscode`, `filter=statuscode:[23]..`, `collapse=timestamp:8`, `output=json`, User-Agent genérico e timeout de 60 s;
  - qualquer exceção devolve `None`; pausa de 1,5 s entre consultas;
  - lê o plano antigo, se existir, aplica `mesclar_plano` e grava com `ensure_ascii=False, indent=1`.
- [ ] **Passo 6: implementar `capturar`** no script:
  - um Chromium headless; para cada entrada pendente e cada resolução, um contexto novo (`viewport`, `locale`);
  - `page.goto(url, wait_until="load", timeout=60000)`, sendo `url_wayback(..., "if_")` para o Wayback e `url_login` para o ao vivo;
  - em seguida, `wait_for_selector(SELETOR_CREDENCIAL, timeout=30000)` e `wait_for_load_state("networkidle", timeout=10000)`, este com timeout ignorado;
  - salvar `screenshot(full_page=False)` como `shot_<res>.png` e `remover_prefixo_wayback(page.content())` como `dom_<res>.html`;
  - baixar uma vez `url_wayback(..., "id_")` como `html_original.html` (bytes). Na captura ao vivo, o HTML original vem da resposta do `goto` (`response.body()`) da 1ª resolução;
  - **status:**
    - resposta ausente ou ≥ 400 → `erro_wayback` (Wayback) ou `bloqueado` (ao vivo);
    - timeout do seletor → `sem_formulario`;
    - senão → `ok`.
  - Pausa de 1,5 s entre carregamentos do Wayback.
  - Grava `meta.json` **por último**, porque é a presença dele que marca a entrada como concluída.
- [ ] **Passo 7: pré-requisito com o Lucas.** Pedir aprovação para baixar o Chromium e então rodar `python -m playwright install chromium`.
- [ ] **Passo 8: verificação manual.**
  - `planejar --marcas config/marcas.exemplo.json --plano data/plano_exemplo.json`. Esperado: até 8 entradas Wayback por variante, sem buracos em 2019–2024, e 1 entrada ao vivo por variante.
  - `capturar --plano data/plano_exemplo.json --raiz data/templates_exemplo`. Esperado: status `ok` na maioria das entradas, e o PNG de 2020 de `login.live.com` mostra o formulário sem a barra do Wayback.
  - Rodar `capturar` de novo e conferir que não há nada pendente.
- [ ] **Passo 9: commit.** `scripts/capturar_templates.py`, `src/mhf/templates.py` e `tests/test_templates.py`, mensagem "Planejamento e captura dos templates (Wayback + ao vivo)".

---

### Tarefa 5: revisão, aprovação e documentação

**Arquivos:**
- Modificar: `src/mhf/templates.py`, `tests/test_templates.py`, `scripts/capturar_templates.py` e `README.md`.

**Interfaces:**
- Produz:
  - `gerar_revisao_html(plano: list[dict], metas: dict[str, dict]) -> str`, em que `metas` é indexado por id;
  - `marcar_aprovacao(plano: list[dict], id_: str, aprovado: bool, motivo: str = "") -> None`, que lança `KeyError` para id desconhecido;
  - **CLI:**
    - `revisar --plano <json> --raiz <pasta>`, que grava `<raiz>/revisao.html`;
    - `aprovar --plano <json> ID [ID ...]`;
    - `rejeitar --plano <json> ID --motivo TEXTO`.

A grade tem uma linha por entidade/variante e colunas 2019…2026 mais "ao vivo". Cada célula mostra:
- a miniatura `src="<id>/shot_1280x960.png"` (caminho relativo, largura 220 px);
- o id, o status das duas resoluções, `aprovado` e o link para `url_snapshot`.

Buracos aparecem como célula com o motivo.

- [ ] **Passo 1: testes que falham**

```python
def test_revisao_html(self):
    plano = [{"id": "paypal/padrao/2019-07-01", "entidade": "PayPal", "variante": "padrao", "anos_alvo": [2019],
              "origem": "wayback", "buraco": None, "aprovado": None},
             {"id": "paypal/padrao/buraco-2021", "entidade": "PayPal", "variante": "padrao", "anos_alvo": [2021],
              "origem": "wayback", "buraco": "sem_snapshot", "aprovado": None}]
    metas = {"paypal/padrao/2019-07-01": {"url_snapshot": "https://web.archive.org/web/20190701000000if_/https://www.paypal.com/signin",
                                          "resolucoes": {"1280x960": {"status": "ok"}, "1366x768": {"status": "ok"}}}}
    html = templates.gerar_revisao_html(plano, metas)
    for trecho in ("paypal/padrao/2019-07-01/shot_1280x960.png", "sem_snapshot", ">2026<", "ao vivo"):
        self.assertIn(trecho, html)

def test_marcar_aprovacao(self):
    plano = [{"id": "a/p/2019-07-01", "aprovado": None, "motivo": ""}]
    templates.marcar_aprovacao(plano, "a/p/2019-07-01", False, "banner de cookies cobre o form")
    self.assertEqual((plano[0]["aprovado"], plano[0]["motivo"]), (False, "banner de cookies cobre o form"))
    with self.assertRaises(KeyError):
        templates.marcar_aprovacao(plano, "nao/existe/2019-01-01", True)
```

- [ ] **Passo 2:** testes → FALHA. **Passo 3:** implementar, escapando textos com `html.escape`. **Passo 4:** testes → OK.
- [ ] **Passo 5:** ligar os subcomandos `revisar`, `aprovar` e `rejeitar` no script. Rodar `revisar` sobre `data/templates_exemplo` e abrir o `revisao.html`: as miniaturas devem aparecer.
- [ ] **Passo 6:** no `README.md`, acrescentar a seção "Passo 2 — templates de login" com os quatro comandos, na ordem planejar → capturar → revisar → aprovar/rejeitar. Explicar que `config/templates_snapshots.json` é versionado e que `data/templates/` não é.
- [ ] **Passo 7:** suíte completa `python -m unittest discover -s tests` → OK.
- [ ] **Passo 8: commit.** Mensagem "Revisão e aprovação dos templates; documentação do passo 2".

---

## Fora deste plano

- **Rodada completa** sobre `config/marcas.json` com as 20 marcas: depende da **etapa 1** (tabela de marcas, com as variantes de login e as URLs alternativas para Microsoft 365, Chase e Apple).
- O `config/templates_snapshots.json` real, revisado e aprovado pelo Lucas, entra num commit próprio depois dessa rodada.
- pHash, embedding, *s* dos templates e índice FAISS: etapas 3 e 4.
