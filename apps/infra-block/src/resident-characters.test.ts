import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as THREE from 'three';
import { createResidentCrew } from './resident-characters';
import { RESIDENTS, demoPresence } from './residents';
import { createGame } from './game';

describe('ResidentCrew', () => {
  const allocatedCrews: ReturnType<typeof createResidentCrew>[] = [];
  const getBuildings = () => createGame('residents-proof', 'munch').buildings;

  beforeEach(() => {
    vi.stubGlobal('document', {
      createElement: (tag: string) => {
        if (tag === 'canvas') {
          return {
            width: 0,
            height: 0,
            getContext: () => ({
              fillStyle: '',
              strokeStyle: '',
              lineWidth: 0,
              font: '',
              textAlign: '',
              fillRect: vi.fn(),
              strokeRect: vi.fn(),
              fillText: vi.fn(),
            }),
          };
        }
        return {};
      },
    });
  });

  afterEach(() => {
    while (allocatedCrews.length > 0) {
      allocatedCrews.pop()?.dispose();
    }
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('instantiates 7 unique role actors and stations, with 14 pick targets under residentSlug roots', () => {
    const buildings = getBuildings();
    const crew = createResidentCrew(RESIDENTS, buildings, false);
    allocatedCrews.push(crew);

    expect(crew.pickTargets).toHaveLength(14);
    expect(crew.group.children.filter(child => child.userData.residentSlug)).toHaveLength(7);

    for (const def of RESIDENTS) {
      const root = crew.group.children.find((c) => c.userData.residentSlug === def.slug);
      expect(root).toBeDefined();
      expect(root?.name).toBe(`Resident_${def.slug}`);

      const actor = root?.children.find((c) => c.name === `Actor_${def.slug}`);
      const station = root?.children.find((c) => c.name === `Station_${def.slug}`);

      expect(actor).toBeDefined();
      expect(station).toBeDefined();
      expect(crew.pickTargets).toContain(actor);
      expect(crew.pickTargets).toContain(station);
    }
  });

  it('normalizes each actor height to 4.2 units using Box3', () => {
    const buildings = getBuildings();
    const crew = createResidentCrew(RESIDENTS, buildings, false);
    allocatedCrews.push(crew);

    for (const def of RESIDENTS) {
      const actor = crew.pickTargets.find((t) => t.name === `Actor_${def.slug}`) as THREE.Group;
      const box = new THREE.Box3().setFromObject(actor);
      const size = box.getSize(new THREE.Vector3());
      expect(size.y).toBeCloseTo(4.2, 1);
    }
  });

  it('keeps all actors static at default unknown presence across 60 updates', () => {
    const buildings = getBuildings();
    const crew = createResidentCrew(RESIDENTS, buildings, false);
    allocatedCrews.push(crew);

    const initialPositions = RESIDENTS.map((def) => {
      const actor = crew.pickTargets.find((t) => t.name === `Actor_${def.slug}`)!;
      return actor.position.clone();
    });

    for (let i = 0; i < 60; i++) {
      crew.update(0.016, 'explore');
    }

    RESIDENTS.forEach((def, idx) => {
      const actor = crew.pickTargets.find((t) => t.name === `Actor_${def.slug}`)!;
      expect(actor.position.x).toBe(initialPositions[idx].x);
      expect(actor.position.y).toBe(initialPositions[idx].y);
      expect(actor.position.z).toBe(initialPositions[idx].z);
    });
  });

  it('moves active demo actor with axis-aligned initial x-constant road movement while parking others', () => {
    const buildings = getBuildings();
    const crew = createResidentCrew(RESIDENTS, buildings, false);
    allocatedCrews.push(crew);

    const presence = demoPresence('cto');
    crew.setPresence(presence);

    const ctaActor = crew.pickTargets.find((t) => t.name === 'Actor_cto')!;
    const startPos = ctaActor.position.clone();

    crew.update(0.05, 'explore');

    expect(ctaActor.position.x).toBeCloseTo(startPos.x, 4);
    expect(ctaActor.position.z).not.toBe(startPos.z);

    const ceoActor = crew.pickTargets.find((t) => t.name === 'Actor_ceo')!;
    const ceoStart = ceoActor.position.clone();
    crew.update(0.05, 'explore');
    expect(ceoActor.position.equals(ceoStart)).toBe(true);
  });

  it('walks cardinal road segments aligned with the visible 10.4-unit grid', () => {
    const crew = createResidentCrew(RESIDENTS, getBuildings(), false);
    allocatedCrews.push(crew);
    crew.setPresence(demoPresence('cto'));
    const actor = crew.pickTargets.find(t => t.name === 'Actor_cto')!;
    const roads = [-20.8, -10.4, 0, 10.4, 20.8];
    let previous = actor.position.clone();
    let roadSamples = 0;
    for (let i = 0; i < 600; i++) {
      crew.update(0.1, 'explore');
      const dx = Math.abs(actor.position.x - previous.x);
      const dz = Math.abs(actor.position.z - previous.z);
      // A frame may straddle a junction; total travel must remain bounded.
      expect(dx + dz).toBeLessThanOrEqual(0.151);
      if (roads.some(v => Math.abs(actor.position.x - v) < 0.001 || Math.abs(actor.position.z - v) < 0.001)) roadSamples++;
      previous = actor.position.clone();
    }
    expect(roadSamples).toBeGreaterThan(300);
  });

  it('keeps all seven full demo routes outside building footprints and deterministic', () => {
    const buildings = getBuildings();
    for (const definition of RESIDENTS) {
      const crew = createResidentCrew(RESIDENTS, buildings, false);
      const twin = createResidentCrew(RESIDENTS, buildings, false);
      allocatedCrews.push(crew, twin);
      const presence = demoPresence(definition.slug);
      expect(presence.find(item => item.slug === definition.slug)).toMatchObject({
        state: 'active', evidence: 'demo', label: 'Demo walking',
      });
      crew.setPresence(presence);
      twin.setPresence(presence);
      const actor = crew.pickTargets.find(item => item.name === `Actor_${definition.slug}`)!;
      const twinActor = twin.pickTargets.find(item => item.name === `Actor_${definition.slug}`)!;
      const home = actor.position.clone();
      const parked = crew.pickTargets.filter(item => item.name.startsWith('Actor_') && item !== actor)
        .map(item => ({ item, position: item.position.clone() }));
      let travelled = 0;
      let returnedHome = false;
      let previous = home.clone();
      for (let frame = 0; frame < 2400; frame++) {
        crew.update(0.1, 'explore');
        twin.update(0.1, 'explore');
        expect(actor.position.equals(twinActor.position)).toBe(true);
        travelled += actor.position.distanceTo(previous);
        if (travelled > 30 && actor.position.distanceTo(home) < 0.2) returnedHome = true;
        previous.copy(actor.position);
        const collision = buildings.find(building =>
          Math.abs(actor.position.x - building.x) < building.width / 2 &&
          Math.abs(actor.position.z - building.z) < building.depth / 2);
        expect(collision?.id, `${definition.slug} frame ${frame} at ${actor.position.x},${actor.position.z}`).toBeUndefined();
      }
      expect(travelled).toBeGreaterThan(300);
      expect(returnedHome, `${definition.slug} should complete its closed route`).toBe(true);
      for (const { item, position } of parked) expect(item.position.equals(position)).toBe(true);
      crew.setPresence([]);
      expect(actor.position.equals(home)).toBe(true);
    }
  });

  it('manually explores all seven residents without changing presence and releases to home', () => {
    const crew = createResidentCrew(RESIDENTS, getBuildings(), true);
    allocatedCrews.push(crew);
    const presence = demoPresence('ceo');
    const evidence = JSON.stringify(presence);
    crew.setPresence(presence);
    for (const definition of RESIDENTS) {
      crew.controlResident(definition.slug);
      const initial = crew.controlState();
      expect(initial.slug).toBe(definition.slug);
      expect(initial.nearbySlug).toBe(definition.slug);
      let state = initial;
      for (let i = 0; i < 10; i++) state = crew.moveResident({ x: 1, z: 0 }, { x: 0, z: -1 }, 0.1);
      expect(state.x).not.toBe(initial.x);
      const stopped = crew.moveResident({ x: 0, z: 0 }, { x: 0, z: -1 }, 0.1);
      expect(stopped).toMatchObject({ slug: definition.slug, x: state.x, z: state.z, moving: false });
      crew.setPresence(presence);
      crew.update(0.1, 'explore');
      expect(crew.controlState().x).toBe(state.x);
      const actor = crew.pickTargets.find(item => item.name === `Actor_${definition.slug}`)!;
      const manuallyParked = actor.position.clone();
      crew.controlResident(null);
      expect(crew.controlState().slug).toBeNull();
      expect(actor.position.equals(manuallyParked)).toBe(false);
    }
    expect(JSON.stringify(presence)).toBe(evidence);
    crew.controlResident('unknown-agent');
    expect(crew.controlState().slug).toBeNull();
  });

  it('stops active movement and parks to home on authoritative empty presence', () => {
    const buildings = getBuildings();
    const crew = createResidentCrew(RESIDENTS, buildings, false);
    allocatedCrews.push(crew);

    crew.setPresence(demoPresence('cto'));
    crew.update(0.1, 'explore');

    const ctoActor = crew.pickTargets.find((t) => t.name === 'Actor_cto')!;
    crew.setPresence([]);

    const homePos = ctoActor.position.clone();
    crew.update(0.1, 'explore');

    expect(ctoActor.position.equals(homePos)).toBe(true);
  });

  it('toggles gate visibility and keeps actor parked at home on held state versus active', () => {
    const buildings = getBuildings();
    const crew = createResidentCrew(RESIDENTS, buildings, false);
    allocatedCrews.push(crew);

    const librarianRoot = crew.group.children.find((c) => c.userData.residentSlug === 'librarian')!;
    const station = librarianRoot.children.find((c) => c.name === 'Station_librarian')!;
    const actor = librarianRoot.children.find((c) => c.name === 'Actor_librarian')!;
    const gateMesh = station.children.find((c) => (c as THREE.Mesh).isMesh && c.rotation.z === Math.PI / 2)!;

    expect(gateMesh.visible).toBe(false);

    crew.setPresence([{
      slug: 'librarian',
      state: 'held',
      evidence: 'observed',
      label: 'Held',
      reason: 'Testing gate',
      recordId: null,
      observedAt: null,
    }]);

    expect(gateMesh.visible).toBe(true);
    const heldPos = actor.position.clone();
    crew.update(0.1, 'explore');
    expect(actor.position.equals(heldPos)).toBe(true);

    crew.setPresence([{
      slug: 'librarian',
      state: 'active',
      evidence: 'observed',
      label: 'Active',
      reason: 'Active now',
      recordId: null,
      observedAt: null,
    }]);

    expect(gateMesh.visible).toBe(false);
  });

  it('freezes active actor position changes when reducedMotion is enabled', () => {
    const buildings = getBuildings();
    const crew = createResidentCrew(RESIDENTS, buildings, true);
    allocatedCrews.push(crew);

    crew.setPresence(demoPresence('cto'));
    const ctoActor = crew.pickTargets.find((t) => t.name === 'Actor_cto')!;
    const initialPos = ctoActor.position.clone();

    crew.update(0.1, 'explore');
    expect(ctoActor.position.equals(initialPos)).toBe(true);
  });

  it('hides crew, freezes movement, and preserves game buildings in sandbox playing mode', () => {
    const game = createGame('residents-proof', 'munch');
    const buildingSnapshot = JSON.parse(JSON.stringify(game.buildings));
    const crew = createResidentCrew(RESIDENTS, game.buildings, false);
    allocatedCrews.push(crew);

    crew.setPresence(demoPresence('cto'));
    const ctoActor = crew.pickTargets.find((t) => t.name === 'Actor_cto')!;
    const initialPos = ctoActor.position.clone();

    crew.update(0.1, 'playing');

    expect(crew.group.visible).toBe(false);
    expect(ctoActor.position.equals(initialPos)).toBe(true);
    expect(game.buildings).toEqual(buildingSnapshot);
  });

  it('disposes all geometries, materials, and textures exactly once and removes group from parent scene', () => {
    const buildings = getBuildings();
    const scene = new THREE.Scene();
    const crew = createResidentCrew(RESIDENTS, buildings, false);

    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];
    const textures: THREE.Texture[] = [];

    crew.group.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        const mesh = obj as THREE.Mesh;
        if (mesh.geometry && !geometries.includes(mesh.geometry)) geometries.push(mesh.geometry);
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        for (const m of mats) {
          if (m && !materials.includes(m)) {
            materials.push(m);
            if ('map' in m && m.map && !textures.includes(m.map as THREE.Texture)) {
              textures.push(m.map as THREE.Texture);
            }
          }
        }
      }
    });

    const geoSpies = geometries.map((g) => vi.spyOn(g, 'dispose'));
    const matSpies = materials.map((m) => vi.spyOn(m, 'dispose'));
    const texSpies = textures.map((t) => vi.spyOn(t, 'dispose'));

    scene.add(crew.group);
    expect(crew.group.parent).toBe(scene);

    crew.dispose();

    expect(crew.group.parent).toBeNull();
    expect(crew.pickTargets).toHaveLength(0);

    for (const spy of geoSpies) expect(spy).toHaveBeenCalledTimes(1);
    for (const spy of matSpies) expect(spy).toHaveBeenCalledTimes(1);
    for (const spy of texSpies) expect(spy).toHaveBeenCalledTimes(1);
  });
});
