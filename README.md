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
