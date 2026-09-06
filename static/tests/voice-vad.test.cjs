const assert = require('node:assert/strict');
require('../voice-vad.js');
const rate = 16000;
const silence = () => new Float32Array(320);
const speech = () => Float32Array.from({ length: 320 }, (_, i) => Math.sin(i / 8) * .15);
function feed(vad, frames, factory, speaking = false) {
  const events = [];
  for (let i = 0; i < frames; i++) events.push(vad.feed(factory(), speaking));
  return events;
}
const vad = new PeponVAD(rate);
assert(feed(vad, 100, silence).every(e => !e.started && !e.segment));
assert(feed(vad, 4, speech).every(e => !e.started)); // 80ms click/noise rejected
feed(vad, 20, silence);
let events = feed(vad, 40, speech);
assert.equal(events.filter(e => e.started).length, 1);
assert(!feed(vad, 25, silence).some(e => e.segment)); // phrase pause, 500ms
assert(!feed(vad, 30, speech).some(e => e.started)); // same utterance
const finished = feed(vad, 35, silence).find(e => e.segment);
assert(finished);
assert(finished.segment.length > rate * 2); // pre-roll + both phrase halves retained
assert(feed(vad, 100, silence).every(e => !e.segment)); // silence never submitted
vad.reset();
assert(feed(vad, 10, speech, true).every(e => !e.started));
assert(feed(vad, 5, speech, true).some(e => e.started)); // stronger, sustained barge-in
vad.reset();
assert(feed(vad, 1050, speech).some(e => e.segment)); // bounded long utterance
console.log('VAD passed: silence/noise rejection, onset, pre-roll, pauses, barge-in, bounded audio.');
