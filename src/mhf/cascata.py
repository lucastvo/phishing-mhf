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
import time
import warnings
from dataclasses import dataclass, field

import numpy as np

from mhf import marcas
from mhf.divisao import s_util

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
    Entidade sem template na classe → linha NaN (não disputa a decisão); o mesmo vale, amostra a amostra,
    quando todos os templates dela foram filtrados (sim_h64 NaN em todas as colunas da entidade). Amostra
    com s ausente → as características de s valem 0 e `s_ausente` vale 1."""
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
        if "sim_h64" in sinais:  # templates filtrados para a amostra (ex.: base de 2026): marca fora da disputa
            sem_template = np.isnan(np.asarray(sinais["sim_h64"][:, cols], dtype=np.float32)).all(axis=1)
            X[sem_template, e, :] = np.nan
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
    estágio 1 por falta de template próximo), estágio (1 ou 2), motivo e escore (NaN no estágio 1).
    Com theta_h = None não há estágio 1: toda página vai ao classificador, e a checagem de domínio vale só
    para a marca atribuída por ele."""
    d1, t1 = np.asarray(d1), np.asarray(t1)
    escores = np.asarray(escores, dtype=float)
    n = len(d1)
    if theta_h is None:
        sem_proximo = dom1 = np.zeros(n, dtype=bool)
    else:
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
    def treinar(cls, X, y, pesos, nomes, arvores=300, n_jobs=4, semente=0, profundidade=None, folha=20):
        """`n_jobs` vale só para o treino: o modelo salvo pontua em 1 núcleo, como no uso real (uma página
        de cada vez, em que dividir 20 linhas entre núcleos custa mais do que pontuar)."""
        from sklearn.ensemble import RandomForestClassifier
        rf = RandomForestClassifier(n_estimators=arvores, min_samples_leaf=folha, max_depth=profundidade,
                                    max_features="sqrt", n_jobs=n_jobs, random_state=semente)
        rf.fit(X, y, sample_weight=pesos)
        rf.n_jobs = 1
        if hasattr(rf, "_sample_weight"):  # cópia dos pesos de treino (~8 MB): inútil para pontuar
            rf._sample_weight = None
        return cls(nomes, rf)

    def pontuar(self, X):
        return self.rf.predict_proba(np.asarray(X, dtype=np.float32))[:, 1]

    def para_dict(self):
        return {"tipo": self.tipo, "nomes": self.nomes, "arquivo": self.arquivo, "arvores": self.rf.n_estimators,
                "profundidade": self.rf.max_depth, "folha": self.rf.min_samples_leaf,
                "importancias": self.rf.feature_importances_.tolist()}

    @classmethod
    def de_dict(cls, d, pasta):
        import joblib
        return cls(d["nomes"], joblib.load(os.path.join(pasta, d["arquivo"])))


class Boosting:
    """Gradient boosting pequeno (HistGradientBoosting do scikit-learn), salvo com joblib. Poucas árvores
    rasas: o modelo cabe em centenas de KB e pontua uma página em ~1 ms."""
    tipo = "boosting"
    arquivo = "boosting.joblib"

    def __init__(self, nomes, gb):
        self.nomes = list(nomes)
        self.gb = gb

    @classmethod
    def treinar(cls, X, y, pesos, nomes, iteracoes=150, folhas=15, taxa=0.1, semente=0):
        from sklearn.ensemble import HistGradientBoostingClassifier
        gb = HistGradientBoostingClassifier(max_iter=iteracoes, max_leaf_nodes=folhas, learning_rate=taxa,
                                            random_state=semente)
        gb.fit(X, y, sample_weight=pesos)
        return cls(nomes, gb)

    def pontuar(self, X):
        return self.gb.predict_proba(np.asarray(X, dtype=np.float32))[:, 1]

    def para_dict(self):
        return {"tipo": self.tipo, "nomes": self.nomes, "arquivo": self.arquivo, "iteracoes": int(self.gb.n_iter_),
                "folhas": self.gb.max_leaf_nodes, "taxa": self.gb.learning_rate}

    @classmethod
    def de_dict(cls, d, pasta):
        import joblib
        return cls(d["nomes"], joblib.load(os.path.join(pasta, d["arquivo"])))


_MODELOS = {c.tipo: c for c in (RegressaoLogistica, Floresta, Boosting)}


def salvar_modelo(pasta, modelo, extras):
    """Grava <pasta>/modelo.json ({"modelo": ..., **extras}) e, na floresta e no boosting, o .joblib."""
    os.makedirs(pasta, exist_ok=True)
    if isinstance(modelo, (Floresta, Boosting)):
        import joblib
        joblib.dump(modelo.rf if isinstance(modelo, Floresta) else modelo.gb, os.path.join(pasta, modelo.arquivo))
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


