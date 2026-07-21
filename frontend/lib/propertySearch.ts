export type Property = {
  id: string
  title: string
  description?: string
  price?: number
  price_currency?: string
  property_subtype?: string
  city?: string
  neighborhood?: string
  bedrooms?: number
  bathrooms?: number
  area_m2?: number
  main_image_url?: string
  updated_at?: string
  last_seen_at?: string
  url: string
  metadata?: {
    main_image?: string
    images?: string[]
    source?: string
    compared_sources?: number
    neighborhood_avg_price?: number
    is_favorite?: boolean
    [key: string]: unknown
  }
}

export type Meta = {
  page: number
  per_page: number
  total: number
}

export type Filters = {
  city: string
  maxPrice: string
  bedrooms: string
  sort: SortKey
}

export type SortKey =
  | 'relevance'
  | 'price_asc'
  | 'price_desc'
  | 'area_desc'
  | 'bedrooms_desc'
  | 'recent'

type SearchHrefFilters = {
  city: string
  maxPrice: string
  bedrooms: string
  sort?: SortKey
}

type SearchQuery = Record<string, string | string[] | undefined>

export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const defaultSort: SortKey = 'relevance'

export const emptyFilters: Filters = {
  city: '',
  maxPrice: '',
  bedrooms: '',
  sort: defaultSort,
}

export const maxPriceOptions = [
  { label: 'Até R$ 200 mil', value: '200000' },
  { label: 'Até R$ 300 mil', value: '300000' },
  { label: 'Até R$ 500 mil', value: '500000' },
  { label: 'Até R$ 750 mil', value: '750000' },
  { label: 'Até R$ 1 milhão', value: '1000000' },
  { label: 'Até R$ 2 milhões', value: '2000000' },
  { label: 'Sem limite', value: '' },
]

export const bedroomOptions = [
  { label: 'Qualquer', value: '' },
  { label: '1+ quarto', value: '1' },
  { label: '2+ quartos', value: '2' },
  { label: '3+ quartos', value: '3' },
  { label: '4+ quartos', value: '4' },
  { label: '5+ quartos', value: '5' },
]

export const sortOptions = [
  { label: 'Mais relevantes', value: 'relevance' },
  { label: 'Menor preço', value: 'price_asc' },
  { label: 'Maior preço', value: 'price_desc' },
  { label: 'Maior área', value: 'area_desc' },
  { label: 'Mais quartos', value: 'bedrooms_desc' },
  { label: 'Mais recentes', value: 'recent' },
] satisfies Array<{ label: string; value: SortKey }>

function queryValue(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? ''
  return value ?? ''
}

function sortFromQuery(value: string): SortKey {
  return sortOptions.some((option) => option.value === value) ? (value as SortKey) : defaultSort
}

export function filtersFromQuery(query: SearchQuery): Filters {
  return {
    city: queryValue(query.city),
    maxPrice: queryValue(query.max_price),
    bedrooms: queryValue(query.bedrooms),
    sort: sortFromQuery(queryValue(query.sort)),
  }
}

export function pageFromQuery(query: SearchQuery): number {
  const page = Number(queryValue(query.page))
  return Number.isFinite(page) && page > 0 ? page : 1
}

export function buildPropertySearchParams(filters: SearchHrefFilters, page?: number): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.city.trim()) params.append('city', filters.city.trim())
  if (filters.maxPrice) params.append('max_price', filters.maxPrice)
  if (filters.bedrooms) params.append('bedrooms', filters.bedrooms)
  if (filters.sort && filters.sort !== defaultSort) params.append('sort', filters.sort)
  if (page && page > 1) params.append('page', String(page))
  return params
}

export function propertySearchHref(filters: SearchHrefFilters, page?: number): string {
  const params = buildPropertySearchParams(filters, page)
  const queryString = params.toString()
  return queryString ? `/imoveis?${queryString}` : '/imoveis'
}
