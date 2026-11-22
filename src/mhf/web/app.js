// MHF — interface de demonstração. Todo texto vindo do servidor entra por textContent (o título de uma
// página aberta ao vivo pode conter HTML).
"use strict";

const PARTES_TEMPO = [
  ["abrir", "abrir a captura"], ["phash", "pHash"], ["busca_h", "busca pelo pHash"],
  ["embedding", "embedding"], ["estrutural", "DOM"], ["busca_es", "busca por embedding e DOM"],
  ["classificador", "classificador"],
];
const CORES_TEMPO = ["#1C2733", "#2F5E8C", "#8FA9C4", "#5B83AD", "#5B6B7A", "#A9B6C3", "#3E4C5A"];
const NOMES_CLASSE = { "1366x768": "1366 × 768 (notebook)", "1280x960": "1280 × 960", "1920x1080": "1920 × 1080 (Full HD)" };

const $ = (id) => document.getElementById(id);
let estado = null;
let exemploAtual = null;

function numero(v, casas = 3) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function el(tag, texto, classe) {
  const e = document.createElement(tag);
  if (texto !== undefined && texto !== null) e.textContent = texto;
  if (classe) e.className = classe;
  return e;
}

function mostrar(qual) {
  for (const id of ["estado-inicial", "estado-carregando", "estado-erro", "resultado"]) $(id).hidden = id !== qual;
}

