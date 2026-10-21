import {afterEach, describe, expect, it, vi} from 'vitest';
import {brandDisplayName, parseBrandSummary, renderBrandPassport} from './brand-summary';

function row() {
  return {tenant: 'alpha', displayName: 'Current Brand', status: 'owner_confirmed', planningReview: 'pending', issues: ['legacy_slug', 'parent_unconfirmed', 'delivery_partner_not_parent', 'service_not_software', 'project_parent_unconfirmed'], sourceIds: ['company-context']};
}

describe('owner context reconciliation', () => {
  it('uses the confirmed display name without changing the tenant slug or old planning', () => {
    const summary = parseBrandSummary({reconciliation: row()}, 'alpha');
    const tenant = {slug: 'alpha', name: 'Older Brand', ...summary};
    expect(brandDisplayName(tenant)).toBe('Current Brand');
    expect(tenant.slug).toBe('alpha');
    expect(brandDisplayName({slug: 'beta', name: 'Unchanged Brand'})).toBe('Unchanged Brand');
    expect(brandDisplayName({slug: 'beta', name: ''})).toBe('beta');
    expect(summary.reconciliation?.planningReview).toBe('pending');
    expect(Object.keys(summary)).toEqual(['reconciliation']);
  });

  it.each([
    (r: any) => {r.tenant = 'foreign';},
    (r: any) => {r.displayName = '<img src=x>';},
    (r: any) => {r.displayName = 'password private';},
    (r: any) => {r.displayName = 'X'.repeat(65);},
    (r: any) => {r.displayName = 'Current Brand\n';},
    (r: any) => {r.status = 'runtime_authorized';},
    (r: any) => {r.planningReview = 'enabled';},
    (r: any) => {r.issues = ['raw notes'];},
    (r: any) => {r.issues = ['legacy_slug', 'legacy_slug'];},
    (r: any) => {r.sourceIds = ['/private/context'];},
    (r: any) => {r.sourceIds = ['company-context\n'];},
    (r: any) => {r.sourceIds = ['token-private'];},
    (r: any) => {r.sourceIds = [];},
    (r: any) => {r.sourceIds = Array(17).fill('context');},
    (r: any) => {r.notes = 'PRIVATE_NOTES';},
    (r: any) => {r.permissions = {identity: true};},
    (r: any) => {delete r.status;},
  ])('rejects malformed or authorizing reconciliation response %#', mutate => {
    const raw = row(); mutate(raw);
    expect(() => parseBrandSummary({reconciliation: raw}, 'alpha')).toThrow();
  });
  it('requires an enclosing tenant for reconciliation and accepts older summaries without it', () => {
    expect(() => parseBrandSummary({reconciliation: row()})).toThrow('tenant mismatch');
    expect(parseBrandSummary({})).toEqual({});
  });
});

class Element {
  children: Element[] = []; textContent = '';
  constructor(public tagName: string) {}
  appendChild(child: Element) {this.children.push(child); return child;}
  setAttribute() {}
  set innerHTML(_: string) {throw new Error('Unsafe markup');}
  text(): string {return [this.textContent, ...this.children.map(c => c.text())].join('\n');}
}
afterEach(() => vi.unstubAllGlobals());
it('shows human-readable pending planning conflicts and context-only authority using text nodes', () => {
  vi.stubGlobal('document', {createElement: (tag: string) => new Element(tag)});
  const summary = parseBrandSummary({reconciliation: row()}, 'alpha');
  const content = (renderBrandPassport(summary) as unknown as Element).text();
  expect(content).toContain('Owner-confirmed context: Current Brand · Tenant slug: alpha');
  expect(content).toContain('Planning review: pending');
  expect(content).toContain('Delivery partner must not be represented as a parent');
  expect(content).toContain('Classify this offering as a service, not software');
  expect(content).toContain('Project parent needs owner review');
  expect(content).toContain('No runtime, module, or identity permissions granted');
});
