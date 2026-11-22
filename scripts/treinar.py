"""
Passo 5b — treina e calibra a cascata no conjunto de desenvolvimento e compara regressão logística e
Random Forest na validação cruzada agrupada.

Uso:
    python scripts/treinar.py \
        --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign \
        --divisao data/divisao.csv --base data/base --marcas config/marcas.json --saida data/modelos

Passos:
1. Monta as características de cada par (amostra, entidade) a partir das tabelas de similaridades.
2. Validação cruzada nas 5 dobras do desenvolvimento: cada amostra é pontuada pelo modelo que não a viu.
3. Calibra θ_h (estágio 1) e τ (estágio 2) sobre esses escores e mede a cascata em cada dobra.
4. Treina os detectores finais com todo o desenvolvimento e grava <saida>/<modelo>/modelo.json (e
   floresta.joblib), mais <saida>/comparacao_dev.{md,json}.
O conjunto de teste não é lido.

Desenho: docs/especificacoes/2026-11-22-cascata.md
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from importlib import metadata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from mhf import base as base_mod  # noqa: E402
from mhf import cascata, divisao, marcas, metricas  # noqa: E402
from mhf.conjuntos import carregar_conjunto, nome_do_dataset  # noqa: E402,F401

MODELOS = {"regressao": cascata.RegressaoLogistica, "floresta": cascata.Floresta, "boosting": cascata.Boosting}


def pares_de_treino(c, mascara):
    """Pares (amostra, entidade) das amostras em `mascara`: sem entidade ausente da classe e sem o par de
    uma página no domínio legítimo da própria entidade. Rótulo: a amostra é phishing dessa entidade. Peso:
    o da estrutura, com positivos e negativos somando o mesmo total (média 1)."""
    X = c["X"][mascara]
    n, e, _ = X.shape
    y = c["entidade_real"][mascara][:, None] == np.array(c["entidades"], dtype=object)[None, :]
    validos = ~np.isnan(X).any(axis=2) & ~c["legit"][mascara]
    w = np.broadcast_to(c["pesos"][mascara][:, None], (n, e))[validos].astype(float)
    y = y[validos].astype(bool)
    if y.any() and (~y).any():
        w = np.where(y, w * (w[~y].sum() / w[y].sum()), w)
    return X[validos], y, w / w.mean()


# ---------------------------------------------------------------- treino e calibração

def treinar_modelo(tipo, c, mascara, iteracoes=150, **floresta):
    """`floresta`: arvores, n_jobs, profundidade e folha do Random Forest; `iteracoes`: do boosting."""
    X, y, w = pares_de_treino(c, mascara)
    if tipo == "regressao":
        return cascata.RegressaoLogistica.treinar(X, y, w, c["nomes"])
    if tipo == "boosting":
        return cascata.Boosting.treinar(X, y, w, c["nomes"], iteracoes=iteracoes)
    return cascata.Floresta.treinar(X, y, w, c["nomes"], **floresta)


def escores_fora_da_dobra(c, tipo, progresso=print, **floresta):
    """Escores (amostras, entidades) em que cada amostra é pontuada pelo modelo treinado sem a dobra dela."""
    escores = np.full(c["X"].shape[:2], np.nan)
    for k in sorted(set(c["dobra"].tolist()) - {-1}):
        t = time.perf_counter()
        modelo = treinar_modelo(tipo, c, (c["dobra"] != k) & (c["dobra"] >= 0), **floresta)
        alvo = c["dobra"] == k
        escores[alvo] = cascata.pontuar_amostras(modelo, c["X"][alvo])
        progresso(f"  {tipo}: dobra {k} ({time.perf_counter() - t:.0f} s)")
    return escores


def calibrar(c, escores, alvo_fpr=0.01, alvo_rev1=0.99, estagio1="nenhum"):
    """τ: menor limiar com FPR ≤ `alvo_fpr` nas páginas legítimas, por amostra, com a decisão completa;
    também o τ que maximiza o F1. Com `estagio1="phash"`, também θ_h: percentil `alvo_rev1` de d₁ nos
    phishings de 𝒯 (pelo menos essa fração chega ao classificador), e θ_h para 95% e 90%. Com "nenhum"
    (padrão), θ_h = None: toda página vai ao classificador."""
    if estagio1 == "nenhum":
        r = cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], None, -np.inf)
        sinalizada, legit = r["phishing"], c["legitima"]
        tau = metricas.limiar_para_fpr(r["escore"][sinalizada & legit],
                                       np.ones(int((sinalizada & legit).sum())), float(legit.sum()), alvo_fpr)
        alvo_f1 = sinalizada & (legit | c["phishing_T"])
        tau_f1 = metricas.limiar_f1(r["escore"][alvo_f1], c["phishing_T"][alvo_f1],
                                    np.ones(int(alvo_f1.sum())), float(c["phishing_T"].sum()))
        return {"estagio1": "nenhum", "theta_h": None, "tau": float(tau), "tau_f1": float(tau_f1),
                "alvo_fpr": alvo_fpr}
    d1_phish = c["d1"][c["phishing_T"]]
    theta = {a: int(np.quantile(d1_phish, a, method="higher")) for a in (alvo_rev1, 0.95, 0.90)}
    theta_h = theta[alvo_rev1]
    r = cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], theta_h, -np.inf)
    sinalizada = r["phishing"]  # com τ = −∞: o que o limiar ainda pode segurar
    legit = c["legitima"]
    tau = metricas.limiar_para_fpr(r["escore"][sinalizada & legit], np.ones(int((sinalizada & legit).sum())),
                                   float(legit.sum()), alvo_fpr)
    alvo_f1 = sinalizada & (legit | c["phishing_T"])
    tau_f1 = metricas.limiar_f1(r["escore"][alvo_f1], c["phishing_T"][alvo_f1],
                                np.ones(int(alvo_f1.sum())), float(c["phishing_T"].sum()))
    def liberadas(th):  # fração das legítimas que o estágio 1 já libera com esse θ_h
        r1 = cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], th, -np.inf)
        return float(((r1["estagio"] == 1) & legit).sum() / max(legit.sum(), 1))
    return {"estagio1": "phash", "theta_h": theta_h, "tau": float(tau), "tau_f1": float(tau_f1), "alvo_fpr": alvo_fpr,
            "alvo_revocacao_estagio1": alvo_rev1, "theta_h_95": theta[0.95], "theta_h_90": theta[0.90],
            "fracao_legitimas_liberadas_estagio1": liberadas(theta_h),
            "fracao_legitimas_liberadas_estagio1_95": liberadas(theta[0.95]),
            "fracao_legitimas_liberadas_estagio1_90": liberadas(theta[0.90])}


def metricas_cascata(c, escores, theta_h, tau, mascara=None):
    """Métricas da cascata no subconjunto `mascara`, por amostra e por estrutura (pesos 1/grupo)."""
    m = np.ones(len(c["d1"]), dtype=bool) if mascara is None else mascara
    r = cascata.aplicar_cascata(c["d1"][m], c["t1"][m], escores[m], c["legit"][m], theta_h, tau)
    pt, legit, fora = c["phishing_T"][m], c["legitima"][m], c["fora_T"][m]
    binario = pt | legit
    esc_max = np.nan_to_num(np.nanmax(np.nan_to_num(escores[m], nan=-1.0), axis=1), nan=0.0)
    melhor = np.argmax(np.nan_to_num(escores[m], nan=-np.inf), axis=1)
    ent = np.array(c["entidades"], dtype=object)
    real = c["entidade_real"][m]
    saida = {}
    for nome, pesos in (("por_amostra", np.ones(int(m.sum()))), ("por_estrutura", c["pesos"][m])):
        b = metricas.binarias(pt[binario], r["phishing"][binario], pesos[binario])
        det = pt & r["phishing"]
        saida[nome] = {**{k: b[k] for k in ("precisao", "revocacao", "f1", "fpr", "especificidade")},
                       "auc": metricas.auc(pt[binario], esc_max[binario], pesos[binario]),
                       "top1": metricas.top1(real[pt], ent[melhor[pt]], pesos[pt]),
                       "top1_detectados": metricas.top1(real[det], ent[r["entidade"][det]], pesos[det])
                       if det.any() else float("nan"),
                       "fora_T_sinalizado": float((pesos[fora] * r["phishing"][fora]).sum() / pesos[fora].sum())
                       if fora.any() else float("nan"),
                       "legitimas_liberadas_estagio1": float((pesos[legit] * (r["estagio"][legit] == 1)).sum()
                                                             / pesos[legit].sum()) if legit.any() else float("nan"),
                       "phishing_T_no_estagio2": float((pesos[pt] * (r["estagio"][pt] == 2)).sum()
                                                       / pesos[pt].sum()) if pt.any() else float("nan")}
    saida["n"] = {"phishing_T": int(pt.sum()), "legitimas": int(legit.sum()), "fora_T": int(fora.sum())}
    return saida


def _media_desvio(dobras, chave, campo):
    v = np.array([d[chave][campo] for d in dobras], dtype=float)
    if np.isnan(v).all():
        return float("nan"), float("nan")
    return float(np.nanmean(v)), float(np.nanstd(v))


def _tempo_por_pagina(modelo, X, n=300):
    """Mediana, em µs, de pontuar uma página (todas as entidades), uma de cada vez."""
    tempos = []
    for i in range(min(n, len(X))):
        t = time.perf_counter()
        cascata.pontuar_amostras(modelo, X[i:i + 1])
        tempos.append((time.perf_counter() - t) * 1e6)
    return float(np.median(tempos)) if tempos else float("nan")


def _tamanho(pasta):
    return sum(os.path.getsize(os.path.join(pasta, f)) for f in os.listdir(pasta))


def _versoes():
    def v(p):
        try:
            return metadata.version(p)
        except metadata.PackageNotFoundError:
            return None
    return {p: v(p) for p in ("numpy", "scikit-learn", "joblib")}


# ---------------------------------------------------------------- relatório

_CAMPOS = (("auc", "AUC do classificador"), ("revocacao", "Revocação"), ("precisao", "Precisão"), ("f1", "F1"),
           ("fpr", "FPR"), ("top1", "Top-1 da marca (do classificador)"),
           ("top1_detectados", "Top-1 nos phishings detectados"),
           ("phishing_T_no_estagio2", "Phishing de 𝒯 que chega ao estágio 2"),
           ("legitimas_liberadas_estagio1", "Legítimas liberadas no estágio 1"),
           ("fora_T_sinalizado", "Phishing fora de 𝒯 sinalizado"))


def _tabela_unica(titulo, por_modelo, nota=""):
    """Tabela métrica × modelo de um único resultado (sem dobras), por amostra e por estrutura."""
    tipos = list(por_modelo)
    linhas = [f"## {titulo}", ""] + ([nota, ""] if nota else [])
    linhas += ["| Métrica | " + " | ".join(f"{t} (amostra)" for t in tipos) + " | "
               + " | ".join(f"{t} (estrutura)" for t in tipos) + " |", "|---|" + "---|" * (2 * len(tipos))]
    for campo, rotulo in _CAMPOS:
        cel = [f"{por_modelo[t][k][campo]:.3f}" for k in ("por_amostra", "por_estrutura") for t in tipos]
        linhas.append(f"| {rotulo} | " + " | ".join(cel) + " |")
    return linhas + [""]


def relatorio_md(comp):
    tipos = list(comp["modelos"])
    linhas = ["# Comparação na validação cruzada (desenvolvimento)", "",
              f"Gerado em {comp['gerado_em']}. Características: {', '.join(comp['nomes'])}. "
              f"Amostras: {comp['n']['phishing_T']} phishings de 𝒯, {comp['n']['legitimas']} legítimas, "
              f"{comp['n']['fora_T']} phishings fora de 𝒯. Estágio 1: {comp.get('estagio1', 'phash')}. "
              "Média ± desvio entre as 5 dobras; θ_h (se houver estágio 1) e τ calibrados "
              "sobre os escores fora da dobra de cada modelo, com um τ só para todas as dobras (por isso a FPR "
              "fica perto do alvo por construção, e o desvio não inclui a variação do limiar). AUC e top-1 "
              "medem o classificador sozinho (escore máximo e entidade de maior escore), sem o estágio 1 nem a "
              "checagem de domínio.", ""]
    for chave, titulo in (("por_amostra", "Por amostra"), ("por_estrutura", "Por estrutura (cada kit conta uma vez)")):
        linhas += [f"## {titulo}", "", "| Métrica | " + " | ".join(tipos) + " |",
                   "|---|" + "---|" * len(tipos)]
        for campo, rotulo in _CAMPOS:
            cel = []
            for t in tipos:
                m, d = _media_desvio(comp["modelos"][t]["dobras"], chave, campo)
                cel.append(f"{m:.3f} ± {d:.3f}")
            linhas.append(f"| {rotulo} | " + " | ".join(cel) + " |")
        linhas.append("")
    linhas += _tabela_unica("No τ que maximiza o F1 (todas as dobras juntas)",
                            {t: comp["modelos"][t]["geral_tau_f1"] for t in tipos},
                            "Mesmos escores fora da dobra, com o τ que maximiza o F1 em vez do alvo de FPR.")
    for chave, titulo in (("com_s", "Amostras com DOM útil (s presente)"),
                          ("sem_s", "Amostras sem DOM útil (s ausente: sem HTML ou ≤ 5 elementos)")):
        if all(chave in comp["modelos"][t]["por_s_ausente"] for t in tipos):
            linhas += _tabela_unica(titulo, {t: comp["modelos"][t]["por_s_ausente"][chave] for t in tipos},
                                    "O s ausente é muito mais comum nas legítimas (Phishpedia benign sem HTML) que "
                                    "no phishing: estas linhas mostram se o classificador depende disso.")
    linhas += ["## Por dataset (escores fora da dobra, todas as dobras juntas, por amostra)", "",
               "| Dataset | Modelo | AUC | Revocação | FPR | Top-1 |", "|---|---|---|---|---|---|"]
    for t in tipos:
        for ds, m in comp["modelos"][t]["por_dataset"].items():
            a = m["por_amostra"]
            linhas.append(f"| {ds} | {t} | {a['auc']:.3f} | {a['revocacao']:.3f} | {a['fpr']:.3f} | {a['top1']:.3f} |")
    linhas += ["", "## Calibração e custo", "", "| | " + " | ".join(tipos) + " |", "|---|" + "---|" * len(tipos)]
    for campo, rotulo in (("theta_h", "θ_h (bits)"), ("tau", "τ (FPR ≤ alvo)"), ("tau_f1", "τ que maximiza o F1"),
                          ("theta_h_95", "θ_h para 95%"), ("theta_h_90", "θ_h para 90%"),
                          ("fracao_legitimas_liberadas_estagio1", "Legítimas liberadas no estágio 1"),
                          ("fracao_legitimas_liberadas_estagio1_95", "Legítimas liberadas no estágio 1 (θ_h de 95%)"),
                          ("fracao_legitimas_liberadas_estagio1_90", "Legítimas liberadas no estágio 1 (θ_h de 90%)")):
        valores = [comp["modelos"][t]["calibracao"].get(campo) for t in tipos]
        if all(v is None for v in valores):
            continue
        linhas.append(f"| {rotulo} | " + " | ".join("—" if v is None else f"{v:.4g}" for v in valores) + " |")
    linhas.append("| Pontuar uma página (µs, mediana) | "
                  + " | ".join(f"{comp['modelos'][t]['tempo_us']:.0f}" for t in tipos) + " |")
    linhas.append("| Tamanho do modelo salvo (KB) | "
                  + " | ".join(f"{comp['modelos'][t]['tamanho_bytes'] / 1024:.1f}" for t in tipos) + " |")
    linhas += ["", "## Pesos de cada característica", "", "| Característica | Coeficiente (regressão, padronizado) | "
               "Importância (floresta) |", "|---|---|---|"]
    coef = comp["modelos"].get("regressao", {}).get("coef", {})
    imp = comp["modelos"].get("floresta", {}).get("importancias", {})
    for nome in comp["nomes"]:
        c = f"{coef[nome]:+.3f}" if nome in coef else "—"
        i = f"{imp[nome]:.3f}" if nome in imp else "—"
        linhas.append(f"| {nome} | {c} | {i} |")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--tabelas", nargs="+", required=True)
    p.add_argument("--divisao", default="data/divisao.csv")
    p.add_argument("--base", default="data/base")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--saida", default="data/modelos")
    p.add_argument("--sinais", default="h,e,s")
    p.add_argument("--hash", type=int, default=64, choices=[64, 256])
    p.add_argument("--embedding", default="small", choices=["small", "large"])
    p.add_argument("--alvo-fpr", type=float, default=0.01)
    p.add_argument("--alvo-revocacao-estagio1", type=float, default=0.99)
    p.add_argument("--modelos", default="regressao,floresta,boosting")
    p.add_argument("--estagio1", default="nenhum", choices=["nenhum", "phash"],
                   help="nenhum (padrão): toda página vai ao classificador; phash: filtro pelo pHash antes dele")
    p.add_argument("--arvores", type=int, default=100, help="Random Forest: número de árvores")
    p.add_argument("--profundidade", type=int, default=12, help="Random Forest: profundidade máxima (0 = sem)")
    p.add_argument("--folha", type=int, default=50, help="Random Forest: mínimo de amostras por folha")
    p.add_argument("--iteracoes", type=int, default=150, help="gradient boosting: número de árvores")
    p.add_argument("--n-jobs", type=int, default=4)
    a = p.parse_args()

    inicio = time.perf_counter()
    sinais = tuple(s for s in a.sinais.split(",") if s)
    nomes = cascata.nomes_caracteristicas(sinais, a.hash, a.embedding)
    tipos = [t for t in a.modelos.split(",") if t]
    if not set(tipos) <= set(MODELOS):
        p.error(f"--modelos deve conter só {sorted(MODELOS)}")
    b = base_mod.Base.carregar(a.base)
    tabela = marcas.ler_tabela(a.marcas)
    with open(a.divisao, "rb") as f:
        sha_divisao = hashlib.sha256(f.read()).hexdigest()
    c = carregar_conjunto(a.tabelas, divisao.ler_divisao(a.divisao), b, tabela, divisao.DESENVOLVIMENTO, nomes)
    print(f"Desenvolvimento: {len(c['meta'])} amostras ({int(c['phishing_T'].sum())} phishings de 𝒯, "
          f"{int(c['legitima'].sum())} legítimas, {int(c['fora_T'].sum())} fora de 𝒯); {len(nomes)} características",
          flush=True)

    comp = {"gerado_em": datetime.now().isoformat(timespec="seconds"), "nomes": nomes, "sinais": list(sinais),
            "estagio1": a.estagio1,
            "n": {"phishing_T": int(c["phishing_T"].sum()), "legitimas": int(c["legitima"].sum()),
                  "fora_T": int(c["fora_T"].sum())}, "modelos": {}}
    for tipo in tipos:
        floresta = {"arvores": a.arvores, "n_jobs": a.n_jobs, "profundidade": a.profundidade or None,
                    "folha": a.folha, "iteracoes": a.iteracoes}
        oof = escores_fora_da_dobra(c, tipo, progresso=lambda s: print(s, flush=True), **floresta)
        cal = calibrar(c, oof, a.alvo_fpr, a.alvo_revocacao_estagio1, a.estagio1)
        dobras = [metricas_cascata(c, oof, cal["theta_h"], cal["tau"], c["dobra"] == k)
                  for k in sorted(set(c["dobra"].tolist()))]
        grupos_ds = {"phish360": c["dataset"] == "phish360",
                     "phishpedia": np.char.startswith(c["dataset"].astype(str), "phishpedia")}
        por_ds = {ds: metricas_cascata(c, oof, cal["theta_h"], cal["tau"], mk) for ds, mk in grupos_ds.items()
                  if mk.any()}

        t = time.perf_counter()
        modelo = treinar_modelo(tipo, c, np.ones(len(c["d1"]), dtype=bool), **floresta)
        print(f"  {tipo}: modelo final ({time.perf_counter() - t:.0f} s)", flush=True)
        pasta = os.path.join(a.saida, tipo)
        extras = {"cascata": cal, "entidades": c["entidades"], "elementos_min_s": divisao.ELEMENTOS_MIN_S,
                  "caracteristicas": {"sinais": list(sinais), "hash_bits": a.hash, "embedding": a.embedding,
                                      "nomes": nomes},
                  "treino": {"amostras": len(c["meta"]), "phishing_T": int(c["phishing_T"].sum()),
                             "divisao_sha256": sha_divisao, "versoes": _versoes(),
                             "treinado_em": datetime.now().isoformat(timespec="seconds")},
                  "validacao": metricas_cascata(c, oof, cal["theta_h"], cal["tau"])}
        cascata.salvar_modelo(pasta, modelo, extras)
        s_aus = c["s_ausente"]
        por_s = {nome: metricas_cascata(c, oof, cal["theta_h"], cal["tau"], mk)
                 for nome, mk in (("com_s", ~s_aus), ("sem_s", s_aus)) if mk.any()}
        info = {"calibracao": cal, "dobras": dobras, "geral": extras["validacao"], "por_dataset": por_ds,
                "geral_tau_f1": metricas_cascata(c, oof, cal["theta_h"], cal["tau_f1"]), "por_s_ausente": por_s,
                "tempo_us": _tempo_por_pagina(modelo, c["X"]), "tamanho_bytes": _tamanho(pasta)}
        if tipo == "regressao":
            info["coef"] = dict(zip(nomes, modelo.coef.tolist()))
        elif tipo == "floresta":
            info["importancias"] = dict(zip(nomes, modelo.rf.feature_importances_.tolist()))
        comp["modelos"][tipo] = info
        g = extras["validacao"]["por_amostra"]
        print(f"  {tipo}: θ_h={cal['theta_h']} τ={cal['tau']:.4f} | AUC {g['auc']:.3f} revocação {g['revocacao']:.3f} "
              f"FPR {g['fpr']:.4f} top-1 {g['top1']:.3f}", flush=True)

    os.makedirs(a.saida, exist_ok=True)
    with open(os.path.join(a.saida, "comparacao_dev.json"), "w", encoding="utf-8") as f:
        json.dump(comp, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.saida, "comparacao_dev.md"), "w", encoding="utf-8") as f:
        f.write(relatorio_md(comp))
    print(f"Comparação em {os.path.join(a.saida, 'comparacao_dev.md')} ({time.perf_counter() - inicio:.0f} s)")


if __name__ == "__main__":
    main()
