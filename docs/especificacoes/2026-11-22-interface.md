# Interface de demonstração — desenho da etapa 7

Data: 22/11/2026. Decisões do Lucas marcadas como **[decidido]**; o restante são escolhas deste desenho, feitas com a delegação dele ("pode fazer do jeito que achar melhor").

## 1. Intenção

Uma interface simples para **ver o MHF funcionando**, com dois usos **[decidido]**:
- **na defesa**, para mostrar à banca, de forma concreta, uma página entrando e o veredito saindo, com o porquê;
- **no uso prático**, como uma prévia simplificada do que a extensão do navegador da Monografia 2 fará: olhar a página aberta, comparar com a base de templates e alertar.

A interface não mede nada novo. Os números do trabalho continuam sendo os da etapa 6 (`data/avaliacao/`); a interface ilustra o mecanismo, inclusive quando ele erra.

## 2. Objetivos, não objetivos e o que a faria falhar

**Objetivos**
- Analisar uma página de duas formas **[decidido]**: (a) **exemplos prontos** do conjunto de teste; (b) **URL ao vivo**, aberta num navegador automatizado.
- Mostrar o veredito em linguagem simples e o que levou a ele: a captura analisada ao lado do template mais parecido, o escore de cada marca contra o limiar, os sinais da marca, a checagem de domínio e o tempo de cada parte.
- Demonstrar a checagem de domínio com a mesma página em dois domínios (o oficial e um simulado).
- Rodar com um comando, sem instalar pacotes novos e sem acesso à internet além da página aberta ao vivo.

**Não objetivos**
- Extensão do navegador, captura automática da aba, atualização da base, vários usuários ao mesmo tempo, empacotamento para outra máquina (Monografia 2).
- Retreinar, recalibrar ou reavaliar o detector.
- Envio de arquivos (captura + HTML) pela interface.

**O que faria a interface falhar, mesmo funcionando**
- Mostrar só acertos: a banca perguntaria "e quando erra?" e a demonstração pareceria escolhida a dedo. Os exemplos incluem erros, marcados como erros.
- Abrir sozinha páginas de phishing reais: os exemplos de phishing vêm sempre da captura + HTML guardados no dataset.
- Apresentar o tempo de abrir a página no navegador automatizado como latência do detector.
- Enviar dados da página para fora da máquina (fontes, bibliotecas ou estatísticas de terceiros).

## 3. Restrições

- **Detector:** o principal da etapa 5, sem mudança: gradient boosting, estágio único, h+e+s, τ calibrado para 1% de falso positivo (`data/modelos/boosting`), base de 572 templates (`data/base`), marcas de `config/marcas.json`. O veredito vem de `cascata.Detector.analisar_pagina`.
- **Pacotes:** só o que já está no `requirements.txt` e a biblioteca padrão do Python. Navegador automatizado: o Chromium do Playwright, já instalado na etapa 2.
- **Antivírus:** os HTMLs de phishing ficam onde estão (pastas dos datasets, que têm exclusão no Windows Defender). Nada de copiar HTML de phishing para `data/` ou para o repositório.
- **Conjunto de teste:** os exemplos saem do teste, que o detector nunca viu (nem no treino, nem na calibração). Escolher exemplos não gera métrica e não entra em `data/avaliacao/registro.jsonl`.
- **Repositório público:** a lista de exemplos versionada guarda só dataset, id e textos; nenhum caminho da máquina.

## 4. Abordagens consideradas

| Abordagem | Como seria | Prós | Contras |
|---|---|---|---|
| **A. Página web local servida pelo Python (escolhida)** | `scripts/interface.py` sobe um servidor em `127.0.0.1` (biblioteca padrão `http.server`); a tela é um HTML com CSS e JavaScript puros, aberta no navegador do sistema | nada a instalar; parece com o que a extensão vai mostrar (um painel no navegador); controle total do visual; roda sem internet | escrever o HTML/CSS/JS à mão |
| B. Streamlit ou Gradio | painel montado em Python | rápido de escrever | exige instalar pacote; visual de "painel de dados", menos parecido com a extensão; layout pouco controlável; o Gradio carrega recursos de terceiros por padrão |
| C. Aplicativo de janela (Tkinter) | janela nativa do Windows | sem servidor | não lembra um navegador; mostrar imagens grandes e gráficos dá mais trabalho |

