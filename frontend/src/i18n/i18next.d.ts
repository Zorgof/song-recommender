import 'i18next'

import type { resources } from './index'

// Type-checked translation keys: t('result.why') compiles, t('result.wyh') does not.
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation'
    resources: (typeof resources)['en']
  }
}
