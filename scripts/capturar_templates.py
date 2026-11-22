"""
Passo 2 — templates de login com vários anos (snapshots do Wayback de 2019 a 2026 + captura ao vivo).

Uso, na ordem:
    python scripts/capturar_templates.py planejar --marcas config/marcas.json --plano config/templates_snapshots.json
    python scripts/capturar_templates.py capturar --plano config/templates_snapshots.json --raiz data/templates
    python scripts/capturar_templates.py revisar  --plano config/templates_snapshots.json --raiz data/templates
    python scripts/capturar_templates.py aprovar  --plano config/templates_snapshots.json --raiz data/templates ID [ID ...]
    python scripts/capturar_templates.py rejeitar --plano config/templates_snapshots.json --raiz data/templates ID --motivo "..."

`planejar` consulta a API CDX do Wayback e grava o plano (a "receita" versionada da base);
`capturar` renderiza cada entrada pendente com o Playwright (Chromium) nas duas resoluções dos
datasets e pode ser interrompido e retomado; `revisar` gera a grade de miniaturas e `aprovar`/
`rejeitar` registram a decisão no plano. As funções puras ficam em src/mhf/templates.py.

Desenho: docs/especificacoes/2026-11-20-base-de-templates.md
"""

import argparse
import http.client
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
PAGINAS_CDX_PREFIXO = 5  # páginas do índice da CDX lidas na busca por prefixo (~15 s e ~1,5 MB cada)
USER_AGENT = "Mozilla/5.0 (compatible; mhf-templates/1.0; pesquisa academica)"

# O http.client recusa respostas com mais de 100 cabeçalhos ("got more than 100 headers"), e algumas do
# Wayback passam disso (ex.: facebook.com/index.php de 2022, que repassa os cabeçalhos arquivados). Sem
# isso, o HTML original dessas páginas nunca era salvo. Não há API pública para o limite.
http.client._MAXHEADERS = max(http.client._MAXHEADERS, 1000)


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


def baixar(url, tentativas=3, prefixo_final=None, se_sair=None):
    """Bytes da URL, ou None se as `tentativas` falharem (o Wayback às vezes derruba a conexão).
    Com `prefixo_final`, devolve `se_sair` (por padrão None) se um redirecionamento levar para fora
    desse prefixo (ex.: um snapshot 3xx do Wayback que mandasse para a página ao vivo, de outra época);
    quem precisa distinguir esse caso de uma falha de rede passa outro valor."""
    requisicao = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for tentativa in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(requisicao, timeout=60) as resposta:
                if prefixo_final and not resposta.geturl().startswith(prefixo_final):
                    print(f"  {url} redirecionou para fora do Wayback ({resposta.geturl()}); descartado")
                    return se_sair
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


def consultar_cdx_prefixo(url):
    """Snapshots (timestamp, status, URL arquivada) de URLs que começam com `url`, só status 200, de
    jun/2018 a dez/2026, tirados das primeiras PAGINAS_CDX_PREFIXO páginas do índice da CDX.

    Por que uma amostra: o prefixo da Amazon ocupa mais de 1.300 páginas do índice (milhares de URLs de
    sessão por ano). Varrer tudo levaria horas, e uma consulta com filtro de data estoura o limite de 60 s
    do próprio Wayback (504), porque ele percorre o prefixo inteiro. O índice é ordenado pela URL, e o
    número de sessão não tem relação com a data, então as primeiras páginas são uma amostra sem viés das
    datas: em 21/11/2026, uma só página já tinha candidatos de todos os anos de 2019 a 2026. A escolha
    (mais próximo de 1º de janeiro, conferindo o conteúdo) é feita dentro dessa amostra, e o plano
    registra a URL e o timestamp exatos, que são a receita reproduzível. Devolve None se alguma página
    falhar: um ano faltando viraria buraco sem que o problema aparecesse."""
    capturas = set()
    for pagina in range(PAGINAS_CDX_PREFIXO):
        consulta = urllib.parse.urlencode({
            "url": url, "matchType": "prefix", "page": str(pagina), "output": "json",
            "from": "201806", "to": "202612",
            "fl": "timestamp,statuscode,original", "filter": "statuscode:200",
        })
        time.sleep(PAUSA_WAYBACK_S)
        dados = baixar(f"https://web.archive.org/cdx/search/cdx?{consulta}")
        if dados is None:
            return None
        try:
            linhas = json.loads(dados or b"[]")
            capturas.update((ts, int(st), original) for ts, st, original in linhas[1:]
                            if st.isdigit() and original)
        except (ValueError, TypeError):  # JSON quebrado ou fora do formato (ex.: {"error": ...})
            print(f"  resposta da CDX ilegível para {url} (página {pagina})")
            return None
    return sorted(capturas)


