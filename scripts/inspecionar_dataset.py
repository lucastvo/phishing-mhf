"""
Passo 0 — Inspeção do dataset Phishpedia (phishing + benigno).

Varre recursivamente uma pasta, encontra cada amostra (pasta que contém shot.png)
e gera um relatório com:
  - quantas amostras existem e quantas têm html.txt / info.txt
  - tamanho do HTML (para achar HTMLs vazios ou truncados)
  - distribuição de marcas-alvo (inferida do nome da pasta, ex.: "PayPal Inc.+2020-...")
  - um CSV com uma linha por amostra, que vira o índice do resto do pipeline

Uso:
    python inspecionar_dataset.py --raiz caminho/para/phishing --rotulo phishing --saida phishing.csv
    python inspecionar_dataset.py --raiz caminho/para/benign   --rotulo benigno  --saida benigno.csv

Dependências: só a biblioteca padrão + Pillow (pip install pillow).
"""

import argparse
import csv
import os
from collections import Counter

from PIL import Image

HTML_MINIMO = 200  # bytes; abaixo disso o HTML provavelmente é inútil para o DOM


def ler_url(caminho_info):
    """info.txt costuma ter só a URL; em algumas versões pode ter mais linhas."""
    try:
        with open(caminho_info, encoding="utf-8", errors="ignore") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    return linha
    except OSError:
        pass
    return ""


def inferir_marca(nome_pasta):
    """No Phishpedia as pastas de phishing seguem o padrão 'Marca+timestamp'."""
    return nome_pasta.split("+")[0].strip() if "+" in nome_pasta else ""


def inspecionar(raiz, rotulo):
    linhas = []
    for pasta, _subpastas, arquivos in os.walk(raiz):
        if "shot.png" not in arquivos:
            continue
        nome = os.path.basename(pasta)
        shot = os.path.join(pasta, "shot.png")
        html = os.path.join(pasta, "html.txt")
        info = os.path.join(pasta, "info.txt")

        try:
            with Image.open(shot) as img:
                largura, altura = img.size
            shot_ok = True
        except Exception:
            largura = altura = 0
            shot_ok = False

        tam_html = os.path.getsize(html) if os.path.exists(html) else 0

        linhas.append({
            "id": os.path.relpath(pasta, raiz),
            "rotulo": rotulo,
            "marca": inferir_marca(nome),
            "url": ler_url(info) if os.path.exists(info) else "",
            "tem_html": int(tam_html > 0),
            "html_util": int(tam_html >= HTML_MINIMO),
            "bytes_html": tam_html,
            "shot_ok": int(shot_ok),
            "largura": largura,
            "altura": altura,
        })
    return linhas


def relatorio(linhas):
    n = len(linhas)
    if n == 0:
        print("Nenhuma amostra encontrada (nenhuma pasta com shot.png).")
        return
    pct = lambda k: 100 * sum(l[k] for l in linhas) / n
    print(f"Amostras encontradas: {n}")
    print(f"  com html.txt:          {pct('tem_html'):.1f}%")
    print(f"  com HTML útil (>={HTML_MINIMO}B): {pct('html_util'):.1f}%")
    print(f"  screenshot legível:    {pct('shot_ok'):.1f}%")
    print(f"  com URL:               {100 * sum(bool(l['url']) for l in linhas) / n:.1f}%")

    marcas = Counter(l["marca"] for l in linhas if l["marca"])
    if marcas:
        print(f"\nMarcas distintas: {len(marcas)}. Top 25:")
        for marca, qtd in marcas.most_common(25):
            print(f"  {qtd:6d}  {marca}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--raiz", required=True)
    p.add_argument("--rotulo", required=True, choices=["phishing", "benigno"])
    p.add_argument("--saida", required=True)
    a = p.parse_args()

    linhas = inspecionar(a.raiz, a.rotulo)
    relatorio(linhas)
    if linhas:
        with open(a.saida, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
            w.writeheader()
            w.writerows(linhas)
        print(f"\nÍndice salvo em {a.saida}")


if __name__ == "__main__":
    main()
