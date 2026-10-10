// One Hermes log record as GET /events lists it. Hermes redacts the payload before it logs it.
export type HermesEvent = { ts: string; kind: string; [key: string]: unknown }
// One route of a task title: scripts/hermes.py route()
export type Route = { agent: string; hook: string; skills: string[]; matched_glob: string }
// One line of scripts/replay.py: the route before and after the current skill-hooks.yaml
export type Replay = { ts: string; task: { title?: string }; before: Route[]; after: Route[]; changed: boolean }

declare module 'claude-code' {
  interface PluginState {
    'sg-hermes': {
      events: HermesEvent[]
      tab: 'live' | 'route' | 'replay'
      routes: Route[] | null
      routedTitle: string
      replay: Replay[] | null
      error: string | null
      up: boolean | null
    }
  }
}
