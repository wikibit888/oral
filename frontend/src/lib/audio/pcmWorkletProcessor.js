/* eslint-disable no-undef */
// Runs on the audio render thread (AudioWorkletGlobalScope). Forwards each
// 128-frame block of mono input (Float32, at the AudioContext's native rate) to
// the main thread, which accumulates + downsamples + encodes (recorder.js /
// wavEncoder.js). AudioWorkletProcessor / registerProcessor are worklet-scope
// globals, hence the eslint-disable above.
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0]) {
      // Copy: the render quantum's backing buffer is reused across calls.
      this.port.postMessage(input[0].slice(0));
    }
    return true; // keep the processor alive until the node is disconnected
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
