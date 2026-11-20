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