Entrada **[decidido]**: exemplos prontos + URL ao vivo. O envio de arquivos ficou de fora: ajuda pouco na defesa e os exemplos já cobrem páginas do dataset.

## 5. Arquitetura

Um processo só, iniciado por `python scripts/interface.py`:
1. Carrega a base, a tabela de marcas, o detector e a MobileNetV3 Small (uma vez, cerca de 5 s) e analisa uma página de aquecimento.
2. Lê a lista de exemplos (seção 6) e confere que cada um existe no disco.
3. Sobe o servidor HTTP em `127.0.0.1` (porta padrão 8000, `--porta`) e abre o navegador do sistema (`--nao-abrir` para não abrir).
4. Atende uma requisição por vez (servidor sem threads). É uma demonstração de um usuário; assim o Playwright, que tem API síncrona presa a uma thread, roda na mesma thread do servidor, sem fila.
5. O Chromium do Playwright só é iniciado na primeira análise por URL e fica aberto até o servidor fechar (Ctrl+C fecha o navegador e o servidor).

Rotas:

| Rota | O que faz |
|---|---|
| `GET /` e `GET /estatico/...` | a página e seus arquivos (HTML, CSS, JS), servidos do repositório |
| `GET /api/estado` | modelo, τ, número de templates e marcas, classes de tela, lista de exemplos (número, título, grupo), URLs sugeridas, se o navegador automatizado está disponível |
| `POST /api/exemplo` `{"numero": n, "url_simulada"}` | analisa o exemplo n (com a URL original ou a simulada, seção 7.2) e devolve o resultado (seção 8.2) |
| `POST /api/url` `{"url", "classe", "idioma", "url_simulada"}` | abre a URL, captura, analisa e devolve o resultado |
| `GET /api/template?id=...` | a captura de um template da base; o id precisa ser um item da base (sem montar caminho a partir do texto recebido) |

Entradas inválidas (URL que não é http/https, classe fora das três, exemplo inexistente, id fora da base) recebem erro 400 com mensagem em português; falhas ao abrir a página (tempo esgotado, endereço inexistente) voltam como erro legível na tela, sem derrubar o servidor.

Toda a tela funciona sem internet: nada de CDN, fontes externas ou bibliotecas de terceiros no navegador.

## 6. Entrada 1: exemplos prontos

### 6.1 Composição

Doze exemplos do conjunto de teste, em dois grupos, cobrindo as três classes de tela (1280×960 do Phish360, 1920×1080 e 1366×768 do Phishpedia):

**Acertos (8)**
1. Clone do login corporativo da Microsoft detectado como phishing da Microsoft.
2. Clone do PayPal detectado como phishing do PayPal.
3. Clone de outra marca global com bom resultado (Netflix ou Amazon).
4. Banco brasileiro (Itaú, Santander, Bradesco ou Caixa) detectado, se algum do teste for detectado; senão, troca por outra marca.
5. Phishing do Phish360 (1280×960) detectado, para mostrar o outro dataset. Sai dos 29 phishings do Phish360 no teste com marca de 𝒯 (grupos do `trainval` que foram para o teste); se nenhum for detectado com a marca certa, troca por outro acerto do Phishpedia.
6. **Página da própria marca no domínio oficial**, de preferência uma com escore acima de τ liberada pela checagem de domínio (é a checagem em ação); se não houver, uma liberada por escore baixo.
7. Página legítima de outro site (fora de 𝒯) liberada por escore baixo.
8. Página legítima sem DOM útil liberada (o detector também decide só com o visual).

