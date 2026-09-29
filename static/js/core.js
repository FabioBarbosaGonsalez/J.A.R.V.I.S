// Núcleo central animado (canvas 2D).
//
// Estados: idle (pulso lento), listening (onda suave), thinking (anéis âmbar
// girando rápido) e speaking (onda e brilho que reagem à fala).
// Os parâmetros visuais de cada estado são interpolados suavemente, então a
// troca de estado nunca "pula".
//
// Sobre "reagir ao áudio": a speechSynthesis do navegador não expõe as amostras
// de áudio. Usamos os eventos de fronteira de palavra (pulse()) somados a uma
// modulação sintética, que dá o mesmo efeito visual mesmo nas vozes que não
// emitem esses eventos.

const PRESETS = {
  idle:      { spin: 0.12, pulseHz: 0.22, pulseAmp: 0.05,  warm: 0,    wave: 0,    glow: 0.55 },
  listening: { spin: 0.35, pulseHz: 0.9,  pulseAmp: 0.025, warm: 0,    wave: 0.55, glow: 0.85 },
  thinking:  { spin: 1.8,  pulseHz: 1.4,  pulseAmp: 0.02,  warm: 1,    wave: 0,    glow: 0.7 },
  speaking:  { spin: 0.45, pulseHz: 0,    pulseAmp: 0,     warm: 0.25, wave: 1,    glow: 0.9 },
};

const CYAN = [76, 214, 255];
const AMBER = [255, 181, 71];
const TAU = Math.PI * 2;

const mix = (a, b, k) => a.map((v, i) => Math.round(v + (b[i] - v) * k));
const rgba = (c, a) => `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${Math.max(0, Math.min(1, a))})`;

