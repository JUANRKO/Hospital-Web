/* ── MENÚ 3 PUNTOS ──────────────────────────── */
(function initMoreMenu() {
  const btn      = document.getElementById('moreBtn');
  const dropdown = document.getElementById('moreDropdown');

  if (!btn || !dropdown) return;

  /* Abrir / cerrar al hacer clic en el botón */
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    const isOpen = dropdown.classList.contains('open');

    closeDropdown();          // cierra cualquier otro

    if (!isOpen) {
      dropdown.classList.add('open');
      btn.classList.add('active');
    }
  });

  /* Cerrar al hacer clic fuera */
  document.addEventListener('click', function (e) {
    if (!btn.contains(e.target) && !dropdown.contains(e.target)) {
      closeDropdown();
    }
  });

  /* Cerrar con ESC */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeDropdown();
  });

  function closeDropdown() {
    dropdown.classList.remove('open');
    btn.classList.remove('active');
  }
})();


/* ── HEADER — efecto scroll ─────────────────── */
(function initHeaderScroll() {
  const header = document.getElementById('main-header');
  if (!header) return;

  window.addEventListener('scroll', function () {
    if (window.scrollY > 60) {
      header.style.background = 'rgba(10,31,68,1)';
      header.style.boxShadow  = '0 2px 20px rgba(0,0,0,0.25)';
    } else {
      header.style.background = 'rgba(10,31,68,0.97)';
      header.style.boxShadow  = 'none';
    }
  }, { passive: true });
})();


/* ── SMOOTH SCROLL para anclas internas ─────── */
(function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
    anchor.addEventListener('click', function (e) {
      const target = document.querySelector(this.getAttribute('href'));
      if (!target) return;
      e.preventDefault();
      const headerH = document.getElementById('main-header')?.offsetHeight || 68;
      const top = target.getBoundingClientRect().top + window.scrollY - headerH - 10;
      window.scrollTo({ top: top, behavior: 'smooth' });
    });
  });
})();


/* ── RUTAS DE NAVEGACIÓN ────────────────────── */
function irLogin() {
  window.location.href = 'pages/login.html';
}

function irFicha() {
    window.location.href = "pages/opcion.html";
}

function irMedico() {
  window.location.href = 'pages/login.html?rol=medico';
}


/* ── ANIMACIÓN DE APARICIÓN (Intersection Observer) ── */
(function initFadeIn() {
  const observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.style.opacity    = '1';
          entry.target.style.transform  = 'translateY(0)';
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12 }
  );

  /* Aplicar a tarjetas de especialidades y bloques de misión */
  const targets = document.querySelectorAll('.spec-card, .mv-block, .contact-item');
  targets.forEach(function (el, i) {
    el.style.opacity    = '0';
    el.style.transform  = 'translateY(22px)';
    el.style.transition = 'opacity 0.45s ' + (i * 0.07) + 's, transform 0.45s ' + (i * 0.07) + 's';
    observer.observe(el);
  });
})();
