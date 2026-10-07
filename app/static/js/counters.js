function formatAmountShort(n) {
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs >= 1000000) {
    const s = Math.floor((abs / 1000000) * 1000) / 1000;
    return sign + s + 'M';
  }
  return sign + Math.round(abs).toLocaleString();
}

document.querySelectorAll('.counter-value').forEach(el => {
  const target = parseFloat(el.dataset.target) || 0;
  const duration = 900;
  const start = performance.now();
  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = formatAmountShort(target * eased);
    if (progress < 1) requestAnimationFrame(tick);
    else el.textContent = formatAmountShort(target);
  }
  requestAnimationFrame(tick);
});
