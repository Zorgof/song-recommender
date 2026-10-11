import { Route, Routes } from 'react-router'

import { Layout } from './components/Layout'
import { HistoryPage } from './pages/HistoryPage'
import { HomePage } from './pages/HomePage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="*" element={<HomePage />} />
      </Route>
    </Routes>
  )
}
