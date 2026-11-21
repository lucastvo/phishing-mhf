# Base de templates com vários anos — desenho da captura

**Data:** 20/11/2026 · **Estado:** aprovado pelo Lucas (20/11/2026) · **Etapa do plano:** 2 (captura de templates), depende da etapa 1 (tabela de marcas)

## 1. Intenção e porquê

O MHF compara cada página com **templates**, que são as impressões digitais das páginas de login legítimas das 20 marcas de 𝒯. Os phishings dos datasets são de 2019–2020 (Phishpedia) e de 2020–2024 (Phish360), mas as marcas redesenham o login ao longo do tempo. Um template capturado só hoje (2026) compararia um kit de 2019 com um design de 2026. Isso subestima o método por um motivo alheio a ele: a idade da base.

A monografia já se compromete com esse ponto. O diferencial "Execução local e atualização" (Cap. 3.6) afirma que listas de referência estáticas se desatualizam (Ji et al., 2025) e que a base é atualizada periodicamente. Este desenho trata a defasagem e transforma essa afirmação em um resultado medido.

## 2. Objetivos, não objetivos e antiobjetivos

**Objetivos**
- Para cada marca de 𝒯 e cada variante de login, obter templates de **vários anos** (2019 a 2026): screenshot, DOM e metadados de origem.
- Permitir dois cenários de avaliação: **base completa** e **só 2026**, cuja diferença mede o custo da defasagem. Permitir também, no Phishpedia, a checagem **"só templates anteriores à data da amostra"**.
- Tornar a base **reproduzível**: qualquer pessoa consegue recriá-la a partir da lista versionada de snapshots.

**Não objetivos** (ficam para outras etapas)
- Calcular pHash, embedding ou *s* (etapas 3 e 4).
- Decidir a resolução padrão nem normalizar imagens (etapa 3). Aqui só se captura nas duas resoluções dos datasets.
- Capturar páginas de phishing; fazer login; contornar CAPTCHA ou detecção de robôs.

**Antiobjetivos** (tornariam o trabalho um fracasso mesmo "funcionando")
- Um template mal renderizado (em branco, sem formulário, página de erro do Wayback) entrar na base sem ninguém ver.
- Um template sem origem rastreável (URL e data do snapshot).
- Uma base que não pode ser reconstruída por outra pessoa.

## 3. Abordagens consideradas

| | Abordagem | Prós | Contras |
|---|---|---|---|
| 1 | Só templates atuais (2026) | simples, sem depender do Wayback | compara 2019 com 2026; subestima o método |
| 2 | Template casado com a data de cada amostra | o mais fiel por amostra | só funciona no Phishpedia (o Phish360 não tem data por amostra); supõe que o kit copia o design do mês; buracos do Wayback deixam amostras sem template |
| **3** | **Base com vários anos, todos na base** | funciona nos dois datasets; a busca escolhe a variante mais próxima; buracos de um ano cobertos pelos vizinhos; contém a abordagem 1 como cenário de comparação | mais trabalho de captura e curadoria |

**Escolhida: 3** (decisão do Lucas, 20/11/2026). Evidências que pesaram:
- No zip do Phish360, todos os `index.html` estão datados de 2021, o que é data de empacotamento, não de coleta.
- Os kits são reaproveitados em massa: 3.724 páginas de Outlook com DOM idêntico.
- Os snapshots de 2020 de `login.live.com` e de `paypal.com/signin` renderizam fielmente no Wayback.

## 4. Desenho

**Arquivos:**
- `scripts/capturar_templates.py`, com três modos: `--planejar`, `--capturar` e `--revisar`.
- `src/mhf/templates.py`, com as funções puras (testáveis sem rede).
- Testes em `tests/test_templates.py`.

### 4.1 Entrada (vem da etapa 1)
A tabela de marcas (`marcas.json`, versionada) traz, para cada entidade de 𝒯, uma lista de **variantes de login**:

```json
{"entidade": "Microsoft",
 "logins": [
   {"variante": "pessoal",     "url": "https://login.live.com/login.srf",  "locale": "en-US"},
   {"variante": "corporativo", "url": "<a definir na etapa 1>",            "locale": "en-US"}
 ]}
```

