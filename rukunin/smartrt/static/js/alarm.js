/* RUKUNIN · alarm.js — Mesin suara alarm darurat yang berjalan di SEMUA halaman.
   Selama alarm aktif, sirene + pesan suara (VN) warga terus berulang walaupun pengguna berpindah menu,
   dan baru berhenti ketika alarm dimatikan oleh Ketua RT (atau suara dibisukan di perangkat ini).
   Agar suara tidak terputus saat pindah halaman, js/app.js memakai navigasi tanpa muat ulang selama alarm aktif.
   Nilai awal dari server: window.RUKUNIN = {csrf, role, alarmAktif, alarmId} (templates/layout/base.html). */
(function () {
  'use strict';

  var G = window.RUKUNIN || {};
  var state = { aktif: !!G.alarmAktif, id: G.alarmId || 0 };
  var MUTE_KEY = 'rukunin.alarm.mute';

  function readMute() { try { return sessionStorage.getItem(MUTE_KEY) === '1'; } catch (e) { return false; } }
  function saveMute(v) { try { sessionStorage.setItem(MUTE_KEY, v ? '1' : '0'); } catch (e) {} }

  var loopMuted = readMute();     // bisu hanya di perangkat/tab ini
  var eng = null;                 // engine aktif (satu per sesi alarm)
  var needUnlock = false;
  var bar = null;

  function onDaruratPage() { return location.pathname === '/darurat'; }

  /* ===================================================== AUDIO ENGINE =====
     Sirene + VN warga diputar BERSAMAAN dan di-loop sampai alarm dimatikan.
     - Pemutaran: HTMLAudioElement (aman untuk file WebM hasil MediaRecorder)
     - Ducking  : Web Audio API (GainNode) -> bekerja juga di iOS, yang mengabaikan audio.volume.
     Ubah angka di AUDIO_CFG untuk menyetel suara. */
  var AUDIO_CFG = {
    sirenDucked: 0.35,  // volume sirene saat VN sedang diputar
    sirenFull:   0.85,  // volume sirene saat VN jeda antar-pengulangan
    vnVolume:    1.0,   // volume VN warga
    vnGapMs:     1500,  // jeda antar pengulangan VN (0 = langsung nyambung)
    rampSec:     0.35   // kecepatan transisi naik/turun volume sirene
  };

  function mkAudioEl(src, loop) {
    var a = new Audio();
    a.preload = 'auto';
    a.loop = loop;
    a.src = src;
    return a;
  }

  // Tunggu sampai audio siap diputar (atau gagal / timeout)
  function whenReady(a, timeoutMs) {
    return new Promise(function (resolve) {
      if (a.readyState >= 3) return resolve(true);
      var done = false;
      function fin(v) { if (!done) { done = true; resolve(v); } }
      a.addEventListener('canplaythrough', function () { fin(true); }, { once: true });
      a.addEventListener('error', function () { fin(false); }, { once: true });
      setTimeout(function () { fin(a.readyState >= 2); }, timeoutMs);
      a.load();
    });
  }

  function safePlay(a) {
    var p = a.play();
    if (p && p.catch) p.catch(function () {});
  }

  // Ducking: sirene turun saat VN berbunyi, naik lagi saat VN jeda
  function setDuck(e, vnPlaying) {
    var g = e.sirenGain.gain, t = e.ctx.currentTime;
    var target = (vnPlaying && e.vnOk) ? AUDIO_CFG.sirenDucked : AUDIO_CFG.sirenFull;
    g.cancelScheduledValues(t);
    g.setValueAtTime(g.value, t);
    g.linearRampToValueAtTime(target, t + AUDIO_CFG.rampSec);
  }

  function createEngine() {
    var AC = window.AudioContext || window.webkitAudioContext;
    var ctx = new AC();

    var master = ctx.createGain();
    master.gain.value = loopMuted ? 0 : 1;
    master.connect(ctx.destination);

    var siren = mkAudioEl('/api/darurat/sirene', true);
    var sirenGain = ctx.createGain();
    ctx.createMediaElementSource(siren).connect(sirenGain);
    sirenGain.connect(master);

    var vn = mkAudioEl('/api/darurat/rekaman?v=' + state.id, false);
    var vnGain = ctx.createGain();
    vnGain.gain.value = AUDIO_CFG.vnVolume;
    ctx.createMediaElementSource(vn).connect(vnGain);
    vnGain.connect(master);

    var e = { ctx: ctx, master: master, siren: siren, vn: vn,
              sirenGain: sirenGain, vnGain: vnGain,
              ready: false, started: false, sirenOk: false, vnOk: false, gapTimer: null };

    // Cadangan: kalau loop bawaan sirene gagal, ulangi manual
    siren.addEventListener('ended', function () {
      if (eng !== e || !e.started) return;
      siren.currentTime = 0; safePlay(siren);
    });

    // VN: durasi file MediaRecorder sering tidak diketahui -> ulangi manual
    vn.addEventListener('ended', function () {
      if (eng !== e || !e.started) return;
      setDuck(e, false);                      // jeda: sirene naik
      clearTimeout(e.gapTimer);
      e.gapTimer = setTimeout(function () {
        if (eng !== e) return;
        vn.currentTime = 0;
        setDuck(e, true);                     // VN mulai: sirene turun
        safePlay(vn);
      }, AUDIO_CFG.vnGapMs);
    });

    // Kalau VN gagal dimuat/diputar, sirene tetap berbunyi normal
    vn.addEventListener('error', function () {
      if (eng !== e || !e.started) return;
      e.vnOk = false; setDuck(e, false);
    });
    return e;
  }

  // Mulai kedua audio dalam satu tick -> benar-benar bersamaan
  function startPlayback(e) {
    if (eng !== e || e.started || !e.ready) return;
    e.started = true;
    hideUnlock();
    e.sirenGain.gain.value = e.vnOk ? AUDIO_CFG.sirenDucked : AUDIO_CFG.sirenFull;
    e.siren.currentTime = 0;
    e.vn.currentTime = 0;
    if (e.sirenOk) safePlay(e.siren);
    if (e.vnOk)    safePlay(e.vn);
  }

  // Browser memblokir suara sebelum ada interaksi -> minta satu ketukan
  function tryRun(e) {
    if (eng !== e || e.started || !e.ready) return;
    function check() {
      if (eng !== e || e.started) return;
      if (e.ctx.state === 'running') startPlayback(e); else showUnlock();
    }
    var p = e.ctx.resume();
    if (p && p.then) p.then(check, check);
    setTimeout(check, 400);
  }

  function renderUnlock() {
    var old = document.getElementById('audioUnlock');
    if (old) old.remove();
    if (!needUnlock) return;
    var b = document.createElement('button');
    b.id = 'audioUnlock'; b.type = 'button';
    b.textContent = '🔊 Ketuk untuk menyalakan suara alarm';
    var actions = bar && bar.querySelector('.ab-actions');
    if (actions) {
      b.className = 'btn red sm';
      actions.insertBefore(b, actions.firstChild);
    } else {
      b.className = 'btn red';
      b.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);' +
        'z-index:9999;padding:14px 22px;font-size:1rem;box-shadow:0 6px 24px rgba(0,0,0,.35)';
      document.body.appendChild(b);   // klik ditangani listener gesture di bawah
    }
  }
  function showUnlock() { if (needUnlock) return; needUnlock = true; renderUnlock(); }
  function hideUnlock() { needUnlock = false; renderUnlock(); }

  function startLoop() {
    if (!state.aktif) return;
    if (eng) { tryRun(eng); return; }          // idempoten: tidak membuat audio ganda
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    var e = createEngine();
    eng = e;
    Promise.all([whenReady(e.siren, 4000), whenReady(e.vn, 4000)]).then(function (r) {
      if (eng !== e) return;
      e.sirenOk = r[0]; e.vnOk = r[1]; e.ready = true;
      if (!e.sirenOk && !e.vnOk) { setTimeout(function () {   // coba lagi bila keduanya gagal
        if (eng === e) { stopEngineOnly(); startLoop(); } }, 3000); return; }
      tryRun(e);
    });
  }

  function stopEngineOnly() {
    var e = eng; eng = null;
    if (!e) return;
    clearTimeout(e.gapTimer);
    [e.siren, e.vn].forEach(function (a) { a.pause(); a.removeAttribute('src'); a.load(); });
    try { e.ctx.close(); } catch (_) {}
  }

  function stopLoop() {
    state.aktif = false;
    hideUnlock();
    stopEngineOnly();
  }

  // Mute lokal: tetap berjalan sinkron, hanya volume master yang 0
  function toggleMute() {
    loopMuted = !loopMuted;
    saveMute(loopMuted);
    if (eng) eng.master.gain.setTargetAtTime(loopMuted ? 0 : 1, eng.ctx.currentTime, 0.05);
    else if (!loopMuted) startLoop();
    updateMuteLabels();
    return loopMuted;
  }
  function muteLabel() { return loopMuted ? '🔊 Hidupkan suara' : '🔇 Matikan di perangkat ini'; }
  function updateMuteLabels() {
    var b = bar && bar.querySelector('[data-ab="mute"]');
    if (b) b.textContent = muteLabel();
    var d = document.getElementById('btnMuteLoop');
    if (d) d.textContent = loopMuted ? '🔊 Hidupkan kembali' : '🔇 Matikan di perangkat ini';
  }

  // Tab kembali terlihat: pulihkan AudioContext yang ditangguhkan browser
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) return;
    if (eng && eng.started && eng.ctx.state !== 'running') eng.ctx.resume();
    poll();
  });

  // Setiap ketukan/klik pertama membuka kunci suara (aturan autoplay browser)
  ['click', 'touchstart', 'keydown'].forEach(function (ev) {
    document.addEventListener(ev, function () { if (state.aktif) startLoop(); }, { passive: true });
  });

  /* ===================================================== BAR PERINGATAN =====
     Di halaman selain Alarm Darurat, tampil bar kecil di bawah layar selama alarm berbunyi. */
  function renderBar() {
    var show = state.aktif && !onDaruratPage();
    document.body.classList.toggle('alarm-bar-on', show);
    if (!show) {
      if (bar) { bar.remove(); bar = null; renderUnlock(); }
      return;
    }
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'alarmBar';
      bar.className = 'alarm-bar';
      bar.setAttribute('role', 'alert');
      bar.innerHTML =
        '<span class="ab-pulse" aria-hidden="true">🚨</span>' +
        '<span class="ab-text"><b>Alarm darurat sedang berbunyi</b><small>Suara tetap menyala di semua menu sampai alarm dimatikan.</small></span>' +
        '<span class="ab-actions">' +
          (G.role !== 'admin' ? '<a class="btn out sm" href="/darurat">Buka panel</a>' : '') +
          '<button type="button" class="btn out sm" data-ab="mute"></button>' +
          (G.role === 'ketua' ? '<button type="button" class="btn red sm" data-ab="stop">🛑 Matikan alarm</button>' : '') +
        '</span>';
      document.body.appendChild(bar);
      bar.addEventListener('click', function (e) {
        var b = e.target.closest('[data-ab]');
        if (!b) return;
        if (b.dataset.ab === 'mute') toggleMute();
        if (b.dataset.ab === 'stop') stopAlarmRequest(b);
      });
      renderUnlock();
    }
    updateMuteLabels();
  }
  document.addEventListener('rukunin:navigated', renderBar);

  // Ketua mematikan alarm dari bar mana pun (server tetap memeriksa peran)
  function stopAlarmRequest(btn) {
    btn.disabled = true;
    fetch('/api/darurat/stop', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRF-Token': G.csrf || '', 'Content-Type': 'application/json' }
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j.ok) { deactivate(); window.Rukunin && window.Rukunin.syncChrome(); }
      else { btn.disabled = false; alert('Gagal: ' + (j.pesan || 'Hanya Ketua RT yang berhak mematikan alarm.')); }
    }).catch(function () { btn.disabled = false; alert('Koneksi gagal.'); });
  }

  /* ===================================================== STATUS ===== */
  function activate(id) {          // dipanggil dari tombol (ada gesture pengguna -> suara langsung boleh berbunyi)
    if (id) state.id = id;
    if (state.aktif && eng) { renderBar(); return; }
    state.aktif = true;
    startLoop();
    renderBar();
  }
  function deactivate() {
    stopLoop();
    renderBar();
  }
  function changed() {
    renderBar();
    if (!window.Rukunin) return;
    if (onDaruratPage()) window.Rukunin.refresh(); else window.Rukunin.syncChrome();
  }

  // Sinkronisasi multi-perangkat: alarm dinyalakan/dimatikan dari perangkat lain
  function poll() {
    fetch('/api/darurat/status', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        if (j.aktif) {
          if (!state.aktif || j.id !== state.id) {
            var wasAktif = state.aktif;
            if (wasAktif) stopEngineOnly();          // alarm baru: muat ulang audio (VN berbeda)
            state.aktif = true; state.id = j.id;
            startLoop();
            changed();
          }
        } else if (state.aktif) {
          deactivate();
          changed();
        }
      }).catch(function () {});
  }
  setInterval(poll, 6000);

  window.RukuninAlarm = {
    active: function () { return state.aktif; },
    activate: activate,
    deactivate: deactivate,
    toggleMute: toggleMute,
    isMuted: function () { return loopMuted; },
    updateLabels: updateMuteLabels
  };

  // Alarm sudah aktif saat halaman dibuka: langsung coba bunyi (jika diblokir browser, tombol "Ketuk" muncul)
  if (state.aktif) startLoop();
  renderBar();
})();
