/* Runs before paint: marks JS as available and reads motion / data preferences. */
(() => {
  const root = document.documentElement;
  const connection = navigator.connection || {};
  root.classList.add('js');
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) root.classList.add('reduce');
  if (connection.saveData || /(^|[^\d])2g/.test(connection.effectiveType || '')) root.classList.add('lite');
})();