def conferidor_de_conteudo(v):
    """Função aceitar(timestamp, url) da busca por prefixo: baixa o HTML original do snapshot (modo id_)
    e confere os textos `evitar`/`exigir` da variante. Devolve True (serve), False (não serve) ou None
    (o download falhou: o planejar não troca de candidato em silêncio). Guarda o resultado, porque o
    mesmo snapshot pode ser candidato de dois anos vizinhos."""
    vistos = {}

    def aceitar(ts, url):
        if (ts, url) not in vistos:
            time.sleep(PAUSA_WAYBACK_S)
            # um redirecionamento para fora do Wayback não é falha de rede: o snapshot só não serve
            dados = baixar(templates.url_wayback(ts, url, "id_"), prefixo_final="https://web.archive.org/web/",
                           se_sair=b"")
            if dados is None:
                print(f"    {ts} ERRO no download (o ano fica como erro_conferencia): {url[:90]}")
                return None  # não guarda: uma nova tentativa pode funcionar
            vistos[(ts, url)] = templates.html_aceitavel(dados.decode("utf-8", "replace"), v.evitar, v.exigir)
            print(f"    {ts} {'serve' if vistos[(ts, url)] else 'descartado'}: {url[:90]}")
        return vistos[(ts, url)]

    return aceitar


def cmd_planejar(a):
    variantes = templates.ler_marcas(a.marcas)
    novo, falhas = [], 0
    for i, v in enumerate(variantes):
        if i:
            time.sleep(PAUSA_WAYBACK_S)
        if v.busca == "prefixo":
            capturas = consultar_cdx_prefixo(v.url)
            entradas = templates.planejar_variante(v, capturas, aceitar=conferidor_de_conteudo(v))
        else:
            capturas = consultar_cdx(v.url)
            entradas = templates.planejar_variante(v, capturas)
        falhas += capturas is None
        snapshots = sum(1 for e in entradas if e["origem"] == "wayback" and not e["buraco"])
        buracos = [f"{e['anos_alvo'][0]} ({e['buraco']})" for e in entradas if e["buraco"]]
        print(f"{v.entidade} / {v.variante}: {snapshots} snapshots"
              + (f"; buracos: {', '.join(buracos)}" if buracos else ""))
        novo += entradas
    if variantes and falhas == len(variantes):
        sys.exit("Todas as consultas ao Wayback falharam (fora do ar?). Plano NÃO foi alterado; tente mais tarde.")
    antigo = ler_json(a.plano) if os.path.exists(a.plano) else []
    plano = templates.mesclar_plano(novo, antigo)  # variantes cuja consulta falhou mantêm o plano anterior
    gravar_json(a.plano, plano)
    print(f"Plano com {len(plano)} entradas gravado em {a.plano}"
          + (f" ({falhas} variante(s) com consulta falha mantiveram o plano anterior, se havia)" if falhas else ""))


def esperar_credencial(pagina, seletor, tempo_ms):
    """Espera um campo de credencial VISÍVEL aparecer na página ou em qualquer frame dela (o login de
    algumas marcas fica dentro de um iframe). Devolve True se apareceu dentro do tempo."""
    from playwright.sync_api import Error as ErroPlaywright

    limite = time.monotonic() + tempo_ms / 1000
    while time.monotonic() < limite:
        for quadro in pagina.frames:
            try:
                if any(el.is_visible() for el in quadro.query_selector_all(seletor)):
                    return True
            except ErroPlaywright:
                pass  # frame saindo ou navegando no meio da consulta
        pagina.wait_for_timeout(500)
    return False


# ---------------------------------------------------------------- capturar

