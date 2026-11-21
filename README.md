# MHF — Multi-modal Hybrid Fingerprinting

Protótipo do TCC "Detecção de Phishing por Impressão Digital de Layout" (Lucas Terra Vieira de Oliveira).

A impressão digital de uma página *w* é φ(w) = (h, e, s):

- **h** — hash perceptual (pHash) do screenshot
- **e** — embedding visual (MobileNetV3)
- **s** — assinatura estrutural do DOM (hash canônico, XPaths de elementos críticos, contagem de elementos)

A verificação é em cascata: (1) busca rápida por *h* no FAISS; (2) só em caso de suspeita visual com domínio divergente, comparação por *e* e *s*.

## Estrutura

```
scripts/   scripts de linha de comando (inspeção, extração, avaliação)
src/mhf/   biblioteca do protótipo
data/      dataset e artefatos gerados (fora do Git)
```

## Dados

Dataset Phishpedia (phishing + benigno): https://sites.google.com/view/phishpedia-site/home
Descompacte em `data/phishpedia/phishing` e `data/phishpedia/benign`.

## Passo 0 — inspeção do dataset

```bash
pip install -r requirements.txt
python scripts/inspecionar_dataset.py --raiz data/phishpedia/phishing --rotulo phishing --saida data/phishing.csv
python scripts/inspecionar_dataset.py --raiz data/phishpedia/benign   --rotulo benigno  --saida data/benigno.csv
```

## Passo 1b — tabela de marcas protegidas

`config/marcas.json` lista as 20 marcas protegidas (o conjunto 𝒯 da monografia). Para cada uma, traz:
- os rótulos dela nos datasets (`nomes_phishpedia` e `nomes_phish360`);
- os domínios legítimos (`dominios`);
- as páginas de login que servem de referência (`logins`), escolhidas pelo que os kits de phishing de fato imitam.

Desenho e decisões em `docs/especificacoes/2026-11-21-tabela-de-marcas.md`.

```python
from mhf import marcas
t = marcas.ler_tabela("config/marcas.json")
marcas.entidade_do_rotulo(t, "phishpedia", "Office365")        # 'Microsoft'
marcas.entidade_do_rotulo(t, "phish360", "mic")                 # None (Made-in-China: fora do conjunto)
marcas.dominio_registravel("https://www.itau.com.br/")          # 'itau.com.br'
marcas.dominio_legitimo(t, "PayPal", "https://paypal.com.conta-segura.net/")  # False
```

O domínio registrável vem da Public Suffix List embutida no `tldextract`, sem acesso à rede, para o resultado ser reproduzível. Os testes (`tests/test_marcas.py`) também conferem a própria tabela: uma URL de login fora dos domínios da marca, ou um rótulo repetido em duas marcas, quebra a suíte.

## Passo 2 — templates de login com vários anos

As marcas redesenham o login ao longo do tempo. Por isso, a base guarda, para cada marca e variante de login, um template por ano: snapshots do Internet Archive (Wayback Machine) de 2019 a 2026, mais uma captura ao vivo. A busca escolhe a variante mais próxima. Desenho completo em `docs/especificacoes/2026-11-20-base-de-templates.md`.

```bash
python -m playwright install chromium --only-shell   # uma vez: navegador headless do Playwright

# 1. planejar: consulta o Wayback e grava a receita da base (versionada no Git)
python scripts/capturar_templates.py planejar --marcas config/marcas.json --plano config/templates_snapshots.json
# 2. capturar: screenshots (1280x960 e 1366x768), DOM e HTML original em data/templates/ (fora do Git);
#    pode ser interrompido e rodado de novo, porque só refaz o que falta
python scripts/capturar_templates.py capturar --plano config/templates_snapshots.json --raiz data/templates
# 3. revisar: gera data/templates/revisao.html com a grade de miniaturas
python scripts/capturar_templates.py revisar --plano config/templates_snapshots.json --raiz data/templates
# 4. aprovar/rejeitar: só templates aprovados entram na base; a aprovação vale para a captura que foi
#    vista (se a entrada for capturada de novo, a aprovação "vence" e precisa ser refeita)
python scripts/capturar_templates.py aprovar  --plano config/templates_snapshots.json --raiz data/templates paypal/padrao/2020-01-01
python scripts/capturar_templates.py rejeitar --plano config/templates_snapshots.json --raiz data/templates microsoft/pessoal/2026-01-07 --motivo "Wayback sem o JavaScript"
```

Entradas aprovadas ou rejeitadas não são recapturadas. Para recapturar uma delas, limpe a decisão no plano (`"aprovado": null`). Uma variante pode definir o campo `"seletor"` na tabela de marcas quando o login dela não usar e-mail, usuário, senha, CPF ou agência.

Os comandos acima usam a tabela completa (`config/marcas.json`, 20 marcas e 32 variantes; o `planejar` leva cerca de 2 minutos). Para um teste rápido, use `config/marcas.exemplo.json`, que tem só PayPal e Microsoft.
