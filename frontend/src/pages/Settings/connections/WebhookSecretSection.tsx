/**
 * WebhookSecretSection — the secret Sonarr/Radarr/Jellyfin send instead of the
 * API key (#71), and the switch that stops webhooks accepting the API key.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Eye, EyeOff, KeyRound, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { SettingsSection } from '@/components/settings/SettingsSection'
import { SettingRow } from '@/components/shared/SettingRow'
import { Toggle } from '@/components/shared/Toggle'
import { toast } from '@/components/shared/Toast'
import { getWebhookSecret, regenerateWebhookSecret } from '@/api/client'
import type { WebhookSecret } from '@/api/settings'
import { apiErrorMessage } from '@/lib/apiError'
import { copyToClipboard } from '@/lib/clipboard'
import { useUpdateConfig } from '@/hooks/useApi'

const QUERY_KEY = ['webhook-secret']
export { QUERY_KEY }

export function WebhookSecretSection() {
  const { t } = useTranslation('settings')
  const queryClient = useQueryClient()
  const [shown, setShown] = useState(false)
  // staleTime: 0 — a cached secret must never be shown or copied after a
  // regeneration, mirroring the API-key reveal query (#71).
  const secretQuery = useQuery({ queryKey: QUERY_KEY, queryFn: getWebhookSecret, staleTime: 0 })
  const updateConfig = useUpdateConfig()

  const regenerate = useMutation({
    mutationFn: regenerateWebhookSecret,
    onSuccess: (data) => {
      // The response carries the new plaintext; write it straight into the
      // cache so display and copy use it even if a later refetch fails.
      queryClient.setQueryData(QUERY_KEY, (prev: WebhookSecret | undefined) => ({
        webhook_secret: data.webhook_secret,
        legacy_auth: prev?.legacy_auth ?? true,
      }))
      toast(t('webhooks_page.secret_regenerated'))
    },
  })

  const secret = secretQuery.data?.webhook_secret ?? ''

  async function copy() {
    let value = secret
    if (!value) {
      const result = await secretQuery.refetch()
      value = result.data?.webhook_secret ?? ''
    }
    if (!value) {
      toast(
        secretQuery.isError
          ? apiErrorMessage(secretQuery.error, t('webhooks_page.secret_load_failed', 'Could not load the webhook secret'))
          : t('webhooks_page.copy_empty', 'No secret to copy'),
        'error',
      )
      return
    }
    // navigator.clipboard alone rejects on insecure origins (plain http LAN);
    // copyToClipboard falls back to execCommand there.
    if (!(await copyToClipboard(value))) {
      toast(t('webhooks_page.copy_failed', 'Could not copy the secret'), 'error')
      return
    }
    toast(t('webhooks_page.copied'))
  }

  function confirmRegenerate() {
    if (window.confirm(t('webhooks_page.secret_regenerate_confirm'))) regenerate.mutate()
  }

  function setLegacy(value: boolean) {
    updateConfig.mutate(
      { webhook_legacy_auth: value },
      { onSuccess: () => void queryClient.invalidateQueries({ queryKey: QUERY_KEY }) },
    )
  }

  return (
    <SettingsSection
      title={t('webhooks_page.secret_title')}
      description={t('webhooks_page.secret_desc')}
      icon={<KeyRound size={16} className="text-accent" />}
    >
      <SettingRow label={t('webhooks_page.secret_label')}>
        <div className="flex min-w-0 items-center gap-2 font-mono text-xs text-muted">
          <span data-testid="webhook-secret" className="min-w-0 break-all">
            {shown ? secret : '•'.repeat(Math.min(secret.length, 24))}
          </span>
          <button
            type="button"
            onClick={() => setShown((v) => !v)}
            className="shrink-0 rounded p-1 text-secondary hover:opacity-80"
            aria-label={shown ? t('webhooks_page.secret_hide') : t('webhooks_page.secret_show')}
            data-testid="webhook-secret-toggle"
          >
            {shown ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
          <button
            type="button"
            onClick={copy}
            className="shrink-0 rounded p-1 text-secondary hover:opacity-80"
            aria-label={t('webhooks_page.secret_copy')}
            data-testid="webhook-secret-copy"
          >
            <Copy size={14} />
          </button>
          <button
            type="button"
            onClick={confirmRegenerate}
            disabled={regenerate.isPending}
            className="flex shrink-0 items-center gap-1 rounded px-2 py-1 text-secondary hover:opacity-80 disabled:opacity-50"
            data-testid="webhook-secret-regenerate"
          >
            <RefreshCw size={12} />
            {t('webhooks_page.secret_regenerate')}
          </button>
        </div>
      </SettingRow>
      <SettingRow label={t('webhooks_page.legacy_label')} description={t('webhooks_page.legacy_hint')}>
        <Toggle
          checked={secretQuery.data?.legacy_auth ?? true}
          onChange={setLegacy}
          disabled={!secretQuery.data || updateConfig.isPending}
        />
      </SettingRow>
    </SettingsSection>
  )
}
