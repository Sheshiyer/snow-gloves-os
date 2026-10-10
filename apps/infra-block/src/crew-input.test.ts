import { describe, expect, it } from 'vitest';
import { crewInputAllowed, type CrewInputContext } from './crew-input';

const walk: CrewInputContext = {
  explore: true, hasControl: true, hidden: false, dialog: false,
  fieldKit: false, sourceNotes: false, encounter: false, editable: false
};

describe('continuous crew input boundaries', () => {
  it('allows a focused explorer with a selected character', () => {
    expect(crewInputAllowed(walk)).toBe(true);
  });
  it.each(['hidden', 'dialog', 'fieldKit', 'sourceNotes', 'encounter', 'editable'] as const)(
    'suspends held input when %s opens after keydown', boundary => {
      expect(crewInputAllowed(walk)).toBe(true);
      expect(crewInputAllowed({ ...walk, [boundary]: true })).toBe(false);
      expect(crewInputAllowed(walk)).toBe(true);
    }
  );
  it('keeps overview and sandbox out of the resident input rail', () => {
    expect(crewInputAllowed({ ...walk, hasControl: false })).toBe(false);
    expect(crewInputAllowed({ ...walk, explore: false })).toBe(false);
  });
});
