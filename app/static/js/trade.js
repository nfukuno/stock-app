// トレード口座画面: 口座サマリー・新規注文・建玉の返済
(function () {
  var T = window.TRADE;
  var $ = function (id) { return document.getElementById(id); };
  var yen = function (v) { return v == null ? '-' : Math.round(v).toLocaleString('ja-JP'); };
  var signed = function (v) { return v == null ? '-' : (v > 0 ? '+' : '') + yen(v); };
  var cls = function (v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : ''; };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); };
  var hm = function (iso) { return iso ? iso.slice(5, 16).replace('T', ' ') : ''; };
  var holding = function (min) { return min < 60 ? min + '分' : min < 1440 ? (min / 60).toFixed(1) + '時間' : (min / 1440).toFixed(1) + '日'; };

  function api(method, url, body) {
    return fetch(url, { method: method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) {
            var d = j.detail;
            throw new Error(Array.isArray(d) ? d.map(function (x) { return x.msg.replace(/^Value error, /, ''); }).join(' / ') : (d || r.statusText));
          }
          return j;
        });
      });
  }

  function msg(el, text, ok) { el.innerHTML = text ? '<span class="' + (ok ? 'pos' : 'neg') + '">' + esc(text) + '</span>' : ''; }

  function render(a) {
    var mr = a.maintenance_rate;
    var k = [
      ['実質保証金', yen(a.effective_margin)],
      ['新規建余力', yen(a.buying_power)],
      ['維持率', mr == null ? '-' : (mr * 100).toFixed(1) + '%', mr != null && mr < 0.3 ? 'neg' : ''],
      ['評価損益', signed(a.unrealized), cls(a.unrealized)],
      ['本日の確定損益', signed(a.today_realized) + '（' + a.today_count + '件）', cls(a.today_realized)],
      ['累計確定損益', signed(a.realized_total), cls(a.realized_total)],
      ['純資産', yen(a.equity)],
      ['建玉代金', yen(a.position_amount)],
    ];
    $('kpis').innerHTML = k.map(function (x) {
      return '<div class="kpi"><div class="l">' + x[0] + '</div><div class="v ' + (x[2] || '') + '">' + x[1] + '</div></div>';
    }).join('');
    var al = [];
    if (a.margin_call) al.push('追証が発生しています（維持率 20% 未満）。建玉を返済して維持率を回復してください。');
    a.positions.forEach(function (p) { if (p.overdue) al.push(p.id + ' ' + p.symbol + ' は強制返済の対象です（終値の確定待ち）。'); });
    if (a.prices_stale) al.push('一部銘柄の現在値が取得できず、評価損益に含めていません。');
    $('alerts').innerHTML = al.map(function (t) { return '<div class="alert">' + esc(t) + '</div>'; }).join('');
    $('asof').textContent = '（' + hm(a.as_of) + ' 時点 / 口座 ' + a.account_id + '）';

    $('positions').innerHTML = a.positions.length ? a.positions.map(function (p) {
      return '<tr><td>' + p.id + '</td><td>' + esc(p.symbol) + ' ' + esc(p.name) + '</td><td>' + esc(p.label) + '</td>' +
        '<td class="' + p.side + '">' + (p.side === 'long' ? '買' : '売') + '</td><td class="num">' + yen(p.qty) + '</td>' +
        '<td class="num">' + p.open_price + '</td><td class="num">' + (p.last == null ? '-' : p.last) + '</td>' +
        '<td class="num ' + cls(p.unrealized) + '">' + signed(p.unrealized) + '</td><td class="num">' + yen(p.accrued_cost) + '</td>' +
        '<td>' + (p.stop || '-') + ' / ' + (p.target || '-') + '</td>' +
        '<td>' + hm(p.opened_at) + '<br><span class="muted">' + p.expiry_date + '</span></td>' +
        '<td><form class="closeform" data-id="' + p.id + '">' +
        '<input name="qty" type="number" min="' + T.lot + '" step="' + T.lot + '" max="' + p.qty + '" value="' + p.qty + '" title="株数">' +
        '<input name="price" type="number" step="0.1" min="0.1" placeholder="返済価格" value="' + (p.last || '') + '" required>' +
        '<input name="executed_at" type="datetime-local" step="1" title="空欄 = 今" style="width:180px">' +
        '<input name="memo" placeholder="決済理由" style="width:140px">' +
        '<button type="submit">返済</button></form></td></tr>';
    }).join('') : '<tr><td colspan="12" class="muted">建玉はありません</td></tr>';

    $('today').innerHTML = a.today_trades.length ? a.today_trades.map(function (t) {
      var reason = t.exit_reason === 'manual' ? esc(t.exit_memo) : '<span class="badge late">強制返済</span>';
      return '<tr><td>' + t.id + '</td><td>' + esc(t.symbol) + ' ' + esc(t.name) + '</td>' +
        '<td class="' + t.side + '">' + (t.side === 'long' ? '買' : '売') + '</td><td class="num">' + yen(t.qty) + '</td>' +
        '<td class="num">' + t.open_price + ' → ' + t.close_price + '</td><td>' + holding(t.holding_minutes) + '</td>' +
        '<td class="num ' + cls(t.net_pnl) + '">' + signed(t.net_pnl) + '</td>' +
        '<td class="num">' + (t.r_multiple == null ? '-' : t.r_multiple.toFixed(2)) + '</td><td>' + reason +
        (t.beyond_stop ? ' <span class="badge warn">損切りライン超え</span>' : '') + '</td></tr>';
    }).join('') : '<tr><td colspan="9" class="muted">本日の返済はまだありません</td></tr>';
  }

  function load() {
    return api('GET', '/api/trade/account').then(render).catch(function (e) { msg($('openmsg'), e.message); });
  }

  // ---- 新規注文
  var form = $('openform');
  function updatePreview() {
    var q = +form.qty.value, p = +form.price.value, s = +form.stop.value, t = +form.target.value;
    var long = form.side.value === 'long';
    if (!q || !p) { $('preview').textContent = ''; return; }
    var parts = ['約定代金 ' + yen(q * p) + ' 円', '必要保証金 ' + yen(q * p * 0.3) + ' 円'];
    if (s) parts.push('損切り時 ' + signed((s - p) * q * (long ? 1 : -1)) + ' 円');
    if (s && t) parts.push('RR ' + (Math.abs(t - p) / Math.abs(p - s)).toFixed(2));
    $('preview').textContent = parts.join(' / ');
  }
  form.addEventListener('input', updatePreview);

  $('symbol').addEventListener('change', function () {
    var v = this.value.trim();
    if (!v) return;
    api('GET', '/api/trade/quote/' + encodeURIComponent(v)).then(function (q) {
      if (!$('symname').value) $('symname').placeholder = q.name || '自動取得';
      if (!form.price.value && q.last) { form.price.value = q.last; updatePreview(); }
    }).catch(function () {});
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var b = {
      symbol: form.symbol.value, name: form.name.value, margin_type: form.margin_type.value, side: form.side.value,
      qty: +form.qty.value, price: +form.price.value, executed_at: form.executed_at.value || null,
      stop: form.stop.value ? +form.stop.value : null, target: form.target.value ? +form.target.value : null,
      emotion: form.emotion.value, memo: form.memo.value,
      tags: Array.prototype.filter.call(form.querySelectorAll('[name=tags]'), function (x) { return x.checked; }).map(function (x) { return x.value; }),
    };
    if (!b.stop && !confirm('損切りラインが未設定です（R倍数が計算できません）。このまま発注しますか？')) return;
    var btn = form.querySelector('button[type=submit]');
    btn.disabled = true;
    api('POST', '/api/trade/open', b).then(function (r) {
      var p = r.position;
      msg($('openmsg'), p.id + ' ' + p.symbol + ' ' + (p.side === 'long' ? '買' : '売') + ' ' + p.qty + '株 @' + p.open_price + ' を建てました', true);
      form.reset(); $('symname').placeholder = '自動取得'; updatePreview();
      render(r.account);
    }).catch(function (e) { msg($('openmsg'), e.message); }).finally(function () { btn.disabled = false; });
  });

  // ---- 返済（入力途中は自動更新で消さない）
  var editing = false;
  $('positions').addEventListener('input', function () { editing = true; });
  $('positions').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target;
    var b = { position_id: f.dataset.id, qty: +f.qty.value, price: +f.price.value, executed_at: f.executed_at.value || null, memo: f.memo.value };
    f.querySelector('button').disabled = true;
    api('POST', '/api/trade/close', b).then(function (r) {
      var t = r.trade;
      editing = false;
      msg($('closemsg'), t.id + ' ' + t.symbol + ' ' + t.qty + '株 @' + t.close_price + ' を返済しました（損益 ' + signed(t.net_pnl) + ' 円）', t.net_pnl >= 0);
      render(r.account);
    }).catch(function (e) { msg($('closemsg'), e.message); f.querySelector('button').disabled = false; });
  });

  // ---- リセット
  $('resetform').addEventListener('submit', function (e) {
    e.preventDefault();
    if (!confirm('新しい口座に切り替えます。現在の建玉は新口座に引き継がれません。よろしいですか？')) return;
    api('POST', '/api/trade/reset', { initial_cash: +this.initial_cash.value }).then(function (a) {
      render(a); msg($('openmsg'), '新しい口座 ' + a.account_id + ' を作成しました', true);
    }).catch(function (e) { msg($('openmsg'), e.message); });
  });

  load();
  setInterval(function () { if (!document.hidden && !editing) load(); }, 60000);
})();