# ---------------------------------------------------------------- uma página

@dataclass
class Veredito:
    """Decisão da cascata para uma página, com o que levou a ela."""
    rotulo: str                     # "phishing" ou "legitima"
    entidade: str | None            # marca imitada (phishing), a do domínio legítimo, ou a de maior escore
    estagio: int                    # 1 ou 2
    motivo: str                     # um de MOTIVOS
    escore: float | None            # escore da entidade no estágio 2 (None no estágio 1)
    d1: int                         # menor distância de Hamming (64 bits) a um template
    entidade_proxima_h: str         # entidade do template mais próximo pelo pHash
    template_proximo_h: str         # id desse template
    dominio: str                    # domínio registrável da URL da página
    tempos_ms: dict = field(default_factory=dict)
    escores: dict | None = None     # escore de cada entidade (estágio 2)
    detalhes: dict | None = None    # com detalhes=True: o que a interface mostra (ver Detector.decidir)


class Detector:
    """A cascata treinada, para uma página de cada vez (verificação, interface e, depois, a extensão).

    `decidir` recebe φ já calculada (ou parte dela: o estágio 1 só precisa do pHash de 64 bits);
    `analisar_pagina` recebe a página bruta e calcula o embedding e o s só se ela chegar ao estágio 2."""

    def __init__(self, base, modelo, info, tabela):
        self.base, self.modelo, self.tabela = base, modelo, tabela
        car = info["caracteristicas"]
        self.nomes, self.embedding, self.hash_bits = car["nomes"], car["embedding"], car["hash_bits"]
        if list(modelo.nomes) != list(self.nomes):
            raise ValueError("as características do modelo não batem com as do modelo.json")
        self.entidades = info["entidades"]
        self.theta_h, self.tau = info["cascata"].get("theta_h"), info["cascata"]["tau"]  # θ_h None: sem estágio 1
        self._embedder = None

    @classmethod
    def carregar(cls, pasta_modelo, base, tabela):
        modelo, info = carregar_modelo(pasta_modelo)
        return cls(base, modelo, info, tabela)

    def decidir(self, consulta, classe, url, elementos=None, completar=None, tempos=None, detalhes=False):
        """Veredito a partir de φ. `consulta` como em Base.similaridades; `elementos` é o tamanho do DOM
        (None: vem de consulta["s"], se houver). Se a página chegar ao estágio 2 e `completar` for dado, ele
        é chamado para acrescentar à consulta o que faltar (embedding, s, elementos), como no navegador.
        Se, no estágio 2, faltar à consulta um sinal que o modelo usa, levanta ValueError em vez de
        devolver "legítima" em silêncio.

        Com `detalhes=True`, o Veredito traz em `detalhes`, sem mudar a decisão: "caracteristicas"
        ({entidade: {nome: valor}}, o vetor que foi ao classificador), "melhor_template" ({entidade:
        {"indice", "id", "cosseno"}}, o template da entidade de maior cosseno do embedding na classe),
        "s_ausente" e "elementos". Entidade sem template na classe fica de fora; página liberada no
        estágio 1 fica com os dois dicionários vazios."""
        tempos = {} if tempos is None else tempos
        t = time.perf_counter()
        r = self.base.similaridades(consulta, classe, sinais=("h",))
        tempos["busca_h"] = (time.perf_counter() - t) * 1000
        if len(r["indices"]) == 0:
            raise ValueError(f"a base não tem templates na classe {classe}")
        colunas = np.array([self.base.itens[i]["entidade"] for i in r["indices"]])
        d1, t1 = estagio1(r["dist_h64"][None, :], colunas, self.entidades)
        legit = matriz_dominio_legitimo([url], self.entidades, self.tabela)
        escores = np.full((1, len(self.entidades)), np.nan)
        extra_detalhes = {"caracteristicas": {}, "melhor_template": {}, "s_ausente": None, "elementos": elementos}
        if self.theta_h is None or (d1[0] <= self.theta_h and not legit[0, t1[0]]):
            if completar is not None:
                extra = completar()
                consulta = {**consulta, **extra}
                elementos = extra.get("elementos", elementos)
            if elementos is None and consulta.get("s") is not None:
                elementos = consulta["s"].contagens.get("elementos")
            t = time.perf_counter()
            # de novo com h: o completar pode ter trazido o pHash de 256 bits
            r2 = self.base.similaridades(consulta, classe, sinais=("h", "e", "s"))
            tempos["busca_es"] = (time.perf_counter() - t) * 1000
            t = time.perf_counter()
            sinais = sinais_da_busca(r2)
            X = caracteristicas(sinais, colunas, self.entidades,
                                np.array([consulta.get("s") is None or not s_util(elementos)]), self.nomes)
            faltando = [n for f, n in enumerate(self.nomes) if np.isnan(X[0, :, f]).all()]
            if faltando:
                raise ValueError(f"a consulta não tem os sinais que o modelo usa: {', '.join(faltando)}")
            escores = pontuar_amostras(self.modelo, X)
            tempos["classificador"] = (time.perf_counter() - t) * 1000
            if detalhes:
                extra_detalhes = self._detalhes(X[0], colunas, r2, consulta, elementos)
        res = aplicar_cascata(d1, t1, escores, legit, self.theta_h, self.tau)
        j = int(np.argmin(r["dist_h64"]))
        e = int(res["entidade"][0])
        return Veredito(rotulo="phishing" if res["phishing"][0] else "legitima",
                        entidade=self.entidades[e] if e >= 0 else None, estagio=int(res["estagio"][0]),
                        motivo=res["motivo"][0],
                        escore=None if np.isnan(res["escore"][0]) else float(res["escore"][0]),
                        d1=int(d1[0]), entidade_proxima_h=self.entidades[int(t1[0])],
                        template_proximo_h=self.base.itens[int(r["indices"][j])]["id"],
                        dominio=marcas.dominio_registravel(url or ""), tempos_ms=tempos,
                        escores=None if np.isnan(escores).all() else
                        {ent: float(v) for ent, v in zip(self.entidades, escores[0]) if not np.isnan(v)},
                        detalhes=extra_detalhes if detalhes else None)

    def _detalhes(self, X, colunas, r, consulta, elementos):
        """O que decidir(detalhes=True) devolve: características por entidade e o template de maior cosseno."""
        caracteristicas, melhor = {}, {}
        cos = np.asarray(r[f"cos_{self.embedding}"], dtype=float)
        for k, ent in enumerate(self.entidades):
            if not (colunas == ent).any():
                continue
            caracteristicas[ent] = {n: float(X[k, f]) for f, n in enumerate(self.nomes)}
            cols = np.flatnonzero((colunas == ent) & ~np.isnan(cos))
            if len(cols):
                j = int(cols[np.argmax(cos[cols])])
                indice = int(r["indices"][j])
                melhor[ent] = {"indice": indice, "id": self.base.itens[indice]["id"], "cosseno": float(cos[j])}
        return {"caracteristicas": caracteristicas, "melhor_template": melhor,
                "s_ausente": bool(consulta.get("s") is None or not s_util(elementos)), "elementos": elementos}

    def analisar_pagina(self, imagem, html, url, classe=None, embedder=None, detalhes=False):
        """Veredito para uma página bruta: captura (caminho ou bytes), HTML (str/bytes ou None) e URL.
        O pHash vem primeiro; o embedding e o s só são calculados se a página chegar ao estágio 2.
        Com `detalhes=True`, os detalhes de decidir mais "dobra" (a imagem analisada) e "classe"."""
        from mhf import estrutural, visual
        tempos = {}
        inicio = t = time.perf_counter()
        img = visual.abrir_imagem(imagem)
        classe = classe or visual.classe_de_tela(img.width)
        dobra = visual.primeira_dobra(img, classe)
        tempos["abrir"] = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        consulta = {"phash64": visual.phash(dobra)}
        tempos["phash"] = (time.perf_counter() - t) * 1000

        def completar():
            extra = {}
            t = time.perf_counter()
            if self.hash_bits == 256:
                extra["phash256"] = visual.phash(dobra, bits=256)
            if embedder is not None:
                emb = embedder
            else:
                if self._embedder is None:
                    self._embedder = visual.Embedder(self.embedding)
                emb = self._embedder
            extra[self.embedding] = emb.embed(dobra)
            tempos["embedding"] = (time.perf_counter() - t) * 1000
            t = time.perf_counter()
            s = estrutural.extrair(html, url) if html else None
            extra["s"], extra["elementos"] = s, (s.contagens.get("elementos") if s else None)
            tempos["estrutural"] = (time.perf_counter() - t) * 1000
            return extra

        v = self.decidir(consulta, classe, url, completar=completar, tempos=tempos, detalhes=detalhes)
        tempos["total"] = (time.perf_counter() - inicio) * 1000
        if detalhes:
            v.detalhes.update({"dobra": dobra, "classe": classe})
        return v
