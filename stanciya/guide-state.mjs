export const MODELS = Object.freeze({
  lite: { title: 'Станция Лайт 1', platform: 'yandexmicro',
    version: '0.369.1.46.4778262442.20261013.297',
    url: 'https://cdnriqbxswemmatxzibl.svc.cdn.yandex.net/yandexmicro/ota/user/770338e8-a517-4642-a442-d26be2632873/0.369.1.46.4778262442.20261013.297.zip' },
  mini: { title: 'Станция Мини 1', platform: 'yandexmini',
    version: '1.305.4.16.3237824040.20250721',
    url: 'https://cdnriqbxswemmatxzibl.svc.cdn.yandex.net/yandexmini/ota/release/0c7bd167-2fa4-4677-bb29-3748c21d985d/1.305.4.16.3237824040.20250721.zip' },
  mini2: { title: 'Станция Мини 2', url: 'https://github.com/krevetkqqq/lite-kit#что-проверено',
    note: 'В lite-kit описаны успешные попытки, но точная сборка для Мини 2 не зафиксирована. Начните с проверки совместимости.' },
  midi: { title: 'Станция Миди', url: 'https://github.com/krevetkqqq/lite-kit#что-проверено',
    note: 'Для Миди у авторов есть успешные попытки. Версию и порядок действий нужно сверить с её документацией.' },
  lite2: { title: 'Станция Лайт 2', url: 'https://hackalice.me/start/retail-ca/',
    note: 'Для Лайт 2 опубликован отдельный способ через заводской режим и замену сертификатов.' },
  mini3: { title: 'Станция Мини 3', url: 'https://hackalice.me/start/retail-ca-mini3/',
    note: 'У Мини 3 свой способ через заводской образ. Если этот образ тоже обновлён, описанный путь не подходит.' },
  first: { title: 'Станция первого поколения', url: 'https://hackalice.me/start/root-android/#station-1',
    note: 'Для первой большой Станции в AliceBridge предусмотрен отдельный способ с записью boot-образа.' },
  max: { title: 'Станция Макс', url: 'https://github.com/suddosu/yasta_flasher',
    note: 'У Макс другой маршрут: yasta_flasher и сервисное USB-подключение к плате. Команды от Лайт и Мини здесь не подходят.' },
  unknown: { title: 'Другая модель / пока не знаю', url: 'https://hackalice.me/',
    note: 'Сначала определите точную модель. Посмотрите название устройства в «Доме с Алисой» и сверьте его со справочником. Схожий внешний вид не подтверждает совместимость.' },
});

export const OS_NAMES = Object.freeze({ windows: 'Windows 10/11', mac: 'macOS', linux: 'Ubuntu / Debian' });

export function firmwareFor(model) {
  if (!Object.hasOwn(MODELS, model) || !MODELS[model].platform) return null;
  return MODELS[model];
}

export function isIPv4(value) {
  if (typeof value !== 'string' || /[^0-9.]/.test(value) || !/^(0|[1-9]\d{0,2})(\.(0|[1-9]\d{0,2})){3}$/.test(value)) return false;
  return value.split('.').every(part => Number(part) <= 255);
}

export function isLanIPv4(value) {
  if (!isIPv4(value)) return false;
  const [a, b] = value.split('.').map(Number);
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

export function connectCommand(model, pc, speaker) {
  if (!firmwareFor(model)) throw new Error('Для этой модели нужен отдельный маршрут.');
  if (!isLanIPv4(pc) || !isLanIPv4(speaker)) throw new Error('Укажите адреса компьютера и колонки в домашней сети.');
  if (pc === speaker) throw new Error('У компьютера и колонки должны быть разные адреса.');
  return `adb connect ${speaker}:5555\nadb shell id`;
}

export function dnsCommand(pc) {
  if (!isLanIPv4(pc)) throw new Error('Сначала укажите адрес компьютера.');
  return `nslookup quasar.yandex.net ${pc}`;
}

export function normaliseState(input = {}) {
  const safe = input && typeof input === 'object' ? input : {};
  const pc = isLanIPv4(safe.pc) ? safe.pc : '';
  const speaker = isLanIPv4(safe.speaker) && safe.speaker !== pc ? safe.speaker : '';
  return {
    model: Object.hasOwn(MODELS, safe.model) ? safe.model : '',
    os: Object.hasOwn(OS_NAMES, safe.os) ? safe.os : '',
    pc, speaker,
    oldDnsMode: ['auto', 'manual'].includes(safe.oldDnsMode) ? safe.oldDnsMode : '',
    oldDns1: isIPv4(safe.oldDns1) ? safe.oldDns1 : '',
    oldDns2: isIPv4(safe.oldDns2) ? safe.oldDns2 : '',
    completed: Array.isArray(safe.completed) ? [...new Set(safe.completed.filter(x => /^[1-7]$/.test(x)))] : [],
  };
}

export function makePrompt(phase, input) {
  const state = normaliseState(input);
  const model = MODELS[state.model]?.title || '[уточните точную модель]';
  const os = OS_NAMES[state.os] || '[уточните систему компьютера]';
  const context = `Моя колонка: ${model}.\nКомпьютер: ${os}.\nАдрес компьютера: ${state.pc || '[ещё не найден]'}.\nАдрес колонки: ${state.speaker || '[ещё не найден]'}.`;
  const source = 'Инструкция: https://ilyautov.github.io/gorilla-guides/stanciya/';
  if (phase === 'diagnose') return `${source}\n${context}\n\nПомоги найти причину ошибки. Сначала спроси, на каком я шаге, какую команду выполнил и что получил в ответ. Попроси нужный фрагмент журнала без паролей и токенов. Разделяй факты и гипотезы. Назови 2–3 возможные причины и проверяй по одной, начиная с действий без изменений. Предлагай исправление после подтверждения причины. Давай одно действие и ожидаемый результат за раз.`;
  if (phase === 'finish') {
    const oldDns = state.oldDnsMode === 'auto' ? 'автоматическое получение DNS' : state.oldDnsMode === 'manual' && state.oldDns1 ? [state.oldDns1, state.oldDns2].filter(Boolean).join(', ') : '[исходные настройки ещё нужно уточнить]';
    return `${source}\n${context}\nИсходный DNS: ${oldDns}.\n\nПомоги завершить настройку. Проверь root по фактическому выводу adb shell id. Помоги вернуть исходные значения DNS и остановить созданный стенд штатным stop-скриптом. Учитывай права администратора Windows. Не считай подтверждённым сохранение доступа после перезагрузки, если его не проверяли. В конце перечисли оставшиеся изменения на компьютере и колонке. Настройка постоянного доступа и отключение OTA требуют отдельного решения.`;
  }
  return `${source}\n${context}\n\nПодготовь компьютер до этапа сброса моей собственной колонки. Сверь совместимость и текущую инструкцию с первоисточниками. Проверь Python, ADB, сеть и свободные порты 53, 80, 443. Подготовь lite-kit и подходящий образ; проверь загрузку и модель. Веди запись: проверка → фактический результат → следующий шаг. Если у тебя нет доступа к терминалу, давай по одной команде с ожидаемым результатом. Перед изменением DNS сохрани исходные значения и опиши возврат. Сброс и запись прошивки вынеси в отдельный следующий шаг. Не запускай их в рамках подготовки.`;
}
