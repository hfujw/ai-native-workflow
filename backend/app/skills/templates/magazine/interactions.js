// 阅读进度条（杂志长图交互基因）——滚动时顶部显示"已读 %"
(function () {
  if (document.getElementById('lumen-progress')) return;
  var bar = document.createElement('div');
  bar.id = 'lumen-progress';
  bar.style.cssText = 'position:fixed;top:0;left:0;height:3px;background:#b03a2e;z-index:9999;width:0%;transition:width .15s;pointer-events:none';
  document.body.appendChild(bar);
  var ticking = false;
  function update() {
    var max = document.body.scrollHeight - window.innerHeight;
    var pct = max > 0 ? (window.scrollY / max) * 100 : 0;
    bar.style.width = Math.min(pct, 100) + '%';
    ticking = false;
  }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  update();
})();
