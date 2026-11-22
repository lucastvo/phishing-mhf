# MHF — Multi-modal Hybrid Fingerprinting

Protótipo do TCC "Detecção de Phishing por Impressão Digital de Layout" (Lucas Terra Vieira de Oliveira).

A impressão digital de uma página *w* é φ(w) = (h, e, s):

- **h** — hash perceptual (pHash) do screenshot
- **e** — embedding visual (MobileNetV3)
- **s** — assinatura estrutural do DOM (hash canônico, XPaths de elementos críticos, contagem de elementos)

A verificação é em cascata: (1) busca rápida por *h* na base local de templates; (2) só em caso de suspeita visual com domínio divergente, comparação por *e* e *s*.

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

| Origem | Imagens | Ler | Abrir | pHash 64 | pHash 256 | Small | Large |
|---|---|---|---|---|---|---|---|
| Templates | 572 | 1,1 | 10,7 | 3,5 | 4,0 | 20,2 | 31,1 |
| Phish360 | 10.748 | 2,5 | 5,1 | 3,3 | 3,6 | 16,7 | 27,0 |
| Phishpedia phishing | 29.496 | 1,7 | 17,4 | 5,1 | 5,5 | 19,1 | 28,2 |
| Phishpedia benign | 30.649 | 1,8 | 18,9 | 2,9 | 3,1 | 15,5 | 24,8 |

- **Ler**: leitura do arquivo do disco.
- **Abrir**: decodificação do PNG, composição da transparência (só quando há) e recorte da primeira dobra. No navegador, a captura já vem decodificada e opaca; as capturas de página inteira do Phishpedia benign (até 85 mil px de altura) explicam o p95 de 127 ms.
- O estágio 1 da cascata usa só o pHash de 64 bits; os embeddings entram no estágio 2.

Rodada sem erros nos quatro conjuntos. Contagens do resumo: 27 + 14 capturas mais baixas que a dobra (Phish360, Phishpedia phishing), usadas como estão; 65 + 459 mais estreitas que a classe (as 800×600 do Phishpedia vão para 1280×960); 6 + 401 + 1.369 mais largas que a classe, recortadas na janela (Phish360, Phishpedia phishing, Phishpedia benign).

## Passo 4 — base de templates e busca

A base tem um item por par (template aprovado, tamanho de tela), com os três sinais da mesma captura: h e e (passo 3) e s, extraído do **DOM renderizado** nesse tamanho de tela (o HTML original de 68 dos 191 templates tem 5 elementos ou menos, porque a página é montada por JavaScript). Cada item traz também a entidade, a data e a origem do snapshot e os domínios legítimos da entidade (`config/marcas.json`).

A busca é **exaustiva**: cada página é comparada com todos os templates da sua classe de tela (190 ou 191). É exata, custa frações de milissegundo e é a mesma conta que uma extensão de navegador faria. O FAISS entra só na medição, para documentar que o resultado e o tempo são equivalentes.

```bash
# 4a. monta a base em data/base/ (base.jsonl, base_small.npy, base_large.npy, base_meta.json)
python scripts/construir_base.py --plano config/templates_snapshots.json --raiz-templates data/templates \
    --visual data/visual_templates --marcas config/marcas.json --saida data/base
# 4b. tabela de similaridades de cada amostra com os templates da sua classe (uma por dataset)
python scripts/similaridades.py --visual data/visual_phish360 --estrutural data/estrutural_phish360.jsonl \
    --dataset phish360 --saida data/similaridades_phish360
python scripts/similaridades.py --visual data/visual_phishpedia_phish --estrutural data/estrutural_phishpedia_phish.jsonl \
    --dataset phishpedia --saida data/similaridades_phishpedia_phish
python scripts/similaridades.py --visual data/visual_phishpedia_benign --estrutural data/estrutural_phishpedia_benign.jsonl \
    --dataset phishpedia --saida data/similaridades_phishpedia_benign
# 4c. mede a busca: exaustiva × FAISS
python scripts/medir_busca.py --base data/base \
    --consultas data/visual_phish360 data/visual_phishpedia_phish data/visual_phishpedia_benign \
    --estrutural data/estrutural_phish360.jsonl data/estrutural_phishpedia_phish.jsonl data/estrutural_phishpedia_benign.jsonl
```

