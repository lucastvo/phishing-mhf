# Avaliação no conjunto de teste — desenho da etapa 6

Data: 22/11/2026. O Lucas aprovou o escopo proposto na conversa (obrigatórios, experimentos prometidos e extras) e delegou as escolhas de implementação ("faça o que achar necessário"). Decisões dele marcadas como **[decidido]**.

## 1. Intenção

Medir o detector da etapa 5 no conjunto de teste, que até aqui não foi lido, e produzir os números e as figuras do Cap. 5:
- as métricas da Seção 2.11 (detecção, identificação do alvo, ablação, latência);
- os experimentos prometidos nas decisões anteriores: defasagem temporal da base e "com e sem estágio 1";
- intervalos de confiança e o teste de "marca nova sem retreinar".

O teste é usado **uma vez**: todos os experimentos rodam juntos, com modelos e limiares escolhidos só no desenvolvimento, e cada execução fica registrada em arquivo.

## 2. O que entra

- Divisão (`data/divisao.csv`), tabelas de similaridades, base de templates e domínios (etapas 4 e 5).
- **Detector principal [decidido]:** gradient boosting, estágio único, características h+e+s (pHash de 64 bits, embedding Small), τ calibrado no desenvolvimento para 1% de falso positivo (`data/modelos/boosting`).
- Para a latência: as páginas brutas do teste (captura, HTML e URL) nos índices dos datasets.

## 3. Métricas e grupos

Phishing de 𝒯 é a classe positiva da detecção restrita a 𝒯; páginas legítimas, a negativa. Métricas da Seção 2.11, por amostra e por estrutura (peso 1/tamanho do grupo de DOM):
- acurácia, precisão, revocação, F1, especificidade e taxa de falso positivo;
- **top-1 da marca** entre os phishings de 𝒯 detectados;
- **AUC** do escore.

**Falso positivo em três grupos [decidido]:**
1. todas as legítimas do teste, e também separadas por dataset;
2. **páginas das próprias marcas de 𝒯**: legítimas cujo domínio é legítimo para alguma marca; elas testam a checagem de domínio;
3. **legítimas mais parecidas com a base**: o décimo das legítimas do teste com maior cosseno máximo com os templates. É uma aproximação objetiva de "páginas parecidas" (outros bancos, logins genéricos), porque os datasets não trazem o setor da página.

**Recortes:**
- por marca: revocação e top-1, com o número de amostras e de estruturas;
- por dataset;
- por tipo de página: com campo de senha, sem campo de senha, sem DOM útil.

**À parte:**
- phishing de marcas fora de 𝒯: fração sinalizada como phishing de alguma marca;
- phishing sem marca do test do Phish360: fração detectada. Esses phishings contam como positivos na detecção binária "completa" (todo phishing × legítimas), uma tabela secundária.

**Intervalos de confiança [decidido]:** bootstrap de 1.000 reamostras das estruturas (grupos de DOM) do teste, percentis 2,5 e 97,5, para as métricas da tabela principal e para a revocação por marca. Reamostrar estruturas, e não amostras, respeita a dependência entre cópias do mesmo kit.

## 4. Experimentos

Cada experimento é treinado e calibrado só no desenvolvimento (validação cruzada nas 5 dobras para τ e o modelo final com todo o desenvolvimento) e medido uma vez no teste. Todos usam o gradient boosting, salvo onde indicado.

| | Experimento | O que muda |
|---|---|---|
| E0 | Principal | o detector salvo (h+e+s) |
| E1 | Ablação | só h, só e, só s, h+e, h+s, e+s, h+e+s [decidido] |
| E1b | Modelos | regressão logística e Random Forest compacta salvos na etapa 5, h+e+s |
| E2 | Variações dos sinais | embedding Large no lugar do Small; pHash de 256 bits no lugar do de 64 |
| E3 | Estágio 1 | com o filtro pelo pHash (θ_h calibrado no desenvolvimento para 99% dos phishings de 𝒯) × sem ele; mostra a fração de legítimas liberadas no estágio 1 |
| E4a | Base de 2026 | só templates de 2026 (ao vivo e Wayback de 2026), com o classificador retreinado e recalibrado na mesma base |
| E4b | Base da época (só Phishpedia) | para cada phishing, só templates com data até a da amostra; para as legítimas do Phishpedia, templates até 31/10/2020 (fim da coleta); comparado com a base completa nas mesmas amostras |
| E5 | Marca nova | 4 grupos de 5 marcas (sorteio com semente 0); para cada grupo, o classificador é treinado sem os pares dessas marcas e medido nos phishings delas; comparado com o principal nas mesmas amostras |

**Data de um template:** o timestamp do Wayback; os capturados ao vivo valem como 21/11/2026, dia da captura. **Data de uma amostra do Phishpedia:** a do nome da pasta. O Phish360 não tem data por amostra e fica fora do E4b.

**Marca nova (E5):** o classificador não recebe o nome da marca como característica, só as similaridades com os templates dela. Se ele detecta marcas que nunca viu no treino, adicionar uma marca à base é só capturar os templates dela, sem retreinar. Isso sustenta o diferencial de base atualizável.

