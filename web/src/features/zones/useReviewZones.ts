import { useQuery } from '@tanstack/react-query'
import { isReviewZones, type ReviewZones } from './reviewZones'

export function useReviewZones() {
  const base = import.meta.env.VITE_DATA_BASE_URL || '/'
  return useQuery({
    queryKey: ['review-zones', base],
    retry: false,
    queryFn: async ({ signal }): Promise<ReviewZones> => {
      const response = await fetch(
        `${base.replace(/\/+$/, '')}/review_zones.geojson`,
        { signal },
      )
      if (!response.ok) throw new Error('Unable to load review zones')
      const body: unknown = await response.json()
      if (!isReviewZones(body)) throw new Error('Invalid review zones')
      return body
    },
  })
}
