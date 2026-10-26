// 建玉・約定の修正 / 後からの追記ダイアログ（/trade と /trade/history で共用）
window.TradeEdit = (function () {
  var T = window.TRADE;
  var dlg, form, cur;
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); };

  function build() {
    dlg = document.createElement('dialog');
    dlg.className = 'editdlg';
    dlg.innerHTML =
      '<form method="dialog" id="editform">' +
      '<h2 id="edittitle"></h2>' +
      '<div class="egrid">' +
      '<label>建値<input name="open_price" type="number" step="0.1" min="0.1" required></label>' +
      '<label>建日時<input name="opened_at" type="datetime-local" step="1" required></label>' +
      '<label class="only-trade">返済日時<input name="closed_at" type="datetime-local" step="1"></label>' +
      '<label class="only-trade">返済価格<input name="close_price" type="number" step="0.1" min="0.1"></label>' +
      '<label>時間軸<select name="horizon">' + Object.keys(T.horizons).map(function (k) { return '<option value="' + k + '">' + esc(T.horizons[k]) + '</option>'; }).join('') + '</select></label>' +
      '<label>感情<select name="emotion"><option value="">-</option>' +
      T.emotions.map(function (e) { return '<option>' + esc(e) + '</option>'; }).join('') + '</select></label>' +
      '</div>' +
      '<fieldset class="eplan"><legend>3行メモ</legend>' +
      '<div class="egrid">' +
      '<label>① 型<select name="setup" required></select></label>' +
      '<label class="wide">根拠<input name="plan_basis" required maxlength="' + T.plan_max + '"></label>' +
      '<label>② 損切り価格<input name="stop" type="number" step="0.1" min="0.1" required></label>' +
      '<label class="wide">無効化の条件<input name="plan_exit_rule" maxlength="' + T.plan_max + '"></label>' +
      '<label>③ 目標価格<input name="target" type="number" step="0.1" min="0.1" required></label>' +
      '<label class="wide">目標の根拠<input name="plan_target_basis" maxlength="' + T.plan_max + '"></label>' +
      '</div></fieldset>' +
      '<fieldset class="eplan only-swing"><legend>スイングの計画</legend><div class="egrid">' +
      '<label>判断した足の日付<input name="decision_date" type="date"></label>' +
      '<label>エントリー方法<select name="entry_method"><option value="">未設定</option>' +
      Object.keys(T.entry_methods).map(function (k) { return '<option value="' + k + '">' + esc(T.entry_methods[k]) + '</option>'; }).join('') + '</select></label>' +
      '<label>判断ストップ（終値基準）<input name="judge_stop" type="number" step="0.1" min="0.1"></label>' +
      '<label>次の壁の価格<input name="next_wall_price" type="number" step="0.1" min="0.1"></label>' +
      '<label>次の壁の種類<select name="next_wall_kind"><option value="">-</option>' +
      T.wall_kinds.map(function (k) { return '<option>' + esc(k) + '</option>'; }).join('') + '</select></label>' +
      '<label>次回決算日<input name="earnings_date" type="date"></label>' +
      '</div></fieldset>' +
      '<fieldset class="eplan only-trade"><legend>保有中の値動き・費用</legend><div class="egrid">' +
      '<label>保有中の最高値<input name="hold_high" type="number" step="0.1" min="0.1"></label>' +
      '<label>保有中の最安値<input name="hold_low" type="number" step="0.1" min="0.1"></label>' +
      '<label>逆日歩（円）<input name="reverse_fee" type="number" step="1" min="0"></label>' +
      '</div><p class="muted" style="font-size:12px;margin:6px 0 0" id="holdnote">最高値・最安値から MFE / MAE（R）を計算します。スイングは返済時に日足から自動で入ります（建日・返済日の全値幅を含む概算）。</p></fieldset>' +
      '<div class="muted" style="font-size:12px;margin:8px 0 4px">補足タグ</div><div class="chips">' +
      T.tags.map(function (t) { return '<label><input type="checkbox" name="tags" value="' + esc(t) + '">' + esc(t) + '</label>'; }).join('') +
      '</div>' +
      '<label class="blk">メモ（シナリオ・振り返り）<textarea name="memo" rows="4" maxlength="' + T.memo_max + '"></textarea></label>' +
      '<label class="blk only-trade">決済理由<select name="exit_type"><option value="">未分類</option>' +
      Object.keys(T.exit_types).map(function (k) { return '<option value="' + k + '">' + esc(T.exit_types[k]) + '</option>'; }).join('') + '</select></label>' +
      '<label class="blk only-trade">決済メモ<textarea name="exit_memo" rows="2" maxlength="' + T.memo_max + '"></textarea></label>' +
      '<p class="muted" style="font-size:12px">価格・日時を直すと損益・R・金利・保有時間を再計算します。強制返済の返済日時を直すと「自分で返済」扱いになります。修正した内容は履歴として残ります。</p>' +
      '<div class="emsg neg"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end"><button type="button" class="cancel" style="background:#889">閉じる</button>' +
      '<button type="submit">保存</button></div></form>';
    document.body.appendChild(dlg);
    form = dlg.querySelector('form');
    dlg.querySelector('.cancel').addEventListener('click', function () { dlg.close(); });
    form.addEventListener('submit', save);
  }

  function num(v) { return v === '' ? null : +v; }
  // "2026-10-22T09:05:00+09:00" → datetime-local 用 "2026-10-22T09:05:00"（JST のまま）
  function local(iso) { return iso ? iso.slice(0, 19) : ''; }
  // ブラウザは秒が 0 のとき "HH:MM" に省略するので、秒を補って比べる
  function same(v, iso) { var full = function (x) { return x.length === 16 ? x + ':00' : x; }; return full(v) === local(iso); }

  function save(e) {
    e.preventDefault();
    var trade = cur.kind === 'trade';
    var b = {
      open_price: num(form.open_price.value), stop: num(form.stop.value), target: num(form.target.value),
      emotion: form.emotion.value, memo: form.memo.value,
      setup: form.setup.value || null, plan_basis: form.plan_basis.value, plan_exit_rule: form.plan_exit_rule.value,
      plan_target_basis: form.plan_target_basis.value, horizon: form.horizon.value,
      tags: Array.prototype.filter.call(form.querySelectorAll('[name=tags]'), function (x) { return x.checked; }).map(function (x) { return x.value; }),
    };
    if (trade) {
      b.close_price = num(form.close_price.value); b.exit_memo = form.exit_memo.value; b.exit_type = form.exit_type.value;
      b.hold_high = num(form.hold_high.value); b.hold_low = num(form.hold_low.value); b.reverse_fee = num(form.reverse_fee.value) || 0;
    }
    if (form.horizon.value === 'swing') {      // 空欄は「消す」（null を送る）
      b.decision_date = form.decision_date.value || null; b.entry_method = form.entry_method.value || null;
      b.judge_stop = num(form.judge_stop.value); b.next_wall_price = num(form.next_wall_price.value);
      b.next_wall_kind = form.next_wall_kind.value || null; b.earnings_date = form.earnings_date.value || null;
    }
    // 日時は変えたときだけ送る（秒まで比較）
    if (form.opened_at.value && !same(form.opened_at.value, cur.obj.opened_at)) b.opened_at = form.opened_at.value;
    if (trade && form.closed_at.value && !same(form.closed_at.value, cur.obj.closed_at)) b.closed_at = form.closed_at.value;
    var url = '/api/trade/' + (trade ? 'trades/' : 'positions/') + encodeURIComponent(cur.obj.id);
    var btn = form.querySelector('button[type=submit]');
    btn.disabled = true;
    fetch(url, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
      .then(function (r) {
        return r.text().then(function (t) {
          var j; try { j = JSON.parse(t); } catch (x) { j = { detail: t }; }
          if (!r.ok) {
            var d = j.detail;
            throw new Error(Array.isArray(d) ? d.map(function (x) { return x.msg.replace(/^Value error, /, ''); }).join(' / ') : (d || r.statusText));
          }
          return j;
        });
      })
      .then(function (j) { dlg.close(); if (cur.onSaved) cur.onSaved(j); })
      .catch(function (err) { dlg.querySelector('.emsg').textContent = err.message; })
      .finally(function () { btn.disabled = false; });
  }

  // kind: 'position' | 'trade'
  function open(kind, obj, onSaved) {
    if (!dlg) build();
    cur = { kind: kind, obj: obj, onSaved: onSaved };
    var trade = kind === 'trade';
    dlg.querySelector('#edittitle').textContent = (trade ? '約定の修正・追記 ' : '建玉の修正・追記 ') + obj.id + ' ' + obj.symbol + ' ' + (obj.name || '');
    Array.prototype.forEach.call(dlg.querySelectorAll('.only-trade'), function (el) { el.style.display = trade ? '' : 'none'; });
    form.open_price.value = obj.open_price;
    form.opened_at.value = local(obj.opened_at);
    form.closed_at.value = trade ? local(obj.closed_at) : '';
    form.close_price.value = trade ? obj.close_price : '';
    var si = obj.side === 'long' ? 0 : 1;
    form.horizon.value = obj.horizon || 'day';
    form.horizon.querySelector('[value=swing]').disabled = obj.margin_type === 'day';   // いちにち信用は持ち越せない
    var swingView = function () {
      Array.prototype.forEach.call(dlg.querySelectorAll('.only-swing'), function (el) { el.style.display = form.horizon.value === 'swing' ? '' : 'none'; });
    };
    form.horizon.onchange = swingView; swingView();
    ['decision_date', 'entry_method', 'judge_stop', 'next_wall_price', 'next_wall_kind', 'earnings_date'].forEach(function (k) {
      form[k].value = obj[k] == null ? '' : obj[k];
    });
    form.hold_high.value = trade && obj.hold_high != null ? obj.hold_high : '';
    form.hold_low.value = trade && obj.hold_low != null ? obj.hold_low : '';
    form.reverse_fee.value = trade && obj.reverse_fee ? obj.reverse_fee : '';
    form.setup.innerHTML = (obj.setup ? '' : '<option value="">未設定（選んでください）</option>') +
      Object.keys(T.setups).map(function (k) { return '<option value="' + k + '">' + esc(T.setups[k][si]) + '</option>'; }).join('');
    form.setup.value = obj.setup || '';
    form.plan_basis.value = obj.plan_basis || '';
    form.plan_exit_rule.value = obj.plan_exit_rule || '';
    form.plan_target_basis.value = obj.plan_target_basis || '';
    // 3行メモ導入前の記録は空でも保存できるように、元が空なら必須を外す
    form.setup.required = !!obj.setup; form.plan_basis.required = !!obj.plan_basis;
    form.stop.required = obj.stop != null; form.target.required = obj.target != null;
    form.plan_exit_rule.placeholder = obj.side === 'long' ? '例: 5分足が 3,815 を割って確定' : '例: 5分足が 2,520 を超えて確定';
    form.stop.value = obj.stop == null ? '' : obj.stop;
    form.target.value = obj.target == null ? '' : obj.target;
    form.emotion.value = obj.emotion || '';
    form.memo.value = obj.memo || '';
    form.exit_memo.value = trade ? (obj.exit_memo || '') : '';
    form.exit_type.value = trade ? (obj.exit_type || '') : '';
    Array.prototype.forEach.call(form.querySelectorAll('[name=tags]'), function (x) { x.checked = (obj.tags || []).indexOf(x.value) >= 0; });
    dlg.querySelector('.emsg').textContent = '';
    dlg.showModal();
  }

  // 修正履歴のバッジ（ホバーで内容を表示）
  function badge(obj) {
    if (!obj.edits || !obj.edits.length) return '';
    var lines = obj.edits.map(function (e) {
      return e.at.slice(5, 16).replace('T', ' ') + ' ' + Object.keys(e.changes).map(function (k) {
        var v = e.changes[k];
        return /memo/.test(k) ? k : k + ': ' + v[0] + '→' + v[1];
      }).join(', ');
    });
    return ' <span class="badge late" title="' + esc(lines.join('\n')) + '">修正あり</span>';
  }

  function button(id) { return '<button type="button" class="editbtn" data-edit="' + esc(id) + '">✎ 編集</button>'; }

  // ---- レビュー用テキスト（別セッションの Claude / ChatGPT に貼る）
  var RR = T.rr_base || 1.5;
  function n(v) { return v == null ? '-' : String(v); }
  function limit(t) {
    if (t.stop == null || t.target == null) return null;
    return Math.round((t.stop + (t.target - t.stop) / (1 + RR)) * 10) / 10;
  }
  function reviewText(t) {
    return t.horizon === 'swing' ? swingText(t) : dayText(t);
  }

  function signedR(v) { return v == null ? '-' : (v > 0 ? '+' : '') + v + 'R'; }

  // スイング版（判断した日足・エントリー方法・判断 / 保険ストップ・次の壁・決算・MFE / MAE・滑り・持ち越し費用）
  function swingText(t) {
    var long = t.side === 'long', lim = limit(t);
    var exitLabel = t.exit_reason !== 'manual' ? '強制返済' : (T.exit_types[t.exit_type] || '未分類');
    var flags = [];
    if (t.planned_rr != null && t.planned_rr < RR) flags.push('計画RRが基準 ' + RR + ' 未満');
    if (t.next_wall_price && t.target && (t.next_wall_price - t.open_price) * (long ? 1 : -1) > 0 && (t.target - t.next_wall_price) * (long ? 1 : -1) > 0)
      flags.push('目標の手前に次の壁（近すぎる壁）');
    if (t.earnings_crossed) flags.push('決算をまたいだ');
    if (!t.earnings_date) flags.push('決算日が未入力');
    if (t.stop_slip_r != null && t.stop_slip_r < 0) flags.push('保険ストップが滑った（' + t.stop_slip_r + 'R）');
    if (t.beyond_stop && t.stop_slip_r == null) flags.push('損切りラインを超えて決済');
    if (t.add_type === 'nanpin') flags.push('ナンピン');
    if (t.edits && t.edits.length) flags.push('記録を後から修正');
    return [
      '【スイング】' + (t.name || '') + '（' + t.symbol + '）' + (long ? '買い' : '売り') + ' ' + t.qty + '株 ' + T.labels[t.margin_type].label +
        '　区分: リプレイ / 本番（どちらか残す）',
      '判断した足: ' + (t.decision_date || t.open_date) + ' 日足確定 ／ エントリー方法: ' + (T.entry_methods[t.entry_method] || '未設定'),
      '型: ' + setupName(t) + (t.plan_basis ? '（' + t.plan_basis + '）' : ''),
      '判断ストップ: ' + (t.judge_stop ? '終値 ' + t.judge_stop + (long ? ' 割れ' : ' 超え') : '未設定') + ' ／ 保険: ' + n(t.stop) +
        ' ／ 目標: ' + n(t.target) + (t.plan_target_basis ? '（' + t.plan_target_basis + '）' : ''),
      '次の壁: ' + (t.next_wall_price ? t.next_wall_price + (t.next_wall_kind ? '（' + t.next_wall_kind + '）' : '') : '未設定'),
      '計画RR: ' + n(t.planned_rr) + ' ／ ' + (long ? '上限' : '下限') + '価格: ' + n(lim) + ' ／ 建値: ' + t.open_price,
      '次回決算: ' + (t.earnings_date || '未入力') + '（またぐ: ' + (t.earnings_crossed == null ? '-' : t.earnings_crossed ? 'はい' : 'いいえ') + '）',
      '返済: ' + t.close_date + ' ' + t.close_price + ' ／ 保有' + t.holding_bdays + '営業日 ／ 決済理由: ' + exitLabel,
      'MFE: ' + signedR(t.mfe_r) + ' ／ MAE: ' + signedR(t.mae_r) + ' ／ 保険の滑り: ' +
        (t.stop_slip_r == null ? 'なし' : t.stop_slip_yen + '円（' + t.stop_slip_r + 'R）') + ' ／ 持ち越し費用: ' + (t.carry_total != null ? t.carry_total : t.carry_cost) + '円',
      '損益: ' + (t.net_pnl > 0 ? '+' : '') + t.net_pnl + '円 ／ R: ' + n(t.r_multiple) + ' ／ 感情: ' + (t.emotion || '未記入'),
      '決済メモ: ' + (t.exit_memo || '未記入'),
      '自動チェック: ' + (flags.length ? flags.join(' / ') : 'なし'),
      '',
      '【環境】日経平均・先物の日足の向き: 　セクターの地合い: ',
      '【画像】①判断した日までの日足（その後が見えない状態） ②週足',
      '【自分で気になった点・質問】',
    ].join('\n');
  }

  function dayText(t) {
    var long = t.side === 'long';
    var lim = limit(t);
    var exitLabel = t.exit_reason !== 'manual' ? '強制返済' : (T.exit_types[t.exit_type] || '未分類');
    var flags = [];
    if (t.beyond_stop) flags.push('損切りラインを超えて決済');
    if (t.add_type === 'nanpin') flags.push('ナンピン');
    if (t.planned_rr != null && t.planned_rr < RR) flags.push('計画RRが基準 ' + RR + ' 未満（' + (long ? '上限' : '下限') + '価格 ' + lim + ' を超えて約定）');
    if (t.edits && t.edits.length) flags.push('記録を後から修正');
    return [
      '【区分】リプレイ / 本番（どちらか残す）　【日付】' + t.open_date + '　【銘柄】' + t.symbol + ' ' + (t.name || '') +
        '　【売買】' + (long ? '買い' : '売り') + ' ' + t.qty + '株（' + T.labels[t.margin_type].label + '）',
      '',
      '【計画（入る前）】',
      '① 型・根拠: ' + setupName(t) + (t.plan_basis ? '　' + t.plan_basis : '　（根拠未記入）'),
      '② 無効化: 損切り ' + n(t.stop) + (t.plan_exit_rule ? '　' + t.plan_exit_rule : ''),
      '③ 目標: ' + n(t.target) + (t.plan_target_basis ? '　' + t.plan_target_basis : ''),
      '計画RR: ' + n(t.planned_rr) + '　' + (long ? '上限' : '下限') + '価格(RR' + RR + '): ' + n(lim),
      '補足タグ: ' + ((t.tags || []).join('・') || 'なし') + '　メモ: ' + (t.memo || 'なし'),
      '',
      '【実際】',
      '建て: ' + t.open_price + '（' + t.opened_at.slice(11, 16) + '）　返済: ' + t.close_price + '（' + t.closed_at.slice(11, 16) + '）' +
        '　保有: ' + t.holding_minutes + '分',
      '損益: ' + (t.net_pnl > 0 ? '+' : '') + t.net_pnl + '円　R: ' + n(t.r_multiple) + '　決済理由: ' + exitLabel +
        '　感情: ' + (t.emotion || '未記入'),
      '決済メモ: ' + (t.exit_memo || '未記入'),
      '自動チェック: ' + (flags.length ? flags.join(' / ') : '特になし'),
      '',
      '【環境】日経先物の方向: 　寄りのギャップ: 　出来高: ',
      '【画像】①エントリー直前の5分足（未来が見えない状態） ②決済後の5分足（決済後30分まで） ③必要なら1分足',
      '【自分で気になった点・質問】',
    ].join('\n');
  }

  function copy(text, btn) {
    var done = function () { if (btn) { var o = btn.textContent; btn.textContent = '✓ コピーしました'; setTimeout(function () { btn.textContent = o; }, 1500); } };
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done);
    var ta = document.createElement('textarea');           // http://localhost 以外（LAN 越しなど）向けの予備
    ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); done();
  }

  function setupName(o) {
    var names = T.setups[o.setup];
    return names ? names[o.side === 'long' ? 0 : 1] : '型未設定';
  }
  // 建玉一覧に出す3行メモの要約
  function planLine(p) {
    if (!p.setup && !p.plan_basis) return p.memo ? '📝 ' + esc(p.memo) : '3行メモ未入力（✎ 編集から追記できます）';
    return '📝 ' + esc(setupName(p)) + (p.plan_basis ? '：' + esc(p.plan_basis) : '') +
      (p.plan_exit_rule ? '<br>✕ ' + esc(p.plan_exit_rule) : '') + (p.plan_target_basis ? '<br>◎ ' + esc(p.plan_target_basis) : '');
  }

  function copyButton(id) { return '<button type="button" class="editbtn" data-copy="' + esc(id) + '">📋 レビュー用にコピー</button>'; }

  return { open: open, badge: badge, button: button, reviewText: reviewText, copy: copy, copyButton: copyButton,
           setupName: setupName, planLine: planLine };
})();
