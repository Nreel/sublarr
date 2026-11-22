import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useApiKeys, useUpdateApiKey, useTestApiKey,
  useRevealApiKeys, useRotateApiKey,
  useExportApiKeys, useImportApiKeys,
  useBazarrMigration, useConfirmBazarrImport,
} from '@/hooks/useApi'
import { toast } from '@/components/shared/Toast'
import { apiErrorMessage } from '@/lib/apiError'
import { copyToClipboard } from '@/lib/clipboard'
import { BazarrImportPreview } from '@/components/settings/BazarrImportPreview'
import {
  Loader2, Shield, ShieldCheck, ShieldAlert, TestTube,
  FileDown, Upload, Eye, EyeOff, Check, X, KeyRound, Copy,
} from 'lucide-react'
import type { ApiKeyService, BazarrMigrationPreview } from '@/lib/types'

// ─── Service Key Card ────────────────────────────────────────────────────────

function ServiceKeyCard({
  service,
  onUpdate,
  onTest,
  onRotate,
  rotating = false,
}: {
  service: ApiKeyService
  onUpdate: (service: string, keyName: string, value: string) => void
  onTest: (service: string) => void
  onRotate: (service: string) => void
  rotating?: boolean
}) {
  const { t } = useTranslation('settings')
  const { t: tc } = useTranslation('common')
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [showValues, setShowValues] = useState<Record<string, boolean>>({})
  // The list endpoint only ever carries masks, so revealing needs a separate
  // request for the full value. It runs on the first eye click for this service.
  const revealQuery = useRevealApiKeys(service.service, Object.values(showValues).some(Boolean))

  async function toggleShow(keyName: string) {
    const next = !showValues[keyName]
    setShowValues((prev) => ({ ...prev, [keyName]: next }))
    if (!next) return
    const result = await revealQuery.refetch()
    if (result.isError) {
      setShowValues((prev) => ({ ...prev, [keyName]: false }))
      toast(apiErrorMessage(result.error, t('apiKeys.reveal_failed', 'Could not reveal the key')), 'error')
    }
  }

  async function handleCopy(keyName: string) {
    let value = revealQuery.data?.keys.find((k) => k.name === keyName)?.value
    if (!value) {
      const result = await revealQuery.refetch()
      value = result.data?.keys.find((k) => k.name === keyName)?.value
    }
    if (!value) {
      toast(t('apiKeys.copy_empty', 'No key to copy'), 'error')
      return
    }
    if (!(await copyToClipboard(value))) {
      toast(t('apiKeys.copy_failed', 'Could not copy the key'), 'error')
      return
    }
    toast(t('apiKeys.copied', 'Key copied to clipboard'))
  }

  const handleStartEdit = (keyName: string) => {
    setEditingKey(keyName)
    setEditValue('')
  }

  const handleSave = (keyName: string) => {
    if (editValue.trim()) {
      onUpdate(service.service, keyName, editValue.trim())
    }
    setEditingKey(null)
    setEditValue('')
  }

  const handleCancel = () => {
    setEditingKey(null)
    setEditValue('')
  }

  const allConfigured = service.keys.every((k) => k.status === 'configured')
  const anyMissing = service.keys.some((k) => k.status === 'missing')

  return (
    <div
      className="rounded-lg p-4 space-y-3 bg-surface border border-border"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {allConfigured ? (
            <ShieldCheck size={16} className="text-success" />
          ) : anyMissing ? (
            <ShieldAlert size={16} className="text-error" />
          ) : (
            <Shield size={16} className="text-muted" />
          )}
          <h3 className="text-sm font-semibold text-foreground">
            {service.service}
          </h3>
        </div>
        {service.testable && (
          <button
            onClick={() => onTest(service.service)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-all duration-150 text-accent border border-accent-dim"
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--accent-bg)' }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent' }}
          >
            <TestTube size={12} />
            {t('actions.test')}
          </button>
        )}
      </div>

      <div className="space-y-2">
        {service.keys.map((key) => (
          <div
            key={key.name}
            className="flex items-center gap-3 px-3 py-2 rounded-md bg-page border border-border"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <KeyRound size={12} className="text-muted" />
                <span className="text-xs font-medium text-secondary">
                  {key.name}
                </span>
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                    key.status === 'configured' ? 'bg-success-bg text-success' : 'bg-error-bg text-error'
                  }`}
                >
                  {key.status}
                </span>
              </div>
              {editingKey === key.name ? (
                <div className="flex items-center gap-2 mt-1.5">
                  <input
                    type="password"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    placeholder={tc('ui.enter_new_value')}
                    className="flex-1 px-2 py-1 rounded text-xs focus:outline-none bg-surface border border-accent-dim text-foreground font-mono"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSave(key.name)
                      if (e.key === 'Escape') handleCancel()
                    }}
                  />
                  <button
                    onClick={() => handleSave(key.name)}
                    className="p-1 rounded text-success"
                    title={t('apiKeys.save')}
                  >
                    <Check size={14} />
                  </button>
                  <button
                    onClick={handleCancel}
                    className="p-1 rounded text-muted"
                    title={tc('ui.cancel')}
                  >
                    <X size={14} />
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2 mt-1">
                  <code
                    className="text-xs text-muted font-mono break-all"
                    data-testid={`api-key-value-${key.name}`}
                  >
                    {showValues[key.name] && key.status === 'configured'
                      ? revealQuery.data?.keys.find((k) => k.name === key.name)?.value || key.masked_value
                      : key.status === 'configured'
                        ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022'
                        : '(not set)'}
                  </code>
                  {key.status === 'configured' && (
                    <button
                      onClick={() => toggleShow(key.name)}
                      className="p-0.5 rounded text-muted"
                      aria-label={showValues[key.name] ? t('apiKeys.hide', 'Hide key') : t('apiKeys.reveal', 'Reveal key')}
                      data-testid={`api-key-reveal-${key.name}`}
                    >
                      {showValues[key.name] ? <EyeOff size={12} /> : <Eye size={12} />}
                    </button>
                  )}
                  {key.status === 'configured' && (
                    <button
                      onClick={() => handleCopy(key.name)}
                      className="p-0.5 rounded text-muted"
                      aria-label={t('apiKeys.copy', 'Copy key')}
                      data-testid={`api-key-copy-${key.name}`}
                    >
                      <Copy size={12} />
                    </button>
                  )}
                  <button
                    onClick={key.status === 'configured' ? () => onRotate(service.service) : () => handleStartEdit(key.name)}
                    disabled={key.status === 'configured' && rotating}
                    className="text-[10px] px-1.5 py-0.5 rounded font-medium transition-all duration-150 text-accent border border-accent-dim"
                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--accent-bg)' }}
                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent' }}
                  >
                    {key.status === 'configured' ? t('apiKeys.rotate') : t('apiKeys.set')}
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Main ApiKeysTab Component ───────────────────────────────────────────────

export function ApiKeysTab({
  excludeServices = [],
  includeOnly,
}: {
  excludeServices?: string[]
  includeOnly?: string[]
}) {
  const { t } = useTranslation('settings')
  const { data, isLoading } = useApiKeys()
  const updateKey = useUpdateApiKey()
  const testKey = useTestApiKey()
  const rotateKey = useRotateApiKey()
  const exportKeys = useExportApiKeys()
  const importKeys = useImportApiKeys()
  const bazarrMigrate = useBazarrMigration()
  const confirmBazarr = useConfirmBazarrImport()

  const importFileRef = useRef<HTMLInputElement>(null)
  const bazarrFileRef = useRef<HTMLInputElement>(null)
  const [bazarrPreview, setBazarrPreview] = useState<BazarrMigrationPreview | null>(null)
  // Confirm re-sends the file: the preview masks every secret it would write.
  const [bazarrFile, setBazarrFile] = useState<File | null>(null)

  const handleUpdate = (service: string, keyName: string, value: string) => {
    updateKey.mutate({ service, keyName, value }, {
      onSuccess: () => toast(t('apiKeys.keyUpdated', 'Key updated successfully')),
      onError: (err) => toast(apiErrorMessage(err, t('apiKeys.keyUpdateFailed', 'Failed to update key')), 'error'),
    })
  }

  const handleTest = (service: string) => {
    testKey.mutate(service, {
      onSuccess: (result) => {
        if (result.success) {
          toast(`${service}: ${result.message}`)
        } else {
          toast(`${service}: ${result.message}`, 'error')
        }
      },
      onError: (err) => toast(apiErrorMessage(err, t('apiKeys.connection_failed', { service })), 'error'),
    })
  }

  const handleRotate = (service: string) => {
    if (!window.confirm(t('apiKeys.rotate_confirm', 'Rotate this key? Callers that use the current key will stop working until they are updated.'))) {
      return
    }
    rotateKey.mutate(service, {
      onSuccess: () => toast(t('apiKeys.rotated', 'Key rotated')),
      onError: (err) => toast(apiErrorMessage(err, t('apiKeys.rotate_failed', 'Failed to rotate key')), 'error'),
    })
  }

  const handleExport = () => {
    exportKeys.mutate(undefined, {
      onSuccess: (blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `sublarr-api-keys-${new Date().toISOString().slice(0, 10)}.zip`
        a.click()
        URL.revokeObjectURL(url)
        toast(t('apiKeys.exportSuccess', 'API keys exported'))
      },
      onError: (err) => toast(apiErrorMessage(err, t('apiKeys.exportFailed', 'Export failed')), 'error'),
    })
  }

  const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    importKeys.mutate(file, {
      onSuccess: (result) => {
        toast(t('apiKeys.imported_keys', { count: result.imported }) + (result.skipped > 0 ? t('apiKeys.imported_skipped', { count: result.skipped }) : ''))
      },
      onError: (err) => toast(apiErrorMessage(err, t('apiKeys.importFailed', 'Import failed')), 'error'),
    })
    e.target.value = ''
  }

  const handleBazarrFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    bazarrMigrate.mutate([file], {
      onSuccess: (preview) => {
        setBazarrFile(file)
        setBazarrPreview(preview)
      },
      onError: (err) => {
        const message = (err as { response?: { data?: { error?: string } } })?.response?.data?.error
        toast(message ?? t('apiKeys.bazarr_parse_failed'), 'error')
      },
    })
    e.target.value = ''
  }

  const handleBazarrConfirm = () => {
    if (!bazarrFile) return
    confirmBazarr.mutate([bazarrFile], {
      onSuccess: (result) => {
        setBazarrPreview(null)
        setBazarrFile(null)
        const count = result.config_imported + result.profiles_imported + result.blacklist_imported
        toast(t('apiKeys.bazarr_import_complete', { count }))
        result.warnings.forEach((w) => toast(w, 'error'))
      },
      onError: (err) => toast(apiErrorMessage(err, t('apiKeys.bazarr_import_failed')), 'error'),
    })
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32">
        <Loader2 size={24} className="animate-spin text-accent" />
      </div>
    )
  }

  const services = (data?.services ?? []).filter((s: ApiKeyService) => {
    if (includeOnly) return includeOnly.includes(s.service)
    return !excludeServices.includes(s.service)
  })

  return (
    <div className="space-y-5">
      {/* Header */}
      <div
        className="rounded-lg p-4 bg-surface border border-border"
      >
        <h2 className="text-sm font-semibold mb-2 text-foreground">
          {t('apiKeys.title', 'API Key Management')}
        </h2>
        <p className="text-xs mb-3 text-muted">
          {t('apiKeys.description', 'Manage all API keys in one place. Test connections, rotate keys, and import/export configurations.')}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleExport}
            disabled={exportKeys.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-150 border border-border text-secondary bg-page"
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent-dim)'; e.currentTarget.style.color = 'var(--accent)' }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
          >
            {exportKeys.isPending ? <Loader2 size={12} className="animate-spin" /> : <FileDown size={12} />}
            {t('apiKeys.export', 'Export Keys')}
          </button>

          <button
            onClick={() => importFileRef.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-150 border border-border text-secondary bg-page"
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent-dim)'; e.currentTarget.style.color = 'var(--accent)' }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
          >
            <Upload size={12} />
            {t('apiKeys.import', 'Import Keys')}
          </button>
          <input ref={importFileRef} type="file" accept=".zip,.csv" onChange={handleImportFile} className="hidden" />

          <div className="h-5 border-l border-border" />

          <button
            onClick={() => bazarrFileRef.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-150 border border-border text-secondary bg-page"
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent-dim)'; e.currentTarget.style.color = 'var(--accent)' }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
          >
            <Upload size={12} />
            {t('apiKeys.bazarrImport', 'Bazarr Migration')}
          </button>
          <input ref={bazarrFileRef} type="file" accept=".yaml,.yml,.ini,.cfg,.db,.zip" onChange={handleBazarrFile} className="hidden" />
        </div>
      </div>

      {/* Bazarr Preview */}
      {bazarrPreview && (
        <BazarrImportPreview
          preview={bazarrPreview}
          onConfirm={handleBazarrConfirm}
          onCancel={() => {
            setBazarrPreview(null)
            setBazarrFile(null)
          }}
          isPending={confirmBazarr.isPending}
        />
      )}

      {/* Service Cards */}
      <div className="grid gap-3">
        {services.map((service: ApiKeyService) => (
          <ServiceKeyCard
            key={service.service}
            service={service}
            onUpdate={handleUpdate}
            onTest={handleTest}
            onRotate={handleRotate}
            rotating={rotateKey.isPending}
          />
        ))}
      </div>

      {services.length === 0 && (
        <div
          className="rounded-lg p-8 text-center bg-surface border border-border"
        >
          <Shield size={32} className="mx-auto mb-2 text-muted" />
          <p className="text-sm text-muted">
            {t('apiKeys.noServices', 'No API key services found.')}
          </p>
        </div>
      )}
    </div>
  )
}
