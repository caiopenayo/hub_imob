import { useEffect, useMemo, useState } from 'react'
import Image from 'next/image'
import {
  Bath,
  BedDouble,
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Heart,
  Images,
  MapPin,
  Maximize2,
  Share2,
} from 'lucide-react'

import type { Property } from '../lib/propertySearch'

type PropertyCardProps = {
  property: Property
  priority?: boolean
}

const imageBlurDataUrl =
  'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIwMCIgaGVpZ2h0PSI3NTAiIHZpZXdCb3g9IjAgMCAxMjAwIDc1MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZGVmcz48bGluZWFyR3JhZGllbnQgaWQ9ImciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj48c3RvcCBzdG9wLWNvbG9yPSIjZmFmOGY0Ii8+PHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjZWVmMmZmIi8+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PHJlY3QgZmlsbD0idXJsKCNnKSIgd2lkdGg9IjEyMDAiIGhlaWdodD0iNzUwIi8+PC9zdmc+'
const galleryPreloadOffsets = [-2, -1, 1, 2]

function formatPrice(price?: number, currency = 'BRL'): string {
  if (!price) {
    return 'Preço não informado'
  }
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency,
  }).format(price)
}

function formatLocation(city?: string, neighborhood?: string): string {
  if (city && neighborhood) return `${neighborhood}, ${city}`
  if (city) return city
  if (neighborhood) return neighborhood
  return 'Localização não informada'
}

function getSourceLabel(source?: string): string {
  if (!source) return 'Fonte externa'
  return source.charAt(0).toUpperCase() + source.slice(1)
}

function getValidImageSrc(src?: string): string | null {
  if (!src) return null
  if (src.startsWith('/') || src.startsWith('https://') || src.startsWith('http://')) return src
  return null
}

function getImageGallery(property: Property): string[] {
  const metadataImages = Array.isArray(property.metadata?.images)
    ? property.metadata.images.filter((src): src is string => typeof src === 'string')
    : []
  const rawImages = [property.metadata?.main_image, ...metadataImages]
  const images = rawImages
    .map((src) => getValidImageSrc(src))
    .filter((src): src is string => Boolean(src))

  const uniqueImages = Array.from(new Set(images))
  return uniqueImages.length ? uniqueImages : ['/images/property-fallback.png']
}

