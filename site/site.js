/* Background loop, growing headline, hero early-access form, toast, reveal-on-scroll and parallax.
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

  /* ---- Growing headline ----
     Each letter is a Fraunces glyph whose weight and SOFT axis follow --b (0 to 1).
     On load the letters sprout in, left to right; afterwards letters near the cursor swell, like leaves turning to the light. */
  const headline = $('[data-grow]');
  if (headline) {
    const text = headline.textContent.replace(/\s+/g, ' ').trim();
    const sr = document.createElement('span');
    sr.className = 'sr-only';
    sr.textContent = text;
    let index = 0;
    const letters = [];
    $$('.hl-line', headline).forEach(line => {
      const words = line.textContent.trim().split(/\s+/);
      const count = line.textContent.replace(/\s+/g, '').length;
      let n = 0;
      line.textContent = '';
      line.setAttribute('aria-hidden', 'true');
      words.forEach((word, wi) => {
        const w = document.createElement('span');
        w.className = 'w';
        for (const c of word) {
          const ch = document.createElement('span');
          ch.className = 'ch';
          ch.textContent = c;
          ch.style.setProperty('--i', index++);
          ch.style.setProperty('--t', (n++ / Math.max(1, count - 1)).toFixed(3));
          w.append(ch);
          letters.push(ch);
        }
        line.append(w);
        if (wi < words.length - 1) line.append(' ');
      });
    });
    headline.prepend(sr);
    if (!reduced.matches) headline.classList.add('grow');

    if (finePointer.matches && !reduced.matches) {
      let raf = 0, x = -1e4, y = -1e4, centres = [];
      const measure = () => { centres = letters.map(ch => { const r = ch.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }); };
      const radius = () => Math.max(140, headline.getBoundingClientRect().height * 0.55);
      const paint = () => {
        raf = 0;
        if (!centres.length) measure();
        const R = radius();
        letters.forEach((ch, k) => {
          const d = Math.hypot(centres[k][0] - x, centres[k][1] - y);
          const b = d >= R ? 0 : Math.pow(1 - d / R, 1.6);
          ch.style.setProperty('--b', b.toFixed(3));
        });
      };
      const queue = () => { if (!raf) raf = requestAnimationFrame(paint); };
      const hero = $('.hero');
      hero.addEventListener('pointermove', e => { x = e.clientX; y = e.clientY; queue(); });
      hero.addEventListener('pointerleave', () => { x = y = -1e4; queue(); });
      addEventListener('scroll', () => { centres = []; }, { passive: true });
      addEventListener('resize', () => { centres = []; });
      // The parallax shifts the block slightly; re-measure once the entrance has finished.
      setTimeout(() => { centres = []; }, 2600);
    }
  }

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
    const bar = $('.line', form), email = $('#hero-email', form), consent = $('[name=consent]', form);
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

  /* ---- Bloom: the sun's glow leans a little towards the cursor ---- */
  if (finePointer.matches && !reduced.matches) {
    let raf = 0;
    addEventListener('pointermove', e => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        root.style.setProperty('--bx', (e.clientX / innerWidth - 0.5).toFixed(3));
        root.style.setProperty('--by', (e.clientY / innerHeight - 0.5).toFixed(3));
      });
    }, { passive: true });
  }

  /* ---- Header backdrop once the page scrolls ---- */
  const nav = $('.nav');
  const onScroll = () => nav && nav.classList.toggle('scrolled', scrollY > 24);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
