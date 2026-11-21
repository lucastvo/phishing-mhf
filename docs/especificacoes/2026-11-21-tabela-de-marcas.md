# Tabela de marcas e domínios — desenho

**Data:** 21/11/2026 · **Estado:** aprovado pelo Lucas (21/11/2026) · **Etapa do plano:** 1 (tabela de marcas), consumida pela etapa 2 (captura de templates) e pelas etapas 5 e 6 (cascata e avaliação)

## 1. Intenção e porquê

O MHF compara cada página com os templates das 20 entidades protegidas (𝒯, monografia §2.1.4). Para isso, precisa saber três coisas de cada entidade:

1. **Quais rótulos dos datasets são dela.** Sem isso não há identificação do alvo (top-1) nem separação entre phishing "em 𝒯" e "fora de 𝒯" (CLAUDE.md §11).
2. **Quais domínios são legítimos.** A cascata (§2.9) libera a página quando o domínio pertence ao template mais próximo.
3. **Quais páginas de login servem de referência.** Essa é a entrada do script de captura (etapa 2).

## 2. Decisões (aprovadas pelo Lucas em 21/11/2026, com base no levantamento dos dados)

1. **Hotmail entra na Microsoft.** Ficam **fora** de 𝒯: Instagram, WhatsApp, AOL, Caixa Geral de Depósitos, CaixaBank e o rótulo `mic` do Phish360, que é o Made-in-China.com.
2. **Versões de outros países entram como variantes extras da mesma marca:** Amazon Japão, eBay Alemanha e Santander Polônia. Os domínios legítimos incluem esses países.
3. **As variantes seguem o que os kits de phishing imitam**, medido pelos títulos das páginas nos dois datasets:
   - login **mais a página inicial** em Chase, Bank of America, Wells Fargo e Facebook;
   - **página de rastreamento** no DHL;
   - **Itaucard** no Itaú;
   - Microsoft **corporativo** (`login.microsoftonline.com/common/oauth2/authorize`, imitado por cerca de 4.600 phishings) **e pessoal** (`login.live.com`).
4. **Adobe e as iscas do OneDrive e do Google Docs continuam em 𝒯.** O resultado é reportado por marca, e as iscas temáticas, que não copiam nenhuma página real, são discutidas como limitação.
5. **A Apple usa `account.apple.com`** (snapshots do Wayback de 2025 e 2026, mais a captura ao vivo). O Wayback bloqueia `appleid.apple.com` e `icloud.com`, então 2019–2023 ficam sem template, e isso é documentado como limitação.
   - A decisão original era "só ao vivo". A implementação descobriu que o domínio novo do Apple ID não é bloqueado, e o Lucas aprovou a mudança em 21/11/2026.
6. **Os domínios legítimos são montados à mão** a partir de fontes oficiais e revisados pelo Lucas. O `domain_map.pkl` do Phishpedia não é usado: é um *pickle* e pode executar código ao ser aberto.

## 3. Objetivos, não objetivos e antiobjetivos

**Objetivos**
- Uma tabela única e versionada que a captura, a cascata e a avaliação leem do mesmo lugar.
- Uma checagem de domínio correta para qualquer domínio do mundo (`.com.br`, `.co.uk`, `.co.jp`, subdomínios, IPs).

**Não objetivos**
- Capturar os templates (etapa 2) e calcular métricas (etapa 6).
- Corrigir o `forms_action_externa` do componente estrutural (PR #1). Ele poderá usar `dominio_registravel` depois.

**Antiobjetivos**
- Um rótulo mapeado para a marca errada, como `mic` → Microsoft.
- Um domínio de phishing aceito como legítimo, como `paypal.com.conta-segura.net`.
- Uma página legítima de outro país acusada de phishing, como `amazon.co.jp`.

## 4. Desenho

**`config/marcas.json`** (versionado) é uma lista de entidades, no formato que `templates.ler_marcas` já lê, com campos a mais:

```json
{"entidade": "Microsoft",
 "nomes_phishpedia": ["Outlook", "Office365", "Microsoft OneDrive", "Hotmail"],
 "nomes_phish360": ["office", "outlook", "microsoft"],
 "dominios": ["microsoft.com", "microsoftonline.com", "live.com", "office.com", "office365.com", "outlook.com", "..."],
 "logins": [
   {"variante": "corporativo", "url": "https://login.microsoftonline.com/common/oauth2/authorize", "locale": "en-US"},
   {"variante": "pessoal", "url": "https://login.live.com/login.srf", "locale": "en-US"}
 ]}
```

**`src/mhf/marcas.py`:**
- `ler_tabela(caminho) -> list[dict]`
- `entidade_do_rotulo(tabela, dataset, rotulo) -> str | None`: `dataset` ∈ {`"phishpedia"`, `"phish360"`}. Devolve `None` para "fora de 𝒯". A comparação é exata. Para os rótulos do Phish360, ignora maiúsculas e minúsculas.
- `dominio_registravel(url_ou_host) -> str`: usa o `tldextract` com a cópia da *Public Suffix List* que vem no pacote (`suffix_list_urls=()`), sem rede e com resultado reproduzível. Para um IP, devolve o próprio IP.
- `dominio_legitimo(tabela, entidade, url) -> bool`: verdadeiro quando o domínio registrável da URL está em `dominios` da entidade.

**Teste de consistência da própria tabela** (roda junto com a suíte):
- são 20 entidades, cada uma com pelo menos um login e um domínio;
- o domínio registrável de cada URL de login está nos `dominios` da própria entidade;
- nenhum rótulo aparece em duas entidades;
- os ids de variante (`slug`) são únicos.

## 5. Escolhas técnicas

- **`tldextract`** no lugar de "dois últimos rótulos do host". Essa regra erra `.com.br`, que é o bug conhecido do componente estrutural. Entra no `requirements.txt`.
- **A branch `marcas` sai da `templates`**, porque a tabela é lida pelo código de captura do PR #2. O PR desta etapa usa o PR #2 como base, e o PR #2 é mergeado primeiro.

## 6. Pontos a fechar na implementação (o Lucas revisa no PR)

- A lista de domínios de cada marca, com os casos de dúvida marcados no PR.
- As URLs que ainda precisam ser checadas no Wayback:
  - a alternativa para a Caixa, cujo internet banking é um app JavaScript;
  - a URL do Itaucard;
  - a página inicial do Facebook, cuja consulta deu timeout.
- Locale das variantes estrangeiras: `ja-JP` (Amazon Japão), `de-DE` (eBay Alemanha), `pl-PL` (Santander Polônia).
