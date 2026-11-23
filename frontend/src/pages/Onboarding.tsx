import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  updateConfig,
  completeOnboarding,
  getMediaServerTypes,
  getMediaServerInstances,
  saveMediaServerInstances,
  testMediaServer,
  saveWatchedFolder,
  triggerStandaloneScan,
  getScoringPreset,
  importScoringPreset,
  getSetupStatus,
  completeSetup,
  getConfig,
  getOnboardingStatus,
} from '@/api/client';
import type { SetupBenchmark, SetupProfile } from '@/api/health';
import { testSonarrInstance, testRadarrInstance, testApiKey } from '@/api/settings';
import { toast } from '@/components/shared/Toast';
import { apiErrorMessage } from '@/lib/apiError';
import {
  Loader2,
  CheckCircle,
  ArrowRight,
  ArrowLeft,
  Server,
  Globe,
  Search,
  Play,
  Monitor,
  Plus,
  RotateCcw,
  TestTube,
  Trash2,
  Eye,
  EyeOff,
  FolderOpen,
  Languages,
  Zap,
  AlertCircle,
  Clapperboard,
  Sparkles,
  Library,
  Gauge,
} from 'lucide-react';
import { INTERFACE_LANGUAGE_OPTIONS } from '@/styles/settingsShared';
import { LanguageProfilesTab } from '@/pages/Settings/LanguageProfilesTab';
import {
  parseInstances,
  serializeInstances,
  generateId,
  type ServiceInstance,
} from '@/pages/Settings/connections/ConnectionsMediaServers';

import type { MediaServerType, MediaServerInstance, MediaServerTestResult } from '@/lib/types';

export const ALL_STEPS = [
  { id: 'mode', titleKey: 'steps.mode', icon: Server, descKey: 'mode_step.description' },
  { id: 'library', titleKey: 'steps.library', icon: Library, descKey: 'library_step.description' },
  { id: 'arr', titleKey: 'steps.arr', icon: Server, descKey: 'arr_step.description' },
  {
    id: 'standalone',
    titleKey: 'steps.standalone',
    icon: FolderOpen,
    descKey: 'standalone_step.description',
  },
  {
    id: 'pathmapping',
    titleKey: 'steps.pathmapping',
    icon: Globe,
    descKey: 'pathmapping_step.description',
  },
  {
    id: 'language',
    titleKey: 'steps.language',
    icon: Languages,
    descKey: 'language_step.description',
  },
  {
    id: 'providers',
    titleKey: 'steps.providers',
    icon: Search,
    descKey: 'providers_step.description',
  },
  {
    id: 'automation',
    titleKey: 'steps.automation',
    icon: Zap,
    descKey: 'automation_step.description',
  },
  {
    id: 'mediaservers',
    titleKey: 'steps.mediaservers',
    icon: Monitor,
    descKey: 'mediaservers_step.description',
  },
  {
    id: 'performance',
    titleKey: 'steps.performance',
    icon: Gauge,
    descKey: 'performance_step.description',
  },
  { id: 'scan', titleKey: 'steps.scan', icon: Play, descKey: 'scan_step.description' },
];

export function getVisibleSteps(setupMode: 'arr' | 'standalone' | null) {
  if (!setupMode) return [ALL_STEPS[0]]; // only setup mode step
  if (setupMode === 'arr') {
    return ALL_STEPS.filter(s =>
      [
        'mode',
        'library',
        'arr',
        'pathmapping',
        'language',
        'providers',
        'automation',
        'mediaservers',
        'performance',
        'scan',
      ].includes(s.id)
    );
  }
  // standalone: skip arr and pathmapping
  return ALL_STEPS.filter(s =>
    [
      'mode',
      'library',
      'standalone',
      'language',
      'providers',
      'automation',
      'mediaservers',
      'performance',
      'scan',
    ].includes(s.id)
  );
}

export type LibraryType = 'anime' | 'movies' | 'mixed';

// Which bundled scoring preset each library type applies. `mixed` keeps the
// (already anime-first, balanced) defaults untouched.
export const LIBRARY_TYPE_PRESET: Record<LibraryType, string | null> = {
  anime: 'Anime',
  movies: 'Movies',
  mixed: null,
};

export interface MappingRow {
  remote: string;
  local: string;
}

/** `remote=local` pairs separated by `;` (same format Settings uses). */
export function parseMappings(raw: string): MappingRow[] {
  return raw
    .split(';')
    .map(part => {
      const i = part.indexOf('=');
      if (i < 0) return null;
      return { remote: part.slice(0, i).trim(), local: part.slice(i + 1).trim() };
    })
    .filter((row): row is MappingRow => row !== null && row.remote !== '' && row.local !== '');
}

export function serializeMappings(rows: MappingRow[]): string {
  return rows
    .filter(r => r.remote.trim() && r.local.trim())
    .map(r => `${r.remote.trim()}=${r.local.trim()}`)
    .join(';');
}

const INTERVAL_OPTIONS = ['1', '3', '6', '12', '24'];
/** Nearest wizard interval option for a stored interval outside the presets. */
export function nearestInterval(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '6';
  return INTERVAL_OPTIONS.reduce(
    (best, opt) => (Math.abs(Number(opt) - n) < Math.abs(Number(best) - n) ? opt : best),
    INTERVAL_OPTIONS[0]
  );
}

export type OnboardingValues = Record<string, string>;

// Keys of `values` that only drive the wizard's own controls. The backend
// knows no such settings and refuses the whole save on an unknown key, which
// left every wizard step at "Failed to save settings" from 1.14.0 to 1.18.3.
const UI_ONLY_KEYS = ['automation_enabled', 'search_interval_hours'] as const;
export const ARR_ONLY_KEYS = [
  'sonarr_instances_json',
  'radarr_instances_json',
  'path_mapping',
] as const;
export const STANDALONE_ONLY_KEYS = ['tmdb_api_key', 'tvdb_api_key'] as const;
/** The config the wizard saves: non-empty values of the chosen setup mode,
 *  with the automation toggle and interval as the wanted-search interval. */
export function buildOnboardingPayload(
  values: OnboardingValues,
  setupMode: 'arr' | 'standalone' | null
): Record<string, string> {
  const payload: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) {
    if (v) payload[k] = v;
  }
  const otherMode =
    setupMode === 'arr' ? STANDALONE_ONLY_KEYS : setupMode === 'standalone' ? ARR_ONLY_KEYS : [];
  for (const k of [...otherMode, ...UI_ONLY_KEYS]) delete payload[k];
  if (values.automation_enabled) {
    payload.wanted_search_interval_hours =
      values.automation_enabled === 'true' ? values.search_interval_hours || '24' : '0';
  }
  return payload;
}

