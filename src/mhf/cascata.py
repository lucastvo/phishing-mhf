"""
Cascata e regra de decisão (etapa 5): f(φ(w)) → {legítima} ∪ 𝒯.

Estágio 1 (barato): d₁ = menor distância de Hamming (pHash de 64 bits) entre a página e os templates da sua
classe de tela; t₁ = entidade desse template. A página é liberada se d₁ > θ_h (nenhum template visualmente
próximo) ou se o domínio dela é um domínio legítimo de t₁.

Estágio 2: para cada entidade de 𝒯, o máximo de cada sinal (h, e, s) sobre os templates dela vira um vetor
de características; um classificador treinado (regressão logística ou Random Forest) dá um escore por
entidade. t* = entidade de maior escore. Abaixo de τ → legítima; domínio legítimo de t* → legítima;
senão → phishing de t*.

A mesma função (`aplicar_cascata`) decide a partir da tabela de similaridades (treino e avaliação) e a
partir de uma página nova (`Detector`), para que as duas façam exatamente a mesma conta.

Desenho: docs/especificacoes/2026-11-22-cascata.md
"""

import json
import os
import warnings

import numpy as np

from mhf import marcas
from mhf.divisao import s_util  # noqa: F401  (regra do s ausente, reexportada para quem usa a cascata)

SINAIS_S = ("jaccard_caminhos", "jaccard_criticos", "sim_contagens", "hash_igual")
MOTIVOS = ("sem_template_proximo", "dominio_legitimo_estagio1", "abaixo_do_limiar", "dominio_legitimo_estagio2",
           "phishing")


# ---------------------------------------------------------------- características

def nomes_caracteristicas(sinais=("h", "e", "s"), hash_bits=64, embedding="small"):
    """Nomes das características do estágio 2, na ordem das colunas do classificador."""
    if not set(sinais) <= {"h", "e", "s"} or not sinais:
        raise ValueError("sinais deve ser um subconjunto não vazio de {'h', 'e', 's'}")
    if hash_bits not in (64, 256) or embedding not in ("small", "large"):
        raise ValueError("hash_bits deve ser 64 ou 256 e embedding 'small' ou 'large'")
    nomes = []
    if "h" in sinais:
        nomes.append(f"sim_h{hash_bits}")
    if "e" in sinais:
        nomes.append(f"cos_{embedding}")
    if "s" in sinais:
        nomes += [*SINAIS_S, "s_ausente"]
    return nomes


def sinais_da_tabela(z, classe):
    """Matrizes amostras × templates de uma classe do .npz de similaridades.py, com as similaridades de
    Hamming calculadas a partir das distâncias e tudo em float32 (a tabela guarda float16)."""
    s = {"dist_h64": z[f"{classe}__dist_h64"].astype(np.int64)}
    s["sim_h64"] = (1 - s["dist_h64"] / 64).astype(np.float32)
    s["sim_h256"] = (1 - z[f"{classe}__dist_h256"].astype(np.float32) / 256).astype(np.float32)
    for k in ("cos_small", "cos_large", *SINAIS_S):
        s[k] = z[f"{classe}__{k}"].astype(np.float32)
    return s


def sinais_da_busca(r):
    """Os mesmos sinais a partir de Base.similaridades de uma página (matrizes 1 × templates)."""
    s = {}
    for k in ("dist_h64", "sim_h64", "sim_h256", "cos_small", "cos_large", *SINAIS_S):
        if k in r:
            s[k] = np.asarray(r[k])[None, :]
    return s


