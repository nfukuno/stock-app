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
      '<label class="only-trade">返済価格<input name="close_price" type="number" step="0.1" min="0.1"></label>' +
      '<label>損切りライン<input name="stop" type="number" step="0.1" min="0.1"></label>' +
      '<label>利確目標<input name="target" type="number" step="0.1" min="0.1"></label>' +
      '<label>感情<select name="emotion"><option value="">-</option>' +
      T.emotions.map(function (e) { return '<option>' + esc(e) + '</option>'; }).join('') + '</select></label>' +
      '</div>' +
      '<div class="muted" style="font-size:12px;margin:8px 0 4px">エントリー理由</div><div class="chips">' +
      T.tags.map(function (t) { return '<label><input type="checkbox" name="tags" value="' + esc(t) + '">' + esc(t) + '</label>'; }).join('') +
      '</div>' +
      '<label class="blk">メモ（根拠・シナリオ・振り返り）<textarea name="memo" rows="4" maxlength="' + T.memo_max + '"></textarea></label>' +
      '<label class="blk only-trade">決済メモ<textarea name="exit_memo" rows="2" maxlength="' + T.memo_max + '"></textarea></label>' +
      '<p class="muted" style="font-size:12px">価格を直すと損益・R・金利を再計算します。修正した内容は履歴として残ります。</p>' +
      '<div class="emsg neg"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end"><button type="button" class="cancel" style="background:#889">閉じる</button>' +
      '<button type="submit">保存</button></div></form>';
    document.body.appendChild(dlg);
    form = dlg.querySelector('form');
    dlg.querySelector('.cancel').addEventListener('click', function () { dlg.close(); });
    form.addEventListener('submit', save);
  }

  function num(v) { return v === '' ? null : +v; }

  function save(e) {
    e.preventDefault();
    var trade = cur.kind === 'trade';
    var b = {
      open_price: num(form.open_price.value), stop: num(form.stop.value), target: num(form.target.value),
      emotion: form.emotion.value, memo: form.memo.value,
      tags: Array.prototype.filter.call(form.querySelectorAll('[name=tags]'), function (x) { return x.checked; }).map(function (x) { return x.value; }),
    };
    if (trade) { b.close_price = num(form.close_price.value); b.exit_memo = form.exit_memo.value; }
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
    form.close_price.value = trade ? obj.close_price : '';
    form.stop.value = obj.stop == null ? '' : obj.stop;
    form.target.value = obj.target == null ? '' : obj.target;
    form.emotion.value = obj.emotion || '';
    form.memo.value = obj.memo || '';
    form.exit_memo.value = trade ? (obj.exit_memo || '') : '';
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

  return { open: open, badge: badge, button: button };
})();
