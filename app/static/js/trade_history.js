// トレード分析画面: 成績サマリー・損益曲線・切り口別・約定履歴
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var yen = function (v) { return v == null ? '-' : Math.round(v).toLocaleString('ja-JP'); };
  var signed = function (v) { return v == null ? '-' : (v > 0 ? '+' : '') + yen(v); };
  var pct = function (v) { return v == null ? '-' : (v * 100).toFixed(1) + '%'; };
  var cls = function (v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : ''; };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); };
  var dt = function (iso) { return iso.slice(5, 16).replace('T', ' '); };
  var hold = function (m) { return m == null ? '-' : m < 60 ? Math.round(m) + '分' : m < 1440 ? (m / 60).toFixed(1) + '時間' : (m / 1440).toFixed(1) + '日'; };

  function curve(points) {
    if (!points.length) return '<span class="muted">まだ返済した取引がありません</span>';
    var W = 1000, H = 220, P = 36;
    var ys = [0].concat(points.map(function (p) { return p.cum; }));
    var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    if (hi === lo) { hi += 1; lo -= 1; }
    var x = function (i) { return P + (W - 2 * P) * i / Math.max(1, points.length); };
    var y = function (v) { return H - P / 2 - (H - P) * (v - lo) / (hi - lo); };
    var d = 'M' + x(0) + ',' + y(0) + points.map(function (p, i) { return ' L' + x(i + 1) + ',' + y(p.cum); }).join('');
    var last = points[points.length - 1].cum;
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img" aria-label="損益曲線">' +
      '<line x1="' + P + '" x2="' + (W - P) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="#ccd" stroke-dasharray="4 4"/>' +
      '<path d="' + d + '" fill="none" stroke="' + (last >= 0 ? 'var(--ok)' : 'var(--ng)') + '" stroke-width="2"/>' +
      '<text x="2" y="' + (y(hi) + 4) + '">' + yen(hi) + '</text><text x="2" y="' + (y(lo) + 4) + '">' + yen(lo) + '</text>' +
      '<text x="' + (W - P) + '" y="' + (y(last) - 6) + '" text-anchor="end">' + signed(last) + '</text></svg>';
  }

  function group(title, rows) {
    return '<div class="card"><h2>' + title + '</h2><table><thead><tr><th></th><th class="num">件数</th><th class="num">勝率</th>' +
      '<th class="num">損益合計</th><th class="num">平均</th></tr></thead><tbody>' +
      (rows.length ? rows.map(function (r) {
        return '<tr><td>' + esc(r.key) + '</td><td class="num">' + r.n + '</td><td class="num">' + pct(r.win_rate) + '</td>' +
          '<td class="num ' + cls(r.total) + '">' + signed(r.total) + '</td><td class="num ' + cls(r.avg) + '">' + signed(r.avg) + '</td></tr>';
      }).join('') : '<tr><td colspan="5" class="muted">-</td></tr>') + '</tbody></table></div>';
  }

  var items = {};

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-edit]');
    if (b && items[b.dataset.edit]) TradeEdit.open('trade', items[b.dataset.edit], load);
  });

  function load() {
  fetch('/api/trade/trades').then(function (r) {
    return r.text().then(function (t) {
      var j; try { j = JSON.parse(t); } catch (e) { throw new Error(t || r.statusText); }
      if (!r.ok) throw new Error(j.detail || r.statusText);
      return j;
    });
  }).then(function (j) {
    var s = j.stats;
    $('acct').textContent = '口座 ' + j.account_id + '（初期保証金 ' + yen(j.initial_cash) + ' 円）';
    var k = [
      ['取引数', s.n + '（' + s.wins + '勝 ' + s.losses + '敗）'],
      ['勝率', pct(s.win_rate)],
      ['損益合計', signed(s.total), cls(s.total)],
      ['期待値（1取引）', signed(s.avg), cls(s.avg)],
      ['平均R', s.avg_r == null ? '-' : s.avg_r.toFixed(2) + 'R（' + s.r_count + '件）', cls(s.avg_r)],
      ['プロフィットファクター', s.profit_factor == null ? '-' : s.profit_factor.toFixed(2)],
      ['平均利益 / 平均損失', signed(s.avg_win) + ' / ' + signed(s.avg_loss)],
      ['最大ドローダウン', yen(s.max_drawdown), s.max_drawdown ? 'neg' : ''],
      ['最大連敗', s.max_loss_streak],
      ['平均保有（勝 / 負）', hold(s.avg_hold_win) + ' / ' + hold(s.avg_hold_loss)],
      ['損切り設定率', pct(s.stop_set_rate)],
      ['損切りライン超えの決済', s.beyond_stop + '件', s.beyond_stop ? 'neg' : ''],
      ['ナンピン', s.nanpin_count + '回', s.nanpin_count ? 'neg' : ''],
    ];
    $('kpis').innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + x[0] + '</div><div class="v ' + (x[2] || '') + '">' + x[1] + '</div></div>';
    }).join('');
    $('curve').innerHTML = curve(s.curve);
    $('groups').innerHTML = [
      group('エントリー理由別', s.by_tag), group('時間帯別（建てた時刻）', s.by_hour), group('曜日別', s.by_weekday),
      group('ナンピン・増し玉別（追加した建玉）', s.by_add_type), group('ナンピンした建玉群とそれ以外', s.by_nanpin_group),
      group('感情別', s.by_emotion), group('売買別', s.by_side), group('信用区分別', s.by_margin_type), group('銘柄別', s.by_symbol),
    ].join('');
    items = {};
    $('trades').innerHTML = j.trades.length ? j.trades.map(function (t) {
      items[t.id] = t;
      return '<tr><td>' + t.id + '<br>' + TradeEdit.button(t.id) + '</td><td>' + dt(t.opened_at) + ' → ' + dt(t.closed_at) + '</td><td>' + esc(t.symbol) + ' ' + esc(t.name) + '</td>' +
        '<td>' + esc(window.TRADE.labels[t.margin_type].label) + '</td><td class="' + t.side + '">' + (t.side === 'long' ? '買' : '売') + '</td>' +
        '<td class="num">' + yen(t.qty) + '</td><td class="num">' + t.open_price + ' → ' + t.close_price + '</td>' +
        '<td class="num ' + cls(t.net_pnl) + '">' + signed(t.net_pnl) + '</td><td class="num">' + yen(t.carry_cost) + '</td>' +
        '<td class="num">' + (t.r_multiple == null ? '-' : t.r_multiple.toFixed(2)) + '</td>' +
        '<td>' + esc((t.tags || []).join('・')) + (t.emotion ? ' / ' + esc(t.emotion) : '') +
        (t.exit_reason !== 'manual' ? ' <span class="badge late">強制返済</span>' : '') +
        (t.beyond_stop ? ' <span class="badge warn">損切り超え</span>' : '') +
        (t.add_type === 'nanpin' ? ' <span class="badge warn">ナンピン</span>' : t.add_type === 'pyramid' ? ' <span class="badge">増し玉</span>' : '') +
        TradeEdit.badge(t) + '</td>' +
        '<td class="wrap">' + esc(t.memo) + (t.exit_memo ? '<br><span class="muted">' + esc(t.exit_memo) + '</span>' : '') + '</td></tr>';
    }).join('') : '<tr><td colspan="12" class="muted">まだ返済した取引がありません</td></tr>';
  }).catch(function (e) { $('kpis').textContent = '読み込みに失敗しました: ' + e.message; });
  }

  load();
})();
