# Componente visual (h, e) — desenho da etapa 3

Data: 21/11/2026. Decisões do Lucas marcadas como **[decidido]**; as demais são escolhas de implementação, que podem ser corrigidas na revisão.

## 1. Intenção e porquê

Implementar a parte visual da impressão digital φ(w) = (h, e, s) (monografia, Seção 2.6):
- **h**: hash perceptual (pHash) da captura de tela, comparado pela distância de Hamming;
- **e**: embedding de uma rede convolucional leve (MobileNetV3), comparado pelo cosseno.

Ambos são calculados sobre a captura normalizada (Seção 2.4.3). O h alimenta o estágio 1 da cascata (busca rápida na base de templates); h e e alimentam o estágio 2. Como o sistema roda no dispositivo (Seções 1.3 e 2.8), o custo por página é uma métrica obrigatória.

## 2. Objetivos, não objetivos e antiobjetivos

**Objetivos**
- Funções puras e testadas para normalizar a captura, calcular h e calcular e.
- Extração em lote de h e e para os três datasets e para os templates aprovados, medindo o tempo por página (como já é feito para s).
- Templates aprovados disponíveis nos três tamanhos de tela dos datasets.

**Não objetivos** (ficam para etapas seguintes)
- Índice FAISS e busca (etapa 4).
- Regra de decisão e limiares (etapa 5).
- Métricas de detecção e ablação (etapa 6). Esta etapa só produz os vetores e os tempos.
- Treinar ou ajustar a rede: os pesos são os pré-treinados na ImageNet.

**Antiobjetivos**
- Normalização que faça cópias fiéis de uma página parecerem diferentes só porque as capturas usaram telas de tamanhos diferentes (ver seção 4).
- Qualquer escolha que dependa de olhar o conjunto de teste.

## 3. Dados que entram

| Origem | Tamanho de tela das capturas |
|---|---|
| Phish360 | 1280×960 (10.653 de 10.748; poucos em 1920, 1366 ou ~990 de largura) |
| Phishpedia phishing | **1920×1080 (21.584 de 29.041)**, 1366×768 (7.052), 800×600 (427), outras perto de 1366 |
| Phishpedia benign | 1366 de largura, **página inteira** (altura de 768 até 85.624 px) |
| Templates aprovados (191) | 1280×960 e 1366×768 |

## 4. Tamanho de tela: comparar no mesmo tamanho [decidido]

**Medição (21/11/2026).** pHash de 64 bits do mesmo template capturado em 1280×960 e em 1366×768, contra templates de marcas diferentes:

| Comparação | Distância de Hamming mediana (0–64) |
|---|---|
| Mesmo template, só mudando a tela: login/conta | 18 |
| Mesmo template, só mudando a tela: página inicial | 24 |
| Mesmo template, só mudando a tela: rastreamento | 16 |
| Mesma marca, outra variante ou ano | 28 |
| Marcas diferentes | 32 |

O redimensionamento muda a escala, mas não desfaz a mudança de layout. Com a tela maior, conteúdo de largura fixa ocupa uma fração menor da imagem; menus, colunas e banners se reorganizam; e a proporção muda (4:3 × 16:9). A distância de 18 já é medida depois do redimensionamento interno do pHash (32×32): é o ruído que a normalização por resolução fixa não remove.

**Abordagens consideradas**
1. **Templates em cada tamanho de tela dos dados; cada amostra é comparada com os templates do mesmo tamanho.** Escolhida. Custo: recapturar os templates aprovados em 1920×1080 e revisar as miniaturas novas. No uso real, o navegador conhece o tamanho da janela, e usa-se o tamanho de template mais próximo.
2. **Uma resolução fixa única para tudo**, como descrito na Seção 2.4.3. Mais simples, mas aceita o ruído medido acima. Para pegar uma cópia capturada em outra tela, o limiar do estágio 1 teria de ser frouxo o bastante para deixar passar marcas diferentes (que ficam a 26–32 bits).
3. **Recortar o conteúdo principal antes de comparar.** Descartada: frágil e com muitos parâmetros sem justificativa.

