# Base de templates e busca — desenho da etapa 4

Data: 22/11/2026. Decisões do Lucas marcadas como **[decidido]**; as demais são escolhas de implementação, que podem ser corrigidas na revisão.

## 1. Intenção e porquê

A cascata (monografia, Seção 2.9) compara a impressão digital φ(w) = (h, e, s) da página visitada com a dos templates das marcas protegidas e olha o domínio do template mais parecido. Esta etapa monta essa **base de templates** e a **busca**: dada uma página, as similaridades de h, e e s com cada template do mesmo tamanho de tela.

Como o sistema roda no dispositivo (Seções 1.3 e 2.8), a base precisa ser pequena, autocontida (inclui os domínios legítimos) e num formato aberto, fácil de levar para a futura extensão de navegador.

## 2. Objetivos, não objetivos e antiobjetivos

**Objetivos**
- Base de templates no disco: um item por par (template aprovado, tamanho de tela), com h, e, s, a entidade, os metadados do snapshot e os domínios legítimos da entidade.
- Busca exaustiva e testada: similaridades de uma página com todos os templates da sua classe de tela.
- Tabela de similaridades de todas as amostras dos três datasets com os templates da sua classe, para a etapa 5 calibrar os limiares e a etapa 6 fazer a ablação sem recalcular nada.
- Medição da busca: latência da busca exaustiva × FAISS, e conferência de que os dois devolvem os mesmos vizinhos.

**Não objetivos** (ficam para etapas seguintes)
- Regra de decisão, limiares e checagem de domínio aplicada (etapa 5). A base só carrega os domínios.
- Métricas de detecção, splits e ablação (etapa 6).
- Decidir o que fazer com páginas de DOM degenerado (questão em aberto 12.2): a tabela grava o número de elementos de cada lado, e a etapa 5 decide.

**Antiobjetivos**
- Busca aproximada que possa perder o template mais parecido.
- Escolhas de desenho feitas olhando o conjunto de teste (ver seção 5.2).
- Base que dependa de biblioteca indisponível no navegador para ser lida ou consultada.

## 3. Dados que entram

- **Templates aprovados:** `templates.templates_aprovados(plano, raiz)` — 572 pares (191 em 1280×960, 191 em 1366×768, 190 em 1920×1080). A aprovação fica presa à captura vista (etapa 2).
- **h e e dos templates:** `data/visual_templates.jsonl` + `_small.npy` / `_large.npy` (etapa 3).
- **s dos templates:** ainda não extraído; vem do `dom_<tamanho>.html` de cada par (seção 5.2).
- **Domínios legítimos:** `config/marcas.json` (etapa 1).
- **Amostras:** `data/visual_<dataset>.{jsonl,npy}` (h, e, classe) e `data/estrutural_<dataset>.jsonl` (s), unidas pelo id.

## 4. Busca exaustiva, sem índice aproximado [decidido]

Medição com os templates reais (classe 1920×1080, 190 templates; 2.000 consultas do Phishpedia; mediana por consulta):

| Busca | Embedding Small (e) | pHash 64 bits (h) |
|---|---|---|
| Exaustiva (numpy) | 0,024 ms | 0,029 ms |
| FAISS exato (`IndexFlatIP` / `IndexBinaryFlat`) | 0,023 ms | 0,013 ms |

O embedding da página custa uns 20 ms (etapa 3), quase mil vezes a busca. Os embeddings Small dos 572 pares ocupam 1,3 MB; a base completa no disco, com o Large e os caminhos do DOM, ocupa cerca de 8 MB (o `base.jsonl` tem 4,5 MB, quase todo de caminhos, que se repetem muito e podem ser compactados para a extensão). Medição completa na base real, com as três classes e a busca do código (`Base.vizinhos`): README, passo 4. Com centenas de templates, índices aproximados (IVF, HNSW) não reduzem a latência por página de forma perceptível e podem perder o vizinho mais próximo.

**Decisão:** o código faz busca exaustiva em numpy. É exata, é a mesma conta que a extensão fará em JavaScript (onde o FAISS não roda) e não acrescenta dependência à base. O FAISS entra só no script de medição (seção 5.5), para documentar que o resultado e o tempo são equivalentes. Índices aproximados passam a ser o caminho para escalar a base, se ela crescer para dezenas de milhares de entradas.

## 5. Desenho

### 5.1 Item da base

Um item por par (template aprovado, tamanho de tela). Todos os sinais do item vêm da mesma captura, no mesmo tamanho de tela:
- `id` (`<entrada>@<tamanho>`, o mesmo de `visual_templates.jsonl`), `entidade`, `variante`, `origem` (`wayback` ou `ao_vivo`), `timestamp`, `classe`;
- `phash64`, `phash256`; a linha do item em `base_small.npy` e `base_large.npy`;
- s: `hash_canonico`, `caminhos`, `criticos`, `contagens` (como em `estrutural.py`);
- `dominios`: os domínios legítimos da entidade.

`origem` e `timestamp` permitem os experimentos já previstos sem refazer a base: "base completa × só 2026" e, no Phishpedia, "só templates anteriores à data da amostra".

### 5.2 Qual HTML do template vira s

Cada template tem duas versões da página: o `html_original.html` (como foi arquivado, antes do JavaScript) e o `dom_<tamanho>.html` (o DOM depois de renderizado). Medição com o vizinho mais próximo só por Jaccard dos caminhos, sem limiar, nos phishings de marcas de 𝒯:

| Versão do template | Phish360 trainval (2.204 com s) | Phishpedia phishing (20.951 com s) |
|---|---|---|
| HTML original | 14,3% | 14,1% |
| DOM renderizado | 14,6% | 37,4% |
| O melhor dos dois | 16,4% | 37,0% |