**Erros (4)**
9. Phishing não detectado: **isca temática** (OneDrive, Adobe ou DHL, que não copia uma página real).
10. Phishing não detectado: página **sem DOM útil**.
11. Phishing não detectado: **etapa seguinte do golpe** (formulário de cartão ou "conta limitada").
12. **Alerta falso**: página legítima parecida com a base sinalizada como phishing.

Se algum tipo não tiver candidato no teste, ele é trocado por outro do mesmo grupo e a troca fica anotada na lista.

**Rótulo real e "acertou" (escolha do desenho).** O rótulo real é sempre o do dataset, como na etapa 6; nenhum exemplo é reetiquetado à mão (a única intervenção manual nos rótulos continua sendo a exclusão do CaixaBank). Por isso:
- **acerto** = phishing de 𝒯 detectado **com a marca certa**, ou página legítima liberada. Só esses entram no grupo de acertos;
- **phishing de 𝒯 detectado com a marca errada** conta como erro ("detectou o phishing, mas errou a marca"), como na etapa 6, que mede detecção e marca separadamente. Pode ocupar uma vaga de erro, se for um caso instrutivo;
- **phishing sem marca no dataset** (quase todo o teste do Phish360: 1.272 de 1.301) e **phishing de marca fora de 𝒯** só entram como erro (não detectado), porque aí o veredito "legítima" é errado sem depender da marca. O exemplo 11 (etapa seguinte do golpe) pode sair deles. Se um desses for detectado, a tela não diz "acertou" nem "errou" a marca: diz "detectado como phishing; o dataset não informa a marca" (ou "a marca real está fora da base").

### 6.2 Como os exemplos são escolhidos

1. `scripts/escolher_exemplos.py` recebe os datasets no mesmo formato de `medir_latencia.py` (`--dataset NOME ÍNDICE RAIZ [CLASSE]`; o Phishpedia benign com `1366x768`), a divisão e o modelo.
2. Sorteia candidatos **só do teste**, por tipo: phishings de 𝒯 por marca, phishings sem DOM útil, phishings sem marca e de marcas fora de 𝒯 (só para o grupo de erros), páginas das marcas de 𝒯 (domínio legítimo de alguma marca), legítimas comuns e legítimas do décimo mais parecido com a base. Algumas centenas de páginas no total.
3. Analisa cada candidato com `Detector.analisar_pagina` (a mesma chamada da interface) e grava `data/interface/candidatos.json` (veredito, marca, motivo, escore, rótulo real) e uma folha de contato com as primeiras dobras.
4. A proposta dos 12 é montada a partir dos candidatos pelos critérios da seção 6.1 e **revisada pelo Lucas olhando as capturas**, como na revisão dos templates. Só depois entra na lista versionada.
5. O script também grava `data/interface/datasets.json` (local, fora do Git) com o índice e a raiz de cada dataset, para a interface achar os arquivos sem argumentos.

### 6.3 Arquivos

- `config/exemplos_interface.json` (versionado): para cada exemplo, `dataset`, `id`, `grupo` (`acerto`/`erro`), `titulo` curto e `nota` (uma ou duas frases explicando o caso, por exemplo "isca temática: imita um documento compartilhado, não a página de login"). Também guarda a lista de **URLs sugeridas** (seção 7.3).
- `data/interface/datasets.json` (local): índices e raízes. Sem ele, a aba de exemplos mostra como gerá-lo.
- Na hora de analisar, a interface lê a captura e o HTML direto das pastas dos datasets e recorta a primeira dobra como na etapa 6 (classe fixada no benign).

Cada clique analisa o exemplo de novo, de verdade: o tempo mostrado é o do detector naquela hora.

## 7. Entrada 2: URL ao vivo

### 7.1 Captura