const inputStyle = {
  backgroundColor: 'var(--bg-primary)',
  border: '1px solid var(--border)',
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: '13px',
};

// Module-level Field input (B1). Defining inputs inside the parent component
// remounts the underlying <input> on every render, which drops keyboard focus
// after every keystroke. Caller resolves value + onChange explicitly so this
// component carries no closure over parent state.
type FieldProps = {
  label: string;
  type?: string;
  placeholder?: string;
  value: string;
  onChange: (next: string) => void;
  autoComplete?: string;
};

function Field({
  label,
  type = 'text',
  placeholder = '',
  value,
  onChange,
  autoComplete,
}: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete ?? (type === 'password' ? 'new-password' : 'off')}
        spellCheck={false}
        className="w-full px-3 py-2 rounded-md text-sm focus:outline-none"
        style={inputStyle}
      />
    </div>
  );
}

let _uid = 0;
const nextUid = () => `ms-${++_uid}-${Date.now().toString(36)}`;

export default function Onboarding() {
  const { t, i18n } = useTranslation('onboarding');
  const { t: tc } = useTranslation('common');
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  // Tracks which connection test is in-flight ('sonarr' | 'radarr' | null)
  // so concurrent click on a different button doesn't show the wrong spinner.
  const [testing, setTesting] = useState<string | null>(null);
  const [scanStarted, setScanStarted] = useState(false);
  const [setupMode, setSetupMode] = useState<'arr' | 'standalone' | null>(null);
  const [libraryType, setLibraryType] = useState<LibraryType | null>(null);

  // Re-run (Settings → General → "Re-run onboarding"): the wizard preloads the
  // current settings so every step shows what is already configured. A fresh
  // install keeps the wizard defaults.
  const [rerun, setRerun] = useState(false);

  // Sonarr/Radarr multi-instance rows — same shape and storage as Settings
  // (sonarr_instances_json / radarr_instances_json; masked secrets are
  // restored server-side by deep_unmask_blob on save).
  const [sonarrInsts, setSonarrInsts] = useState<ServiceInstance[]>([]);
  const [radarrInsts, setRadarrInsts] = useState<ServiceInstance[]>([]);
  const [instStatus, setInstStatus] = useState<
    Record<string, { testing: boolean; healthy: boolean | null; message: string }>
  >({});

  // Path mapping rows — serialized to the `path_mapping` string on save.
  const [mappingRows, setMappingRows] = useState<MappingRow[]>([]);


  // Performance profile step (consolidates the former FirstRunWizard modal)
  const [benchmark, setBenchmark] = useState<SetupBenchmark | null>(null);
  const [perfProfile, setPerfProfile] = useState<SetupProfile | null>(null);

  const visibleSteps = getVisibleSteps(setupMode);
  const currentStepDef = visibleSteps[step] || visibleSteps[0];

  // Standalone folder state
  const [standaloneFolders, setStandaloneFolders] = useState<{ path: string; label: string }[]>([]);
  const [newFolderPath, setNewFolderPath] = useState('');

  const [values, setValues] = useState({
    opensubtitles_api_key: '',
    jimaku_api_key: '',
    subdl_api_key: '',
    // Starts at the language the wizard itself is rendered in, so the
    // dropdown matches what the user sees before touching it.
    interface_language: i18n.language?.startsWith('en') ? 'en' : 'de',
    tmdb_api_key: '',
    tvdb_api_key: '',
    automation_enabled: 'true',
    search_interval_hours: '6',
    upgrade_enabled: 'true',
  });

  // Media server state.
  // Stable per-instance ids decouple show-password / test-result state from the
  // array index, so removing instance #1 doesn't shift visibility flags from #2
  // onto the wrong row (N1). Two parallel arrays kept in sync via add/remove.
  const [msTypes, setMsTypes] = useState<MediaServerType[]>([]);
  const [msInstances, setMsInstances] = useState<MediaServerInstance[]>([]);
  const msInstanceIds = useRef<string[]>([]);
  const [msTestResults, setMsTestResults] = useState<
    Record<string, MediaServerTestResult | 'testing'>
  >({});
  const [msShowPasswords, setMsShowPasswords] = useState<Record<string, boolean>>({});
  const [msTypesError, setMsTypesError] = useState(false);

  // Load media server types when reaching that step. On failure we surface a
  // retry button (N3); the previous catch block ignored the error so users sat
  // in front of an indefinite loading spinner.
  const loadMsTypes = () => {
    setMsTypesError(false);
    getMediaServerTypes()
      .then(ts => setMsTypes(ts))
      .catch(() => setMsTypesError(true));
  };

  useEffect(() => {
    if (currentStepDef.id === 'mediaservers' && msTypes.length === 0 && !msTypesError) {
      loadMsTypes();
    }
  }, [currentStepDef.id, msTypes.length, msTypesError]);

  // Fetch the hardware benchmark when the performance step becomes visible so
  // the recommended profile card is pre-selected.
  useEffect(() => {
    if (currentStepDef.id === 'performance' && !benchmark) {
      getSetupStatus()
        .then(s => {
          setBenchmark(s.benchmark);
          setPerfProfile(prev => prev ?? s.benchmark.recommended_profile);
        })
        .catch(() => {
          // Benchmark unavailable — fall back to 'balanced' as selectable default.
          setPerfProfile(prev => prev ?? 'balanced');
        });
    }
  }, [currentStepDef.id, benchmark]);

  // Re-run prefill: mirror the stored settings into the wizard state so each
  // step shows the current configuration (mirrors Settings pages).
  useEffect(() => {
    let cancelled = false;
    getOnboardingStatus()
      .then(status => {
        if (!status.completed || cancelled) return;
        setRerun(true);
        getConfig()
          .then(cfg => {
            if (cancelled) return;
            const c = cfg as Record<string, unknown>;
            setSetupMode(String(c.standalone_enabled ?? '') === 'true' ? 'standalone' : 'arr');
            const lt = String(c.library_type ?? '');
            if (lt === 'anime' || lt === 'movies' || lt === 'mixed') {
              setLibraryType(lt as LibraryType);
            }
            setSonarrInsts(parseInstances(c.sonarr_instances_json));
            setRadarrInsts(parseInstances(c.radarr_instances_json));
            setMappingRows(parseMappings(String(c.path_mapping ?? '')));
            setValues(v => ({
              ...v,
              interface_language:
                typeof c.interface_language === 'string' ? c.interface_language : v.interface_language,
              automation_enabled:
                String(c.wanted_search_interval_hours ?? '') === '0' ? 'false' : 'true',
              search_interval_hours: nearestInterval(c.wanted_search_interval_hours),
              upgrade_enabled: String(c.upgrade_enabled ?? 'true') === 'false' ? 'false' : 'true',
            }));
            const sp = String(c.scheduler_profile ?? '');
            if (sp === 'light' || sp === 'balanced' || sp === 'aggressive') {
              setPerfProfile(prev => prev ?? (sp as SetupProfile));
            }
          })
          .catch(() => {});
        getMediaServerInstances()
          .then(insts => {
            if (cancelled) return;
            setMsInstances(insts);
            msInstanceIds.current = insts.map(() => nextUid());
          })
          .catch(() => {});
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);


  const set = (key: string, val: string) => setValues(v => ({ ...v, [key]: val }));

  // Keys that only apply to one setup mode (ARR_ONLY_KEYS /
  // STANDALONE_ONLY_KEYS): buildOnboardingPayload filters by setupMode so a
  // user who fills Sonarr credentials, goes back, and switches to standalone
  // doesn't POST the stale Sonarr keys (B16).

  const saveAndNext = async () => {
    setSaving(true);
    try {
      // Library-type step: persist the choice (so a wizard re-run preselects
      // it) and apply the matching bundled scoring preset (if any).
      if (currentStepDef.id === 'library') {
        await updateConfig({ library_type: libraryType ?? 'mixed' });
        const presetName = libraryType ? LIBRARY_TYPE_PRESET[libraryType] : null;
        if (presetName) {
          try {
            const preset = await getScoringPreset(presetName);
            await importScoringPreset(preset);
            toast(t('library_step.preset_applied', { preset: presetName }));
          } catch {
            toast(t('library_step.preset_failed'), 'error');
          }
        }
        setStep(s => s + 1);
        return;
      }

      // Performance step: apply the chosen scheduler profile via the same
      // endpoint the former FirstRunWizard modal used. This also sets
      // setup_wizard_completed=true so the modal never shows afterwards.
      if (currentStepDef.id === 'performance') {
        try {
          await completeSetup(perfProfile ?? 'balanced');
        } catch {
          toast(t('performance_step.apply_failed'), 'error');
        }
        setStep(s => s + 1);
        return;
      }

      const toSave = buildOnboardingPayload(values, setupMode);

      if (currentStepDef.id === 'standalone') {
        toSave.standalone_enabled = 'true';
        await updateConfig(toSave);
        // Save folders concurrently so one bad path doesn't block the rest (B11).
        const folderPayloads = standaloneFolders
          .filter(f => f.path.trim())
          .map(folder =>
            saveWatchedFolder({
              path: folder.path.trim(),
              label: folder.label.trim(),
              media_type: 'auto',
              enabled: true,
            })
          );
        const folderResults = await Promise.allSettled(folderPayloads);
        const rejected = folderResults.filter(
          (r): r is PromiseRejectedResult => r.status === 'rejected'
        );
        if (rejected.length > 0) {
          // Show why (e.g. a folder outside the media folder), not just how many.
          toast(
            apiErrorMessage(
              rejected[0].reason,
              t('errors.folder_save', { count: rejected.length })
            ),
            'error'
          );
        }
      } else if (currentStepDef.id === 'arr') {
        // Multi-instance blobs like Settings → Connections; rows with no url
        // and no key are dropped. A masked key round-trips via deep_unmask_blob.
        await updateConfig({
          ...toSave,
          sonarr_instances_json: serializeInstances(
            sonarrInsts.filter(i => i.url.trim() || i.api_key.trim())
          ),
          radarr_instances_json: serializeInstances(
            radarrInsts.filter(i => i.url.trim() || i.api_key.trim())
          ),
        });
      } else if (currentStepDef.id === 'pathmapping') {
        await updateConfig({ ...toSave, path_mapping: serializeMappings(mappingRows) });
      } else {
        await updateConfig(toSave);
      }

      // Save the full instance list — empty means "remove all", matching
      // Settings; skip if the type catalog failed to load so we don't wipe
      // stored servers we couldn't render.
      if (currentStepDef.id === 'mediaservers' && msTypes.length > 0) {
        await saveMediaServerInstances(msInstances);
      }

      setStep(s => s + 1);
    } catch (err) {
      // Say why (e.g. "Invalid URL for ollama_url: …"), not just that it failed.
      toast(apiErrorMessage(err, t('errors.save_failed')), 'error');
    } finally {
      setSaving(false);
    }
  };

  // Inline connection test for arr-step instance rows. Sonarr/Radarr have a
  // dedicated `/instances/test` endpoint that accepts {url, api_key} — masked
  // stored keys resolve server-side — so we validate without persisting first.
  const testInstanceConnection = async (which: 'sonarr' | 'radarr', inst: ServiceInstance) => {
    if (!inst.url.trim()) return;
    setInstStatus(s => ({ ...s, [inst.id]: { testing: true, healthy: null, message: '' } }));
    try {
      const fn = which === 'sonarr' ? testSonarrInstance : testRadarrInstance;
      const result = await fn({ url: inst.url.trim(), api_key: inst.api_key.trim() });
      setInstStatus(s => ({
        ...s,
        [inst.id]: {
          testing: false,
          healthy: result.healthy,
          message: result.message || (result.healthy ? 'OK' : 'Error'),
        },
      }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setInstStatus(s => ({
        ...s,
        [inst.id]: { testing: false, healthy: false, message: msg },
      }));
    }
  };

  const addInstance = (which: 'sonarr' | 'radarr') => {
    const prefix = which === 'sonarr' ? 'Sonarr' : 'Radarr';
    const newInst: ServiceInstance = {
      id: generateId(),
      name: `${prefix} ${(which === 'sonarr' ? sonarrInsts : radarrInsts).length + 1}`,
      url: '',
      api_key: '',
    };
    if (which === 'sonarr') setSonarrInsts(prev => [...prev, newInst]);
    else setRadarrInsts(prev => [...prev, newInst]);
  };

  const updateInstance = (
    which: 'sonarr' | 'radarr',
    id: string,
    patch: Partial<ServiceInstance>
  ) => {
    const setter = which === 'sonarr' ? setSonarrInsts : setRadarrInsts;
    setter(prev => prev.map(i => (i.id === id ? { ...i, ...patch } : i)));
  };

  const removeInstance = (which: 'sonarr' | 'radarr', id: string) => {
    const setter = which === 'sonarr' ? setSonarrInsts : setRadarrInsts;
    setter(prev => prev.filter(i => i.id !== id));
    setInstStatus(prev => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  // TMDB/TVDB tests require the key to be persisted first (the backend test_fn
  // looks up the client from saved config). Persist then test.
  const runApiKeyTest = async (service: 'tmdb' | 'tvdb') => {
    const key = service === 'tmdb' ? values.tmdb_api_key : values.tvdb_api_key;
    if (!key) return;
    setTesting(service);
    try {
      await updateConfig({ [`${service}_api_key`]: key });
      const result = await testApiKey(service);
      toast(`${service}: ${result.message}`, result.success ? 'success' : 'error');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast(`${service}: ${msg}`, 'error');
    } finally {
      setTesting(null);
    }
  };

  const startScan = async () => {
    try {
      if (setupMode === 'standalone') {
        await triggerStandaloneScan();
        setScanStarted(true);
        toast(t('scan_step.standalone_scan_started'));
      } else {
        const { refreshWanted } = await import('@/api/client');
        await refreshWanted();
        setScanStarted(true);
        toast(t('scan_step.wanted_scan_started'));
      }
    } catch {
      toast(t('scan_step.scan_failed'), 'error');
    }
  };

  const finish = async () => {
    try {
      await completeOnboarding();
      navigate('/');
    } catch {
      // Don't swallow — user needs to know finalisation failed so they can retry (B6).
      toast(t('errors.complete_failed'), 'error');
    }
  };

  // "Skip Setup" should still mark onboarding complete on the backend; otherwise
  // the wizard is shown again on the next visit and any partially-saved config
  // is left in limbo (N2).
  const skipSetup = async () => {
    try {
      await completeOnboarding();
    } catch {
      // best-effort: navigation still happens so the user is unblocked.
    }
    navigate('/');
  };

  // Switching setup mode mid-flow must not POST the other mode's keys (B16).
  // ARR credentials live in instance-row state that only the arr step saves,
  // so switching to standalone needs no clearing there.
  const chooseSetupMode = (mode: 'arr' | 'standalone') => {
    setSetupMode(mode);
    setStep(1);
    if (mode === 'arr') {
      setValues(v => {
        const next = { ...v };
        for (const k of STANDALONE_ONLY_KEYS) next[k] = '';
        return next;
      });
    }
  };

  // "Reset to defaults" reverts this step's controls to the wizard defaults;
  // it reaches the backend only when the user advances with Next. The
  // Language step has no reset button — profiles are database records managed
  // in the step itself (add, edit, delete), like Settings → Languages.
  const resetStep = () => {
    switch (currentStepDef.id) {
      case 'mode':
        setSetupMode(null);
        break;
      case 'library':
        setLibraryType(null);
        break;
      case 'arr':
        setSonarrInsts([]);
        setRadarrInsts([]);
        setInstStatus({});
        break;
      case 'standalone':
        setValues(v => ({ ...v, tmdb_api_key: '', tvdb_api_key: '' }));
        setStandaloneFolders([]);
        setNewFolderPath('');
        break;
      case 'pathmapping':
        setMappingRows([]);
        break;
      case 'automation':
        setValues(v => ({
          ...v,
          automation_enabled: 'true',
          search_interval_hours: '6',
          upgrade_enabled: 'true',
        }));
        break;
      case 'mediaservers':
        setMsInstances([]);
        msInstanceIds.current = [];
        setMsTestResults({});
        setMsShowPasswords({});
        break;
      case 'performance':
        setPerfProfile(benchmark?.recommended_profile ?? 'balanced');
        break;
      default:
        break;
    }
  };

  // Media server helpers
  const addMediaServer = (serverType: MediaServerType) => {
    const newInst: MediaServerInstance = {
      type: serverType.name,
      name: serverType.display_name,
      enabled: true,
    };
    for (const field of serverType.config_fields) {
      newInst[field.key] = field.default ?? '';
    }
    msInstanceIds.current = [...msInstanceIds.current, nextUid()];
    setMsInstances(prev => [...prev, newInst]);
  };

  const updateMsField = (idx: number, key: string, value: unknown) => {
    setMsInstances(prev => {
      const updated = [...prev];
      updated[idx] = { ...updated[idx], [key]: value };
      return updated;
    });
  };

  const removeMsInstance = (idx: number) => {
    const removedId = msInstanceIds.current[idx];
    msInstanceIds.current = msInstanceIds.current.filter((_, i) => i !== idx);
    setMsInstances(prev => prev.filter((_, i) => i !== idx));
    // Clean up companion state keyed by the removed uid so leftover entries
    // don't bleed onto a future row with the same array index (N1).
    if (removedId) {
      setMsTestResults(prev => {
        const next = { ...prev };
        delete next[removedId];
        return next;
      });
      setMsShowPasswords(prev => {
        const next: Record<string, boolean> = {};
        for (const [k, v] of Object.entries(prev)) {
          if (!k.startsWith(`${removedId}-`)) next[k] = v;
        }
        return next;
      });
    }
  };

  const testMsInstance = async (idx: number) => {
    const inst = msInstances[idx];
    const uid = msInstanceIds.current[idx];
    if (!uid) return;
    setMsTestResults(prev => ({ ...prev, [uid]: 'testing' }));
    try {
      const result = await testMediaServer(inst as Record<string, unknown>);
      setMsTestResults(prev => ({ ...prev, [uid]: result }));
      if (result.healthy) {
        toast(`${inst.name}: ${t('mediaservers_step.connection_successful')}`);
      } else {
        toast(`${inst.name}: ${result.message}`, 'error');
      }
    } catch {
      setMsTestResults(prev => ({
        ...prev,
        [uid]: { healthy: false, message: t('mediaservers_step.test_failed') },
      }));
      toast(`${inst.name}: ${t('mediaservers_step.test_failed')}`, 'error');
    }
  };

  // Helper that resolves a `values` key to a controlled-input prop pair, so
  // each <Field /> only needs to know its target key once.
  const fieldFor = (keyName: keyof typeof values) => ({
    value: values[keyName] ?? '',
    onChange: (v: string) => set(keyName, v),
  });

  return (
    <div
      className="min-h-screen flex items-center justify-center p-6"
      style={{ backgroundColor: 'var(--bg-primary)' }}
    >
      {/* Shared "form" width tier, not a bespoke max-w-xl: the wizard carries
          real content (library type, scheduler profile) that was cramped into
          576px on any desktop screen. */}
      <div className="w-full max-w-form space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
            {t('welcome.title')}
          </h1>
          <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            {t('welcome.subtitle')}
          </p>
        </div>

        {/* Progress (N5 — semantic progressbar for assistive tech) */}
        <div
          className="flex items-center gap-1"
          role="progressbar"
          aria-valuenow={step + 1}
          aria-valuemin={1}
          aria-valuemax={visibleSteps.length}
          aria-label={t('step_info', { step: step + 1, total: visibleSteps.length })}
        >
          {visibleSteps.map((s, i) => (
            <div key={s.id} className="flex-1 flex items-center gap-1">
              <div
                className="h-1.5 flex-1 rounded-full transition-all duration-300"
                style={{
                  backgroundColor: i <= step ? 'var(--accent)' : 'var(--border)',
                }}
              />
            </div>
          ))}
        </div>

        {/* Step Content */}
        <div
          className="rounded-lg p-6 space-y-5"
          style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              {(() => {
                const Icon = currentStepDef.icon;
                return <Icon size={20} style={{ color: 'var(--accent)' }} />;
              })()}
              <div>
                <h2 className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>
                  {t(currentStepDef.titleKey)}
                </h2>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {t('step_info', { step: step + 1, total: visibleSteps.length })} &mdash;{' '}
                  {t(currentStepDef.descKey)}
                </p>
              </div>
            </div>
            {currentStepDef.id !== 'scan' && currentStepDef.id !== 'language' && (
              <button
                type="button"
                data-testid="onboarding-reset-step"
                onClick={resetStep}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium shrink-0"
                style={{
                  border: '1px solid var(--border)',
                  color: 'var(--text-secondary)',
                  backgroundColor: 'var(--bg-primary)',
                }}
              >
                <RotateCcw size={12} />
                {t('navigation.reset')}
              </button>
            )}
          </div>

          {rerun && (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {t('rerun_banner')}
            </p>
          )}

          {currentStepDef.id === 'mode' && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {/* Sonarr / Radarr Mode card */}
                <button
                  onClick={() => chooseSetupMode('arr')}
                  className="rounded-lg p-4 text-left space-y-2 transition-all duration-200"
                  style={{
                    backgroundColor: 'var(--bg-primary)',
                    border:
                      setupMode === 'arr' ? '2px solid var(--accent)' : '1px solid var(--border)',
                  }}
                  onMouseEnter={e => {
                    if (setupMode !== 'arr')
                      e.currentTarget.style.borderColor = 'var(--accent-dim)';
                  }}
                  onMouseLeave={e => {
                    if (setupMode !== 'arr') e.currentTarget.style.borderColor = 'var(--border)';
                  }}
                >
                  <div className="flex items-center justify-between">
                    <Server size={20} style={{ color: 'var(--accent)' }} />
                    {setupMode === 'arr' && (
                      <CheckCircle size={16} style={{ color: 'var(--accent)' }} />
                    )}
                  </div>
                  <div className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {t('mode_step.arr_title')}
                  </div>
                  <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {t('mode_step.arr_description')}
                  </div>
                </button>

                {/* Standalone Mode card */}
                <button
                  onClick={() => chooseSetupMode('standalone')}
                  className="rounded-lg p-4 text-left space-y-2 transition-all duration-200"
                  style={{
                    backgroundColor: 'var(--bg-primary)',
                    border:
                      setupMode === 'standalone'
                        ? '2px solid var(--accent)'
                        : '1px solid var(--border)',
                  }}
                  onMouseEnter={e => {
                    if (setupMode !== 'standalone')
                      e.currentTarget.style.borderColor = 'var(--accent-dim)';
                  }}
                  onMouseLeave={e => {
                    if (setupMode !== 'standalone')
                      e.currentTarget.style.borderColor = 'var(--border)';
                  }}
                >
                  <div className="flex items-center justify-between">
                    <FolderOpen size={20} style={{ color: 'var(--accent)' }} />
                    {setupMode === 'standalone' && (
                      <CheckCircle size={16} style={{ color: 'var(--accent)' }} />
                    )}
                  </div>
                  <div className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                    {t('mode_step.standalone_title')}
                  </div>
                  <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {t('mode_step.standalone_description')}
                  </div>
                </button>
              </div>
            </div>
          )}

          {currentStepDef.id === 'library' && (
            <div className="space-y-4">
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                {t('library_step.question')}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {[
                  { type: 'anime' as const, icon: Sparkles },
                  { type: 'movies' as const, icon: Clapperboard },
                  { type: 'mixed' as const, icon: Library },
                ].map(({ type, icon: TypeIcon }) => (
                  <button
                    key={type}
                    data-testid={`library-type-${type}`}
                    onClick={() => setLibraryType(type)}
                    className="rounded-lg p-4 text-left space-y-2 transition-all duration-200"
                    style={{
                      backgroundColor: 'var(--bg-primary)',
                      border:
                        libraryType === type
                          ? '2px solid var(--accent)'
                          : '1px solid var(--border)',
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <TypeIcon size={20} style={{ color: 'var(--accent)' }} />
                      {libraryType === type && (
                        <CheckCircle size={16} style={{ color: 'var(--accent)' }} />
                      )}
                    </div>
                    <div className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                      {t(`library_step.${type}_title`)}
                    </div>
                    <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                      {t(`library_step.${type}_description`)}
                    </div>
                  </button>
                ))}
              </div>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                {t('library_step.help')}
              </p>
            </div>
          )}

          {currentStepDef.id === 'performance' && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {(['light', 'balanced', 'aggressive'] as const).map(profile => {
                  const recommended = benchmark?.recommended_profile === profile;
                  const selected = perfProfile === profile;
                  return (
                    <button
                      key={profile}
                      data-testid={`perf-profile-${profile}`}
                      onClick={() => setPerfProfile(profile)}
                      className="rounded-lg p-4 text-left space-y-2 transition-all duration-200"
                      style={{
                        backgroundColor: 'var(--bg-primary)',
                        border: selected ? '2px solid var(--accent)' : '1px solid var(--border)',
                      }}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span
                          className="text-sm font-semibold"
                          style={{ color: 'var(--text-primary)' }}
                        >
                          {t(`performance_step.${profile}_title`)}
                        </span>
                        {recommended && (
                          <span
                            className="text-[10px] font-semibold rounded-full px-1.5 py-0.5 shrink-0"
                            style={{ backgroundColor: 'var(--accent)', color: '#fff' }}
                          >
                            {t('performance_step.recommended')}
                          </span>
                        )}
                      </div>
                      <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                        {t(`performance_step.${profile}_description`)}
                      </div>
                    </button>
                  );
                })}
              </div>
              {benchmark && (
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {t('performance_step.detected', {
                    cpu: benchmark.cpu_count,
                    ram: benchmark.ram_gb,
                  })}
                </p>
              )}
            </div>
          )}

          {currentStepDef.id === 'arr' && (
            <div className="space-y-5">
              {(['sonarr', 'radarr'] as const).map(which => {
                const insts = which === 'sonarr' ? sonarrInsts : radarrInsts;
                return (
                  <div key={which} className="space-y-3">
                    <h3
                      className="text-sm font-semibold"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      {t(`arr_step.${which}_heading`)}
                    </h3>
                    {insts.map(inst => {
                      const status = instStatus[inst.id];
                      return (
                        <div
                          key={inst.id}
                          data-testid={`onboarding-${which}-instance`}
                          className="rounded-lg p-4 space-y-3"
                          style={{
                            backgroundColor: 'var(--bg-primary)',
                            border: '1px solid var(--border)',
                          }}
                        >
                          <div className="flex items-center justify-between">
                            <input
                              type="text"
                              value={inst.name}
                              onChange={e => updateInstance(which, inst.id, { name: e.target.value })}
                              placeholder={t(`arr_step.${which}_name_placeholder`)}
                              className="text-sm font-semibold focus:outline-none bg-transparent"
                              style={{ color: 'var(--text-primary)' }}
                            />
                            <button
                              onClick={() => removeInstance(which, inst.id)}
                              className="p-1 rounded transition-colors"
                              style={{ color: 'var(--text-muted)' }}
                              aria-label={t('arr_step.remove_instance')}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                          <Field
                            label={t('arr_step.url_label')}
                            placeholder={which === 'sonarr' ? 'http://localhost:8989' : 'http://localhost:7878'}
                            value={inst.url}
                            onChange={v => updateInstance(which, inst.id, { url: v })}
                          />
                          <Field
                            label={t('arr_step.api_key_label')}
                            type="password"
                            value={inst.api_key}
                            onChange={v => updateInstance(which, inst.id, { api_key: v })}
                          />
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => testInstanceConnection(which, inst)}
                              disabled={!inst.url.trim() || status?.testing}
                              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-150 disabled:opacity-50"
                              style={{
                                border: '1px solid var(--border)',
                                color: 'var(--text-secondary)',
                                backgroundColor: 'var(--bg-surface)',
                              }}
                            >
                              {status?.testing ? (
                                <Loader2 size={12} className="animate-spin" />
                              ) : (
                                <TestTube size={12} />
                              )}
                              {t('common:actions.test')}
                            </button>
                            {status && !status.testing && status.message && (
                              <span
                                className="text-xs"
                                style={{
                                  color: status.healthy ? 'var(--success)' : 'var(--error)',
                                }}
                              >
                                {status.healthy ? 'OK' : 'Error'}: {status.message}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    <button
                      type="button"
                      data-testid={`onboarding-add-${which}`}
                      onClick={() => addInstance(which)}
                      className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium"
                      style={{
                        border: '1px dashed var(--border)',
                        color: 'var(--text-muted)',
                      }}
                    >
                      <Plus size={12} />
                      {t(`arr_step.add_${which}`)}
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {currentStepDef.id === 'standalone' && (
            <div className="space-y-4">
              <Field
                label={t('standalone_step.tmdb_api_key')}
                type="password"
                {...fieldFor('tmdb_api_key')}
              />
              <button
                type="button"
                onClick={() => runApiKeyTest('tmdb')}
                disabled={!values.tmdb_api_key || testing === 'tmdb'}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-150 disabled:opacity-50"
                style={{
                  border: '1px solid var(--border)',
                  color: 'var(--text-secondary)',
                  backgroundColor: 'var(--bg-primary)',
                }}
              >
                {testing === 'tmdb' ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <TestTube size={12} />
                )}
                {t('standalone_step.test_tmdb')}
              </button>
              <Field
                label={t('standalone_step.tvdb_api_key')}
                type="password"
                {...fieldFor('tvdb_api_key')}
              />
              <button
                type="button"
                onClick={() => runApiKeyTest('tvdb')}
                disabled={!values.tvdb_api_key || testing === 'tvdb'}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-150 disabled:opacity-50"
                style={{
                  border: '1px solid var(--border)',
                  color: 'var(--text-secondary)',
                  backgroundColor: 'var(--bg-primary)',
                }}
              >
                {testing === 'tvdb' ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <TestTube size={12} />
                )}
                {t('standalone_step.test_tvdb')}
              </button>
              <div className="space-y-2">
                <label
                  className="block text-sm font-medium"
                  style={{ color: 'var(--text-primary)' }}
                >
                  {t('standalone_step.media_folders')}
                </label>
                {standaloneFolders.map((folder, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <input
                      type="text"
                      value={folder.path}
                      onChange={e => {
                        const updated = [...standaloneFolders];
                        updated[idx] = { ...updated[idx], path: e.target.value };
                        setStandaloneFolders(updated);
                      }}
                      placeholder="/path/to/media"
                      className="flex-1 px-3 py-2 rounded-md text-sm focus:outline-none"
                      style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }}
                    />
                    <button
                      onClick={() => setStandaloneFolders(prev => prev.filter((_, i) => i !== idx))}
                      className="p-1.5 rounded transition-colors"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={newFolderPath}
                    onChange={e => setNewFolderPath(e.target.value)}
                    placeholder="/path/to/media"
                    className="flex-1 px-3 py-2 rounded-md text-sm focus:outline-none"
                    style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && newFolderPath.trim()) {
                        setStandaloneFolders(prev => [
                          ...prev,
                          { path: newFolderPath.trim(), label: '' },
                        ]);
                        setNewFolderPath('');
                      }
                    }}
                  />
                  <button
                    onClick={() => {
                      if (newFolderPath.trim()) {
                        setStandaloneFolders(prev => [
                          ...prev,
                          { path: newFolderPath.trim(), label: '' },
                        ]);
                        setNewFolderPath('');
                      }
                    }}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-all duration-150"
                    style={{ color: 'var(--accent)', border: '1px solid var(--accent-dim)' }}
                  >
                    <Plus size={14} />
                    {t('common:actions.add')}
                  </button>
                </div>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {t('standalone_step.media_folders_help')}
                </p>
              </div>
            </div>
          )}

          {currentStepDef.id === 'pathmapping' && (
            <div className="space-y-4">
              {mappingRows.map((row, idx) => (
                <div
                  key={idx}
                  data-testid="onboarding-mapping-row"
                  className="flex items-center gap-2"
                >
                  <input
                    type="text"
                    value={row.remote}
                    onChange={e =>
                      setMappingRows(prev =>
                        prev.map((r, i) => (i === idx ? { ...r, remote: e.target.value } : r))
                      )
                    }
                    placeholder={t('pathmapping_step.remote_placeholder')}
                    className="flex-1 px-3 py-2 rounded-md text-sm focus:outline-none"
                    style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }}
                  />
                  <span style={{ color: 'var(--text-muted)' }}>=</span>
                  <input
                    type="text"
                    value={row.local}
                    onChange={e =>
                      setMappingRows(prev =>
                        prev.map((r, i) => (i === idx ? { ...r, local: e.target.value } : r))
                      )
                    }
                    placeholder={t('pathmapping_step.local_placeholder')}
                    className="flex-1 px-3 py-2 rounded-md text-sm focus:outline-none"
                    style={{ ...inputStyle, fontFamily: 'var(--font-mono)' }}
                  />
                  <button
                    onClick={() => setMappingRows(prev => prev.filter((_, i) => i !== idx))}
                    className="p-1.5 rounded transition-colors"
                    style={{ color: 'var(--text-muted)' }}
                    aria-label={t('pathmapping_step.remove_rule')}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                data-testid="onboarding-add-mapping"
                onClick={() => setMappingRows(prev => [...prev, { remote: '', local: '' }])}
                className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-all duration-150"
                style={{ color: 'var(--accent)', border: '1px solid var(--accent-dim)' }}
              >
                <Plus size={14} />
                {t('pathmapping_step.add_rule')}
              </button>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                {t('pathmapping_step.help')}
              </p>
            </div>
          )}

          {currentStepDef.id === 'language' && (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label
                  className="block text-sm font-medium"
                  style={{ color: 'var(--text-primary)' }}
                >
                  {t('language_step.interface_language')}
                </label>
                <select
                  data-testid="select-interface-language"
                  value={values.interface_language}
                  onChange={e => {
                    const code = e.target.value;
                    set('interface_language', code);
                    // Switch the wizard itself immediately — the choice is
                    // what the user should read for the rest of setup. Persist
                    // it right away like Settings → General does: the global
                    // config sync re-applies the stored interface_language on
                    // every refresh, so an unsaved choice would snap the UI
                    // back before the step save. The Next save re-sends it.
                    i18n.changeLanguage(code);
                    void updateConfig({ interface_language: code }).catch(() => {});
                  }}
                  className="w-full px-3 py-2 rounded-md text-sm focus:outline-none"
                  style={inputStyle}
                >
                  {INTERFACE_LANGUAGE_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {t('language_step.interface_language_hint')}
                </p>
              </div>

              {/* Language profiles: the exact editor from
                  Settings → Subtitles → Languages & Profiles. Profiles are
                  persisted immediately through the profiles API; Save also
                  makes the saved profile the library-wide default. On a
                  re-run the existing profiles are fetched fresh, so the
                  settings previously made here are remembered. */}
              <LanguageProfilesTab defaultOnSave />
            </div>
          )}

          {currentStepDef.id === 'providers' && (
            <div className="space-y-4">
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                {t('providers_step.info')}
              </p>
              <Field
                label={t('providers_step.opensubtitles_api_key')}
                type="password"
                {...fieldFor('opensubtitles_api_key')}
              />
              <Field
                label={t('providers_step.jimaku_api_key')}
                type="password"
                {...fieldFor('jimaku_api_key')}
              />
              <Field
                label={t('providers_step.subdl_api_key')}
                type="password"
                {...fieldFor('subdl_api_key')}
              />
            </div>
          )}

          {currentStepDef.id === 'automation' && (
            <div className="space-y-4">
              {/* Automatic subtitle search toggle */}
              <div
                className="flex items-start gap-3 p-3 rounded-lg"
                style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border)' }}
              >
                <input
                  type="checkbox"
                  id="automation_enabled"
                  checked={values.automation_enabled === 'true'}
                  onChange={e => set('automation_enabled', e.target.checked ? 'true' : 'false')}
                  className="mt-0.5 h-4 w-4 rounded"
                  style={{ accentColor: 'var(--accent)' }}
                />
                <div className="flex-1 space-y-1">
                  <label
                    htmlFor="automation_enabled"
                    className="block text-sm font-medium cursor-pointer"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {t('automation_step.auto_search_label')}
                  </label>
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {t('automation_step.auto_search_description')}
                  </p>
                </div>
              </div>

              {/* Interval select — only shown when automation enabled */}
              {values.automation_enabled === 'true' && (
                <div className="space-y-1.5">
                  <label
                    className="block text-sm font-medium"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {t('automation_step.interval_label')}
                  </label>
                  <select
                    value={values.search_interval_hours}
                    onChange={e => set('search_interval_hours', e.target.value)}
                    className="w-full px-3 py-2 rounded-md text-sm focus:outline-none"
                    style={inputStyle}
                  >
                    <option value="1">{t('automation_step.interval_1h')}</option>
                    <option value="3">{t('automation_step.interval_3h')}</option>
                    <option value="6">{t('automation_step.interval_6h')}</option>
                    <option value="12">{t('automation_step.interval_12h')}</option>
                    <option value="24">{t('automation_step.interval_24h')}</option>
                  </select>
                </div>
              )}

              {/* Upgrade existing subtitles toggle */}
              <div
                className="flex items-start gap-3 p-3 rounded-lg"
                style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border)' }}
              >
                <input
                  type="checkbox"
                  id="upgrade_enabled"
                  checked={values.upgrade_enabled === 'true'}
                  onChange={e => set('upgrade_enabled', e.target.checked ? 'true' : 'false')}
                  className="mt-0.5 h-4 w-4 rounded"
                  style={{ accentColor: 'var(--accent)' }}
                />
                <div className="flex-1 space-y-1">
                  <label
                    htmlFor="upgrade_enabled"
                    className="block text-sm font-medium cursor-pointer"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {t('automation_step.upgrade_label')}
                  </label>
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {t('automation_step.upgrade_description')}
                  </p>
                </div>
              </div>

              {/* Info box */}
              <div
                className="flex items-start gap-2 p-3 rounded-lg text-xs"
                style={{
                  backgroundColor: 'var(--accent-bg)',
                  border: '1px solid var(--accent-dim)',
                  color: 'var(--text-secondary)',
                }}
              >
                <Zap size={12} className="mt-0.5 shrink-0" style={{ color: 'var(--accent)' }} />
                <span>{t('automation_step.settings_hint')}</span>
              </div>
            </div>
          )}

          {currentStepDef.id === 'mediaservers' && (
            <div className="space-y-4">
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                {t('mediaservers_step.info')}
              </p>

              {/* Type selection buttons */}
              <div className="flex flex-wrap gap-2">
                {msTypes.map(t => (
                  <button
                    key={t.name}
                    onClick={() => addMediaServer(t)}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-all duration-150"
                    style={{
                      border: '1px solid var(--accent-dim)',
                      color: 'var(--accent)',
                      backgroundColor: 'var(--accent-bg)',
                    }}
                  >
                    <Plus size={14} />
                    {t.display_name}
                  </button>
                ))}
              </div>

              {/* Configured instances */}
              {msInstances.map((inst, idx) => {
                const typeInfo = msTypes.find(t => t.name === inst.type);
                const uid = msInstanceIds.current[idx] ?? `idx-${idx}`;
                const testResult = msTestResults[uid];

                return (
                  <div
                    key={uid}
                    className="rounded-lg p-4 space-y-3"
                    style={{
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className="text-sm font-semibold"
                          style={{ color: 'var(--text-primary)' }}
                        >
                          {inst.name}
                        </span>
                        <span
                          className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                          style={{ backgroundColor: 'var(--accent-bg)', color: 'var(--accent)' }}
                        >
                          {typeInfo?.display_name ?? inst.type}
                        </span>
                      </div>
                      <button
                        onClick={() => removeMsInstance(idx)}
                        className="p-1 rounded transition-colors"
                        style={{ color: 'var(--text-muted)' }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    {/* Name */}
                    <input
                      type="text"
                      value={String(inst.name ?? '')}
                      onChange={e => updateMsField(idx, 'name', e.target.value)}
                      placeholder={t('mediaservers_step.server_name')}
                      className="w-full px-2.5 py-1.5 rounded text-sm focus:outline-none"
                      style={inputStyle}
                    />

                    {/* Dynamic config fields */}
                    {typeInfo?.config_fields.map(field => {
                      const pwKey = `${uid}-${field.key}`;
                      return (
                        <div key={field.key} className="space-y-1">
                          <label
                            className="text-xs font-medium"
                            style={{ color: 'var(--text-secondary)' }}
                          >
                            {field.label}{' '}
                            {field.required && <span style={{ color: 'var(--error)' }}>*</span>}
                          </label>
                          <div className="flex items-center gap-1.5">
                            <input
                              type={
                                field.type === 'password' && !msShowPasswords[pwKey]
                                  ? 'password'
                                  : 'text'
                              }
                              value={String(inst[field.key] ?? '')}
                              onChange={e => updateMsField(idx, field.key, e.target.value)}
                              placeholder={
                                field.default ||
                                (field.required
                                  ? t('mediaservers_step.required')
                                  : t('mediaservers_step.optional'))
                              }
                              autoComplete={field.type === 'password' ? 'new-password' : 'off'}
                              spellCheck={false}
                              className="flex-1 px-2.5 py-1.5 rounded text-sm focus:outline-none"
                              style={inputStyle}
                            />
                            {field.type === 'password' && (
                              <button
                                onClick={() =>
                                  setMsShowPasswords(p => ({ ...p, [pwKey]: !p[pwKey] }))
                                }
                                className="p-1.5 rounded"
                                style={{
                                  border: '1px solid var(--border)',
                                  color: 'var(--text-muted)',
                                  backgroundColor: 'var(--bg-primary)',
                                }}
                              >
                                {msShowPasswords[pwKey] ? <EyeOff size={12} /> : <Eye size={12} />}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}

                    {/* Test button and result */}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => testMsInstance(idx)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-all duration-150"
                        style={{
                          border: '1px solid var(--border)',
                          color: 'var(--text-secondary)',
                          backgroundColor: 'var(--bg-surface)',
                        }}
                      >
                        {testResult === 'testing' ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <TestTube size={12} />
                        )}
                        {t('common:actions.test')}
                      </button>
                      {testResult && testResult !== 'testing' && (
                        <span
                          className="text-xs"
                          style={{ color: testResult.healthy ? 'var(--success)' : 'var(--error)' }}
                        >
                          {testResult.healthy ? 'OK' : 'Error'}: {testResult.message}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}

              {msInstances.length === 0 && msTypes.length === 0 && !msTypesError && (
                <div className="text-center py-4">
                  <Loader2
                    size={16}
                    className="animate-spin mx-auto"
                    style={{ color: 'var(--accent)' }}
                  />
                </div>
              )}
              {msTypesError && (
                <div
                  className="flex items-center gap-2 p-3 rounded-lg text-xs"
                  style={{
                    backgroundColor: 'var(--error-bg, var(--bg-primary))',
                    border: '1px solid var(--error)',
                  }}
                >
                  <AlertCircle size={14} style={{ color: 'var(--error)' }} />
                  <span className="flex-1" style={{ color: 'var(--text-primary)' }}>
                    {t('mediaservers_step.types_load_failed')}
                  </span>
                  <button
                    type="button"
                    onClick={loadMsTypes}
                    className="px-2 py-1 rounded text-xs"
                    style={{
                      border: '1px solid var(--border)',
                      color: 'var(--text-primary)',
                      backgroundColor: 'var(--bg-primary)',
                    }}
                  >
                    {tc('actions.retry')}
                  </button>
                </div>
              )}
            </div>
          )}

          {currentStepDef.id === 'scan' && (
            <div className="space-y-4 text-center">
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                {t('scan_step.info')}
              </p>
              {!scanStarted ? (
                <button
                  onClick={startScan}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-medium text-white"
                  style={{ backgroundColor: 'var(--accent)' }}
                >
                  <Play size={16} />
                  {t('scan_step.start_scan')}
                </button>
              ) : (
                <div
                  className="flex items-center justify-center gap-2"
                  style={{ color: 'var(--success)' }}
                >
                  <CheckCircle size={18} />
                  <span className="text-sm font-medium">{t('scan_step.scan_started')}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => (step > 0 ? setStep(s => s - 1) : skipSetup())}
            className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm"
            style={{ color: 'var(--text-muted)' }}
          >
            <ArrowLeft size={14} />
            {step > 0 ? t('navigation.back') : t('navigation.skip_setup')}
          </button>

          {/* "Finish" belongs to the final scan step only — before the setup
              mode is picked `visibleSteps` holds just the mode step, which
              used to render "Finish Setup" as the button of step 1. */}
          {currentStepDef.id !== 'scan' ? (
            <button
              onClick={saveAndNext}
              disabled={
                saving ||
                (currentStepDef.id === 'mode' && !setupMode) ||
                (currentStepDef.id === 'library' && !libraryType)
              }
              className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-white"
              style={{
                backgroundColor:
                  (currentStepDef.id === 'mode' && !setupMode) ||
                  (currentStepDef.id === 'library' && !libraryType)
                    ? 'var(--text-muted)'
                    : 'var(--accent)',
              }}
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              {currentStepDef.id === 'mediaservers'
                ? msInstances.length > 0
                  ? t('navigation.save_next')
                  : t('navigation.skip')
                : t('navigation.next')}
              <ArrowRight size={14} />
            </button>
          ) : (
            <button
              onClick={finish}
              className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-white"
              style={{ backgroundColor: 'var(--success)' }}
            >
              <CheckCircle size={14} />
              {t('navigation.finish')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
