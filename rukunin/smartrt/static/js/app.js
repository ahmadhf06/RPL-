/* RUKUNIN · app.js — Interaksi umum: menu aktif yang meluncur, panel profil (dibuka/ditutup dengan panah di kartu pengguna),
   modal kaca, transisi halaman, pencarian, cuaca, notifikasi (polling), statistik langsung, unggah foto profil,
   dan navigasi tanpa muat ulang selama alarm berbunyi. Tanpa library tambahan. */
(function () {
  'use strict';
  var body = document.body;
  var root = document.documentElement;
  body.classList.add('js-active');

  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function sess(k, v) { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } }
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ========================================================================
     1. Menu aktif sidebar (olive) — meluncur halus dari menu sebelumnya ke menu yang baru dibuka
     ======================================================================== */
  var placeActive = function () {};
  var slideActive = function () {};
  function initSidebarIndicator() {
    var menu = $('#sidebarMenu');
    var ind = $('#sidebarIndicator');
    if (!menu || !ind) return;

    function place(el) {
      ind.style.top = el.offsetTop + 'px';
      ind.style.height = el.offsetHeight + 'px';
    }
    function jump(el) {            // pindah tanpa animasi
      ind.style.transition = 'none';
      place(el);
      void ind.offsetHeight;
      ind.style.transition = '';
    }
    placeActive = function () {
      var a = $('a.on', menu);
      if (!a || a.offsetParent === null) { ind.style.opacity = '0'; return; }
      jump(a);
      ind.style.opacity = '1';
    };

    slideActive = function () {     // meluncur ke menu aktif yang baru (dipakai navigasi tanpa muat ulang)
      var a = $('a.on', menu);
      if (!a || a.offsetParent === null) { ind.style.opacity = '0'; return; }
      place(a);
      ind.style.opacity = '1';
    };

    var active = $('a.on', menu);
    if (!active) { ind.style.opacity = '0'; return; }
    var prevHref = sess('rukunin.nav');
    var prev = null;
    if (prevHref) $$('a[data-nav-link]', menu).forEach(function (a) { if (a.getAttribute('href') === prevHref) prev = a; });
    if (prev && prev !== active && !reduceMotion) {
      jump(prev);                  // mulai dari menu sebelumnya...
      ind.style.opacity = '1';
      requestAnimationFrame(function () { requestAnimationFrame(function () { place(active); }); });   // ...lalu meluncur
    } else {
      jump(active);
      ind.style.opacity = '1';
    }
    sess('rukunin.nav', active.getAttribute('href'));
    window.addEventListener('resize', placeActive);
  }

  /* Menu panjang: tampilkan pemudaran di bawah selama masih ada menu yang bisa digulir */
  function initMenuScrollHint() {
    [$('#sidebarMenu'), $('.panel-scroll')].forEach(function (box) {
      if (!box) return;
      function upd() { if (box.scrollHeight - box.scrollTop - box.clientHeight > 4) box.setAttribute('data-more', ''); else box.removeAttribute('data-more'); }
      box.addEventListener('scroll', upd);
      window.addEventListener('resize', upd);
      upd();
      if (box.id === 'sidebarMenu') {
        var a = $('a.on', box);
        if (a && a.offsetTop + a.offsetHeight > box.clientHeight) { box.scrollTop = a.offsetTop - 40; upd(); }
      }
    });
  }

  /* ========================================================================
     2. Pencarian global (menu & baris tabel)
     ======================================================================== */
  function initGlobalSearch() {
    var input = $('#globalSearchInput');
    if (!input) return;
    var full = input.getAttribute('placeholder');
    function fit() { input.setAttribute('placeholder', window.innerWidth <= 640 ? 'Cari...' : full); }
    fit();
    window.addEventListener('resize', fit);
    input.addEventListener('input', function () {
      var q = this.value.trim().toLowerCase();
      $$('#sidebarMenu a[data-nav-link]').forEach(function (item) {
        item.style.display = (!q || item.textContent.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
      });
      $$('.tw table tr:not(:first-child)').forEach(function (row) {
        row.style.display = (!q || row.textContent.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
      });
      placeActive();
    });
  }

  /* ========================================================================
     3. Panel profil kanan: tampil/sembunyi (desktop) atau laci geser (tablet & HP)
     ======================================================================== */
  function isDesktop() { return window.matchMedia('(min-width: 1201px)').matches; }
  function syncPanelToggle() {       // panah bawah di kartu pengguna: status buka/tutup untuk pembaca layar & animasi putar
    var open = isDesktop() ? root.classList.contains('panel-on') : body.classList.contains('panel-open');
    $$('[data-toggle-panel][aria-controls]').forEach(function (b) { b.setAttribute('aria-expanded', open ? 'true' : 'false'); });
  }
  function togglePanel() {
    if (isDesktop()) {
      root.classList.toggle('panel-on');
      store('rukunin.panel.' + root.dataset.panelKey, root.classList.contains('panel-on') ? 'on' : 'off');
    } else {
      body.classList.toggle('panel-open');
    }
    syncPanelToggle();
  }
  window.addEventListener('resize', syncPanelToggle);

  /* ========================================================================
     4. Modal kaca (dialog) — buka/tutup dengan transisi, plus konfirmasi bergaya kaca
     ======================================================================== */
  function openModal(d) {
    if (!d || d.open) return;
    if (d.showModal) d.showModal(); else d.setAttribute('open', '');
    var f = $('input:not([type=hidden]), select, textarea, button.btn:not(.out)', d);
    if (f) setTimeout(function () { f.focus(); }, 60);
  }
  function closeModal(d, cb) {
    if (!d || !d.open) { if (cb) cb(); return; }
    function fin() {
      d.classList.remove('closing');
      if (d.close) d.close(); else d.removeAttribute('open');
      if (cb) cb();
    }
    if (reduceMotion) return fin();
    d.classList.add('closing');
    setTimeout(fin, 230);
  }
  function wireDialog(d) {
    d.addEventListener('cancel', function (e) { e.preventDefault(); closeModal(d); });
    d.addEventListener('mousedown', function (e) { if (e.target === d) closeModal(d); });
  }
  $$('dialog.glass-modal').forEach(wireDialog);

  function confirmModal(msg) {
    return new Promise(function (resolve) {
      if (!window.HTMLDialogElement) { resolve(window.confirm(msg)); return; }
      var d = document.createElement('dialog');
      d.className = 'glass-modal';
      d.innerHTML = '<div class="gm-head"><h2>Konfirmasi</h2></div><div class="gm-body"><p></p></div>' +
        '<div class="gm-foot"><button type="button" class="btn out" data-r="0">Batal</button>' +
        '<button type="button" class="btn" data-r="1">Ya, lanjutkan</button></div>';
      $('p', d).textContent = msg;
      document.body.appendChild(d);
      wireDialog(d);
      var answered = false;
      function done(v) {
        if (answered) return;
        answered = true;
        closeModal(d, function () { d.remove(); resolve(v); });
      }
      d.addEventListener('click', function (e) { var b = e.target.closest('[data-r]'); if (b) done(b.dataset.r === '1'); });
      d.addEventListener('close', function () { done(false); });
      d.addEventListener('cancel', function () { done(false); });
      openModal(d);
    });
  }

  /* ========================================================================
     5. Transisi antarhalaman: konten memudar + skeleton selama halaman berikutnya dimuat
     ======================================================================== */
  function leaving(on) { body.classList.toggle('is-leaving', on); }
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target && a.target !== '_self') return;
    if (a.hasAttribute('download') || a.hasAttribute('data-no-transition') || a.hasAttribute('data-print')) return;
    var href = a.getAttribute('href') || '';
    if (!href || href.charAt(0) === '#' || /^(mailto|tel|javascript):/i.test(href)) return;
    if (a.origin !== location.origin) return;
    if (/\/(export|media)\b|\.(csv|pdf|mp3|webm)$/i.test(a.pathname)) return;
    if (a.pathname === location.pathname && a.search === location.search) return;
    if (reduceMotion) return;
    leaving(true);
    setTimeout(function () { leaving(false); }, 6000);       // pengaman bila navigasi tidak terjadi
  });
  window.addEventListener('pageshow', function () { leaving(false); });

  /* ========================================================================
     6. Kartu cuaca (Open-Meteo, tanpa kunci API). Gagal/offline -> pesan singkat.
     ======================================================================== */
  var WX = [
    [[0], 'Cerah', 'sun'], [[1, 2], 'Cerah berawan', 'partly'], [[3], 'Berawan', 'cloud'],
    [[45, 48], 'Berkabut', 'cloud'], [[51, 53, 55, 56, 57], 'Gerimis', 'rain'],
    [[61, 63, 65, 66, 67, 80, 81, 82], 'Hujan', 'rain'], [[95, 96, 99], 'Badai petir', 'storm']
  ];
  var WXI = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>',
    partly: '<path d="M12 3v1.5M4.2 6.2l1 1M2 13h1.5M19.8 6.2l-1 1"/><path d="M7.5 13a4 4 0 1 1 7.7-1.3"/><path d="M18 19H9a4 4 0 1 1 .8-7.9A5 5 0 0 1 18 14a2.5 2.5 0 0 1 0 5z"/>',
    cloud: '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
    rain: '<path d="M18 10h-1.26A8 8 0 1 0 9 17h9a4 4 0 0 0 0-7z"/><path d="M8 20l1-2M12 21l1-2M16 20l1-2"/>',
    storm: '<path d="M18 10h-1.26A8 8 0 1 0 9 17h9a4 4 0 0 0 0-7z"/><path d="M12 14l-2 4h3l-2 4"/>'
  };
  function wxInfo(code) {
    for (var i = 0; i < WX.length; i++) if (WX[i][0].indexOf(code) !== -1) return WX[i];
    return [[], 'Cuaca', 'cloud'];
  }
  function initWeather() {
    var card = $('#weatherCard');
    if (!card) return;
    var icon = $('#weatherIcon'), temp = $('#weatherTemp'), desc = $('#weatherDesc');
    var lat = parseFloat(card.dataset.lat), lng = parseFloat(card.dataset.lng);
    function fail() {
      icon.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + WXI.cloud + '</svg>';
      temp.textContent = '--°C';
      desc.textContent = 'Cuaca belum tersedia (periksa koneksi internet)';
    }
    if (isNaN(lat) || isNaN(lng) || !window.fetch) return fail();
    var url = 'https://api.open-meteo.com/v1/forecast?latitude=' + lat + '&longitude=' + lng +
      '&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&timezone=auto';
    fetch(url).then(function (r) { return r.ok ? r.json() : Promise.reject(); }).then(function (j) {
      var c = j.current, w = wxInfo(c.weather_code);
      icon.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + WXI[w[2]] + '</svg>';
      temp.textContent = Math.round(c.temperature_2m) + '°C';
      desc.textContent = w[1] + ' · lembap ' + Math.round(c.relative_humidity_2m) + '% · angin ' + Math.round(c.wind_speed_10m) + ' km/j';
    }).catch(fail);
  }

  /* ========================================================================
     7. Penangan klik & submit umum (fungsi lama tetap dipertahankan)
     ======================================================================== */
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-toggle-nav]')) body.classList.toggle('nav-open');
    if (e.target.closest('[data-toggle-panel]')) togglePanel();   // panah bawah di kartu pengguna / area gelap di luar laci
    var mo = e.target.closest('[data-modal-open]');
    if (mo) { e.preventDefault(); openModal($(mo.getAttribute('data-modal-open'))); }
    var mc = e.target.closest('[data-modal-close]');
    if (mc) { var dd = mc.closest('dialog'); if (dd) closeModal(dd); }
    if (e.target.closest('[data-print]')) window.print();
    var g = e.target.closest('[data-geo]');
    if (g && navigator.geolocation) {
      g.textContent = 'Mencari lokasi…';
      navigator.geolocation.getCurrentPosition(function (pos) {
        var latInput = document.getElementById('lat');
        var lngInput = document.getElementById('lng');
        if (latInput) latInput.value = pos.coords.latitude.toFixed(6);
        if (lngInput) lngInput.value = pos.coords.longitude.toFixed(6);
        g.textContent = 'Lokasi terisi ✓';
      }, function () {
        g.textContent = 'Gagal mengambil lokasi';
      });
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { body.classList.remove('nav-open'); body.classList.remove('panel-open'); syncPanelToggle(); }
  });

  // Konfirmasi (data-confirm) kini tampil sebagai popup kaca, bukan dialog bawaan browser
  document.addEventListener('submit', function (e) {
    var form = e.target;
    var m = form.getAttribute && form.getAttribute('data-confirm');
    if (!m || form.dataset.confirmed) return;
    e.preventDefault();
    var submitter = e.submitter;
    confirmModal(m).then(function (ok) {
      if (!ok) return;
      form.dataset.confirmed = '1';
      if (form.requestSubmit) form.requestSubmit(submitter || undefined); else form.submit();
    });
  });

  /* ========================================================================
     8. Notifikasi real-time, toast di atas layar, dan statistik langsung
     ======================================================================== */
  function get(url, cb) {
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) cb(j); })
      .catch(function () {});
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Menampilkan notifikasi pemberitahuan pesan di layar pada bagian atas
  function showTopNotificationToast(item) {
    if (!item) return;
    var host = document.getElementById('topNotificationHost');
    if (!host) {
      host = document.createElement('div');
      host.id = 'topNotificationHost';
      host.className = 'top-notification-host';
      document.body.appendChild(host);
    }

    var isDarurat = (item.judul || '').indexOf('🚨') !== -1 || (item.judul || '').toUpperCase().indexOf('ALARM') !== -1;
    var iconEmoji = isDarurat ? '🚨' : ((item.judul || '').indexOf('📢') !== -1 ? '📢' : '🔔');

    var toast = document.createElement('div');
    toast.className = 'top-notification-toast' + (isDarurat ? ' tnt-emergency' : '');
    toast.innerHTML = 
      '<div class="tnt-icon">' + iconEmoji + '</div>' +
      '<div class="tnt-body">' +
        '<div class="tnt-header">' +
          '<b class="tnt-title">' + escapeHtml(item.judul) + '</b>' +
          '<span class="tnt-badge">' + (isDarurat ? 'Darurat' : 'Pemberitahuan') + '</span>' +
        '</div>' +
        '<p class="tnt-msg">' + escapeHtml(item.pesan || '') + '</p>' +
      '</div>' +
      '<div class="tnt-actions">' +
        (item.id ? '<a href="/notifikasi/' + item.id + '/buka" class="tnt-btn">Buka Pesan</a>' : '') +
        '<button type="button" class="tnt-close" aria-label="Tutup">✕</button>' +
      '</div>';

    host.appendChild(toast);

    // Animasi meluncur turun dari atas
    setTimeout(function () {
      toast.classList.add('tnt-visible');
    }, 40);

    var closeBtn = toast.querySelector('.tnt-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        dismissToast(toast);
      });
    }

    // Hilang otomatis setelah 10 detik
    setTimeout(function () {
      dismissToast(toast);
    }, 10000);
  }

  function dismissToast(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.remove('tnt-visible');
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 400);
  }

  function updateNotifUI(j) {
    if (!j) return;
    // Update badge di icon lonceng
    document.querySelectorAll('[data-notif-count]').forEach(function (el) {
      el.textContent = j.unread;
      el.hidden = !j.unread;
    });

    var countBadge = document.getElementById('notifMenuCount');
    if (countBadge) {
      countBadge.textContent = j.unread ? (j.unread + ' baru') : '0 baru';
    }

    // Render list isi pesan di menu dropdown lonceng
    var menuList = document.getElementById('notifMenuList');
    if (menuList && j.items) {
      if (j.items.length === 0) {
        menuList.innerHTML = '<div class="notif-menu-empty">Tidak ada pemberitahuan baru.</div>';
      } else {
        var html = '';
        j.items.forEach(function (it) {
          var unreadClass = !it.dibaca ? ' nmi-unread' : '';
          var isDarurat = (it.judul || '').indexOf('🚨') !== -1;
          var iconEmoji = isDarurat ? '🚨' : ((it.judul || '').indexOf('📢') !== -1 ? '📢' : '🔔');
          html += '<a href="/notifikasi/' + it.id + '/buka" class="notif-menu-item' + unreadClass + '">' +
            '<div class="nmi-icon">' + iconEmoji + '</div>' +
            '<div class="nmi-content">' +
              '<div class="nmi-title">' + escapeHtml(it.judul) + '</div>' +
              '<div class="nmi-msg">' + escapeHtml(it.pesan || '') + '</div>' +
              '<small class="nmi-time muted">' + (it.created_at || '') + '</small>' +
            '</div>' +
          '</a>';
        });
        menuList.innerHTML = html;
      }
    }

    // Munculkan di layar bagian atas agar warga langsung mengetahui pesan
    if (j.items && j.unread > 0) {
      j.items.forEach(function (item) {
        if (!item.dibaca) {
          var key = 'notif_shown_' + item.id;
          if (!sessionStorage.getItem(key)) {
            sessionStorage.setItem(key, '1');
            showTopNotificationToast(item);
          }
        }
      });
    }
  }

  function initNotifDropdown() {
    var toggleBtn = document.getElementById('notifDropdownToggle');
    var menu = document.getElementById('notifMenu');
    if (!toggleBtn || !menu) return;

    function closeMenu() {
      menu.hidden = true;
      toggleBtn.setAttribute('aria-expanded', 'false');
    }

    function openMenu() {
      menu.hidden = false;
      toggleBtn.setAttribute('aria-expanded', 'true');
    }

    // Pastikan keadaan awal tertutup
    closeMenu();

    toggleBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (menu.hidden) openMenu(); else closeMenu();
    });

    // Klik di luar panel -> tutup
    document.addEventListener('click', function (e) {
      if (!menu.hidden && !menu.contains(e.target) && !toggleBtn.contains(e.target)) {
        closeMenu();
      }
    });

    // Tombol Esc -> tutup
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !menu.hidden) {
        closeMenu();
        toggleBtn.focus();
      }
    });
  }

  function poll() {
    if (document.hidden) return;
    get('/api/notifikasi', updateNotifUI);
    
    if (document.querySelector('[data-stat]')) {
      get('/api/stats', function (j) {
        document.querySelectorAll('[data-stat]').forEach(function (el) {
          var v = j.cards[el.dataset.stat];
          if (v !== undefined) el.textContent = v;
        });
      });
    }
  }

  if (document.querySelector('.sidebar')) {
    // Ambil data notifikasi saat pertama halaman dibuka
    poll();
    setInterval(poll, 15000);
  }


  /* ========================================================================
     9. Foto profil: pilih foto dari perangkat -> dipotong persegi & diperkecil di browser -> diunggah
     ======================================================================== */
  var AVATAR_PX = 512;
  function loadBitmap(file) {
    if (window.createImageBitmap) {
      return createImageBitmap(file, { imageOrientation: 'from-image' }).catch(function () { return createImageBitmap(file); });
    }
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onload = function () { var im = new Image(); im.onload = function () { resolve(im); }; im.onerror = reject; im.src = fr.result; };
      fr.onerror = reject;
      fr.readAsDataURL(file);
    });
  }
  function squareBlob(file) {
    return loadBitmap(file).then(function (img) {
      var w = img.width || img.naturalWidth, h = img.height || img.naturalHeight, s = Math.min(w, h);
      var c = document.createElement('canvas');
      c.width = c.height = Math.min(AVATAR_PX, s);
      var ctx = c.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, (w - s) / 2, (h - s) / 2, s, s, 0, 0, c.width, c.height);
      return new Promise(function (resolve, reject) {
        c.toBlob(function (b) { b ? resolve(b) : reject(); }, 'image/jpeg', 0.88);
      });
    });
  }
  function setAvatarImages(url) {
    $$('.user-chip-link .av img, .avatar-big img, [data-avatar-prev]').forEach(function (im) { im.src = url; });
  }
  function avatarToast(text, err) {
    showTopNotificationToast({ judul: err ? 'Foto profil gagal diubah' : 'Foto profil', pesan: text });
  }
  function avatarBusy(on) {
    $$('.avatar-big').forEach(function (b) { b.classList.toggle('uploading', on); });
  }
  function sendAvatar(fd) {
    avatarBusy(true);
    return fetch('/profil/foto', {
      method: 'POST', credentials: 'same-origin', body: fd,
      headers: { 'X-CSRF-Token': (window.RUKUNIN || {}).csrf || '', 'X-Requested-With': 'fetch' }
    }).then(function (r) { return r.json().catch(function () { return { ok: false, pesan: 'Gagal menyimpan foto (kode ' + r.status + ').' }; }); })
      .then(function (j) {
        if (!j.ok) { avatarToast(j.pesan || 'Gagal menyimpan foto.', true); return false; }
        setAvatarImages(j.url);
        avatarToast(j.pesan);
        return true;
      })
      .catch(function () { avatarToast('Koneksi gagal. Coba lagi.', true); return false; })
      .then(function (ok) { avatarBusy(false); return ok; });
  }
  function uploadAvatar(file) {
    if (!file) return Promise.resolve(false);
    if (!/^image\//.test(file.type)) { avatarToast('Pilih berkas gambar (JPG, PNG, atau WEBP).', true); return Promise.resolve(false); }
    return squareBlob(file).catch(function () {
      return file.size <= 5 * 1024 * 1024 ? file : null;        // cadangan: kirim apa adanya bila masih muat
    }).then(function (blob) {
      if (!blob) { avatarToast('Foto tidak dapat dibaca atau terlalu besar (maks. 5 MB).', true); return false; }
      var fd = new FormData();
      fd.append('foto', blob, 'foto.jpg');
      return sendAvatar(fd).then(function (ok) {
        if (ok) $$('[data-avatar-remove]').forEach(function (b) { b.hidden = false; });
        return ok;
      });
    });
  }
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-avatar-pick]')) {
      e.preventDefault();
      var inp = $('#avatarFile');
      if (inp) inp.click();
    }
    var rm = e.target.closest('[data-avatar-remove]');
    if (rm) {
      e.preventDefault();
      confirmModal('Hapus foto profil dan kembali ke gambar bawaan?').then(function (ok) {
        if (!ok) return;
        var fd = new FormData(); fd.append('hapus', '1');
        sendAvatar(fd).then(function (done) { if (done) $$('[data-avatar-remove]').forEach(function (b) { b.hidden = true; }); });
      });
    }
  });
  document.addEventListener('change', function (e) {
    var inp = e.target.closest && e.target.closest('input[data-avatar-file]');
    if (!inp || !inp.files || !inp.files[0]) return;
    if (inp.closest('[data-avatar-form]')) return;                // halaman Profil: diunggah lewat tombol "Unggah foto"
    uploadAvatar(inp.files[0]).then(function () { inp.value = ''; });
  });
  document.addEventListener('submit', function (e) {
    var f = e.target.closest && e.target.closest('[data-avatar-form]');
    if (!f) return;
    e.preventDefault();
    var inp = $('input[data-avatar-file]', f);
    if (inp && inp.files && inp.files[0]) uploadAvatar(inp.files[0]).then(function (ok) { if (ok) inp.value = ''; });
  });

  /* ========================================================================
     10. Navigasi tanpa muat ulang — aktif HANYA selama alarm darurat berbunyi, supaya suara sirene
         tidak terputus ketika warga membuka menu lain (lihat js/alarm.js). Di luar itu, navigasi biasa.
     ======================================================================== */
  var pjaxBusy = false, pjaxUsed = false;
  function pjaxOn() {
    return !!(window.RukuninAlarm && window.RukuninAlarm.active() && window.fetch && window.DOMParser && history.pushState);
  }
  function swapPart(sel, doc) {
    var cur = $(sel), nw = doc.querySelector(sel);
    if (cur && nw) cur.replaceWith(document.importNode(nw, true));
  }
  function runScripts(box) {       // skrip hasil parse tidak otomatis jalan: buat ulang agar dieksekusi
    $$('script', box).forEach(function (old) {
      var s = document.createElement('script');
      for (var i = 0; i < old.attributes.length; i++) s.setAttribute(old.attributes[i].name, old.attributes[i].value);
      s.async = false;
      s.text = old.text;
      old.replaceWith(s);
    });
  }
  function applyDoc(doc, url, mode) {
    var newMain = doc.querySelector('main.content');
    if (!newMain || doc.querySelector('.shell.guest') || !doc.getElementById('sidebarMenu')) return false;   // login/cetak/dll: muat biasa
    document.title = doc.title;
    body.classList.toggle('page-home', doc.body.classList.contains('page-home'));
    root.dataset.panelKey = doc.documentElement.dataset.panelKey || 'other';
    root.dataset.panelDefault = doc.documentElement.dataset.panelDefault || 'off';
    var pv = store('rukunin.panel.' + root.dataset.panelKey);
    if (pv === null || pv === undefined) pv = root.dataset.panelDefault;
    root.classList.toggle('panel-on', pv === 'on');

    var main = $('main.content');
    main.innerHTML = newMain.innerHTML;
    runScripts(main);

    // menu aktif (sidebar, menu bawah, pengaturan) mengikuti halaman baru
    $$('#sidebarMenu a[href], .menu-foot a[href], .bottom-nav a[href]').forEach(function (a) {
      var m = doc.querySelector((a.closest('.bottom-nav') ? '.bottom-nav' : a.closest('.menu-foot') ? '.menu-foot' : '#sidebarMenu') + ' a[href="' + a.getAttribute('href') + '"]');
      a.classList.toggle('on', !!(m && m.classList.contains('on')));
    });
    var act = $('#sidebarMenu a.on');
    if (act) sess('rukunin.nav', act.getAttribute('href'));
    ['.user-chip-link', '.avatar-big', '.panel-name', '.panel-role', '.safe-banner'].forEach(function (s) { swapPart(s, doc); });
    var dlg = doc.getElementById('modalProfil'), cur = $('#modalProfil');
    if (dlg && cur && !cur.open) { var nd = document.importNode(dlg, true); cur.replaceWith(nd); wireDialog(nd); }

    var si = $('#globalSearchInput');
    if (si && si.value) { si.value = ''; si.dispatchEvent(new Event('input')); }
    body.classList.remove('nav-open'); body.classList.remove('panel-open');
    syncPanelToggle();

    if (mode === 'push') { history.pushState({ rukunin: 1 }, '', url); window.scrollTo(0, 0); }
    else if (mode === 'replace') history.replaceState({ rukunin: 1 }, '', url);
    pjaxUsed = true;
    leaving(false);
    slideActive();
    initMenuScrollHint();
    poll();
    document.dispatchEvent(new CustomEvent('rukunin:navigated'));
    return true;
  }
  function pjaxLoad(url, init, mode) {
    if (pjaxBusy) return;
    pjaxBusy = true;
    leaving(true);
    init = init || {};
    init.credentials = 'same-origin';
    init.headers = { 'X-Requested-With': 'pjax', 'Accept': 'text/html' };
    var isPost = (init.method || 'GET').toUpperCase() === 'POST';
    fetch(url, init).then(function (r) {
      if (!/text\/html/i.test(r.headers.get('content-type') || '')) throw { hard: r.url || url };
      return r.text().then(function (t) { return { url: r.url || url, text: t }; });
    }).then(function (res) {
      var doc = new DOMParser().parseFromString(res.text, 'text/html');
      if (!applyDoc(doc, res.url, mode)) throw { hard: res.url };
    }).catch(function (err) {
      leaving(false);
      if (err && err.hard) location.assign(err.hard);
      else if (!isPost) location.assign(url);
      else avatarToast('Koneksi gagal. Coba kirim ulang.', true);
    }).then(function () { pjaxBusy = false; });
  }
  function sameOriginUrl(href) {
    var a = document.createElement('a'); a.href = href;
    return a.origin === location.origin ? a : null;
  }
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || !pjaxOn()) return;
    var a = e.target.closest('a[href]');
    if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download') || a.hasAttribute('data-no-transition') || a.hasAttribute('data-print')) return;
    var href = a.getAttribute('href') || '';
    if (!href || href.charAt(0) === '#' || /^(mailto|tel|javascript):/i.test(href)) return;
    if (a.origin !== location.origin) return;
    if (/\/(export|media|avatar)\b|\.(csv|pdf|mp3|webm)$/i.test(a.pathname)) return;
    if (a.pathname === location.pathname && a.search === location.search && a.hash) return;
    e.preventDefault();
    var same = a.pathname === location.pathname && a.search === location.search;
    pjaxLoad(a.pathname + a.search, {}, same ? 'replace' : 'push');
  });
  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented || !pjaxOn()) return;
    var f = e.target;
    if (!f || f.tagName !== 'FORM' || f.hasAttribute('data-no-pjax') || (f.target && f.target !== '_self')) return;
    var sub = e.submitter;
    var method = ((sub && sub.getAttribute('formmethod')) || f.getAttribute('method') || 'get').toLowerCase();
    var action = (sub && sub.getAttribute('formaction')) || f.getAttribute('action') || location.pathname + location.search;
    var a = sameOriginUrl(action);
    if (!a || method === 'dialog' || /\/(export|media)\b|\.(csv|pdf)$/i.test(a.pathname)) return;
    e.preventDefault();
    var fd = new FormData(f);
    if (sub && sub.name) fd.append(sub.name, sub.value);
    if (method === 'post') {
      pjaxLoad(a.pathname + a.search, { method: 'POST', body: fd }, 'push');
    } else {
      var qs = new URLSearchParams();
      fd.forEach(function (v, k) { if (typeof v === 'string') qs.append(k, v); });
      pjaxLoad(a.pathname + (qs.toString() ? '?' + qs.toString() : ''), {}, 'push');
    }
  });
  window.addEventListener('popstate', function () {
    if (!pjaxUsed) return;
    if (pjaxOn()) pjaxLoad(location.pathname + location.search, {}, 'none'); else location.reload();
  });

  // Dipakai js/alarm.js & js/darurat.js
  window.Rukunin = {
    refresh: function () { if (pjaxOn()) pjaxLoad(location.pathname + location.search, {}, 'replace'); else location.reload(); },
    syncChrome: function () {            // perbarui banner status di panel tanpa mengganggu isian formulir
      fetch(location.pathname + location.search, { credentials: 'same-origin', headers: { 'X-Requested-With': 'pjax' } })
        .then(function (r) { return r.ok ? r.text() : ''; })
        .then(function (t) { if (t) swapPart('.safe-banner', new DOMParser().parseFromString(t, 'text/html')); })
        .catch(function () {});
    }
  };

  setTimeout(function () {
    document.querySelectorAll('.flash.ok').forEach(function (f) {
      f.style.opacity = '0';
      f.style.transition = 'opacity 0.5s ease';
      setTimeout(function () { f.style.display = 'none'; }, 500);
    });
  }, 6000);

  initSidebarIndicator();
  initMenuScrollHint();
  initGlobalSearch();
  initNotifDropdown();
  initWeather();
  syncPanelToggle();
})();