Para cada análise, um contexto novo e limpo do Chromium (sem cookies de análises anteriores):
- **janela** igual à classe escolhida: 1366×768 (padrão), 1280×960 ou 1920×1080;
- **idioma do navegador** escolhido na tela: `en-US` (padrão, o mesmo das marcas globais na captura dos templates) ou `pt-BR` (o dos bancos brasileiros);
- downloads bloqueados;
- abre com `wait_until="load"` (limite de 30 s); **espera um campo de credencial visível** (senha, e-mail ou usuário, em qualquer frame, como `esperar_credencial` na captura dos templates) por até **20 s** (escolha do desenho: o `login.live.com` só monta o formulário depois de cerca de 13 s de JavaScript); depois espera a rede acalmar por até 10 s; captura **só a janela** (a primeira dobra) e o **DOM renderizado** (`page.content()`), e guarda a URL final (depois de redirecionamentos), o título, o código HTTP e se o campo de credencial apareceu. Páginas sem login demoram até 20 s a mais para abrir; a tela avisa "esperando o formulário de login (até 20 s)" enquanto isso.

A análise usa a URL final. O tempo de abrir a página aparece separado do tempo do detector (seção 8).

### 7.2 "Analisar como se estivesse em…"

Campo opcional `url_simulada`. Quando preenchido, a página é aberta normalmente, mas a análise usa essa URL no lugar da URL final: a checagem de domínio e a contagem de formulários com destino externo passam a ver o domínio simulado. É a demonstração "mesma página, outro domínio": o login verdadeiro da Microsoft em `login.live.com` sai legítimo pela checagem de domínio; o mesmo login "em" `https://microsoft-verificacao.test/` sai phishing da Microsoft. A tela deixa claro quando o domínio é simulado. Aceita o endereço sem `https://` (completa sozinha).

O mesmo campo existe **na aba de exemplos** (escolha do desenho), para a demonstração funcionar **sem internet**: o exemplo 6 (página da própria marca no domínio oficial) sai legítimo com a URL original e, "em" outro domínio, sai phishing da marca se o escore dele passar de τ. Por isso a escolha do exemplo 6 prefere uma página com escore acima de τ (seção 6.1). Se nenhuma URL sugerida passar nos dois vereditos (seção 7.3), a aba de URL continua funcionando sem sugestões e a demonstração do domínio fica com o exemplo 6.

### 7.3 URLs sugeridas e segurança

- **URLs sugeridas** na tela (botões que preenchem o campo): páginas de login legítimas de marcas de 𝒯 cuja captura funciona e que dão o resultado esperado nos dois casos (domínio real → legítima; domínio simulado → phishing da marca). Candidatas: `login.live.com`, `netflix.com/login`, `login.yahoo.com`, `dropbox.com/login`, `linkedin.com/login`, `itau.com.br`. A lista final é conferida na implementação (capturar cada uma e ver os dois vereditos) e só as que passam entram em `config/exemplos_interface.json`.
- **Aviso fixo** na aba: "O navegador vai abrir a página de verdade. Não cole links suspeitos reais; para ver phishing, use os exemplos."
- Só `http` e `https`. O Chromium roda isolado (sandbox padrão), sem perfil salvo, com downloads bloqueados. Nada da página sai da máquina.

## 8. Tela de resultado

