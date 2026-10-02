/* Same-origin signup, confirmation, unsubscribe and volunteer applications. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  $('#year').textContent = new Date().getFullYear();
  const openDlg = d => { if (!d.open) d.showModal(); };
  $$('[data-signup]').forEach(b => b.addEventListener('click', () => openDlg($('#signup-dialog'))));
  $$('[data-contribute]').forEach(b => b.addEventListener('click', () => openDlg($('#contribute'))));
  $$('dialog').forEach(d => {
    $$('[data-close]', d).forEach(b => b.addEventListener('click', () => d.close()));
    d.addEventListener('click', e => { if (e.target === d && (e.clientX < d.getBoundingClientRect().left || e.clientX > d.getBoundingClientRect().right || e.clientY < d.getBoundingClientRect().top || e.clientY > d.getBoundingClientRect().bottom)) d.close(); });
  });
  $$('[data-privacy]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); openDlg($('#privacy')); }));
  const sub = $('#early-access'), email = $('#sub-email');
  $$('[data-focus-email], [data-beta]').forEach(a => a.addEventListener('click', e => {
    e.preventDefault();
    if (a.hasAttribute('data-beta')) $('[name=beta]', sub).checked = true;
    openDlg($('#signup-dialog'));
    if (!$('#sub-done').classList.contains('show')) email.focus({ preventScroll: true });
    else $('#sub-done').focus({ preventScroll: true });
  }));
  const roles = $('#ap-role');
  function hint() { $('#role-hint').textContent = roles.selectedOptions[0]?.dataset.hint || ''; }
  roles.addEventListener('change', hint);
  $$('[data-role]').forEach(b => b.addEventListener('click', () => {
    roles.value = b.dataset.role || ''; hint();
    $('#apply-title').textContent = roles.value ? `Join us: ${roles.selectedOptions[0].textContent}` : b.dataset.area ? `Join us: ${b.dataset.area}` : 'Apply to join';
    if ($('#contribute').open) $('#contribute').close();
    openDlg($('#apply'));
    if (!$('#apply-done').classList.contains('show')) $('#ap-name').focus();
  }));
  $$('[data-count-for]').forEach(c => { const input = document.getElementById(c.dataset.countFor); const update = () => c.textContent = `${input.value.length} / ${input.maxLength}`; input.addEventListener('input', update); update(); });
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  // Real-time email validation on dialog fields marked data-live: quiet while typing, clear once valid or on blur.
  $$('input[data-live]').forEach(input => {
    const field = input.closest('.field'), note = document.createElement('p');
    note.className = 'field-msg'; note.id = `${input.id}-msg`; note.setAttribute('aria-live', 'polite');
    field.append(note); input.setAttribute('aria-describedby', note.id);
    const set = (state, text = '') => { field.dataset.state = state; note.textContent = text; input.setAttribute('aria-invalid', String(state === 'invalid')); };
    input.addEventListener('input', () => { const v = input.value.trim(); !v ? set('idle') : emailRe.test(v) ? set('valid', 'Looks good.') : field.dataset.state === 'invalid' ? set('invalid', 'That doesn’t look like an email address yet.') : set('typing'); });
    input.addEventListener('blur', () => { const v = input.value.trim(); if (v && !emailRe.test(v)) set('invalid', 'That doesn’t look like an email address yet.'); });
  });
  async function send(url, data) {
    const ctrl = new AbortController(), timeout = setTimeout(() => ctrl.abort(), 12000);
    try { const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data), signal: ctrl.signal });
      let body = {}; try { body = await res.json(); } catch (_) {}
      return { ok: res.ok, status: res.status, body };
    } finally { clearTimeout(timeout); }
  }
  function wire(form, done, url, collect, onOk, toastText) {
    const message = $('.msg', form), button = $('button[type=submit]', form);
    form.addEventListener('submit', async e => {
      e.preventDefault(); if (button.disabled) return;
      message.textContent = ''; const v = collect(new FormData(form));
      if (v.error) { message.textContent = v.error; v.focus?.focus(); return; }
      const label = button.innerHTML; button.disabled = true; button.innerHTML = '<span>Sending</span><span class="spinner" aria-hidden="true"></span>'; form.setAttribute('aria-busy', 'true');
      try { const r = await send(url, v.data);
        if (r.ok) { form.hidden = true; done.classList.add('show'); onOk?.(v.data); done.focus(); window.dhToast?.(toastText); }
        else message.textContent = r.status === 429 ? 'Too many attempts. Please try again in a few minutes.' : (r.body.error || 'We couldn’t save that. Please try again, or email contact@dopehub.net.');
      } catch (_) { message.textContent = 'We couldn’t reach the server. Check your connection and try again.'; }
      finally { button.disabled = false; button.innerHTML = label; form.removeAttribute('aria-busy'); }
    });
  }
  wire(sub, $('#sub-done'), '/api/subscribe', fd => {
    const address = (fd.get('email') || '').trim(), newsletter = !!fd.get('newsletter'), beta = !!fd.get('beta');
    if (!newsletter && !beta) return { error: 'Choose the newsletter, a beta invitation, or both.', focus: $('[name=newsletter]', sub) };
    if (!emailRe.test(address)) return { error: 'Please enter a valid email address.', focus: email };
    if (!fd.get('consent')) return { error: 'Please confirm you’re 18 or over and agree to your selected emails.', focus: $('[name=consent]', sub) };
    return { data: { email: address, newsletter, beta, consent: true, website: fd.get('website') || '' } };
  }, data => {
    $('#signup-confirm-detail').textContent = data.beta
      ? (data.newsletter ? 'Your newsletter and beta choices stay separate. ' : '') + 'Confirm your beta request to join the waiting list. Your access invitation comes separately when it’s ready.'
      : 'Confirm your newsletter subscription for occasional updates and launch news. You can unsubscribe at any time.';
  }, 'Request received. Confirm from your inbox.');
  wire($('#apply-form'), $('#apply-done'), '/api/apply', fd => {
    const data = Object.fromEntries(fd); for (const k of ['name', 'email', 'link', 'message']) data[k] = (data[k] || '').trim();
    if (!data.name) return { error: 'Please tell us your name.', focus: $('#ap-name') };
    if (!emailRe.test(data.email)) return { error: 'Please enter a valid email address.', focus: $('#ap-email') };
    if (!data.role) return { error: 'Please choose an area of interest.', focus: roles };
    if (!data.availability) return { error: 'Please choose your approximate availability.', focus: $('#ap-time') };
    if (data.link && !/^https:\/\/\S+\.\S+/.test(data.link)) return { error: 'Portfolio links should start with https://', focus: $('#ap-link') };
    if (data.message.length < 20) return { error: 'Please tell us a little more about your experience (at least 20 characters).', focus: $('#ap-msg') };
    if (!data.consent) return { error: 'Please confirm you’re 18 or over and agree to the privacy notice.', focus: $('[name=consent]', $('#apply-form')) };
    data.consent = true; return { data };
  }, data => $('[data-first-name]').textContent = data.name.split(/\s+/)[0], 'Application sent. Thank you.');
  const banner = $('#banner');
  function notice(title, text, error = false) { $('div b', banner).textContent = title; $('div span', banner).textContent = text; banner.classList.toggle('err', error); $('use', banner).setAttribute('href', error ? '#i-alert' : '#i-check'); banner.hidden = false; }
  $('button', banner).addEventListener('click', () => banner.hidden = true);
  const qs = new URLSearchParams(location.search), confirm = qs.get('confirm'), unsubscribe = qs.get('unsubscribe');
  // Keep tokens in the address until the operation succeeds, so a failed connection can be retried.
  const clearToken = () => history.replaceState(null, '', location.pathname + location.hash);
  if (confirm) send('/api/confirm', { token: confirm }).then(r => {
    if (r.ok) { clearToken(); notice('Your preferences are confirmed.', 'Newsletter updates follow your choices. A beta access invitation will arrive separately when it’s ready.'); }
    else notice('That link didn’t work.', r.body.error || 'Please request a new confirmation using the form.', true);
  }).catch(() => notice('We couldn’t confirm just yet.', 'Please check your connection and reload this page to retry.', true));
  if (unsubscribe) {
    const dialog = $('#unsub'), button = $('[data-unsub-yes]', dialog), message = $('.msg', dialog); openDlg(dialog);
    button.addEventListener('click', async () => {
      button.disabled = true; message.textContent = '';
      try { const r = await send('/api/unsubscribe', { token: unsubscribe });
        if (r.ok) { clearToken(); dialog.close(); notice('Your email preferences have been updated.', r.body.message || 'You will no longer receive these emails.'); }
        else message.textContent = r.body.error || 'Please try again, or email contact@dopehub.net.';
      } catch (_) { message.textContent = 'Couldn’t reach the server. Please try again.'; }
      finally { button.disabled = false; }
    });
  }
  try {
    if (!navigator.webdriver && navigator.doNotTrack !== '1' && window.doNotTrack !== '1' && !navigator.globalPrivacyControl) {
      let ref = ''; try { ref = document.referrer ? new URL(document.referrer).hostname : ''; } catch (_) {}
      fetch('/api/hit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ p: location.pathname, r: ref, s: qs.get('utm_source') || '', w: innerWidth }), keepalive: true }).catch(() => {});
    }
  } catch (_) {}
})();
