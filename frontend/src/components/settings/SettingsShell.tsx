import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { SettingsNav } from './SettingsNav';

interface SettingsShellProps {
  readonly children: ReactNode
}

/**
 * Bring the `#section-id` a deep link asked for into view. React Router does
 * not act on the fragment, and the sections above the target are lazy-loaded,
 * so they grow *after* the first jump and push it back out of view — keep
 * re-anchoring until the element's position stops moving. Every /settings/*
 * page gets this from the shell; pages that link from elsewhere (a Health
 * badge pointing at #backends) depend on it.
 */
function useSectionHashAnchor(hash: string) {
  useEffect(() => {
    if (!hash) return
    const id = hash.slice(1)
    let last = -1
    let settled = 0
    const timer = window.setInterval(() => {
      const el = document.getElementById(id)
      if (!el) return
      const top = el.getBoundingClientRect().top
      el.scrollIntoView({ block: 'start' })
      settled = Math.abs(top - last) < 2 ? settled + 1 : 0
      last = top
      if (settled >= 3) window.clearInterval(timer)
    }, 120)
    const stop = window.setTimeout(() => window.clearInterval(timer), 4000)
    return () => {
      window.clearInterval(timer)
      window.clearTimeout(stop)
    }
  }, [hash])
}

/**
 * Two-column layout for all /settings/* routes:
 * left = persistent navigation sidebar, right = page content.
 */
export function SettingsShell({ children }: SettingsShellProps) {
  const { hash } = useLocation()
  useSectionHashAnchor(hash)
  return (
    <div
      data-testid="settings-shell"
      className="flex flex-col md:flex-row md:items-start gap-4 md:gap-6 w-full"
    >
      {/* Sidebar — full-width scrollable block on phones, sticky column from md up */}
      <div className="w-full max-h-64 overflow-y-auto md:w-auto md:max-h-screen md:sticky md:top-0">
        <SettingsNav />
      </div>

      {/* Divider (two-column layout only) */}
      <div
        className="hidden md:block"
        style={{
          width: 1,
          minHeight: '100%',
          background: 'var(--border)',
          flexShrink: 0,
          alignSelf: 'stretch',
        }}
      />

      {/* Page content */}
      <div className="flex-1 min-w-0 pb-10">
        {children}
      </div>
    </div>
  )
}
