import type { BuildingState } from './contracts';

export type CrewPoint = { x: number; z: number };

const SPEED = 6.0;
const RADIUS = 1.2;
const PLATFORM_MAX = 25.3 - RADIUS;
const MAX_MICROSTEP = 0.1;

function isFinitePoint(p: CrewPoint): boolean {
  return Number.isFinite(p.x) && Number.isFinite(p.z);
}

function isInsideBuilding(pos: CrewPoint, b: BuildingState): boolean {
  const hw = (b.width ?? 0) / 2 + RADIUS;
  const hd = (b.depth ?? 0) / 2 + RADIUS;
  return (
    pos.x >= b.x - hw &&
    pos.x <= b.x + hw &&
    pos.z >= b.z - hd &&
    pos.z <= b.z + hd
  );
}

function isSafe(pos: CrewPoint, buildings: readonly BuildingState[]): boolean {
  if (!isFinitePoint(pos)) return false;
  if (Math.abs(pos.x) > PLATFORM_MAX || Math.abs(pos.z) > PLATFORM_MAX) return false;
  for (let i = 0; i < buildings.length; i++) {
    if (isInsideBuilding(pos, buildings[i]!)) return false;
  }
  return true;
}

export function safeCrewHome(home: CrewPoint, buildings: readonly BuildingState[]): CrewPoint {
  const start: CrewPoint = {
    x: Number.isFinite(home.x) ? Math.max(-PLATFORM_MAX, Math.min(PLATFORM_MAX, home.x)) : 0,
    z: Number.isFinite(home.z) ? Math.max(-PLATFORM_MAX, Math.min(PLATFORM_MAX, home.z)) : 0,
  };
  if (isSafe(start, buildings)) return start;

  for (let r = 0.5; r <= 15.0; r += 0.5) {
    const steps = Math.max(8, Math.round(2 * Math.PI * r * 2));
    for (let i = 0; i < steps; i++) {
      const angle = (i * 2 * Math.PI) / steps;
      const cand: CrewPoint = {
        x: Math.max(-PLATFORM_MAX, Math.min(PLATFORM_MAX, start.x + Math.cos(angle) * r)),
        z: Math.max(-PLATFORM_MAX, Math.min(PLATFORM_MAX, start.z + Math.sin(angle) * r)),
      };
      if (isSafe(cand, buildings)) return cand;
    }
  }

  for (let x = -PLATFORM_MAX; x <= PLATFORM_MAX; x += 1.0) {
    for (let z = -PLATFORM_MAX; z <= PLATFORM_MAX; z += 1.0) {
      const cand = { x, z };
      if (isSafe(cand, buildings)) return cand;
    }
  }
  return { x: 0, z: 0 };
}

export function navigateCrew(
  position: CrewPoint,
  input: CrewPoint,
  cameraForward: CrewPoint,
  dt: number,
  buildings: readonly BuildingState[]
): CrewPoint {
  if (!isFinitePoint(position)) return { x: 0, z: 0 };
  const safeDt = Number.isFinite(dt) ? Math.max(0, Math.min(0.1, dt)) : 0;
  if (safeDt <= 0) return { x: position.x, z: position.z };

  const inX = Number.isFinite(input.x) ? input.x : 0;
  const inZ = Number.isFinite(input.z) ? input.z : 0;
  const inMag = Math.hypot(inX, inZ);
  if (inMag < 1e-6) return { x: position.x, z: position.z };

  const scale = Math.min(1, inMag) / inMag;
  const normInX = inX * scale;
  const normInZ = inZ * scale;

  let fX = Number.isFinite(cameraForward.x) ? cameraForward.x : 0;
  let fZ = Number.isFinite(cameraForward.z) ? cameraForward.z : -1;
  const fMag = Math.hypot(fX, fZ);
  if (fMag < 1e-6) {
    fX = 0;
    fZ = -1;
  } else {
    fX /= fMag;
    fZ /= fMag;
  }

  const rX = -fZ;
  const rZ = fX;

  const moveX = (fX * normInZ + rX * normInX) * SPEED * safeDt;
  const moveZ = (fZ * normInZ + rZ * normInX) * SPEED * safeDt;
  const totalDist = Math.hypot(moveX, moveZ);
  if (totalDist < 1e-6) return { x: position.x, z: position.z };

  const microsteps = Math.max(1, Math.ceil(totalDist / MAX_MICROSTEP));
  const stepX = moveX / microsteps;
  const stepZ = moveZ / microsteps;

  let curX = position.x;
  let curZ = position.z;

  for (let s = 0; s < microsteps; s++) {
    const nextX = Math.max(-PLATFORM_MAX, Math.min(PLATFORM_MAX, curX + stepX));
    if (isSafe({ x: nextX, z: curZ }, buildings)) {
      curX = nextX;
    }
    const nextZ = Math.max(-PLATFORM_MAX, Math.min(PLATFORM_MAX, curZ + stepZ));
    if (isSafe({ x: curX, z: nextZ }, buildings)) {
      curZ = nextZ;
    }
  }

  return { x: curX, z: curZ };
}

