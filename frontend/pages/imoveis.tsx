import { ChangeEvent, FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'
import {
  AlertCircle,
  Home as HomeIcon,
  List,
  Map,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
} from 'lucide-react'

import { AppShell } from '../components/AppShell'
import { PropertyCard } from '../components/PropertyCard'
import { SiteFooter } from '../components/SiteFooter'
import {
  API_URL,
  ApiError,
  bedroomOptions,
  buildPropertySearchParams,
  emptyFilters,
  fetchNaturalSearch,
  filtersFromQuery,
  maxPriceOptions,
  pageFromQuery,
  propertySearchHref,
  sortOptions,
} from '../lib/propertySearch'
import type {
  BooleanCriterion,
  Filters,
  Meta,
  NaturalSearchResponse,
  NormalizationIssue,
  NumericCriterion,
  Property,
  RequirementLevel,
  SearchIntent,
} from '../lib/propertySearch'

const PER_PAGE = 21
const MAX_QUERY_LENGTH = 500

type RequestStatus =
  | 'initial'
  | 'loading'
  | 'success'
  | 'interpretation_error'
  | 'model_unavailable'
  | 'backend_error'

type SearchMode = 'traditional' | 'natural' | 'edited'
type NumericField = 'price' | 'area_m2' | 'bedrooms' | 'bathrooms' | 'parking_spaces'

const exampleQueries = [
  'Apartamento de 100 m² em Pinheiros por até R$ 1 milhão',
  'Cobertura em Perdizes com 3 quartos e vaga de preferência',
  'Casa em São Paulo com varanda obrigatória',
]

const propertyTypeLabels: Record<string, string> = {
  apartment: 'Apartamento',
  house: 'Casa',
  studio: 'Studio',
  commercial: 'Comercial',
  land: 'Terreno',
}

const transactionLabels: Record<string, string> = {
  sale: 'Comprar',
  rent: 'Alugar',
}

const numericFieldLabels: Record<NumericField, string> = {
  price: 'Preço',
  area_m2: 'Área',
  bedrooms: 'Quartos',
  bathrooms: 'Banheiros',
  parking_spaces: 'Vagas',
}

function queryValue(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? ''
  return value ?? ''
}

function naturalSearchHref(query: string, page?: number): string {
  const params = new URLSearchParams()
  const trimmedQuery = query.trim()
  if (trimmedQuery) params.set('q', trimmedQuery)
  if (page && page > 1) params.set('page', String(page))
  const queryString = params.toString()
  return queryString ? `/imoveis?${queryString}` : '/imoveis'
}

function formatCurrency(value: number): string {
  if (value >= 1_000_000) {
    return `R$ ${(value / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mi`
  }
  if (value >= 1_000) {
    return `R$ ${(value / 1_000).toLocaleString('pt-BR', { maximumFractionDigits: 0 })} mil`
  }
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }).format(value)
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 }).format(value)
}

function criterionValue(criterion: NumericCriterion): number | null {
  return criterion.max_value ?? criterion.target_value ?? criterion.min_value ?? null
}

function criterionMode(criterion: NumericCriterion): 'max_value' | 'target_value' | 'min_value' {
  if (criterion.max_value != null) return 'max_value'
  if (criterion.min_value != null) return 'min_value'
  return 'target_value'
}

function numericCriterionLabel(field: NumericField, criterion: NumericCriterion): string {
  const value = criterionValue(criterion)
  if (value == null) return numericFieldLabels[field]

  if (field === 'price') {
    if (criterion.max_value != null) return `Até ${formatCurrency(value)}`
    if (criterion.min_value != null) return `A partir de ${formatCurrency(value)}`
    return `Cerca de ${formatCurrency(value)}`
  }

  const suffix = field === 'area_m2' ? 'm²' : numericFieldLabels[field].toLocaleLowerCase('pt-BR')
  if (criterion.max_value != null) return `Até ${formatNumber(value)} ${suffix}`
  if (criterion.min_value != null) return `${formatNumber(value)}+ ${suffix}`
  return `Cerca de ${formatNumber(value)} ${suffix}`
}

function importanceLabel(importance: RequirementLevel): string {
  return importance === 'preferred' ? 'preferência' : 'obrigatório'
}