O `locale` é `pt-BR` para Itaú, Bradesco, Caixa e Santander, e `en-US` para as demais marcas. Ele só é usado na captura ao vivo.

### 4.2 Fase 1 — planejar (`--planejar`)
Para cada variante e cada ano de **2019 a 2026**, consulta a API CDX do Wayback e escolhe o snapshot com status 200 **mais próximo de 1º de janeiro** daquele ano.
- **Por que janeiro:** assim, toda amostra do Phishpedia (a mais antiga é de jul/2019) tem pelo menos um template anterior a ela, o que viabiliza a checagem "só templates anteriores".
- **Tolerância:** se o snapshot mais próximo estiver a mais de 6 meses do alvo, o ano vira **buraco** (registrado, sem template). Se dois anos caírem no mesmo snapshot, ele entra uma vez só.
- **Redirecionamentos:** URLs de login costumam redirecionar (ex.: `login.srf` com parâmetros). Se no ano só houver snapshots 3xx, segue-se o destino do redirecionamento e registra-se a URL final efetivamente usada.
- **Capturas ao vivo:** entram no mesmo arquivo de saída abaixo, com `origem: ao_vivo` e a data da captura no lugar do timestamp, para que a aprovação (4.4) fique num lugar só.
- **Saída:** `config/templates_snapshots.json` (**versionado**; não usar `.csv`, que o `.gitignore` ignora), com, por variante e ano, o timestamp escolhido ou o motivo do buraco. Esse arquivo é a "receita" reproduzível da base, e você o revisa antes da fase 2.
- **Buracos conhecidos:** `login.microsoftonline.com` (0 snapshots), Chase antes de 2023, Apple (a API respondeu 403). Nesta fase, testam-se URLs alternativas de cada um (decididas na etapa 1). O que não tiver cobertura fica documentado como limitação, por marca e ano.

### 4.3 Fase 2 — capturar (`--capturar`)
Usa o Playwright com Chromium headless, na máquina do Lucas.
- **Snapshots do Wayback:** abre `https://web.archive.org/web/<timestamp>if_/<url>`. O modificador `if_` remove a barra do Wayback e mantém os recursos (CSS, imagens) **arquivados**. O `id_` puxaria o CSS ao vivo, de 2026, e misturaria épocas.
- **Ao vivo (2026):** abre a URL original com o `locale` da variante.
- **Espera:** espera um campo de credencial aparecer (`input[type=password]`, `input[type=email]` ou similar), por até 30 s, e depois a rede ficar ociosa, com limite. Não usar espera de tempo fixo: o login da Microsoft de 2025 levou ~13 s para mostrar o formulário.
- **Duas resoluções**, cada uma num carregamento separado (a página pode se reorganizar ao mudar de largura): 1280×960 (Phish360) e 1366×768 (Phishpedia). Screenshot **só da área visível**, não da página inteira.
- **HTML, em duas versões**, porque ainda não sabemos qual delas corresponde ao HTML dos datasets (ver 4.6):
  - `dom_<resolução>.html`: o DOM depois do JavaScript (`page.content()`), com o prefixo `https://web.archive.org/web/<ts>.../` **removido** das URLs. Sem isso, toda `action` de formulário pareceria externa e contaminaria `forms_action_externa`.
  - `html_original.html`: os bytes do HTML como foi arquivado (`.../<timestamp>id_/<url>`), antes do JavaScript.
- **Status por resolução:**
  - `ok`: o campo de credencial apareceu.
  - `sem_formulario`: a página carregou, mas o campo não apareceu no tempo limite.
  - `erro_wayback`: o Wayback devolveu página de erro ou "not archived", ou status HTTP ≠ 200.
  - `bloqueado`: na captura ao vivo, CAPTCHA, "acesso negado" ou similar.

  Tudo é salvo mesmo quando falha, para aparecer na revisão.
- **Sem interação:** o script não clica em nada (nem em banner de cookies). O que atrapalhar aparece na revisão.
- **Retomável:** pula capturas que já tenham `meta.json` com status OK. Espera ~1,5 s entre requisições ao Wayback.

