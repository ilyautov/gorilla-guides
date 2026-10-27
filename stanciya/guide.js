import { MODELS, OS_NAMES, firmwareFor, isIPv4, isLanIPv4, connectCommand, dnsCommand, normaliseState, makePrompt } from './guide-state.mjs';

const KEY = 'goro.station.guide.v1';
const byId = id => document.getElementById(id);
let state = normaliseState();
let storageAvailable = true;
let saved = null;
try { saved = localStorage.getItem(KEY); }
catch { storageAvailable = false; }
try { state = normaliseState(JSON.parse(saved || '{}')); }
catch { state = normaliseState(); }

function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); }
  catch { storageAvailable = false; }
  if (!storageAvailable) byId('storage-note').textContent = 'Браузер не сохраняет отметки. Инструкция работает, но после закрытия страницы данные могут исчезнуть.';
}

function message(id, text, good = false) {
  const node = byId(id);
  node.textContent = text;
  node.classList.toggle('is-ok', good);
}

function render() {
  const firmware = firmwareFor(state.model);
  const supported = Boolean(firmware);
  const other = state.model && !supported;
  const routeReady = supported && Object.hasOwn(OS_NAMES, state.os);
  byId('manual-route').hidden = Boolean(other);
  byId('other-route').hidden = !other;
  if (other) {
    const model = MODELS[state.model];
    byId('other-title').textContent = `Для ${model.title} нужен свой маршрут`;
    byId('other-note').textContent = model.note;
    byId('other-link').href = model.url;
  }
  const status = byId('route-status');
  status.textContent = routeReady ? `Ваш маршрут: ${firmware.title} + ${OS_NAMES[state.os]}. Показываем нужные команды.`
    : other ? 'Основной маршрут ниже скрыт: он не подходит выбранной модели.'
    : supported ? 'Теперь выберите систему компьютера.' : 'Выберите модель и систему. Ниже останутся подходящие инструкции.';
  status.classList.toggle('is-ready', routeReady);

  document.querySelectorAll('[data-model]').forEach(node => { node.hidden = state.model ? node.dataset.model !== state.model : false; });
  document.querySelectorAll('[data-selection-hint]').forEach(node => { node.hidden = supported; });
  document.querySelectorAll('[data-os]').forEach(node => {
    node.hidden = state.os ? !node.dataset.os.split(' ').includes(state.os) : false;
    if (node.tagName === 'DETAILS' && node.dataset.lastOs !== state.os) {
      node.open = Boolean(state.os) && !node.hidden;
      node.dataset.lastOs = state.os;
    }
  });
  document.querySelectorAll('[data-pc]').forEach(node => { node.textContent = state.pc || 'Адрес ПК из шага 4'; });
  document.querySelectorAll('[data-speaker]').forEach(node => { node.textContent = state.speaker || 'Адрес Станции из шага 6'; });

  let canConnect = false;
  try {
    byId('connect-command').textContent = connectCommand(state.model, state.pc, state.speaker);
    canConnect = routeReady;
  } catch {
    byId('connect-command').textContent = other ? 'Для выбранной модели используйте её отдельную инструкцию.'
      : 'Выберите модель и систему, затем укажите адреса компьютера и колонки.';
  }
  byId('dns-command').textContent = state.pc ? dnsCommand(state.pc) : 'Сначала укажите адрес компьютера в шаге 4.';
  document.querySelectorAll('[data-copy]').forEach(button => {
    const target = button.dataset.copy;
    button.disabled = target.startsWith('prompt-') ? false : !routeReady;
    if (button.dataset.guard === 'connect') button.disabled = !canConnect;
    if (button.dataset.guard === 'pc') button.disabled = !routeReady || !state.pc;
  });

  byId('old-dns-fields').hidden = byId('old-dns-mode').value !== 'manual';
  byId('restore-dns').textContent = state.oldDnsMode === 'auto' ? 'автоматическое получение DNS.'
    : state.oldDnsMode === 'manual' && state.oldDns1 ? `${state.oldDns1}${state.oldDns2 ? ` и ${state.oldDns2}` : ''}.`
    : 'пока не сохранена; используйте свой снимок экрана или запись.';
  for (const phase of ['prepare', 'diagnose', 'finish']) byId(`prompt-${phase}`).textContent = makePrompt(phase, state);

  document.querySelectorAll('[data-complete]').forEach(checkbox => {
    checkbox.disabled = !routeReady;
    checkbox.checked = state.completed.includes(checkbox.dataset.complete);
  });
  const count = state.completed.length;
  byId('progress').value = count;
  byId('progress-label').textContent = `Отмечено вами: ${count} из 7`;
  const anchors = ['tools', 'prepare', 'firmware', 'server', 'network', 'access', 'finish'];
  anchors.forEach((id, index) => {
    const link = document.querySelector(`.guide-sidebar a[href="#${id}"]`);
    link.dataset.done = String(state.completed.includes(String(index + 1)));
  });
}

