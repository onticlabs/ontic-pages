import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import { parsePublish } from './register'

const OUTPUT = [
  'published depth-eval version 3 (12 files)',
  'private: only mikel@onticlabs.io can open it, signed in with that address',
  'https://pages.onticlabs.io/depth-eval/',
  '',
].join('\n')

const PROPS = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 10,
  bodyColumns: 100,
  scroll: { offset: 0, bodyRows: 10 },
  view: {},
}

// The engine beneath the plugin: a Bash call that printed OUTPUT, and an empty band.
function engine(on: On) {
  on('tool.call', { tool: 'Bash' }, () => ({
    result: { stdout: OUTPUT, stderr: '', interrupted: false, isImage: false },
  }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
}

test('reads the page from the publish output', () => {
  expect(parsePublish(OUTPUT)).toEqual({
    name: 'depth-eval',
    version: 3,
    url: 'https://pages.onticlabs.io/depth-eval/',
  })
  expect(parsePublish('published depth-eval version 3 (12 files)\n')).toBe(null)
  expect(parsePublish('hello\n')).toBe(null)
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`shows the published page as a link above the prompt on ${surface}`, async ($, on) => {
    engine(on)
    const before = await $.ui.mount({ plugin: 'ontic-pages', surface, component: 'AbovePrompt', props: PROPS })
    expect(await before.find({ type: 'Link' })).toBe(undefined)

    await $.tool.call({ tool: 'Bash', command: 'ontic pages publish ./report --name depth-eval' })

    const after = await $.ui.mount({ plugin: 'ontic-pages', surface, component: 'AbovePrompt', props: PROPS })
    expect(await after.find({ type: 'Link' })).toMatchObject({ text: 'depth-eval (version 3)' })
  })
}

test('ignores the same output from other commands', async ($, on) => {
  engine(on)
  await $.tool.call({ tool: 'Bash', command: 'cat publish.log' })

  const band = await $.ui.mount({ plugin: 'ontic-pages', surface: 'terminal', component: 'AbovePrompt', props: PROPS })
  expect(await band.find({ type: 'Link' })).toBe(undefined)
})
