import { type ReactNode } from 'react'
import Sidebar from './Sidebar'

interface Props {
  children: ReactNode
}

export default function Layout({ children }: Props) {
  return (
    <div className="flex h-screen overflow-hidden bg-zinc-950">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  )
}