function filtersFromIntent(intent: SearchIntent): Filters {
  const bedroomsValue = intent.bedrooms ? criterionValue(intent.bedrooms) : null
  return {
    city: intent.city ?? '',
    maxPrice: intent.price?.max_value != null ? String(Math.round(intent.price.max_value)) : '',
    bedrooms: bedroomsValue != null ? String(Math.round(bedroomsValue)) : '',
    sort: emptyFilters.sort,
  }
}

function hasIntentCriteria(intent: SearchIntent | null): boolean {
  if (!intent) return false
  return Boolean(
    intent.transaction_type ||
    intent.property_type ||
    intent.city ||
    intent.neighborhoods.length ||
    intent.price ||
    intent.area_m2 ||
    intent.bedrooms ||
    intent.bathrooms ||
    intent.parking_spaces ||
    intent.balcony
  )
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export default function PropertiesPage() {
  const router = useRouter()
  const activeRequestRef = useRef<AbortController | null>(null)
  const [properties, setProperties] = useState<Property[]>([])
  const [city, setCity] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [bedrooms, setBedrooms] = useState('')
  const [sort, setSort] = useState(emptyFilters.sort)
  const [appliedFilters, setAppliedFilters] = useState<Filters>(emptyFilters)
  const [meta, setMeta] = useState<Meta>({ page: 1, per_page: PER_PAGE, total: 0 })
  const [page, setPage] = useState(1)
  const [rawQuery, setRawQuery] = useState('')
  const [activeNaturalQuery, setActiveNaturalQuery] = useState('')
  const [interpretedIntent, setInterpretedIntent] = useState<SearchIntent | null>(null)
  const [editableCriteria, setEditableCriteria] = useState<SearchIntent | null>(null)
  const [normalizationIssues, setNormalizationIssues] = useState<NormalizationIssue[]>([])
  const [issueCorrections, setIssueCorrections] = useState<Record<string, string>>({})
  const [searchMode, setSearchMode] = useState<SearchMode>('traditional')
  const [requestStatus, setRequestStatus] = useState<RequestStatus>('initial')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hasReadQuery, setHasReadQuery] = useState(false)

  useEffect(() => {
    if (!router.isReady) return

    const naturalQuery = queryValue(router.query.q).slice(0, MAX_QUERY_LENGTH)
    const nextPage = pageFromQuery(router.query)
    if (naturalQuery.trim()) {
      setRawQuery(naturalQuery)
      setActiveNaturalQuery(naturalQuery)
      setSearchMode('natural')
      setPage(nextPage)
      setHasReadQuery(true)
      return
    }

    const nextFilters = filtersFromQuery(router.query)
    setCity(nextFilters.city)
    setMaxPrice(nextFilters.maxPrice)
    setBedrooms(nextFilters.bedrooms)
    setSort(nextFilters.sort)
    setAppliedFilters(nextFilters)
    setPage(nextPage)
    setSearchMode('traditional')
    setHasReadQuery(true)
  }, [
    router.isReady,
    router.query.bedrooms,
    router.query.city,
    router.query.max_price,
    router.query.page,
    router.query.q,
    router.query.sort,
  ])

  useEffect(() => {
    if (!router.isReady || !hasReadQuery) return

    if (searchMode === 'natural' && activeNaturalQuery.trim()) {
      void fetchNaturalProperties(activeNaturalQuery, page)
      return
    }

    if (searchMode === 'traditional') {
      void fetchProperties(page, appliedFilters)
    }
  }, [router.isReady, hasReadQuery, searchMode, activeNaturalQuery, page, appliedFilters])

  useEffect(() => {
    return () => {
      activeRequestRef.current?.abort()
    }
  }, [])

  function nextRequestController(): AbortController {
    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller
    return controller
  }

  async function fetchProperties(requestedPage: number, filters: Filters, preserveIntent = false) {
    const controller = nextRequestController()
    setIsLoading(true)
    setError(null)
    if (!preserveIntent) {
      setRequestStatus('loading')
      setInterpretedIntent(null)
      setEditableCriteria(null)
      setNormalizationIssues([])
    }

    const params = buildPropertySearchParams(filters)
    params.append('page', String(requestedPage))
    params.append('per_page', String(PER_PAGE))

    try {
      const response = await fetch(`${API_URL}/properties/?${params.toString()}`, { signal: controller.signal })
      if (!response.ok) {
        throw new Error(`Erro ao buscar propriedades: ${response.status}`)
      }
      const data = await response.json() as { items?: Property[]; meta?: Meta }
      setProperties(data.items ?? [])
      setMeta(data.meta ?? { page: requestedPage, per_page: PER_PAGE, total: 0 })
      setRequestStatus('success')
    } catch (err) {
      if (isAbortError(err)) return
      console.error('Não foi possível carregar os imóveis agora.', err)
      setError('Não conseguimos carregar imóveis agora.')
      setRequestStatus('backend_error')
    } finally {
      if (activeRequestRef.current === controller) {
        setIsLoading(false)
      }
    }
  }

  async function fetchNaturalProperties(query: string, requestedPage: number) {
    const controller = nextRequestController()
    setIsLoading(true)
    setError(null)
    setRequestStatus('loading')

    try {
      const data: NaturalSearchResponse = await fetchNaturalSearch({
        query,
        page: requestedPage,
        perPage: PER_PAGE,
        signal: controller.signal,
      })
      setProperties(data.items ?? [])
      setMeta(data.meta ?? { page: requestedPage, per_page: PER_PAGE, total: 0 })
      setInterpretedIntent(data.intent)
      setEditableCriteria(data.normalized_intent)
      setNormalizationIssues(data.normalization_issues ?? [])
      setIssueCorrections({})
      setRequestStatus('success')
    } catch (err) {
      if (isAbortError(err)) return
      if (err instanceof ApiError && err.status === 503) {
        setError('A busca em linguagem natural está temporariamente indisponível.')
        setRequestStatus('model_unavailable')
      } else if (err instanceof ApiError && err.status === 422) {
        setError('Não conseguimos interpretar essa busca.')
        setRequestStatus('interpretation_error')
      } else {
        setError('Não conseguimos completar a busca agora.')
        setRequestStatus('backend_error')
      }
      setProperties([])
      setMeta({ page: requestedPage, per_page: PER_PAGE, total: 0 })
    } finally {
      if (activeRequestRef.current === controller) {
        setIsLoading(false)
      }
    }
  }

  function handleNaturalSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedQuery = rawQuery.trim()
    if (trimmedQuery.length < 3 || trimmedQuery.length > MAX_QUERY_LENGTH || isLoading) return
    void router.push(naturalSearchHref(trimmedQuery))
  }

  function handleNaturalKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  function handleTraditionalSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setActiveNaturalQuery('')
    setSearchMode('traditional')
    void router.push(propertySearchHref({ city, maxPrice, bedrooms, sort }))
  }

  function handleSortChange(nextSort: Filters['sort']) {
    setSort(nextSort)
    const nextFilters = { city, maxPrice, bedrooms, sort: nextSort }
    setActiveNaturalQuery('')
    setSearchMode('traditional')
    void router.push(propertySearchHref(nextFilters))
  }

  function clearFilters() {
    setCity('')
    setMaxPrice('')
    setBedrooms('')
    setSort(emptyFilters.sort)
    setRawQuery('')
    setActiveNaturalQuery('')
    setSearchMode('traditional')
    void router.push(propertySearchHref(emptyFilters))
  }

  function retrySearch() {
    if (searchMode === 'natural' && activeNaturalQuery.trim()) {
      void fetchNaturalProperties(activeNaturalQuery, page)
      return
    }
    void fetchProperties(page, appliedFilters, searchMode === 'edited')
  }

  function applyEditedCriteria(nextIntent: SearchIntent) {
    setEditableCriteria(nextIntent)
    setSearchMode('edited')
    setPage(1)
    const nextFilters = filtersFromIntent(nextIntent)
    setAppliedFilters(nextFilters)
    setCity(nextFilters.city)
    setMaxPrice(nextFilters.maxPrice)
    setBedrooms(nextFilters.bedrooms)
    setSort(nextFilters.sort)
    void fetchProperties(1, nextFilters, true)
  }

  function removeCriterion(field: keyof SearchIntent, neighborhood?: string) {
    if (!editableCriteria) return
    const nextIntent: SearchIntent = {
      ...editableCriteria,
      neighborhoods: [...editableCriteria.neighborhoods],
      unresolved_terms: [...editableCriteria.unresolved_terms],
    }

    if (field === 'neighborhoods' && neighborhood) {
      nextIntent.neighborhoods = nextIntent.neighborhoods.filter((item) => item !== neighborhood)
    } else if (field === 'unresolved_terms') {
      nextIntent.unresolved_terms = []
    } else {
      nextIntent[field] = null as never
    }
    applyEditedCriteria(nextIntent)
  }

  function updateNeighborhood(index: number, value: string, shouldApply: boolean) {
    if (!editableCriteria) return
    const neighborhoods = [...editableCriteria.neighborhoods]
    neighborhoods[index] = value
    const nextIntent = { ...editableCriteria, neighborhoods }
    setEditableCriteria(nextIntent)
    if (shouldApply && value.trim()) {
      applyEditedCriteria(nextIntent)
    }
  }

  function updateNumericCriterion(field: NumericField, value: string, shouldApply: boolean) {
    if (!editableCriteria) return
    const current = editableCriteria[field]
    if (!current) return

    const numericValue = value === '' ? null : Number(value)
    const key = criterionMode(current)
    const nextCriterion: NumericCriterion = {
      ...current,
      min_value: current.min_value ?? null,
      max_value: current.max_value ?? null,
      target_value: current.target_value ?? null,
      [key]: Number.isFinite(numericValue) ? numericValue : null,
    }
    const nextIntent = { ...editableCriteria, [field]: nextCriterion }
    setEditableCriteria(nextIntent)
    if (shouldApply) {
      applyEditedCriteria(nextIntent)
    }
  }

  function updateIssueCorrection(key: string, value: string) {
    setIssueCorrections((current) => ({ ...current, [key]: value }))
  }

  function applyIssueCorrection(issue: NormalizationIssue, index: number) {
    if (!editableCriteria) return
    const correction = issueCorrections[`${issue.field}-${index}`]?.trim()
    if (!correction) return

    if (issue.field === 'city') {
      applyEditedCriteria({ ...editableCriteria, city: correction })
      return
    }

    if (issue.field === 'neighborhoods') {
      applyEditedCriteria({
        ...editableCriteria,
        neighborhoods: [...editableCriteria.neighborhoods, correction],
      })
    }
  }

  function goToPage(nextPage: number) {
    if (searchMode === 'natural' && activeNaturalQuery.trim()) {
      void router.push(naturalSearchHref(activeNaturalQuery, nextPage))
      return
    }

    if (searchMode === 'edited') {
      setPage(nextPage)
      void fetchProperties(nextPage, appliedFilters, true)
      return
    }

    void router.push(propertySearchHref(appliedFilters, nextPage))
  }

  function renderNumericChip(field: NumericField, criterion: NumericCriterion) {
    const value = criterionValue(criterion)
    return (
      <span className={`criteria-chip ${criterion.importance}`} key={field}>
        <span>{numericCriterionLabel(field, criterion)}</span>
        <input
          aria-label={`Editar ${numericFieldLabels[field]}`}
          inputMode="numeric"
          min={0}
          type="number"
          value={value ?? ''}
          onBlur={(event) => updateNumericCriterion(field, event.target.value, true)}
          onChange={(event: ChangeEvent<HTMLInputElement>) => updateNumericCriterion(field, event.target.value, false)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              updateNumericCriterion(field, event.currentTarget.value, true)
            }
          }}
        />
        <small>{importanceLabel(criterion.importance)}</small>
        <button aria-label={`Remover ${numericFieldLabels[field]}`} type="button" onClick={() => removeCriterion(field)}>
          <X aria-hidden="true" size={14} />
        </button>
      </span>
    )
  }

  function renderCriteriaChips(intent: SearchIntent) {
    const chips = []
    if (intent.transaction_type) {
      chips.push(
        <span className="criteria-chip required" key="transaction">
          <span>{transactionLabels[intent.transaction_type] ?? intent.transaction_type}</span>
          <small>obrigatório</small>
          <button aria-label="Remover tipo de transação" type="button" onClick={() => removeCriterion('transaction_type')}>
            <X aria-hidden="true" size={14} />
          </button>
        </span>
      )
    }
    if (intent.property_type) {
      chips.push(
        <span className="criteria-chip required" key="property-type">
          <span>{propertyTypeLabels[intent.property_type] ?? intent.property_type}</span>
          <small>obrigatório</small>
          <button aria-label="Remover tipo de imóvel" type="button" onClick={() => removeCriterion('property_type')}>
            <X aria-hidden="true" size={14} />
          </button>
        </span>
      )
    }
    if (intent.city) {
      chips.push(
        <span className="criteria-chip required" key="city">
          <span>{intent.city}</span>
          <small>cidade</small>
          <button aria-label="Remover cidade" type="button" onClick={() => removeCriterion('city')}>
            <X aria-hidden="true" size={14} />
          </button>
        </span>
      )
    }
    intent.neighborhoods.forEach((neighborhood, index) => {
      chips.push(
        <span className="criteria-chip required editable" key={`neighborhood-${neighborhood}-${index}`}>
          <input
            aria-label={`Editar bairro ${neighborhood}`}
            value={neighborhood}
            onBlur={(event) => updateNeighborhood(index, event.target.value, true)}
            onChange={(event) => updateNeighborhood(index, event.target.value, false)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                updateNeighborhood(index, event.currentTarget.value, true)
              }
            }}
          />
          <small>bairro</small>
          <button aria-label={`Remover bairro ${neighborhood}`} type="button" onClick={() => removeCriterion('neighborhoods', neighborhood)}>
            <X aria-hidden="true" size={14} />
          </button>
        </span>
      )
    })

    const numericFields: NumericField[] = ['price', 'area_m2', 'bedrooms', 'bathrooms', 'parking_spaces']
    numericFields.forEach((field) => {
      const criterion = intent[field]
      if (criterion) chips.push(renderNumericChip(field, criterion))
    })

    if (intent.balcony) {
      chips.push(
        <span className={`criteria-chip ${intent.balcony.importance}`} key="balcony">
          <span>{intent.balcony.value ? 'Varanda' : 'Sem varanda'}</span>
          <small>{importanceLabel(intent.balcony.importance)}</small>
          <button aria-label="Remover varanda" type="button" onClick={() => removeCriterion('balcony')}>
            <X aria-hidden="true" size={14} />
          </button>
        </span>
      )
    }

    return chips
  }

  const totalPages = Math.max(1, Math.ceil(meta.total / meta.per_page))
  const hasResults = properties.length > 0
  const hasNaturalContext = searchMode === 'natural' || searchMode === 'edited'
  const hasAppliedFilters = Boolean(
    hasNaturalContext ||
    appliedFilters.city ||
    appliedFilters.maxPrice ||
    appliedFilters.bedrooms ||
    appliedFilters.sort !== emptyFilters.sort
  )
  const cityContext = appliedFilters.city.trim() ? ` em ${appliedFilters.city.trim()}` : ''
  const resultLabel = isLoading
    ? hasNaturalContext ? 'Entendendo sua busca e buscando imóveis compatíveis...' : 'Atualizando oportunidades...'
    : meta.total === 1
      ? hasNaturalContext ? '1 imóvel compatível encontrado' : `1 imóvel encontrado${cityContext}`
      : hasNaturalContext ? `${meta.total} imóveis compatíveis encontrados` : `${meta.total} imóveis encontrados${cityContext}`
  const rawQueryLength = rawQuery.length
  const canSubmitNatural = rawQuery.trim().length >= 3 && rawQueryLength <= MAX_QUERY_LENGTH && !isLoading
  const criteriaChips = editableCriteria ? renderCriteriaChips(editableCriteria) : []
  const paginationPages = Array.from({ length: Math.min(totalPages, 5) }, (_, index) => {
    if (totalPages <= 5) return index + 1
    if (page <= 3) return index + 1
    if (page >= totalPages - 2) return totalPages - 4 + index
    return page - 2 + index
  })
  const sortedProperties = useMemo(() => {
    const nextProperties = [...properties]
    if (hasNaturalContext && sort === 'relevance') return nextProperties

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
  }, [hasNaturalContext, properties, sort])

  return (
    <AppShell>
      <Head>
        <title>Imob Hub | Imóveis</title>
      </Head>

      <main className="results-page-shell">
        <section className="natural-search-band" aria-label="Busca em linguagem natural">
          <div className="section-inner natural-search-layout">
            <div className="natural-search-heading">
              <p className="eyebrow">Busca inteligente</p>
              <h1>Descreva o imóvel que você procura.</h1>
              <p>
                Escreva em linguagem natural. O Imob Hub transforma sua frase em critérios editáveis
                e mantém os filtros tradicionais disponíveis.
              </p>
            </div>

            <form className="natural-search-form" onSubmit={handleNaturalSubmit}>
              <label htmlFor="natural-search-query">Busca por descrição</label>
              <div className="natural-input-shell">
                <Sparkles aria-hidden="true" size={22} />
                <textarea
                  id="natural-search-query"
                  maxLength={MAX_QUERY_LENGTH}
                  onChange={(event) => setRawQuery(event.target.value)}
                  onKeyDown={handleNaturalKeyDown}
                  placeholder="Descreva o imóvel que você procura..."
                  rows={3}
                  value={rawQuery}
                  disabled={isLoading}
                />
              </div>
              <div className="natural-search-footer">
                <p>Ex.: apartamento de 100 m² em Pinheiros por até R$ 1 milhão</p>
                <span className={rawQueryLength > MAX_QUERY_LENGTH - 40 ? 'char-counter is-close' : 'char-counter'}>
                  {rawQueryLength}/{MAX_QUERY_LENGTH}
                </span>
              </div>
              <div className="natural-actions">
                <button className="button button-primary" type="submit" disabled={!canSubmitNatural}>
                  <Search aria-hidden="true" size={18} />
                  {isLoading && hasNaturalContext ? 'Buscando...' : 'Buscar com descrição'}
                </button>
                <button className="button button-ghost" type="button" onClick={clearFilters}>
                  Limpar
                </button>
              </div>
            </form>

            {requestStatus === 'initial' && !hasResults ? (
              <div className="natural-examples" aria-label="Exemplos de buscas">
                {exampleQueries.map((example) => (
                  <button key={example} type="button" onClick={() => setRawQuery(example)}>
                    {example}
                  </button>
                ))}
              </div>
            ) : null}

            {editableCriteria && hasIntentCriteria(editableCriteria) ? (
              <section className="criteria-panel" aria-label="Critérios interpretados">
                <div className="criteria-panel-header">
                  <div>
                    <p className="eyebrow">Entendido pela busca</p>
                    <h2>Critérios editáveis</h2>
                  </div>
                  {interpretedIntent ? <span>Texto original preservado</span> : null}
                </div>
                <div className="criteria-chips">
                  {criteriaChips}
                </div>
              </section>
            ) : null}

            {normalizationIssues.length ? (
              <section className="issue-panel" aria-label="Pontos para revisar">
                <div className="issue-panel-title">
                  <AlertCircle aria-hidden="true" size={20} />
                  <div>
                    <strong>Alguns termos precisam de confirmação.</strong>
                    <span>Corrija abaixo ou use os filtros avançados.</span>
                  </div>
                </div>
                {normalizationIssues.map((issue, index) => {
                  const key = `${issue.field}-${index}`
                  return (
                    <div className="issue-row" key={key}>
                      <p>
                        Não encontramos ou não confirmamos “{issue.original_value}”.
                      </p>
                      {(issue.field === 'city' || issue.field === 'neighborhoods') && editableCriteria ? (
                        <div className="issue-correction">
                          <input
                            aria-label={`Corrigir ${issue.original_value}`}
                            value={issueCorrections[key] ?? ''}
                            placeholder="Digite a correção"
                            onChange={(event) => updateIssueCorrection(key, event.target.value)}
                          />
                          <button className="button button-secondary" type="button" onClick={() => applyIssueCorrection(issue, index)}>
                            Aplicar
                          </button>
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </section>
            ) : null}

            <details className="advanced-filters-panel" open={requestStatus === 'model_unavailable'}>
              <summary>
                <SlidersHorizontal aria-hidden="true" size={18} />
                Filtros avançados
              </summary>
              <form onSubmit={handleTraditionalSubmit} className="listing-filter-bar">
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
            </details>
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
              <div className={requestStatus === 'model_unavailable' ? 'notice notice-warning' : 'notice notice-error'}>
                <span className="notice-icon"><HomeIcon aria-hidden="true" size={22} /></span>
                <div>
                  <strong>{error}</strong>
                  <span>
                    {requestStatus === 'model_unavailable'
                      ? 'Os filtros tradicionais continuam funcionando.'
                      : requestStatus === 'interpretation_error'
                        ? 'Você pode reformular a frase ou usar os filtros avançados.'
                        : 'Tente novamente em alguns instantes.'}
                  </span>
                </div>
                {requestStatus !== 'model_unavailable' ? (
                  <button className="button button-secondary retry-button" type="button" onClick={retrySearch}>
                    Tentar novamente
                  </button>
                ) : null}
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
                  <p>
                    Tente ajustar a descrição ou usar os filtros avançados para visualizar novas oportunidades.
                  </p>
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
