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

  if (vista === 'condicoes') vistaCondicoes();
  else raiz.innerHTML = '<p class="aviso">Em construção.</p>';
})();
