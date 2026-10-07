import type { GameState } from './contracts';

export function challengeUrl(state: GameState): string {
  const url = new URL(window.location.href);
  url.searchParams.set('block', state.seed);
  url.searchParams.set('character', state.character);
  const scoreVal = Math.max(0, Math.floor(Number.isFinite(state.score) ? state.score : 0));
  url.searchParams.set('beat', String(scoreVal));
  url.searchParams.set('mode', 'sandbox');
  return url.toString();
}

export function exportScorecard(state: GameState): void {
  const canvas = document.createElement('canvas');
  canvas.width = 1080;
  canvas.height = 1350;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // Palette
  const cream = '#f4f0e5';
  const forest = '#193c35';
  const orange = '#ed713f';

  // Background
  ctx.fillStyle = cream;
  ctx.fillRect(0, 0, 1080, 1350);

  // Border & Grid Frame
  ctx.strokeStyle = forest;
  ctx.lineWidth = 12;
  ctx.strokeRect(36, 36, 1008, 1278);

  // Fine inner accent border
  ctx.strokeStyle = orange;
  ctx.lineWidth = 3;
  ctx.strokeRect(48, 48, 984, 1254);

  // Brand Header
  ctx.fillStyle = forest;
  ctx.font = '700 36px sans-serif';
  ctx.fillText('SNOW GLOVES OS', 80, 120);

  ctx.fillStyle = orange;
  ctx.font = '700 24px sans-serif';
  ctx.fillText('/ INFRASTRUCTURE SIMULATION SCORECARD', 440, 120);

  ctx.strokeStyle = 'rgba(25, 60, 53, 0.2)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(80, 150);
  ctx.lineTo(1000, 150);
  ctx.stroke();

  // Big Hero Score Block
  ctx.fillStyle = forest;
  ctx.font = '700 48px sans-serif';
  ctx.fillText('FINAL SCORE', 80, 240);

  ctx.fillStyle = orange;
  ctx.font = '900 180px sans-serif';
  ctx.fillText(String(state.score), 80, 420);

  // Stat Grid Panel
  ctx.fillStyle = forest;
  ctx.fillRect(80, 500, 920, 460);

  ctx.fillStyle = cream;
  ctx.font = '700 24px sans-serif';
  ctx.fillText('RUN SPECIFICATION', 120, 555);

  ctx.fillStyle = 'rgba(244, 240, 229, 0.3)';
  ctx.fillRect(120, 575, 840, 2);

  // Rows in panel
  const stats = [
    { label: 'OPERATIVE UNIT', value: state.character.toUpperCase() },
    { label: 'SEED BLOCK', value: state.seed.slice(0, 32) },
    { label: 'DESTROYED PAYLOADS', value: String(state.destroyed) },
    { label: 'MAX COMBO MULTIPLIER', value: `${state.bestCombo}x` },
    { label: 'ELAPSED SIMULATION', value: `${state.elapsed.toFixed(1)}s` }
  ];

  stats.forEach((st, idx) => {
    const y = 630 + (idx * 60);
    ctx.fillStyle = 'rgba(244, 240, 229, 0.7)';
    ctx.font = '600 22px sans-serif';
    ctx.fillText(st.label, 120, y);

    ctx.fillStyle = cream;
    ctx.font = '700 26px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(st.value, 960, y);
    ctx.textAlign = 'left';
  });

  // Footer Verification Note
  ctx.fillStyle = forest;
  ctx.font = '600 22px sans-serif';
  ctx.fillText('BROWSER SIMULATION · SOURCE-MAPPED TOY CITY', 80, 1040);

  ctx.fillStyle = 'rgba(25, 60, 53, 0.6)';
  ctx.font = '400 18px sans-serif';
  ctx.fillText(`Timestamp: ${new Date().toISOString()} | Deterministic Seed Protocol`, 80, 1080);

  // Bottom stamp
  ctx.fillStyle = orange;
  ctx.fillRect(80, 1140, 920, 70);
  ctx.fillStyle = '#ffffff';
  ctx.font = '700 24px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('SNOW GLOVES INFRASTRUCTURE TOY-CITY RUNTIME', 540, 1184);

  const link = document.createElement('a');
  link.download = `snowgloves-${state.character}-${state.seed}.png`;
  link.href = canvas.toDataURL('image/png');
  link.click();
}
