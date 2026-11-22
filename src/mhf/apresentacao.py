"""
Apresentação do veredito na interface (etapa 7): transforma um Veredito (com detalhes) no conteúdo da tela,
em português e com vírgula decimal. Não decide nada: só descreve o que o Detector decidiu.

Desenho: docs/especificacoes/2026-11-22-interface.md, seção 8.
"""

import base64
import io
import math
import urllib.parse

from mhf import avaliacao, exemplos

LEGENDA_TEMPLATE = ("O classificador usa o melhor valor de cada sinal entre todos os templates da marca; "
                    "esta é a imagem mais parecida.")

# (nome da característica, rótulo na tela); a ordem é a da tela
ROTULOS_SINAIS = (
    ("sim_h64", "Semelhança do pHash"),
    ("sim_h256", "Semelhança do pHash de 256 bits"),
    ("cos_small", "Cosseno do embedding (MobileNetV3)"),
    ("cos_large", "Cosseno do embedding (MobileNetV3 Large)"),
    ("jaccard_caminhos", "Caminhos do DOM em comum (Jaccard)"),
    ("jaccard_criticos", "Elementos críticos em comum (formulário, senha, envio)"),
    ("sim_contagens", "Semelhança das contagens do DOM"),
    ("hash_igual", "DOM idêntico a um template"),
    ("s_ausente", "DOM ausente ou com até 5 elementos"),
)
_BITS = {"sim_h64": 64, "sim_h256": 256}
_SIM_NAO = ("hash_igual", "s_ausente")
# sinais que vêm do DOM: com o s ausente, o classificador recebe 0 neles (cascata.caracteristicas), mas não
# houve comparação nenhuma; a tela mostra "—" para não sugerir "DOM comparado e nada em comum"
_SINAIS_DO_DOM = ("jaccard_caminhos", "jaccard_criticos", "sim_contagens", "hash_igual")


def _vazio(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def numero(v, casas=3) -> str:
    """0.8491 → "0,849"; None ou NaN → "—"."""
    if _vazio(v):
        return "—"
    return f"{v:.{casas}f}".replace(".", ",")


def frase_do_motivo(v, tau: float) -> str:
    """Uma frase, em linguagem simples, com o motivo do veredito."""
    x, d = v.entidade or v.entidade_proxima_h, v.dominio or "(sem domínio)"
    if v.motivo == "phishing":
        return f"Parece {x} (escore {numero(v.escore)}, limiar {numero(tau)}) e o domínio {d} não é de {x}."
    if v.motivo == "dominio_legitimo_estagio2":
        return f"Parece {x}, mas está num domínio oficial de {x} ({d})."
    if v.motivo == "abaixo_do_limiar":
        return (f"Não se parece o bastante com nenhuma marca protegida (mais próxima: {x}, "
                f"escore {numero(v.escore)} < {numero(tau)}).")
    if v.motivo == "sem_template_proximo":
        return "Nenhum template visualmente parecido (pHash)."
    if v.motivo == "dominio_legitimo_estagio1":
        return f"O template mais parecido pelo pHash é de {x}, e o domínio {d} é oficial de {x}."
    raise ValueError(f"motivo desconhecido: {v.motivo}")


def sinais_legiveis(caracteristicas: dict) -> list:
    """As características que o classificador recebeu para uma marca, com rótulo e texto para a tela."""
    rotulos = dict(ROTULOS_SINAIS)
    ordem = [n for n, _ in ROTULOS_SINAIS if n in caracteristicas] + \
        [n for n in caracteristicas if n not in rotulos]
    sem_dom = not _vazio(caracteristicas.get("s_ausente")) and caracteristicas["s_ausente"] >= 0.5
    sinais = []
    for nome in ordem:
        v = caracteristicas[nome]
        valor = None if _vazio(v) or (sem_dom and nome in _SINAIS_DO_DOM) else float(v)
        if valor is None:
            texto = "—"
        elif nome in _SIM_NAO:
            texto = "sim" if valor >= 0.5 else "não"
        elif nome in _BITS:
            bits = _BITS[nome]
            texto = f"{numero(valor)} ({round((1 - valor) * bits)} de {bits} bits diferentes)"
        else:
            texto = numero(valor)
        sinais.append({"nome": nome, "rotulo": rotulos.get(nome, nome), "valor": valor, "texto": texto})
    return sinais


def template_exibido(v, base) -> dict | None:
    """O template da marca exibida mais parecido pelo embedding, para mostrar ao lado da página."""
    mt = ((v.detalhes or {}).get("melhor_template") or {}).get(v.entidade)
    if mt is None:
        return None
    item = base.itens[mt["indice"]]
    return {"id": item["id"], "marca": item["entidade"], "variante": item["variante"],
            "ano": str(avaliacao.data_do_template(item).year),
            "origem": "Wayback" if item["origem"] == "wayback" else "ao vivo",
            "cosseno": float(mt["cosseno"]),
            "url": "/api/template?id=" + urllib.parse.quote(item["id"], safe="")}


def _imagem_data_url(img) -> str | None:
    if img is None:
        return None
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _dominios(tabela, entidade):
    for e in tabela:
        if e["entidade"] == entidade:
            return list(e["dominios"])
    return []


def montar_resultado(v, tau, base, tabela, url_analisada, simulado, exemplo=None, pagina=None) -> dict:
    """O JSON que a tela mostra para um veredito (Veredito com detalhes). `exemplo` (Exemplo) traz o rótulo
    real; `pagina` (PaginaCapturada) traz o que a captura ao vivo viu."""
    detalhes = v.detalhes or {}
    caracteristicas = (detalhes.get("caracteristicas") or {}).get(v.entidade, {})
    escores = sorted(((m, e) for m, e in (v.escores or {}).items() if not _vazio(e)), key=lambda x: -x[1])[:5]
    real = None
    if exemplo is not None:
        situacao = exemplos.situacao_real(exemplo.estrato, v.rotulo, v.entidade, simulado)
        real = {"texto": exemplos.texto_real(exemplo.estrato, exemplo.marca_dataset), "situacao": situacao,
                "frase": exemplos.frase_situacao(situacao, exemplo.estrato, exemplo.estrato),
                "nota": exemplo.nota, "titulo": exemplo.titulo}
    info_pagina = None
    if pagina is not None:
        info_pagina = {"url_digitada": pagina.url_digitada, "url_final": pagina.url_final,
                       "url_analisada": url_analisada, "titulo": pagina.titulo, "status": pagina.status,
                       "credencial": pagina.credencial, "tempo_abrir_s": round(pagina.tempo_s, 1)}
    phishing = v.rotulo == "phishing"
    return {
        "veredito": {"rotulo": v.rotulo, "titulo": f"PHISHING — imita {v.entidade}" if phishing else "Legítima",
                     "frase": frase_do_motivo(v, tau), "motivo": v.motivo},
        "marca": v.entidade,
        "escore": None if _vazio(v.escore) else float(v.escore),
        "tau": float(tau),
        "escores": [{"marca": m, "escore": float(e)} for m, e in escores],
        "sinais": sinais_legiveis(caracteristicas),
        "template": template_exibido(v, base),
        "legenda_template": LEGENDA_TEMPLATE,
        "dominio": v.dominio,
        "dominio_simulado": bool(simulado),
        "dominios_oficiais": _dominios(tabela, v.entidade),
        "url_analisada": url_analisada,
        "tempos_ms": {k: round(ms) for k, ms in v.tempos_ms.items()},
        "captura": _imagem_data_url(detalhes.get("dobra")),
        "classe": detalhes.get("classe"),
        "real": real,
        "pagina": info_pagina,
    }
