import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { WebhookSecretSection } from '../connections/WebhookSecretSection'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/shared/Toast', () => ({ toast: vi.fn() }))

vi.mock('@/components/settings/SettingsSection', () => ({
  SettingsSection: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/shared/SettingRow', () => ({
  SettingRow: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

const getWebhookSecret = vi.fn()
const regenerateWebhookSecret = vi.fn()
vi.mock('@/api/client', () => ({
  getWebhookSecret: () => getWebhookSecret(),
  regenerateWebhookSecret: () => regenerateWebhookSecret(),
}))

const updateConfig = vi.fn()
vi.mock('@/hooks/useApi', () => ({
  useUpdateConfig: () => ({ mutate: updateConfig, isPending: false }),
}))

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <WebhookSecretSection />
    </QueryClientProvider>,
  )
}

describe('WebhookSecretSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getWebhookSecret.mockResolvedValue({ webhook_secret: 'abc123secret', legacy_auth: true })
  })

  it('hides the secret until asked', async () => {
    renderSection()
    const value = screen.getByTestId('webhook-secret')
    await waitFor(() => expect(value.textContent).toMatch(/^•+$/))
    fireEvent.click(screen.getByTestId('webhook-secret-toggle'))
    expect(value.textContent).toBe('abc123secret')
  })

  it('regenerates only after confirmation', async () => {
    regenerateWebhookSecret.mockResolvedValue({ webhook_secret: 'new' })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    renderSection()
    fireEvent.click(screen.getByTestId('webhook-secret-regenerate'))
    expect(regenerateWebhookSecret).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('webhook-secret-regenerate'))
    await waitFor(() => expect(regenerateWebhookSecret).toHaveBeenCalledTimes(1))
    confirm.mockRestore()
  })

  it('copies the plaintext secret, not the mask, through the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    renderSection()
    fireEvent.click(screen.getByTestId('webhook-secret-copy'))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('abc123secret'))
  })

  it('keeps the regenerated secret shown and copyable when the refetch fails', async () => {
    getWebhookSecret.mockResolvedValueOnce({ webhook_secret: 'abc123secret', legacy_auth: true })
    getWebhookSecret.mockRejectedValue(new Error('session required'))
    regenerateWebhookSecret.mockResolvedValue({ webhook_secret: 'newsecret' })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderSection()
    const value = screen.getByTestId('webhook-secret')
    await waitFor(() => expect(value.textContent).toMatch(/^•+$/))
    fireEvent.click(screen.getByTestId('webhook-secret-toggle'))
    await waitFor(() => expect(value.textContent).toBe('abc123secret'))
    fireEvent.click(screen.getByTestId('webhook-secret-regenerate'))
    await waitFor(() => expect(value.textContent).toBe('newsecret'))
    fireEvent.click(screen.getByTestId('webhook-secret-copy'))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('newsecret'))
    confirm.mockRestore()
  })

  it('turns legacy API-key auth off through the config', async () => {
    renderSection()
    const toggle = await screen.findByRole('switch')
    await waitFor(() => expect(toggle).not.toBeDisabled())
    fireEvent.click(toggle)
    expect(updateConfig.mock.calls[0][0]).toEqual({ webhook_legacy_auth: false })
  })
})
