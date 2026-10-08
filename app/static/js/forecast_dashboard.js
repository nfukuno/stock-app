/* 成績ダッシュボード: 集計は API(stats.py) 側。ここは描画のみ。 */
(function () {
  'use strict';
  var D = window.DASH, $ = function (id) { return document.getElementById(id); };
  var LABEL = {}; D.scenarios.forEach(function (s) { LABEL[s.key] = s.label; });
  var charts = {}, last = '';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function f(v, d, sign) { if (v == null) return '-'; var s = Number(v).toFixed(d == null ? 1 : d); return sign && v > 0 ? '+' + s : s; }
  function cls(v) { return v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : '')); }
  function chart(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart($(id), cfg); }
  var base = { responsive: true, maintainAspectRatio: false };

  function table(head, rows) {
    return '<table><thead><tr>' + head.map(function (h) { return '<th' + (h[1] ? ' class="num"' : '') + '>' + h[0] + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows.map(function (r) { return '<tr>' + r.map(function (c, i) { return '<td' + (head[i][1] ? ' class="num ' + (c[1] || '') + '"' : '') + '>' + (head[i][1] ? c[0] : c) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table>';
  }

  function render(res) {
    var s = res.summary, empty = !s.n;
    $('empty').style.display = empty ? 'block' : 'none';
    $('content').style.display = empty ? 'none' : 'block';
    if (empty) return;
    var k = s.kpi;
    $('kpis').innerHTML = [
      ['採点件数', k.n, ''], ['平均スコア', f(k.mean_total), ''],
      ['平均スキル（自分−横ばい）', f(k.mean_skill, 1, true), cls(k.mean_skill)],
      ['スキルがプラスだった割合', k.skill_positive_rate == null ? '-' : f(k.skill_positive_rate, 0) + '%', ''],
      ['方向的中率', k.direction_rate == null ? '-' : f(k.direction_rate, 0) + '%', ''],
      ['シナリオ的中率', k.scenario_rate == null ? '-' : f(k.scenario_rate, 0) + '%', '']
    ].map(function (x) { return '<div class="kpi"><div class="l">' + x[0] + '</div><div class="v ' + x[2] + '">' + x[1] + '</div></div>'; }).join('');

    chart('c_trend', { data: { labels: s.trend.map(function (t) { return t.label; }), datasets: [
      { type: 'line', label: '日別スコア', data: s.trend.map(function (t) { return t.total; }), showLine: false, pointRadius: 3, borderColor: '#9aa6c9', backgroundColor: '#9aa6c9' },
      { type: 'line', label: 'スコア(10件移動平均)', data: s.trend.map(function (t) { return t.ma; }), borderColor: '#2f5bea', pointRadius: 0, tension: .2 },
      { type: 'line', label: '横ばい予想(10件移動平均)', data: s.trend.map(function (t) { return t.flat_ma; }), borderColor: '#999', borderDash: [5, 4], pointRadius: 0, tension: .2 }] },
      options: Object.assign({}, base, { scales: { y: { min: 0, max: 100 }, x: { ticks: { maxTicksLimit: 10 } } } }) });

    var b = s.bias;
    $('b_opt').innerHTML = b.optimism == null ? '-' : '<b class="' + (b.optimism > 0 ? 'neg' : 'pos') + '">' + f(b.optimism, 2, true) + ' ATR</b>';
    $('b_rng').innerHTML = b.range_ratio == null ? '-' : '<b>' + f(b.range_ratio, 2) + ' 倍</b>';
    $('b_note').textContent = (b.optimism == null ? '' : (b.optimism > 0 ? '上に予想しがち（楽観）。' : (b.optimism < 0 ? '下に予想しがち（悲観）。' : '偏りなし。'))) +
      (b.range_ratio == null ? '' : (b.range_ratio < 1 ? '値幅を小さく見積もる傾向。' : '値幅を大きく見積もる傾向。'));
    chart('c_scatter', { type: 'scatter', data: { datasets: [
      { label: '予想 vs 実際', data: s.scatter, backgroundColor: 'rgba(47,91,234,.6)', pointRadius: 4 },
      { label: '一致ライン', type: 'line', data: [{ x: -3, y: -3 }, { x: 3, y: 3 }], borderColor: '#bbb', borderDash: [4, 4], pointRadius: 0 }] },
      options: Object.assign({}, base, { scales: { x: { title: { display: true, text: '実際の前日比(ATR)' } }, y: { title: { display: true, text: '予想の前日比(ATR)' } } },
        plugins: { tooltip: { callbacks: { label: function (c) { return (c.raw.label || '') + ' (' + c.raw.x + ', ' + c.raw.y + ')'; } } } } }) });

    chart('c_conf', { type: 'bar', data: { labels: s.by_confidence.map(function (r) { return '自信' + r.key + '（' + r.n + '件）'; }), datasets: [
      { label: '平均スコア', data: s.by_confidence.map(function (r) { return r.mean_total; }), backgroundColor: '#2f5bea' },
      { label: '平均スキル', data: s.by_confidence.map(function (r) { return r.mean_skill; }), backgroundColor: '#f59e0b' }] }, options: base });
    $('t_conf').innerHTML = table([['自信度'], ['件数', 1], ['平均スコア', 1], ['平均スキル', 1]],
      s.by_confidence.map(function (r) { return [r.key, [r.n], [f(r.mean_total)], [f(r.mean_skill, 1, true), cls(r.mean_skill)]]; }));

    $('t_scn').innerHTML = table([['予想シナリオ'], ['件数', 1], ['的中率', 1], ['平均スコア', 1]],
      s.by_scenario.map(function (r) { return [esc(LABEL[r.key] || r.key), [r.n], [r.hit_rate == null ? '-' : f(r.hit_rate, 0) + '%'], [f(r.mean_total)]]; }));

    var cm = s.confusion, keys = cm.rows;
    $('t_cm').innerHTML = '<table class="cm"><thead><tr><th></th>' + cm.cols.map(function (c) { return '<th>' + esc(LABEL[c]) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      cm.matrix.map(function (row, i) { return '<tr><th style="writing-mode:horizontal-tb;text-align:right;font-size:12px">' + esc(LABEL[keys[i]]) + '</th>' +
        row.map(function (v, j) { return '<td class="' + (i === j ? 'diag' : '') + (v ? '' : ' z') + '">' + (v || '·') + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table>';

    var g = function (rows, name) { return table([[name], ['件数', 1], ['平均スコア', 1], ['平均スキル', 1]],
      rows.map(function (r) { return [esc(r.label || r.key), [r.n], [f(r.mean_total)], [f(r.mean_skill, 1, true), cls(r.mean_skill)]]; })); };
    $('t_sym').innerHTML = g(s.by_symbol, '銘柄'); $('t_wd').innerHTML = g(s.by_weekday, '曜日');

    $('reviews').innerHTML = s.recent.map(function (r) {
      var hit = r.scenario_hit === true ? '○' : (r.scenario_hit === false ? '✕' : '－');
      return '<div class="rcard"><div><b>' + esc(r.target_date) + '</b> ' + esc(r.symbol) + ' ' + esc(r.name) + (r.late ? ' <span class="badge late">遅延</span>' : '') + '</div>' +
        '<img alt="予想と実際の比較" src="' + D.pagesUrl + '/output/forecast/' + encodeURIComponent(r.id) + '.png" onerror="this.style.visibility=\'hidden\'">' +
        '<div><b>' + f(r.total) + '点</b> <span class="' + cls(r.skill) + '">（横ばい比 ' + f(r.skill, 1, true) + '）</span></div>' +
        '<div class="bd">方向 ' + f(r.direction, 0) + ' / 終値 ' + f(r.close_s, 0) + ' / 始値 ' + f(r.open_s, 0) + ' / 値幅IoU ' + f(r.range_iou, 0) + ' / 実体IoU ' + f(r.body_iou, 0) + ' / ヒゲ ' + f(r.shadow, 0) + '</div>' +
        '<div class="bd">シナリオ ' + hit + ' 予想:' + esc(LABEL[r.scenario] || r.scenario) + ' / 実際:' + esc(LABEL[r.actual_scenario] || r.actual_scenario) + ' ・ 自信' + esc(r.confidence) + '</div>' +
        (r.memo ? '<div class="memo">' + esc(r.memo) + '</div>' : '') + '</div>';
    }).join('');
  }

  async function load() {
    var q = new URLSearchParams();
    if (last) q.set('last', last);
    if ($('symbol').value) q.set('symbol', $('symbol').value);
    if ($('late').checked) q.set('include_late', 'true');
    $('status').textContent = '読み込み中…';
    try {
      var r = await fetch('/api/forecast/results?' + q.toString());
      if (!r.ok) { var e = await r.json().catch(function () { return {}; }); throw new Error(e.detail || r.status); }
      render(await r.json()); $('status').textContent = '';
    } catch (e) { $('status').textContent = '読み込み失敗: ' + e.message; }
  }
  document.querySelectorAll('#period button').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('#period button').forEach(function (x) { x.classList.remove('on'); });
      b.classList.add('on'); last = b.dataset.last; load();
    });
  });
  $('symbol').addEventListener('change', load); $('late').addEventListener('change', load);
  load();
})();