**Saída** (fora do git): `data/templates/<entidade>/<variante>/<AAAA-MM>/` com `shot_1280x960.png`, `shot_1366x768.png`, `dom_1280x960.html`, `dom_1366x768.html`, `html_original.html` e `meta.json`. O `meta.json` traz entidade, variante, URL de login, origem (`wayback`/`ao_vivo`), URL e timestamp do snapshot, ano-alvo, data da captura, status e tempo de renderização por resolução, e as versões do Playwright e do Chromium.

### 4.4 Fase 3 — revisar (`--revisar`)
Gera `data/templates/revisao.html`, uma grade com marcas nas linhas, anos nas colunas e miniaturas nas células, com status e link para o snapshot. **Você aprova cada template**. A aprovação (`aprovado: true/false` e o motivo) fica registrada em `config/templates_snapshots.json`. **Só templates aprovados entram na base** (etapa 4). Isso protege contra o primeiro antiobjetivo.

### 4.5 O que a avaliação ganha (consumido na etapa 6)
- **Base completa** × **só 2026** (ao vivo): custo da defasagem em revocação, FPR e top-1.
- **Phishpedia, só templates com timestamp anterior à amostra:** responde à objeção "usar template do futuro".
- (Opcional) Curva de desempenho conforme a idade da base: só até 2019, até 2021, até 2023…

### 4.6 Riscos e pontos em aberto
- **HTML bruto × DOM renderizado:** os datasets parecem guardar o HTML bruto ("RAW-HTML" no Phish360; no Phishpedia ainda não se sabe). Por isso a captura salva as duas versões. A escolha de qual comparar com qual fica para a etapa 4, com dados na mão.
- **Idioma e região na captura ao vivo:** capturando do Brasil, marcas globais podem servir páginas em português ou com outro layout, mesmo com `locale` en-US. Isso será checado na revisão.
- **Bloqueio de robôs ou CAPTCHA ao vivo** (ex.: Google, Chase): a captura é marcada como falha e documentada. Nada de contornar.
- **Duração:** ~20 marcas × ~1,5 variantes × 9 capturas (8 snapshots de 2019–2026 + 1 ao vivo) × 2 resoluções ≈ 540 carregamentos de ~10–20 s, ou seja, 1,5 a 3 h. Por isso a captura é retomável.

### 4.7 Testes
Testes unitários, sem rede, para as funções puras:
- escolha do snapshot a partir de uma lista CDX (mais próximo, tolerância, deduplicação);
- montagem das URLs `if_`/`id_`;
- remoção do prefixo do Wayback das URLs do DOM;
- nomes de pasta.

A captura em si é verificada à mão em 1 ou 2 marcas antes da rodada completa.

## 5. Dependências e pré-requisitos
- **Etapa 1 (tabela de marcas)** pronta, com as variantes de login e as URLs alternativas para os buracos.
- **Navegador do Playwright:** `python -m playwright install chromium`, um download à parte que ainda precisa da sua aprovação.

## 6. Impacto na monografia
- **Cap. 4:** construção da base de templates com vários anos (este documento).
- **Cap. 5:** experimento da defasagem (base completa × só 2026).
- **Cap. 1, Método item 2:** já precisa ser reescrito por causa dos datasets; passa a mencionar a base com vários anos.
- **§2.6.3** ("Construção da impressão digital") continua coerente: o template é produzido pelo mesmo procedimento aplicado a páginas legítimas.

## 7. Decisões tomadas neste desenho (conferir)
Estas são decisões minhas, propostas para você conferir:
- **Snapshot mais próximo de 1º de janeiro**, com tolerância de 6 meses.
- **Captura nas duas resoluções dos datasets**, adiando a escolha da resolução para a etapa 3.
- **Salvar o DOM renderizado e o HTML original**, adiando para a etapa 4 qual deles comparar.
- **Modificador `if_`** para os snapshots do Wayback.
- **Revisão manual obrigatória** antes de um template entrar na base.
- **Receita da base em `config/templates_snapshots.json`**, versionada; as imagens e os HTMLs ficam fora do git.
