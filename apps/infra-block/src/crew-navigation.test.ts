import { describe, it, expect } from 'vitest';
import { createGame } from './game';
import { RESIDENTS } from './residents';
import { navigateCrew, safeCrewHome, type CrewPoint } from './crew-navigation';
import type { BuildingState } from './contracts';

const PLATFORM_MAX = 25.3 - 1.2;

describe('crew-navigation', () => {
  const game = createGame('crew-test', 'munch');
  const buildings = game.buildings;
  const baseBuilding = buildings[0]!;

  it('rotates basis: forward (1,0) gives W->+x, D->+z', () => {
    const forward: CrewPoint = { x: 1, z: 0 };
    const origin: CrewPoint = { x: 0, z: 0 };
    const movedW = navigateCrew(origin, { x: 0, z: 1 }, forward, 0.1, []);
    expect(movedW.x).toBeCloseTo(0.6, 4);
    expect(movedW.z).toBeCloseTo(0, 4);

    const movedD = navigateCrew(origin, { x: 1, z: 0 }, forward, 0.1, []);
    expect(movedD.x).toBeCloseTo(0, 4);
    expect(movedD.z).toBeCloseTo(0.6, 4);
  });

  it('normalizes diagonals to identical speed', () => {
    const forward: CrewPoint = { x: 0, z: -1 };
    const origin: CrewPoint = { x: 0, z: 0 };
    const cardinal = navigateCrew(origin, { x: 0, z: 1 }, forward, 0.1, []);
    const diagonal = navigateCrew(origin, { x: 1, z: 1 }, forward, 0.1, []);
    const distCard = Math.hypot(cardinal.x - origin.x, cardinal.z - origin.z);
    const distDiag = Math.hypot(diagonal.x - origin.x, diagonal.z - origin.z);
    expect(distDiag).toBeCloseTo(distCard, 4);
  });

  it('handles static inputs and dt bounds', () => {
    const pos: CrewPoint = { x: 5, z: 5 };
    const fwd: CrewPoint = { x: 0, z: -1 };
    expect(navigateCrew(pos, { x: 0, z: 0 }, fwd, 0.1, [])).toEqual(pos);
    expect(navigateCrew(pos, { x: 1, z: 0 }, fwd, 0, [])).toEqual(pos);
    expect(navigateCrew(pos, { x: 1, z: 0 }, fwd, -1, [])).toEqual(pos);
    const clampedDt = navigateCrew(pos, { x: 0, z: 1 }, fwd, 100, []);
    expect(Math.hypot(clampedDt.x - pos.x, clampedDt.z - pos.z)).toBeCloseTo(0.6, 4);
  });

  it('slides along walls and prevents tunneling on huge dt', () => {
    const wallBuilding: BuildingState = {
      ...baseBuilding,
      id: 'test-wall',
      x: 0,
      z: 0,
      width: 4,
      depth: 4,
    };
    const startPos: CrewPoint = { x: 0, z: 3.25 };
    const intoWall = navigateCrew(startPos, { x: 0, z: 1 }, { x: 0, z: -1 }, 0.1, [wallBuilding]);
    expect(intoWall.z).toBe(startPos.z);

    const slide = navigateCrew(startPos, { x: 1, z: 1 }, { x: 0, z: -1 }, 0.1, [wallBuilding]);
    expect(slide.z).toBe(startPos.z);
    expect(slide.x).toBeGreaterThan(startPos.x);

    const fastTunnel = navigateCrew({ x: 0, z: 4.0 }, { x: 0, z: 1 }, { x: 0, z: -1 }, 10, [wallBuilding]);
    expect(fastTunnel.z).toBeGreaterThanOrEqual(2 + 1.2);
  });

  it('respects platform outer edges', () => {
    const nearEdge: CrewPoint = { x: PLATFORM_MAX - 0.1, z: 0 };
    const pushed = navigateCrew(nearEdge, { x: 1, z: 0 }, { x: 0, z: -1 }, 0.1, []);
    expect(pushed.x).toBeCloseTo(PLATFORM_MAX, 4);
  });

  it('computes safe deterministic homes for all 7 residents', () => {
    expect(RESIDENTS.length).toBe(7);
    for (let i = 0; i < RESIDENTS.length; i++) {
      const b = buildings.find(building => building.id === RESIDENTS[i].nodeId)!;
      const rawCorner: CrewPoint = {
        x: Math.max(-24, Math.min(24, b.x + b.width / 2 + 1.7 - 0.8)),
        z: Math.max(-24, Math.min(24, b.z + b.depth / 2 + 1.7 + 0.3)),
      };
      const safe1 = safeCrewHome(rawCorner, buildings);
      const safe2 = safeCrewHome(rawCorner, buildings);
      expect(safe1).toEqual(safe2);
      let walked = safe1;
      const inputs = [{ x: 1, z: 0 }, { x: 0, z: 1 }, { x: -1, z: 0 }, { x: 0, z: -1 }, { x: 1, z: 1 }];
      for (let frame = 0; frame < 600; frame++) {
        walked = navigateCrew(walked, inputs[Math.floor(frame / 60) % inputs.length], { x: 0.6, z: -0.8 }, 0.1, buildings);
        expect(Math.abs(walked.x)).toBeLessThanOrEqual(PLATFORM_MAX);
        expect(Math.abs(walked.z)).toBeLessThanOrEqual(PLATFORM_MAX);
        for (const obstacle of buildings) {
          expect(Math.abs(walked.x - obstacle.x) <= obstacle.width / 2 + 1.2 && Math.abs(walked.z - obstacle.z) <= obstacle.depth / 2 + 1.2).toBe(false);
        }
      }
      for (const bld of buildings) {
        const hw = bld.width / 2 + 1.2;
        const hd = bld.depth / 2 + 1.2;
        const inside = safe1.x >= bld.x - hw && safe1.x <= bld.x + hw && safe1.z >= bld.z - hd && safe1.z <= bld.z + hd;
        expect(inside).toBe(false);
      }
    }
  });
});

