/* explorador.js — as três vistas. Uma só página por vez; `body[data-vista]` decide qual.
 *
 * O estado da vista de comparação vive na barra de endereço, não em memória: assim um
 * achado — "olha a questão 41-peca-civil na condição X contra a Y" — é um link que se cola
 * numa mensagem, e não uma sequência de cliques para o outro repetir.
 */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const raiz = $('#raiz');
  const vista = document.body.dataset.vista;
  const api = (r) => fetch(r).then(x => x.json());
  const esc = (s) => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };
  const pct = (v) => v === null || v === undefined ? '—' : v.toFixed(1).replace('.', ',') + '%';

  const url = new URLSearchParams(location.search);
  const guarda = (k, v) => {
    if (v) url.set(k, v); else url.delete(k);
    history.replaceState(null, '', location.pathname + '?' + url);
  };

  // ─────────────────────────────── comparar condições
  async function vistaCondicoes() {
    raiz.innerHTML = '<p class="aviso">carregando…</p>';
    const [qs, cs] = await Promise.all([api('/api/questoes'), api('/api/condicoes')]);
    const comResposta = cs.filter(c => c.tem_resposta);

    const opQ = qs.map(q => `<option value="${q.id}">${q.id} · ${q.tipo} · ${esc(q.area)} · ${q.criterios} critérios</option>`).join('');
    const opC = (sel) => '<option value="">—</option>' + comResposta.map(c =>
      `<option value="${c.cond}"${c.cond === sel ? ' selected' : ''}>${esc(c.rotulo)}</option>`).join('');

    raiz.innerHTML = `
      <div class="barra">
        <div class="campo"><label>questão</label><select id="q" style="min-width:330px">${opQ}</select></div>
        <div class="campo a"><label>condição A</label><select id="a" style="min-width:300px">${opC(url.get('a'))}</select></div>
        <div class="campo b"><label>condição B</label><select id="b" style="min-width:300px">${opC(url.get('b'))}</select></div>
        <div class="campo"><label>execução</label><select id="run"></select></div>
        <button id="so-div">só onde divergem</button>
      </div>
      <div id="saida"></div>`;

    if (url.get('q')) $('#q').value = url.get('q');
    let soDiverg = false;
    $('#so-div').addEventListener('click', (e) => {
      soDiverg = !soDiverg; e.target.classList.toggle('sel', soDiverg); pinta();
    });
    ['q', 'a', 'b', 'run'].forEach(k => $('#' + k).addEventListener('change', () => {
      guarda(k, $('#' + k).value); carrega(k !== 'run');
    }));

    let dado = null;
    async function carrega(resetRun) {
      const q = $('#q').value, a = $('#a').value, b = $('#b').value;
      guarda('q', q); guarda('a', a); guarda('b', b);
      if (!a && !b) { $('#saida').innerHTML = '<p class="aviso">Escolha ao menos uma condição.</p>'; return; }
      const run = resetRun ? (url.get('run') || 0) : $('#run').value;
      $('#saida').innerHTML = '<p class="aviso">carregando…</p>';
      dado = await api(`/api/comparar?q=${encodeURIComponent(q)}&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&run=${run}`);
      const execs = (dado.lados.find(l => l) || {}).execucoes || [];
      $('#run').innerHTML = execs.map(e => `<option value="${e}"${String(e) === String(run) ? ' selected' : ''}>execução ${e + 1}</option>`).join('');
      pinta();
    }

    function pinta() {
      if (!dado) return;
      const q = dado.questao, lados = dado.lados;
      const crits = (q.criterios || []);
      const linhas = crits.map(c => {
        const cid = c.id ?? c.criterio_id ?? `${c.letra ?? c.numero ?? ''}-${c.parte ?? ''}`;
        const vs = lados.map(l => l ? l.vereditos[cid] : undefined);
        const diverge = vs[0] !== undefined && vs[1] !== undefined && vs[0] !== vs[1];
        if (soDiverg && !diverge) return '';
        const meta = (lados.find(l => l && l.meta[cid]) || { meta: {} }).meta[cid] || {};
        const cel = (v) => v === undefined ? '<td class="v">—</td>'
          : `<td class="v ${v ? 'sim' : 'nao'}">${v ? '✓' : '✗'}</td>`;
        return `<tr class="${diverge ? 'diverge' : ''}">
          <td><span class="cid">${esc(cid)}</span>${meta.titulo ? ` · ${esc(meta.titulo)}` : ''}
              ${meta.classe ? `<div class="classe">${esc(meta.classe)}</div>` : ''}
              <div>${esc(c.texto ?? c.descricao ?? c.gabarito ?? '')}</div></td>
          <td class="pts">${(meta.pontuacao_max ?? 0).toFixed(2).replace('.', ',')}</td>
          ${cel(vs[0])}${cel(vs[1])}</tr>`;
      }).join('');

      const painel = (l, cls) => !l ? '' : `
        <div class="lado ${cls}"><h3><span>${esc(l.rotulo)}</span>
          <span class="nota">${pct(l.nota)} <span class="classe">nesta execução · média ${pct(l.nota_media)}</span></span></h3>
          ${l.resposta ? `<div class="txt">${esc(l.resposta)}</div>`
                       : '<p class="vazio">sem resposta guardada para esta execução</p>'}</div>`;

      $('#saida').innerHTML = `
        <div class="enunciado"><div class="rot">${esc(q.id)} · ${esc(q.area)} · exame ${esc(q.exame)} · ${esc(q.tipo)}</div>${esc(q.enunciado)}</div>
        <div class="resumo"><span>critérios: <b>${crits.length}</b></span>
          <span>divergem entre A e B: <b>${dado.divergem.length}</b></span></div>
        <div class="par">${painel(lados[0], 'a')}${painel(lados[1], 'b')}</div>
        <table><thead><tr><th>Critério</th><th>Pontos</th><th class="v">A</th><th class="v">B</th></tr></thead>
        <tbody>${linhas || '<tr><td colspan="4" class="aviso">nenhuma divergência</td></tr>'}</tbody></table>`;
      $('#dir').textContent = `${crits.length} critérios · ${dado.divergem.length} divergências`;
    }
    carrega(true);
  }


  /* ── régua: os juízes contra o padrão-ouro, e os respondentes na mesma tarefa.
   *
   * Duas tabelas na mesma tela e no mesmo eixo de áreas. É a leitura que o artigo faz em
   * duas tabelas separadas por limite de página; aqui não há limite, então ficam juntas.
   */
  // As mesmas abreviaturas do artigo. Cortar o nome em N letras produzia "CONSTI." e
  // "TRABAL.", que ninguém escreve.
  const ABREV = { 'administrativo': 'Adm.', 'civil': 'Civ.', 'constitucional': 'Const.',
                  'empresarial': 'Empr.', 'penal': 'Pen.', 'trabalhista': 'Trab.',
                  'tributário': 'Trib.' };

  async function vistaRegua() {
    const TAREFAS = [['peca_merito', 'peça · mérito'], ['peca_formal', 'peça · forma'],
                     ['discursiva', 'questão discursiva']];
    let tarefa = url.get('tarefa') || 'peca_merito';
    raiz.innerHTML = `<div class="barra">
      <label>tarefa <select id="tk">${TAREFAS.map(([v, r]) =>
        `<option value="${v}"${v === tarefa ? ' selected' : ''}>${r}</option>`).join('')}</select></label>
      <span class="dica">κ &times;100 · nota em % dos pontos da banca</span></div>
      <div id="corpo"></div>`;
    const corpo = $('#corpo');

    const tabela = (titulo, nota, areas, linhas, fmt, extra) => `
      <h2>${titulo}</h2><p class="nota">${nota}</p>
      <div class="rol"><table class="regua">
        <thead><tr><th>modelo</th>${areas.map(a =>
          `<th class="n">${esc(ABREV[a] || a)}</th>`).join('')}<th class="n z">geral</th>${
          extra ? '<th class="n">ampl.</th>' : ''}</tr></thead>
        <tbody>${linhas.map(l => {
          const vs = l.areas.filter(x => x !== null && x !== undefined);
          const max = vs.length ? Math.max(...vs) : null;
          return `<tr${l.producao ? ' class="hl"' : ''}><td><code>${esc(l.nome)}</code>${
            l.producao ? ' <span class="tag">produção</span>' : ''}</td>${
            l.areas.map(x => `<td class="n${x !== null && x === max ? ' melhor' : ''}">${
              fmt(x)}</td>`).join('')}<td class="n z">${fmt(l.geral)}</td>${
            extra ? `<td class="n">${fmt(l.ampl)}</td>` : ''}</tr>`;
        }).join('')}</tbody></table></div>`;

    async function carrega() {
      corpo.innerHTML = '<p class="vazio">carregando…</p>';
      const d = await api('/api/regua?tarefa=' + encodeURIComponent(tarefa));
      if (d.erro) { corpo.innerHTML = `<p class="vazio">${esc(d.erro)}</p>`; return; }
      const k = (x) => x === null || x === undefined ? '—' : Math.round(x * 100);
      const n = (x) => x === null || x === undefined ? '—' : x.toFixed(1).replace('.', ',');
      corpo.innerHTML =
        tabela(`Concordância com o padrão-ouro humano · ${esc(d.rotulo)}`,
               'κ de Cohen contra as decisões dos três juristas, por área do direito. '
               + 'A coluna ampl. é a distância entre a melhor e a pior área do mesmo juiz.',
               d.areas, d.juizes, k, true)
        + tabela(`Nota dos mesmos modelos como respondentes · ${esc(d.rotulo)}`,
                 'Percentual dos pontos da banca, ponderado pela pontuação de cada critério.',
                 d.areas, d.respondentes, n, false);
    }
    $('#tk').onchange = (e) => { tarefa = e.target.value; guarda('tarefa', tarefa); carrega(); };
    carrega();
  }

  /* ── anotar: decisão binária cega, para estender o padrão-ouro.
   *
   * A tela mostra enunciado, resposta e UM critério. Não mostra o gabarito do item, nem o
   * veredito de nenhum juiz, nem o que outro anotador decidiu: qualquer um dos três
   * transformaria a anotação numa conferência, que mede outra coisa.
   */
  async function vistaAnotar() {
    let quem = localStorage.getItem('anotador') || '';
    let atual = null, feitas = 0;
    raiz.innerHTML = `<div class="barra">
      <label>anotador <input id="quem" value="${esc(quem)}" placeholder="seu nome"></label>
      <span class="dica" id="conta"></span></div><div id="cartao"></div>`;
    const cartao = $('#cartao');

    async function proxima() {
      cartao.innerHTML = '<p class="vazio">carregando…</p>';
      const d = await api('/api/anotar/proxima');
      if (d.erro) { cartao.innerHTML = `<p class="vazio">${esc(d.erro)}</p>`; return; }
      atual = d;
      cartao.innerHTML = `
        <p class="cab">${esc(d.genero)} · ${esc(d.area)} · exame ${esc(String(d.exame))}
           · critério ${d.indice} de ${d.total_criterios}${
             d.pontos ? ' · vale ' + String(d.pontos).replace('.', ',') : ''}</p>
        <div class="cols">
          <section><h3>enunciado</h3><div class="texto">${esc(d.enunciado)}</div></section>
          <section><h3>resposta avaliada</h3><div class="texto">${
            d.resposta ? esc(d.resposta) : '<i>sem resposta guardada para esta questão</i>'}</div></section>
        </div>
        <section class="crit"><h3>o critério</h3>
          ${d.titulo_criterio ? `<p class="tit">${esc(d.titulo_criterio)}</p>` : ''}
          <p class="texto">${esc(d.texto_criterio)}</p></section>
        <div class="acoes">
          <button id="sim" class="sim">cumpriu</button>
          <button id="nao" class="nao">não cumpriu</button>
          <button id="pula" class="pula">pular</button>
        </div>`;
      $('#sim').onclick = () => grava(1);
      $('#nao').onclick = () => grava(0);
      $('#pula').onclick = proxima;
    }

    async function grava(atendeu) {
      quem = $('#quem').value.trim();
      if (!quem) { $('#quem').focus(); return; }
      localStorage.setItem('anotador', quem);
      const r = await fetch('/api/anotacoes/' + encodeURIComponent(quem), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ questao: atual.questao, criterio: atual.criterio, atendeu }),
      }).then(x => x.json());
      feitas = r.anotados ?? feitas + 1;
      $('#conta').textContent = feitas + ' anotado(s)';
      proxima();
    }

    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || !atual) return;
      if (e.key === 's' || e.key === 'S') grava(1);
      if (e.key === 'n' || e.key === 'N') grava(0);
    });
    proxima();
  }

  /* Mapa, e não uma cadeia de `if`: com `else` pendurado no último `if`, toda vista que
   * não fosse a última caía no aviso de "em construção" mesmo já estando escrita. */
  const VISTAS = { condicoes: vistaCondicoes, regua: vistaRegua, anotar: vistaAnotar };
  (VISTAS[vista] || (() => {
    raiz.innerHTML = '<p class="aviso">Vista desconhecida.</p>';
  }))();
})();
