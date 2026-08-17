// 点击翻转卡片（问答模式交互基因）——正面问题，点击翻面看答案
(function () {
  var cards = document.querySelectorAll('.flip-card');
  if (!cards.length) return;
  cards.forEach(function (card) {
    card.style.cursor = 'pointer';
    card.style.position = 'relative';
    card.style.perspective = '600px';
    var inner = card.querySelector('.flip-inner') || card.firstElementChild;
    if (inner && inner !== card) {
      inner.style.transition = 'transform .4s';
      inner.style.transformStyle = 'preserve-3d';
      card.style.minHeight = inner.offsetHeight + 'px';
    }
    card.addEventListener('click', function () {
      card.classList.toggle('flipped');
      if (inner) inner.style.transform = card.classList.contains('flipped') ? 'rotateY(180deg)' : '';
    });
  });
})();
