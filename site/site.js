/* Background loop, countdown, hero subscribe bar, reveal-on-scroll and parallax.
   The dialogs' forms (beta invite, application, privacy, unsubscribe) live in app.js. */
(() => {
  'use strict';
  const root = document.documentElement;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const wide = matchMedia('(min-width: 768px)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
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
    video.play().catch(() => {});
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
  const syncAvailability = () => { if (toggle) toggle.hidden = !canPlay(); videos.forEach(attach); };
  wide.addEventListener('change', syncAvailability);
  reduced.addEventListener('change', syncAvailability);
  syncAvailability();
  document.addEventListener('visibilitychange', () => {
    videos.forEach(v => { if (!v.dataset.ready) return; document.hidden || paused ? v.pause() : v.play().catch(() => {}); });
  });

  /* ---- Countdown ---- */
  const countdown = $('.countdown');
  if (countdown) {
    const launch = Date.parse(countdown.dataset.launch);
    const parts = { days: $('[data-days]', countdown), hours: $('[data-hours]', countdown), mins: $('[data-mins]', countdown), secs: $('[data-secs]', countdown) };
    const pad = n => String(n).padStart(2, '0');
    const tick = () => {
      let left = Math.max(0, launch - Date.now());
      const days = Math.floor(left / 864e5); left -= days * 864e5;
      const hours = Math.floor(left / 36e5); left -= hours * 36e5;
      const mins = Math.floor(left / 6e4); left -= mins * 6e4;
      parts.days.textContent = pad(days); parts.hours.textContent = pad(hours);
      parts.mins.textContent = pad(mins); parts.secs.textContent = pad(Math.floor(left / 1e3));
      countdown.classList.toggle('is-live', launch <= Date.now());
    };
    if (Number.isFinite(launch)) { tick(); setInterval(tick, 1000); }
    else countdown.hidden = true;
  }

  /* ---- Hero subscribe bar: instant validation, posts to the same /api/subscribe as the dialog ---- */
  const form = $('#subscribe');
  if (form) {
    const bar = $('.bar', form), email = $('#hero-email', form), consent = $('[name=consent]', form);
    const validation = $('.validation', form), button = $('button[type=submit]', form), done = $('#hero-done');
    const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    const state = (name, text = '', ok = false) => { bar.dataset.state = name; validation.textContent = text; validation.classList.toggle('ok', ok); };
    email.addEventListener('input', () => {
      const v = email.value.trim();
      if (!v) return state('idle');
      emailRe.test(v) ? state('valid', 'Looks good.', true) : state('typing');
    });
    email.addEventListener('blur', () => {
      const v = email.value.trim();
      if (v && !emailRe.test(v)) state('invalid', 'That doesn’t look like an email address.');
    });
    form.addEventListener('submit', async e => {
      e.preventDefault();
      if (button.disabled) return;
      const address = email.value.trim();
      if (!emailRe.test(address)) { state('invalid', 'Please enter a valid email address.'); email.focus(); return; }
      if (!consent.checked) { state('invalid', 'Please confirm you’re 18 or over and happy to receive launch emails.'); consent.focus(); return; }
      const label = button.innerHTML;
      button.disabled = true; button.textContent = 'Sending…'; form.setAttribute('aria-busy', 'true');
      try {
        const ctrl = new AbortController(), timeout = setTimeout(() => ctrl.abort(), 12000);
        const res = await fetch('/api/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal,
          body: JSON.stringify({ email: address, newsletter: true, beta: false, consent: true, website: $('[name=website]', form).value || '' }) });
        clearTimeout(timeout);
        let body = {}; try { body = await res.json(); } catch (_) {}
        if (res.ok) { form.classList.add('is-done'); done.classList.add('show'); done.focus(); }
        else state('invalid', res.status === 429 ? 'Too many attempts. Please try again in a few minutes.' : (body.error || 'We couldn’t save that. Please try again, or email contact@dopehub.net.'));
      } catch (_) { state('invalid', 'We couldn’t reach the server. Check your connection and try again.'); }
      finally { button.disabled = false; button.innerHTML = label; form.removeAttribute('aria-busy'); }
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
    setTimeout(() => reveals.forEach(show), 5000);
  }

  /* ---- Mouse parallax: the foreground drifts a few pixels against the cursor ---- */
  const hero = $('.hero');
  if (hero && matchMedia('(hover: hover) and (pointer: fine)').matches && !reduced.matches) {
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
  }

  /* ---- Header backdrop once the page scrolls ---- */
  const nav = $('.nav');
  const onScroll = () => nav && nav.classList.toggle('scrolled', scrollY > 24);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
