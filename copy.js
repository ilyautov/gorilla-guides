document.querySelectorAll('.code').forEach(function(box){
  var b=document.createElement('button');b.className='copy';b.type='button';b.textContent='Копировать';
  b.addEventListener('click',function(){
    var t=box.querySelector('pre').innerText;
    var ok=function(){b.textContent='Скопировано';setTimeout(function(){b.textContent='Копировать'},1500)};
    var sel=function(){var r=document.createRange();r.selectNodeContents(box.querySelector('pre'));var s=getSelection();s.removeAllRanges();s.addRange(r)};
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,sel)}else{sel()}
  });
  box.appendChild(b);
});