byId('model').value = state.model;
byId('os').value = state.os;
byId('pc-ip').value = state.pc;
byId('speaker-ip').value = state.speaker;
byId('old-dns-mode').value = state.oldDnsMode;
byId('old-dns-1').value = state.oldDns1;
byId('old-dns-2').value = state.oldDns2;

for (const field of ['model', 'os']) byId(field).addEventListener('change', () => {
  state = normaliseState({ ...state, [field]: byId(field).value, completed: [], speaker: '',
    pc: field === 'os' ? '' : state.pc });
  byId('pc-ip').value = state.pc;
  byId('speaker-ip').value = '';
  message('pc-error', '');
  message('speaker-error', '');
  persist(); render();
});

function saveAddress(event, kind) {
  event.preventDefault();
  const input = byId(kind === 'pc' ? 'pc-ip' : 'speaker-ip');
  const output = kind === 'pc' ? 'pc-error' : 'speaker-error';
  const value = input.value.trim();
  const other = kind === 'pc' ? state.speaker : state.pc;
  if (!isLanIPv4(value)) {
    input.setAttribute('aria-invalid', 'true');
    message(output, 'Нужен домашний IPv4-адрес: четыре числа через точки, например 192.168.1.50, 10.0.0.5 или 172.16.0.5.');
    return;
  }
  if (value === other) {
    input.setAttribute('aria-invalid', 'true');
    message(output, 'Это уже адрес другого устройства. У компьютера и Станции должны быть разные адреса.');
    return;
  }
  state[kind] = value;
  input.removeAttribute('aria-invalid');
  input.value = value;
  message(output, kind === 'pc' ? 'Адрес компьютера подставлен в схему и подсказки.' : 'Адрес колонки подставлен в команду ниже.', true);
  persist(); render();
}
byId('pc-form').addEventListener('submit', event => saveAddress(event, 'pc'));
byId('speaker-form').addEventListener('submit', event => saveAddress(event, 'speaker'));
for (const [id, kind] of [['pc-ip', 'pc'], ['speaker-ip', 'speaker']]) {
  byId(id).addEventListener('input', () => {
    state[kind] = '';
    byId(id).removeAttribute('aria-invalid');
    message(kind === 'pc' ? 'pc-error' : 'speaker-error', 'Нажмите кнопку, чтобы подставить новый адрес.');
    state.completed = state.completed.filter(step => !['4', '5', '6'].includes(step));
    persist(); render();
  });
}
byId('old-dns-mode').addEventListener('change', () => { byId('old-dns-fields').hidden = byId('old-dns-mode').value !== 'manual'; });
byId('dns-form').addEventListener('submit', event => {
  event.preventDefault();
  const mode = byId('old-dns-mode').value;
  const first = byId('old-dns-1').value.trim();
  const second = byId('old-dns-2').value.trim();
  if (!['auto', 'manual'].includes(mode) || mode === 'manual' && (!isIPv4(first) || second && !isIPv4(second))) {
    message('dns-memory-status', 'Выберите исходный режим. Для ручного режима запишите DNS 1 и, если был, DNS 2: по четыре числа через точки.');
    return;
  }
  state.oldDnsMode = mode;
  state.oldDns1 = mode === 'manual' ? first : '';
  state.oldDns2 = mode === 'manual' ? second : '';
  persist(); render();
  message('dns-memory-status', storageAvailable ? 'Записано в этом браузере. Подсказка для возврата появится в шаге 7.' : 'Записано до закрытия страницы. Сделайте также свой снимок экрана роутера.', true);
});

document.querySelectorAll('[data-complete]').forEach(checkbox => checkbox.addEventListener('change', () => {
  state.completed = [...document.querySelectorAll('[data-complete]:checked')].map(node => node.dataset.complete);
  persist(); render();
}));
byId('clear-checks').addEventListener('click', () => { state.completed = []; persist(); render(); });

document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  if (button.disabled) return;
  const source = byId(button.dataset.copy);
  const feedback = button.closest('.command').querySelector('.copy-feedback');
  const text = source.textContent;
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(text);
    button.textContent = 'Скопировано';
    feedback.textContent = 'Вставьте в нужное окно. На этом сайте команда не выполняется.';
  } catch {
    const range = document.createRange();
    range.selectNodeContents(source);
    const selection = window.getSelection();
    selection.removeAllRanges(); selection.addRange(range);
    feedback.textContent = 'Текст выделен. Нажмите Ctrl+C или ⌘C, чтобы скопировать.';
  }
  setTimeout(() => { button.textContent = 'Копировать'; }, 1800);
}));

if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      document.querySelectorAll('.guide-sidebar a').forEach(link => {
        if (link.hash === `#${entry.target.id}`) link.setAttribute('aria-current', 'step');
        else link.removeAttribute('aria-current');
      });
    }
  }, { rootMargin: '-5% 0px -70% 0px' });
  document.querySelectorAll('#manual-route section[id]').forEach(section => observer.observe(section));
}
render();
if (!storageAvailable) persist();