- `construir_base.py` recusa montar uma base vazia e confere que todo template aprovado tem h e e na saída visual.
- `similaridades.py` confere que a base está em dia com a saída visual dos templates (mesmos ids e mesmo pHash) antes de calcular.
- Tabela: `<saida>.jsonl` (uma linha por amostra: id, classe, linha na matriz, rótulo, partição, marca, entidade de 𝒯, URL, elementos do s) e `<saida>.npz` (por classe de tela, matrizes amostras × templates de `dist_h64`, `dist_h256`, `cos_small`, `cos_large`, `hash_igual`, `jaccard_caminhos`, `jaccard_criticos` e `sim_contagens`, mais os índices na base das colunas). Amostra sem HTML útil fica com as colunas de s em NaN.

Base construída: 572 itens (191 em 1280×960, 191 em 1366×768, 190 em 1920×1080), todos com s. Tabelas: 10.748 + 29.496 + 30.649 amostras, de 36 a 72 s por dataset.

**Medição da busca** (`medir_busca.py`): 2.000 consultas sorteadas por classe de tela, uma de cada vez; mediana em µs (p95 entre parênteses); CPU i7-4790; FAISS 1.16.0, numpy 2.3.5. Na classe 1920×1080 (190 templates):

| Sinal | `Base.vizinhos` | Núcleo numpy | FAISS exato | Mesmo 1º vizinho (`Base.vizinhos` × FAISS) |
|---|---|---|---|---|
| pHash 64 bits | 112,0 (118,8) | 29,5 (31,8) | 28,0 (31,7) | 100% |
| Embedding Small | 48,3 (49,2) | 19,1 (19,4) | 27,2 (27,5) | 100% |
| Embedding Large | 53,4 (56,4) | 24,3 (25,3) | 36,2 (37,7) | 100% |

- As outras duas classes dão números iguais a menos de 4 µs, também com 100% de concordância.
- `Base.vizinhos` é a busca do código: além do núcleo, monta a consulta, ordena e, para o pHash, calcula também a distância de 256 bits.
- O s contra os templates da classe custa 2,4–2,6 ms (mediana; p95 até 3,5 ms), e a busca completa (h, e e s) 2,6 ms. Para comparar: o embedding Small da página custa 16–20 ms (passo 3).
- Com centenas de templates, um índice aproximado (IVF, HNSW) não mudaria a latência por página de forma perceptível.

## Passo 5 — cascata, treino e verificação

A cascata decide f(φ(w)) → {legítima} ∪ 𝒯:

1. **Estágio 1:** pHash de 64 bits contra os templates da classe de tela. Liberada se d₁ > θ_h (nenhum template parecido) ou se o domínio da página é legítimo da marca do template mais parecido.
2. **Estágio 2:** para cada marca, o melhor valor de cada sinal (h, e, s) sobre os templates dela vira um vetor de características; um classificador dá um escore por marca. Abaixo de τ, ou no domínio legítimo da marca de maior escore → legítima; senão, phishing dessa marca.

