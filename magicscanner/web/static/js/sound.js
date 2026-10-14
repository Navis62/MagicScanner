// Bips de retour (succès, à vérifier, échec, annulation).
const audio = new (window.AudioContext || window.webkitAudioContext)();

function beep(freq, ms = 90, delay = 0, type = "sine") {
  const osc = audio.createOscillator(), gain = audio.createGain(), t = audio.currentTime + delay;
  osc.type = type;
  osc.frequency.value = freq;
  osc.connect(gain);
  gain.connect(audio.destination);
  gain.gain.setValueAtTime(0.15, t);
  gain.gain.exponentialRampToValueAtTime(0.001, t + ms / 1000);
  osc.start(t);
  osc.stop(t + ms / 1000);
}

export const sound = {
  ok: () => beep(880),
  check: () => beep(520),
  error: () => beep(180, 250),
  undo: () => beep(300, 150),
  // Alarme : la carte vaut plus que son prix de vente (sirène à deux tons, impossible à confondre avec les bips).
  alarm: () => [0, 0.16, 0.32, 0.48].forEach((d, i) => beep(i % 2 ? 660 : 990, 140, d, "square")),
};