def caracteristicas(sinais, entidades_colunas, entidades, s_ausente, nomes):
    """Tensor (amostras, entidades, características): para cada entidade, o máximo de cada sinal sobre os
    templates dela (sinais separados: o melhor pHash e o melhor cosseno podem vir de templates diferentes).
    Entidade sem template na classe → linha NaN (não disputa a decisão). Amostra com s ausente → as
    características de s valem 0 e `s_ausente` vale 1."""
    s_ausente = np.asarray(s_ausente, dtype=bool)
    entidades_colunas = np.asarray(entidades_colunas)
    n = len(s_ausente)
    X = np.full((n, len(entidades), len(nomes)), np.nan, dtype=np.float32)
    for e, ent in enumerate(entidades):
        cols = np.flatnonzero(entidades_colunas == ent)
        if cols.size == 0:
            continue
        for f, nome in enumerate(nomes):
            if nome == "s_ausente":
                X[:, e, f] = s_ausente
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # linha toda NaN → NaN
                m = np.nanmax(np.asarray(sinais[nome][:, cols], dtype=np.float32), axis=1)
            if nome in SINAIS_S:
                m = np.where(s_ausente, 0.0, np.nan_to_num(m, nan=0.0))
            X[:, e, f] = m
    return X


def estagio1(dist_h64, entidades_colunas, entidades):
    """d₁ (menor distância de Hamming) e o índice em `entidades` da entidade desse template (empate: a
    primeira coluna, que é a ordem da base)."""
    dist_h64 = np.asarray(dist_h64)
    j = np.argmin(dist_h64, axis=1)
    indice = {e: i for i, e in enumerate(entidades)}
    t1 = np.array([indice[entidades_colunas[k]] for k in j], dtype=np.int64)
    return dist_h64[np.arange(len(j)), j], t1


def matriz_dominio_legitimo(urls, entidades, tabela):
    """(amostras, entidades): o domínio registrável da URL é legítimo para a entidade? Aceita host sem
    esquema (no Phishpedia benign sem URL, o nome da pasta é o domínio)."""
    dominios = {t["entidade"]: {d.lower() for d in t["dominios"]} for t in tabela}
    legit = np.zeros((len(urls), len(entidades)), dtype=bool)
    for n, url in enumerate(urls):
        dom = marcas.dominio_registravel(url or "")
        if dom:
            legit[n] = [dom in dominios.get(e, ()) for e in entidades]
    return legit


def aplicar_cascata(d1, t1, escores, legit, theta_h, tau):
    """Decisão da cascata para N amostras. Devolve phishing (bool), entidade (índice; −1 se liberada no
    estágio 1 por falta de template próximo), estágio (1 ou 2), motivo e escore (NaN no estágio 1)."""
    d1, t1 = np.asarray(d1), np.asarray(t1)
    escores = np.asarray(escores, dtype=float)
    n = len(d1)
    sem_proximo = d1 > theta_h
    dom1 = ~sem_proximo & legit[np.arange(n), t1]
    estagio2 = ~sem_proximo & ~dom1
    melhor = np.argmax(np.nan_to_num(escores, nan=-np.inf), axis=1) if escores.size else np.zeros(n, int)
    escore_melhor = escores[np.arange(n), melhor] if escores.size else np.full(n, np.nan)
    abaixo = estagio2 & ~(escore_melhor >= tau)  # NaN conta como abaixo
    dom2 = estagio2 & ~abaixo & legit[np.arange(n), melhor]
    phishing = estagio2 & ~abaixo & ~dom2

    motivo = np.select([sem_proximo, dom1, abaixo, dom2], list(MOTIVOS[:4]), default="phishing").tolist()
    entidade = np.where(sem_proximo, -1, np.where(dom1, t1, melhor))
    return {"phishing": phishing, "entidade": entidade.astype(np.int64),
            "estagio": np.where(estagio2, 2, 1), "motivo": motivo,
            "escore": np.where(estagio2, escore_melhor, np.nan)}


# ---------------------------------------------------------------- modelos

