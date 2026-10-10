import {
  Layer,
  InfraNode,
  CharacterId,
  BuildingState,
  CarState,
  GameState,
  WorldEvent,
  InputState,
} from './contracts';
import { nodes } from './data';

// ---------- Configuration ----------
const BUILDING_IDS: string[] = nodes.map((n) => n.id);
const BUILDING_POSITIONS: { x: number; z: number }[] = (() => {
  const centers = [-15.6, -5.2, 5.2, 15.6];
  const result: { x: number; z: number }[] = [];
  for (const z of centers) {
    for (const x of centers) {
      result.push({ x, z });
    }
  }
  return result.slice(0, 16);
})();

const CHARACTER_SPEEDS: Record<CharacterId, number> = {
  munch: 5,
  bongo: 4.2,
  bolt: 6,
};

const CHARACTER_RADII: Record<CharacterId, number> = {
  munch: 1.05,
  bongo: 1.2,
  bolt: 0.9,
};

const PLAYER_BOUND = 23;
const ATTACK_COOLDOWN = 0.42;
const COMBO_EXPIRY = 3.5;
const STOMP_COOLDOWN = 7;
const STOMP_DAMAGE = 3;
const STOMP_RANGE = 8;
const GRAB_RANGE = 3.4;
const THROW_DAMAGE = 4;
const THROW_RANGE = 10;
const ATTACK_RANGE = 3.8;
const ATTACK_DAMAGE = 1;
const MAX_MULTIPLIER = 5;
const BASE_DEMOLISH_POINTS = 180;
const HEIGHT_POINT_MULTIPLIER = 50;
const CAR_BONUS_MULTIPLIER = 75;
const HIT_SCORE_ADD = 20;
const INITIAL_TIMER = 45;
const MIN_FLOORS = 2;
const MAX_FLOORS = 5;
const MIN_WIDTH = 5;
const MAX_WIDTH = 6;
const MIN_DEPTH = 5;
const MAX_DEPTH = 6;
const HEIGHT_PER_FLOOR = 1.5;
const HEALTH_PER_FLOOR = 1.13;
const SPAWN_X = 0;
const SPAWN_Z = 10.4;
const FIRST_CAR_GUARANTEE_INDEX = 2;
const FIRST_CAR_GUARANTEE_Z = 10.4;

