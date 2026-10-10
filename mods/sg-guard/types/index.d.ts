declare module 'claude-code' {
  interface PluginState {
    'sg-guard': {
      blocked: number
      redacted: number
      refused: string[]
    }
  }
}
