"""
Impressão digital estrutural (componente s de φ(w) = (h, e, s)).

Conforme a Seção 2.6 da monografia, s é formada por:
  1. hash canônico do DOM normalizado;
  2. conjunto de caminhos de tags (comparado por índice de Jaccard);
  3. caminhos XPath de elementos críticos (campos de senha, formulários, botões de envio);
  4. características simples (contagens de elementos-chave).

Normalização (Seção 2.4.3): descarta conteúdo textual, scripts, estilos, comentários e
atributos voláteis (ids, classes, estilos inline etc.). Só sobrevivem alguns atributos que
descrevem o PAPEL do elemento (ex.: type do <input>), em ordem fixa.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

from lxml import etree, html

from mhf.marcas import dominio_registravel

# Elementos que não fazem parte do layout e só adicionam ruído.
TAGS_DESCARTADAS = {
    "script", "style", "noscript", "template", "meta", "link", "base", "title", "head",
    "svg", "path", "g", "defs", "use", "symbol",  # internos de SVG variam muito entre versões
}

# Atributos que indicam o papel funcional do elemento e que são estáveis entre clones.
# Qualquer outro atributo (id, class, style, data-*, name, value...) é descartado.
ATRIBUTOS_DE_PAPEL = {
    "input": ("type",),
    "button": ("type",),
}

TIPOS_CAMPO_TEXTO = {"text", "email", "tel", "number", ""}


@dataclass
class ImpressaoEstrutural:
    hash_canonico: str
    caminhos: set[str] = field(default_factory=set)
    xpaths_criticos: set[str] = field(default_factory=set)
    contagens: dict[str, int] = field(default_factory=dict)

    def para_dict(self) -> dict:
        d = asdict(self)
        d["caminhos"] = sorted(self.caminhos)
        d["xpaths_criticos"] = sorted(self.xpaths_criticos)
        return d

    @classmethod
    def de_dict(cls, d: dict) -> "ImpressaoEstrutural":
        return cls(d["hash_canonico"], set(d["caminhos"]), set(d["xpaths_criticos"]), dict(d["contagens"]))


# ---------------------------------------------------------------- normalização

def _rotulo(el) -> str:
    """Nome normalizado do nó: tag + atributos de papel, ex.: input[password]."""
    tag = el.tag.lower()
    attrs = ATRIBUTOS_DE_PAPEL.get(tag, ())
    valores = [(el.get(a) or "").strip().lower() for a in attrs]
    if tag == "input" and valores and valores[0] in TIPOS_CAMPO_TEXTO:
        valores[0] = "text"  # text/email/tel são intercambiáveis num formulário de login
    return f"{tag}[{','.join(valores)}]" if attrs else tag


def _filhos(el):
    for filho in el:
        if not isinstance(filho.tag, str):  # comentários, instruções de processamento
            continue
        if filho.tag.lower() in TAGS_DESCARTADAS:
            continue
        if filho.tag.lower() == "input" and (filho.get("type") or "").lower() == "hidden":
            continue  # campos ocultos carregam tokens e variam a cada carga
        yield filho


def parsear(conteudo: bytes | str):
    """Converte o HTML bruto na raiz <body> (ou <html>) do DOM. Retorna None se não houver DOM útil."""
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8", errors="ignore")
    if not conteudo.strip():
        return None
    try:
        doc = html.fromstring(conteudo)
    except (etree.ParserError, ValueError):
        return None
    corpo = doc.find(".//body")
    return corpo if corpo is not None else doc


# ---------------------------------------------------------------- componentes de s

def _serializacao_canonica(el) -> str:
    """Serialização recursiva só com rótulos normalizados: (div(form(input[text])(input[password])))."""
    return "(" + _rotulo(el) + "".join(_serializacao_canonica(f) for f in _filhos(el)) + ")"


_ACTION_ABSOLUTA = re.compile(r"^\s*(?:https?:)?[/\\]{2}", re.I)


def _action_externa(action: str, dominio_pagina: str) -> bool:
    """O formulário envia os dados para outro dono? Compara os domínios registráveis (Public Suffix
    List, via mhf.marcas): www.itau.com.br e secure.itau.com.br são o mesmo dono; golpe.com.br e
    evilpaypal.com não. Só conta action absoluta (http://, https:// ou //host); relativa ("/entrar",
    "post.php") fica na própria página, e outros esquemas (mailto:, javascript:) não são contados.
    Sem a URL da página não dá para saber, e não conta."""
    if not dominio_pagina or not _ACTION_ABSOLUTA.match(action):
        return False
    action = action.strip()
    if action[:1] in "/\\":  # //host/... herda o esquema da página; o domínio não depende dele
        action = "http:" + action
    destino = dominio_registravel(action)
    return bool(destino) and destino != dominio_pagina


def _caminhar(el, prefixo, caminhos, criticos, contagens, dominio_pagina):
    caminho = f"{prefixo}/{_rotulo(el)}"
    caminhos.add(caminho)
    tag = el.tag.lower()

    contagens["elementos"] += 1
    if tag == "form":
        contagens["formularios"] += 1
        criticos.add(caminho)
        if _action_externa(el.get("action") or "", dominio_pagina):
            contagens["forms_action_externa"] += 1
    elif tag == "input":
        tipo = (el.get("type") or "text").lower()
        contagens["inputs"] += 1
        if tipo == "password":
            contagens["campos_senha"] += 1
            criticos.add(caminho)
        elif tipo == "submit":
            criticos.add(caminho)
    elif tag == "button":
        contagens["botoes"] += 1
        if (el.get("type") or "submit").lower() == "submit":
            criticos.add(caminho)
    elif tag == "iframe":
        contagens["iframes"] += 1
    elif tag == "img":
        contagens["imagens"] += 1
    elif tag == "a":
        contagens["links"] += 1

    for filho in _filhos(el):
        _caminhar(filho, caminho, caminhos, criticos, contagens, dominio_pagina)


def extrair(conteudo: bytes | str, url: str = "") -> ImpressaoEstrutural | None:
    """Extrai s a partir do HTML bruto (html.txt). `url` é usada só para detectar action externa."""
    raiz = parsear(conteudo)
    if raiz is None:
        return None
    dominio = dominio_registravel(url) if url else ""

    caminhos: set[str] = set()
    criticos: set[str] = set()
    contagens = dict.fromkeys(
        ["elementos", "formularios", "inputs", "campos_senha", "botoes",
         "iframes", "imagens", "links", "forms_action_externa"], 0)
    _caminhar(raiz, "", caminhos, criticos, contagens, dominio)

    hash_canonico = hashlib.sha256(_serializacao_canonica(raiz).encode()).hexdigest()
    return ImpressaoEstrutural(hash_canonico, caminhos, criticos, contagens)


# ---------------------------------------------------------------- comparação

def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def similaridade_contagens(a: dict, b: dict) -> float:
    """Média, por característica, de 1 - |x - y| / max(x, y). Vale 1 quando as contagens são iguais."""
    termos = []
    for k in a:
        x, y = a[k], b.get(k, 0)
        termos.append(1.0 if x == y == 0 else 1 - abs(x - y) / max(x, y))
    return sum(termos) / len(termos) if termos else 1.0


def comparar(s1: ImpressaoEstrutural, s2: ImpressaoEstrutural) -> dict[str, float]:
    """Similaridades em [0, 1] por componente. A combinação (pesos fixos ou classificador)
    fica para a regra de decisão da cascata, como previsto na Seção 1.4, item 5."""
    return {
        "hash_igual": float(s1.hash_canonico == s2.hash_canonico),
        "jaccard_caminhos": jaccard(s1.caminhos, s2.caminhos),
        "jaccard_criticos": jaccard(s1.xpaths_criticos, s2.xpaths_criticos),
        "sim_contagens": similaridade_contagens(s1.contagens, s2.contagens),
    }
