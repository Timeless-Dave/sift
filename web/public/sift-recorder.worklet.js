/**
 * AudioWorklet recorder for the acoustic sweep (loaded by web/src/sensors/acoustic.ts).
 * Lives in public/ so it ships as a same-origin file: the Content-Security-Policy has
 * neither blob: nor data: in script-src, so an inline worklet would be blocked, and the
 * bundler inlines tiny files. Posts each input block to the main thread; pass-through.
 */
class SiftRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs && inputs[0];
    const first = channels && channels[0];
    if (first) this.port.postMessage(first.slice(0));
    return true;
  }
}

registerProcessor("sift-recorder", SiftRecorder);