export function createCore(canvas) {
  const ctx = canvas.getContext('2d');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  let state = 'idle';
  const p = { ...PRESETS.idle };
  let width = 0;
  let height = 0;
  let angle = 0;
  let phase = 0;
  let level = 0; // energia da fala, 0..1
  let t = 0;
  let last = performance.now();
  let raf = 0;

  const particles = Array.from({ length: 46 }, () => ({
    r: 0.36 + Math.random() * 0.62,
    a: Math.random() * TAU,
    s: (0.2 + Math.random() * 0.8) * (Math.random() < 0.5 ? -1 : 1),
    size: 0.5 + Math.random() * 1.3,
    o: 0.15 + Math.random() * 0.45,
  }));

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!raf) draw();
  }

  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    t += dt;

    const target = PRESETS[state];
    const k = 1 - Math.exp(-dt * 4);
    for (const key in target) p[key] += (target[key] - p[key]) * k;

    angle += p.spin * dt;
    phase += p.pulseHz * dt * TAU;

    if (state === 'speaking') {
      const synthetic = 0.22 + 0.22 * Math.abs(Math.sin(t * 7.3) * Math.sin(t * 2.1));
      level = Math.max(level * Math.exp(-dt * 5), synthetic);
    } else {
      level *= Math.exp(-dt * 4);
    }

    draw();
    raf = requestAnimationFrame(frame);
  }

  function draw() {
    const R = Math.min(width, height) * 0.46;
    if (R <= 0) return;

    const color = mix(CYAN, AMBER, p.warm);
    const pulse = 1 + Math.sin(phase) * p.pulseAmp;

    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.translate(width / 2, height / 2);
    ctx.globalCompositeOperation = 'lighter';

    // Halo
    const halo = ctx.createRadialGradient(0, 0, R * 0.1, 0, 0, R);
    halo.addColorStop(0, rgba(color, 0.2 * p.glow));
    halo.addColorStop(1, rgba(color, 0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(0, 0, R, 0, TAU);
    ctx.fill();

    // Anel de marcações
    ctx.save();
    ctx.rotate(angle * 0.25);
    for (let i = 0; i < 120; i++) {
      const major = i % 10 === 0;
      const a = (i / 120) * TAU;
      const r1 = R * 0.96;
      const r2 = R * (major ? 0.89 : 0.93);
      ctx.strokeStyle = rgba(CYAN, major ? 0.75 : 0.28);
      ctx.lineWidth = major ? 1.5 : 1;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1);
      ctx.lineTo(Math.cos(a) * r2, Math.sin(a) * r2);
      ctx.stroke();
    }
    ctx.restore();

    // Anel segmentado
    ctx.save();
    ctx.rotate(angle);
    ctx.lineWidth = 2;
    ctx.strokeStyle = rgba(color, 0.75);
    for (let i = 0; i < 3; i++) {
      const a0 = (i * TAU) / 3;
      ctx.beginPath();
      ctx.arc(0, 0, R * 0.82, a0, a0 + Math.PI * 0.45);
      ctx.stroke();
    }
    ctx.restore();

    // Anel tracejado, girando ao contrário
    ctx.save();
    ctx.rotate(-angle * 1.4);
    ctx.setLineDash([R * 0.02, R * 0.035]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = rgba(CYAN, 0.45);
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.72, 0, TAU);
    ctx.stroke();
    ctx.restore();

    // Arcos do estado "pensando"
    if (p.warm > 0.02) {
      ctx.save();
      ctx.rotate(angle * 2.2);
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.strokeStyle = rgba(AMBER, 0.85 * p.warm);
      for (let i = 0; i < 4; i++) {
        const a0 = (i * Math.PI) / 2;
        ctx.beginPath();
        ctx.arc(0, 0, R * 0.62, a0, a0 + Math.PI * 0.22);
        ctx.stroke();
      }
      ctx.restore();
    }

    // Onda circular (ouvindo / falando)
    const waveAmp = p.wave * R * (state === 'speaking'
      ? 0.03 + level * 0.09
      : 0.035 * (0.6 + 0.4 * Math.sin(t * 3)));
    ctx.beginPath();
    for (let i = 0; i <= 180; i++) {
      const a = (i / 180) * TAU;
      const noise = Math.sin(a * 6 + t * 4) * 0.5 + Math.sin(a * 11 - t * 6.5) * 0.3 + Math.sin(a * 3 + t * 2) * 0.2;
      const r = R * 0.5 * pulse + noise * waveAmp;
      const x = Math.cos(a) * r;
      const y = Math.sin(a) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = rgba(color, 0.5 + 0.4 * p.wave);
    ctx.stroke();

    // Partículas orbitando
    for (const pt of particles) {
      const a = pt.a + angle * pt.s * 0.6;
      const r = R * pt.r;
      ctx.fillStyle = rgba(CYAN, pt.o * p.glow);
      ctx.fillRect(Math.cos(a) * r, Math.sin(a) * r, pt.size, pt.size);
    }

    // Orbe central
    const orbR = R * 0.3 * pulse * (1 + level * 0.18);
    const orb = ctx.createRadialGradient(0, 0, 0, 0, 0, orbR);
    orb.addColorStop(0, `rgba(255, 255, 255, ${0.1 + 0.8 * p.glow})`);
    orb.addColorStop(0.25, rgba(color, 0.2 + 0.7 * p.glow));
    orb.addColorStop(0.7, rgba(color, 0.18));
    orb.addColorStop(1, rgba(color, 0));
    ctx.fillStyle = orb;
    ctx.beginPath();
    ctx.arc(0, 0, orbR, 0, TAU);
    ctx.fill();

    ctx.lineWidth = 1;
    ctx.strokeStyle = rgba(color, 0.6);
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.34 * pulse, 0, TAU);
    ctx.stroke();

    ctx.restore();
  }

  function start() {
    if (raf) return;
    last = performance.now();
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    cancelAnimationFrame(raf);
    raf = 0;
  }

  // Com "reduzir movimento", o núcleo fica parado e só muda de cor/forma por estado.
  function applyMotionPreference() {
    if (reduceMotion.matches) {
      stop();
      Object.assign(p, PRESETS[state]);
      draw();
    } else {
      start();
    }
  }

  new ResizeObserver(resize).observe(canvas);
  reduceMotion.addEventListener('change', applyMotionPreference);
  applyMotionPreference();

  return {
    get state() {
      return state;
    },
    setState(next) {
      if (!PRESETS[next] || next === state) return;
      state = next;
      if (!raf) {
        Object.assign(p, PRESETS[state]);
        draw();
      }
    },
    /** Pico de energia (ex.: a cada palavra falada). */
    pulse(strength = 0.5) {
      level = Math.min(1, level + strength);
    },
  };
}
