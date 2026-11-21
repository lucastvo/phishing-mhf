# Tabela de marcas e domínios — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Objetivo:** `config/marcas.json` com as 20 entidades de 𝒯 (rótulos dos datasets, domínios legítimos e variantes de login) e `src/mhf/marcas.py` com o mapeamento rótulo → entidade e a checagem de domínio.

**Arquitetura:**
- A tabela é um JSON versionado, no formato que `templates.ler_marcas` já lê, mais os campos `nomes_phishpedia`, `nomes_phish360` e `dominios`.
- As funções puras ficam em `src/mhf/marcas.py`.
- O domínio registrável é obtido com `tldextract`, usando a cópia da Public Suffix List que vem no pacote, sem rede.

**Stack:** Python 3.13, `tldextract` (nova dependência), `unittest`.

**Spec:** `docs/especificacoes/2026-11-21-tabela-de-marcas.md`

## Restrições globais

- Nomes em português. Testes sem rede: `python -m unittest discover -s tests`.
- `tldextract` sempre com `suffix_list_urls=()`, para usar a lista embutida (reproduzível e offline).
- As 6 decisões do spec §2 são do Lucas: **não mudar** sem perguntar.
- **Avisar o Lucas antes de começar a Task 1** (ele troca o modelo/esforço para a implementação).
- Commits com a identidade do Lucas (configurada no git) e o trailer `Co-Authored-By: Claude …`. Nunca commitar `CLAUDE.md`, `data/` ou `*.csv`.
- Branch `marcas` (a partir de `templates`). O PR usa `templates` como base.

## Foco da revisão

1. **Domínio parecido, mas de outro dono:** `paypal.com.conta-segura.net`, `paypal-login.com`, `secure-paypal.com.br` → **não** legítimos. *(teste na Task 2)*
2. **Sufixos compostos e países:** `www.itau.com.br`, `amazon.co.jp`, `bbc.co.uk`, `signin.ebay.de` → domínio registrável certo. *(teste na Task 1)*
3. **URLs malformadas ou incomuns:** sem esquema, com porta, com usuário (`http://paypal.com@evil.net/`), IP, maiúsculas, ponto final no host → sem exceção, e com o host **real**: em `paypal.com@evil.net`, o host é `evil.net`. *(teste na Task 1)*
4. **Rótulos fora de 𝒯 parecidos com os de dentro:** `Caixa Geral de Depositos`, `CaixaBank`, `mic`, `AOL Inc.`, `Instagram` → `None`. *(teste na Task 2)*
5. **Tabela incoerente:** URL de login cujo domínio não está nos `dominios` da própria marca, ou rótulo repetido em duas marcas → falha no teste de consistência. *(Task 3)*

---

### Task 1: domínio registrável

**Arquivos:**
- Criar: `src/mhf/marcas.py` e `tests/test_marcas.py`.
- Modificar: `requirements.txt` (acrescentar `tldextract`).

**Interfaces:**
- Produz `dominio_registravel(url_ou_host: str) -> str`: em minúsculas, sem ponto final; IP é devolvido como está; host vazio devolve `""`.

- [ ] **Passo 1: instalar a dependência** (aprovada pelo Lucas em 21/11/2026): `python -m pip install tldextract`. Acrescentar `tldextract` ao `requirements.txt`.
- [ ] **Passo 2: testes que falham**

```python
def test_dominio_registravel(self):
    casos = {
        "https://www.itau.com.br/": "itau.com.br",
        "https://secure07c.chase.com/web/auth/dashboard": "chase.com",
        "https://www.amazon.co.jp/ap/signin": "amazon.co.jp",
        "http://bbc.co.uk": "bbc.co.uk",
        "signin.ebay.de": "ebay.de",                       # sem esquema
        "https://WWW.PayPal.COM:443/signin": "paypal.com",  # maiúsculas e porta
        "https://paypal.com./signin": "paypal.com",         # ponto final
        "http://paypal.com@evil.net/login": "evil.net",     # usuário antes do @: o host real é evil.net
        "http://192.168.0.10/login": "192.168.0.10",
        "": "",
    }
```

- [ ] **Passo 3:** rodar → FALHA (módulo inexistente).
- [ ] **Passo 4:** implementar. Usar `urllib.parse.urlsplit`, acrescentando `//` quando faltar esquema, para obter `hostname`, que já trata usuário, porta e maiúsculas. Depois, um `tldextract.TLDExtract(suffix_list_urls=())` de módulo, com `registered_domain` (ou `domain + "." + suffix`). IP: `ipaddress.ip_address`.
- [ ] **Passo 5:** testes → OK. **Passo 6: commit** "Domínio registrável com a Public Suffix List (tldextract)".

---

### Task 2: leitura da tabela, rótulo → entidade e checagem de domínio

**Arquivos:**
- Modificar: `src/mhf/marcas.py`, `tests/test_marcas.py`.
- Criar: `tests/dados/marcas_teste.json`, uma tabela pequena (PayPal, Microsoft e Caixa) para os testes não dependerem da tabela real.

**Interfaces:**
- `ler_tabela(caminho: str) -> list[dict]`
- `entidade_do_rotulo(tabela, dataset: str, rotulo: str) -> str | None`:
  - `dataset` ∈ {`"phishpedia"`, `"phish360"`}; outro valor lança `ValueError`;
  - Phishpedia: comparação exata; Phish360: sem diferenciar maiúsculas.
