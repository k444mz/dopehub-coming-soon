/* Background loop, countdown, the two email capture forms (updates + beta), reveal-on-scroll,
   glass tilt / spotlight, magnetic buttons, parallax, scroll progress and nav highlighting.
   Dialogs, the team application, confirmation and unsubscribe links live in app.js. */
(() => {
  'use strict';
  const root = document.documentElement;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const wide = matchMedia('(min-width: 768px)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  const bg = $('.bg');
  const videos = $$('video[data-webm]');
  let paused = false, stageVisible = true;

  /* ---- Background loop: fetched only on wide screens, with motion allowed and no data-saver ---- */
  const canPlay = () => wide.matches && !reduced.matches && !root.classList.contains('lite');
  const shouldRun = () => !paused && !document.hidden && stageVisible;
  const run = v => { if (!v.dataset.ready) return; shouldRun() ? v.play().catch(() => {}) : v.pause(); };
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
    run(video);
  }
  const toggle = $('[data-motion-toggle]');
  function setPaused(next) {
    paused = next;
    root.classList.toggle('is-paused', paused);
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(paused));
      $('[data-label]', toggle).textContent = paused ? 'Play motion' : 'Pause motion';
      $('use', toggle).setAttribute('href', paused ? '#i-play' : '#i-pause');
    }
    videos.forEach(run);
  }
  if (toggle) toggle.addEventListener('click', () => setPaused(!paused));
  const syncAvailability = () => { if (toggle) toggle.hidden = !canPlay(); videos.forEach(attach); };
  wide.addEventListener('change', syncAvailability);
  reduced.addEventListener('change', syncAvailability);
  syncAvailability();
  document.addEventListener('visibilitychange', () => videos.forEach(run));

  // The loop sits behind the hero and the subscribe section only. Once both have scrolled away,
  // hide the fixed layer and stop decoding so the rest of the page scrolls on a quiet GPU.
  const stage = $('.stage');
  if (stage && 'IntersectionObserver' in window) {
    new IntersectionObserver(([entry]) => {
      stageVisible = entry.isIntersecting;
      if (bg) bg.classList.toggle('is-off', !stageVisible);
      videos.forEach(run);
    }).observe(stage);
  }

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

  /* ---- Email capture: updates (newsletter) and beta invitation, both post to /api/subscribe ---- */
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  function capture(form) {
    const box = form.parentElement;
    const kind = form.dataset.capture;
    const bar = $('.field-bar', form), email = $('[type=email]', form), consent = $('[name=consent]', form);
    const validation = $('.validation', form), button = $('[type=submit]', form), done = $('.done', box);
    const steps = $$('.steps li', box);
    const state = (name, text = '', ok = false) => {
      bar.dataset.state = name; validation.textContent = text; validation.classList.toggle('ok', ok);
      email.setAttribute('aria-invalid', String(name === 'invalid'));
    };
    const markStep = valid => { if (steps[0]) steps[0].classList.toggle('is-complete', valid); };
    email.addEventListener('input', () => {
      const v = email.value.trim();
      markStep(emailRe.test(v));
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
      if (!consent.checked) {
        state('invalid', kind === 'beta' ? 'Please confirm you’re 18 or over and agree to emails for your choices.' : 'Please confirm you’re 18 or over and happy to receive launch emails.');
        consent.focus(); return;
      }
      const newsletter = kind === 'beta' ? !!$('[name=newsletter]', form)?.checked : true;
      const payload = { email: address, newsletter, beta: kind === 'beta', consent: true, website: $('[name=website]', form).value || '' };
      button.disabled = true; button.classList.add('is-loading'); form.setAttribute('aria-busy', 'true');
      try {
        const ctrl = new AbortController(), timeout = setTimeout(() => ctrl.abort(), 12000);
        const res = await fetch('/api/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal, body: JSON.stringify(payload) });
        clearTimeout(timeout);
        let body = {}; try { body = await res.json(); } catch (_) {}
        if (res.ok) {
          if (kind === 'beta') {
            box.dataset.step = '2';
            const detail = $('[data-beta-detail]', box);
            if (detail && newsletter) detail.textContent = 'Confirm using the link in your email. Your newsletter and beta choices stay separate, and your invitation comes when access is ready.';
          }
          box.classList.add('is-done'); done.classList.add('show'); done.focus();
        } else {
          state('invalid', res.status === 429 ? 'Too many attempts. Please try again in a few minutes.' : (body.error || 'We couldn’t save that. Please try again, or email contact@dopehub.net.'));
        }
      } catch (_) { state('invalid', 'We couldn’t reach the server. Check your connection and try again.'); }
      finally { button.disabled = false; button.classList.remove('is-loading'); form.removeAttribute('aria-busy'); }
    });
  }
  $$('form[data-capture]').forEach(capture);

  /* ---- Reveal on scroll ---- */
  // Everything is visible at rest; only elements below the fold at load are hidden until they scroll in.
  const reveals = $$('.reveal');
  if ('IntersectionObserver' in window && !reduced.matches) {
    const show = el => { el.classList.add('in'); el.classList.remove('pending'); setTimeout(() => el.classList.add('settled'), 1400); };
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) { show(e.target); io.unobserve(e.target); } });
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
    reveals.forEach(el => { if (el.getBoundingClientRect().top > innerHeight) { el.classList.add('pending'); io.observe(el); } });
    setTimeout(() => reveals.forEach(show), 6000);
  }

  /* ---- Glass borders only animate while on screen ---- */
  const luxes = $$('.lux');
  if ('IntersectionObserver' in window) {
    const live = new IntersectionObserver(entries => entries.forEach(e => e.target.classList.toggle('live', e.isIntersecting)));
    luxes.forEach(el => live.observe(el));
  } else luxes.forEach(el => el.classList.add('live'));

  const motionOK = () => finePointer.matches && !reduced.matches;

  /* ---- Tilt + spotlight: eased towards the cursor every frame, so the card glides rather than snaps ---- */
  function tilt(el) {
    const max = parseFloat(el.dataset.tilt) || 4;
    const calm = el.hasAttribute('data-calm');
    let rx = 0, ry = 0, tx = 0, ty = 0, frame = 0;
    const step = () => {
      rx += (tx - rx) * 0.1; ry += (ty - ry) * 0.1;
      el.style.setProperty('--rx', rx.toFixed(3) + 'deg');
      el.style.setProperty('--ry', ry.toFixed(3) + 'deg');
      frame = Math.abs(tx - rx) + Math.abs(ty - ry) > 0.01 ? requestAnimationFrame(step) : 0;
    };
    const kick = () => { if (!frame) frame = requestAnimationFrame(step); };
    el.addEventListener('pointermove', e => {
      if (e.pointerType !== 'mouse' || !motionOK()) return;
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      el.style.setProperty('--mx', (x * 100).toFixed(1) + '%');
      el.style.setProperty('--my', (y * 100).toFixed(1) + '%');
      // Hold still while someone is typing in a form inside the card
      const still = calm && el.contains(document.activeElement) && document.activeElement.matches('input, textarea, select');
      tx = still ? 0 : -(y - 0.5) * 2 * max;
      ty = still ? 0 : (x - 0.5) * 2 * max;
      kick();
    });
    el.addEventListener('pointerleave', () => { tx = 0; ty = 0; kick(); });
    el.addEventListener('focusin', () => { if (calm) { tx = 0; ty = 0; kick(); } });
  }
  $$('[data-tilt]').forEach(tilt);

  /* ---- Magnetic buttons: drift a few pixels towards the cursor ---- */
  $$('[data-magnetic]').forEach(btn => {
    btn.addEventListener('pointermove', e => {
      if (e.pointerType !== 'mouse' || !motionOK()) return;
      const r = btn.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
      btn.style.setProperty('--mgx', Math.max(-8, Math.min(8, dx * 0.18)).toFixed(1) + 'px');
      btn.style.setProperty('--mgy', Math.max(-6, Math.min(6, dy * 0.3)).toFixed(1) + 'px');
    });
    btn.addEventListener('pointerleave', () => { btn.style.setProperty('--mgx', '0px'); btn.style.setProperty('--mgy', '0px'); });
  });

  /* ---- Mouse parallax: the hero type drifts a few pixels against the cursor ---- */
  const hero = $('.hero');
  if (hero) {
    let frame = 0;
    hero.addEventListener('pointermove', e => {
      if (frame || e.pointerType !== 'mouse' || !motionOK()) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const r = hero.getBoundingClientRect();
        hero.style.setProperty('--px', ((e.clientX - r.left) / r.width - 0.5).toFixed(3));
        hero.style.setProperty('--py', ((e.clientY - r.top) / r.height - 0.5).toFixed(3));
      });
    });
  }

  /* ---- Scroll: header backdrop, progress bar, hero fade and background dim ---- */
  const nav = $('.nav');
  let ticking = false;
  const onScroll = () => {
    ticking = false;
    const y = scrollY, max = document.documentElement.scrollHeight - innerHeight;
    if (nav) nav.classList.toggle('scrolled', y > 24);
    root.style.setProperty('--progress', max > 0 ? (y / max).toFixed(4) : '0');
    if (!reduced.matches) root.style.setProperty('--sp', Math.min(1, y / innerHeight).toFixed(3));
  };
  addEventListener('scroll', () => { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  addEventListener('resize', onScroll, { passive: true });
  onScroll();

  /* ---- Highlight the nav link for the section in view ---- */
  const links = $$('.nav-link[href^="#"]');
  if (links.length && 'IntersectionObserver' in window) {
    const byId = new Map(links.map(a => [a.getAttribute('href').slice(1), a]));
    const spy = new IntersectionObserver(entries => entries.forEach(e => {
      const link = byId.get(e.target.id);
      if (link && e.isIntersecting) links.forEach(a => { a.classList.toggle('is-active', a === link); a === link ? a.setAttribute('aria-current', 'true') : a.removeAttribute('aria-current'); });
      else if (link && !e.isIntersecting && link.classList.contains('is-active')) { link.classList.remove('is-active'); link.removeAttribute('aria-current'); }
    }), { rootMargin: '-45% 0px -50% 0px' });
    byId.forEach((_, id) => { const s = document.getElementById(id); if (s) spy.observe(s); });
  }
})();