### 8.1 Esboço

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ MHF · detector de phishing por impressão digital de layout                    │
│ gradient boosting · 572 templates de 20 marcas · limiar τ = 0,941 · local     │
├──────────────────┬────────────────────────────────────────────────────────────┤
│ [Exemplos] [URL] │ ┌────────────────────────────────────────────────────────┐ │
│                  │ │ ⚠ PHISHING — imita Microsoft                           │ │
│ Acertos          │ │ Parece a Microsoft (escore 0,99, limiar 0,94) e o      │ │
│  1 Microsoft     │ │ domínio exemplo-golpe.com não é da Microsoft.          │ │
│  2 PayPal        │ └────────────────────────────────────────────────────────┘ │
│  …               │ Rótulo real: phishing de Microsoft · ✓ acertou             │
│ Erros            │ "Clone do login corporativo, a variante mais copiada."     │
│  9 Isca OneDrive │                                                            │
│  …               │ ┌── página analisada ──┐   ┌── template mais parecido ──┐  │
│                  │ │   (primeira dobra)   │   │ microsoft/corporativo/2020 │  │
│                  │ └──────────────────────┘   └────────────────────────────┘  │
│                  │                                                            │
│                  │ Escore por marca (│ = τ)        Sinais da Microsoft         │
│                  │ Microsoft ██████████████│ 0,99  pHash       0,86 (9 bits) │
│                  │ Yahoo     █             │ 0,02  embedding   0,97          │
│                  │ Google    █             │ 0,01  DOM caminhos 0,91 …       │
│                  │                                                            │
│                  │ Domínio: exemplo-golpe.com · oficiais: microsoft.com, …    │
│                  │ Detector: 84 ms (embedding 29 · abrir 17 · classificador 11 │
│                  │ · pHash 8 · busca 6 · DOM 3)                               │
│                  │ ▸ Como o MHF decide                                        │
└──────────────────┴────────────────────────────────────────────────────────────┘
```

### 8.2 O que aparece

- **Veredito** em destaque: "PHISHING — imita X" (vermelho) ou "Legítima" (verde), com uma frase por motivo:
  - `phishing`: "Parece X (escore e, limiar τ) e o domínio d não é de X."
  - `dominio_legitimo_estagio2`: "Parece X, mas está num domínio oficial de X (d)."
  - `abaixo_do_limiar`: "Não se parece o bastante com nenhuma marca protegida (mais próxima: X, escore e < τ)."
  - os motivos do estágio 1 só aparecem se o modelo carregado tiver estágio 1 (o principal não tem); recebem frase própria.
- **Rótulo real** (só nos exemplos): o que a página é de fato pelo dataset, se o detector acertou (pelas regras da seção 6.1: marca certa, marca errada, "o dataset não informa a marca") e a nota do exemplo. Com domínio simulado, a tela não compara com o rótulo real (a página foi tirada do lugar dela) e diz isso.
- **Página analisada × template mais parecido**: à esquerda, a primeira dobra que o detector viu; à direita, o template da **marca exibida** (a atribuída, a do domínio oficial ou a de maior escore) mais parecido **pelo embedding** na mesma classe de tela, com marca, variante, ano e origem (Wayback ou ao vivo). Legenda: "o classificador usa o melhor valor de cada sinal entre todos os templates da marca; esta é a imagem mais parecida".
- **Escore por marca**: barras das 5 marcas de maior escore, com a marca do limiar τ.
- **Sinais da marca exibida**: as 7 características que o classificador recebe, com nome legível: semelhança do pHash (e a distância em bits), cosseno do embedding, Jaccard dos caminhos do DOM, Jaccard dos elementos críticos, semelhança das contagens, DOM idêntico (sim/não) e "DOM ausente" (sim/não).
- **Domínio** registrável da página (marcado "simulado" quando for o caso) e os domínios oficiais da marca exibida.
- **Tempo** do detector por parte e total (as partes de `Veredito.tempos_ms`). Na URL ao vivo, uma linha separada: "abrir a página no navegador automatizado: x s (na extensão a página já está aberta, então esse tempo não existe)".
- **"Como o MHF decide"** (recolhido por padrão): os passos em 5 linhas — captura da janela → impressão digital φ = (h, e, s) → comparação com os templates do mesmo tamanho de tela → escore de cada marca pelo gradient boosting → limiar τ e checagem de domínio.

### 8.3 Visual

Tela única, clara, legível num projetor (fonte grande nos vereditos, contraste alto, cores com significado só para veredito: vermelho/verde, com ícone e texto, sem depender só da cor). Detalhes de estilo ficam com quem implementa.

## 9. Mudança na biblioteca

`Detector.analisar_pagina` ganha `detalhes=False`. Com `detalhes=True`, o `Veredito` traz, além do de hoje:
- a primeira dobra analisada (imagem) e a classe de tela usada;
- as características de cada marca (o vetor que foi ao classificador, com os nomes);
- para cada marca, o template de maior cosseno do embedding na classe (índice, id, cosseno);
- se o s foi tratado como ausente e o número de elementos do DOM.

O veredito não muda com `detalhes` (teste: os mesmos campos com e sem). Os outros chamadores (`verificar.py`, `medir_latencia.py`) continuam iguais.

## 10. Testes

- **Unidade (antes do código):** frase de cada motivo; montagem do resultado a partir de um `Veredito` (com e sem rótulo real, com domínio simulado nas duas abas); "acertou" para phishing de 𝒯 com a marca certa e errada, phishing sem marca, phishing fora de 𝒯 e legítima; escolha do template exibido; validação de URL (esquemas, completar `https://`, classe, idioma); `id` de template fora da base recusado; leitura da lista de exemplos (exemplo ausente no disco → mensagem clara); `detalhes=True` não muda o veredito.
- **Servidor:** sobe em porta livre numa thread com detector e capturador falsos; testa `/api/estado`, `/api/exemplo`, `/api/url`, `/api/template` e os erros 400.
- **Captura:** função testada com um navegador falso (sem rede). Um teste real com o Chromium só roda com `MHF_TESTE_NAVEGADOR=1`.
- **Manual, antes do PR:** abrir a interface, rodar os 12 exemplos e as URLs sugeridas (domínio real e simulado), conferir os vereditos com `candidatos.json` e guardar capturas de tela para a descrição do PR.

