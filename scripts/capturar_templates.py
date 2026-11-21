"""
Passo 2 — templates de login com vários anos (snapshots do Wayback de 2019 a 2026 + captura ao vivo).

Uso, na ordem:
    python scripts/capturar_templates.py planejar --marcas config/marcas.json --plano config/templates_snapshots.json
    python scripts/capturar_templates.py capturar --plano config/templates_snapshots.json --raiz data/templates
    python scripts/capturar_templates.py revisar  --plano config/templates_snapshots.json --raiz data/templates
    python scripts/capturar_templates.py aprovar  --plano config/templates_snapshots.json ID [ID ...]
    python scripts/capturar_templates.py rejeitar --plano config/templates_snapshots.json ID --motivo "..."

`planejar` consulta a API CDX do Wayback e grava o plano (a "receita" versionada da base);
`capturar` renderiza cada entrada pendente com o Playwright (Chromium) nas duas resoluções dos
datasets e pode ser interrompido e retomado; `revisar` gera a grade de miniaturas e `aprovar`/
`rejeitar` registram a decisão no plano. As funções puras ficam em src/mhf/templates.py.

Desenho: docs/especificacoes/2026-11-20-base-de-templates.md
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from importlib.metadata import version

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import templates  # noqa: E402

PAUSA_WAYBACK_S = 1.5  # gentileza com o Internet Archive entre requisições
USER_AGENT = "Mozilla/5.0 (compatible; mhf-templates/1.0; pesquisa academica)"


# ---------------------------------------------------------------- utilidades

def ler_json(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def gravar_json(caminho, dados):
    """Grava em arquivo temporário e troca no fim, para uma queda não deixar o JSON pela metade."""
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(temporario, caminho)


def baixar(url, tentativas=3):
    """Bytes da URL, ou None se as `tentativas` falharem (o Wayback às vezes derruba a conexão)."""
    requisicao = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for tentativa in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(requisicao, timeout=60) as resposta:
                return resposta.read()
        except Exception as erro:  # rede instável, 5xx do Wayback etc.: quem chama decide o que fazer
            print(f"  falha ao baixar {url} (tentativa {tentativa}/{tentativas}): {erro}")
            if tentativa < tentativas:
                time.sleep(5 * tentativa)
    return None


# ---------------------------------------------------------------- planejar

def consultar_cdx(url):
    """Snapshots (timestamp, status) de `url` de jun/2018 a dez/2026, um por dia, só 2xx e 3xx.
    Devolve None se a consulta falhar, para o plano registrar o buraco como "erro_consulta"."""
    consulta = urllib.parse.urlencode({
        "url": url, "from": "201806", "to": "202612", "output": "json",
        "fl": "timestamp,statuscode", "filter": "statuscode:[23]..",
        "collapse": "timestamp:8",  # um por dia: garante que o rótulo AAAA-MM-DD da entrada seja único
    })
    dados = baixar(f"https://web.archive.org/cdx/search/cdx?{consulta}")
    if dados is None:
        return None
    try:
        linhas = json.loads(dados or b"[]")
    except ValueError:
        print(f"  resposta da CDX ilegível para {url}")
        return None
    return [(ts, int(st)) for ts, st in linhas[1:] if st.isdigit()]  # linhas[0] é o cabeçalho


def cmd_planejar(a):
    variantes = templates.ler_marcas(a.marcas)
    novo = []
    for i, v in enumerate(variantes):
        if i:
            time.sleep(PAUSA_WAYBACK_S)
        entradas = templates.planejar_variante(v, consultar_cdx(v.url))
        snapshots = sum(1 for e in entradas if e["origem"] == "wayback" and not e["buraco"])
        buracos = [f"{e['anos_alvo'][0]} ({e['buraco']})" for e in entradas if e["buraco"]]
        print(f"{v.entidade} / {v.variante}: {snapshots} snapshots"
              + (f"; buracos: {', '.join(buracos)}" if buracos else ""))
        novo += entradas
    antigo = ler_json(a.plano) if os.path.exists(a.plano) else []
    gravar_json(a.plano, templates.mesclar_plano(novo, antigo))
    print(f"Plano com {len(novo)} entradas gravado em {a.plano}")


# ---------------------------------------------------------------- capturar

def capturar_entrada(navegador, e, raiz, versoes):
    """Renderiza uma entrada nas duas resoluções e grava screenshots, DOMs, HTML original e meta.json
    (por último). Nada é clicado; falhas são registradas no status e os arquivos são salvos assim mesmo."""
    from playwright.sync_api import Error as ErroPlaywright
    from playwright.sync_api import TimeoutError as TempoEsgotado

    pasta = templates.pasta_entrada(raiz, e["id"])
    os.makedirs(pasta, exist_ok=True)
    ao_vivo = e["origem"] == "ao_vivo"
    # Modo comum do Wayback (não if_): no if_ o login da Microsoft acha que os cookies estão desligados
    # e redireciona para uma página não arquivada. A barra do modo comum é removida antes do screenshot.
    url = e["url_login"] if ao_vivo else templates.url_wayback(e["timestamp"], e["url_login"], "")

    if not ao_vivo:  # HTML como foi arquivado, antes do JavaScript
        time.sleep(PAUSA_WAYBACK_S)
        original = baixar(templates.url_wayback(e["timestamp"], e["url_login"], "id_"))
        if original is not None:
            with open(os.path.join(pasta, "html_original.html"), "wb") as f:
                f.write(original)

    resolucoes = {}
    for nome, (largura, altura) in templates.RESOLUCOES.items():
        if not ao_vivo:
            time.sleep(PAUSA_WAYBACK_S)
        # Cada resolução num carregamento próprio: a página pode se reorganizar ao mudar de largura.
        contexto = navegador.new_context(viewport={"width": largura, "height": altura}, locale=e["locale"])
        pagina = contexto.new_page()
        inicio = time.perf_counter()
        erro_navegacao = None
        try:
            resposta = pagina.goto(url, wait_until="load", timeout=60000)
        except ErroPlaywright as erro:  # tempo esgotado, DNS, conexão derrubada...
            resposta = None
            erro_navegacao = str(erro).splitlines()[0][:200]
        if resposta is None or resposta.status >= 400:
            status = "bloqueado" if ao_vivo else "erro_wayback"
        else:
            try:
                pagina.wait_for_selector(templates.SELETOR_CREDENCIAL, timeout=30000)
                status = "ok"
            except TempoEsgotado:
                status = "sem_formulario"
            try:
                pagina.wait_for_load_state("networkidle", timeout=10000)
            except TempoEsgotado:
                pass  # páginas com requisições contínuas nunca ficam ociosas; o formulário já apareceu
            if ao_vivo and not os.path.exists(os.path.join(pasta, "html_original.html")):
                try:
                    with open(os.path.join(pasta, "html_original.html"), "wb") as f:
                        f.write(resposta.body())
                except ErroPlaywright:
                    pass
        tempo = time.perf_counter() - inicio
        try:
            if not ao_vivo:
                pagina.evaluate("s => document.querySelectorAll(s).forEach(e => e.remove())",
                                templates.SELETOR_BARRA_WAYBACK)
            pagina.screenshot(path=os.path.join(pasta, f"shot_{nome}.png"), full_page=False)
            with open(os.path.join(pasta, f"dom_{nome}.html"), "w", encoding="utf-8") as f:
                f.write(templates.remover_prefixo_wayback(pagina.content()))
        except ErroPlaywright as erro:  # ex.: redirecionamento tardio destruiu a página no meio da gravação
            print(f"  {e['id']} {nome}: não foi possível salvar screenshot/DOM ({erro})")
            status = "erro_captura"  # não deixa um "ok" sem arquivos; a entrada fica pendente
        resolucoes[nome] = {"status": status, "tempo_s": round(tempo, 1), "url_final": pagina.url}
        if erro_navegacao:
            resolucoes[nome]["erro"] = erro_navegacao  # para diagnosticar falhas intermitentes depois
        contexto.close()

    meta = {"entidade": e["entidade"], "variante": e["variante"], "url_login": e["url_login"],
            "origem": e["origem"], "url_snapshot": None if ao_vivo else url, "timestamp": e["timestamp"],
            "anos_alvo": e["anos_alvo"], "data_captura": datetime.now().isoformat(timespec="seconds"),
            "resolucoes": resolucoes, "versoes": versoes}
    gravar_json(os.path.join(pasta, "meta.json"), meta)  # por último: marca a entrada como concluída
    return meta


def cmd_capturar(a):
    from playwright.sync_api import sync_playwright

    pendentes = templates.entradas_pendentes(ler_json(a.plano), a.raiz)
    if a.so:
        pendentes = [e for e in pendentes if e["id"] in set(a.so)]
    print(f"{len(pendentes)} entradas pendentes")
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        versoes = {"playwright": version("playwright"), "chromium": navegador.version}
        for i, e in enumerate(pendentes, 1):
            meta = capturar_entrada(navegador, e, a.raiz, versoes)
            resumo = ", ".join(f"{r}={d['status']} ({d['tempo_s']} s)" for r, d in meta["resolucoes"].items())
            print(f"[{i}/{len(pendentes)}] {e['id']}: {resumo}")
        navegador.close()


# ---------------------------------------------------------------- revisar / aprovar / rejeitar

def cmd_revisar(a):
    plano = ler_json(a.plano)
    metas = {}
    for e in plano:
        caminho = os.path.join(templates.pasta_entrada(a.raiz, e["id"]), "meta.json")
        if not e.get("buraco") and os.path.exists(caminho):
            metas[e["id"]] = ler_json(caminho)
    saida = os.path.join(a.raiz, "revisao.html")
    os.makedirs(a.raiz, exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        f.write(templates.gerar_revisao_html(plano, metas))
    print(f"Página de revisão gravada em {saida} ({len(metas)} entradas capturadas)")


def _marcar(a, aprovado, motivo):
    plano = ler_json(a.plano)
    try:
        for id_ in a.ids:
            templates.marcar_aprovacao(plano, id_, aprovado, motivo)
    except KeyError as erro:  # nada é gravado se algum id não existir
        sys.exit(f"id não encontrado no plano: {erro.args[0]} (nenhuma alteração gravada)")
    gravar_json(a.plano, plano)
    print(f"{len(a.ids)} entrada(s) marcada(s) como {'aprovada' if aprovado else 'rejeitada'}")


def cmd_aprovar(a):
    _marcar(a, True, "")


def cmd_rejeitar(a):
    _marcar(a, False, a.motivo)


# ---------------------------------------------------------------- linha de comando

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("planejar", help="consulta o Wayback e grava o plano de snapshots")
    s.add_argument("--marcas", required=True, help="tabela de marcas com as variantes de login (JSON)")
    s.add_argument("--plano", required=True, help="plano de snapshots a gravar (JSON versionado)")
    s.set_defaults(func=cmd_planejar)

    s = sub.add_parser("capturar", help="renderiza as entradas pendentes do plano")
    s.add_argument("--plano", required=True)
    s.add_argument("--raiz", required=True, help="pasta de saída (ex.: data/templates, fora do git)")
    s.add_argument("--so", nargs="+", metavar="ID", help="capturar só estas entradas")
    s.set_defaults(func=cmd_capturar)

    s = sub.add_parser("revisar", help="gera <raiz>/revisao.html com a grade de miniaturas")
    s.add_argument("--plano", required=True)
    s.add_argument("--raiz", required=True)
    s.set_defaults(func=cmd_revisar)

    s = sub.add_parser("aprovar", help="aprova entradas do plano (só aprovadas entram na base)")
    s.add_argument("--plano", required=True)
    s.add_argument("ids", nargs="+", metavar="ID")
    s.set_defaults(func=cmd_aprovar)

    s = sub.add_parser("rejeitar", help="rejeita uma entrada do plano, com o motivo")
    s.add_argument("--plano", required=True)
    s.add_argument("ids", nargs=1, metavar="ID")
    s.add_argument("--motivo", required=True)
    s.set_defaults(func=cmd_rejeitar)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
