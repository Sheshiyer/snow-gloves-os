// One message held in the inbox instead of interrupting the running turn.
export type Held = { id: number; text: string; from: string; at: number }

declare module 'claude-code' {
  interface PluginState {
    'sg-handoff': {
      held: Held[]
      isInboxOn: boolean
      note: string | null
      nextId: number
    }
  }
}
