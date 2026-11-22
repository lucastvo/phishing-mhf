"""
Passo 5c — verifica páginas com um detector salvo (passo 5b) e mostra o veredito de cada uma.

Uso, com amostras das tabelas de similaridades:
    python scripts/verificar.py --modelo data/modelos/regressao \
        --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign \
        --divisao data/divisao.csv --amostras 20
    python scripts/verificar.py --modelo data/modelos/regressao --tabelas ... --divisao data/divisao.csv \
        --ids "trainval\\P10001_paypal" "Amazon.com Inc.+2019-07-29-10`40`48"

Uso, com uma página bruta (captura, HTML e URL), como seria no navegador:
    python scripts/verificar.py --modelo data/modelos/regressao \
        --imagem pagina.png --html pagina.html --url "http://paypal-conta.example/"

O conjunto de teste só é lido com --usar-teste: ele é usado uma única vez, na avaliação (etapa 6).

Desenho: docs/especificacoes/2026-11-22-cascata.md, seção 9.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from mhf import base as base_mod  # noqa: E402
from mhf import cascata, divisao, marcas, metricas  # noqa: E402
from mhf.conjuntos import carregar_conjunto  # noqa: E402

_MOTIVOS = {"sem_template_proximo": "nenhum template parecido (pHash)",
            "dominio_legitimo_estagio1": "domínio legítimo da marca mais parecida (pHash)",
            "abaixo_do_limiar": "escore abaixo do limiar",
            "dominio_legitimo_estagio2": "domínio legítimo da marca de maior escore",
            "phishing": "parece a marca e o domínio não é dela"}


def _real(c, i):
    m = c["meta"][i]
    if c["phishing_T"][i]:
        return f"phishing de {m['entidade']}"
    if c["fora_T"][i]:
        return "phishing (marca fora da base)" if m.get("marca") else "phishing (sem marca)"
    return "legítima"


def verificar_tabela(a, p, b, tabela, info, modelo):
    div = divisao.ler_divisao(a.divisao)
    if a.ids:
        c = carregar_conjunto(a.tabelas, div, b, tabela, None, info["caracteristicas"]["nomes"])
        posicao = {m["id"]: i for i, m in enumerate(c["meta"])}
        faltando = [i for i in a.ids if i not in posicao]
        if faltando:
            p.error(f"ids fora das tabelas ou excluídos: {', '.join(faltando)}")
        sel = np.array([posicao[i] for i in a.ids])
        if not a.usar_teste and any(c["meta"][i]["conjunto"] == divisao.TESTE for i in sel):
            p.error("há ids do conjunto de teste; use --usar-teste se for mesmo a avaliação final")
    else:
        if a.conjunto == divisao.TESTE and not a.usar_teste:
            p.error("o conjunto de teste é usado uma vez, na etapa 6; use --usar-teste para lê-lo")
        c = carregar_conjunto(a.tabelas, div, b, tabela, a.conjunto, info["caracteristicas"]["nomes"])
        rng = np.random.default_rng(a.semente)
        sel = np.sort(rng.choice(len(c["meta"]), size=min(a.amostras, len(c["meta"])), replace=False))

    cal = info["cascata"]
    escores = cascata.pontuar_amostras(modelo, c["X"][sel])
    r = cascata.aplicar_cascata(c["d1"][sel], c["t1"][sel], escores, c["legit"][sel], cal["theta_h"], cal["tau"])
    print(f"Detector: {modelo.tipo} | θ_h = {cal['theta_h']} bits | τ = {cal['tau']:.4f} | {len(sel)} amostras")
    if any(c["meta"][i]["conjunto"] == divisao.DESENVOLVIMENTO for i in sel):
        print("Atenção: o detector final foi treinado com todo o desenvolvimento; nessas amostras o veredito "
              "confere o funcionamento, mas não mede o desempenho (para isso: comparacao_dev.md e, na etapa 6, "
              "o teste).")
    print()
    print("| Amostra | Real | Veredito | Estágio | Motivo | Escore | Mais parecida pelo pHash (d₁) |")
    print("|---|---|---|---|---|---|---|")
    for k, i in enumerate(sel):
        e = int(r["entidade"][k])
        veredito = f"phishing de {c['entidades'][e]}" if r["phishing"][k] else "legítima"
        escore = "—" if np.isnan(r["escore"][k]) else f"{r['escore'][k]:.3f}"
        print(f"| {c['meta'][i]['id']} | {_real(c, i)} | {veredito} | {int(r['estagio'][k])} | "
              f"{_MOTIVOS[r['motivo'][k]]} | {escore} | {c['entidades'][int(c['t1'][i])]} ({int(c['d1'][i])}) |")
    binario = c["phishing_T"][sel] | c["legitima"][sel]
    if binario.any():
        m = metricas.binarias(c["phishing_T"][sel][binario], r["phishing"][binario])
        print(f"\nNas {int(binario.sum())} amostras de phishing de marcas da base ou legítimas: "
              f"{int(m['vp'])} phishings detectados de {int(m['vp'] + m['fn'])}, "
              f"{int(m['fp'])} alertas falsos em {int(m['fp'] + m['vn'])} legítimas.")


def verificar_pagina(a, b, tabela):
    det = cascata.Detector.carregar(a.modelo, b, tabela)
    html = None
    if a.html:
        with open(a.html, "rb") as f:
            html = f.read()
    v = det.analisar_pagina(a.imagem, html, a.url, classe=a.classe)
    veredito = f"PHISHING de {v.entidade}" if v.rotulo == "phishing" else "legítima"
    print(f"Veredito: {veredito}")
    print(f"  estágio {v.estagio}: {_MOTIVOS[v.motivo]}")
    print(f"  domínio da página: {v.dominio or '(sem domínio)'}")
    print(f"  template mais parecido pelo pHash: {v.template_proximo_h} ({v.entidade_proxima_h}), "
          f"d₁ = {v.d1} bits (θ_h = {det.theta_h})")
    if v.escores:
        top = sorted(v.escores.items(), key=lambda x: -x[1])[:3]
        print(f"  escores (τ = {det.tau:.4f}): " + ", ".join(f"{e} {s:.3f}" for e, s in top))
    print("  tempo (ms): " + ", ".join(f"{k} {ms:.1f}" for k, ms in v.tempos_ms.items()))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--modelo", default="data/modelos/regressao", help="pasta de um detector salvo por treinar.py")
    p.add_argument("--base", default="data/base")
    p.add_argument("--marcas", default="config/marcas.json")
    g = p.add_argument_group("amostras das tabelas")
    g.add_argument("--tabelas", nargs="+")
    g.add_argument("--divisao", default="data/divisao.csv")
    g.add_argument("--ids", nargs="+")
    g.add_argument("--amostras", type=int, default=20)
    g.add_argument("--conjunto", default=divisao.DESENVOLVIMENTO, choices=[divisao.DESENVOLVIMENTO, divisao.TESTE])
    g.add_argument("--semente", type=int, default=0)
    g.add_argument("--usar-teste", action="store_true")
    g2 = p.add_argument_group("página bruta")
    g2.add_argument("--imagem")
    g2.add_argument("--html")
    g2.add_argument("--url", default="")
    g2.add_argument("--classe")
    a = p.parse_args()

    b = base_mod.Base.carregar(a.base)
    tabela = marcas.ler_tabela(a.marcas)
    if a.imagem:
        verificar_pagina(a, b, tabela)
    elif a.tabelas:
        modelo, info = cascata.carregar_modelo(a.modelo)
        verificar_tabela(a, p, b, tabela, info, modelo)
    else:
        p.error("use --tabelas (amostras das tabelas) ou --imagem (página bruta)")


if __name__ == "__main__":
    main()
