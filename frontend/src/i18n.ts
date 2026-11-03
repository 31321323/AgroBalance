// UI text has a stable catalog boundary for adding an English translation.
// Locale selection and English content belong to the next product milestone.
export const defaultLocale = 'ru' as const
export const ru = {
  pages: {
    dashboard: 'Обзор хозяйства',
    fields: 'Мои участки',
    calendar: 'Календарь поливов',
    analytics: 'Аналитика',
    settings: 'Настройки',
    detail: 'Обзор участка',
  },
  recommendation: {
    irrigate: 'Полив рекомендуется',
    ok: 'Полив пока не требуется',
    insufficient: 'Требуется уточнение данных',
  },
}
export type TranslationCatalog = typeof ru
