/* 予想入力画面: Lightweight Charts v4.2 + 4つのドラッグハンドル(O/H/L/C) */
(function () {
  'use strict';
  var F = window.FORECAST;
  var KEYS = ['open', 'high', 'low', 'close'];
  var LABEL = { open: 'O', high: 'H', low: 'L', close: 'C' };
  var HANDLE_DX = { open: -34, close: 34, high: 0, low: 0 };   // 近接時に重ならないよう横/縦にずらす
  var HANDLE_DY = { open: 0, close: 0, high: -13, low: 13 };
  var SCN = {}; (F.scenarios || []).forEach(function (x) { SCN[x.key] = x.label; });
  var UP = '#d6403a', DOWN = '#1f7ae0';
  var $ = function (id) { return document.getElementById(id); };

  var data = null, chart, candle, predSeries;
  var pred = null, locked = false, dragging = null, handles = {}, lastPos = '';

  function toast(msg, isErr) {
    var t = $('toast');
    t.textContent = msg; t.className = isErr ? 'err' : ''; t.style.display = 'block';
    clearTimeout(toast._t); toast._t = setTimeout(function () { t.style.display = 'none'; }, 3500);
  }
  function r1(v) { return Math.round(v * 10) / 10; }
  function fmt(v) { return (Math.round(v * 10) / 10).toFixed(1); }

  // ---------- 制約付きの値更新 ----------
  function setPrice(key, price) {
    price = r1(price);
    if (!(price > 0) || !isFinite(price)) return;
    if (key === 'open' || key === 'close') {
      pred[key] = price;
      if (pred.high < price) pred.high = price;
      if (pred.low > price) pred.low = price;
    } else if (key === 'high') {
      pred.high = Math.max(price, pred.open, pred.close);
    } else {
      pred.low = Math.min(price, pred.open, pred.close);
    }
    render();
  }

  // ---------- 描画 ----------
  function render() {
    predSeries.setData([{ time: data.target_date, open: pred.open, high: pred.high, low: pred.low, close: pred.close }]);
    KEYS.forEach(function (k) {
      var el = $('in_' + k);
      if (document.activeElement !== el) el.value = fmt(pred[k]);
      var pc = data.prev_close, atr = data.atr14;
      var pct = (pred[k] - pc) / pc * 100;
      $('sub_' + k).textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' + (atr ? ' / ' + ((pred[k] - pc) / atr >= 0 ? '+' : '') + ((pred[k] - pc) / atr).toFixed(2) + 'ATR' : '');
    });
    var rng = pred.high - pred.low, body = Math.abs(pred.close - pred.open);
    $('rangeinfo').textContent = '値幅 ' + fmt(rng) + (data.atr14 ? '（' + (rng / data.atr14).toFixed(2) + 'ATR）' : '') +
      ' / 実体 ' + fmt(body) + ' / 前日終値 ' + fmt(data.prev_close) + ' / ATR14 ' + (data.atr14 ? fmt(data.atr14) : '-');
    place();
  }

  function place() {
    if (!pred) return;
    var x = chart.timeScale().timeToCoordinate(data.target_date);
    var parts = [x];
    KEYS.forEach(function (k) {
      var y = predSeries.priceToCoordinate(pred[k]);
      parts.push(y);
      var h = handles[k];
      if (x === null || y === null) { h.style.display = 'none'; return; }
      h.style.display = 'flex';
      h.style.left = (x + HANDLE_DX[k]) + 'px';
      h.style.top = (y + HANDLE_DY[k]) + 'px';
      h.textContent = LABEL[k] + ' ' + fmt(pred[k]);
    });
    lastPos = parts.join(',');
  }
  function loop() {                      // スクロール・ズーム・価格軸の変化後も位置を追従
    var x = chart.timeScale().timeToCoordinate(data.target_date);
    var key = [x].concat(KEYS.map(function (k) { return predSeries.priceToCoordinate(pred[k]); })).join(',');
    if (key !== lastPos) place();
    requestAnimationFrame(loop);
  }

  // ---------- ハンドル ----------
  function makeHandles() {
    KEYS.forEach(function (k) {
      var h = document.createElement('div');
      h.className = 'handle'; h.dataset.key = k; h.setAttribute('data-testid', 'handle-' + k);
      $('overlay').appendChild(h); handles[k] = h;
      h.addEventListener('pointerdown', function (e) {
        if (locked) return;
        e.preventDefault(); h.setPointerCapture(e.pointerId);
        var y = predSeries.priceToCoordinate(pred[k]);
        var top = $('overlay').getBoundingClientRect().top;
        dragging = { key: k, grab: (e.clientY - top) - (y + HANDLE_DY[k]) };
        h.classList.add('dragging');
      });
      h.addEventListener('pointermove', function (e) {
        if (!dragging || dragging.key !== k) return;
        var rect = $('overlay').getBoundingClientRect();
        var y = e.clientY - rect.top - dragging.grab - HANDLE_DY[k];
        y = Math.max(0, Math.min(rect.height, y));
        var price = predSeries.coordinateToPrice(y);
        if (price !== null) setPrice(k, price);
      });
      var end = function (e) { if (dragging && dragging.key === k) { dragging = null; h.classList.remove('dragging'); } };
      h.addEventListener('pointerup', end); h.addEventListener('pointercancel', end);
    });
  }

  // ---------- チャート ----------
  function sma(bars, n) {
    var out = [];
    for (var i = n - 1; i < bars.length; i++) {
      var s = 0; for (var j = i - n + 1; j <= i; j++) s += bars[j].close;
      out.push({ time: bars[i].time, value: s / n });
    }
    return out;
  }
  function buildChart() {
    chart = LightweightCharts.createChart($('chart'), {
      autoSize: true,
      layout: { background: { color: '#ffffff' }, textColor: '#333' },
      grid: { vertLines: { color: '#f0f1f4' }, horzLines: { color: '#f0f1f4' } },
      rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.2 } },
      timeScale: { rightOffset: 8, borderColor: '#e3e6ec', fixLeftEdge: false },
      crosshair: { mode: 0 }
    });
    candle = chart.addCandlestickSeries({ upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN });
    candle.setData(data.bars.map(function (b) { return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }; }));
    var vol = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    vol.setData(data.bars.map(function (b) { return { time: b.time, value: b.volume, color: b.close >= b.open ? 'rgba(214,64,58,.35)' : 'rgba(31,122,224,.35)' }; }));
    [[5, '#f59e0b'], [25, '#8b5cf6']].forEach(function (p) {
      var l = chart.addLineSeries({ color: p[1], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      l.setData(sma(data.bars, p[0]));
    });
    var pc = data.prev_close, a = data.atr14 || pc * 0.02;
    predSeries = chart.addCandlestickSeries({
      upColor: 'rgba(214,64,58,.45)', downColor: 'rgba(31,122,224,.45)',
      borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
      priceLineVisible: false, lastValueVisible: false,
      // ドラッグ中に価格軸が伸縮して手元がブレないよう、予想足の範囲は固定幅で扱う
      autoscaleInfoProvider: function () { return { priceRange: { minValue: pc - 2.5 * a, maxValue: pc + 2.5 * a } }; }
    });
    var n = data.bars.length, from = Math.max(0, n - 60);
    chart.timeScale().setVisibleLogicalRange({ from: from, to: n + 8 });
    chart.timeScale().subscribeVisibleLogicalRangeChange(place);
  }

  // ---------- フォーム ----------
  var SHAPES = {   // [O, H, L, C, 前日終値] を 0..1 で表した模式図
    round_trip: [.5, .95, .05, .52, .5], gap_up_trend: [.62, .95, .58, .9, .45], gap_up_fade: [.65, .72, .3, .35, .45],
    gap_down_rebound: [.35, .7, .05, .6, .55], gap_down_trend: [.35, .4, .05, .1, .55], range: [.48, .58, .4, .52, .5],
    up_trend: [.5, .85, .45, .8, .4], down_trend: [.5, .55, .15, .2, .6], other: [.45, .8, .2, .55, .5]
  };
  function icons() {
    document.querySelectorAll('.icon').forEach(function (el) {
      var s = SHAPES[el.dataset.key]; if (!s) return;
      var Y = function (v) { return (1 - v) * 24 + 2; };
      var up = s[3] >= s[0], col = up ? UP : DOWN;
      el.innerHTML = '<svg width="22" height="28" viewBox="0 0 22 28"><line x1="0" x2="22" y1="' + Y(s[4]) + '" y2="' + Y(s[4]) + '" stroke="#aaa" stroke-dasharray="2 2"/>' +
        '<line x1="11" x2="11" y1="' + Y(s[1]) + '" y2="' + Y(s[2]) + '" stroke="' + col + '"/>' +
        '<rect x="7" width="8" y="' + Math.min(Y(s[0]), Y(s[3])) + '" height="' + Math.max(2, Math.abs(Y(s[0]) - Y(s[3]))) + '" fill="' + col + '"/></svg>';
    });
  }
  function syncSelected() {
    document.querySelectorAll('#scn label, #conf label').forEach(function (l) { l.classList.toggle('sel', l.querySelector('input').checked); });
  }
  function setLocked(v, msg) {
    locked = v;
    $('chartwrap').classList.toggle('readonly', v);
    document.querySelectorAll('#panel input, #scn input, #conf input, #memo, #save, #name').forEach(function (e) { e.disabled = v; });
    var b = $('banner'); b.style.display = v ? 'block' : 'none'; if (v) b.textContent = msg;
  }
  function fillForm(p) {
    if (p.scenario) { var r = document.querySelector('input[name=scenario][value="' + p.scenario + '"]'); if (r) r.checked = true; }
    if (p.confidence) { var c = document.querySelector('input[name=confidence][value="' + p.confidence + '"]'); if (c) c.checked = true; }
    $('memo').value = p.memo || ''; $('memocount').textContent = $('memo').value.length + '/' + F.memoMax;
    syncSelected();
  }

  async function save() {
    var sc = document.querySelector('input[name=scenario]:checked');
    var cf = document.querySelector('input[name=confidence]:checked');
    if (!sc) return toast('シナリオを選んでください', true);
    if (!cf) return toast('自信度を選んでください', true);
    if (data.past_lock) {
      var ex = data.existing, warn;
      if (ex && !ex.late) warn = '対象日の 9:00 を過ぎています。この編集は「場中の修正」として保存され、採点には影響しません。\n採点には 9:00 前に保存した予想が使われます。';
      else warn = '対象日の 9:00 を過ぎています。この予想は「場中予想」として保存され、採点・LINE 通知・成績集計の対象外になります。';
      if (!confirm(warn + '\n保存しますか？')) return;
    }
    $('save').disabled = true;
    try {
      var res = await fetch('/api/forecast', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: data.symbol, target_date: data.target_date, pred: pred,
          scenario: sc.value, confidence: parseInt(cf.value, 10), memo: $('memo').value, name: $('name').value.trim() })
      });
      var body = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        var d = body.detail; if (Array.isArray(d)) d = d.map(function (x) { return x.msg; }).join(' / ');
        toast(d || ('保存に失敗しました (' + res.status + ')'), true);
        if (res.status === 409) setLocked(true, '採点済みのため編集できません');
        return;
      }
      data.existing = body; banner();
      $('savedinfo').textContent = '保存しました ' + body.updated_at.replace('T', ' ').slice(0, 16) + (body.late ? '（場中・採点なし）' : (body.frozen ? '（場中の修正・採点は9:00前の予想）' : ''));
      toast('保存しました');
    } catch (e) {
      toast('通信エラー: ' + e, true);
    } finally {
      if (!locked) $('save').disabled = false;
    }
  }

  function banner() {
    var b = $('banner'), ex = data.existing;
    if (!data.past_lock) { b.style.display = 'none'; return; }
    b.style.display = 'block';
    var fz = ex && ex.frozen;
    if (fz) {
      b.innerHTML = '9:00 を過ぎています。<b>採点に使われるのは 9:00 前に保存した予想</b>です（場中の編集は採点に影響しません）。<br>' +
        '採点用: O ' + fmt(fz.pred.open) + ' / H ' + fmt(fz.pred.high) + ' / L ' + fmt(fz.pred.low) + ' / C ' + fmt(fz.pred.close) +
        '（' + (SCN[fz.scenario] || fz.scenario) + '・自信' + fz.confidence + '） ' + String(fz.saved_at).replace('T', ' ').slice(0, 16) + ' 保存';
    } else if (ex && !ex.late) {
      b.textContent = '9:00 を過ぎています。保存済みの予想（9:00 前）が採点に使われます。ここで編集しても採点には影響せず、場中の修正として別に保存されます。';
    } else {
      b.textContent = '9:00 を過ぎています。保存は「場中予想」扱いで、採点・成績集計の対象外です（場中に日足を考えるための予想として使えます）。';
    }
  }

  async function init() {
    icons();
    var res = await fetch('/api/forecast/candles/' + encodeURIComponent(F.symbol) + '?days=120');
    if (!res.ok) {
      var err = await res.json().catch(function () { return {}; });
      $('chartwrap').innerHTML = '<p class="neg" style="padding:20px">' + (err.detail || ('読み込みに失敗しました (' + res.status + ')')) + '</p>';
      $('save').disabled = true; return;
    }
    data = await res.json();
    $('title').textContent = data.symbol + (data.name && data.name !== data.symbol ? ' ' + data.name : '');
    if (data.name && data.name !== data.symbol) $('name').value = data.name;
    $('target').textContent = '予想対象日: ' + data.target_date;
    var pc = data.prev_close, a = data.atr14 || pc * 0.01;
    var ex = data.existing;
    pred = ex ? { open: ex.pred.open, high: ex.pred.high, low: ex.pred.low, close: ex.pred.close }
              : { open: pc, close: pc, high: r1(pc + a / 2), low: r1(pc - a / 2) };   // 初期値 = flat ベースライン
    buildChart(); makeHandles();
    if (ex) { fillForm(ex); $('savedinfo').textContent = '保存済み ' + ex.updated_at.replace('T', ' ').slice(0, 16) + (ex.late ? '（場中・採点なし）' : (ex.frozen ? '（場中の修正・採点は9:00前の予想）' : '')); }
    KEYS.forEach(function (k) { $('in_' + k).addEventListener('change', function (e) { var v = parseFloat(e.target.value); if (isFinite(v)) setPrice(k, v); else render(); }); });
    $('memo').addEventListener('input', function () { $('memocount').textContent = $('memo').value.length + '/' + F.memoMax; });
    document.querySelectorAll('#scn input, #conf input').forEach(function (i) { i.addEventListener('change', syncSelected); });
    $('save').addEventListener('click', save);
    render();
    if (data.locked) setLocked(true, '採点済みのため編集できません');
    else banner();
    requestAnimationFrame(loop);
    window.__fc = { get pred() { return pred; }, get data() { return data; } };
  }
  init().catch(function (e) { toast('初期化に失敗: ' + e, true); console.error(e); });
})();
