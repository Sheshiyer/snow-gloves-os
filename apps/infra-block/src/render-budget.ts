export type GraphicsProfile = 'balanced' | 'eco';

export function renderBudget(profile: GraphicsProfile, deviceRatio: number) {
  const ratio = Number.isFinite(deviceRatio) && deviceRatio > 0 ? deviceRatio : 1;
  return {
    pixelRatio: Math.min(ratio, profile === 'eco' ? 0.8 : 1.25),
    shadows: profile !== 'eco',
    shadowSize: 1024,
    maxFps: profile === 'eco' ? 30 : 60
  };
}
