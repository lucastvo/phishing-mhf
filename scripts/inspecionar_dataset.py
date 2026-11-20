"""
Passo 0 — Inspeção do dataset (Phish360 ou Phishpedia).

Formatos reconhecidos automaticamente, por amostra:
  Phish360:   <amostra>/SCREEN-SHOT/screen_shoot.png, RAW-HTML/index.html, URL/url.txt, Label/label.txt
  Phishpedia: <amostra>/shot.png, html.txt, info.txt (rótulo vem de --rotulo)

Varre recursivamente uma pasta, encontra cada amostra (pasta que contém shot.png)
e gera um relatório com:
  - quantas amostras existem e quantas têm html.txt / info.txt
  - tamanho do HTML (para achar HTMLs vazios ou truncados)
  - distribuição de marcas-alvo (inferida do nome da pasta, ex.: "PayPal Inc.+2020-...")
  - um CSV com uma linha por amostra, que vira o índice do resto do pipeline

Uso:
    python inspecionar_dataset.py --raiz data/Phish360 --saida data/phish360.csv
    python inspecionar_dataset.py --raiz data/phishpedia/phishing --rotulo phishing --saida data/phishing.csv

Dependências: só a biblioteca padrão + Pillow (pip install pillow).
"""

import argparse
import csv
import os
from collections import Counter

from PIL import Image

HTML_MINIMO = 200  # bytes; abaixo disso o HTML provavelmente é inútil para o DOM


def ler_texto(caminho):
    """Primeira linha não vazia do arquivo (sem BOM). Vazio se não existir."""
    try:
        with open(caminho, encoding="utf-8-sig", errors="ignore") as f:
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


def normalizar_rotulo(texto):
    t = texto.strip().lower()
    if t.startswith("phish"):
        return "phishing"
    if t.startswith(("legit", "benign")):
        return "benigno"
    return t


def localizar(pasta, arquivos):
    """Devolve (shot, html, url, label) da amostra, ou None se a pasta não for uma amostra."""
    if "shot.png" in arquivos:  # Phishpedia
        return (os.path.join(pasta, "shot.png"), os.path.join(pasta, "html.txt"),
                os.path.join(pasta, "info.txt"), None)
    shot = os.path.join(pasta, "SCREEN-SHOT", "screen_shoot.png")
    if os.path.isfile(shot):  # Phish360
        return (shot, os.path.join(pasta, "RAW-HTML", "index.html"),
                os.path.join(pasta, "URL", "url.txt"), os.path.join(pasta, "Label", "label.txt"))
    return None


def inspecionar(raiz, rotulo_padrao=None):
    linhas = []
    for pasta, _subpastas, arquivos in os.walk(raiz):
        caminhos = localizar(pasta, arquivos)
        if caminhos is None:
            continue
        shot, html, info, label = caminhos
        rel = os.path.relpath(pasta, raiz)
        nome = os.path.basename(pasta)

        try:
            with Image.open(shot) as img:
                largura, altura = img.size
            shot_ok = True
        except Exception:
            largura = altura = 0
            shot_ok = False

        tam_html = os.path.getsize(html) if os.path.exists(html) else 0
        rotulo = normalizar_rotulo(ler_texto(label)) if label else (rotulo_padrao or "")

        linhas.append({
            "id": rel,
            "particao": rel.replace("\\", "/").split("/")[0] if os.sep in rel or "/" in rel else "",
            "rotulo": rotulo,
            "marca": inferir_marca(nome),
            "url": ler_texto(info),
            "caminho_shot": os.path.relpath(shot, raiz),
            "caminho_html": os.path.relpath(html, raiz),
            "tem_html": int(tam_html > 0),
            "html_util": int(tam_html >= HTML_MINIMO),
            "bytes_html": tam_html,
            "shot_ok": int(shot_ok),
            "largura": largura,
            "altura": altura,
        })
        _subpastas.clear()  # não desce dentro da amostra
    return linhas


def relatorio(linhas):
    n = len(linhas)
    if n == 0:
        print("Nenhuma amostra encontrada.")
        return
    pct = lambda k: 100 * sum(l[k] for l in linhas) / n
    print(f"Amostras encontradas: {n}")
    for (part, rot), qtd in sorted(Counter((l["particao"], l["rotulo"]) for l in linhas).items()):
        print(f"  {part or '-':10s} {rot:10s} {qtd}")
    print(f"  com HTML:              {pct('tem_html'):.1f}%")
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
    p.add_argument("--rotulo", choices=["phishing", "benigno"], help="só para Phishpedia, que não traz rótulo por amostra")
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
