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
        return r.text().then(function (t) {
          var j; try { j = JSON.parse(t); } catch (e) { j = { detail: t }; }
          if (!r.ok) {
            var d = j.detail;
            throw new Error(Array.isArray(d) ? d.map(function (x) { return x.msg.replace(/^Value error, /, ''); }).join(' / ') : (d || r.statusText));
          }
          return j;
        });
      });
  }

  function msg(el, text, ok) { el.innerHTML = text ? '<span class="' + (ok ? 'pos' : 'neg') + '">' + esc(text) + '</span>' : ''; }

  function closeForm(attr, qty, last, label) {
    return '<form class="closeform" ' + attr + '>' +
      '<input name="qty" type="number" min="' + T.lot + '" step="' + T.lot + '" max="' + qty + '" value="' + qty + '" title="株数">' +
      '<input name="price" type="number" step="0.1" min="0.1" placeholder="返済価格" value="' + (last || '') + '" required>' +
      '<input name="executed_at" type="datetime-local" step="1" title="空欄 = 今" style="width:180px">' +
      '<select name="exit_type" title="決済理由"><option value="">決済理由（未分類）</option>' +
      Object.keys(T.exit_types).map(function (k) { return '<option value="' + k + '">' + esc(T.exit_types[k]) + '</option>'; }).join('') + '</select>' +
      '<input name="memo" placeholder="決済メモ" style="width:140px">' +
      '<button type="submit">' + label + '</button></form>';
  }

  function posRow(p, single) {
    var add = p.add_type === 'nanpin' ? ' <span class="badge warn">ナンピン</span>' : p.add_type === 'pyramid' ? ' <span class="badge">増し玉</span>' : '';
    items[p.id] = { kind: 'position', obj: p };
    return '<tr' + (single ? '' : ' class="member"') + '><td>' + p.id + '<br>' + TradeEdit.button(p.id) + '</td><td>' + esc(p.symbol) + ' ' + esc(p.name) + add +
      TradeEdit.badge(p) + '<div class="memo-line">' + TradeEdit.planLine(p) + '</div></td><td>' + esc(p.label) + '</td>' +
      '<td class="' + p.side + '">' + (p.side === 'long' ? '買' : '売') + '</td><td class="num">' + yen(p.qty) + '</td>' +
      '<td class="num">' + p.open_price + '</td><td class="num">' + (p.last == null ? '-' : p.last) + '</td>' +
      '<td class="num ' + cls(p.unrealized) + '">' + signed(p.unrealized) + '</td><td class="num">' + yen(p.accrued_cost) + '</td>' +
      '<td>' + (p.stop || '-') + ' / ' + (p.target || '-') + '</td>' +
      '<td>' + hm(p.opened_at) + '<br><span class="muted">' + p.expiry_date + '</span></td>' +
      '<td>' + closeForm('data-id="' + p.id + '"', p.qty, p.last, '返済') + '</td></tr>';
  }

  var FMT = {
    int: function (v) { return v == null ? '-' : String(v); },
    pct: function (v) { return v == null ? '-' : (v * 100).toFixed(1) + '%'; },
    r: function (v) { return v == null ? '-' : v.toFixed(2) + 'R'; },
    ratio: function (v) { return v == null ? '-' : v.toFixed(2); },
  };

  function renderRoadmap(phases) {
    $('roadmap').innerHTML = phases.map(function (ph, i) {
      var next = phases[i + 1];
      var conds = ph.conditions.length ? '<div class="conds"><div class="muted">' + esc(ph.next_label) + '</div><ul>' +
        ph.conditions.map(function (c) {
          return '<li class="' + (c.ok ? 'pos' : '') + '">' + (c.ok ? '✅ ' : '⬜ ') + esc(c.label) +
            ' <span class="muted">（現在: ' + FMT[c.fmt](c.value) + '）</span></li>';
        }).join('') + '</ul>' +
        (ph.ready && next && !next.done ? '<div class="ready">' + (next.title.indexOf('本番') === 0
          ? '条件達成！ 最小単位での本番に進めます（Phase 4 の本番記録・比較機能も使いましょう）'
          : '条件達成！ Claude に「' + esc(next.title.split(':')[0]) + ' を作って」と依頼してください') + '</div>' : '') +
        '</div>' : '';
      return '<div class="phase' + (ph.done ? ' done' : '') + '"><h3>' + (ph.done ? '✔ ' : '') + esc(ph.title) +
        ' <span class="badge ' + (ph.done ? 'ok' : 'pending') + '">' + (ph.done ? '実装済み' : '未実装') + '</span></h3><ul>' +
        ph.items.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' + conds + '</div>';
    }).join('');
  }

  var items = {};          // 編集ボタン用: id → {kind, obj}

  function render(a) {
    items = {};
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
    a.positions.forEach(function (p) {
      if (p.backdated) al.push(p.id + ' ' + p.symbol + ' は過去日の建玉です。返済を入力してください（返済日時は ' + p.expiry_date + ' の大引けまで）。');
      else if (p.overdue) al.push(p.id + ' ' + p.symbol + ' は強制返済の対象です（終値の確定待ち）。');
    });
    if (a.prices_stale) al.push('一部銘柄の現在値が取得できず、評価損益に含めていません。');
    $('alerts').innerHTML = al.map(function (t) { return '<div class="alert">' + esc(t) + '</div>'; }).join('');
    $('asof').textContent = '（' + hm(a.as_of) + ' 時点 / 口座 ' + a.account_id + '）';

    $('positions').innerHTML = a.groups.length ? a.groups.map(function (g) {
      var single = g.members.length === 1;
      var rows = g.members.map(function (p) { return posRow(p, single); }).join('');
      if (single) return rows;
      // 2 本以上の建玉 → 合計行（平均建値・合計評価損益・まとめて返済）を先頭に
      return '<tr class="grouprow"><td>合計 ' + g.members.length + '本</td><td>' + esc(g.symbol) + ' ' + esc(g.name) +
        (g.nanpin ? ' <span class="badge warn">ナンピン</span>' : '') + '</td><td>' + esc(g.label) + '</td>' +
        '<td class="' + g.side + '">' + (g.side === 'long' ? '買' : '売') + '</td><td class="num">' + yen(g.qty) + '</td>' +
        '<td class="num" title="平均建値">' + g.avg_price + '<br><span class="muted">平均</span></td><td class="num">' + (g.last == null ? '-' : g.last) + '</td>' +
        '<td class="num ' + cls(g.unrealized) + '">' + signed(g.unrealized) + '</td><td class="num">' + yen(g.accrued_cost) + '</td>' +
        '<td></td><td class="muted">古い建玉から返済</td>' +
        '<td>' + closeForm('data-key="' + esc(g.key) + '"', g.qty, g.last, 'まとめて返済') + '</td></tr>' + rows;
    }).join('') : '<tr><td colspan="12" class="muted">建玉はありません</td></tr>';

    renderRoadmap(a.roadmap);

    $('today').innerHTML = a.today_trades.length ? a.today_trades.map(function (t) {
      var reason = t.exit_reason !== 'manual' ? '<span class="badge late">強制返済</span>'
        : (t.exit_type ? '<span class="badge">' + esc(T.exit_types[t.exit_type]) + '</span> ' : '<span class="badge warn">未分類</span> ') + esc(t.exit_memo);
      items[t.id] = { kind: 'trade', obj: t };
      return '<tr><td>' + t.id + '<br>' + TradeEdit.button(t.id) + '<br>' + TradeEdit.copyButton(t.id) + '</td><td>' + esc(t.symbol) + ' ' + esc(t.name) + TradeEdit.badge(t) + '</td>' +
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
  // 3行メモ: 買い・売りで表示名・ヒントを切り替え、RR と上限（下限）価格を計算する
  var RR = T.rr_base || 1.5;
  var HINT = {
    long: { hint: '買い: 損切りは建値より下、目標は上', basis: '例: 5分足が 5MA を上抜けて確定、上値 3,830 を突破',
            rule: '例: 5分足が 3,815 を割って確定したら撤退（任意）', tgt: '例: 本日高値 3,884（任意）', limit: '上限価格', cmp: '以下で買えば' },
    short: { hint: '売り: 損切りは建値より上、目標は下', basis: '例: 5分足が VWAP で跳ね返されて確定、戻り高値 2,520 の下',
             rule: '例: 5分足が 2,520 を超えて確定したら撤退（任意）', tgt: '例: 本日安値 2,440（任意）', limit: '下限価格', cmp: '以上で売れば' },
  };
  function planLabels() {
    var side = form.side.value, h = HINT[side];
    $('planhint').textContent = h.hint;
    $('plan_basis').placeholder = h.basis;
    $('plan_exit_rule').placeholder = h.rule;
    $('plan_target_basis').placeholder = h.tgt;
    $('stop').placeholder = '損切り価格（建値より' + (side === 'long' ? '下' : '上') + '）';
    $('target').placeholder = '目標価格（建値より' + (side === 'long' ? '上' : '下') + '）';
    Array.prototype.forEach.call($('setup').options, function (o) {
      if (o.value) o.textContent = T.setups[o.value][side === 'long' ? 0 : 1];
    });
  }

  // 計画の評価。null = まだ判定できない
  function planCheck() {
    var p = +form.price.value, sp = +form.stop.value, tp = +form.target.value, long = form.side.value === 'long';
    var h = HINT[form.side.value];
    if (!sp || !tp) return { text: '損切りと目標を入れると、RR と' + h.limit + 'を表示します。', cls: '' };
    if ((tp - sp) * (long ? 1 : -1) <= 0) return { text: (long ? '買いは目標を損切りより上に' : '売りは目標を損切りより下に') + '置いてください。', cls: 'ng', bad: true };
    var limit = Math.round((sp + (tp - sp) / (1 + RR)) * 10) / 10;
    var head = h.limit + ' ' + yen1(limit) + '（この価格' + h.cmp + ' RR ' + RR + ' 以上）';
    if (!p) return { text: head, cls: '' };
    var risk = (p - sp) * (long ? 1 : -1), reward = (tp - p) * (long ? 1 : -1);
    if (risk <= 0) return { text: '損切りは建値より' + (long ? '下' : '上') + 'に置いてください。', cls: 'ng', bad: true };
    if (reward <= 0) return { text: '目標は建値より' + (long ? '上' : '下') + 'に置いてください。', cls: 'ng', bad: true };
    var rr = reward / risk, q = +form.qty.value || 0;
    var tail = ' ／ 損切り時 ' + signed(-risk * q) + ' 円 ／ 約定代金 ' + yen(q * p) + ' 円（必要保証金 ' + yen(q * p * 0.3) + ' 円）';
    return { text: '計画RR ' + rr.toFixed(2) + (rr >= RR ? ' ✅ ' : ' ⚠ 基準 ' + RR + ' 未満 ') + '／ ' + head + tail, cls: rr >= RR ? 'ok' : 'ng', rr: rr };
  }
  function yen1(v) { return v.toLocaleString('ja-JP', { maximumFractionDigits: 1 }); }
  function updatePreview() {
    var c = planCheck();
    $('planout').textContent = c.text;
    $('planout').className = 'planout ' + c.cls;
  }
  Array.prototype.forEach.call(form.querySelectorAll('[name=side]'), function (r) { r.addEventListener('change', function () { planLabels(); updatePreview(); }); });
  planLabels();
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
      stop: +form.stop.value, target: +form.target.value,
      setup: form.setup.value, plan_basis: form.plan_basis.value, plan_exit_rule: form.plan_exit_rule.value,
      plan_target_basis: form.plan_target_basis.value,
      emotion: form.emotion.value, memo: form.memo.value,
      tags: Array.prototype.filter.call(form.querySelectorAll('[name=tags]'), function (x) { return x.checked; }).map(function (x) { return x.value; }),
    };
    var c = planCheck();
    if (c.bad) { msg($('openmsg'), c.text); return; }
    if (c.rr != null && c.rr < RR && !confirm('計画RR ' + c.rr.toFixed(2) + ' は基準 ' + RR + ' 未満です。\n原則は「見送る」か「' + HINT[form.side.value].limit + 'まで待つ」です。\nそれでも記録しますか？（分析で「基準違反」として集計されます）')) return;
    var btn = form.querySelector('button[type=submit]');
    btn.disabled = true;
    api('POST', '/api/trade/open', b).then(function (r) {
      var p = r.position;
      msg($('openmsg'), p.id + ' ' + p.symbol + ' ' + (p.side === 'long' ? '買' : '売') + ' ' + p.qty + '株 @' + p.open_price + ' を建てました', true);
      form.reset(); $('symname').placeholder = '自動取得'; planLabels(); updatePreview();
      render(r.account);
    }).catch(function (e) { msg($('openmsg'), e.message); }).finally(function () { btn.disabled = false; });
  });

  // ---- 返済（入力途中は自動更新で消さない）
  var editing = false;
  $('positions').addEventListener('input', function () { editing = true; });
  $('positions').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target;
    var b = { qty: +f.qty.value, price: +f.price.value, executed_at: f.executed_at.value || null, memo: f.memo.value, exit_type: f.exit_type.value };
    var group = !!f.dataset.key;
    if (group) b.key = f.dataset.key; else b.position_id = f.dataset.id;
    f.querySelector('button').disabled = true;
    api('POST', group ? '/api/trade/close_group' : '/api/trade/close', b).then(function (r) {
      var ts = group ? r.trades : [r.trade];
      var net = ts.reduce(function (s, t) { return s + t.net_pnl; }, 0);
      editing = false;
      msg($('closemsg'), ts.map(function (t) { return t.id; }).join(', ') + ' ' + ts[0].symbol + ' ' + b.qty + '株 @' + b.price +
        ' を返済しました（損益 ' + signed(net) + ' 円）', net >= 0);
      render(r.account);
    }).catch(function (e) { msg($('closemsg'), e.message); f.querySelector('button').disabled = false; });
  });

  // ---- 修正・追記
  document.addEventListener('click', function (e) {
    var cp = e.target.closest('[data-copy]');
    if (cp && items[cp.dataset.copy]) { TradeEdit.copy(TradeEdit.reviewText(items[cp.dataset.copy].obj), cp); return; }
    var b = e.target.closest('[data-edit]');
    if (!b || !items[b.dataset.edit]) return;
    var it = items[b.dataset.edit];
    TradeEdit.open(it.kind, it.obj, function (r) {
      msg($('closemsg'), it.obj.id + ' を更新しました', true);
      render(r.account);
    });
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