## 11. Como rodar (README, passo 7)

```bash
# uma vez: escolher os exemplos (grava data/interface/)
python scripts/escolher_exemplos.py --dataset phish360 <índice> <raiz> --dataset phishpedia_phish <índice> <raiz> \
    --dataset phishpedia_benign <índice> <raiz> 1366x768
# depois, sempre:
python scripts/interface.py            # abre http://127.0.0.1:8000
```

## 12. Limitações conhecidas

- **Tempo de abrir a página** com o Playwright (segundos, até 20 s a mais em páginas sem login) não é latência do detector; na extensão a página já está aberta.
- **Sem internet**, a aba de URL não funciona; os exemplos e a demonstração do domínio pelo exemplo 6 continuam funcionando.
- **DOM ao vivo × DOM do treino:** ao vivo, o s vem do DOM renderizado (como nos templates e como a extensão verá); no Phish360, o HTML do treino é o que o servidor enviou. Páginas legítimas ao vivo ficam mais parecidas com os templates do que as do treino; o efeito no escore não é medido.
- **Sites que bloqueiam navegador automatizado** (o PayPal bloqueou na captura dos templates) não funcionam na URL ao vivo; ficam fora das URLs sugeridas.
- **Três tamanhos de janela** só, os da base.
- **Exemplos dependem dos datasets no disco** (pastas com exclusão no antivírus). Levar a interface para outra máquina exige os datasets ou um pacote próprio, fora do escopo.
- **Um usuário, uma análise por vez.**

## 13. Impacto na monografia

- **Cap. 4:** uma seção sobre o protótipo de demonstração e a correspondência com a extensão (captura da janela ↔ `captureVisibleTab`; DOM renderizado ↔ *content script*; tudo local).
- **Cap. 6 / trabalhos futuros:** a extensão parte daqui.
- Nenhum resultado do Cap. 5 muda.

## 14. Deixado para quem implementa

Organização dos arquivos estáticos, estilo visual, formato das imagens na resposta (PNG ou JPEG em base64), mensagens de erro, tamanho da amostra de candidatos por tipo e a porta, desde que respeitem as seções acima.

## 15. Resultado da implementação (22/11/2026)

**Exemplos** (`config/exemplos_interface.json`), escolhidos entre 270 candidatos sorteados do teste por `scripts/escolher_exemplos.py` e revisados pelo Lucas olhando as capturas. Nos 270, o veredito pela página bruta foi igual ao da tabela de similaridades da etapa 6.

