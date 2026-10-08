export interface CrewInputContext {
  explore: boolean;
  hasControl: boolean;
  hidden: boolean;
  dialog: boolean;
  fieldKit: boolean;
  sourceNotes: boolean;
  encounter: boolean;
  editable: boolean;
}

/** One eligibility rule for keyboard dispatch and the continuous movement loop. */
export function crewInputAllowed(context: CrewInputContext): boolean {
  return context.explore && context.hasControl && !context.hidden && !context.dialog
    && !context.fieldKit && !context.sourceNotes && !context.encounter && !context.editable;
}
