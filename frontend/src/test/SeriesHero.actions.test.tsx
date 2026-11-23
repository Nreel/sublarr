/**
 * SeriesHero.actions.test.tsx — every hero action button explains itself on hover.
 *
 * "Search All Missing", "Re-scan Series", "NFO Export" and "Series Settings" read
 * as opaque labels; the description has to come from the locale, not be invented
 * in the component.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import en from '@/i18n/locales/en/library.json'
import de from '@/i18n/locales/de/library.json'
import { SeriesHero } from '@/components/series/SeriesHero'
import type { SeriesDetail } from '@/lib/types'

function lookup(locale: Record<string, unknown>, key: string): string | undefined {
  let v: unknown = locale
  for (const part of key.split('.')) {
    if (typeof v !== 'object' || v === null || !(part in v)) return undefined
    v = (v as Record<string, unknown>)[part]
  }
  return typeof v === 'string' ? v : undefined
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => lookup(en as unknown as Record<string, unknown>, key) ?? key }),
}))

const series = {
  id: 1,
  title: 'Judas Erased',
  episode_file_count: 12,
  season_count: 1,
  status: 'continuing',
  target_languages: ['de'],
  episodes: [],
} as unknown as SeriesDetail

function renderHero() {
  return render(
    <SeriesHero
      series={series}
      missingCount={5}
      withSubsCount={7}
      lowScoreCount={0}
      isMissingSearchPending={false}
      missingSearchStarted={false}
      onSearchAllMissing={() => undefined}
      onRescan={() => undefined}
      onNfoExport={() => undefined}
      onSeriesSettings={() => undefined}
    />,
  )
}

const BUTTONS: Array<{ labelKey: string; hintKey: string }> = [
  { labelKey: 'series_detail.search_all_missing', hintKey: 'series_detail.hint_search_all_missing' },
  { labelKey: 'series_detail.rescan_series', hintKey: 'series_detail.hint_rescan_series' },
  { labelKey: 'series_detail.nfo_export', hintKey: 'series_detail.hint_nfo_export' },
  { labelKey: 'series_detail.series_settings', hintKey: 'series_detail.hint_series_settings' },
]

describe('hero action buttons', () => {
  it.each(BUTTONS)('%s carries a localized hover description', ({ labelKey, hintKey }) => {
    renderHero()
    const label = lookup(en as unknown as Record<string, unknown>, labelKey)!
    const hint = lookup(en as unknown as Record<string, unknown>, hintKey)!
    // The ⚡ glyph prefixes the search button's accessible name.
    const button = screen.getByRole('button', { name: new RegExp(label) })
    expect(button.getAttribute('title')).toBe(hint)
    expect(hint.length).toBeGreaterThan(20)
    // The description must say more than the label does.
    expect(hint).not.toBe(label)
  })

  it('every hint exists in German too', () => {
    for (const { hintKey } of BUTTONS) {
      expect(lookup(de as unknown as Record<string, unknown>, hintKey)).toBeTruthy()
    }
  })
})
