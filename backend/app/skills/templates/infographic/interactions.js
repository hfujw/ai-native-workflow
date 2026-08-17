// 数字滚动（信息图交互基因）——关键数字进入视口时从 0 滚到目标值
(function () {
  if (!('IntersectionObserver' in window)) return;
  var els = document.querySelectorAll('.count-up');
  if (!els.length) return;
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var el = entry.target;
      observer.unobserve(el);
      var target = parseInt(el.getAttribute('data-target') || el.textContent.replace(/[^\d]/g, ''), 10) || 0;
      if (!target) return;
      var duration = 1200;
      var start = null;
      function step(ts) {
        if (!start) start = ts;
        var p = Math.min((ts - start) / duration, 1);
        var eased = 1 - Math.pow(1 - p, 3); // ease-out
        el.textContent = Math.round(target * eased).toLocaleString();
        if (p < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }, { threshold: 0.3 });
  els.forEach(function (el) { observer.observe(el); });
})();