```bash
# 5a. divide em desenvolvimento e teste, por estrutura do DOM (o mesmo kit nunca fica dos dois lados)
python scripts/dividir.py \
    --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign \
    --estrutural data/estrutural_phish360.jsonl data/estrutural_phishpedia_phish.jsonl data/estrutural_phishpedia_benign.jsonl \
    --exclusoes config/exclusoes.json --saida data/divisao.csv
# 5b. treina, calibra e compara regressão logística × Random Forest (só no desenvolvimento)
python scripts/treinar.py \
    --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign \
    --divisao data/divisao.csv --base data/base --marcas config/marcas.json --saida data/modelos
# 5c. verifica com o detector salvo: amostras das tabelas...
python scripts/verificar.py --modelo data/modelos/regressao \
    --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign \
    --divisao data/divisao.csv --amostras 20
# ...ou uma página bruta (captura, HTML e URL)
python scripts/verificar.py --modelo data/modelos/regressao --imagem pagina.png --html pagina.html --url "http://exemplo.test/"
```

- **Divisão:** grupos pelo hash do DOM; grupo com amostra do test do Phish360 vai inteiro para o teste; grupos só do Phishpedia são divididos 70/30 (`StratifiedGroupKFold`, semente 0); 5 dobras de validação cruzada no desenvolvimento. As 5 amostras do CaixaBank rotuladas `caixa` no Phish360 ficam fora (`config/exclusoes.json`). Resultado: 51.214 amostras no desenvolvimento e 19.674 no teste. Os kits copiados aos milhares ficam inteiros de um lado: o teste da Microsoft tem 4.386 amostras e 15 estruturas, por isso as métricas saem também por estrutura (cada kit pesa 1).
- **Treino:** pares (amostra, marca), rótulo "é phishing desta marca", peso por estrutura reequilibrado entre positivos e negativos; o par de uma página no domínio legítimo da própria marca fica de fora. Amostra sem HTML útil ou com 5 elementos ou menos: s = 0 e `s_ausente` = 1.
- **Calibração (só no desenvolvimento, escores fora da dobra):** θ_h deixa passar ao estágio 2 pelo menos 99% dos phishings de 𝒯; τ é o menor limiar com falso positivo ≤ 1% nas páginas legítimas.
- **Saídas:** `data/divisao.csv`, `data/modelos/regressao/modelo.json` (pontuação em numpy puro, 3,4 KB), `data/modelos/floresta/` (`modelo.json` e `floresta.joblib`) e `data/modelos/comparacao_dev.{md,json}`.
- O `verificar.py` só lê o conjunto de teste com `--usar-teste`: ele é usado uma vez, na avaliação (etapa 6).

**Validação cruzada no desenvolvimento** (média entre as 5 dobras; τ no alvo de 1% de falso positivo; "estrutura" = cada kit conta uma vez):

| Métrica | Regressão logística (amostra / estrutura) | Random Forest (amostra / estrutura) |
|---|---|---|
| AUC do classificador | 0,817 / 0,712 | 0,831 / 0,793 |
| Revocação | 0,381 / 0,255 | 0,329 / 0,255 |
| Precisão | 0,952 / 0,778 | 0,944 / 0,777 |
| Falso positivo | 0,010 / 0,010 | 0,010 / 0,010 |
| Marca certa entre os phishings detectados | 0,641 / 0,656 | 0,953 / 0,942 |
| Pontuar uma página | 0,03 ms | 55 ms |
| Tamanho do modelo | 3,4 KB | 172 MB |

- **O estágio 1 quase não filtra:** θ_h = 24 bits e o estágio 1 libera só 0,8% das páginas legítimas (7,9% com θ_h de 95% ou 90%, ambos 22 bits). Com 190 templates por classe, quase toda página tem algum template a menos de 24 bits.
- **Sem DOM útil, a regressão logística não detecta nada** (AUC 0,41, revocação 0); o Random Forest chega a AUC 0,88 nessas páginas. O coeficiente do cosseno do embedding na regressão é +0,014: ela se apoia no DOM (Jaccard dos caminhos +1,07, contagens +0,64) e no pHash (+0,49).
- No τ que maximiza o F1, a revocação sobe para 0,64 (regressão) e 0,72 (floresta), com falso positivo de 12% e 23%.
- Relatório completo, por dataset e por presença do DOM: `data/modelos/comparacao_dev.md`.
