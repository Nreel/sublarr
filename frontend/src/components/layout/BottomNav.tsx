import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { LayoutDashboard, BookOpen, Bell, Settings, Search } from 'lucide-react'
import { useQueueTaskCount, useWantedSummary } from '@/hooks/useWantedApi'
import { useActiveJobCount } from '@/hooks/useApi'

interface BottomNavItem {
  readonly to: string
  readonly labelKey: string
  readonly icon: typeof LayoutDashboard
  readonly testId: string
  /** Pill badges pinned to the icon, in render order; zero-count ones drop out. */
  readonly badges?: readonly { testId: string; tone: BadgeTone }[]
}

type BadgeTone = 'warning' | 'accent'

const navItems: readonly BottomNavItem[] = [
  { to: '/', labelKey: 'nav.dashboard', icon: LayoutDashboard, testId: 'bottom-nav-dashboard' },
  { to: '/library', labelKey: 'nav.library', icon: BookOpen, testId: 'bottom-nav-library' },
  { to: '/wanted', labelKey: 'nav.wanted', icon: Search, testId: 'bottom-nav-wanted', badges: [{ testId: 'bottom-nav-wanted-badge', tone: 'warning' }] },
  {
    to: '/activity',
    labelKey: 'nav.activity',
    icon: Bell,
    testId: 'bottom-nav-activity',
    badges: [
      { testId: 'bottom-nav-activity-queue-badge', tone: 'warning' },
      { testId: 'bottom-nav-activity-translations-badge', tone: 'accent' },
    ],
  },
  { to: '/settings', labelKey: 'nav.settings', icon: Settings, testId: 'bottom-nav-settings' },
] as const

const badgeTones = {
  warning: { backgroundColor: 'var(--warning-bg)', color: 'var(--warning)' },
  accent: { backgroundColor: 'var(--accent-bg)', color: 'var(--accent)' },
} as const

export function BottomNav() {
  const { t } = useTranslation('common')
  const { data: wantedSummary } = useWantedSummary()

  const wantedCount = wantedSummary?.total ?? 0

  // Activity badges: Queue work items still pending (batch search/probe/extract
  // or a scan) and translation jobs in flight — the same figures the Activity
  // page pills show.
  const queueCount = useQueueTaskCount()
  const translationCount = useActiveJobCount()

  const badgeCounts: Record<string, number> = {
    'bottom-nav-wanted-badge': wantedCount,
    'bottom-nav-activity-queue-badge': queueCount,
    'bottom-nav-activity-translations-badge': translationCount,
  }

  return (
    <nav
      data-testid="bottom-nav"
      className="fixed bottom-0 left-0 right-0 z-50 flex md:hidden"
      style={{
        backgroundColor: 'var(--bg-primary)',
        borderTop: '1px solid var(--border)',
      }}
    >
      {navItems.map(({ to, labelKey, icon: Icon, testId, badges }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          data-testid={testId}
          aria-label={t(labelKey)}
          className="flex-1 flex flex-col items-center gap-0.5 py-2 relative transition-colors duration-100"
          style={({ isActive }) => ({
            color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
          })}
        >
          {({ isActive }) => (
            <>
              {/* Active indicator bar at top */}
              {isActive && (
                <div
                  className="absolute top-0 left-4 right-4 h-[2px] rounded-b-sm"
                  style={{ backgroundColor: 'var(--accent)' }}
                />
              )}
              <div className="relative">
                <Icon size={22} strokeWidth={isActive ? 2.2 : 1.8} />
                {badges?.some((badge) => badgeCounts[badge.testId] > 0) && (
                  <div className="absolute -top-1.5 left-full flex gap-[2px] -translate-x-1/2 pointer-events-none">
                    {badges
                      .filter((badge) => badgeCounts[badge.testId] > 0)
                      .map((badge) => (
                        <span
                          key={badge.testId}
                          data-testid={badge.testId}
                          className="text-[9px] font-semibold leading-tight px-1 min-w-[14px] max-w-[28px] text-center rounded-full"
                          style={badgeTones[badge.tone]}
                        >
                          {badgeCounts[badge.testId] > 99 ? '99+' : badgeCounts[badge.testId]}
                        </span>
                      ))}
                  </div>
                )}
              </div>
              <span className="text-[10px] font-medium">{t(labelKey)}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
