/**
 * HealthPage failure sections: scheduler ticks, whisper, video sync, ops,
 * hooks, backup/notifications. Each section only renders when it has rows.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { HealthPage } from '@/pages/HealthPage';
import type { LibraryHealth } from '@/api/system/healthLibrary';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const recent = () => new Date(Date.now() - 2 * 86_400_000).toISOString();

const health: LibraryHealth = {
  totals: {
    wanted: 1,
    problems: 0,
    unmatched: 0,
    providers_degraded: 0,
    providers_no_activity: 0,
  },
  problems: [],
  providers: [],
  translation: {
    failures_7d: 0,
    stuck_items: 0,
    backends: [],
    recent_errors: [],
    pipeline_errors: [],
  },
  scheduler_errors: [
    {
      job_id: 'subtitle_automation',
      status: 'timeout_not_started',
      error_type: 'BlockedByOverlap',
      error_msg: 'previous run still active',
      started_at: recent(),
      triggered_by: 'scheduler',
    },
  ],
  whisper_errors: [
    {
      job_id: 'wh-1',
      file_path: '/media/Show B/Show B - S01E02.mkv',
      backend_name: 'llama.cpp',
      status: 'failed',
      error: 'backend returned 500',
      completed_at: recent(),
    },
  ],
  sync_errors: [
    {
      job_id: 'ffsubsync',
      file_path: '/media/Show C/Show C - S02E03.mkv',
      status: 'failed',
      error: 'engine crashed',
      started_at: recent(),
    },
  ],
  ops_errors: [
    {
      event_type: 'remux',
      file_path: '/media/Show D/Show D.mkv',
      error: 'ffmpeg exit 1',
      created_at: recent(),
    },
  ],
  hook_errors: [
    { hook: 'on_download', error: 'script exit 3', created_at: recent() },
  ],
  backup_errors: [
    { event_type: 'backup_failed', error: 'disk full', created_at: recent() },
  ],
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
  await screen.findByText('subtitle_automation');
}

describe('HealthPage activity failure sections', () => {
  it('renders every populated failure section with its rows', async () => {
    await renderPage();
    expect(screen.getByText('sections.scheduler.title')).toBeTruthy();
    expect(screen.getByText('previous run still active')).toBeTruthy();
    expect(screen.getByText('scheduler')).toBeTruthy();

    expect(screen.getByText('sections.whisper.title')).toBeTruthy();
    expect(screen.getByText('Show B - S01E02.mkv')).toBeTruthy();
    expect(screen.getByText('llama.cpp')).toBeTruthy();
    expect(screen.getByText('backend returned 500')).toBeTruthy();

    expect(screen.getByText('sections.sync.title')).toBeTruthy();
    expect(screen.getByText('Show C - S02E03.mkv')).toBeTruthy();
    expect(screen.getByText('ffsubsync')).toBeTruthy();
    expect(screen.getByText('engine crashed')).toBeTruthy();

    expect(screen.getByText('sections.ops.title')).toBeTruthy();
    expect(screen.getByText('Show D.mkv')).toBeTruthy();
    expect(screen.getByText('ffmpeg exit 1')).toBeTruthy();

    expect(screen.getByText('sections.hooks.title')).toBeTruthy();
    expect(screen.getByText('on_download')).toBeTruthy();
    expect(screen.getByText('script exit 3')).toBeTruthy();

    expect(screen.getByText('sections.backups.title')).toBeTruthy();
    expect(screen.getByText('disk full')).toBeTruthy();
  });

  it('renders nothing for absent failure sections', async () => {
    health.scheduler_errors = [];
    health.whisper_errors = [];
    health.sync_errors = [];
    health.ops_errors = [];
    health.hook_errors = [];
    health.backup_errors = [];
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <HealthPage />
        </MemoryRouter>
      </QueryClientProvider>
    );
    await screen.findByText('title');
    expect(screen.queryByText('sections.scheduler.title')).toBeNull();
    expect(screen.queryByText('sections.whisper.title')).toBeNull();
    expect(screen.queryByText('sections.sync.title')).toBeNull();
    expect(screen.queryByText('sections.ops.title')).toBeNull();
    expect(screen.queryByText('sections.hooks.title')).toBeNull();
    expect(screen.queryByText('sections.backups.title')).toBeNull();
  });
});