def renderizar_resolucao(navegador, e, pasta, nome, tamanho, url, seletor, salvar_original):
    """Renderiza a entrada numa resolução e grava shot_<nome>.png e dom_<nome>.html. Devolve o resumo
    dessa resolução (status, tempo, URL final e, no Wayback, o snapshot exibido e os vestígios no DOM).
    Com `salvar_original`, a captura ao vivo também grava o html_original.html (se ainda não existir)."""
    from playwright.sync_api import Error as ErroPlaywright
    from playwright.sync_api import TimeoutError as TempoEsgotado

    ao_vivo = e["origem"] == "ao_vivo"
    largura, altura = tamanho
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
        status = "ok" if esperar_credencial(pagina, seletor, 30000) else "sem_formulario"
        try:
            pagina.wait_for_load_state("networkidle", timeout=10000)
        except TempoEsgotado:
            pass  # páginas com requisições contínuas nunca ficam ociosas; o formulário já apareceu
        if salvar_original and ao_vivo and not os.path.exists(os.path.join(pasta, "html_original.html")):
            try:
                with open(os.path.join(pasta, "html_original.html"), "wb") as f:
                    f.write(resposta.body())
            except ErroPlaywright:
                pass
    tempo = time.perf_counter() - inicio
    residuos = None
    try:
        if not ao_vivo:
            pagina.evaluate("s => document.querySelectorAll(s).forEach(e => e.remove())",
                            templates.SELETOR_BARRA_WAYBACK)
        pagina.screenshot(path=os.path.join(pasta, f"shot_{nome}.png"), full_page=False)
        dom = pagina.content()
        if not ao_vivo:  # scripts/estilos do próprio Wayback e URLs reescritas
            dom = templates.remover_prefixo_wayback(templates.limpar_injecoes_wayback(dom))
            residuos = templates.residuos_wayback(dom)
        with open(os.path.join(pasta, f"dom_{nome}.html"), "w", encoding="utf-8") as f:
            f.write(dom)
    except ErroPlaywright as erro:  # ex.: redirecionamento tardio destruiu a página no meio da gravação
        print(f"  {e['id']} {nome}: não foi possível salvar screenshot/DOM ({erro})")
        status = "erro_captura"  # não deixa um "ok" sem arquivos; a entrada fica pendente
    resumo = {"status": status, "tempo_s": round(tempo, 1), "url_final": pagina.url}
    if not ao_vivo:
        # O snapshot de fato exibido (redirecionamentos podem levar a outra captura) — é esta data
        # que vale na avaliação, por exemplo na checagem "só templates anteriores à amostra".
        resumo["timestamp_efetivo"] = templates.timestamp_efetivo(pagina.url)
        resumo["residuos_wayback"] = residuos
    if erro_navegacao:
        resumo["erro"] = erro_navegacao  # para diagnosticar falhas intermitentes depois
    contexto.close()
    return resumo


def capturar_extra_entrada(navegador, e, raiz, resolucao, versoes):
    """Captura uma entrada já aprovada só numa resolução extra. Grava shot_/dom_ dessa resolução e, por
    último, extra_<resolucao>.json; não toca no meta.json nem no html_original.html da captura principal."""
    pasta = templates.pasta_entrada(raiz, e["id"])
    for nome in templates.arquivos_extra(resolucao) + [os.path.basename(templates.meta_extra_caminho(raiz, e["id"], resolucao))]:
        try:  # nada de uma captura extra anterior pode passar como desta
            os.remove(os.path.join(pasta, nome))
        except FileNotFoundError:
            pass
    ao_vivo = e["origem"] == "ao_vivo"
    url = e["url_login"] if ao_vivo else templates.url_wayback(e["timestamp"], templates.url_da_captura(e), "")
    seletor = e.get("seletor") or templates.SELETOR_CREDENCIAL
    resumo = renderizar_resolucao(navegador, e, pasta, resolucao, templates.RESOLUCOES_EXTRAS[resolucao], url,
                                  seletor, salvar_original=False)
    meta = {"entidade": e["entidade"], "variante": e["variante"], "url_login": e["url_login"],
            "origem": e["origem"], "timestamp": e["timestamp"], "resolucao": resolucao,
            "url_snapshot": None if ao_vivo else url,
            "data_captura": datetime.now().isoformat(timespec="seconds"), **resumo, "versoes": versoes}
    if e.get("url_arquivada"):
        meta["url_arquivada"] = e["url_arquivada"]
    gravar_json(templates.meta_extra_caminho(raiz, e["id"], resolucao), meta)  # por último
    return meta


