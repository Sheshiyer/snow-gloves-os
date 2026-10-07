import { describe, expect, it } from 'vitest';
import { createGame, tick, attack, stomp, grabThrow, start, pause, resume } from './game';

describe('seeded geometry determinism', () => {
  it('same seed produces identical layout', () => {
    const a = createGame('snow', 'munch');
    const b = createGame('snow', 'munch');
    expect(a.buildings.map((x) => [x.x, x.z, x.width, x.depth, x.floors, x.health])).toEqual(
      b.buildings.map((x) => [x.x, x.z, x.width, x.depth, x.floors, x.health])
    );
    expect(a.cars.map((c) => [c.x, c.z])).toEqual(b.cars.map((c) => [c.x, c.z]));
  });

  it('different seeds produce different layout', () => {
    const a = createGame('snow', 'munch');
    const b = createGame('rain', 'munch');
    expect(a.buildings.map((x) => [x.x, x.z, x.width, x.depth, x.floors, x.health])).not.toEqual(
      b.buildings.map((x) => [x.x, x.z, x.width, x.depth, x.floors, x.health])
    );
  });
});

describe('world presence', () => {
  it('has 16 buildings and 13 cars', () => {
    const g = createGame('x', 'bolt');
    expect(g.buildings).toHaveLength(16);
    expect(g.cars).toHaveLength(13);
  });

  it('buildings have valid stats', () => {
    const g = createGame('x', 'bolt');
    for (const b of g.buildings) {
      expect(b.width).toBeGreaterThanOrEqual(5);
      expect(b.width).toBeLessThanOrEqual(6);
      expect(b.depth).toBeGreaterThanOrEqual(5);
      expect(b.depth).toBeLessThanOrEqual(6);
      expect(b.floors).toBeGreaterThanOrEqual(2);
      expect(b.floors).toBeLessThanOrEqual(5);
      expect(b.height).toBeCloseTo(b.floors * 1.5);
      expect(b.maxHealth).toBe(b.floors + 1);
      expect(b.health).toBe(b.maxHealth);
      expect(b.destroyed).toBe(false);
    }
  });

  it('player starts at origin', () => {
    const g = createGame('x', 'bolt');
    expect(g.player.x).toBe(0);
    expect(g.player.z).toBe(10.4);
  });
});

describe('pause and resume', () => {
  it('pause freezes tick', () => {
    const g = createGame('x', 'bolt');
    start(g);
    pause(g);
    const events = tick(g, 1, { x: 0, z: 1, attack: false });
    expect(events).toEqual([]);
    expect(g.elapsed).toBe(0);
    expect(g.player.x).toBe(0);
    expect(g.player.z).toBe(10.4);
  });

  it('resume resumes tick', () => {
    const g = createGame('x', 'bolt');
    start(g);
    pause(g);
    resume(g);
    tick(g, 0.1, { x: 0, z: 1, attack: false });
    expect(g.elapsed).toBeCloseTo(0.1);
    expect(g.player.z).toBeGreaterThan(10.4);
  });

  it('actions frozen in pause', () => {
    const g = createGame('x', 'bolt');
    start(g);
    pause(g);
    expect(attack(g)).toEqual([]);
    expect(stomp(g)).toEqual([]);
    expect(grabThrow(g)).toEqual([]);
  });
});

describe('dt cap and NaN', () => {
  it('clamps dt to 0.1', () => {
    const g = createGame('x', 'bolt');
    start(g);
    tick(g, 1, { x: 0, z: 1, attack: false });
    expect(g.elapsed).toBeCloseTo(0.1);
  });

  it('rejects NaN dt', () => {
    const g = createGame('x', 'bolt');
    start(g);
    tick(g, Number.NaN, { x: 0, z: 1, attack: false });
    expect(g.elapsed).toBe(0);
  });

  it('explore mode freezes', () => {
    const g = createGame('x', 'bolt');
    tick(g, 0.1, { x: 0, z: 1, attack: false });
    expect(g.elapsed).toBe(0);
    expect(g.mode).toBe('explore');
  });
});

