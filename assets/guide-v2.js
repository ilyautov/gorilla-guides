// guide-v2: кнопка «Копировать» у блоков .command и раскрытие <details> по якорю.
// Без хранения состояния: ничего не пишет в localStorage и никуда не отправляет.
(function () {
  document.documentElement.classList.add('js');

  function selectText(node) {
    var range = document.createRange();
    range.selectNodeContents(node);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  document.querySelectorAll('.command').forEach(function (box) {
    var button = box.querySelector('.command-bar button');
    var pre = box.querySelector('pre');
    var feedback = box.querySelector('.copy-feedback');
    if (!button || !pre) return;
    button.addEventListener('click', function () {
      var text = pre.innerText.replace(/\n$/, '');
      var done = function () {
        button.textContent = 'Скопировано';
        if (feedback) feedback.textContent = '';
        setTimeout(function () { button.textContent = 'Копировать'; }, 1800);
      };
      var fallback = function () {
        selectText(pre);
        if (feedback) feedback.textContent = 'Текст выделен. Нажмите Ctrl+C или ⌘C.';
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
    });
  });

  // Якорь на <details> или на элемент внутри него: раскрыть всю цепочку.
  function openHashTarget() {
    if (!location.hash) return;
    var target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (e) { return; }
    if (!target) return;
    var node = target;
    while (node) {
      if (node.tagName === 'DETAILS') node.open = true;
      node = node.parentElement;
    }
    target.scrollIntoView();
  }
  window.addEventListener('hashchange', openHashTarget);
  // Повторный клик по той же ссылке не меняет hash, поэтому слушаем и клики.
  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[href^="#"]');
    if (link && link.getAttribute('href') === location.hash) setTimeout(openHashTarget, 0);
  });
  openHashTarget();
})();

// Команды не переносим: перенос на дефисе («--min-» / «size») сбивает тех, кто набирает руками.
document.querySelectorAll('.command').forEach(function (block) {
  var label = block.querySelector('.command-bar > span');
  if (label && /терминал|powershell|settings\.json|cmd/i.test(label.textContent)) block.classList.add('is-shell');
});
