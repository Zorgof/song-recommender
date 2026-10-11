import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router'

import { LanguageSwitcher } from './LanguageSwitcher'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium ${
    isActive
      ? 'bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-white'
      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
  }`

export function Layout() {
  const { t } = useTranslation()

  useEffect(() => {
    document.title = t('app.title')
  }, [t])

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-3 px-4 py-3">
          <NavLink to="/" className="mr-auto text-lg font-bold">
            🎵 {t('app.title')}
          </NavLink>
          <nav aria-label={t('nav.label')} className="flex gap-1">
            <NavLink to="/" end className={navLinkClass}>
              {t('nav.home')}
            </NavLink>
            <NavLink to="/history" className={navLinkClass}>
              {t('nav.history')}
            </NavLink>
          </nav>
          <LanguageSwitcher />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
