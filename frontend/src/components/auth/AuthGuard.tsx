import { useQuery } from '@tanstack/react-query'
import { Navigate, useLocation } from 'react-router-dom'
import { getAuthStatus } from '@/api/client'

interface AuthGuardProps {
  children: React.ReactNode
}

export function AuthGuard({ children }: AuthGuardProps) {
  const location = useLocation()
  const { data: auth, isLoading, isFetching } = useQuery({
    queryKey: ['auth-status'],
    queryFn: getAuthStatus,
    staleTime: 30_000,
    retry: false,
  })

  // A sign-in or first-run setup invalidates this query and then navigates.
  // Until the refetch settles the cache still holds the pre-login answer
  // ("authenticated: false"), and redirecting on it bounced a browser that had
  // just signed in straight back to /login — the password had to be entered
  // twice. Render nothing until the read has settled, then decide on fresh data.
  if (isLoading || isFetching) return null

  if (auth && !auth.configured) {
    return <Navigate to="/setup" replace />
  }
  if (auth?.configured && auth.enabled && !auth.authenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  return <>{children}</>
}