describe('clock and result', () => {
  it('result after 45 seconds', () => {
    const g = createGame('x', 'bolt');
    start(g);
    let events: any[] = [];
    for (let i = 0; i < 451; i++) {
      events = tick(g, 0.1, { x: 0, z: 0, attack: false });
      if (g.mode === 'result') break;
    }
    expect(g.mode).toBe('result');
    expect(events.some((e) => e.type === 'result')).toBe(true);
    expect(g.elapsed).toBeCloseTo(45);
  });

  it('cooldown only expires while playing', () => {
    const g = createGame('x', 'bolt');
    start(g);
    attack(g);
    // freeze during cooldown
    pause(g);
    tick(g, 5, { x: 0, z: 0, attack: false }); // 5s in pause does nothing
    resume(g);
    expect(attack(g)).toEqual([]); // still cooling down
  });
});

describe('collision and normalized movement', () => {
  it('world bounds clamp player', () => {
    const g = createGame('x', 'bolt');
    start(g);
    tick(g, 10, { x: 1, z: 0, attack: false });
    expect(g.player.x).toBeLessThanOrEqual(23);
    expect(g.player.x).toBeGreaterThanOrEqual(-23);
  });

  it('normalized diagonal has magnitude ~speed*dt', () => {
    const g = createGame('x', 'bolt');
    start(g);
    const before = { x: g.player.x, z: g.player.z };
    tick(g, 0.1, { x: 1, z: 1, attack: false });
    const dx = g.player.x - before.x;
    const dz = g.player.z - before.z;
    expect(Math.sqrt(dx * dx + dz * dz)).toBeCloseTo(6 * 0.1, 1);
  });
});

describe('attack cooldown and scoring', () => {
  it('attack cooldown prevents double attack', () => {
    const g = createGame('x', 'bolt');
    start(g);
    g.player.x = 0;
    g.player.z = 10.4;
    const b = g.buildings[0];
    g.player.x = b.x;
    g.player.z = b.z + 2; // within 3.8 edge
    const first = attack(g);
    expect(first.length).toBeGreaterThan(0);
    const second = attack(g);
    expect(second).toEqual([]);
  });

  it('attack damages and scores demolition', () => {
    const g = createGame('x', 'bolt');
    start(g);
    const b = g.buildings[0];
    g.player.x = b.x;
    g.player.z = b.z + 2;
    // reduce health to 1 to test demolition
    b.health = 1;
    const events = attack(g);
    expect(events.some((e) => e.type === 'demolish')).toBe(true);
    expect(b.destroyed).toBe(true);
    expect(g.destroyed).toBe(1);
    expect(g.remaining).toBe(45);
    expect(g.combo).toBe(1);
    expect(g.multiplier).toBe(1);
  });

  it('demolition increments combo multiplier', () => {
    const g = createGame('x', 'bolt');
    start(g);
    const b = g.buildings[0];
    g.player.x = b.x;
    g.player.z = b.z + 2;
    b.health = 1;
    attack(g);
    expect(g.multiplier).toBe(1);
    const c = g.buildings[1];
    g.player.x = c.x;
    g.player.z = c.z + 2;
    c.health = 1;
    for (let i = 0; i < 5; i++) tick(g, 0.1, { x: 0, z: 0, attack: false });
    attack(g);
    expect(g.combo).toBe(2);
    expect(g.multiplier).toBe(2);
  });
});

describe('combo expiry', () => {
  it('combo resets after expiry', () => {
    const g = createGame('x', 'bolt');
    start(g);
    const b = g.buildings[0];
    g.player.x = b.x;
    g.player.z = b.z + 2;
    b.health = 1;
    attack(g);
    expect(g.combo).toBe(1);
    for (let i = 0; i < 36; i++) tick(g, 0.1, { x: 0, z: 0, attack: false });
    expect(g.combo).toBe(0);
    expect(g.multiplier).toBe(1);
  });
});

