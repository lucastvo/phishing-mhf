"""
Exemplos prontos da interface (etapa 7): páginas do conjunto de teste lidas direto das pastas dos datasets
(os HTMLs de phishing não são copiados: as pastas dos datasets têm exclusão no antivírus), o rótulo real
de cada uma (o estrato da divisão, sem reetiquetar nada à mão) e os tipos de candidato usados para
escolher os exemplos.

Desenho: docs/especificacoes/2026-11-22-interface.md, seção 6.
"""

import csv
import io
import json
import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from mhf import divisao, visual

MOTIVO_SEM_DATASETS = ("data/interface/datasets.json não existe; gere com scripts/escolher_exemplos.py "
                       "(README, passo 7)")
_SEM_MARCA = ("fora", "sem_marca")


# ---------------------------------------------------------------- rótulo real

def situacao_real(estrato: str, rotulo: str, entidade: str | None, simulado: bool) -> str:
    """Compara o veredito com o rótulo real (estrato da divisão): "acertou", "errou", "marca_errada",
    "marca_desconhecida" (phishing detectado sem marca de 𝒯 no dataset) ou "sem_comparacao" (domínio
    simulado: a página foi tirada do lugar dela)."""
    if simulado:
        return "sem_comparacao"
    phishing = rotulo == "phishing"
    if estrato == "benigno":
        return "errou" if phishing else "acertou"
    if estrato in _SEM_MARCA:
        return "marca_desconhecida" if phishing else "errou"
    if not phishing:
        return "errou"
    return "acertou" if entidade == estrato else "marca_errada"


def texto_real(estrato: str, marca_dataset: str) -> str:
    """O que a página é de fato, pelo dataset."""
    if estrato == "benigno":
        return "legítima"
    if estrato == "sem_marca":
        return "phishing (o dataset não informa a marca)"
    if estrato == "fora":
        return f"phishing de marca fora da base ({marca_dataset})"
    if marca_dataset and marca_dataset != estrato:
        return f"phishing de {estrato} (rótulo do dataset: {marca_dataset})"
    return f"phishing de {estrato}"


def frase_situacao(situacao: str, estrato: str, entidade_real: str | None) -> str:
    """Frase curta do resultado da comparação com o rótulo real."""
    if situacao == "acertou":
        return "✓ acertou"
    if situacao == "errou":
        return "✗ errou: alerta falso" if estrato == "benigno" else "✗ errou: phishing não detectado"
    if situacao == "marca_errada":
        return f"✗ detectou o phishing, mas errou a marca (real: {entidade_real})"
    if situacao == "marca_desconhecida":
        return ("detectado como phishing; o dataset não informa a marca" if estrato == "sem_marca"
                else "detectado como phishing; a marca real está fora da base")
    if situacao == "sem_comparacao":
        return "domínio simulado: a página foi tirada do lugar dela, então não há rótulo real para comparar"
    raise ValueError(f"situação desconhecida: {situacao}")


# ---------------------------------------------------------------- páginas dos datasets

def ler_pagina_do_dataset(linha: dict, raiz: str, classe: str | None) -> dict:
    """Captura (só a primeira dobra, regravada em PNG, como a captura da aba no navegador), HTML e URL de
    uma linha do índice de um dataset. `classe` fixa o tamanho de tela (Phishpedia benign); None = pela
    largura da captura. Arquivo ausente → FileNotFoundError."""
    with Image.open(os.path.join(raiz, linha["caminho_shot"])) as img:
        img.load()
        largura, altura = visual.tamanho_da_dobra(img.width, classe or visual.classe_de_tela(img.width))
        dobra = img.crop((0, 0, min(largura, img.width), min(altura, img.height)))
    buf = io.BytesIO()
    dobra.save(buf, format="PNG")  # no mesmo modo de cor (com o alfa, se houver)
    html = None
    if linha.get("html_util") == "1":
        with open(os.path.join(raiz, linha["caminho_html"]), "rb") as f:
            html = f.read()
    return {"imagem": buf.getvalue(), "html": html, "url": linha.get("url") or linha["id"], "classe": classe}


def gravar_datasets(caminho: str, datasets: dict):
    """{nome: {"indice", "raiz", "classe"}} → data/interface/datasets.json (local: caminhos da máquina)."""
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(datasets, f, ensure_ascii=False, indent=2)