- `dominio_legitimo(tabela, entidade: str, url: str) -> bool`: entidade desconhecida lança `KeyError`.

- [ ] **Passo 1: testes que falham**

```python
def test_entidade_do_rotulo(self):
    t = marcas.ler_tabela(TABELA_TESTE)
    self.assertEqual(marcas.entidade_do_rotulo(t, "phishpedia", "Hotmail"), "Microsoft")
    self.assertEqual(marcas.entidade_do_rotulo(t, "phish360", "OFFICE"), "Microsoft")
    for fora in ("Caixa Geral de Depositos", "CaixaBank", "AOL Inc.", "Instagram"):
        self.assertIsNone(marcas.entidade_do_rotulo(t, "phishpedia", fora))
    self.assertIsNone(marcas.entidade_do_rotulo(t, "phish360", "mic"))   # Made-in-China, não Microsoft
    with self.assertRaises(ValueError):
        marcas.entidade_do_rotulo(t, "visualphish", "paypal")

def test_dominio_legitimo(self):
    t = marcas.ler_tabela(TABELA_TESTE)
    self.assertTrue(marcas.dominio_legitimo(t, "PayPal", "https://www.paypal.com/signin"))
    self.assertTrue(marcas.dominio_legitimo(t, "Microsoft", "https://login.microsoftonline.com/common/oauth2/authorize"))
    for falso in ("https://paypal.com.conta-segura.net/", "https://paypal-login.com/",
                  "https://secure-paypal.com.br/", "http://paypal.com@evil.net/"):
        self.assertFalse(marcas.dominio_legitimo(t, "PayPal", falso))
    with self.assertRaises(KeyError):
        marcas.dominio_legitimo(t, "Nubank", "https://nubank.com.br/")
```

- [ ] **Passo 2:** FALHA. **Passo 3:** implementar. **Passo 4:** OK. **Passo 5: commit** "Mapeamento rótulo → entidade e checagem de domínio legítimo".

---

### Task 3: a tabela real das 20 marcas e o teste de consistência

**Arquivos:**
- Criar: `config/marcas.json`.
- Modificar: `tests/test_marcas.py`.

**Interfaces:**
- Consome `ler_tabela`, `dominio_registravel` e `templates.ler_marcas`/`templates.id_entrada`.

- [ ] **Passo 1: teste de consistência que falha** (`test_tabela_real_consistente`, lendo `config/marcas.json`):
  - exatamente 20 entidades;
  - cada uma com pelo menos 1 login e pelo menos 1 domínio;
  - `dominio_registravel(login.url)` ∈ `dominios` da própria entidade;
  - nenhum rótulo (por dataset) aparece em duas entidades;
  - os ids `templates.id_entrada(entidade, variante, "x")` são únicos;
  - `templates.ler_marcas("config/marcas.json")` lê sem erro.
- [ ] **Passo 2:** FALHA (arquivo inexistente).
- [ ] **Passo 3: pesquisar as URLs abertas no Wayback** (API CDX, URL exata, como o `planejar`): a alternativa para a Caixa, a URL do Itaucard e a página inicial do Facebook (refazer a consulta). Registrar a cobertura encontrada para o PR.
- [ ] **Passo 4: escrever `config/marcas.json`**, conforme o spec §2. Inclui:
  - os rótulos levantados em 21/11/2026 (CLAUDE.md §9);
  - os domínios oficiais de cada marca, com os países das variantes estrangeiras;
  - as variantes da tabela aprovada, com o locale: `ja-JP` na Amazon Japão, `de-DE` no eBay Alemanha, `pl-PL` no Santander Polônia, `pt-BR` nos bancos brasileiros e `en-US` nas demais.
  - A Apple entra com o login ao vivo. Ela também aparece no `planejar`, onde os buracos são esperados.
- [ ] **Passo 5:** suíte completa → OK.
- [ ] **Passo 6: verificação nos dados reais** (sem gravar no repositório): quantas amostras de phishing de cada dataset caem em cada entidade e quantas ficam fora de 𝒯. Esperado:
  - os totais por entidade batem com o levantamento (ex.: Microsoft 8.298 com HTML útil, somando os dois datasets);
  - `mic` e AOL ficam fora.
- [ ] **Passo 7: `planejar`** com a tabela real para `data/plano_marcas.json` (fora do git): lista os buracos por marca e ano, para o PR. A rodada completa de captura **não** faz parte desta etapa.
- [ ] **Passo 8: commit** "Tabela das 20 marcas de 𝒯 com domínios e variantes de login".

---

### Task 4: documentação

- [ ] README: seção "Passo 1b — tabela de marcas", explicando `config/marcas.json` e como mapear rótulos e checar domínios.
- [ ] Mudar os comandos do passo 2 no README para usar `config/marcas.json`, em vez do arquivo de exemplo.
- [ ] Suíte completa → OK. **Commit** "Documentação da tabela de marcas".

## Fora deste plano

- A rodada completa de captura das 20 marcas e a aprovação dos templates, que o Lucas faz na grade de revisão.
- O uso de `dominio_registravel` no componente estrutural (PR #1).
