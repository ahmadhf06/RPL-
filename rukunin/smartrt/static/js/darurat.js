/* Halaman Alarm Darurat: rekam suara, aktifkan/matikan alarm, unggah sirene.
   Suara sirene + VN dimainkan oleh js/alarm.js (global). Nilai dari server: window.DARURAT_CFG (templates/darurat/index.html). */
(function () {
  'use strict';

  /* ---- helpers ---- */
  var CFG = window.DARURAT_CFG || {};
  var CSRF = (window.RUKUNIN && window.RUKUNIN.csrf) || CFG.csrf;
  function apiPost(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); });
  }

  /* ---- state ---- */
  var mediaRec = null, chunks = [], blob = null, uploadedName = null;
  var timerInterval = null, secs = 0;

  /* ---- element refs ---- */
  var btnRekam    = document.getElementById('btnRekam');
  var btnStop     = document.getElementById('btnStop');
  var recDot      = document.getElementById('recDot');
  var recTime     = document.getElementById('recTime');
  var panelPreview = document.getElementById('panelPreview');
  var panelRekam  = document.getElementById('panelRekam');
  var panelAktifkan = document.getElementById('panelAktifkan');
  var audioPreview = document.getElementById('audioPreview');
  var btnUlang    = document.getElementById('btnUlang');
  var btnUnggah   = document.getElementById('btnUnggah');
  var uploadStatus = document.getElementById('uploadStatus');
  var btnAktifkan  = document.getElementById('btnAktifkan');
  var formStop    = document.getElementById('formStop');
  var btnMuteLoop = document.getElementById('btnMuteLoop');
  var inputJenis  = document.getElementById('inputJenis');
  var inputPesan  = document.getElementById('inputPesan');

  /* ---- step helper ---- */
  function setStep(n) {
    [1,2,3,4].forEach(function(i){
      var el = document.getElementById('s'+i);
      if (!el) return;
      el.className = 'step' + (i < n ? ' done' : i === n ? ' active' : '');
    });
  }

  /* ===================================================== RECORDING ===== */
  function fmtTime(s) {
    var m = Math.floor(s / 60);
    return (m < 10 ? '0'+m : m) + ':' + (s%60 < 10 ? '0'+(s%60) : s%60);
  }

  if (btnRekam) btnRekam.addEventListener('click', function () {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      alert('Browser Anda tidak mendukung perekaman suara. Gunakan Chrome atau Firefox terbaru.');
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      chunks = []; blob = null; uploadedName = null;
      secs = 0; recTime.textContent = '00:00';

      var mime = ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus',
                  'audio/ogg','audio/mp4'].find(function(t){return MediaRecorder.isTypeSupported(t);}) || '';
      mediaRec = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
      mediaRec.ondataavailable = function (e) { if (e.data.size > 0) chunks.push(e.data); };
      mediaRec.onstop = function () {
        stream.getTracks().forEach(function(t){t.stop();});
        blob = new Blob(chunks, { type: mediaRec.mimeType || 'audio/webm' });
        audioPreview.src = URL.createObjectURL(blob);
        panelRekam.hidden = true;
        panelPreview.hidden = false;
        setStep(2);
      };
      mediaRec.start(500);
      recDot.classList.add('recording');
      btnRekam.hidden = true;
      btnStop.hidden = false;

      timerInterval = setInterval(function(){
        secs++;
        recTime.textContent = fmtTime(secs);
        if (secs >= 300) { mediaRec.stop(); clearInterval(timerInterval); } // max 5 menit
      }, 1000);
    }).catch(function (err) {
      alert('Akses mikrofon ditolak atau tidak tersedia: ' + err.message);
    });
  });

  if (btnStop) btnStop.addEventListener('click', function () {
    if (mediaRec && mediaRec.state !== 'inactive') {
      clearInterval(timerInterval);
      recDot.classList.remove('recording');
      btnStop.hidden = true;
      mediaRec.stop();
    }
  });

  /* ===================================================== ULANG ===== */
  if (btnUlang) btnUlang.addEventListener('click', function () {
    blob = null; uploadedName = null; chunks = [];
    panelPreview.hidden = true;
    panelRekam.hidden = false;
    btnRekam.hidden = false;
    btnStop.hidden = true;
    recDot.classList.remove('recording');
    recTime.textContent = '00:00';
    secs = 0;
    uploadStatus.textContent = '';
    setStep(1);
  });

  /* ===================================================== UPLOAD ===== */
  if (btnUnggah) btnUnggah.addEventListener('click', function () {
    if (!blob) { alert('Rekaman tidak ditemukan.'); return; }
    btnUnggah.disabled = true;
    uploadStatus.textContent = 'Mengunggah rekaman…';

    var ext = (blob.type.split(';')[0].split('/')[1] || 'webm');
    var fd = new FormData();
    fd.append('audio', blob, 'rekaman.' + ext);

    fetch('/api/darurat/upload', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRF-Token': CSRF }, body: fd
    }).then(function(r){ return r.json(); }).then(function(j){
      if (j.ok) {
        uploadedName = j.filename;
        uploadStatus.textContent = '✔ Rekaman siap.';
        panelPreview.hidden = true;
        panelAktifkan.hidden = false;
        setStep(3);
      } else {
        uploadStatus.textContent = '❌ ' + (j.pesan || 'Gagal mengunggah.');
        btnUnggah.disabled = false;
      }
    }).catch(function(){
      uploadStatus.textContent = '❌ Koneksi gagal.';
      btnUnggah.disabled = false;
    });
  });

  /* ===================================================== NYALAKAN LANGSUNG (TANPA POPUP) ===== */
  var btnNyalakanLangsung = document.getElementById('btnNyalakanLangsung');
  if (btnNyalakanLangsung) {
    btnNyalakanLangsung.addEventListener('click', function () {
      btnNyalakanLangsung.disabled = true;
      btnNyalakanLangsung.textContent = '🚨 Menyalakan Sirene Alarm…';

      // Langsung nyalakan alarm darurat tanpa popup konfirmasi
      apiPost('/api/darurat/aktifkan', {
        jenis: 'Keadaan Darurat Lingkungan',
        pesan: 'Alarm darurat dinyalakan segera! Seluruh warga dimohon waspada dan saling membantu.'
      }).then(function(j) {
        if (j.ok) {
          ALARM().activate(j.id);      // dari klik pengguna -> suara langsung berbunyi
          refreshPage();
        } else {
          alert('Gagal menyalakan alarm: ' + (j.pesan || 'Terjadi kesalahan.'));
          btnNyalakanLangsung.disabled = false;
          btnNyalakanLangsung.textContent = '🚨 NYALAKAN ALARM SEKARANG (LANGSUNG BUNYI)';
        }
      }).catch(function() {
        alert('Koneksi server gagal.');
        btnNyalakanLangsung.disabled = false;
        btnNyalakanLangsung.textContent = '🚨 NYALAKAN ALARM SEKARANG (LANGSUNG BUNYI)';
      });
    });
  }

  /* ===================================================== AKTIFKAN DENGAN REKAMAN (TANPA POPUP) ===== */
  if (btnAktifkan) btnAktifkan.addEventListener('click', function () {
    var jenis = (inputJenis ? inputJenis.value.trim() : '') || 'Keadaan Darurat Warga';
    var pesan = inputPesan ? inputPesan.value.trim() : '';
    btnAktifkan.disabled = true;
    btnAktifkan.textContent = 'Mengaktifkan…';

    // Langsung aktifkan tanpa popup confirm
    apiPost('/api/darurat/aktifkan', { jenis: jenis, pesan: pesan, rekaman: uploadedName })
      .then(function(j){
        if (j.ok) {
          setStep(4);
          ALARM().activate(j.id);
          refreshPage();
        } else {
          alert('Gagal: ' + (j.pesan || 'Terjadi kesalahan.'));
          btnAktifkan.disabled = false;
          btnAktifkan.textContent = '🚨 Aktifkan Alarm dengan Rekaman';
        }
      }).catch(function(){
        alert('Koneksi gagal.');
        btnAktifkan.disabled = false;
        btnAktifkan.textContent = '🚨 Aktifkan Alarm dengan Rekaman';
      });
  });

  /* ===================================================== STOP ALARM (HANYA KETUA RT) ===== */
  if (formStop) formStop.addEventListener('submit', function(e){
    e.preventDefault();
    var btn = document.getElementById('btnStopAlarm');
    if(btn) { btn.disabled = true; btn.textContent = 'Menghentikan…'; }

    fetch('/api/darurat/stop', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' }
    }).then(function(r){ return r.json(); }).then(function(j){
      if (j.ok) {
        ALARM().deactivate();
        location.reload();
      } else {
        alert('Gagal: ' + (j.pesan || 'Hanya Ketua RT yang berhak mematikan alarm.'));
        if(btn) { btn.disabled = false; btn.textContent = '🛑 Matikan Alarm Darurat (Ketua RT)'; }
      }
    }).catch(function(){
      alert('Koneksi gagal.');
      if(btn) { btn.disabled = false; btn.textContent = '🛑 Matikan Alarm Darurat (Ketua RT)'; }
    });
  });

  /* ===================================================== SUARA ALARM =====
     Mesin sirene + VN ada di js/alarm.js (global, jalan di semua halaman, tidak putus saat pindah menu).
     Di sini hanya tombol-tombol halaman ini yang memanggilnya. */
  var ALARM = function () { return window.RukuninAlarm || { activate: function () {}, deactivate: function () {}, toggleMute: function () { return false; }, isMuted: function () { return false; }, updateLabels: function () {} }; };
  function refreshPage() { if (window.Rukunin) window.Rukunin.refresh(); else location.reload(); }

  // Mute lokal (hanya perangkat ini)
  if (btnMuteLoop) {
    btnMuteLoop.addEventListener('click', function () { ALARM().toggleMute(); });
    // alarm.js dimuat setelah skrip ini (defer): sesuaikan tulisan tombol begitu halaman siap
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { ALARM().updateLabels(); });
    else ALARM().updateLabels();
  }

  /* ===================================================== TES TELEGRAM (KETUA/ADMIN) ===== */
  var btnTesTelegram = document.getElementById('btnTesTelegram');
  if (btnTesTelegram) btnTesTelegram.addEventListener('click', function () {
    var st = document.getElementById('tgStatus');
    btnTesTelegram.disabled = true;
    st.textContent = 'Mengirim…';
    apiPost('/api/darurat/telegram-tes', {}).then(function (j) {
      st.textContent = j.ok ? '✔ Terkirim ke ' + j.berhasil + ' dari ' + j.tujuan + ' chat.' : '❌ ' + (j.pesan || 'Gagal.');
    }).catch(function () {
      st.textContent = '❌ Koneksi gagal.';
    }).then(function () { btnTesTelegram.disabled = false; });
  });

  /* ===================================================== TES NOTIFIKASI HP / NTFY (KETUA/ADMIN) ===== */
  var btnTesNtfy = document.getElementById('btnTesNtfy');
  if (btnTesNtfy) btnTesNtfy.addEventListener('click', function () {
    var st = document.getElementById('ntfyStatus');
    btnTesNtfy.disabled = true;
    st.textContent = 'Mengirim…';
    apiPost('/api/darurat/ntfy-tes', {}).then(function (j) {
      st.textContent = j.ok ? '✔ Terkirim. HP yang berlangganan topik harus berbunyi.' : '❌ ' + (j.pesan || 'Gagal.');
    }).catch(function () {
      st.textContent = '❌ Koneksi gagal.';
    }).then(function () { btnTesNtfy.disabled = false; });
  });

  /* ===================================================== UPLOAD SIRENE ===== */
  var formSirene = document.getElementById('formSirene');
  if (formSirene) formSirene.addEventListener('submit', function(e){
    e.preventDefault();
    var file = document.getElementById('fileSirene').files[0];
    var status = document.getElementById('sireneStatus');
    if (!file) { alert('Pilih file audio terlebih dahulu.'); return; }
    status.textContent = 'Mengunggah…';
    var fd = new FormData();
    fd.append('sirene', file);
    fetch('/api/darurat/upload-sirene', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRF-Token': CSRF }, body: fd
    }).then(function(r){ return r.json(); }).then(function(j){
      status.textContent = j.ok ? '✔ Sirene berhasil diunggah.' : '❌ ' + (j.pesan||'Gagal.');
      if (j.ok) setTimeout(function(){ location.reload(); }, 1200);
    }).catch(function(){ status.textContent = '❌ Koneksi gagal.'; });
  });

})();
