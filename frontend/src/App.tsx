import { Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import AgentChatDrawer from './components/AgentChatDrawer'

export default function App() {
  return (
    <div className="flex min-h-screen bg-ind-bg font-sans">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
      <AgentChatDrawer />
    </div>
  )
}
