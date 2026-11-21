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

Dataset principal: **Phish360** (amostras únicas de phishing e legítimas, já separadas em `trainval/` e `test/`).
Coloque a pasta em `data/Phish360`. O script de inspeção também aceita o formato do Phishpedia.

## Passo 0 — inspeção do dataset

```bash
pip install -r requirements.txt
python scripts/inspecionar_dataset.py --raiz data/Phish360 --saida data/phish360.csv
```

## Passo 1 — impressão digital estrutural (s)

`src/mhf/estrutural.py`: normaliza o DOM e extrai o hash canônico, os caminhos de tags, os XPaths críticos e as contagens. A função `comparar` devolve as similaridades por componente.

```bash
python -m unittest discover -s tests
python scripts/extrair_estrutural.py --indice data/phish360.csv --raiz data/Phish360 --saida data/estrutural_phish360.jsonl
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
python scripts/capturar_templates.py aprovar  --plano config/templates_snapshots.json --raiz data/templates paypal/login/2020-01-01
python scripts/capturar_templates.py rejeitar --plano config/templates_snapshots.json --raiz data/templates microsoft/pessoal/2026-01-07 --motivo "Wayback sem o JavaScript"
```

Entradas aprovadas ou rejeitadas não são recapturadas. Para recapturar uma delas, limpe a decisão no plano (`"aprovado": null`). Uma variante pode definir o campo `"seletor"` na tabela de marcas quando o login dela não usar e-mail, usuário, senha, CPF ou agência.

**Resolução extra (1920x1080).** É o tamanho de tela de 74% dos phishings do Phishpedia, e cada amostra é comparada com templates do mesmo tamanho de tela (desenho em `docs/especificacoes/2026-11-21-componente-visual.md`). Ela é capturada depois, só para as entradas aprovadas, com metadados (`extra_1920x1080.json`) e aprovação próprios, sem mexer na captura e na aprovação principais:

```bash
python scripts/capturar_templates.py capturar-extra --resolucao 1920x1080 --plano config/templates_snapshots.json --raiz data/templates
python scripts/capturar_templates.py revisar  --resolucao 1920x1080 --plano config/templates_snapshots.json --raiz data/templates   # revisao_1920x1080.html
python scripts/capturar_templates.py aprovar  --resolucao 1920x1080 --plano config/templates_snapshots.json --raiz data/templates ID [ID ...]
python scripts/capturar_templates.py rejeitar --resolucao 1920x1080 --plano config/templates_snapshots.json --raiz data/templates ID --motivo "..."
```

Os comandos acima usam a tabela completa (`config/marcas.json`, 20 marcas e 30 variantes; o `planejar` leva cerca de 2 minutos). Para um teste rápido, use `config/marcas.exemplo.json`, que tem só PayPal e Microsoft.

## Passo 3 — impressão digital visual (h, e)

`src/mhf/visual.py` calcula a parte visual da impressão digital. Desenho completo e medições em `docs/especificacoes/2026-11-21-componente-visual.md`.

- **Classe de tela.** Cada captura recebe o tamanho de tela dos templates de largura mais próxima (1280x960, 1366x768 ou 1920x1080) e é comparada só com templates desse tamanho. A página muda de layout com a largura da tela, e redimensionar a imagem não desfaz isso.
- **Primeira dobra.** O topo da captura é recortado com a altura da tela da classe. Isso importa nas capturas de página inteira do Phishpedia benign.
  - Imagem mais larga que a classe (página que transbordou na horizontal): fica só a janela, com a largura e a altura da classe.
  - Áreas transparentes são compostas sobre branco, como o navegador mostra a página.
- **h:** pHash de 64 bits (256 como variação), comparado por `sim_hash` (1 − d_H/n).
- **e:** MobileNetV3 Small (principal) e Large (comparação), pré-treinadas na ImageNet.
  - Entrada: a dobra em 224x224.
  - Saída: o vetor do *global average pooling*, com norma 1; assim o cosseno vira um produto interno.

Os pesos são baixados uma vez, na primeira execução, de `download.pytorch.org`, para `data/torch` (fora do Git). Uma variável `TORCH_HOME` já definida tem prioridade.

```bash
python scripts/extrair_visual.py --plano config/templates_snapshots.json --raiz-templates data/templates --saida data/visual_templates
python scripts/extrair_visual.py --indice data/phish360.csv --raiz data/Phish360 --saida data/visual_phish360
# Phishpedia benign: capturado numa tela de 1366x768, em página inteira; a classe é fixada para o dataset todo
python scripts/extrair_visual.py --indice data/phishpedia_benign.csv --raiz data/benign_sample_30k --classe 1366x768 --saida data/visual_phishpedia_benign
```

Saídas:
- `<saida>.jsonl`: uma linha por captura, com id, classe, tamanho original, hashes, metadados e tempos;
- `<saida>_small.npy` e `<saida>_large.npy`: os embeddings, na ordem das linhas do JSONL;
- `<saida>.erros.tsv`: só se alguma captura não puder ser lida; a rodada segue sem ela.

Os templates entram como um item por par (template aprovado, tamanho de tela), via `templates.templates_aprovados`.

**Tempo por imagem**, uma de cada vez (como no uso real). Mediana em ms, CPU i7-4790 com 4 threads, sem outros programas abertos:

| Origem | Imagens | Abrir e recortar | pHash (64 + 256) | Small | Large |
|---|---|---|---|---|---|
| Templates | 572 | 11,8 | 7,3 | 18,7 | 30,3 |
| Phish360 | 10.748 | 6,8 | 6,8 | 16,2 | 25,4 |
| Phishpedia phishing | 29.496 | 15,3 | 10,6 | 19,0 | 27,7 |
| Phishpedia benign | 30.649 | 17,5 | 6,0 | 15,5 | 25,0 |

"Abrir e recortar" inclui a leitura do disco e a decodificação do PNG; no navegador, a captura já vem decodificada.
