import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

import i18n from '../i18n'

beforeEach(async () => {
  localStorage.clear()
  // jsdom does not implement scrolling.
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  await i18n.changeLanguage('en')
})

// Vitest globals are off, so Testing Library cannot register its automatic cleanup.
afterEach(() => {
  cleanup()
})
