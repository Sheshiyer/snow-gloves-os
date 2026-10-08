import { describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import { createBrandMarkers, mountBrandAtlas, type BrandTenant } from './brand-atlas.js';
import { parseBrandSummary } from './brand-summary.js';

const validKnowledge = {
  registeredSources: 1,
  admittedSources: 2,
  contextFiles: 3,
  plannedFiles: 4,
  presentFiles: 5,
  missingFiles: 6,
  rejectedFiles: 7,
  researchFiles: 8,
  researchVerified: 9,
  researchMissing: 10,
  researchDrift: 11,
  researchRejected: 12,
  status: 'source-plan-only',
  provenanceStatus: 'verified',
};

const validPlanning = {
  parent: 'acme-parent',
  relationship: 'portfolio',
  authority: 'planning-only',
  status: 'planning_not_provisioned',
  projects: [{ id: 'p-1', name: 'Launch', status: 'planning_not_provisioned' }],
  desks: ['editorial', 'creative-production', 'delivery', 'growth'],
  flows: [{ id: 'f-1', status: 'proposed_not_approved' }],
  sources: ['data:tenant:acme:planning'],
};

function expectParseError(run: () => unknown, fragment: string): void {
  try {
    run();
    throw new Error('expected parse failure');
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain(fragment);
  }
}

describe('parseBrandSummary', () => {
  it('parses valid knowledge and planning subset', () => {
    const parsed = parseBrandSummary({ knowledge: validKnowledge, planning: validPlanning });
    expect(parsed.knowledge?.plannedFiles).toBe(4);
    expect(parsed.planning?.sources[0]).toBe('data:tenant:acme:planning');
    expect(parsed.planning?.desks).toEqual(['editorial', 'creative-production', 'delivery', 'growth']);

    const knowledgeOnly = parseBrandSummary({ knowledge: validKnowledge });
    expect(knowledgeOnly.knowledge?.status).toBe('source-plan-only');
    expect(knowledgeOnly.planning).toBeUndefined();

    const planningOnly = parseBrandSummary({ planning: validPlanning });
    expect(planningOnly.planning?.authority).toBe('planning-only');
    expect(planningOnly.knowledge).toBeUndefined();
  });

  it('allows empty project name up to 128 characters', () => {
    const parsed = parseBrandSummary({
      planning: {
        ...validPlanning,
        projects: [{ id: 'p-empty', name: '', status: 'planning_not_provisioned' }],
      },
    });
    expect(parsed.planning?.projects[0].name).toBe('');
  });

  it('rejects malformed knowledge counts and enums', () => {
    expectParseError(
      () => parseBrandSummary({ knowledge: { ...validKnowledge, plannedFiles: -1 } }),
      'plannedFiles',
    );
    expectParseError(
      () => parseBrandSummary({ knowledge: { ...validKnowledge, plannedFiles: 100001 } }),
      'plannedFiles',
    );
    expectParseError(
      () =>
        parseBrandSummary({
          knowledge: { ...validKnowledge, status: 'source_plan_not_completed' },
        }),
      'knowledge.status',
    );
    expectParseError(
      () =>
        parseBrandSummary({
          knowledge: { ...validKnowledge, provenanceStatus: 'unknown' },
        }),
      'provenanceStatus',
    );
    expectParseError(
      () => parseBrandSummary({ knowledge: { ...validKnowledge, extra: 1 } }),
      'unexpected key',
    );
  });

  it('rejects malformed planning bounds, arrays, slugs, desks and source labels', () => {
    expectParseError(
      () =>
        parseBrandSummary({
          planning: {
            ...validPlanning,
            projects: [{ id: 'x'.repeat(65), name: 'n', status: 'planning_not_provisioned' }],
          },
        }),
      'planning.projects[0].id',
    );
    expectParseError(
      () =>
        parseBrandSummary({
          planning: {
            ...validPlanning,
            projects: [{ id: 'INVALID_SLUG', name: 'n', status: 'planning_not_provisioned' }],
          },
        }),
      'planning.projects[0].id',
    );
    expectParseError(
      () =>
        parseBrandSummary({
          planning: {
            ...validPlanning,
            flows: Array.from({ length: 129 }, (_, i) => ({ id: `f-${i}`, status: 'proposed_not_approved' })),
          },
        }),
      'planning.flows: maximum 128',
    );
    expectParseError(
      () =>
        parseBrandSummary({
          planning: {
            ...validPlanning,
            desks: [{ id: 'editorial' }] as unknown as string[],
          },
        }),
      'planning.desks[0]',
    );
    expectParseError(
      () =>
        parseBrandSummary({
          planning: {
            ...validPlanning,
            flows: [{ id: 'f-1', status: 'approved' }],
          },
        }),
      'flows[0].status',
    );
    expectParseError(
      () =>
        parseBrandSummary({
          planning: { ...validPlanning, sources: ['data:tenant:acme:wrong'] },
        }),
      'planning.sources[0]',
    );
  });
});

describe('createBrandMarkers pick and dispose', () => {
  it('updates world matrices, picks nearest slug, and clears on stale / dispose', () => {
    const onSelect = vi.fn();
    const anchor = new THREE.Vector3(0, 0, 0);
    const markers = createBrandMarkers(anchor, onSelect);

    const tenants: BrandTenant[] = [
      { slug: 'near-brand', name: 'Near', availability: 'local' },
      { slug: 'far-brand', name: 'Far', availability: 'fixture' },
    ];
    markers.update(tenants, 'scene', false);
    expect(markers.group.children.length).toBe(2);

    const raycaster = new THREE.Raycaster();
    raycaster.set(new THREE.Vector3(3.6, 0.7, 10), new THREE.Vector3(0, 0, -1));
    const picked = markers.pick(raycaster);
    expect(picked).toBe(true);
    expect(onSelect).toHaveBeenCalledWith('near-brand');

    markers.update(tenants, 'scene', true);
    expect(markers.group.children.length).toBe(0);
    expect(markers.pick(raycaster)).toBe(false);

    markers.update(tenants, 'scene', false);
    expect(markers.group.children.length).toBe(2);

    markers.dispose();
    expect(markers.group.children.length).toBe(0);
    expect(markers.pick(raycaster)).toBe(false);
  });
});