// ---------- Utility Functions ----------
function seededRandom(seed: string): () => number {
  let s = 0;
  for (let i = 0; i < seed.length; i++) {
    s = (s * 31 + seed.charCodeAt(i)) & 0x7fffffff;
  }
  return function () {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function circleAABBNearestPoint(
  circleX: number,
  circleZ: number,
  radius: number,
  rectX: number,
  rectZ: number,
  width: number,
  depth: number
): { x: number; z: number; distance: number } {
  const halfW = width / 2;
  const halfD = depth / 2;
  const nearestX = clamp(circleX, rectX - halfW, rectX + halfW);
  const nearestZ = clamp(circleZ, rectZ - halfD, rectZ + halfD);
  const dx = circleX - nearestX;
  const dz = circleZ - nearestZ;
  const distance = Math.sqrt(dx * dx + dz * dz);
  return { x: nearestX, z: nearestZ, distance };
}

function distance(a: { x: number; z: number }, b: { x: number; z: number }): number {
  const dx = a.x - b.x;
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dz * dz);
}

function edgeDistance(
  px: number,
  pz: number,
  bx: number,
  bz: number,
  width: number,
  depth: number
): number {
  const nearest = circleAABBNearestPoint(px, pz, 0, bx, bz, width, depth);
  return distance({ x: px, z: pz }, { x: nearest.x, z: nearest.z });
}

// ---------- Game State Management ----------
const internalWeakMap = new WeakMap<GameState, { attackCooldown: number; lastDemolition: number }>();

function ensureInternal(state: GameState): { attackCooldown: number; lastDemolition: number } {
  if (!internalWeakMap.has(state)) {
    internalWeakMap.set(state, { attackCooldown: 0, lastDemolition: 0 });
  }
  return internalWeakMap.get(state)!;
}

function resetComboOnTimeout(state: GameState): void {
  if (state.combo > 0 && state.elapsed - ensureInternal(state).lastDemolition >= COMBO_EXPIRY) {
    state.combo = 0;
    state.multiplier = 1;
  }
}

function resetTimerPrecisely(state: GameState): void {
  state.remaining = 0;
}

function isPlayerInBounds(x: number, z: number): boolean {
  return Math.abs(x) <= PLAYER_BOUND && Math.abs(z) <= PLAYER_BOUND;
}

function generateBuildings(seed: string): BuildingState[] {
  const rng = seededRandom(seed);
  return BUILDING_IDS.map((id, index) => {
    const pos = BUILDING_POSITIONS[index % BUILDING_POSITIONS.length];
    const width = MIN_WIDTH + Math.floor(rng() * (MAX_WIDTH - MIN_WIDTH + 1));
    const depth = MIN_DEPTH + Math.floor(rng() * (MAX_DEPTH - MIN_DEPTH + 1));
    const floors = MIN_FLOORS + Math.floor(rng() * (MAX_FLOORS - MIN_FLOORS + 1));
    const height = floors * HEIGHT_PER_FLOOR;
    const maxHealth = floors + 1;
    return {
      id,
      x: pos.x,
      z: pos.z,
      width,
      depth,
      height,
      floors,
      health: maxHealth,
      maxHealth,
      destroyed: false,
    };
  });
}

function generateCars(seed: string): CarState[] {
  const rng = seededRandom(seed + 'cars');
  const roads = [[2,10.4],[-20.8,-15.6],[20.8,-5.2],[-10.4,-20.8],[10.4,-20.8],[-20.8,5.2],[20.8,15.6],[-10.4,20.8],[10.4,20.8],[0,-10.4],[-10.4,0],[10.4,0],[0,20.8]];
  return roads.map(([x,z],id) => ({ id, x: id ? x + (rng() - .5) * .2 : x, z: id ? z + (rng() - .5) * .2 : z, state: 'parked' }));
}

export function createGame(seed: string, character: CharacterId): GameState {
  const state: GameState = {
    mode: 'explore',
    seed,
    character,
    player: {
      x: SPAWN_X,
      z: SPAWN_Z,
      angle: 0,
    },
    buildings: generateBuildings(seed),
    cars: generateCars(seed),
    score: 0,
    remaining: INITIAL_TIMER,
    destroyed: 0,
    combo: 0,
    bestCombo: 0,
    multiplier: 1,
    stompCooldown: 0,
    heldCar: null,
    elapsed: 0,
  };
  internalWeakMap.set(state, { attackCooldown: 0, lastDemolition: 0 });
  return state;
}

// ---------- Movement and Collision ----------
function canMove(state: GameState, newX: number, newZ: number): boolean {
  const limit = PLAYER_BOUND - CHARACTER_RADII[state.character];
  if (Math.abs(newX) > limit || Math.abs(newZ) > limit) {
    return false;
  }
  const radius = CHARACTER_RADII[state.character];
  for (const building of state.buildings) {
    if (building.destroyed) continue;
    const nearest = circleAABBNearestPoint(newX, newZ, radius, building.x, building.z, building.width, building.depth);
    const dx = newX - nearest.x;
    const dz = newZ - nearest.z;
    const distSq = dx * dx + dz * dz;
    if (distSq < radius * radius) {
      return false;
    }
  }
  return true;
}

function applyMovement(state: GameState, input: InputState, dt: number): void {
  const speed = CHARACTER_SPEEDS[state.character];
  const ix = Number.isFinite(input.x) ? input.x : 0;
  const iz = Number.isFinite(input.z) ? input.z : 0;
  const length = Math.max(1, Math.hypot(ix, iz));
  const moveX = ix / length * speed * dt;
  const moveZ = iz / length * speed * dt;

  let newX = state.player.x;
  let newZ = state.player.z;

  // Move along x-axis first
  newX += moveX;
  if (canMove(state, newX, state.player.z)) {
    state.player.x = newX;
  } else {
    newX = state.player.x;
  }

  // Then move along z-axis
  newZ += moveZ;
  if (canMove(state, state.player.x, newZ)) {
    state.player.z = newZ;
  } else {
    newZ = state.player.z;
  }

  // Update angle based on movement direction
  if (ix !== 0 || iz !== 0) {
    state.player.angle = Math.atan2(ix, iz);
  }
}

// ---------- Game Actions ----------
function findNearestBuilding(state: GameState, x: number, z: number): BuildingState | null {
  let nearest: BuildingState | null = null;
  let minDistance = Infinity;
  for (const building of state.buildings) {
    if (building.destroyed) continue;
    const dist = edgeDistance(x, z, building.x, building.z, building.width, building.depth);
    if (dist < minDistance) {
      minDistance = dist;
      nearest = building;
    }
  }
  return nearest;
}

function findNearestCar(state: GameState, x: number, z: number): CarState | null {
  let nearest: CarState | null = null;
  let minDistance = Infinity;
  for (const car of state.cars) {
    if (car.state === 'parked') {
      const dist = distance({ x, z }, { x: car.x, z: car.z });
      if (dist < minDistance) {
        minDistance = dist;
        nearest = car;
      }
    }
  }
  return nearest;
}

function findClosestParkedCar(state: GameState, x: number, z: number): CarState | null {
  return findNearestCar(state, x, z);
}

export function attack(state: GameState): WorldEvent[] {
  const events: WorldEvent[] = [];
  const internal = ensureInternal(state);

  if (state.mode !== 'playing' || internal.attackCooldown > 0) {
    return events;
  }

  const nearest = findNearestBuilding(state, state.player.x, state.player.z);
  if (nearest && edgeDistance(state.player.x, state.player.z, nearest.x, nearest.z, nearest.width, nearest.depth) <= ATTACK_RANGE) {
    nearest.health -= ATTACK_DAMAGE;
    state.score += HIT_SCORE_ADD * state.multiplier;
    events.push({
      type: 'hit',
      x: state.player.x,
      z: state.player.z,
      id: nearest.id,
    });

    if (nearest.health <= 0) {
      nearest.destroyed = true;
      state.destroyed++;
      state.combo++;
      state.multiplier = Math.min(state.combo, MAX_MULTIPLIER);
      if (state.combo > state.bestCombo) {
        state.bestCombo = state.combo;
      }
      internal.lastDemolition = state.elapsed;
      state.score += Math.round(BASE_DEMOLISH_POINTS + nearest.height * HEIGHT_POINT_MULTIPLIER) * state.multiplier;
      events.push({
        type: 'demolish',
        x: nearest.x,
        z: nearest.z,
        value: Math.round(BASE_DEMOLISH_POINTS + nearest.height * HEIGHT_POINT_MULTIPLIER) * state.multiplier,
        id: nearest.id,
      });
    }
  }

  internal.attackCooldown = ATTACK_COOLDOWN;
  return events;
}

export function stomp(state: GameState): WorldEvent[] {
  const events: WorldEvent[] = [];
  if (state.mode !== 'playing' || state.stompCooldown > 0) {
    return events;
  }

  state.stompCooldown = STOMP_COOLDOWN;
  let hitAny = false;

  for (const building of state.buildings) {
    if (building.destroyed) continue;
    const dist = edgeDistance(state.player.x, state.player.z, building.x, building.z, building.width, building.depth);
    if (dist <= STOMP_RANGE) {
      building.health -= STOMP_DAMAGE;
      state.score += HIT_SCORE_ADD * state.multiplier;
      events.push({
        type: 'hit',
        x: state.player.x,
        z: state.player.z,
        id: building.id,
      });

      if (building.health <= 0) {
        building.destroyed = true;
        state.destroyed++;
        state.combo++;
        state.multiplier = Math.min(state.combo, MAX_MULTIPLIER);
        if (state.combo > state.bestCombo) {
          state.bestCombo = state.combo;
        }
        ensureInternal(state).lastDemolition = state.elapsed;
        state.score += Math.round(BASE_DEMOLISH_POINTS + building.height * HEIGHT_POINT_MULTIPLIER) * state.multiplier;
        events.push({
          type: 'demolish',
          x: building.x,
          z: building.z,
          value: Math.round(BASE_DEMOLISH_POINTS + building.height * HEIGHT_POINT_MULTIPLIER) * state.multiplier,
          id: building.id,
        });
      }
      hitAny = true;
    }
  }

  if (hitAny) {
    events.push({
      type: 'stomp',
      x: state.player.x,
      z: state.player.z,
    });
  }

  return events;
}

export function grabThrow(state: GameState): WorldEvent[] {
  const events: WorldEvent[] = [];
  if (state.mode !== 'playing') {
    return events;
  }

  if (state.heldCar === null) {
    // Try to grab
    const nearest = findClosestParkedCar(state, state.player.x, state.player.z);
    if (nearest && distance({ x: state.player.x, z: state.player.z }, { x: nearest.x, z: nearest.z }) <= GRAB_RANGE) {
      nearest.state = 'held';
      state.heldCar = nearest.id;
      events.push({
        type: 'grab',
        x: nearest.x,
        z: nearest.z,
        id: nearest.id.toString(),
      });
    }
  } else {
    // Throw
    const heldCar = state.cars.find((c) => c.id === state.heldCar);
    if (heldCar) {
      const nearest = findNearestBuilding(state, state.player.x, state.player.z);
      const eventsFromThrow: WorldEvent[] = [];

      if (nearest && edgeDistance(state.player.x, state.player.z, nearest.x, nearest.z, nearest.width, nearest.depth) <= THROW_RANGE) {
        nearest.health -= THROW_DAMAGE;
        state.score += HIT_SCORE_ADD * state.multiplier;
        eventsFromThrow.push({
          type: 'hit',
          x: nearest.x,
          z: nearest.z,
          id: nearest.id,
        });

        if (nearest.health <= 0) {
          nearest.destroyed = true;
          state.destroyed++;
          state.combo++;
          state.multiplier = Math.min(state.combo, MAX_MULTIPLIER);
          if (state.combo > state.bestCombo) {
            state.bestCombo = state.combo;
          }
          ensureInternal(state).lastDemolition = state.elapsed;
          state.score += Math.round(BASE_DEMOLISH_POINTS + nearest.height * HEIGHT_POINT_MULTIPLIER) * state.multiplier;
          eventsFromThrow.push({
            type: 'demolish',
            x: nearest.x,
            z: nearest.z,
            value: Math.round(BASE_DEMOLISH_POINTS + nearest.height * HEIGHT_POINT_MULTIPLIER) * state.multiplier,
            id: nearest.id,
          });
        }
      }

      heldCar.state = 'destroyed';
      state.score += CAR_BONUS_MULTIPLIER * state.multiplier;
      state.heldCar = null;
      events.push(...eventsFromThrow);
      events.push({
        type: 'throw',
        x: state.player.x,
        z: state.player.z,
      });
    } else {
      // No valid target - consume car as miss
      const car = state.cars.find((c) => c.id === state.heldCar);
      if (car) {
        car.state = 'destroyed';
      }
      state.heldCar = null;
      events.push({
        type: 'miss',
        x: state.player.x,
        z: state.player.z,
      });
    }
  }

  return events;
}

export function start(state: GameState): void {
  if (state.mode !== 'explore') {
    return;
  }
  state.mode = 'playing';
  state.multiplier = 1;
  state.combo = 0;
  state.score = 0;
  state.destroyed = 0;
  state.remaining = INITIAL_TIMER;
  state.elapsed = 0;
  state.stompCooldown = 0;
  state.heldCar = null;
  internalWeakMap.set(state, { attackCooldown: 0, lastDemolition: 0 });
}

export function pause(state: GameState): void {
  if (state.mode !== 'playing') {
    return;
  }
  state.mode = 'paused';
}

export function resume(state: GameState): void {
  if (state.mode !== 'paused') {
    return;
  }
  state.mode = 'playing';
}

// ---------- Tick Function ----------
function checkResultCondition(state: GameState): boolean {
  return state.destroyed >= state.buildings.length || state.remaining <= 0;
}

export function tick(state: GameState, dt: number, input: InputState): WorldEvent[] {
  const events: WorldEvent[] = [];
  const internal = ensureInternal(state);
  const clampedDt = Number.isFinite(dt) ? clamp(dt, 0, 0.1) : 0;

  if (state.mode === 'explore') { applyMovement(state, input, clampedDt); return events; }

  if (state.mode === 'playing') {
    // Movement
    applyMovement(state, input, clampedDt);

    // Timer
    state.remaining -= clampedDt;
    if (state.remaining <= 0) {
      resetTimerPrecisely(state);
    }

    // Elapsed time
    state.elapsed += clampedDt;

    // Cooldowns
    if (internal.attackCooldown > 0) {
      internal.attackCooldown -= clampedDt;
      if (internal.attackCooldown < 0) {
        internal.attackCooldown = 0;
      }
    }

    if (state.stompCooldown > 0) {
      state.stompCooldown -= clampedDt;
      if (state.stompCooldown < 0) {
        state.stompCooldown = 0;
      }
    }

    // Reset combo on timeout
    resetComboOnTimeout(state);

    if (!checkResultCondition(state) && input.attack) events.push(...attack(state));

    // Check result condition
    if (checkResultCondition(state)) {
      state.mode = 'result';
      events.push({
        type: 'result',
        x: state.player.x,
        z: state.player.z,
      });
    }
  }

  return events;
}