def capturar_entrada(navegador, e, raiz, versoes):
    """Renderiza uma entrada nas duas resoluções e grava screenshots, DOMs, HTML original e meta.json
    (por último). Nada é clicado; falhas são registradas no status e os arquivos são salvos assim mesmo."""
    pasta = templates.pasta_entrada(raiz, e["id"])
    os.makedirs(pasta, exist_ok=True)
    templates.limpar_pasta_captura(pasta)  # nada de uma captura anterior pode passar como desta
    ao_vivo = e["origem"] == "ao_vivo"
    # Modo comum do Wayback (não if_): no if_ o login da Microsoft acha que os cookies estão desligados
    # e redireciona para uma página não arquivada. A barra do modo comum é removida antes do screenshot.
    url = e["url_login"] if ao_vivo else templates.url_wayback(e["timestamp"], templates.url_da_captura(e), "")

    seletor = e.get("seletor") or templates.SELETOR_CREDENCIAL

    if not ao_vivo:  # HTML como foi arquivado, antes do JavaScript
        time.sleep(PAUSA_WAYBACK_S)
        original = baixar(templates.url_wayback(e["timestamp"], templates.url_da_captura(e), "id_"),
                          prefixo_final="https://web.archive.org/web/")
        if original is not None:
            with open(os.path.join(pasta, "html_original.html"), "wb") as f:
                f.write(original)

    resolucoes = {nome: renderizar_resolucao(navegador, e, pasta, nome, tamanho, url, seletor, salvar_original=True)
                  for nome, tamanho in templates.RESOLUCOES.items()}

    meta = {"entidade": e["entidade"], "variante": e["variante"], "url_login": e["url_login"],
            "origem": e["origem"], "url_snapshot": None if ao_vivo else url, "timestamp": e["timestamp"],
            "anos_alvo": e["anos_alvo"], "data_captura": datetime.now().isoformat(timespec="seconds"),
            "resolucoes": resolucoes, "versoes": versoes}
    if e.get("url_arquivada"):  # busca por prefixo: identifica o snapshot junto com o timestamp
        meta["url_arquivada"] = e["url_arquivada"]
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


def cmd_capturar_extra(a):
    from playwright.sync_api import sync_playwright

    pendentes = templates.extras_pendentes(ler_json(a.plano), a.raiz, a.resolucao)
    if a.so:
        pendentes = [e for e in pendentes if e["id"] in set(a.so)]
    print(f"{len(pendentes)} entradas aprovadas sem captura em {a.resolucao}")
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        versoes = {"playwright": version("playwright"), "chromium": navegador.version}
        for i, e in enumerate(pendentes, 1):
            meta = capturar_extra_entrada(navegador, e, a.raiz, a.resolucao, versoes)
            print(f"[{i}/{len(pendentes)}] {e['id']}: {a.resolucao}={meta['status']} ({meta['tempo_s']} s)")
        navegador.close()


# ---------------------------------------------------------------- revisar / aprovar / rejeitar

def cmd_revisar(a):
    if a.resolucao:
        cmd_revisar_extra(a)
        return
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


def cmd_revisar_extra(a):
    plano = ler_json(a.plano)
    metas = {}
    for e in plano:
        caminho = templates.meta_extra_caminho(a.raiz, e["id"], a.resolucao)
        if not e.get("buraco") and os.path.exists(caminho):
            metas[e["id"]] = ler_json(caminho)
    saida = os.path.join(a.raiz, f"revisao_{a.resolucao}.html")
    with open(saida, "w", encoding="utf-8") as f:
        f.write(templates.gerar_revisao_extra_html(plano, metas, a.resolucao))
    print(f"Página de revisão gravada em {saida} ({len(metas)} entradas capturadas em {a.resolucao})")