## 5. Latência

`scripts/medir_latencia.py`:
- **amostra:** 300 páginas brutas do teste, 100 de cada dataset, sorteadas com semente 0;
- **detector:** o principal, com `Detector.analisar_pagina`;
- **condições:** a MobileNetV3 é carregada antes e uma página de aquecimento fica fora da medição; uma página de cada vez, com o PC livre;
- **saída:** mediana e p95 de cada parte (abrir, pHash, busca, embedding, DOM, classificador) e do total.

A leitura do HTML do disco fica fora da medição: no navegador, o DOM já está na memória.

## 6. Saídas

Em `data/avaliacao/` (fora do Git):
- `resultados.json`: todos os números;
- `relatorio.md`: as tabelas em Markdown, para conferir;
- `tabelas/*.tex`: tabelas LaTeX (booktabs, vírgula decimal), prontas para o Cap. 5;
- `figuras/*.pdf`:
  - curva ROC do principal e da ablação;
  - revocação por marca, com os intervalos de confiança;
  - composição da latência;
- `registro.jsonl`: uma linha por execução, com data, configuração e o hash da divisão e dos modelos. Se a avaliação precisar rodar de novo (correção de defeito, por exemplo), isso fica visível.

## 7. Fora de escopo

- **"Qualquer template × mesmo tamanho de tela":** exigiria refazer as tabelas com comparações entre tamanhos de tela; a sanidade da etapa 3 já sustenta a escolha.
- **Ajustar qualquer coisa depois de ver o teste.** Se aparecer um defeito, a correção e a nova execução ficam registradas e explicadas.

## 8. Impacto na monografia

- Cap. 5 inteiro sai destas saídas.
- **Seção 2.11 e Cap. 1 (item "Avaliação"):** a divisão é por estrutura do DOM, não por entidade ou período; o motivo é que o `family_id` não agrupa os kits.
- **Cap. 1, hipótese:** sai o "hash perceptual como filtro rápido" (estágio único).

## 9. Correções antes da rodada (revisão independente)

A revisão foi feita antes de o teste ser lido, e as correções entraram antes da rodada única:
- **E4a:** a base de 2026 é a dos templates **planejados** para 2026 (`anos_alvo` do plano) mais os capturados ao vivo. O snapshot mais próximo de 1º de janeiro costuma ser de dezembro de 2025, e o filtro pelo ano do timestamp tirava a Amazon inteira da base.
- **E5:** as colunas das marcas excluídas ficam fora também da calibração de τ, como se elas não existissem, e a taxa de falso positivo no teste é reportada.
- **Latência:** a captura é recortada na primeira dobra antes da medição, como a captura da aba no navegador. Sem isso, as páginas inteiras do Phishpedia benign (até 85 mil px) mediriam o formato do dataset.
- **Registro e ensaio:**
  - `registro.jsonl` ganha uma linha no início e outra no fim de cada execução;
  - os resultados se acumulam entre execuções;
  - `--ensaio` roda tudo com a dobra 0 do desenvolvimento no papel do teste. Ele foi rodado com os dados reais antes da rodada única.

## 10. Resultados (22/11/2026, rodada única no teste)

Tabelas completas em `data/avaliacao/relatorio.md` e no README (passo 6). Pontos para o Cap. 5:
- **Principal:**
  - revocação de 0,553 por amostra (IC 0,104–0,854) e de 0,278 por estrutura (0,245–0,315);
  - falso positivo de 1,1%: o alvo de 1%, calibrado no desenvolvimento, se manteve no teste;
  - precisão de 0,98 por amostra, marca certa em 0,98 dos detectados e AUC de 0,943 por amostra e 0,827 por estrutura;
  - os intervalos por amostra são largos porque poucos kits copiados aos milhares dominam o teste. As métricas por estrutura são as que permitem conclusões.
- **Ablação:** a combinação h+e+s tem a maior AUC por estrutura (0,827). O DOM é o sinal isolado mais forte (0,720), e o embedding é o que dá a marca certa. Isso sustenta o diferencial "combinação visual + DOM" (Seção 3.6).
- **Limites:**
  - 8,5% de falso positivo nas legítimas mais parecidas com a base;
  - revocação de 0,116 em páginas sem campo de senha (etapas seguintes do golpe e iscas);
  - DHL, Adobe, Apple e Chase quase não são detectadas.
- **Temporal:**
  - a base só de 2026 perde um terço da revocação por estrutura (de 0,278 para 0,179). Isso sustenta a base com vários anos e a atualização periódica (Seção 3.6);
  - no Phishpedia, os templates anteriores ao ataque dão mais revocação (0,377) que a base completa (0,279).
- **Marca nova:** revocação de 0,560 nas marcas nunca vistas (o principal tem 0,553), com falso positivo de 1,2% a 2,4%.
- **Latência:** 81,6 ms por página (mediana; p95 de 145 ms) em CPU, uma ordem de grandeza abaixo dos 0,24–1,1 s citados no Cap. 3.
