/**
 * HealthPage provider STATE column: one verdict per provider. An auto-disabled
 * provider used to render the word "Auto-disabled" twice — once as the state
 * chip, once as the status_reason badge, which says the same thing under
 * another key. The chip is the breaker state; the badge is the reason.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { HealthPage } from '@/pages/HealthPage';
import type { LibraryHealth } from '@/api/system/healthLibrary';

vi.mock('react-i18next', () => ({
  // Keys, not translations: the assertion is about which controls render, not
  // which words the catalogs happen to hold.
  useTranslation: () => ({ t: (key: string) => key }),
}));

const health: LibraryHealth = {
  totals: {
    wanted: 0,
    problems: 0,
    unmatched: 0,
    providers_degraded: 1,
    providers_no_activity: 0,
  },
  problems: [],
  providers: [
    {
      provider: 'tvsubtitles',
      breaker_state: 'closed',
      breaker_failures: 0,
      searches: 6,
      hit_rate: 0,
      failed_downloads: 6,
      auto_disabled: true,
      degraded: true,
      status_reason: 'auto_disabled',
    },
    {
      provider: 'addic7ed',
      breaker_state: 'closed',
      breaker_failures: 0,
      searches: 8,
      hit_rate: 0.5,
      failed_downloads: 0,
      auto_disabled: false,
      degraded: false,
      status_reason: 'ok',
    },
    {
      provider: 'brokenhost',
      breaker_state: 'open',
      breaker_failures: 7,
      searches: 4,
      hit_rate: 0,
      failed_downloads: 0,
      auto_disabled: false,
      degraded: true,
      status_reason: 'circuit_open',
    },
  ],
  translation: {
    failures_7d: 0,
    stuck_items: 0,
    backends: [],
    recent_errors: [],
    pipeline_errors: [],
  },
};

vi.mock('@/api/system/healthLibrary', () => ({
  getLibraryHealth: async () => health,
}));

async function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <HealthPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText('providers.title');
}

describe('HealthPage provider state column', () => {
  it('renders the auto-disabled verdict once', async () => {
    await renderPage();
    expect(screen.getAllByText('badges.auto_disabled.label')).toHaveLength(1);
    // Only the healthy provider's closed breaker produces an "OK" chip; the
    // auto-disabled one (also a closed breaker) produces no chip at all.
    expect(screen.getAllByText('providers.state_closed')).toHaveLength(1);
  });

  it('keeps the breaker-state chip for providers that are not switched off', async () => {
    await renderPage();
    expect(screen.getByText('providers.state_closed')).toBeInTheDocument();
    expect(screen.getByText('providers.state_open')).toBeInTheDocument();
    expect(screen.getByText('badges.circuit_open.label')).toBeInTheDocument();
  });
});
