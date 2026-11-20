import { X, ArrowUp, ArrowDown } from 'lucide-react'
import { settingsInputStyle } from '@/styles/settingsShared'
import { useTranslation } from 'react-i18next'

interface LanguageOption {
  readonly value: string
  readonly label: string
}

interface Props {
  readonly value: string[]
  readonly options: readonly LanguageOption[]
  readonly onChange: (newValue: string[]) => void
  readonly placeholder?: string
  /** Passed to the dropdown <select> for tests that target a specific picker. */
  readonly testId?: string
  /**
   * Selection order carries priority: first pill = most preferred, last =
   * least. Pills then show their rank plus move-up/move-down controls.
   */
  readonly ordered?: boolean
}

export function LanguagePillSelector({
  value,
  options,
  onChange,
  placeholder = '— Add language —',
  ordered = false,
  testId,
}: Props) {
  const { t: tc } = useTranslation('common')
  const available = options.filter((o) => !value.includes(o.value))

  const remove = (lang: string) => onChange(value.filter((v) => v !== lang))

  const add = (lang: string) => {
    if (lang && !value.includes(lang)) onChange([...value, lang])
  }

  const move = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= value.length) return
    const next = [...value]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '6px',
          minHeight: '36px',
          padding: '6px 8px',
          background: 'var(--bg-primary)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          alignItems: 'center',
        }}
      >
        {value.map((lang, i) => {
          const opt = options.find((o) => o.value === lang)
          return (
            <span
              key={lang}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                background: 'var(--accent-bg)',
                border: '1px solid var(--accent-dim)',
                borderRadius: '4px',
                padding: '3px 8px',
                fontSize: '12px',
                color: 'var(--accent)',
              }}
            >
              {ordered && (
                <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {i + 1}
                </span>
              )}
              {opt?.label ?? lang}
              {ordered && (
                <>
                  <button
                    type="button"
                    aria-label={tc('ui.move_priority_up', 'Move up')}
                    title={tc('ui.move_priority_up', 'Move up')}
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      background: 'none',
                      border: 'none',
                      color: i === 0 ? 'var(--border)' : 'var(--text-muted)',
                      cursor: i === 0 ? 'default' : 'pointer',
                      padding: 0,
                      marginLeft: '2px',
                    }}
                  >
                    <ArrowUp size={11} />
                  </button>
                  <button
                    type="button"
                    aria-label={tc('ui.move_priority_down', 'Move down')}
                    title={tc('ui.move_priority_down', 'Move down')}
                    disabled={i === value.length - 1}
                    onClick={() => move(i, 1)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      background: 'none',
                      border: 'none',
                      color: i === value.length - 1 ? 'var(--border)' : 'var(--text-muted)',
                      cursor: i === value.length - 1 ? 'default' : 'pointer',
                      padding: 0,
                    }}
                  >
                    <ArrowDown size={11} />
                  </button>
                </>
              )}
              <button
                type="button"
                aria-label={tc('ui.remove')}
                onClick={() => remove(lang)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: 0,
                  marginLeft: '2px',
                }}
              >
                <X size={11} />
              </button>
            </span>
          )
        })}
        {value.length === 0 && (
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>—</span>
        )}
      </div>

      {available.length > 0 && (
        <select
          data-testid={testId}
          value=""
          onChange={(e) => {
            add(e.target.value)
            e.target.value = ''
          }}
          style={{ ...settingsInputStyle, width: '220px', fontSize: '12px' }}
        >
          <option value="">{placeholder}</option>
          {available.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </div>
  )
}
