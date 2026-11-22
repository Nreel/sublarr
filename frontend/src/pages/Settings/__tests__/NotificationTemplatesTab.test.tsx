/**
 * NotificationTemplatesTab.test.tsx — notification event toggles.
 *
 * Covers the toggles that the notifier actually reads, including the provider
 * degradation alert (backend default false, so a click must send "true").
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NotificationTemplatesTab } from '../NotificationTemplatesTab'
import enSettings from '../../../i18n/locales/en/settings.json'

function lookupKey(ns: Record<string, unknown>, key: string): string | undefined {
  const parts = key.split('.')
  let v: unknown = ns
  for (const p of parts) {
    if (typeof v !== 'object' || v === null) return undefined
    v = (v as Record<string, unknown>)[p]
  }
  return typeof v === 'string' ? v : undefined
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: string | Record<string, unknown>) => {
      if (typeof opts === 'string') return opts
      if (opts !== undefined && typeof opts === 'object' && 'count' in opts)
        return `${key}:${String(opts.count)}`
      return lookupKey(enSettings, key) ?? key.split('.').pop() ?? key
    },
  }),
}))

vi.mock('@/components/notifications/TemplateEditor', () => ({
  TemplateEditor: () => <div data-testid="mock-template-editor" />,
}))
vi.mock('@/components/notifications/TemplatePreview', () => ({
  TemplatePreview: () => <div data-testid="mock-template-preview" />,
}))
vi.mock('@/components/shared/Toast', () => ({ toast: vi.fn() }))

const mockUpdateConfig = vi.fn()
let mockConfig: Record<string, string> = {}

vi.mock('@/hooks/useApi', () => ({
  useConfig: () => ({ data: mockConfig, isLoading: false }),
  useUpdateConfig: () => ({ mutate: mockUpdateConfig, isPending: false }),
  useNotificationTemplates: () => ({ data: [], isLoading: false }),
  useCreateNotificationTemplate: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateNotificationTemplate: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteNotificationTemplate: () => ({ mutate: vi.fn(), isPending: false }),
  useNotificationFilters: () => ({ data: { include_events: '', exclude_events: '' }, isLoading: false }),
  useUpdateNotificationFilters: () => ({ mutate: vi.fn(), isPending: false }),
  useEventCatalog: () => ({ data: [], isLoading: false }),
}))

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <NotificationTemplatesTab />
      </BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('NotificationTemplatesTab event toggles', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockConfig = { notify_on_download: 'true', provider_degradation_alerts_enabled: 'false' }
  })

  it('renders the degradation alert control', () => {
    renderTab()
    expect(screen.getByText('Alert on Provider Degradation')).toBeInTheDocument()
  })

  it('flips a disabled alert to true on click', () => {
    renderTab()
    fireEvent.click(screen.getByText('Alert on Provider Degradation'))
    expect(mockUpdateConfig).toHaveBeenCalledWith({ provider_degradation_alerts_enabled: 'true' })
  })

  it('flips an enabled download notification back to false', () => {
    renderTab()
    fireEvent.click(screen.getByText('Notify on Download'))
    expect(mockUpdateConfig).toHaveBeenCalledWith({ notify_on_download: 'false' })
  })
})