describe('grab and throw', () => {
  it('grabs closest parked car within 3.4', () => {
    const g = createGame('x', 'bolt');
    start(g);
    g.player.x = g.cars[0].x;
    g.player.z = g.cars[0].z;
    const events = grabThrow(g);
    expect(events.some((e) => e.type === 'grab')).toBe(true);
    expect(g.heldCar).toBe(0);
    expect(g.cars[0].state).toBe('held');
  });

  it('throws car at closest building within 10', () => {
    const g = createGame('x', 'bolt');
    start(g);
    // grab
    g.player.x = g.cars[0].x;
    g.player.z = g.cars[0].z;
    grabThrow(g);
    // move near a building
    const b = g.buildings[0];
    g.player.x = b.x;
    g.player.z = b.z + 2;
    const before = b.health;
    const events = grabThrow(g);
    expect(events.some((e) => e.type === 'throw')).toBe(true);
    expect(g.heldCar).toBeNull();
    expect(g.cars[0].state).toBe('destroyed');
    expect(b.health).toBeLessThan(before);
  });

  it('second action throws the held car instead of grabbing another', () => {
    const g = createGame('x', 'bolt');
    start(g);
    g.player.x = g.cars[0].x;
    g.player.z = g.cars[0].z;
    grabThrow(g);
    g.player.x = g.cars[1].x;
    g.player.z = g.cars[1].z;
    grabThrow(g);
    expect(g.heldCar).toBeNull();
    expect(g.cars[0].state).toBe('destroyed');
    expect(g.cars[1].state).toBe('parked');
  });
});

describe('stomp cooldown', () => {
  it('stomp cooldown prevents double stomp', () => {
    const g = createGame('x', 'bolt');
    start(g);
    const b = g.buildings[0];
    g.player.x = b.x;
    g.player.z = b.z + 2;
    const first = stomp(g);
    expect(first.length).toBeGreaterThan(0);
    expect(stomp(g)).toEqual([]);
  });

  it('stomp damages buildings within 8', () => {
    const g = createGame('x', 'bolt');
    start(g);
    const b = g.buildings[0];
    g.player.x = b.x;
    g.player.z = b.z + 2;
    const before = b.health;
    stomp(g);
    expect(b.health).toBeLessThan(before);
  });
});

describe('start pause resume state machine', () => {
  it('start only from explore', () => {
    const g = createGame('x', 'bolt');
    start(g);
    expect(g.mode).toBe('playing');
    start(g); // no-op
    expect(g.mode).toBe('playing');
    expect(g.elapsed).toBe(0);
  });
});

describe('precise action contracts', () => {
  it('uses floors plus one health and legal claw reach beyond the collision radius', () => {
    const g = createGame('reach', 'bongo');
    for (const b of g.buildings) expect(b.maxHealth).toBe(b.floors + 1);
    start(g);
    const b = g.buildings[0];
    g.player.x = b.x - b.width / 2 - 3.7;
    g.player.z = b.z;
    const before = b.health;
    attack(g);
    expect(b.health).toBe(before - 1);
    expect(g.score).toBe(20);
  });

  it('a thrown car deals exactly four damage and scores its separate bonus', () => {
    const g = createGame('throw-damage', 'munch'); start(g);
    grabThrow(g);
    expect(g.heldCar).not.toBeNull();
    const b = g.buildings[0]; b.health = 6;
    g.player.x = b.x - b.width / 2 - 2;
    g.player.z = b.z;
    const events = grabThrow(g);
    expect(b.health).toBe(2);
    expect(b.destroyed).toBe(false);
    expect(g.score).toBe(95);
    expect(events.some(e => e.type === 'throw')).toBe(true);
  });

  it('exploration moves at the selected character speed without consuming round time', () => {
    const slow = createGame('speed', 'bongo');
    const fast = createGame('speed', 'bolt');
    tick(slow, .1, {x: 1, z: 0, attack: false});
    tick(fast, .1, {x: 1, z: 0, attack: false});
    expect(slow.player.x).toBeCloseTo(.42);
    expect(fast.player.x).toBeCloseTo(.6);
    expect(slow.remaining).toBe(45);
    expect(fast.remaining).toBe(45);
  });
});
