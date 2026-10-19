import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Page } from '../types'

const last = atom({ plugin: 'ontic-pages', key: 'last' } as const, null)

// `ontic pages publish` (or `ontic-pages publish`) prints
// "published <name> version <n> (<k> files)" and, last, the page URL ending in /<name>/.
const PUBLISH_COMMAND = /\bontic[- ]pages\b[\s\S]*\bpublish\b/

export function parsePublish(stdout: string): Page | null {
  let page: Page | null = null
  for (const line of stdout.split('\n').map(text => text.trim())) {
    const [, name, version] = /^published (\S+) version (\d+) \(/.exec(line) ?? []
    if (name && version) {
      page = { name, version: Number(version), url: '' }
    } else if (page && !page.url && /^https?:\/\/\S+$/.test(line) && line.endsWith(`/${page.name}/`)) {
      page.url = line
    }
  }
  return page?.url ? page : null
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'page',
      description: 'Show the link to the last ontic page published in this session',
    })

    return next(e)
  })

  on('command.run', { command: 'page' }, async $ => {
    const page = await read($, last)

    return {
      text: page
        ? `${page.name} version ${page.version}: ${page.url}`
        : 'No ontic page published in this session yet.',
    }
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && !ran.isError && PUBLISH_COMMAND.test(e.command)) {
      const page = parsePublish(ran.result.stdout)
      if (page) {
        await update($, last, () => page)
      }
    }

    return ran
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const page = await read($, last)
    if (e.props.hasSurvey || page === null) {
      return next(e)
    }

    const { Box, Link, Text } = $.ui.resolve(e)

    return (
      <Box>
        <Text dimColor>Ontic page: </Text>
        <Link href={page.url} label={`${page.name} (version ${page.version})`} />
      </Box>
    )
  })
}
