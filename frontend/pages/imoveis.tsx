import { FormEvent, useEffect, useMemo, useState } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'
import { Home as HomeIcon, List, Map, Search } from 'lucide-react'

import { AppShell } from '../components/AppShell'
import { PropertyCard } from '../components/PropertyCard'
import { SiteFooter } from '../components/SiteFooter'
import {
  API_URL,
  bedroomOptions,
  buildPropertySearchParams,
  emptyFilters,
  filtersFromQuery,
  maxPriceOptions,
  pageFromQuery,
  propertySearchHref,
  sortOptions,
} from '../lib/propertySearch'
import type { Filters, Meta, Property } from '../lib/propertySearch'

const PER_PAGE = 21

export default function PropertiesPage() {
  const router = useRouter()
  const [properties, setProperties] = useState<Property[]>([])
  const [city, setCity] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [bedrooms, setBedrooms] = useState('')
  const [sort, setSort] = useState(emptyFilters.sort)
  const [appliedFilters, setAppliedFilters] = useState<Filters>(emptyFilters)
  const [meta, setMeta] = useState<Meta>({ page: 1, per_page: PER_PAGE, total: 0 })
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hasReadQuery, setHasReadQuery] = useState(false)

  useEffect(() => {
    if (!router.isReady) return

    const nextFilters = filtersFromQuery(router.query)
    const nextPage = pageFromQuery(router.query)
    setCity(nextFilters.city)
    setMaxPrice(nextFilters.maxPrice)
    setBedrooms(nextFilters.bedrooms)
    setSort(nextFilters.sort)
    setAppliedFilters(nextFilters)
    setPage(nextPage)
    setHasReadQuery(true)
  }, [router.isReady, router.query.bedrooms, router.query.city, router.query.max_price, router.query.page, router.query.sort])

  useEffect(() => {
    if (!router.isReady || !hasReadQuery) return
    void fetchProperties(page, appliedFilters)
  }, [router.isReady, hasReadQuery, page, appliedFilters])

  async function fetchProperties(requestedPage: number, filters: Filters) {
    setIsLoading(true)
    setError(null)

    const params = buildPropertySearchParams(filters)
    params.append('page', String(requestedPage))
    params.append('per_page', String(PER_PAGE))

    try {
      const response = await fetch(`${API_URL}/properties/?${params.toString()}`)
      if (!response.ok) {
        throw new Error(`Erro ao buscar propriedades: ${response.status}`)
      }
      const data = await response.json()
      setProperties(data.items ?? [])
      setMeta(data.meta ?? { page: requestedPage, per_page: PER_PAGE, total: 0 })
    } catch (err) {
      console.error('Não foi possível carregar os imóveis agora.', err)
      setError('Não conseguimos carregar imóveis agora.')
    } finally {
      setIsLoading(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void router.push(propertySearchHref({ city, maxPrice, bedrooms, sort }))
  }

  function handleSortChange(nextSort: Filters['sort']) {
    setSort(nextSort)
    const nextFilters = { city, maxPrice, bedrooms, sort: nextSort }
    void router.push(propertySearchHref(nextFilters))
  }

  function clearFilters() {
    setCity('')
    setMaxPrice('')
    setBedrooms('')
    setSort(emptyFilters.sort)
    void router.push(propertySearchHref(emptyFilters))
  }

  function goToPage(nextPage: number) {
    void router.push(propertySearchHref(appliedFilters, nextPage))
  }

  const totalPages = Math.max(1, Math.ceil(meta.total / meta.per_page))
  const hasAppliedFilters = Boolean(
    appliedFilters.city || appliedFilters.maxPrice || appliedFilters.bedrooms || appliedFilters.sort !== emptyFilters.sort
  )
  const hasResults = properties.length > 0
  const cityContext = appliedFilters.city.trim() ? ` em ${appliedFilters.city.trim()}` : ''
  const resultLabel = isLoading
    ? 'Atualizando oportunidades...'
    : meta.total === 1
      ? `1 imóvel encontrado${cityContext}`
      : `${meta.total} imóveis encontrados${cityContext}`
  const sortedProperties = useMemo(() => {
    const nextProperties = [...properties]

    switch (sort) {
      case 'price_asc':
        return nextProperties.sort((a, b) => (a.price ?? Number.MAX_SAFE_INTEGER) - (b.price ?? Number.MAX_SAFE_INTEGER))
      case 'price_desc':
        return nextProperties.sort((a, b) => (b.price ?? 0) - (a.price ?? 0))
      case 'area_desc':
        return nextProperties.sort((a, b) => (b.area_m2 ?? 0) - (a.area_m2 ?? 0))
      case 'bedrooms_desc':
        return nextProperties.sort((a, b) => (b.bedrooms ?? 0) - (a.bedrooms ?? 0))
      case 'recent':
        return nextProperties.sort((a, b) => {
          const firstDate = Date.parse(b.updated_at ?? b.last_seen_at ?? '')
          const secondDate = Date.parse(a.updated_at ?? a.last_seen_at ?? '')
          return (Number.isFinite(firstDate) ? firstDate : 0) - (Number.isFinite(secondDate) ? secondDate : 0)
        })
      default:
        return nextProperties
    }
  }, [properties, sort])
  const paginationPages = Array.from({ length: Math.min(totalPages, 5) }, (_, index) => {
    if (totalPages <= 5) return index + 1
    if (page <= 3) return index + 1
    if (page >= totalPages - 2) return totalPages - 4 + index
    return page - 2 + index
  })

  return (
    <AppShell>
      <Head>
        <title>Imob Hub | Imóveis</title>
      </Head>

      <main className="results-page-shell">
        <section className="listing-toolbar-shell" aria-label="Filtros de imóveis">
          <div className="section-inner">
            <form onSubmit={handleSubmit} className="listing-filter-bar">
              <label className="compact-field compact-city">
                <span>Cidade</span>
                <input
                  name="city"
                  value={city}
                  onChange={(event) => setCity(event.target.value)}
                  placeholder="São Paulo"
                />
              </label>

              <label className="compact-field">
                <span>Até R$</span>
                <select
                  name="maxPrice"
                  value={maxPrice}
                  onChange={(event) => setMaxPrice(event.target.value)}
                >
                  {maxPriceOptions.map((option) => (
                    <option key={option.label} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="compact-field">
                <span>Quartos</span>
                <select
                  name="bedrooms"
                  value={bedrooms}
                  onChange={(event) => setBedrooms(event.target.value)}
                >
                  {bedroomOptions.map((option) => (
                    <option key={option.label} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="compact-field">
                <span>Ordenar</span>
                <select
                  name="sort"
                  value={sort}
                  onChange={(event) => handleSortChange(event.target.value as Filters['sort'])}
                >
                  {sortOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <button className="button button-primary compact-search-button" type="submit" disabled={isLoading}>
                <Search aria-hidden="true" size={18} />
                Buscar
              </button>
              <button className="button button-ghost compact-clear-button" type="button" onClick={clearFilters}>
                Limpar
              </button>
              <p
                aria-live="polite"
                className={isLoading ? 'compact-result-count is-loading' : 'compact-result-count'}
              >
                {error ? 'Busca indisponível' : resultLabel}
              </p>
            </form>
          </div>
        </section>

        <section className="section-band results-band results-page-band">
          <div className="section-inner results-section">
            <div className="results-header">
              <div>
                <p className="eyebrow">Resultados</p>
                <h2>Oportunidades para comparar</h2>
                <p className={isLoading ? 'results-summary meta-skeleton' : 'results-summary'}>
                  {error ? 'Busca temporariamente indisponível' : resultLabel}
                </p>
              </div>
              <div className="results-meta">
                <div className="view-toggle-group" aria-label="Modo de visualização">
                  <button className="view-toggle active" type="button" aria-pressed="true">
                    <List aria-hidden="true" size={17} />
                    Lista
                  </button>
                  <button className="view-toggle muted" type="button" aria-disabled="true">
                    <Map aria-hidden="true" size={17} />
                    Mapa
                  </button>
                </div>
              </div>
            </div>

            {error ? (
              <div className="notice notice-error">
                <span className="notice-icon"><HomeIcon aria-hidden="true" size={22} /></span>
                <div>
                  <strong>{error}</strong>
                  <span>Tente novamente em alguns instantes.</span>
                </div>
              </div>
            ) : null}

            {isLoading && !hasResults ? (
              <section className="property-grid" aria-label="Carregando imóveis">
                {Array.from({ length: 6 }).map((_, index) => (
                  <div className="skeleton-card" key={index} />
                ))}
              </section>
            ) : null}

            {!isLoading && !error && !hasResults ? (
              <section className="empty-state">
                <span className="empty-icon"><HomeIcon aria-hidden="true" size={34} /></span>
                <div>
                  <p className="eyebrow">{hasAppliedFilters ? 'Sem resultado' : 'Comece pela busca'}</p>
                  <h2>Nenhum imóvel encontrado.</h2>
                  <p>Tente ajustar os filtros para visualizar novas oportunidades.</p>
                </div>
              </section>
            ) : null}

            {!error && hasResults ? (
              <section className="property-grid" aria-label="Lista de imóveis">
                {sortedProperties.map((property, index) => (
                  <PropertyCard key={property.id} property={property} priority={index < 3} />
                ))}
              </section>
            ) : null}

            {!error && totalPages > 1 ? (
              <section className="pagination" aria-label="Paginação">
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={page <= 1 || isLoading}
                  onClick={() => goToPage(Math.max(1, page - 1))}
                >
                  Anterior
                </button>

                <div className="pagination-pages" aria-label="Páginas">
                  {paginationPages.map((paginationPage) => (
                    <button
                      aria-current={paginationPage === page ? 'page' : undefined}
                      className={paginationPage === page ? 'page-button active' : 'page-button'}
                      key={paginationPage}
                      type="button"
                      disabled={isLoading}
                      onClick={() => goToPage(paginationPage)}
                    >
                      {paginationPage}
                    </button>
                  ))}
                </div>

                <button
                  className="button button-secondary"
                  type="button"
                  disabled={page >= totalPages || isLoading}
                  onClick={() => goToPage(Math.min(totalPages, page + 1))}
                >
                  Próxima
                </button>
              </section>
            ) : null}
          </div>
        </section>
      </main>
      <SiteFooter />
    </AppShell>
  )
}
