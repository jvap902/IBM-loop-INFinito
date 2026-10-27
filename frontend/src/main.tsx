import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import App from './App'
import Dashboard from './pages/Dashboard'
import RunPage from './pages/RunPage'
import Axis1Page from './pages/Axis1Page'
import Axis2Page from './pages/Axis2Page'
import Axis3Page from './pages/Axis3Page'
import AuditPage from './pages/AuditPage'

import './index.css'

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
      { path: 'axis3', element: <Axis3Page /> },
      { path: 'audit', element: <AuditPage /> },
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
