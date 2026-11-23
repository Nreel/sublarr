import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect } from 'vitest'
import { buildOnboardingPayload } from '../pages/Onboarding'

// The wizard's initial values (Onboarding.tsx), with providers filled in.
// ARR credentials and media servers are saved by their own step branches
// (instance JSON blobs / PUT /mediaservers), not through this payload.
const VALUES = {
  opensubtitles_api_key: '',
  jimaku_api_key: '',
  subdl_api_key: '',
  interface_language: 'en',
  tmdb_api_key: 'tmdb',
  tvdb_api_key: '',
  automation_enabled: 'true',
  search_interval_hours: '6',
  upgrade_enabled: 'true',
  path_mapping: '/data/media=/media',
};

// Discord install-help 2026-10-31: 1.18.3 refused every wizard step with
// "Unknown config key: automation_enabled", and the untouched Ollama default
// as a loopback URL, so nothing from the wizard (path mapping included) was saved.
describe('buildOnboardingPayload', () => {
  it('sends no wizard-only keys', () => {
    const payload = buildOnboardingPayload(VALUES, 'arr')

    expect(payload).not.toHaveProperty('automation_enabled')
    expect(payload).not.toHaveProperty('search_interval_hours')
  });

  it('saves the automation choice as the wanted-search interval', () => {
    expect(buildOnboardingPayload(VALUES, 'arr').wanted_search_interval_hours).toBe('6')
    expect(
      buildOnboardingPayload({ ...VALUES, automation_enabled: 'false' }, 'arr').wanted_search_interval_hours,
    ).toBe('0')
  });

  it('keeps the path mapping and drops the other mode and empty values', () => {
    const arr = buildOnboardingPayload(VALUES, 'arr')
    expect(arr.path_mapping).toBe('/data/media=/media')
    expect(arr).not.toHaveProperty('tmdb_api_key')

    const standalone = buildOnboardingPayload(VALUES, 'standalone')
    expect(standalone).not.toHaveProperty('path_mapping')
    expect(standalone.tmdb_api_key).toBe('tmdb')
  });
});

// The contract with the backend: backend/tests/test_onboarding_payload_accepted.py
// sends exactly this file through the real PUT /config validator. Regenerate
// with UPDATE_CONTRACTS=1 after an intended change; CI only compares (#61 S1).
describe('onboarding payload contract', () => {
  it('matches the file the backend test sends', () => {
    const contract = {
      arr: buildOnboardingPayload({ ...VALUES, opensubtitles_api_key: 'k', jimaku_api_key: 'k', subdl_api_key: 'k' }, 'arr'),
      standalone: buildOnboardingPayload({ ...VALUES, tvdb_api_key: 'k' }, 'standalone'),
      automation_off: buildOnboardingPayload({ ...VALUES, automation_enabled: 'false' }, 'arr'),
    }
    const file = resolve(import.meta.dirname, '__contracts__/onboarding-payload.json')
    if (process.env.UPDATE_CONTRACTS) writeFileSync(file, JSON.stringify(contract, null, 2) + '\n')
    // Compared as data, so a CRLF checkout of the file still matches (#66).
    expect(JSON.parse(readFileSync(file, 'utf-8'))).toEqual(contract)
  })
})
