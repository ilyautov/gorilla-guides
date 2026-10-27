import test from 'node:test';
import assert from 'node:assert/strict';
import { normaliseProject, makeBrief, recommendedTools, makeTask, FORMAT } from './guide-state.mjs';

test('saved values are whitelisted and control characters cannot enter prompts', () => {
 const p=normaliseProject({goal:'__proto__',agent:'<script>',os:'evil',format:'evil',duration:999,purpose:'evil',topic:'  Тема\u0000\nпро кино  ',completed:['1','1','8','<b>']});
 assert.equal(p.goal,'text');assert.equal(p.os,'unknown');assert.equal(p.agent,'new');assert.equal(p.duration,15);assert.equal(p.format,'vertical');assert.equal(p.purpose,'personal');assert.equal(p.topic,'Тема про кино');assert.deepEqual(p.completed,['1']);
 assert.doesNotThrow(()=>normaliseProject({goal:{toString:null},duration:{toString:null,valueOf:null}}));
 assert.equal(normaliseProject({topic:'я'.repeat(1000)}).topic.length,160);
});
test('the brief requires a real topic and matches chosen size and duration', () => {
 assert.throws(()=>makeBrief({topic:' '}));
 const b=makeBrief({topic:'Как проверить ответ',format:'wide',duration:30});
 assert.match(b,/1920×1080/);assert.match(b,/0–10/);assert.match(b,/20–30/);assert.match(b,/MP4/);assert.equal(FORMAT.square.size,'1080×1080');
});
test('commercial voice route uses the original recording, never NC voice weights', () => {
 const p={goal:'voice',purpose:'commercial',topic:'Наш продукт'};
 assert.deepEqual(recommendedTools(p),['HyperFrames','своя запись','WhisperX']);
 assert.ok(!recommendedTools(p).some(x=>/OmniVoice|F5/.test(x)));
 assert.match(makeBrief(p),/не использовать готовые веса OmniVoice и F5-TTS/);
 assert.match(makeBrief({goal:'photo',purpose:'commercial',topic:'Наш продукт'}),/Small/);
});
test('all task prompts separate preparation, review and delivery evidence', () => {
 for(const phase of ['prepare','build','fix','finish']){
  assert.doesNotThrow(()=>makeTask(phase,{topic:'я'}));
  const s=makeTask(phase,{topic:'Кино </code><script>alert(1)</script>',agent:'codex'});
  assert.equal(typeof s,'string');assert.ok(s.length>250);assert.match(s,/Кино/);
 }
 assert.match(makeTask('prepare',{topic:'Тема ролика'}),/не скачивай/);
 assert.match(makeTask('finish',{topic:'Тема ролика'}),/фактическ/);
});
