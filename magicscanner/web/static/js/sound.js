// Bips de retour (succès, à vérifier, échec, annulation).
const audio = new (window.AudioContext || window.webkitAudioContext)();

function beep(freq, ms = 90) {
  const osc = audio.createOscillator(), gain = audio.createGain();
  osc.frequency.value = freq;
  osc.connect(gain);
  gain.connect(audio.destination);
  gain.gain.setValueAtTime(0.15, audio.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + ms / 1000);
  osc.start();
  osc.stop(audio.currentTime + ms / 1000);
}

export const sound = {
  ok: () => beep(880),
  check: () => beep(520),
  error: () => beep(180, 250),
  undo: () => beep(300, 150),
};