A abordagem 1 contém a 2: as imagens são redimensionadas para uma resolução fixa nas duas; muda só com quais templates cada amostra é comparada. A avaliação pode medir as duas ("qualquer template" × "mesmo tamanho de tela").

**Limitação:** no uso real há muitos tamanhos de janela (1536, 1440, celular...), e o tamanho mais próximo nunca é exato.

## 5. Desenho

### 5.1 Classe de tela
Cada captura recebe uma das três classes, **1280×960, 1366×768 ou 1920×1080**, pela largura mais próxima. As capturas de 800×600 (4:3) vão para 1280×960. São as únicas sem template do mesmo tamanho exato, o que é registrado. A classe é gravada junto com h e e.

**Classe fixa quando o tamanho de tela é conhecido (decidido com o Lucas, 21/11/2026).** O Phishpedia benign foi capturado numa tela de 1366×768, em página inteira.
- 1.369 páginas transbordam na horizontal: a imagem fica mais larga que a tela, até 35.347 px, e todas têm pelo menos 768 px de altura.
- Pela largura, 446 delas cairiam na classe 1920×1080 e seriam comparadas com templates do tamanho errado.
- Por isso, a extração recebe a classe do dataset (`--classe 1366x768`).
- Nos outros datasets, a classe vem da largura de cada imagem.

### 5.2 Normalização da imagem
1. Abrir com `ImageFile.LOAD_TRUNCATED_IMAGES = True` e `Image.MAX_IMAGE_PIXELS = None` (armadilhas conhecidas dos datasets) e converter para RGB. **Áreas transparentes são compostas sobre branco**, que é como o navegador mostra a página. As capturas do Phishpedia são PNG RGBA, e parte delas tem regiões com alfa 0 e RGB 0 (cerca de 5% no phishing e 13% no benign, numa amostra de 200 de cada). Descartar o alfa deixaria essas regiões pretas. Os templates (Playwright) e o Phish360 são opacos.
2. **Recortar a primeira dobra** a partir do canto superior esquerdo. Isso afeta sobretudo o Phishpedia benign (página inteira).
   - **Imagem com largura até a da classe:** a faixa de cima, com a largura da imagem e a altura proporcional à classe. Ex.: uma captura de 1366 de largura fica com 768 px de altura.
   - **Imagem mais larga que a classe:** a janela, com a largura e a altura da classe (decidido com o Lucas, 21/11/2026). É o caso do transbordo horizontal numa captura de página inteira, em que a tela só mostrava o canto superior esquerdo da página. É também o que a extensão do navegador recebe ao capturar a aba visível. Antes, a dobra mantinha a largura toda: uma página de 7.253 px de largura virava um recorte de 7.253 × 4.078 px espremido em 224×224.
3. Capturas menores que a dobra (ex.: altura menor que a da classe) são usadas como estão, sem preencher, e contadas. A extração também conta as capturas mais estreitas e as mais largas que a classe.

### 5.3 h — hash perceptual
- `imagehash.phash` sobre a dobra recortada: tons de cinza, 32×32, DCT, 8×8 coeficientes de baixa frequência → **64 bits**.
- Variação para o experimento: 256 bits (`hash_size=16`). É barato e responde à nota `\lucas{tamanho do hash}` da Seção 2.6.
- Gravado em hexadecimal.

### 5.4 e — embedding [decidido: Small e Large]
- **MobileNetV3 Small** (principal) e **MobileNetV3 Large** (comparação), torchvision, pesos pré-treinados na ImageNet:
  - Small: `IMAGENET1K_V1`, 2,5 M parâmetros, 9,8 MB;
  - Large: `IMAGENET1K_V2`, 5,5 M parâmetros, 21,1 MB.
- Os pesos são baixados uma vez de `download.pytorch.org` (fonte oficial; o torchvision confere o hash do arquivo). Ficam em `data/torch/hub/checkpoints/`, fora do git: a extração define `TORCH_HOME=data/torch`. Download feito com o ok do Lucas em 21/11/2026.
- Tempo medido com os pesos reais, uma imagem de cada vez, CPU i7-4790 com 4 threads: **Small 29,6 ms; Large 57,3 ms** por embedding.
  Essa primeira medição foi feita com a captura de templates rodando ao mesmo tempo. Na extração completa, com a máquina livre, as medianas ficaram em **15–19 ms (Small) e 25–30 ms (Large)** (tabela no README, passo 3).
