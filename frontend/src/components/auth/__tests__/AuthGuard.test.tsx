import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'

const getAuthStatus = vi.fn()
vi.mock('@/api/client', () => ({
  getAuthStatus: () => getAuthStatus(),
}))

import { AuthGuard } from '@/components/auth/AuthGuard'

/** Navigates to a new path, the way Login.tsx does after a successful
 *  sign-in (invalidate auth-status, then navigate back to the protected route). */
function JumpTo({ path }: { path: string }) {
  const navigate = useNavigate()
  return <button onClick={() => navigate(path)}>go</button>
}

function renderGuarded(client: QueryClient, otherRoute: ReactNode) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/login" element={otherRoute} />
          <Route path="/setup" element={<div>setup-page</div>} />
          <Route path="/" element={<AuthGuard><div>dashboard</div></AuthGuard>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AuthGuard', () => {
  it('sends an unauthenticated browser to /login', async () => {
    getAuthStatus.mockResolvedValue({ configured: true, enabled: true, authenticated: false })
    renderGuarded(new QueryClient(), <div>login-page</div>)
    await waitFor(() => expect(screen.getByText('login-page')).toBeInTheDocument())
  })

  it('sends a browser with no password configured to /setup', async () => {
    getAuthStatus.mockResolvedValue({ configured: false, enabled: false, authenticated: false })
    renderGuarded(new QueryClient(), <div>login-page</div>)
    await waitFor(() => expect(screen.getByText('setup-page')).toBeInTheDocument())
  })

  it('does not bounce back to /login on the cached pre-login status', async () => {
    // First read: signed out, so /login is the correct destination.
    getAuthStatus.mockResolvedValue({ configured: true, enabled: true, authenticated: false })
    const client = new QueryClient()
    renderGuarded(client, <JumpTo path="/" />)
    await waitFor(() => expect(screen.getByText('go')).toBeInTheDocument())

    // The browser now holds a session cookie, but the cache still answers
    // "authenticated: false" until the refetch settles. Redirecting on that
    // stale answer bounced a browser that had just signed in straight back to
    // /login, so the password had to be entered a second time.
    getAuthStatus.mockResolvedValue({ configured: true, enabled: true, authenticated: true })
    await client.invalidateQueries({ queryKey: ['auth-status'] })
    screen.getByText('go').click()

    await waitFor(() => expect(screen.getByText('dashboard')).toBeInTheDocument())
    expect(screen.queryByText('login-page')).not.toBeInTheDocument()
  })
})
