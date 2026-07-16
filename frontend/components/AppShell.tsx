import Link from 'next/link'
import { useRouter } from 'next/router'
import type { ReactNode } from 'react'

type AppShellProps = {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const router = useRouter()

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link href="/" className="brand" aria-label="Página inicial do Imob Hub">
          <span className="brand-mark">IH</span>
          <span>
            <span className="brand-name">Imob Hub</span>
            <span className="brand-subtitle">Todos os imóveis. Uma única busca.</span>
          </span>
        </Link>

        <nav className="topnav" aria-label="Navegação principal">
          <Link className={router.pathname === '/imoveis' ? 'nav-link active' : 'nav-link'} href="/imoveis">
            Imóveis
          </Link>
          <Link className="nav-link" href="/#como-funciona">
            Como funciona
          </Link>
          <Link className="nav-link" href="/#fontes">
            Fontes
          </Link>
        </nav>
      </header>

      {children}
    </div>
  )
}
