import test from 'node:test';
import assert from 'node:assert/strict';

const api = await import('./guide-state.mjs').catch(() => ({}));

test('only the two documented models expose a firmware download', () => {
  assert.equal(typeof api.firmwareFor, 'function', 'firmware selection is not implemented');
  assert.match(api.firmwareFor('lite').url, /\/yandexmicro\//);
  assert.match(api.firmwareFor('mini').url, /\/yandexmini\//);
  for (const model of ['', 'mini2', 'max', '__proto__', '<script>']) {
    assert.equal(api.firmwareFor(model), null);
  }
});

test('LAN addresses reject shell input, public hosts and malformed octets', () => {
  assert.equal(typeof api.isLanIPv4, 'function', 'address validation is not implemented');
  for (const ip of ['192.168.1.50', '10.0.0.5', '172.16.1.5', '172.31.255.254']) {
    assert.equal(api.isLanIPv4(ip), true, ip);
  }
  for (const ip of ['', '127.0.0.1', '8.8.8.8', '172.32.0.1', '192.168.1.300',
    '192.168.01.2', '192.168.1.2;whoami', '$(curl evil)', '192.168.1.2\nreboot',
    '192.168.1.2\n', '192.168.1.2\t']) {
    assert.equal(api.isLanIPv4(ip), false, ip);
  }
});

test('connection commands require distinct validated computer and speaker addresses', () => {
  assert.equal(typeof api.connectCommand, 'function', 'command generation is not implemented');
  assert.equal(api.connectCommand('lite', '192.168.1.50', '192.168.1.77'),
    'adb connect 192.168.1.77:5555\nadb shell id');
  assert.throws(() => api.connectCommand('lite', '192.168.1.50', '192.168.1.50'));
  assert.throws(() => api.connectCommand('max', '192.168.1.50', '192.168.1.77'));
  assert.throws(() => api.connectCommand('mini', '192.168.1.50', '192.168.1.77;reboot'));
  assert.throws(() => api.connectCommand('mini', '', '192.168.1.77'));
});

test('prompts and persisted state discard unknown model names and injected addresses', () => {
  assert.equal(typeof api.normaliseState, 'function', 'state validation is not implemented');
  const state = api.normaliseState({ model: '__proto__', os: 'win;reboot',
    pc: '$(curl evil)', speaker: '192.168.1.77', completed: ['1', '99', '<img>'],
    oldDnsMode: 'manual', oldDns1: '8.8.8.8;reboot', oldDns2: '1.1.1.1' });
  assert.equal(state.model, '');
  assert.equal(state.os, '');
  assert.equal(state.pc, '');
  assert.equal(state.oldDns1, '');
  assert.deepEqual(state.completed, ['1']);
  const prompt = api.makePrompt('prepare', state);
  assert.doesNotMatch(prompt, /curl evil|__proto__|win;reboot|8\.8\.8\.8;reboot/);
  assert.match(prompt, /Сброс/);
});
