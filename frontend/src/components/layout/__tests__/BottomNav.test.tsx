import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { useActiveJobCount } from '@/hooks/useApi'
import { useQueueTaskCount, useWantedSummary } from '@/hooks/useWantedApi'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/hooks/useApi', () => ({
  useActiveJobCount: vi.fn(() => 0),
}))

vi.mock('@/hooks/useWantedApi', () => ({
  useWantedSummary: vi.fn(() => ({ data: { total: 5 } })),
  useQueueTaskCount: vi.fn(() => 0),
}))

import { BottomNav } from '../BottomNav'

function renderWithRouter(ui: React.ReactElement, { route = '/' } = {}) {
  window.history.pushState({}, 'Test page', route)
  return render(<BrowserRouter>{ui}</BrowserRouter>)
}

describe('BottomNav', () => {
  beforeEach(() => {
    vi.mocked(useActiveJobCount).mockReturnValue(0)
    vi.mocked(useQueueTaskCount).mockReturnValue(0)
    vi.mocked(useWantedSummary).mockReturnValue({ data: { total: 5 } })
  })

  it('renders the five nav items', () => {
    renderWithRouter(<BottomNav />)
    for (const id of ['dashboard', 'library', 'wanted', 'activity', 'settings']) {
      expect(screen.getByTestId(`bottom-nav-${id}`)).toBeInTheDocument()
    }
  })

  it('shows the Wanted badge', () => {
    renderWithRouter(<BottomNav />)
    expect(screen.getByTestId('bottom-nav-wanted-badge')).toHaveTextContent('5')
  })

  it('caps the Wanted badge at 99+', () => {
    vi.mocked(useWantedSummary).mockReturnValue({ data: { total: 155 } })
    renderWithRouter(<BottomNav />)
    expect(screen.getByTestId('bottom-nav-wanted-badge')).toHaveTextContent('99+')
  })

  it('shows the Queue badge when queue work is pending', () => {
    vi.mocked(useQueueTaskCount).mockReturnValue(3)
    renderWithRouter(<BottomNav />)
    expect(screen.getByTestId('bottom-nav-activity-queue-badge')).toHaveTextContent('3')
    expect(screen.queryByTestId('bottom-nav-activity-translations-badge')).toBeNull()
  })

  it('shows the Translations badge when jobs are in flight', () => {
    vi.mocked(useActiveJobCount).mockReturnValue(7)
    renderWithRouter(<BottomNav />)
    expect(screen.getByTestId('bottom-nav-activity-translations-badge')).toHaveTextContent('7')
    expect(screen.queryByTestId('bottom-nav-activity-queue-badge')).toBeNull()
  })

  it('shows Queue before Translations when both are running', () => {
    vi.mocked(useQueueTaskCount).mockReturnValue(120)
    vi.mocked(useActiveJobCount).mockReturnValue(7)
    renderWithRouter(<BottomNav />)
    const badges = screen
      .getAllByTestId(/bottom-nav-activity-/)
      .map((el) => `${el.dataset.testid}:${el.textContent}`)
    expect(badges).toEqual([
      'bottom-nav-activity-queue-badge:99+',
      'bottom-nav-activity-translations-badge:7',
    ])
  })

  it('shows no Activity badges when nothing is running', () => {
    renderWithRouter(<BottomNav />)
    expect(screen.queryByTestId('bottom-nav-activity-queue-badge')).toBeNull()
    expect(screen.queryByTestId('bottom-nav-activity-translations-badge')).toBeNull()
  })

  it('marks the active route with aria-current', () => {
    renderWithRouter(<BottomNav />, { route: '/activity' })
    expect(screen.getByTestId('bottom-nav-activity')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByTestId('bottom-nav-wanted')).not.toHaveAttribute('aria-current')
  })
})
