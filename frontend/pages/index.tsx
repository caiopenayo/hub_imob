import { FormEvent, useState } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'
import {
  BarChart3,
  Building2,
  Clock3,
  ExternalLink,
  Home as HomeIcon,
  MapPin,
  Search,
  ShieldCheck,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { AppShell } from '../components/AppShell'
import { SiteFooter } from '../components/SiteFooter'
import {
  emptyFilters,
  propertySearchHref,
} from '../lib/propertySearch'

const MAX_QUERY_LENGTH = 500

const benefits = [
  {
    icon: Search,
    title: 'Tudo em um lugar',
    copy: 'Compare imóveis de várias fontes sem abrir dezenas de abas.',
  },
  {
    icon: BarChart3,
    title: 'Compare oportunidades',
    copy: 'Compare preços, localização e características em uma única visão.',
  },
  {
    icon: ExternalLink,
    title: 'Vá direto à fonte',
    copy: 'Abra o anúncio original quando encontrar uma boa opção.',
  },
] satisfies Array<{ icon: LucideIcon; title: string; copy: string }>

const steps = [
  {
    icon: MapPin,
    title: 'Defina sua busca',
    copy: 'Escolha cidade, preço e quartos para começar com foco.',
  },
  {
    icon: Building2,
    title: 'Compare oportunidades',
    copy: 'Analise imóveis de fontes diferentes em uma só lista.',
  },
  {
    icon: ExternalLink,
    title: 'Abra o anúncio original',
    copy: 'Siga para a fonte e continue o contato com o anunciante.',
  },
] satisfies Array<{ icon: LucideIcon; title: string; copy: string }>

const trustItems = [
  { icon: ShieldCheck, label: 'Fontes monitoradas' },
  { icon: Clock3, label: 'Atualizações frequentes' },
  { icon: HomeIcon, label: 'Busca centralizada' },
  { icon: BarChart3, label: 'Comparação inteligente' },
] satisfies Array<{ icon: LucideIcon; label: string }>

const heroTrustItems = [
  { icon: Clock3, label: 'Atualizações frequentes' },
  { icon: ShieldCheck, label: 'Fontes monitoradas' },
  { icon: BarChart3, label: 'Compare em um lugar' },
] satisfies Array<{ icon: LucideIcon; label: string }>

export default function Home() {
  const router = useRouter()
  const [query, setQuery] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuery = query.trim()
    if (!trimmedQuery) {
      void router.push(propertySearchHref(emptyFilters))
      return
    }
    const params = new URLSearchParams({ q: trimmedQuery })
    void router.push(`/imoveis?${params.toString()}`)
  }

  function clearFilters() {
    setQuery('')
  }

  function openResultsPage() {
    void router.push(propertySearchHref(emptyFilters))
  }

  return (
    <AppShell>
      <Head>
        <title>Imob Hub | Busca de imóveis</title>
      </Head>

      <main>
        <section className="hero-band">
          <div className="marketplace-hero">
            <div className="hero-content">
              <p className="eyebrow">Imob Hub</p>
              <h1 className="hero-title">Encontre seu próximo imóvel em uma única busca.</h1>
              <p className="hero-subtitle">
                Compare imóveis de várias fontes sem abrir dezenas de abas.
              </p>
              <p className="hero-tagline">Todos os imóveis. Uma única busca.</p>

              <section className="search-card" aria-label="Buscar imóveis">
                <form onSubmit={handleSubmit} className="search-form">
                  <label className="field field-city hero-natural-field">
                    <span>Descreva sua busca</span>
                    <textarea
                      maxLength={MAX_QUERY_LENGTH}
                      name="query"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' && !event.shiftKey) {
                          event.preventDefault()
                          event.currentTarget.form?.requestSubmit()
                        }
                      }}
                      placeholder="Apartamento de 100 m² em Pinheiros por até R$ 1 milhão"
                      rows={3}
                    />
                  </label>

                  <div className="search-actions">
                    <button className="button button-primary button-search" type="submit" disabled={query.length > MAX_QUERY_LENGTH}>
                      <Search aria-hidden="true" size={20} />
                      Buscar com descrição
                    </button>
                    <button className="button button-ghost" type="button" onClick={clearFilters}>
                      Limpar
                    </button>
                  </div>
                </form>
              </section>
            </div>

            <aside className="hero-visual" aria-label="Prévia da experiência">
              <img src="/images/property-fallback.png" alt="Sala residencial iluminada" />
              <div className="hero-visual-overlay">
                <div className="hero-trust-list">
                  {heroTrustItems.map((item) => {
                    const Icon = item.icon
                    return (
                      <span className="hero-trust-pill" key={item.label}>
                        <Icon aria-hidden="true" size={17} />
                        {item.label}
                      </span>
                    )
                  })}
                </div>
              </div>
            </aside>
          </div>
        </section>

        <section className="section-band benefits-band">
          <div className="section-inner benefits" aria-label="Benefícios">
            {benefits.map((benefit) => {
              const Icon = benefit.icon
              return (
                <article className="benefit-card" key={benefit.title}>
                  <span className="icon-pill"><Icon aria-hidden="true" size={22} /></span>
                  <h2>{benefit.title}</h2>
                  <p>{benefit.copy}</p>
                </article>
              )
            })}
          </div>
        </section>

        <section className="section-band how-band" id="como-funciona">
          <div className="section-inner">
            <div className="section-heading">
              <p className="eyebrow">Como funciona</p>
              <h2>Da busca ao anúncio original, sem complicação.</h2>
            </div>
            <div className="steps-grid">
              <svg className="steps-connector" viewBox="0 0 1000 90" aria-hidden="true" preserveAspectRatio="none">
                <path d="M170 45 C270 12 385 12 500 45 C615 78 730 78 830 45" />
              </svg>
              {steps.map((step, index) => {
                const Icon = step.icon
                return (
                  <article className="step-card" key={step.title}>
                    <div className="step-topline">
                      <span className="step-number">{index + 1}</span>
                      <Icon aria-hidden="true" size={24} />
                    </div>
                    <h3>{step.title}</h3>
                    <p>{step.copy}</p>
                  </article>
                )
              })}
            </div>
          </div>
        </section>

        <section className="section-band trust-band" id="fontes">
          <div className="section-inner trust-layout">
            <div>
              <p className="eyebrow">Fontes</p>
              <h2>Múltiplas fontes, uma única busca.</h2>
              <p>
                Imob Hub centraliza anúncios de fontes monitoradas para você comparar
                oportunidades sem abrir dezenas de abas.
              </p>
            </div>
            <div className="trust-grid" aria-label="Indicadores de confiança">
              {trustItems.map((item) => {
                const Icon = item.icon
                return (
                  <div className="trust-badge" key={item.label}>
                    <Icon aria-hidden="true" size={20} />
                    <span>{item.label}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </section>

        <section className="section-band final-cta-band">
          <div className="section-inner final-cta">
            <div>
              <p className="eyebrow">Continue explorando</p>
              <h2>Ainda procurando o imóvel ideal?</h2>
              <p>Continue explorando oportunidades atualizadas regularmente.</p>
            </div>
            <button className="button button-primary" type="button" onClick={openResultsPage}>
              Explorar imóveis
            </button>
          </div>
        </section>

      </main>
      <SiteFooter />
    </AppShell>
  )
}
