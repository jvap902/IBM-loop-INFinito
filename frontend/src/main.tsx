import 'leaflet/dist/leaflet.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import L from 'leaflet'

import App from './App'
import Dashboard from './pages/Dashboard'
import RunPage from './pages/RunPage'
import Axis1Page from './pages/Axis1Page'
import Axis2Page from './pages/Axis2Page'
import Axis3Page from './pages/Axis3Page'
import AuditPage from './pages/AuditPage'
import ReportsPage from './pages/ReportsPage'
import RunHistoryPage from './pages/RunHistoryPage'

import './index.css'

// Fix Leaflet default marker icons broken by Vite's asset bundling
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 60_000 },
  },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'run',   element: <RunPage /> },
      { path: 'axis1', element: <Axis1Page /> },
      { path: 'axis2', element: <Axis2Page /> },
      { path: 'axis3',   element: <Axis3Page /> },
      { path: 'history', element: <RunHistoryPage /> },
      { path: 'reports', element: <ReportsPage /> },
      { path: 'audit',   element: <AuditPage /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
)
