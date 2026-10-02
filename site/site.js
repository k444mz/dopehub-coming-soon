/* Background loop, hero early-access form, toast, reveal-on-scroll, parallax and frame spotlight.
   The dialogs' forms (beta invite, application, privacy, unsubscribe) live in app.js. */
(() => {
  'use strict';
  const root = document.documentElement;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const wide = matchMedia('(min-width: 768px)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  const videos = $$('video[data-webm]');
  let paused = false;

  /* ---- Background loop: fetched only on wide screens, with motion allowed and no data-saver ---- */
  const canPlay = () => wide.matches && !reduced.matches && !root.classList.contains('lite');
  function attach(video) {
    if (video.dataset.ready || !canPlay()) return;
    video.dataset.ready = '1';
    for (const [type, key] of [['video/webm', 'webm'], ['video/mp4', 'mp4']]) {
      const source = document.createElement('source');
      source.src = video.dataset[key];
      source.type = type;
      video.append(source);
    }
    video.addEventListener('playing', () => video.classList.add('is-playing'), { once: true });
    video.load();
    if (!paused) video.play().catch(() => {});
  }
  const toggle = $('[data-motion-toggle]');
  function setPaused(next) {
    paused = next;
    root.classList.toggle('is-paused', paused);
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(paused));
      $('[data-label]', toggle).textContent = paused ? 'Play motion' : 'Pause motion';
    }
    videos.forEach(v => { if (v.dataset.ready) paused ? v.pause() : v.play().catch(() => {}); });
  }
  if (toggle) toggle.addEventListener('click', () => setPaused(!paused));
  const syncAvailability = () => {
    if (toggle) toggle.hidden = !canPlay();
    videos.forEach(v => { attach(v); if (v.dataset.ready && !canPlay()) v.pause(); });
  };
  wide.addEventListener('change', syncAvailability);
  reduced.addEventListener('change', syncAvailability);
  syncAvailability();
  document.addEventListener('visibilitychange', () => {
    videos.forEach(v => { if (!v.dataset.ready) return; document.hidden || paused || !canPlay() ? v.pause() : v.play().catch(() => {}); });
  });

  /* ---- Toast (shared with app.js through window.dhToast) ---- */
  const toast = $('#toast');
  let toastTimer = 0;
  window.dhToast = text => {
    if (!toast) return;
    $('[data-toast-text]', toast).textContent = text;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 4200);
  };

  /* ---- Hero early-access form: real-time validation, posts to /api/subscribe as a newsletter sign-up ---- */
  const form = $('#subscribe');
  if (form) {
    const bar = $('.bar', form), email = $('#hero-email', form), consent = $('[name=consent]', form);
    const validation = $('.validation', form), button = $('button[type=submit]', form), done = $('#hero-done');
    const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    let touched = false;
    const state = (name, text = '', ok = false) => {
      bar.dataset.state = name;
      validation.textContent = text;
      validation.classList.toggle('ok', ok);
      email.setAttribute('aria-invalid', String(name === 'invalid'));
      if (name === 'invalid') { bar.classList.remove('shake'); void bar.offsetWidth; bar.classList.add('shake'); }
    };
    email.addEventListener('input', () => {
      const v = email.value.trim();
      if (!v) return state('idle');
      if (emailRe.test(v)) state('valid', 'Looks good.', true);
      else if (touched) state('typing', 'Keep going: an address looks like name@example.com.');
      else state('typing');
    });
    email.addEventListener('blur', () => {
      const v = email.value.trim();
      if (v) touched = true;
      if (v && !emailRe.test(v)) state('invalid', 'That doesn’t look like an email address yet.');
    });
    consent.addEventListener('change', () => {
      $('.check', form).classList.remove('attention');
      if (consent.checked && bar.dataset.state === 'invalid' && emailRe.test(email.value.trim())) state('valid', 'Looks good.', true);
    });
    $$('[data-focus-hero]').forEach(a => a.addEventListener('click', e => {
      e.preventDefault();
      form.scrollIntoView({ behavior: reduced.matches ? 'instant' : 'smooth', block: 'center' });
      (form.classList.contains('is-done') ? done : email).focus({ preventScroll: true });
    }));
    form.addEventListener('submit', async e => {
      e.preventDefault();
      if (button.disabled) return;
      const address = email.value.trim();
      touched = true;
      if (!emailRe.test(address)) { state('invalid', address ? 'Please enter a valid email address.' : 'Enter your email address to get early access.'); email.focus(); return; }
      if (!consent.checked) { state('invalid', 'Please confirm you’re 18 or over and happy to receive launch emails.'); $('.check', form).classList.add('attention'); consent.focus(); return; }
      const label = button.innerHTML;
      button.disabled = true;
      button.innerHTML = '<span>Sending</span><span class="spinner" aria-hidden="true"></span>';
      form.setAttribute('aria-busy', 'true');
      const ctrl = new AbortController(), timeout = setTimeout(() => ctrl.abort(), 12000);
      try {
        const res = await fetch('/api/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal,
          body: JSON.stringify({ email: address, newsletter: true, beta: false, consent: true, website: $('[name=website]', form).value || '' }) });
        let body = {}; try { body = await res.json(); } catch (_) {}
        if (res.ok) {
          $('[data-hero-address]', done).textContent = address;
          form.classList.add('is-done');
          done.focus();
          window.dhToast('You’re nearly in. Confirm from your inbox.');
        } else state('invalid', res.status === 429 ? 'Too many attempts. Please try again in a few minutes.' : (body.error || 'We couldn’t save that. Please try again, or email contact@dopehub.net.'));
      } catch (_) { state('invalid', 'We couldn’t reach the server. Check your connection and try again.'); }
      finally { clearTimeout(timeout); button.disabled = false; button.innerHTML = label; form.removeAttribute('aria-busy'); }
    });
  }

  /* ---- Reveal on scroll ---- */
  // Everything is visible at rest; only elements below the fold at load are hidden until they scroll in.
  const reveals = $$('.reveal');
  if ('IntersectionObserver' in window && !reduced.matches) {
    const show = el => { el.classList.add('in'); el.classList.remove('pending'); };
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) { show(e.target); io.unobserve(e.target); } });
    }, { threshold: 0.15 });
    reveals.forEach(el => { if (el.getBoundingClientRect().top > innerHeight) { el.classList.add('pending'); io.observe(el); } });
    setTimeout(() => reveals.forEach(show), 6000);
  }

  /* ---- Mouse parallax (guide 2): the foreground drifts 5 to 10 px against the cursor ---- */
  const hero = $('.hero');
  if (hero && finePointer.matches && !reduced.matches) {
    let frame = 0;
    hero.addEventListener('pointermove', e => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const r = hero.getBoundingClientRect();
        hero.style.setProperty('--px', ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
        hero.style.setProperty('--py', ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
      });
    });
    hero.addEventListener('pointerleave', () => { hero.style.setProperty('--px', 0); hero.style.setProperty('--py', 0); });
  }

  /* ---- Frame spotlight: a soft warm highlight follows the cursor across framed glass ---- */
  if (finePointer.matches) {
    $$('.frame').forEach(el => el.addEventListener('pointermove', e => {
      const r = el.getBoundingClientRect();
      el.style.setProperty('--mx', `${e.clientX - r.left}px`);
      el.style.setProperty('--my', `${e.clientY - r.top}px`);
    }));
  }

  /* ---- Header backdrop once the page scrolls ---- */
  const nav = $('.nav');
  const onScroll = () => nav && nav.classList.toggle('scrolled', scrollY > 24);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
