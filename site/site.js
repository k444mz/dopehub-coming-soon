/* Background loops, reveal-on-scroll and subtle parallax. Forms live in app.js. */
(() => {
  'use strict';
  const root = document.documentElement;
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const wide = matchMedia('(min-width: 768px)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const videos = $$('video[data-webm]');
  let paused = false;

  // Video is only fetched on wide screens, with motion allowed and no data-saver.
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
  }

  const watcher = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    for (const { target, isIntersecting } of entries) {
      if (isIntersecting) { attach(target); if (!paused && target.dataset.ready) target.play().catch(() => {}); }
      else target.pause();
    }
  }, { rootMargin: '200px 0px' }) : null;

  videos.forEach(video => {
    if (video.dataset.eager) attach(video);
    watcher ? watcher.observe(video) : attach(video);
  });

  const toggle = document.querySelector('[data-motion-toggle]');
  function setPaused(next) {
    paused = next;
    root.classList.toggle('is-paused', paused);
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(paused));
      toggle.querySelector('[data-label]').textContent = paused ? 'Play motion' : 'Pause motion';
    }
    videos.forEach(v => { if (v.dataset.ready) paused ? v.pause() : v.play().catch(() => {}); });
  }
  if (toggle) toggle.addEventListener('click', () => setPaused(!paused));
  const syncAvailability = () => {
    if (toggle) toggle.hidden = !canPlay();
    videos.forEach(v => attach(v));
  };
  wide.addEventListener('change', syncAvailability);
  reduced.addEventListener('change', syncAvailability);
  syncAvailability();
  document.addEventListener('visibilitychange', () => {
    videos.forEach(v => { if (!v.dataset.ready) return; document.hidden || paused ? v.pause() : v.play().catch(() => {}); });
  });

  // Reveal on scroll.
  const reveals = $$('.reveal');
  if ('IntersectionObserver' in window && !reduced.matches) {
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { threshold: 0.15 });
    reveals.forEach(el => io.observe(el));
  } else reveals.forEach(el => el.classList.add('in'));

  // Mouse parallax: foreground type drifts a few pixels against the cursor.
  const hero = document.querySelector('.hero');
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

  // Header gains a backdrop once the page scrolls.
  const nav = document.querySelector('.nav');
  const onScroll = () => nav && nav.classList.toggle('scrolled', scrollY > 24);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
