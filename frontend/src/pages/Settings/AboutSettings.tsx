import { Info, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { WhatsNewModal } from '@/components/layout/WhatsNewModal'
import { WHATS_NEW, versionKey } from '@/content/whatsNew'
import { useTranslation } from 'react-i18next'
import { SettingsDetailLayout } from '@/components/settings/SettingsDetailLayout'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { FormLayout } from '@/components/settings/layouts'
import type { FormSectionDef } from '@/components/settings/layouts'
import { getHealth } from '@/api/client'

// Settings Template B (FormLayout) — Codex-named reference for an info-heavy
// page. titleKeys reuse the existing about_page.*_title strings (the
// section heading and the TOC entry should always read the same).
const SECTIONS: readonly FormSectionDef[] = [
  { id: 'version',   titleKey: 'about_page.version_title' },
]

// ─── Component ────────────────────────────────────────────────────────────────

export function AboutSettings() {
  const { t } = useTranslation('settings')
  const { t: tc } = useTranslation('common')
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    staleTime: 60_000,
  })

  const version = health?.version ?? '—'
  const [showWhatsNew, setShowWhatsNew] = useState(false)
  const wnVersion = versionKey(health?.version) ?? Object.keys(WHATS_NEW).slice(-1)[0] ?? null

  return (
    <SettingsDetailLayout
      title={t('about_page.title')}
      subtitle={t('about_page.subtitle')}
    >
      <div data-testid="about-settings">
        <FormLayout sections={SECTIONS}>

        {/* ── Version ───────────────────────────────────────────────────── */}
        <section id="version" data-testid="settings.about.section-version">
        <div data-testid="section-version">
          <SettingsSection
            title={t('about_page.version_title')}
            description={t('about_page.version_desc')}
            icon={<Info size={16} style={{ color: 'var(--accent)' }} />}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '10px 14px',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                width: 'fit-content',
              }}
            >
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Sublarr</span>
              <span
                data-testid="version-badge"
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--accent)',
                  fontFamily: 'var(--font-mono, monospace)',
                }}
              >
                {version}
              </span>
              <button
                onClick={() => setShowWhatsNew(true)}
                className="flex items-center gap-1 text-xs font-medium"
                style={{ color: 'var(--accent)' }}
              >
                <Sparkles size={13} /> {tc('whatsnew.title', { version: wnVersion ?? version })}
              </button>
            </div>
          </SettingsSection>
        </div>
        </section>

        </FormLayout>
      </div>
      <WhatsNewModal open={showWhatsNew} version={wnVersion} onDismiss={() => setShowWhatsNew(false)} />
    </SettingsDetailLayout>
  )
}
