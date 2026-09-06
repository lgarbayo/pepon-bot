import './voice-vad.js';

class VoiceProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.vad = new globalThis.PeponVAD(sampleRate);
    this.frame = new Float32Array(Math.round(sampleRate * 0.02));
    this.offset = 0;
    this.speaking = false;
    this.port.onmessage = ({ data }) => {
      if (data.type === 'speaking') {
        this.speaking = data.value;
        if (data.value) this.vad.reset();
      }
    };
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input) {
      for (const sample of input) {
        this.frame[this.offset++] = sample;
        if (this.offset === this.frame.length) {
          const result = this.vad.feed(this.frame, this.speaking);
          this.port.postMessage(result, result.segment ? [result.segment.buffer] : []);
          this.frame = new Float32Array(this.frame.length);
          this.offset = 0;
        }
      }
    }
    // Output remains silence: never route the microphone to the speaker.
    return true;
  }
}
registerProcessor('pepon-voice', VoiceProcessor);
