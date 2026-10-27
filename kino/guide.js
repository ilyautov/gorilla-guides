import { GOALS, AGENTS, normaliseProject, recommendedTools, makeBrief, makeTask } from './guide-state.mjs';
const KEY='goro.kino.guide.v1';const $=id=>document.getElementById(id);
let state=normaliseProject();let storage=true;let dirty=false;
try{state=normaliseProject(JSON.parse(localStorage.getItem(KEY)||'{}'));}catch{storage=false;}
function save(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch{storage=false;}if(!storage)$('storage-note').textContent='Браузер не сохраняет данные. Скопируйте задание и свои отметки перед закрытием страницы.';}
const fields=['goal','format','agent','os','duration','purpose','topic'];
for(const id of fields)$(id).value=String(state[id]);
function render(){
 const g=GOALS[state.goal];$('route-name').textContent=g.title;$('route-note').textContent=g.note;$('route-tools').textContent=recommendedTools(state).join(' + ');
 $('license-note').textContent=state.purpose==='commercial'?'Для рекламы и заказов: исходная запись вместо NC-клонов голоса, Depth Anything Small, отдельная проверка лицензии LTX и карты.':'Личный эксперимент: код инструментов открыт, услуги агента и облака могут стоить денег. У моделей и материалов свои условия.';
 $('agent-note').textContent=state.agent==='new'?'Можно начать без AI: скачайте учебный проект в шаге 2. Чтобы делать собственные сцены запросами, есть приложение HyperFrames и агенты с доступом к папке.':state.agent==='chat'?'Обычный чат сам по себе не имеет доступа к папке и терминалу. Для локального маршрута нужен агент с такими возможностями; у HyperFrames также есть отдельное подключение к AI-чату.':`Откройте папку проекта в ${AGENTS[state.agent]}. Команды относятся к терминалу, задания — к чату агента.`;
 const third=state.duration/3;$('timeline-middle').textContent=`${third} с`;$('timeline-last').textContent=`${third*2} с`;$('timeline-end').textContent=`${state.duration} с`;
 let ready=false;try{$('project-brief').textContent=makeBrief(state);ready=!dirty;}catch{$('project-brief').textContent='Укажите тему выше или нажмите «Попробовать на примере». Готовое задание появится здесь.';}
 document.querySelectorAll('[data-copy="project-brief"]').forEach(b=>b.disabled=!ready);
 document.querySelectorAll('[data-copy^="task-"]').forEach(b=>b.disabled=dirty);
 for(const phase of ['prepare','build','fix','finish'])$(`task-${phase}`).textContent=makeTask(phase,state);
 $('brief-state').textContent=dirty?'Параметры изменены. Нажмите «Составить задание», чтобы применить их.':state.topic.length>=3?'Задание составлено. Сайт его никуда не отправляет и видео не генерирует.':'Выберите задачу и напишите тему. Для первого опыта подойдёт готовый пример.';
 document.querySelectorAll('[data-os]').forEach(n=>{n.hidden=state.os!=='unknown'&&n.dataset.os!==state.os;});
 document.querySelectorAll('[data-complete]').forEach(n=>{n.checked=state.completed.includes(n.dataset.complete);});
 $('progress').value=state.completed.length;$('progress-label').textContent=`Отмечено вами: ${state.completed.length} из 6`;
}
function apply(){const values=Object.fromEntries(fields.map(id=>[id,$(id).value]));const next=normaliseProject({...values,completed:state.completed});if(fields.some(id=>next[id]!==state[id]))next.completed=[];state=next;dirty=false;save();render();}
$('project-form').addEventListener('submit',event=>{event.preventDefault();if($('topic').value.trim().length<3){$('topic').setAttribute('aria-invalid','true');$('brief-state').textContent='Напишите тему хотя бы в трёх символах или возьмите готовый пример.';$('topic').focus();return;}$('topic').removeAttribute('aria-invalid');apply();});
for(const id of fields)$(id).addEventListener('input',()=>{dirty=true;$('topic').removeAttribute('aria-invalid');render();});
$('fill-example').addEventListener('click',()=>{Object.entries({goal:'text',format:'vertical',duration:15,purpose:'personal',topic:'Почему уверенный ответ нейросети нужно проверять'}).forEach(([id,value])=>$(id).value=String(value));$('topic').removeAttribute('aria-invalid');apply();});
for(const n of document.querySelectorAll('[data-complete]'))n.addEventListener('change',()=>{state.completed=[...document.querySelectorAll('[data-complete]:checked')].map(n=>n.dataset.complete);save();render();});
$('clear-checks').addEventListener('click',()=>{state.completed=[];save();render();});
for(const button of document.querySelectorAll('[data-copy]'))button.addEventListener('click',async()=>{
 if(button.disabled)return;const source=$(button.dataset.copy);const feedback=button.closest('.command').querySelector('.copy-feedback');
 try{if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');await navigator.clipboard.writeText(source.textContent);button.textContent='Скопировано';feedback.textContent='Вставьте в окно, указанное над блоком.';}
 catch{const range=document.createRange();range.selectNodeContents(source);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);feedback.textContent='Текст выделен. Нажмите Ctrl+C или ⌘C.';}
 setTimeout(()=>{button.textContent='Копировать';},1800);
});
render();if(!storage)save();
