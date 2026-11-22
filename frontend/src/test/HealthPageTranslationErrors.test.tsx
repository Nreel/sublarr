/**
 * HealthPage translation block — pipeline failures (jobs with no backend
 * event) must be listed here, not only behind an episode's History button.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { HealthPage } from '@/pages/HealthPage';
import type { LibraryHealth } from '@/api/system/healthLibrary';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key.split('.').pop() ?? key }),
}));

const health: LibraryHealth = {
  totals: {
    wanted: 1,
    problems: 0,
    unmatched: 0,
    series_affected: 1,
    providers_degraded: 0,
    providers_no_activity: 0,
  },
  series: [],
  problems: [],
  providers: [],
  translation: {
    failures_7d: 1,
    stuck_items: 0,
    backends: [
      {
        backend: 'openai_compat',
        requests: 42,
        failed: 0,
        consecutive_failures: 0,
        last_error: '',
        last_failure_at: null,
        last_success_at: null,
      },
    ],
    recent_errors: [],
    pipeline_errors: [
      {
        job_id: 'a1b2c3d4',
        file_path: '/media/Show A/Show A - S01E01.mkv',
        source_format: 'ass',
        error: 'No source subtitle found to translate from',
        created_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
        completed_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
      },
    ],
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
    </QueryClientProvider>
  );
  await screen.findByText('openai_compat');
}

describe('HealthPage translation health', () => {
  it('lists pipeline failures with their error text', async () => {
    await renderPage();
    expect(await screen.findByText('No source subtitle found to translate from')).toBeTruthy();
    expect(screen.getByText('Show A - S01E01.mkv')).toBeTruthy();
    expect(screen.getByText('pipeline_title')).toBeTruthy();
    // The reassuring empty state must not sit next to a listed failure.
    expect(screen.queryByText('empty_errors')).toBeNull();
  });

  it('keeps the empty state when nothing failed', async () => {
    health.translation.pipeline_errors = [];
    await renderPage();
    expect(await screen.findByText('empty_errors')).toBeTruthy();
  });
});
