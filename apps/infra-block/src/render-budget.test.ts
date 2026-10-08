import { describe, expect, it } from 'vitest';
import { renderBudget } from './render-budget';

describe('bounded graphics profiles', () => {
  it('bounds costly pixel and shadow work on high density displays', () => {
    expect(renderBudget('balanced', 4)).toEqual({ pixelRatio: 1.25, shadows: true, shadowSize: 1024, maxFps: 60 });
    expect(renderBudget('eco', 4)).toEqual({ pixelRatio: 0.8, shadows: false, shadowSize: 1024, maxFps: 30 });
  });
  it('rejects invalid device ratios while respecting lower density displays', () => {
    for (const value of [NaN, Infinity, -2, 0]) expect(renderBudget('balanced', value).pixelRatio).toBe(1);
    expect(renderBudget('balanced', 0.7).pixelRatio).toBe(0.7);
  });
});