async function pedir(metodo, caminho, corpo) {
  const r = await fetch(caminho, {
    method: metodo, headers: { "Content-Type": "application/json" },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  let dados = null;
  try { dados = await r.json(); } catch (e) { /* resposta sem JSON */ }
  if (!r.ok) throw new Error((dados && dados.erro) || `o servidor respondeu ${r.status}`);
  return dados;
}

// ---------------------------------------------------------------- estado inicial

function preencherEstado(e) {
  estado = e;
  $("resumo").textContent = `Modelo: ${e.modelo}. Base: ${e.templates} templates de ${e.marcas} marcas. ` +
    `Limiar τ = ${numero(e.tau)}. Tudo roda localmente, nesta máquina.`;

  const listas = { acerto: $("lista-acertos"), erro: $("lista-erros") };
  for (const ex of e.exemplos) {
    const li = el("li");
    const b = el("button");
    b.type = "button";
    b.dataset.numero = ex.numero;
    b.append(el("span", String(ex.numero), "num"), el("span", ex.titulo));
    if (!ex.disponivel) { b.disabled = true; b.title = ex.motivo; }
    b.addEventListener("click", () => analisarExemplo(ex.numero));
    li.append(b);
    (listas[ex.grupo] || listas.erro).append(li);
  }
  for (const [grupo, titulo] of [["acerto", "titulo-acertos"], ["erro", "titulo-erros"]]) {
    $(titulo).hidden = listas[grupo].children.length === 0;
  }
  if (!e.exemplos.length) {
    $("sem-exemplos").hidden = false;
    $("sem-exemplos").textContent = "Nenhum exemplo configurado. Gere a lista com scripts/escolher_exemplos.py (README, passo 7).";
  } else if (!e.exemplos.some((x) => x.disponivel)) {
    $("sem-exemplos").hidden = false;
    $("sem-exemplos").textContent = e.exemplos[0].motivo;
  }

  const classe = $("campo-classe");
  for (const c of e.classes) {
    const o = el("option", NOMES_CLASSE[c] || c); o.value = c; if (c === e.classe_padrao) o.selected = true; classe.append(o);
  }
  const idioma = $("campo-idioma");
  for (const i of e.idiomas) { const o = el("option", i); o.value = i; idioma.append(o); }
  $("aviso-url").textContent = e.aviso_url;
  if (!e.navegador) {
    $("aviso-url").textContent = "A análise por URL está desligada nesta execução (--sem-navegador).";
    $("form-url").querySelectorAll("input, select, button").forEach((x) => { x.disabled = true; });
  }

  if (e.urls_sugeridas.length) {
    $("sugestoes-bloco").hidden = false;
    for (const s of e.urls_sugeridas) {
      const li = el("li");
      const real = el("button", "Domínio real", "botao-leve");
      const sim = el("button", "Simulado", "botao-leve");
      real.type = sim.type = "button";
      real.title = s.url;
      sim.title = `${s.url} analisada como se estivesse em ${s.url_simulada}`;
      real.addEventListener("click", () => usarSugestao(s, false));
      sim.addEventListener("click", () => usarSugestao(s, true));
      li.append(el("span", s.titulo), real, sim);
      $("sugestoes").append(li);
    }
  }
}

function usarSugestao(s, simulado) {
  $("campo-url").value = s.url;
  if (s.classe) $("campo-classe").value = s.classe;
  if (s.idioma) $("campo-idioma").value = s.idioma;
  $("campo-simulado").value = simulado ? (s.url_simulada || "") : "";
  analisarUrl();
}

// ---------------------------------------------------------------- análises

function marcarExemplo(n) {
  exemploAtual = n;
  document.querySelectorAll(".exemplos button").forEach((b) => {
    b.setAttribute("aria-current", String(Number(b.dataset.numero) === n));
  });
}

async function analisarExemplo(n) {
  marcarExemplo(n);
  $("texto-carregando").textContent = "Analisando…";
  mostrar("estado-carregando");
  try {
    const r = await pedir("POST", "/api/exemplo", { numero: n, url_simulada: $("campo-simulado").value.trim() || null });
    mostrarResultado(r);
  } catch (e) {
    mostrarErro(e.message);
  }
}

async function analisarUrl() {
  marcarExemplo(null);
  const botao = $("botao-url");
  botao.disabled = true;
  $("texto-carregando").textContent = "Abrindo a página e esperando o formulário de login (até 20 s)…";
  mostrar("estado-carregando");
  try {
    const r = await pedir("POST", "/api/url", {
      url: $("campo-url").value, classe: $("campo-classe").value, idioma: $("campo-idioma").value,
      url_simulada: $("campo-simulado").value.trim() || null,
    });
    mostrarResultado(r);
  } catch (e) {
    mostrarErro(e.message);
  } finally {
    botao.disabled = false;
  }
}

function mostrarErro(msg) {
  $("texto-erro").textContent = `Não foi possível analisar: ${msg}`;
  mostrar("estado-erro");
}

// ---------------------------------------------------------------- resultado

function mostrarResultado(r) {
  const phishing = r.veredito.rotulo === "phishing";
  const v = $("veredito");
  v.className = `veredito ${phishing ? "phishing" : "legitima"}`;
  void v.offsetWidth; // reinicia a animação
  v.classList.add("aparece");
  $("veredito-icone").textContent = phishing ? "⚠" : "✓";
  $("veredito-titulo").textContent = r.veredito.titulo;
  $("veredito-frase").textContent = r.veredito.frase;

  $("real").hidden = !r.real;
  if (r.real) {
    $("real-texto").textContent = r.real.texto + ".";
    $("real-frase").textContent = r.real.frase;
    $("real-nota").textContent = r.real.nota;
  }

  $("pagina-aberta").hidden = !r.pagina;
  if (r.pagina) {
    const p = r.pagina;
    let urls = `Aberta: ${p.url_digitada}`;
    if (p.url_final !== p.url_digitada) urls += `; redirecionada para ${p.url_final}`;
    if (p.titulo) urls += `; título: “${p.titulo}”`;
    if (p.status) urls += `; HTTP ${p.status}`;
    if (p.status >= 400) urls += " (o site pode ter bloqueado o navegador automatizado)";
    if (!p.credencial) urls += "; nenhum campo de login apareceu";
    $("pagina-urls").textContent = urls + ".";
    $("pagina-tempo").textContent = `Abrir a página no navegador automatizado: ${numero(p.tempo_abrir_s, 1)} s ` +
      "(na extensão a página já está aberta, então esse tempo não existe).";
  }

  $("img-pagina").src = r.captura || "";
  $("legenda-pagina").textContent = `(${NOMES_CLASSE[r.classe] || r.classe})`;
  const t = r.template;
  $("img-template").hidden = !t;
  $("sem-template").hidden = !!t;
  $("elo").hidden = !t;
  if (t) {
    $("img-template").src = t.url;
    $("legenda-template").textContent = `(${t.marca}, ${t.variante}, ${t.ano}, ${t.origem})`;
    $("elo-valor").textContent = numero(t.cosseno);
  } else {
    $("img-template").removeAttribute("src");
    $("legenda-template").textContent = "";
  }
  $("legenda-bancada").textContent = r.legenda_template;

  desenharEscores(r);
  desenharSinais(r);

  $("dominio").textContent = r.dominio || "(sem domínio)";
  $("etiqueta-simulado").hidden = !r.dominio_simulado;
  $("dominios-oficiais").textContent = r.marca && r.dominios_oficiais.length
    ? `Domínios oficiais de ${r.marca}: ${r.dominios_oficiais.join(", ")}.` : "";

  desenharTempo(r.tempos_ms);
  mostrar("resultado");
}

function desenharEscores(r) {
  const caixa = $("escores");
  caixa.replaceChildren();
  if (!r.escores.length) { caixa.append(el("p", "Nenhum escore (a página não chegou ao classificador).", "explica")); return; }
  for (const s of r.escores) {
    const linha = el("div", null, "escore" + (s.marca === r.marca ? " destaque" : ""));
    const trilho = el("div", null, "trilho");
    const valor = el("div", null, "valor");
    valor.style.width = `${Math.max(0, Math.min(1, s.escore)) * 100}%`;
    trilho.append(valor);
    linha.append(el("span", s.marca), trilho, el("span", numero(s.escore), "numero"));
    caixa.append(linha);
  }
  // a linha do limiar atravessa as barras: uma camada com as mesmas colunas das linhas, em porcentagem
  // (acompanha qualquer mudança de largura sem recalcular nada)
  const sobre = el("div", null, "sobreposicao");
  const faixa = el("div", null, "faixa");
  const limiar = el("div", null, "limiar");
  limiar.style.left = `${Math.max(0, Math.min(1, r.tau)) * 100}%`;
  limiar.append(el("span", `τ ${numero(r.tau)}`));
  faixa.append(limiar);
  sobre.append(el("span"), faixa, el("span"));
  caixa.prepend(sobre);
}

function desenharSinais(r) {
  $("sinais-marca").textContent = r.marca || "—";
  const corpo = $("sinais").tBodies[0];
  corpo.replaceChildren();
  for (const s of r.sinais) {
    const tr = el("tr");
    const valor = el("td");
    if (typeof s.valor === "number" && !["hash_igual", "s_ausente"].includes(s.nome)) {
      const mini = el("span", null, "mini");
      const barra = el("i");
      barra.style.width = `${Math.max(0, Math.min(1, s.valor)) * 100}%`;
      mini.append(barra);
      valor.append(mini);
    }
    valor.append(document.createTextNode(s.texto));
    tr.append(el("td", s.rotulo), valor);
    corpo.append(tr);
  }
}

function desenharTempo(tempos) {
  $("tempo-total").textContent = `${tempos.total ?? "—"} ms`;
  const barra = $("barra-tempo");
  const lista = $("partes-tempo");
  barra.replaceChildren();
  lista.replaceChildren();
  const partes = PARTES_TEMPO.filter(([k]) => tempos[k] !== undefined);
  const soma = partes.reduce((a, [k]) => a + tempos[k], 0) || 1;
  partes.sort((a, b) => tempos[b[0]] - tempos[a[0]]);
  partes.forEach(([k, nome], i) => {
    const cor = CORES_TEMPO[i % CORES_TEMPO.length];
    const seg = el("i");
    seg.style.width = `${(tempos[k] / soma) * 100}%`;
    seg.style.background = cor;
    barra.append(seg);
    const item = el("li");
    const amostra = el("b");
    amostra.style.background = cor;
    item.append(amostra, document.createTextNode(`${nome} ${tempos[k]} ms`));
    lista.append(item);
  });
}

// ---------------------------------------------------------------- abas e eventos

function trocarAba(qual) {
  const exemplos = qual === "exemplos";
  $("aba-exemplos").setAttribute("aria-selected", String(exemplos));
  $("aba-url").setAttribute("aria-selected", String(!exemplos));
  $("painel-exemplos").hidden = !exemplos;
  $("painel-url").hidden = exemplos;
}

$("aba-exemplos").addEventListener("click", () => trocarAba("exemplos"));
$("aba-url").addEventListener("click", () => trocarAba("url"));
$("form-url").addEventListener("submit", (ev) => { ev.preventDefault(); analisarUrl(); });
$("limpar-simulado").addEventListener("click", () => {
  $("campo-simulado").value = "";
  if (exemploAtual !== null) analisarExemplo(exemploAtual);
});
$("campo-simulado").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && exemploAtual !== null) { ev.preventDefault(); analisarExemplo(exemploAtual); }
});

pedir("GET", "/api/estado").then(preencherEstado).catch((e) => {
  $("resumo").textContent = `Não foi possível falar com o servidor: ${e.message}`;
});