export function PropertyCard({ property, priority = false }: PropertyCardProps) {
  const [isFavorite, setIsFavorite] = useState(Boolean(property.metadata?.is_favorite))
  const [currentImageIndex, setCurrentImageIndex] = useState(0)
  const favoriteStorageKey = `imobhub:favorites:${property.id}`
  const galleryImages = useMemo(() => getImageGallery(property), [property])
  const imageSrc = galleryImages[currentImageIndex] ?? '/images/property-fallback.png'
  const hasGallery = galleryImages.length > 1
  const isRemoteImage = imageSrc.startsWith('http://') || imageSrc.startsWith('https://')
  const sourceLabel = getSourceLabel(property.metadata?.source)

  useEffect(() => {
    setCurrentImageIndex(0)
  }, [property.id, galleryImages.length])

  useEffect(() => {
    try {
      const savedFavorite = window.localStorage.getItem(favoriteStorageKey)
      if (savedFavorite !== null) {
        setIsFavorite(savedFavorite === 'true')
      }
    } catch {
      // Favorites still work for the current session if local persistence is unavailable.
    }
  }, [favoriteStorageKey])

  useEffect(() => {
    if (!hasGallery || typeof window === 'undefined') return

    galleryPreloadOffsets.forEach((offset) => {
      const nextIndex = (currentImageIndex + offset + galleryImages.length) % galleryImages.length
      const nextImageSrc = galleryImages[nextIndex]
      if (!nextImageSrc || nextImageSrc === imageSrc) return

      const preloadedImage = new window.Image()
      preloadedImage.decoding = 'async'
      preloadedImage.src = nextImageSrc
    })
  }, [currentImageIndex, galleryImages, hasGallery, imageSrc])

  function toggleFavorite() {
    setIsFavorite((current) => {
      const nextFavorite = !current
      try {
        window.localStorage.setItem(favoriteStorageKey, String(nextFavorite))
      } catch {
        // Keep the visual state responsive even when browser storage is blocked.
      }
      return nextFavorite
    })
  }

  async function shareProperty() {
    if (typeof navigator === 'undefined') return
    const shareData = {
      title: property.title || 'Imóvel no Imob Hub',
      url: property.url,
    }

    try {
      if (navigator.share) {
        await navigator.share(shareData)
        return
      }
      await navigator.clipboard?.writeText(property.url)
    } catch {
      // Sharing is a convenience action; cancelled native shares should not interrupt browsing.
    }
  }

  function showPreviousImage() {
    setCurrentImageIndex((current) => (
      current === 0 ? galleryImages.length - 1 : current - 1
    ))
  }

  function showNextImage() {
    setCurrentImageIndex((current) => (
      current === galleryImages.length - 1 ? 0 : current + 1
    ))
  }

  return (
    <article className="property-card">
      <div className="property-media">
        <Image
          alt={property.title || 'Imóvel'}
          blurDataURL={imageBlurDataUrl}
          className="property-image"
          fill
          placeholder="blur"
          priority={priority}
          sizes="(max-width: 820px) 100vw, (max-width: 1040px) 50vw, 33vw"
          src={imageSrc}
          unoptimized={isRemoteImage}
        />
        <a
          aria-label={`Abrir anúncio original: ${property.title || 'imóvel'}`}
          className="property-media-link"
          href={property.url}
          target="_blank"
          rel="noreferrer"
        />
        <span className="source-badge">
          <Building2 aria-hidden="true" size={13} />
          Fonte original: {sourceLabel}
        </span>

        {hasGallery ? (
          <>
            <button
              aria-label="Foto anterior"
              className="property-gallery-button previous"
              type="button"
              onClick={showPreviousImage}
            >
              <ChevronLeft aria-hidden="true" size={20} />
            </button>
            <button
              aria-label="Próxima foto"
              className="property-gallery-button next"
              type="button"
              onClick={showNextImage}
            >
              <ChevronRight aria-hidden="true" size={20} />
            </button>
            <span className="property-gallery-count">
              <Images aria-hidden="true" size={14} />
              {currentImageIndex + 1}/{galleryImages.length}
            </span>
          </>
        ) : null}
      </div>
      <div className="property-media-actions">
        <button
          aria-label={isFavorite ? 'Remover dos favoritos' : 'Salvar nos favoritos'}
          aria-pressed={isFavorite}
          className={isFavorite ? 'property-icon-button active' : 'property-icon-button'}
          type="button"
          onClick={toggleFavorite}
        >
          <Heart aria-hidden="true" fill={isFavorite ? 'currentColor' : 'none'} size={18} />
        </button>
        <button
          aria-label="Compartilhar imóvel"
          className="property-icon-button"
          type="button"
          onClick={shareProperty}
        >
          <Share2 aria-hidden="true" size={18} />
        </button>
      </div>

      <div className="property-body">
        <div className="property-heading">
          <div>
            <p className="property-location">
              <MapPin aria-hidden="true" size={15} />
              {formatLocation(property.city, property.neighborhood)}
            </p>
            <h2>{property.title || 'Imóvel sem título'}</h2>
          </div>
          <strong className="property-price">
            {formatPrice(property.price, property.price_currency)}
          </strong>
        </div>

        <div className="facts" aria-label="Detalhes do imóvel">
          <span><Maximize2 aria-hidden="true" size={17} />{property.area_m2 ? `${property.area_m2} m²` : '- m²'}</span>
          <span><BedDouble aria-hidden="true" size={17} />{property.bedrooms ?? '-'} quartos</span>
          <span><Bath aria-hidden="true" size={17} />{property.bathrooms ?? '-'} banheiros</span>
        </div>

        <p className="property-source">
          <CheckCircle2 aria-hidden="true" size={16} />
          Encontrado e comparado via Imob Hub · Anúncio original em {sourceLabel}
        </p>

        <div className="property-actions">
          <a className="button button-primary" href={property.url} target="_blank" rel="noreferrer">
            <ExternalLink aria-hidden="true" size={17} />
            Ver anúncio original
          </a>
        </div>
      </div>
    </article>
  )
}