def _marcar(a, aprovado, motivo):
    """Registra a decisão junto com a data da captura vista (do meta.json, ou do extra_<r>.json com
    --resolucao), para a aprovação valer só para aquela captura. Se algum id for inválido, nada é gravado."""
    plano = ler_json(a.plano)
    por_id = {e["id"]: e for e in plano}
    try:
        for id_ in a.ids:
            if id_ not in por_id:
                raise KeyError(id_)
            # Só a captura deste snapshot (mesma URL e timestamp do plano) e completa conta como vista;
            # sem ela, aprovar é recusado (rejeitar continua possível).
            if a.resolucao:
                data_captura = templates.data_captura_extra_valida(a.raiz, por_id[id_], a.resolucao)
                templates.marcar_aprovacao_extra(plano, id_, a.resolucao, aprovado, motivo, data_captura=data_captura)
                continue
            data_captura = templates.data_captura_valida(a.raiz, por_id[id_])
            templates.marcar_aprovacao(plano, id_, aprovado, motivo, data_captura=data_captura)
    except KeyError as erro:
        sys.exit(f"id não encontrado no plano: {erro.args[0]} (nenhuma alteração gravada)")
    except ValueError as erro:
        sys.exit(f"{erro} (nenhuma alteração gravada)")
    gravar_json(a.plano, plano)
    print(f"{len(a.ids)} entrada(s) marcada(s) como {'aprovada' if aprovado else 'rejeitada'}")


def cmd_aprovar(a):
    _marcar(a, True, "")


def cmd_rejeitar(a):
    _marcar(a, False, a.motivo)


# ---------------------------------------------------------------- linha de comando

def criar_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    sub = p.add_subparsers(dest="comando", required=True)
    extras = sorted(templates.RESOLUCOES_EXTRAS)

    s = sub.add_parser("planejar", help="consulta o Wayback e grava o plano de snapshots")
    s.add_argument("--marcas", required=True, help="tabela de marcas com as variantes de login (JSON)")
    s.add_argument("--plano", required=True, help="plano de snapshots a gravar (JSON versionado)")
    s.set_defaults(func=cmd_planejar)

    s = sub.add_parser("capturar", help="renderiza as entradas pendentes do plano")
    s.add_argument("--plano", required=True)
    s.add_argument("--raiz", required=True, help="pasta de saída (ex.: data/templates, fora do git)")
    s.add_argument("--so", nargs="+", metavar="ID", help="capturar só estas entradas")
    s.set_defaults(func=cmd_capturar)

    s = sub.add_parser("capturar-extra", help="captura as entradas aprovadas numa resolução extra")
    s.add_argument("--plano", required=True)
    s.add_argument("--raiz", required=True)
    s.add_argument("--resolucao", required=True, choices=extras)
    s.add_argument("--so", nargs="+", metavar="ID", help="capturar só estas entradas")
    s.set_defaults(func=cmd_capturar_extra)

    s = sub.add_parser("revisar", help="gera <raiz>/revisao.html (ou revisao_<resolucao>.html) com as miniaturas")
    s.add_argument("--plano", required=True)
    s.add_argument("--raiz", required=True)
    s.add_argument("--resolucao", choices=extras, help="revisar uma resolução extra")
    s.set_defaults(func=cmd_revisar)

    s = sub.add_parser("aprovar", help="aprova entradas do plano (só aprovadas entram na base)")
    s.add_argument("--plano", required=True)
    s.add_argument("--raiz", required=True, help="pasta das capturas (para registrar qual captura foi vista)")
    s.add_argument("--resolucao", choices=extras, help="decidir só esta resolução extra")
    s.add_argument("ids", nargs="+", metavar="ID")
    s.set_defaults(func=cmd_aprovar)

    s = sub.add_parser("rejeitar", help="rejeita uma entrada do plano, com o motivo")
    s.add_argument("--plano", required=True)
    s.add_argument("--raiz", required=True, help="pasta das capturas (para registrar qual captura foi vista)")
    s.add_argument("--resolucao", choices=extras, help="decidir só esta resolução extra")
    s.add_argument("ids", nargs=1, metavar="ID")
    s.add_argument("--motivo", required=True)
    s.set_defaults(func=cmd_rejeitar)
    return p


def main():
    a = criar_parser().parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
