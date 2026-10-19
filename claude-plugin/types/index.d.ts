export type Page = { name: string; version: number; url: string }

declare module 'claude-code' {
  interface PluginState {
    'ontic-pages': { last: Page | null }
  }
}