- Entrada: a dobra recortada, redimensionada para **224×224** e normalizada com a média e o desvio da ImageNet (as transformações dos próprios pesos). A distorção de proporção é a mesma para amostra e template da mesma classe de tela (seção 4).
- Saída: o vetor depois do *global average pooling*, antes do classificador (**576 dimensões na Small, 960 na Large**), normalizado em L2. Assim o cosseno vira um produto interno, que é o que o `IndexFlatIP` da etapa 4 usa.
- CPU, `torch.inference_mode()`, modelo em `eval()`. O modelo é carregado uma vez e reaproveitado.

### 5.5 Latência
A extração mede, por página e separadamente:
- leitura do disco;
- abertura e normalização (decodificar, compor a transparência e recortar a dobra);
- h de 64 bits e h de 256 bits;
- e (Small);
- e (Large).

A leitura do disco é medida à parte (no navegador, a captura já está na memória), e o h de 64 e o de 256 bits têm cada um o seu tempo. As imagens são processadas uma de cada vez, como no uso real, em que cada página chega sozinha. Por isso não há medição em lote: o lote só mudaria o tempo total da extração, que é relatado à parte. Os números vão para o Cap. 4/5.

### 5.6 Templates em 1920×1080
- `RESOLUCOES` ganha `1920x1080`.
- **Recaptura só dos templates aprovados, só na resolução nova**, sem tocar nos arquivos das outras duas resoluções.
- As miniaturas novas passam pela mesma revisão manual. Uma resolução que falhar (ex.: layout quebrado no Wayback) fica de fora só nessa classe de tela, sem invalidar a aprovação das outras.
- A forma exata de registrar a aprovação por resolução fica para o plano, respeitando a regra atual: a aprovação vale para a captura que foi vista.

### 5.7 Saídas
- `src/mhf/visual.py`: classe de tela, normalização, `phash`, `Embedder` (Small/Large) e `comparar(v1, v2)`, que recebe `{"h", "e"}` e devolve a similaridade de h (`sim_h` = 1 − d_H/n) e o cosseno de e (`cos_e`), separados.
- `scripts/extrair_visual.py`: como o `extrair_estrutural.py`. Lê o índice CSV de um dataset (ou o plano de templates), grava h e a classe em JSONL e os embeddings em `.npy` (fora do git), um por modelo, com os ids na mesma ordem. Erros por amostra não interrompem a rodada (`<saida>.erros.tsv`).
- `tests/test_visual.py`: sem rede e sem baixar pesos (rede com pesos aleatórios para testar formato, normalização L2 e determinismo).

## 6. Entrega em dois PRs

1. **Templates em 1920×1080:** mudança pequena em `templates.py` e no script, recaptura e revisão das miniaturas.
2. **Componente visual:** `visual.py`, extração em lote e tempos. A descrição do PR traz a justificativa da seção 4 (pedido do Lucas).

## 7. Impacto na monografia

- **Seção 2.4.3 (normalização, nota `\lucas{resolução da captura}`):** a normalização deixa de ser "uma resolução fixa" e passa a ser "classe de tela + redimensionamento fixo, comparando no mesmo tamanho de tela".
- **Seção 2.6.2 (nota sobre o tamanho do hash):** 64 bits, com 256 como variação.
- **Seção 2.6.2 (comparação de e):** cosseno, com o vetor de norma 1. O texto hoje diz "distância euclidiana ou cosseno"; com norma 1 as duas ordenam os vizinhos da mesma forma.
- **Seção 2.6.1 e Cap. 1, item 3 do Método (rede de embeddings):** MobileNetV3 Small como principal e Large como comparação, pré-treinadas na ImageNet, sem ajuste fino.
- **Cap. 1, item 2 do Método:** ainda cita VisualPhish e IEEE (já apontado antes).

## 8. Dependências

- Já instalados: Pillow, imagehash, torch e torchvision (CPU).
- Pesos pré-treinados baixados em `data/torch` (seção 5.4).
