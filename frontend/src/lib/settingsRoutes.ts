/** Settings routes with the section anchor that holds the relevant field.
 *  React Router does not act on fragments, so SettingsShell scrolls to the
 *  section once the page has rendered (see components/settings/SettingsShell). */
export const AUTOMATION_SEARCH = '/settings/automation#search-scan';
export const GENERAL_PATHS = '/settings/general#paths';
export const PROVIDERS_GLOBAL = '/settings/providers#global';
export const SUBTITLES_LANGUAGES = '/settings/subtitles/languages';
export const SUBTITLES_SCORING = '/settings/subtitles/scoring';
export const SUBTITLES_FORMAT = '/settings/subtitles/format';
export const TRANSLATION_BACKENDS = '/settings/translation#backends';
export const TRANSLATION_QUALITY = '/settings/translation#context-quality';
export const TRANSLATION_COST_MEMORY = '/settings/translation/cost-memory';
export const SYSTEM_DIAGNOSTICS = '/settings/system/diagnostics';