- No HTML original, 68 dos 191 templates têm 5 elementos ou menos: a página é montada por JavaScript. No DOM renderizado, nenhum.
- O Phishpedia parece guardar o DOM renderizado; no Phish360 as duas versões empatam.
- **Decisão:** s vem do `dom_<tamanho>.html` do mesmo par. A URL passada a `estrutural.extrair` (usada só em `forms_action_externa`) é a `url_login` do template, a URL legítima da página. Guardar as duas versões ganharia 1,8 ponto num dataset e perderia 0,4 no outro, com o dobro de dados.
- A medição usou só o trainval do Phish360 (a partição de teste oficial não foi tocada). No Phishpedia, ainda sem split, a comparação não tem parâmetro ajustável: escolhe entre duas versões fixas.

Referência, com o mesmo vizinho mais próximo sem limiar e só no mesmo tamanho de tela: h 13,3% / 42,6%, e Small 21,8% / 57,4%, e Large 22,6% / 55,2% (Phish360 trainval / Phishpedia). **O s sozinho identifica mal a marca**, o que é esperado: os kits copiam a aparência, não o código (Zieni et al., 2023, citados no Cap. 2). O papel dele na combinação é o que a ablação da etapa 6 vai medir.

### 5.3 Busca

`Base.similaridades(consulta, classe)` devolve, para cada template da classe, na ordem da base:
- `dist_h64` e `dist_h256` (Hamming) e `sim_h64` / `sim_h256` (1 − d/n);
- `cos_small` e `cos_large` (produto interno de vetores de norma 1);
- `hash_igual`, `jaccard_caminhos`, `jaccard_criticos`, `sim_contagens` (`estrutural.comparar`), quando a consulta tem s; senão, NaN;
- os índices dos itens, para recuperar entidade, domínios e metadados.

`Base.vizinhos(consulta, classe, sinal, k)` devolve os k templates mais próximos por um sinal (`h64`, `h256`, `small`, `large`, `caminhos`). A consulta é um dicionário com os campos que existirem (h, e por modelo, s); a função não recalcula nada da página.

### 5.4 Tabela de similaridades das amostras

`scripts/similaridades.py` roda a busca para todas as amostras de um dataset e grava, por dataset:
- `<saida>.npz`: matrizes N × T_classe por sinal, agrupadas por classe de tela (as amostras de uma classe só são comparadas com os templates dessa classe). Distâncias de Hamming em inteiros, similaridades em float16;
- `<saida>.jsonl`: uma linha por amostra (id, classe, rótulo, marca, entidade de 𝒯 ou nula, URL, elementos do s) na ordem das linhas das matrizes.

Antes de calcular, o script confere que o JSONL e os `.npy` de cada entrada visual têm o mesmo número de linhas e que os ids da base batem com os de `visual_templates.jsonl`.

Estimativa: ~70 mil amostras × ~191 templates × 8 sinais ≈ 190 MB por rodada completa, fora do Git; alguns minutos (o Jaccard dos caminhos domina).

### 5.5 Medição da busca

`scripts/medir_busca.py`, sobre a base real:
- latência por consulta (mediana e p95) da busca exaustiva e do FAISS exato, para h64 e para e Small/Large, por classe de tela;
- latência do s contra todos os templates da classe (o custo do estágio 2);
- conferência de que o vizinho mais próximo é o mesmo nos dois métodos.

Uma imagem de cada vez, com a máquina livre, como na etapa 3. A tabela vai para o README e para o Cap. 4.

### 5.6 Formato no disco

`data/base/` (fora do Git, reconstruível a partir do plano e das capturas):
- `base.jsonl`: um item por linha, sem os embeddings;
- `base_small.npy` e `base_large.npy`: float32, norma 1, na ordem do `base.jsonl`;
- `base_meta.json`: data de construção, número de itens por classe e por entidade, versões das bibliotecas.

JSON + `.npy` são formatos abertos; a conversão para o formato que a extensão usar fica para a Monografia 2.

## 6. Arquivos

- `src/mhf/base.py`: construção, leitura (com as conferências de alinhamento), `similaridades` e `vizinhos`.
- `scripts/construir_base.py`: extrai o s dos DOMs dos templates e grava `data/base/`.
- `scripts/similaridades.py`: seção 5.4.
- `scripts/medir_busca.py`: seção 5.5 (único uso do FAISS).
- Testes em `tests/test_base.py`, sem rede e sem os dados reais (base sintética pequena).
- README: passo 4.

## 7. Impacto na monografia

- **Cap. 1, Método, item "Indexação e busca":** hoje diz "organização das impressões digitais dos templates em um índice FAISS". Passa a ser uma base local com busca exaustiva, com o FAISS como comparação.
- **Seção 2.8:** hoje trata a estrutura de indexação como "fator determinante para a viabilidade". Com centenas de templates, a busca exaustiva é exata e custa frações de milissegundo; índices aproximados importam se a base crescer para dezenas de milhares de entradas. A tabela da seção 4 sustenta a mudança.
- **Seção 2.9 e README:** "busca de h na base (FAISS)" → busca exaustiva de h na base.
- **Seção 2.6 / Cap. 4:** o s dos templates vem do DOM renderizado (seção 5.2).
- **Cap. 5 (futuro):** o s sozinho identifica mal a marca (seção 5.2); vale como resultado da ablação, não como defeito.
- Os três diferenciais da Seção 3.6 não mudam; o terceiro (execução local) ganha uma medição direta.

## 8. Dependências

Nenhuma nova. `faiss-cpu` já está no `requirements.txt` e passa a ser usado só na medição.
