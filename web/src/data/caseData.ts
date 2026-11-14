import type { operations } from '../generated/api'

type Case =
  operations['getCase']['responses'][200]['content']['application/json']
type Stats =
  operations['getStats']['responses'][200]['content']['application/json']
type Layers =
  operations['getLayers']['responses'][200]['content']['application/json']

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Unable to load ${url}: ${response.status}`)
  const data: unknown = await response.json()
  if (
    typeof data !== 'object' ||
    data === null ||
    !('data_status' in data) ||
    (data.data_status !== 'mock' && data.data_status !== 'real')
  ) {
    throw new Error(`Invalid data_status in ${url}`)
  }
  return data as T
}

export async function loadCaseData(baseUrl: string) {
  const base = baseUrl.replace(/\/+$/, '')
  const [caseData, stats, layers] = await Promise.all([
    getJson<Case>(`${base}/case.json`),
    getJson<Stats>(`${base}/stats.json`),
    getJson<Layers>(`${base}/layers.json`),
  ])
  return { case: caseData, stats, layers }
}
