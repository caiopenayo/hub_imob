import Link from 'next/link'

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="section-inner footer-inner">
        <div className="footer-brand">
          <span className="brand-mark">IH</span>
          <div>
            <strong>Imob Hub</strong>
            <p>Todos os imóveis. Uma única busca.</p>
          </div>
        </div>
        <nav className="footer-nav" aria-label="Navegação do rodapé">
          <Link href="/imoveis">Imóveis</Link>
          <Link href="/#como-funciona">Como funciona</Link>
          <Link href="/#fontes">Fontes</Link>
          <a href="#contato">Contato</a>
        </nav>
        <p className="footer-contact" id="contato">contato@imobhub.com</p>
        <p className="footer-copy">© 2026 Imob Hub</p>
      </div>
    </footer>
  )
}