class RegressaoLogistica:
    """StandardScaler + regressão logística (L2). Pontua em numpy puro, a partir dos números salvos."""
    tipo = "regressao"

    def __init__(self, nomes, media, escala, coef, intercepto):
        self.nomes = list(nomes)
        self.media = np.asarray(media, dtype=float)
        self.escala = np.asarray(escala, dtype=float)
        self.coef = np.asarray(coef, dtype=float)
        self.intercepto = float(intercepto)

    @classmethod
    def treinar(cls, X, y, pesos, nomes, C=1.0):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        esc = StandardScaler().fit(X, sample_weight=pesos)
        lr = LogisticRegression(C=C, max_iter=1000).fit(esc.transform(X), y, sample_weight=pesos)
        return cls(nomes, esc.mean_, esc.scale_, lr.coef_[0], lr.intercept_[0])

    def pontuar(self, X):
        z = (np.asarray(X, dtype=float) - self.media) / self.escala
        return 1.0 / (1.0 + np.exp(-(z @ self.coef + self.intercepto)))

    def para_dict(self):
        return {"tipo": self.tipo, "nomes": self.nomes, "media": self.media.tolist(),
                "escala": self.escala.tolist(), "coef": self.coef.tolist(), "intercepto": self.intercepto}

    @classmethod
    def de_dict(cls, d, pasta=None):
        return cls(d["nomes"], d["media"], d["escala"], d["coef"], d["intercepto"])


class Floresta:
    """Random Forest do scikit-learn, salva com joblib (arquivo gerado pelo próprio projeto)."""
    tipo = "floresta"
    arquivo = "floresta.joblib"

    def __init__(self, nomes, rf):
        self.nomes = list(nomes)
        self.rf = rf

    @classmethod
    def treinar(cls, X, y, pesos, nomes, arvores=300, n_jobs=4, semente=0):
        from sklearn.ensemble import RandomForestClassifier
        rf = RandomForestClassifier(n_estimators=arvores, min_samples_leaf=20, max_features="sqrt",
                                    n_jobs=n_jobs, random_state=semente)
        rf.fit(X, y, sample_weight=pesos)
        return cls(nomes, rf)

    def pontuar(self, X):
        return self.rf.predict_proba(np.asarray(X, dtype=np.float32))[:, 1]

    def para_dict(self):
        return {"tipo": self.tipo, "nomes": self.nomes, "arquivo": self.arquivo,
                "arvores": self.rf.n_estimators, "importancias": self.rf.feature_importances_.tolist()}

    @classmethod
    def de_dict(cls, d, pasta):
        import joblib
        return cls(d["nomes"], joblib.load(os.path.join(pasta, d["arquivo"])))


_MODELOS = {c.tipo: c for c in (RegressaoLogistica, Floresta)}


def salvar_modelo(pasta, modelo, extras):
    """Grava <pasta>/modelo.json ({"modelo": ..., **extras}) e, na floresta, <pasta>/floresta.joblib."""
    os.makedirs(pasta, exist_ok=True)
    if isinstance(modelo, Floresta):
        import joblib
        joblib.dump(modelo.rf, os.path.join(pasta, Floresta.arquivo))
    with open(os.path.join(pasta, "modelo.json"), "w", encoding="utf-8") as f:
        json.dump({"modelo": modelo.para_dict(), **extras}, f, ensure_ascii=False, indent=2)


def carregar_modelo(pasta):
    """(modelo, demais campos do modelo.json)."""
    with open(os.path.join(pasta, "modelo.json"), encoding="utf-8") as f:
        d = json.load(f)
    info = d.pop("modelo")
    return _MODELOS[info["tipo"]].de_dict(info, pasta), d


def pontuar_amostras(modelo, X):
    """Escores (amostras, entidades) de um tensor de características; NaN onde a entidade não tem template."""
    n, e, f = X.shape
    plano = X.reshape(n * e, f)
    validos = ~np.isnan(plano).any(axis=1)
    escores = np.full(n * e, np.nan)
    if validos.any():
        escores[validos] = modelo.pontuar(plano[validos])
    return escores.reshape(n, e)
