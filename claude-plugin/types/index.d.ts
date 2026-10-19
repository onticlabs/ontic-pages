// `version` is the page version's id as publish prints it, a UTC timestamp like 20261019T091314Z.
export type Page = { name: string; version: string; url: string }

declare module 'claude-code' {
  interface PluginState {
    'ontic-pages': { last: Page | null }
  }
}
