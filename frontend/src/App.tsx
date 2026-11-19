import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { ScheduleProvider } from './context/ScheduleContext'
import { EarningsPage } from './pages/EarningsPage'
import { ReviewPage } from './pages/ReviewPage'
import { SchedulePage } from './pages/SchedulePage'
import { UploadPage } from './pages/UploadPage'
import { WarningsPage } from './pages/WarningsPage'

export function App() {
  return (
    <ScheduleProvider>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<Navigate to="/upload" replace />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/warnings" element={<WarningsPage />} />
            <Route path="/schedule" element={<SchedulePage />} />
            <Route path="/earnings" element={<EarningsPage />} />
            <Route path="*" element={<Navigate to="/upload" replace />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </ScheduleProvider>
  )
}

export default App