| # | Grupo | Página | Veredito (escore) |
|---|---|---|---|
| 1 | acerto | Clone do login da Microsoft (Outlook, Phishpedia) | phishing de Microsoft (0,999) |
| 2 | acerto | Clone do login do PayPal | phishing de PayPal (0,999) |
| 3 | acerto | Clone do login da Netflix | phishing de Netflix (0,997) |
| 4 | acerto | Clone da página inicial do Itaú | phishing de Itaú (0,998) |
| 5 | acerto | Clone do login da Amazon (Phish360, 1280×960) | phishing de Amazon (0,989) |
| 6 | acerto | Login verdadeiro do eBay em `ebay.es` | legítima, abaixo do limiar (0,779) |
| 7 | acerto | Login de outro site (StudentVIP) | legítima, abaixo do limiar (0,521) |
| 8 | acerto | Página sem DOM útil (365area) | legítima, abaixo do limiar (0,545) |
| 9 | erro | Isca do OneDrive | não detectado (0,662) |
| 10 | erro | Clone do Yahoo sem DOM útil | não detectado (0,848; Yahoo é a marca mais próxima) |
| 11 | erro | Etapa seguinte do golpe: Bank of America pedindo foto do documento (Phish360) | não detectado (0,690) |
| 12 | erro | Alerta falso: login do vestibular de uma escola (`saobraz.edu.br`) | phishing de Yahoo (0,965) |

**URLs sugeridas** (conferidas em 1366×768): `login.live.com`, `netflix.com/login`, `login.yahoo.com`, `dropbox.com/login`, `facebook.com/login.php` e `banco.bradesco` (pt-BR). Todas dão legítima no domínio real (checagem de domínio, escore 0,999) e phishing da marca no domínio simulado. `linkedin.com/login`, `itau.com.br` e `santander.com.br` respondem 403 ao navegador automatizado e ficaram de fora. Facebook e Bradesco entraram no lugar delas, pela mesma regra.

**Desvios do desenho:**
- **Demonstração do domínio sem internet (§7.2).** Nenhuma página das próprias marcas no teste passa de τ (as 6 candidatas ficam entre 0,55 e 0,78). Como a checagem de domínio só é feita depois do limiar, o exemplo 6 "em outro domínio" continuaria legítimo. A demonstração usa o exemplo 1 no sentido inverso: no domínio do golpe, phishing da Microsoft (0,999); "em" `https://login.microsoftonline.com/`, legítima pela checagem de domínio.
- **Candidatos "página da própria marca" (§6.2).** Essas páginas saem por escore baixo, antes da checagem de domínio. Por isso o tipo do candidato passou a considerar também se o domínio é oficial de alguma marca (`tipo_do_candidato(..., dominio_de_marca)`).
- **Imagem da página na resposta:** JPEG, e não PNG (§14). É menor e mais rápida de codificar em 1920×1080; a análise usa a captura original.
- **Reuso:** `esperar_credencial` saiu de `scripts/capturar_templates.py` para `mhf.captura`, e o recorte da dobra de `scripts/medir_latencia.py` para `mhf.exemplos.ler_pagina_do_dataset`. O comportamento é o mesmo nos dois.
- **Tela em 1024×768**, tamanho comum de projetor: escores e sinais ficam um sobre o outro abaixo de 1280 px de largura.
- **Servidor (§5), depois da revisão independente.** Cada conexão tem sua thread, porque os navegadores abrem conexões antes de precisar e, num servidor sem threads, uma conexão ociosa prendia as outras. Toda chamada ao detector e ao Playwright passa por um único trabalhador: as análises continuam saindo uma por vez, e o Playwright fica sempre na mesma thread. A porta é exclusiva: no Windows, uma segunda interface na mesma porta dá erro em vez de ligar em silêncio. O servidor só atende pedidos endereçados a `127.0.0.1`/`localhost` e exige JSON no POST, o que impede um site aberto no navegador de disparar análises (DNS rebinding e POST "simples").
- **Sandbox do Chromium (§7.3):** o Playwright o desliga por padrão; a captura ao vivo o liga explicitamente (`chromium_sandbox=True`). Conferido no Windows.
- **Sinais do DOM sem DOM (§8.2):** com o DOM ausente, o classificador recebe 0 nesses sinais; a tela mostra "—", para não sugerir que o DOM foi comparado.
