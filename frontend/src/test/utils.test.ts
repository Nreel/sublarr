import { describe, it, expect } from 'vitest'
import { formatDuration, formatRelativeTime, formatTimestamp, truncatePath, cn } from '@/lib/utils'

describe('formatDuration', () => {
  it('formats seconds', () => {
    expect(formatDuration(30)).toBe('30s')
  })

  it('formats minutes', () => {
    expect(formatDuration(125)).toBe('2m 5s')
  })

  it('formats hours', () => {
    expect(formatDuration(3665)).toBe('1h 1m')
  })
})

describe('formatTimestamp', () => {
  it('renders exact date and time to the second', () => {
    // No timezone suffix → parsed as local time, so the assertion holds in any TZ.
    expect(formatTimestamp('2026-11-25T14:32:07', 'en-US')).toBe('11/25/2026, 14:32:07')
  })

  it('keeps seconds precision instead of a coarse relative label', () => {
    const utc = formatTimestamp('2026-11-25T14:32:07.000Z', 'en-US')
    expect(utc).toMatch(/\d{2}:\d{2}:\d{2}$/)
    expect(utc).not.toContain('ago')
  })

  it('renders a placeholder for missing or invalid input', () => {
    expect(formatTimestamp(null)).toBe('—')
    expect(formatTimestamp('not-a-date')).toBe('—')
  })
})

describe('formatRelativeTime', () => {
  it('formats recent time', () => {
    const now = new Date()
    const recent = new Date(now.getTime() - 30 * 1000)
    expect(formatRelativeTime(recent.toISOString())).toBe('just now')
  })

  it('formats minutes ago', () => {
    const now = new Date()
    const minutesAgo = new Date(now.getTime() - 5 * 60 * 1000)
    expect(formatRelativeTime(minutesAgo.toISOString())).toContain('m ago')
  })
})

describe('truncatePath', () => {
  it('truncates long paths', () => {
    const longPath = '/very/long/path/to/file.mkv'
    const truncated = truncatePath(longPath, 20)
    expect(truncated.length).toBeLessThanOrEqual(23) // ... + 20 chars
  })

  it('keeps short paths unchanged', () => {
    const shortPath = '/file.mkv'
    expect(truncatePath(shortPath, 60)).toBe(shortPath)
  })
})

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('handles conditional classes', () => {
    expect(cn('foo', (false as boolean) && 'bar', 'baz')).toBe('foo baz')
  })
})
