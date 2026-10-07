import { describe, expect, it } from 'vitest';
import { nodes } from './data';
import { createGame, tick, attack, stomp, grabThrow, start, pause, resume } from './game';
const idle = { x: 0, z: 0, attack: false };
const advance = (g: ReturnType<typeof createGame>, seconds: number) => {
  for (let n = 0; n < Math.ceil(seconds / 0.1); n++) tick(g, 0.1, idle);
};
const near = (g: ReturnType<typeof createGame>, i: number) => {
  const b = g.buildings[i];
  g.player = { x: b.x - b.width / 2 - 1.8, z: b.z, angle: Math.PI / 2 };
  return b;
};
describe('controller acceptance from the supplied specification', () => {
  it('binds sixteen buildings to actual infrastructure IDs on the 10.4 grid', () => {
    const g = createGame('acceptance', 'munch');
    expect(g.buildings.map(b => b.id).sort()).toEqual(nodes.map(n => n.id).sort());
    const centers = [-15.6, -5.2, 5.2, 15.6];
    for (const b of g.buildings) {
      expect(centers.some(x => Math.abs(x - b.x) < 0.0001)).toBe(true);
      expect(centers.some(z => Math.abs(z - b.z) < 0.0001)).toBe(true);
    }
    expect(g.remaining).toBe(45);
    expect(g.player).toMatchObject({ x: 0, z: 10.4 });
    expect(g.cars).toHaveLength(13);
    expect(new Set(g.cars.map(c => Math.round(c.z))).size).toBeGreaterThan(3);
    expect(g.cars.some(c => Math.hypot(c.x, c.z - 10.4) < 3)).toBe(true);
  });
  it('scores ordinary hits, limits cadence, and adds demolition points', () => {
    const g = createGame('acceptance', 'munch'); start(g);
    const b = near(g, 0); const hp = b.health;
    attack(g); expect(b.health).toBe(hp - 1); expect(g.score).toBe(20);
    attack(g); expect(b.health).toBe(hp - 1);
    advance(g, 0.5); b.health = 1; attack(g);
    expect(b.destroyed).toBe(true); expect(g.combo).toBe(1); expect(g.multiplier).toBe(1);
    expect(g.score).toBe(40 + Math.round(180 + b.height * 50));
  });
  it('freezes pause and prevents scoring after the timed result', () => {
    const g = createGame('acceptance', 'bolt'); start(g); pause(g);
    advance(g, 2); expect(g.remaining).toBe(45); resume(g);
    advance(g, 45.1); expect(g.mode).toBe('result'); expect(g.remaining).toBe(0);
    const score = g.score; attack(g); stomp(g); grabThrow(g); expect(g.score).toBe(score);
  });
  it('exposes stomp cooldown and keeps car grab separate from throw', () => {
    const g = createGame('acceptance', 'bongo'); start(g);
    stomp(g); expect(g.stompCooldown).toBe(7); expect(stomp(g)).toEqual([]);
    advance(g, 1); expect(g.stompCooldown).toBeCloseTo(6);
    g.player.x = 0; g.player.z = 10.4; grabThrow(g);
    expect(g.heldCar).not.toBeNull(); expect(g.cars.some(c => c.state === 'held')).toBe(true);
    grabThrow(g); expect(g.heldCar).toBeNull(); expect(g.cars.some(c => c.state === 'held')).toBe(false);
  });
  it('expires the demolition combo without ordinary hits extending it', () => {
    const g = createGame('acceptance', 'munch'); start(g);
    near(g, 0).health = 1; attack(g); advance(g, 2.8);
    const b = near(g, 1); b.health = 6; attack(g); expect(g.combo).toBe(1);
    advance(g, 0.9); expect(g.combo).toBe(0); expect(g.multiplier).toBe(1);
  });
});
