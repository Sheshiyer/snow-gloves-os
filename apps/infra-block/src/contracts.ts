export type Layer = 'strategy' | 'knowledge' | 'orchestration' | 'governance' | 'runtime';
export interface InfraNode {
  id: string; name: string; short: string; layer: Layer; color: string;
  summary: string; detail: string; sources: string[]; links: string[];
  evidence: 'source' | 'local' | 'pending'; evidenceNote: string;
}
export type CharacterId = 'munch' | 'bongo' | 'bolt';
export interface BuildingState { id: string; x: number; z: number; width: number; depth: number; height: number; floors: number; health: number; maxHealth: number; destroyed: boolean; }
export interface CarState { id: number; x: number; z: number; state: 'parked' | 'held' | 'airborne' | 'destroyed'; }
export interface GameState {
  mode: 'explore' | 'playing' | 'paused' | 'result'; seed: string; character: CharacterId;
  player: { x: number; z: number; angle: number }; buildings: BuildingState[]; cars: CarState[];
  /** remaining is active ROUND TIME in seconds; buildings use IDs from data.nodes. */
  score: number; remaining: number; destroyed: number; combo: number; bestCombo: number;
  multiplier: number; stompCooldown: number; heldCar: number | null; elapsed: number;
}
export interface WorldEvent { type: 'hit' | 'demolish' | 'stomp' | 'grab' | 'throw' | 'miss' | 'result'; x: number; z: number; value?: number; id?: string; }
/** Reversible local exploration. This is never evidence of an infrastructure job. */
export interface CrewControlState {
  slug: string | null; x: number; z: number; moving: boolean; nearbySlug: string | null;
}
export interface WorldController {
  update(state: GameState, dt: number): void; event(event: WorldEvent): void;
  select(id: string | null): void; filter(layer: Layer | 'all'): void;
  route(ids: string[]): void; reset(state: GameState): void; dispose(): void;
  controlResident(slug: string | null): void;
  moveResident(x: number, z: number, dt: number): CrewControlState;
  setGraphics(profile: 'balanced' | 'eco'): void;
}
export interface InputState { x: number; z: number; attack: boolean; }
