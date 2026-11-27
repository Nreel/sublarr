import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// ─── Mocks ───────────────────────────────────────────────────────────────────

const mockToast = vi.fn()
const mockClipboardWrite = vi.fn()

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: string | Record<string, unknown>) => {
      if (typeof opts === 'string') return opts
      if (opts !== undefined && typeof opts === 'object' && 'count' in opts)
        return `${key}:${String(opts.count)}`
      return key
    },
  }),
}))

vi.mock('@/components/shared/Toast', () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}))

vi.mock('@/components/settings/SettingsSection', () => ({
  SettingsSection: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div>
      <h2>{title}</h2>
      {children}
    </div>
  ),
}))

// Covered by its own test; it needs a QueryClient.
vi.mock('@/pages/Settings/connections/WebhookSecretSection', () => ({
  WebhookSecretSection: () => null,
  QUERY_KEY: ['webhook-secret'],
}))

const mockGetWebhookSecret = vi.fn()
vi.mock('@/api/client', () => ({
  getWebhookSecret: (...args: unknown[]) => mockGetWebhookSecret(...args),
}))

vi.mock('@/components/shared/SettingRow', () => ({
  SettingRow: ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div>
      <label>{label}</label>
      {children}
    </div>
  ),
}))

// ─── Tests ───────────────────────────────────────────────────────────────────

import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { WebhooksSection } from '../connections/WebhooksSection'

function renderSection() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <WebhooksSection />
    </QueryClientProvider>,
  )
}

describe('WebhooksSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetWebhookSecret.mockResolvedValue({ webhook_secret: 'test-webhook-secret', legacy_auth: true })
    Object.defineProperty(navigator, 'clipboard', {
      writable: true,
      value: { writeText: mockClipboardWrite.mockResolvedValue(undefined) },
    })
  })

  it('renders webhook URL for sonarr', async () => {
    renderSection()
    const el = await waitFor(() => {
      const e = screen.getByTestId('webhook-url-sonarr')
      // Sonarr cannot send headers: the copyable URL must carry the secret itself.
      expect(e.textContent).toContain('?apikey=test-webhook-secret')
      return e
    })
    expect(el.textContent).toContain('/api/v1/webhook/sonarr')
  })

  it('renders webhook URL for radarr', async () => {
    renderSection()
    const el = await waitFor(() => {
      const e = screen.getByTestId('webhook-url-radarr')
      expect(e.textContent).toContain('?apikey=test-webhook-secret')
      return e
    })
    expect(el.textContent).toContain('/api/v1/webhook/radarr')
  })

  it('renders webhook URL for jellyfin', async () => {
    renderSection()
    const el = await waitFor(() => {
      const e = screen.getByTestId('webhook-url-jellyfin')
      expect(e.textContent).toContain('?apikey=test-webhook-secret')
      return e
    })
    expect(el.textContent).toContain('/api/v1/webhook/jellyfin')
  })

  it('omits the apikey param when no secret is configured', async () => {
    mockGetWebhookSecret.mockResolvedValue({ webhook_secret: '', legacy_auth: true })
    renderSection()
    await waitFor(() => expect(mockGetWebhookSecret).toHaveBeenCalled())
    expect(screen.getByTestId('webhook-url-sonarr').textContent).not.toContain('apikey')
  })

  it('copies URL and shows toast when copy button clicked', async () => {
    renderSection()
    await waitFor(() =>
      expect(screen.getByTestId('webhook-url-sonarr').textContent).toContain('apikey=test-webhook-secret'),
    )
    fireEvent.click(screen.getByTestId('webhook-copy-sonarr'))
    expect(mockClipboardWrite).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/webhook/sonarr?apikey=test-webhook-secret'),
    )
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('webhooks_page.copied'))
  })
})
