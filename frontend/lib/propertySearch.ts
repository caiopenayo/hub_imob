export type Property = {
  id: string
  title: string
  description?: string
  transaction_type?: string
  property_type?: string
  price?: number
  price_currency?: string
  property_subtype?: string
  city?: string
  neighborhood?: string
  bedrooms?: number
  bathrooms?: number
  parking_spaces?: number
  balcony?: boolean | null
  area_m2?: number
  main_image_url?: string
  updated_at?: string
  last_seen_at?: string
  url: string
  match_score?: number
  matched_preferences?: string[]
  missing_preferences?: string[]
  unknown_preferences?: string[]
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

export type RequirementLevel = 'required' | 'preferred'
export type TransactionType = 'sale' | 'rent'
export type PropertyType = 'apartment' | 'house' | 'studio' | 'commercial' | 'land'

export type NumericCriterion = {
  min_value?: number | null
  max_value?: number | null
  target_value?: number | null
  importance: RequirementLevel
}

export type BooleanCriterion = {
  value: boolean
  importance: RequirementLevel
}

export type SearchIntent = {
  transaction_type?: TransactionType | null
  property_type?: PropertyType | null
  city?: string | null
  neighborhoods: string[]
  price?: NumericCriterion | null
  area_m2?: NumericCriterion | null
  bedrooms?: NumericCriterion | null
  bathrooms?: NumericCriterion | null
  parking_spaces?: NumericCriterion | null
  balcony?: BooleanCriterion | null
  unresolved_terms: string[]
  clarification_needed: boolean
  clarification_question?: string | null
}

export type NormalizationIssue = {
  field: string
  original_value: string
  reason: string
}

export type SearchModelInfo = {
  provider: string
  model_id: string
}

export type NaturalSearchResponse = {
  query: string
  intent: SearchIntent
  normalized_intent: SearchIntent
  normalization_issues: NormalizationIssue[]
  items: Property[]
  meta: Meta
  model: SearchModelInfo
}

export type NaturalSearchRequest = {
  query: string
  page?: number
  perPage?: number
  signal?: AbortSignal
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

export async function fetchNaturalSearch({
  query,
  page = 1,
  perPage = 21,
  signal,
}: NaturalSearchRequest): Promise<NaturalSearchResponse> {
  const response = await fetch(`${API_URL}/search`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      query,
      page,
      per_page: perPage,
    }),
    signal,
  })

  if (!response.ok) {
    const message = response.status === 503
      ? 'A busca em linguagem natural está temporariamente indisponível.'
      : 'Não conseguimos interpretar essa busca.'
    throw new ApiError(message, response.status)
  }

  return response.json() as Promise<NaturalSearchResponse>
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
