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
      '<th class="num">損益合計</th><th class="num">平均</th><th class="num">平均R</th></tr></thead><tbody>' +
      (rows.length ? rows.map(function (r) {
        return '<tr><td>' + esc(r.key) + '</td><td class="num">' + r.n + '</td><td class="num">' + pct(r.win_rate) + '</td>' +
          '<td class="num ' + cls(r.total) + '">' + signed(r.total) + '</td><td class="num ' + cls(r.avg) + '">' + signed(r.avg) + '</td>' +
          '<td class="num ' + cls(r.avg_r) + '">' + (r.avg_r == null ? '-' : r.avg_r.toFixed(2)) + '</td></tr>';
      }).join('') : '<tr><td colspan="6" class="muted">-</td></tr>') + '</tbody></table></div>';
  }

  var items = {};

  var last = null;          // 直近に読み込んだ成績（サマリーのコピー用）

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-edit]');
    if (b && items[b.dataset.edit]) TradeEdit.open('trade', items[b.dataset.edit], load);
    var c = e.target.closest('[data-copy]');
    if (c && items[c.dataset.copy]) TradeEdit.copy(TradeEdit.reviewText(items[c.dataset.copy]), c);
  });

  function hz() { var c = document.querySelector('[name=hz]:checked'); return c ? c.value : ''; }
  Array.prototype.forEach.call(document.querySelectorAll('[name=hz]'), function (r) {
    r.addEventListener('change', function () { try { localStorage.setItem('trade.hz', hz()); } catch (e) {} load(); });
  });
  try { var saved = localStorage.getItem('trade.hz'); if (saved) document.querySelector('[name=hz][value=' + saved + ']').checked = true; } catch (e) {}

  function range() {
    var q = [];
    if (hz()) q.push('horizon=' + hz());
    if ($('from').value) q.push('from=' + $('from').value);
    if ($('to').value) q.push('to=' + $('to').value);
    return q.length ? '?' + q.join('&') : '';
  }
  ['from', 'to'].forEach(function (id) { $(id).addEventListener('change', load); });
  $('csv').addEventListener('click', function () { location.href = '/api/trade/export.csv' + range(); });
  $('copysum').addEventListener('click', function () { if (last) TradeEdit.copy(summaryText(last), this); });

  // 週次レビューなどで別セッションに貼る成績サマリー
  function summaryText(j) {
    var s = j.stats;
    var rows = function (title, xs) {
      return title + '\n' + xs.map(function (x) {
        return '  ' + x.key + ': ' + x.n + '件 勝率' + pct(x.win_rate) + ' 損益' + signed(x.total) +
          ' 平均R ' + (x.avg_r == null ? '-' : x.avg_r.toFixed(2));
      }).join('\n');
    };
    return [
      '【成績サマリー】' + ({ '': 'デイトレ＋スイング', day: 'デイトレ', swing: 'スイング' })[hz()] + '　期間: ' + ($('from').value || '最初') + ' 〜 ' + ($('to').value || '最新') + '（口座 ' + j.account_id + '）',
      '取引数 ' + s.n + '（' + s.wins + '勝 ' + s.losses + '敗）／ 勝率 ' + pct(s.win_rate) + ' ／ 損益合計 ' + signed(s.total) + '円',
      '期待値(1取引) ' + signed(s.avg) + '円 ／ 平均R ' + (s.avg_r == null ? '-' : s.avg_r.toFixed(2)) +
        ' ／ PF ' + (s.profit_factor == null ? '-' : s.profit_factor.toFixed(2)),
      'ペイオフレシオ ' + (s.payoff_ratio == null ? '-' : s.payoff_ratio.toFixed(2)) + ' ／ 損益分岐勝率 ' + pct(s.breakeven_win_rate) +
        ' ／ 最大DD ' + yen(s.max_drawdown) + '円 ／ 最大連敗 ' + s.max_loss_streak,
      '損切り設定率 ' + pct(s.stop_set_rate) + ' ／ 損切りライン超え ' + s.beyond_stop + '件 ／ ナンピン ' + s.nanpin_count + '回 ／ 決済理由未分類 ' + s.unclassified_exits + '件',
      '',
      hz() === 'day' ? '' : '平均保有 ' + (s.avg_hold_bdays == null ? '-' : s.avg_hold_bdays.toFixed(1)) + '営業日 ／ 持ち越し費用 ' + yen(s.carry_total) +
        '円 ／ 平均MFE ' + (s.avg_mfe_r == null ? '-' : s.avg_mfe_r.toFixed(2)) + 'R ／ 平均MAE ' + (s.avg_mae_r == null ? '-' : s.avg_mae_r.toFixed(2)) +
        'R ／ 取り切り率 ' + pct(s.avg_capture) + ' ／ 窓で損切り ' + s.gap_stops + '件 ／ 保険の平均滑り ' +
        (s.avg_stop_slip_r == null ? '-' : s.avg_stop_slip_r.toFixed(2)) + 'R ／ 決算またぎ ' + s.earnings_crossed + '件',
      hz() ? '' : rows('■時間軸別', s.by_horizon),
      rows('■型別', s.by_setup), rows('■RR 基準を守ったか', s.by_rr_rule),
      hz() === 'day' ? '' : rows('■エントリー方法別', s.by_entry_method),
      rows('■決済理由別', s.by_exit_type), rows('■補足タグ別', s.by_tag), rows('■時間帯別', s.by_hour),
      rows('■感情別', s.by_emotion), rows('■売買別', s.by_side),
      '',
      '※ 約定ごとの詳細は CSV を添付します。来週の重点ルールを1つ提案してください。',
    ].join('\n');
  }

  function load() {
  fetch('/api/trade/trades' + range()).then(function (r) {
    return r.text().then(function (t) {
      var j; try { j = JSON.parse(t); } catch (e) { throw new Error(t || r.statusText); }
      if (!r.ok) throw new Error(j.detail || r.statusText);
      return j;
    });
  }).then(function (j) {
    last = j;
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
      ['ペイオフレシオ（平均利益÷平均損失）', s.payoff_ratio == null ? '-' : s.payoff_ratio.toFixed(2)],
      ['損益分岐勝率（これ以上勝てばプラス）', pct(s.breakeven_win_rate),
        s.breakeven_win_rate != null && s.win_rate != null ? (s.win_rate >= s.breakeven_win_rate ? 'pos' : 'neg') : ''],
      ['最大ドローダウン', yen(s.max_drawdown), s.max_drawdown ? 'neg' : ''],
      ['最大連敗', s.max_loss_streak],
      ['平均保有（勝 / 負）', hold(s.avg_hold_win) + ' / ' + hold(s.avg_hold_loss)],
      ['損切り設定率', pct(s.stop_set_rate)],
      ['損切りライン超えの決済', s.beyond_stop + '件', s.beyond_stop ? 'neg' : ''],
      ['ナンピン', s.nanpin_count + '回', s.nanpin_count ? 'neg' : ''],
      ['決済理由が未分類', s.unclassified_exits + '件', s.unclassified_exits ? 'neg' : ''],
      ['RR 基準未満で入った', s.below_rr_base + '件', s.below_rr_base ? 'neg' : ''],
    ];
    var r2 = function (v) { return v == null ? '-' : (v > 0 ? '+' : '') + v.toFixed(2) + 'R'; };
    if (hz() !== 'day') k = k.concat([
      ['平均保有（営業日）', s.avg_hold_bdays == null ? '-' : s.avg_hold_bdays.toFixed(1) + '日'],
      ['持ち越し費用の合計', yen(s.carry_total) + '円', s.carry_total ? 'neg' : ''],
      ['平均 MFE / MAE', r2(s.avg_mfe_r) + ' / ' + r2(s.avg_mae_r) + '（' + s.mfe_count + '件）'],
      ['利益の取り切り率（R ÷ MFE）', pct(s.avg_capture)],
      ['窓で損切り', s.gap_stops + '件', s.gap_stops ? 'neg' : ''],
      ['保険ストップの平均の滑り', r2(s.avg_stop_slip_r) + '（' + s.stop_slip_count + '件）', s.avg_stop_slip_r < 0 ? 'neg' : ''],
      ['決算をまたいだ', s.earnings_crossed + '件', s.earnings_crossed ? 'neg' : ''],
    ]);
    $('kpis').innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + x[0] + '</div><div class="v ' + (x[2] || '') + '">' + x[1] + '</div></div>';
    }).join('');
    $('curve').innerHTML = curve(s.curve);
    $('groups').innerHTML = [
      hz() ? '' : group('時間軸別', s.by_horizon),
      group('型別（3行メモ）', s.by_setup), group('RR 基準を守ったか', s.by_rr_rule),
      hz() === 'day' ? '' : group('エントリー方法別（スイング）', s.by_entry_method),
      hz() === 'day' ? '' : group('決算をまたいだか', s.by_earnings),
      group('決済理由別', s.by_exit_type), group('補足タグ別', s.by_tag), group('時間帯別（建てた時刻）', s.by_hour), group('曜日別', s.by_weekday),
      group('ナンピン・増し玉別（追加した建玉）', s.by_add_type), group('ナンピンした建玉群とそれ以外', s.by_nanpin_group),
      group('感情別', s.by_emotion), group('売買別', s.by_side), group('信用区分別', s.by_margin_type), group('銘柄別', s.by_symbol),
    ].join('');
    items = {};
    $('trades').innerHTML = j.trades.length ? j.trades.map(function (t) {
      items[t.id] = t;
      var sw = t.horizon === 'swing' ? ' <span class="badge swing">スイング ' + t.holding_bdays + '日</span>' : '';
      return '<tr><td>' + t.id + sw + '<br>' + TradeEdit.button(t.id) + '<br>' + TradeEdit.copyButton(t.id) + '</td><td>' + dt(t.opened_at) + ' → ' + dt(t.closed_at) + '</td><td>' + esc(t.symbol) + ' ' + esc(t.name) + '</td>' +
        '<td>' + esc(window.TRADE.labels[t.margin_type].label) + '</td><td class="' + t.side + '">' + (t.side === 'long' ? '買' : '売') + '</td>' +
        '<td class="num">' + yen(t.qty) + '</td><td class="num">' + t.open_price + ' → ' + t.close_price + '</td>' +
        '<td class="num ' + cls(t.net_pnl) + '">' + signed(t.net_pnl) + '</td><td class="num">' + yen(t.carry_cost) + '</td>' +
        '<td class="num">' + (t.r_multiple == null ? '-' : t.r_multiple.toFixed(2)) + '</td>' +
        '<td>' + esc(TradeEdit.setupName(t)) + ((t.tags || []).length ? ' / ' + esc(t.tags.join('・')) : '') + (t.emotion ? ' / ' + esc(t.emotion) : '') +
        (t.exit_reason !== 'manual' ? ' <span class="badge late">強制返済</span>'
          : t.exit_type ? ' <span class="badge">' + esc(window.TRADE.exit_types[t.exit_type]) + '</span>' : ' <span class="badge warn">決済理由未分類</span>') +
        (t.beyond_stop ? ' <span class="badge warn">損切り超え</span>' : '') +
        (t.add_type === 'nanpin' ? ' <span class="badge warn">ナンピン</span>' : t.add_type === 'pyramid' ? ' <span class="badge">増し玉</span>' : '') +
        TradeEdit.badge(t) + '</td>' +
        '<td class="wrap">' + (t.plan_basis ? '<b>' + esc(t.plan_basis) + '</b><br>' : '') + esc(t.memo) + (t.exit_memo ? '<br><span class="muted">' + esc(t.exit_memo) + '</span>' : '') + '</td></tr>';
    }).join('') : '<tr><td colspan="12" class="muted">まだ返済した取引がありません</td></tr>';
  }).catch(function (e) { $('kpis').textContent = '読み込みに失敗しました: ' + e.message; });
  }

  load();
})();