def ler_datasets(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- lista de exemplos

@dataclass
class Exemplo:
    numero: int
    dataset: str
    id: str
    grupo: str              # "acerto" ou "erro"
    titulo: str
    nota: str
    estrato: str | None     # rótulo real (divisão): entidade de 𝒯, "fora", "sem_marca" ou "benigno"
    marca_dataset: str
    linha: dict | None      # linha do índice do dataset
    raiz: str | None
    classe: str | None
    disponivel: bool
    motivo: str             # por que não está disponível ("" se está)


def _ler_indice(caminho):
    with open(caminho, encoding="utf-8") as f:
        return {l["id"]: l for l in csv.DictReader(f)}


def ler_exemplos(caminho_config: str, caminho_datasets: str, div: dict) -> tuple[list, list]:
    """Lê config/exemplos_interface.json → (exemplos numerados a partir de 1, URLs sugeridas). Cada exemplo
    é conferido no disco; o que faltar o deixa indisponível, com o motivo, em vez de quebrar a interface
    (o antivírus pode pôr um arquivo em quarentena). `div` é o resultado de divisao.ler_divisao."""
    with open(caminho_config, encoding="utf-8") as f:
        config = json.load(f)
    datasets = ler_datasets(caminho_datasets) if os.path.exists(caminho_datasets) else None
    indices, lista = {}, []
    for n, item in enumerate(config.get("exemplos", []), start=1):
        ds, id_ = item["dataset"], item["id"]
        d = div.get((ds, id_))
        e = Exemplo(numero=n, dataset=ds, id=id_, grupo=item["grupo"], titulo=item["titulo"], nota=item["nota"],
                    estrato=d["estrato"] if d else None, marca_dataset="", linha=None, raiz=None, classe=None,
                    disponivel=False, motivo="")
        lista.append(e)
        if datasets is None:
            e.motivo = MOTIVO_SEM_DATASETS
            continue
        if ds not in datasets:
            e.motivo = f"o dataset {ds} não está em {caminho_datasets}"
            continue
        info = datasets[ds]
        e.raiz, e.classe = info["raiz"], info.get("classe")
        if ds not in indices:
            indices[ds] = _ler_indice(info["indice"]) if os.path.exists(info["indice"]) else None
        if indices[ds] is None:
            e.motivo = f"índice não encontrado: {info['indice']}"
            continue
        linha = indices[ds].get(id_)
        if linha is None:
            e.motivo = f"{id_} não está no índice de {ds}"
            continue
        e.linha, e.marca_dataset = linha, linha.get("marca", "")
        if d is None:
            e.motivo = f"{id_} não está na divisão (excluída?)"
            continue
        if d["conjunto"] != divisao.TESTE:
            e.motivo = f"{id_} não é do conjunto de teste ({d['conjunto']})"
            continue
        arquivos = [linha["caminho_shot"]] + ([linha["caminho_html"]] if linha.get("html_util") == "1" else [])
        faltando = [os.path.join(e.raiz, a) for a in arquivos if not os.path.exists(os.path.join(e.raiz, a))]
        if faltando:
            e.motivo = f"arquivo não encontrado (quarentena do antivírus?): {faltando[0]}"
            continue
        e.disponivel = True
    return lista, config.get("urls_sugeridas", [])


# ---------------------------------------------------------------- candidatos

def tipo_do_candidato(estrato: str, rotulo: str, entidade: str | None, motivo: str, s_ausente: bool) -> str:
    """Em que caixa da seção 6.1 do desenho a página cai, dado o rótulo real e o veredito."""
    phishing = rotulo == "phishing"
    if estrato == "benigno":
        if phishing:
            return "alerta_falso"
        if motivo.startswith("dominio_legitimo"):
            return "legitima_dominio_oficial"
        return "legitima_sem_dom" if s_ausente else "legitima_comum"
    if estrato in _SEM_MARCA:
        if phishing:
            return "phishing_sem_marca_detectado"
        return "phishing_nao_detectado_sem_dom" if s_ausente else "phishing_sem_marca_nao_detectado"
    if phishing:
        return "phishing_marca_certa" if entidade == estrato else "phishing_marca_errada"
    return "phishing_nao_detectado_sem_dom" if s_ausente else "phishing_nao_detectado"


def folha_de_contato(itens: list, saida: str, colunas: int = 4, largura: int = 400):
    """Grade JPEG das dobras (itens[i]["imagem"], PNG) com a legenda de cada uma, para a revisão manual."""
    miniaturas = []
    for it in itens:
        with Image.open(io.BytesIO(it["imagem"])) as img:
            img = img.convert("RGB")
            altura = max(1, round(img.height * largura / img.width))
            miniaturas.append(img.resize((largura, altura)))
    legenda_h = 28
    celula_h = max((m.height for m in miniaturas), default=1) + legenda_h
    linhas = max(1, -(-len(miniaturas) // colunas))
    folha = Image.new("RGB", (colunas * largura, linhas * celula_h), "white")
    desenho = ImageDraw.Draw(folha)
    fonte = ImageFont.load_default(size=16)
    for k, (m, it) in enumerate(zip(miniaturas, itens)):
        x, y = (k % colunas) * largura, (k // colunas) * celula_h
        folha.paste(m, (x, y))
        desenho.rectangle([x, y, x + largura - 1, y + m.height - 1], outline=(180, 180, 180))
        desenho.text((x + 4, y + m.height + 4), it["legenda"], fill="black", font=fonte)
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    folha.save(saida, format="JPEG", quality=85)
