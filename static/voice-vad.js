// SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
//
// SPDX-License-Identifier: MIT

// Energy VAD with adaptive noise floor, onset confirmation and pre-roll.
// Pure signal logic, shared by the AudioWorklet and deterministic tests.
class PeponVAD {
  constructor(sampleRate) {
    this.sampleRate = sampleRate;
    this.noise = 0.003;
    this.reset();
  }
  reset() {
    this.pre = [];
    this.preMs = 0;
    this.frames = null;
    this.onsetMs = 0;
    this.silenceMs = 0;
    this.durationMs = 0;
  }
  feed(samples, speaking = false) {
    const ms = (samples.length / this.sampleRate) * 1000;
    const rms = Math.sqrt(
      samples.reduce((sum, x) => sum + x * x, 0) / samples.length,
    );
    const threshold = Math.max(
      speaking ? 0.035 : 0.012,
      this.noise * (speaking ? 5 : 3),
    );
    const voiced = rms > threshold;
    const result = {
      level: Math.min(1, rms * 10),
      started: false,
      segment: null,
    };
    if (!this.frames) {
      if (!voiced && !speaking)
        this.noise = Math.min(0.025, this.noise * 0.98 + rms * 0.02);
      this.pre.push(samples);
      this.preMs += ms;
      while (this.preMs > 420 && this.pre.length > 1) {
        this.preMs -= (this.pre.shift().length / this.sampleRate) * 1000;
      }
      this.onsetMs = voiced ? this.onsetMs + ms : 0;
      if (this.onsetMs >= (speaking ? 280 : 160)) {
        this.frames = this.pre;
        this.pre = [];
        this.durationMs = this.preMs;
        this.preMs = 0;
        this.silenceMs = 0;
        result.started = true;
      }
    } else {
      this.frames.push(samples);
      this.durationMs += ms;
      this.silenceMs = voiced ? 0 : this.silenceMs + ms;
      if (this.silenceMs >= 700 || this.durationMs >= 20000) {
        const length = this.frames.reduce((n, frame) => n + frame.length, 0);
        result.segment = new Float32Array(length);
        let offset = 0;
        for (const frame of this.frames) {
          result.segment.set(frame, offset);
          offset += frame.length;
        }
        this.reset();
      }
    }
    return result;
  }
}
globalThis.PeponVAD = PeponVAD;
