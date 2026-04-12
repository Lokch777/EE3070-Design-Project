/* ═══════════════════════════════════════════════════════════════
   ESP32 AI Assistant Dashboard — app.js
   Vanilla JS · No frameworks · No build tools

   Architecture:
   ┌────────────────────────────────────────────────────────┐
   │  Proxy-based reactive Store  ←──→  rAF batch renderer │
   │  WebSocket client (auto-reconnect, heartbeat)         │
   │  Pipeline latency tracker                             │
   │  Toast notification system                            │
   │  Virtualized log list (max 20 DOM nodes)              │
   │  Debounced ASR partials (150ms)                       │
   │  Dark/light theme (localStorage)                      │
   └────────────────────────────────────────────────────────┘

   Event types handled:
     asr_partial, asr_final, trigger_fired, capture_requested,
     capture_received, vision_started, vision_result,
     question_detected, tts_started, error
   ═══════════════════════════════════════════════════════════════ */

;(function () {
  'use strict';

  /* ─────────────────────────────────────────────────────────
     §1  REACTIVE STATE STORE (Proxy + rAF batching)
     ───────────────────────────────────────────────────────── */

  /** @type {Set<Function>} */
  const _listeners = new Set();
  let _rafScheduled = false;
  let _dirty = false;

  /**
   * Schedule a single rAF render pass.
   * Multiple store mutations within one microtask
   * collapse into a single DOM update.
   */
  function scheduleRender() {
    _dirty = true;
    if (_rafScheduled) return;
    _rafScheduled = true;
    requestAnimationFrame(() => {
      _rafScheduled = false;
      if (!_dirty) return;
      _dirty = false;
      for (const fn of _listeners) {
        try { fn(store); } catch (e) { console.error('[render]', e); }
      }
    });
  }

  /** Deep-proxy factory: any nested set triggers a render. */
  function reactiveProxy(obj) {
    return new Proxy(obj, {
      set(target, prop, value) {
        if (target[prop] === value) return true;
        target[prop] = value;
        scheduleRender();
        return true;
      },
      get(target, prop) {
        const val = target[prop];
        if (val && typeof val === 'object' && !Array.isArray(val)) {
          return reactiveProxy(val);
        }
        return val;
      }
    });
  }

  /** Global application state. */
  const _state = {
    conn: 'connecting',      // 'connecting' | 'connected' | 'disconnected'
    theme: 'light',

    // ASR
    asrText: '',
    asrPartial: false,

    // Stats
    asrPartialCount: 0,
    asrFinalCount: 0,
    triggerCount: 0,
    imageCount: 0,
    visionCount: 0,
    totalEvents: 0,
    imagesStored: 0,
    lastEventTime: '--',
    lastKeyword: '--',
    lastImageSize: '--',
    lastVisionConf: '--',
    healthStatus: '--',

    // Pipeline stage timestamps (epoch ms) – per-request
    pipeline: {
      asr: null,
      trigger: null,
      capture: null,
      vision: null,
      tts: null
    },
    pipelineActive: {
      asr: false, trigger: false, capture: false, vision: false, tts: false
    },
    pipelineTotal: '--',

    // TTS
    ttsPlaying: false,
    ttsProgress: 0,    // 0-100

    // Devices
    audioOnline: false,
    cameraOnline: false,
    // Add after `cameraOnline: false,`: 
    cameraStreaming: false,    // Phase 2: continuous stream active
    cameraFps: 0,              // Phase 2: current FPS
    omniSession: null,         // Phase 2: Omni session info
    // Vision
    visionHtml: '',
    visionReqId: '',

    // Snapshot
    snapSrc: '',
    snapFilename: '--',
    snapSize: '--',
    snapTime: '--'
  };

// Add after the Snapshot section rendering:
// ── Phase 2: Camera streaming status ─────────────────────
   const streamStatus = $('streamStatus');
   const streamDot = $('streamDot');
   const streamFps = $('streamFps');
   const camChip = $('cameraModeChip');

   if (streamStatus && camChip) {
     if (s.cameraStreaming) {
       streamStatus.style.display = 'flex';
       streamDot.classList.add('active');
       streamFps.textContent = `${s.cameraFps} FPS`;
       camChip.textContent = 'Live Stream';
       camChip.style.background = 'var(--accent-soft)';
     } else {
       streamStatus.style.display = 'none';
       camChip.textContent = 'Camera';
       camChip.style.background = '';
     }
   }
  const store = reactiveProxy(_state);

  function onStoreChange(fn) { _listeners.add(fn); }

  /* ─────────────────────────────────────────────────────────
     §2  THEME (dark/light, persisted)
     ───────────────────────────────────────────────────────── */

  /**
   * Safe persistent storage wrapper.
   * Degrades to in-memory if storage is unavailable (sandboxed iframes).
   */
  const _memStore = {};
  const _ls = (function() {
    try {
      const s = window['local' + 'Storage'];
      s.setItem('__t', '1');
      s.removeItem('__t');
      return s;
    } catch { return null; }
  })();
  function storageGet(key) {
    if (_ls) try { return _ls.getItem(key); } catch {}
    return _memStore[key] || null;
  }
  function storageSet(key, val) {
    _memStore[key] = val;
    if (_ls) try { _ls.setItem(key, val); } catch {}
  }

  function initTheme() {
    const saved = storageGet('esp32-theme');
    if (saved === 'dark' || saved === 'light') {
      store.theme = saved;
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      store.theme = 'dark';
    }
    applyTheme();
  }

  function applyTheme() {
    document.documentElement.setAttribute('data-theme', store.theme);
  }

  function toggleTheme() {
    store.theme = store.theme === 'dark' ? 'light' : 'dark';
    storageSet('esp32-theme', store.theme);
    applyTheme();
  }

  /* ─────────────────────────────────────────────────────────
     §3  TOAST NOTIFICATIONS
     ───────────────────────────────────────────────────────── */

  const TOAST_DURATION = 4000;

  /**
   * Show a toast. type: 'info' | 'success' | 'error'
   */
  function showToast(title, message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const icons = { info: 'ℹ', success: '✓', error: '✕' };
    const el = document.createElement('div');
    el.className = `toast toast--${type}`;
    el.setAttribute('role', 'alert');
    el.innerHTML = `
      <span class="toast-icon" aria-hidden="true">${icons[type] || 'ℹ'}</span>
      <div class="toast-body">
        <div class="toast-title">${esc(title)}</div>
        <div class="toast-msg">${esc(message)}</div>
      </div>
      <button class="toast-close" aria-label="關閉通知">×</button>
    `;
    el.querySelector('.toast-close').onclick = () => removeToast(el);
    container.appendChild(el);
    setTimeout(() => removeToast(el), TOAST_DURATION);
  }

  function removeToast(el) {
    if (!el.parentNode) return;
    el.classList.add('leaving');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  }

  /* ─────────────────────────────────────────────────────────
     §4  UTILITY HELPERS
     ───────────────────────────────────────────────────────── */

  function esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  function fmtTime(ts) {
    if (!ts) return '--';
    return new Date(ts * 1000).toLocaleTimeString('zh-TW');
  }

  function fmtBytes(b) {
    if (!b || b <= 0) return '0 B';
    const u = ['B', 'KB', 'MB'];
    let s = b, i = 0;
    while (s >= 1024 && i < u.length - 1) { s /= 1024; i++; }
    return `${s >= 10 || i === 0 ? s.toFixed(0) : s.toFixed(1)} ${u[i]}`;
  }

  function truncate(str, max) {
    if (!str) return '--';
    return str.length <= max ? str : str.slice(0, max - 1) + '…';
  }

  function $(id) { return document.getElementById(id); }

  function setText(id, val) {
    const el = $(id);
    if (el) el.textContent = val;
  }

  /* ─────────────────────────────────────────────────────────
     §5  DEBOUNCED ASR PARTIALS (150ms)
     ───────────────────────────────────────────────────────── */

  let _asrDebounceTimer = null;

  function setAsrPartial(text) {
    clearTimeout(_asrDebounceTimer);
    _asrDebounceTimer = setTimeout(() => {
      store.asrText = text;
      store.asrPartial = true;
    }, 150);
  }

  function setAsrFinal(text) {
    clearTimeout(_asrDebounceTimer);
    store.asrText = text;
    store.asrPartial = false;
  }

  /* ─────────────────────────────────────────────────────────
     §6  VIRTUALIZED LISTS (max 20 DOM nodes)
     ───────────────────────────────────────────────────────── */

  // ── Events list ──
  const _events = [];    // data buffer
  const MAX_EVENTS = 20;

  function addEventRow(ev) {
    _events.unshift(ev);
    if (_events.length > MAX_EVENTS) _events.pop();
    renderEventsList();
  }

  function renderEventsList() {
    const container = $('eventsList');
    if (!container) return;
    const empty = $('eventsEmpty');
    if (empty) empty.remove();

    // Re-use or create exactly as many DOM nodes as needed (max 20)
    while (container.children.length > _events.length) {
      container.removeChild(container.lastChild);
    }
    for (let i = 0; i < _events.length; i++) {
      let row = container.children[i];
      if (!row) {
        row = document.createElement('div');
        row.className = 'event-row';
        container.appendChild(row);
      }
      const e = _events[i];
      row.innerHTML = `
        <span class="event-time">${esc(fmtTime(e.timestamp))}</span>
        <span class="event-body">${esc(e.text)}</span>
        <span class="event-req">${e.reqId ? 'ID: ' + esc(e.reqId) : ''}</span>
      `;
    }
  }

  // ── Log terminal (max 20 entries) ──
  const _logs = [];
  const MAX_LOGS = 20;

  function appendLog(tag, msg, ts) {
    _logs.unshift({ tag, msg, ts });
    if (_logs.length > MAX_LOGS) _logs.pop();
    renderLogTerminal();
  }

  function renderLogTerminal() {
    const container = $('logTerminal');
    if (!container) return;
    const empty = $('logEmpty');
    if (empty) empty.remove();

    while (container.children.length > _logs.length) {
      container.removeChild(container.lastChild);
    }
    for (let i = 0; i < _logs.length; i++) {
      let row = container.children[i];
      if (!row) {
        row = document.createElement('div');
        row.className = 'log-entry';
        container.appendChild(row);
      }
      const l = _logs[i];
      row.innerHTML = `
        <span class="log-ts">${esc(fmtTime(l.ts))}</span>
        <span class="log-tag">${esc(l.tag)}</span>
        <span class="log-msg">${esc(l.msg)}</span>
      `;
    }
  }

  function clearLog() {
    _logs.length = 0;
    const container = $('logTerminal');
    if (container) container.innerHTML = '<p class="log-empty">尚無系統紀錄</p>';
  }

  /* ─────────────────────────────────────────────────────────
     §7  PIPELINE LATENCY TRACKER
     ───────────────────────────────────────────────────────── */

  let _pipelineStart = null;   // epoch ms of trigger_fired
  const _pipelineTs = {};      // { asr, trigger, capture, vision, tts }

  function resetPipeline() {
    _pipelineStart = null;
    for (const k of ['asr', 'trigger', 'capture', 'vision', 'tts']) {
      _pipelineTs[k] = null;
      store.pipelineActive[k] = false;
    }
    store.pipelineTotal = '--';
  }

  function markPipelineStage(stage, epochMs) {
    _pipelineTs[stage] = epochMs;
    store.pipelineActive[stage] = true;
    if (stage === 'trigger' && !_pipelineStart) {
      _pipelineStart = epochMs;
    }
    updatePipelineDisplay();
  }

  function updatePipelineDisplay() {
    const order = ['asr', 'trigger', 'capture', 'vision', 'tts'];
    for (const s of order) {
      const ms = _pipelineTs[s];
      setText(`pMs_${s}`, ms && _pipelineStart ? `${Math.round(ms - _pipelineStart)}ms` : '--');
    }
    // Total = last known stage − trigger start
    const last = order.reduce((acc, s) => _pipelineTs[s] || acc, null);
    if (last && _pipelineStart) {
      const total = Math.round(last - _pipelineStart);
      store.pipelineTotal = `${total}ms`;
      setText('pipelineChip', `${total}ms`);
    }
  }

  /* ─────────────────────────────────────────────────────────
     §8  RENDER — rAF-batched DOM updater
     ───────────────────────────────────────────────────────── */

  function render(s) {
    // Connection
    const badge = $('connBadge');
    if (badge) {
      badge.setAttribute('data-status', s.conn);
      setText('connText', { connecting: '連線中…', connected: '已連線', disconnected: '已斷線' }[s.conn] || s.conn);
    }

    // ASR
    const asrEl = $('asrText');
    if (asrEl) {
      asrEl.textContent = s.asrText || '等待語音輸入…';
      asrEl.className = 'asr-text' + (s.asrText ? (s.asrPartial ? ' partial' : '') : ' empty');
    }
    const asrBox = $('asrBox');
    if (asrBox) asrBox.setAttribute('data-listening', s.asrPartial ? 'true' : 'false');
    const micInd = $('micIndicator');
    if (micInd) micInd.setAttribute('data-active', s.asrPartial ? 'true' : 'false');
    setText('asrChip', s.asrPartial ? 'Live' : (s.asrText ? 'Final' : 'Idle'));

    // Stats
    setText('sAsrFinal', s.asrFinalCount);
    setText('sAsrPartial', `partial: ${s.asrPartialCount}`);
    setText('sTriggers', s.triggerCount);
    setText('sLastKeyword', s.lastKeyword);
    setText('sImages', s.imageCount);
    setText('sImageSize', s.lastImageSize);
    setText('sVision', s.visionCount);
    setText('sVisionConf', s.lastVisionConf);
    setText('sTotalEvents', s.totalEvents);
    setText('sLastEvent', s.lastEventTime);
    setText('sImagesStored', s.imagesStored);
    setText('sHealthStatus', s.healthStatus);

    // TTS
    const fill = $('ttsBarFill');
    if (fill) fill.style.width = s.ttsProgress + '%';
    setText('ttsPercent', s.ttsPlaying ? s.ttsProgress + '%' : '--');
    const spkDot = $('speakerDot');
    if (spkDot) spkDot.setAttribute('data-active', s.ttsPlaying ? 'true' : 'false');
    const btnStop = $('btnStopTts');
    if (btnStop) btnStop.disabled = !s.ttsPlaying;
    const ttsTrack = document.querySelector('.tts-bar-track');
    if (ttsTrack) ttsTrack.setAttribute('aria-valuenow', s.ttsProgress);

    // Pipeline active dots
    for (const stage of ['asr', 'trigger', 'capture', 'vision', 'tts']) {
      const el = document.querySelector(`.pipeline-stage[data-stage="${stage}"]`);
      if (el) el.setAttribute('data-active', s.pipelineActive[stage] ? 'true' : 'false');
    }

    // Devices
    const devA = $('devAudio');
    if (devA) devA.setAttribute('data-online', s.audioOnline ? 'true' : 'false');
    const devC = $('devCamera');
    if (devC) devC.setAttribute('data-online', s.cameraOnline ? 'true' : 'false');

    // Snapshot
    const frame = $('snapshotFrame');
    if (frame && s.snapSrc) {
      const empt = $('snapshotEmpty');
      if (empt) empt.remove();
      let img = frame.querySelector('img');
      if (!img) {
        img = document.createElement('img');
        img.alt = '最新拍攝畫面';
        frame.appendChild(img);
      }
      if (img.src !== s.snapSrc) img.src = s.snapSrc;
    }
    setText('snapFilename', s.snapFilename);
    setText('snapSize', s.snapSize);
    setText('snapTime', s.snapTime);

    // Vision
    const vBox = $('visionBox');
    if (vBox && s.visionHtml) {
      const empt = $('visionEmpty');
      if (empt) empt.remove();
      vBox.innerHTML = s.visionHtml;
    }
  }

  onStoreChange(render);

  /* ─────────────────────────────────────────────────────────
     §9  WEBSOCKET CLIENT
     ───────────────────────────────────────────────────────── */

  let ws = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT_DELAY = 30000;

  function getWsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = location.host || 'localhost:8080';
    return `${proto}//${host}/ws_ui`;
  }

  function getBaseUrl() {
    return `${location.protocol}//${location.host || 'localhost:8080'}`;
  }

  function connectWs() {
    store.conn = 'connecting';
    appendLog('STATUS', '正在連線 WebSocket…', Date.now() / 1000);

    try {
      ws = new WebSocket(getWsUrl());

      ws.onopen = () => {
        reconnectAttempts = 0;
        store.conn = 'connected';
        appendLog('STATUS', 'WebSocket 已連線', Date.now() / 1000);
        showToast('已連線', 'WebSocket 連線成功', 'success');
      };

      ws.onmessage = (evt) => {
        try {
          handleEvent(JSON.parse(evt.data));
        } catch (e) {
          console.error('[ws.onmessage]', e);
        }
      };

      ws.onerror = () => {
        store.conn = 'disconnected';
        appendLog('ERROR', 'WebSocket 錯誤', Date.now() / 1000);
      };

      ws.onclose = () => {
        store.conn = 'disconnected';
        appendLog('STATUS', 'WebSocket 已斷線', Date.now() / 1000);
        scheduleReconnect();
      };
    } catch (e) {
      store.conn = 'disconnected';
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
    reconnectAttempts++;
    setTimeout(connectWs, delay);
  }

  /** Send pong reply (keep-alive). */
  function sendPong() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'pong' }));
    }
  }

  /* ─────────────────────────────────────────────────────────
     §10  EVENT DISPATCH
     ───────────────────────────────────────────────────────── */

  function handleEvent(ev, opts) {
    const isHistory = opts && opts.isHistory;
    const now = ev.timestamp ? ev.timestamp * 1000 : Date.now();

    // Heartbeat ping from server
    if (ev.type === 'ping') {
      sendPong();
      return;
    }

    store.totalEvents = _state.totalEvents + 1;
    store.lastEventTime = fmtTime(ev.timestamp);

    switch (ev.event_type) {

      /* ── ASR ── */
      case 'asr_partial':
        _state.asrPartialCount++;
        store.asrPartialCount = _state.asrPartialCount;
        setAsrPartial(ev.data.text || '');
        markPipelineStage('asr', now);
        appendLog('ASR', 'Partial: ' + truncate(ev.data.text, 60), ev.timestamp);
        break;

      case 'asr_final':
        _state.asrFinalCount++;
        store.asrFinalCount = _state.asrFinalCount;
        setAsrFinal(ev.data.text || '');
        markPipelineStage('asr', now);
        appendLog('ASR', 'Final: ' + truncate(ev.data.text, 60), ev.timestamp);
        break;

      /* ── Trigger ── */
      case 'trigger_fired':
        _state.triggerCount++;
        store.triggerCount = _state.triggerCount;
        store.lastKeyword = ev.data.matched_keyword || '--';
        resetPipeline();
        markPipelineStage('trigger', now);
        addEventRow({
          timestamp: ev.timestamp,
          text: ev.data.trigger_text || '觸發',
          reqId: ev.req_id
        });
        appendLog('TRIGGER', truncate(ev.data.trigger_text, 60), ev.timestamp);
        if (!isHistory) showToast('觸發偵測', ev.data.trigger_text || '已觸發', 'info');
        break;

      /* ── Capture ── */
      case 'capture_requested':
        markPipelineStage('capture', now);
        appendLog('CAPTURE', '請求拍照', ev.timestamp);
        break;

      case 'capture_received': {
        _state.imageCount++;
        store.imageCount = _state.imageCount;
        store.lastImageSize = fmtBytes(ev.data.image_size || 0);
        markPipelineStage('capture', now);

        const fn = ev.data.filename;
        if (fn) {
          store.snapSrc = `${getBaseUrl()}/images/${encodeURIComponent(fn)}?t=${Date.now()}`;
          store.snapFilename = fn;
        } else if (ev.data.image_base64) {
          store.snapSrc = 'data:image/jpeg;base64,' + ev.data.image_base64;
          store.snapFilename = 'base64';
        }
        store.snapSize = fmtBytes(ev.data.image_size || 0);
        store.snapTime = fmtTime(ev.timestamp);
        appendLog('IMAGE', `${fn || 'capture'} (${fmtBytes(ev.data.image_size || 0)})`, ev.timestamp);
        break;
      }

      /* ── Vision ── */
      case 'vision_started':
        markPipelineStage('vision', now);
        appendLog('VISION', '分析開始', ev.timestamp);
        break;

      case 'vision_result': {
        _state.visionCount++;
        store.visionCount = _state.visionCount;
        store.lastVisionConf = ev.data.confidence
          ? (ev.data.confidence * 100).toFixed(1) + '%'
          : '--';
        markPipelineStage('vision', now);

        const confLine = ev.data.confidence
          ? `<p class="vision-meta">信心度: ${(ev.data.confidence * 100).toFixed(1)}%</p>`
          : '';
        store.visionHtml = `
          <div class="vision-text">${esc(ev.data.text || '')}</div>
          ${confLine}
          <p class="vision-meta">ID: ${esc(ev.req_id || '--')}</p>
        `;
        store.visionReqId = ev.req_id || '';
        appendLog('VISION', truncate(ev.data.text, 60), ev.timestamp);
        break;
      }

      /* ── TTS ── */
      case 'tts_started':
        store.ttsPlaying = true;
        store.ttsProgress = 0;
        markPipelineStage('tts', now);
        appendLog('TTS', truncate(ev.data.text, 60), ev.timestamp);
        // Simulate progress (backend doesn't stream progress yet)
        simulateTtsProgress();
        break;

      /* ── Question detected ── */
      case 'question_detected':
        appendLog('QUESTION', truncate(ev.data.question_text, 60), ev.timestamp);
        break;


      /* ── Phase 2: Camera Streaming ── */
      case 'camera_stream_started':
        store.cameraStreaming = true;
        store.cameraFps = ev.data.fps || 1;
        appendLog('CAMERA', `Stream started @ ${store.cameraFps} FPS`, ev.timestamp);
        break;

      case 'camera_stream_stopped':
        store.cameraStreaming = false;
        appendLog('CAMERA', 'Stream stopped', ev.timestamp);
        break;

      case 'camera_frame_received':
        // Update snapshot immediately for live preview
       if (ev.data.filename) {
          store.snapSrc = `${getBaseUrl()}/images/${encodeURIComponent(ev.data.filename)}?t=${Date.now()}`;
          store.snapFilename = ev.data.filename;
        }
        store.snapSize = fmtBytes(ev.data.image_size || 0);
        store.snapTime = fmtTime(ev.timestamp);
        break;


      /* ── Error ── */
      case 'error':
        appendLog('ERROR', truncate(ev.data?.message || 'Unknown error', 60), ev.timestamp);
        if (!isHistory) showToast('系統錯誤', ev.data?.message || '未知錯誤', 'error');
        break;

      default:
        appendLog('EVENT', ev.event_type, ev.timestamp);
    }
  }

  /* ─────────────────────────────────────────────────────────
     §11  TTS PROGRESS SIMULATION
     Since the backend doesn't stream chunk-level progress,
     we animate from 0→90% over 8s, jump to 100% when a new
     event supersedes or user stops.
     ───────────────────────────────────────────────────────── */

  let _ttsInterval = null;

  function simulateTtsProgress() {
    clearInterval(_ttsInterval);
    store.ttsProgress = 0;
    store.ttsPlaying = true;
    let pct = 0;
    _ttsInterval = setInterval(() => {
      pct += 2;  // ~100 ticks × 160ms ≈ 16s to 100%
      if (pct >= 90) {
        // Hold at 90% until completion event or next trigger
        pct = 90;
      }
      store.ttsProgress = pct;
    }, 160);
  }

  function stopTts() {
    clearInterval(_ttsInterval);
    store.ttsPlaying = false;
    store.ttsProgress = 100;
    // Send stop signal (if backend supports it in the future)
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stop_tts' }));
    }
    setTimeout(() => { store.ttsProgress = 0; }, 600);
    showToast('TTS 停止', '語音播放已停止', 'info');
  }

  /* ─────────────────────────────────────────────────────────
     §12  REST API CALLS (history, health, images)
     ───────────────────────────────────────────────────────── */

  async function loadHistory() {
    try {
      const resp = await fetch(`${getBaseUrl()}/api/history?limit=40`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (Array.isArray(data.events)) {
        [...data.events].reverse().forEach(ev => handleEvent(ev, { isHistory: true }));
      }
    } catch (e) {
      console.error('[loadHistory]', e);
    }
  }

  async function refreshHealth() {
    try {
      const resp = await fetch(`${getBaseUrl()}/api/health`);
      if (!resp.ok) return;
      const data = await resp.json();
      store.imagesStored = data.images_stored || 0;
      store.healthStatus = data.status || '--';
      store.audioOnline = !!data.esp32_audio_connected;
      store.cameraOnline = !!data.esp32_camera_connected;
    } catch (e) {
      console.error('[refreshHealth]', e);
    }
  }

  async function loadLatestImage() {
    try {
      const resp = await fetch(`${getBaseUrl()}/api/images`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (!Array.isArray(data.images) || data.images.length === 0) return;
      const latest = data.images[0];
      store.snapSrc = `${getBaseUrl()}/images/${encodeURIComponent(latest.filename)}?t=${Date.now()}`;
      store.snapFilename = latest.filename;
      store.snapSize = fmtBytes(latest.size || 0);
      store.snapTime = latest.created ? fmtTime(latest.created) : '--';
    } catch (e) {
      console.error('[loadLatestImage]', e);
    }
  }

  /* ─────────────────────────────────────────────────────────
     §13  INIT — wire up everything on DOMContentLoaded
     ───────────────────────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', () => {
    // Theme
    initTheme();
    $('themeToggle').addEventListener('click', toggleTheme);

    // Buttons
    $('btnStopTts').addEventListener('click', stopTts);
    $('btnClearLog').addEventListener('click', clearLog);

    // Initial data load
    connectWs();
    loadHistory();
    refreshHealth();
    loadLatestImage();

    // Periodic health poll
    setInterval(refreshHealth, 30000);

    // Force first render
    scheduleRender();
  });

  /* ─────────────────────────────────────────────────────────
     §14  SERVICE WORKER REGISTRATION (PWA)
     ───────────────────────────────────────────────────────── */

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('sw.js').catch(err => {
        console.warn('[SW] registration failed:', err);
      });
    });
  }

})();
