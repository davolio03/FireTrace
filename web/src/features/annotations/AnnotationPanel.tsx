import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ChangeEvent } from 'react'
import type { operations } from '../../generated/api'
import { useMapStore } from '../../state/mapStore'
import { loadVerifiedZones } from './zoneProvenance'
import {
  createAnnotation,
  loadAnnotations,
  parseExport,
  saveAnnotations,
  validGeometry,
  type AnnotationDocument,
  type Evidence,
  type Verdict,
} from './annotations'

type CaseData =
  operations['getCase']['responses'][200]['content']['application/json']
type PointEvidence =
  operations['inspectPoint']['responses'][200]['content']['application/json']
const verdicts: [Verdict, string][] = [
  ['consistent_with_fire', 'Consistent with fire effects'],
  ['doubtful', 'Doubtful'],
  ['not_fire_related', 'Likely not fire-related'],
  ['needs_field_check', 'Needs field check'],
]

function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

function safeText(text: string) {
  return text.replace(/[\\`*_{}[\]()<>|#!]/g, '\\$&').replace(/\r?\n/g, ' ')
}

export function AnnotationPanel({
  caseData,
  captureMap,
  displayStatus,
}: {
  caseData: CaseData | null
  captureMap: (() => string) | null
  displayStatus?: 'loading' | 'mock' | 'real' | 'error'
}) {
  const selection = useMapStore((state) => state.selection)
  const select = useMapStore((state) => state.select)
  const compare = useMapStore((state) => state.compare)
  const client = useQueryClient()
  const [document, setDocument] = useState<AnnotationDocument | null>(null)
  const [pending, setPending] = useState<AnnotationDocument | null>(null)
  const [author, setAuthor] = useState('')
  const [note, setNote] = useState('')
  const [verdict, setVerdict] = useState<Verdict>('needs_field_check')
  const [error, setError] = useState('')
  const [storageCase, setStorageCase] = useState<string | null>(null)
  const zoneId = selection.type === 'zone' ? selection.zoneId : null
  const zoneQuery = useQuery({
    queryKey: [
      'annotation-zone',
      import.meta.env.VITE_DATA_BASE_URL || '/',
      caseData?.case_id,
      caseData?.data_status,
      caseData?.method?.id,
      JSON.stringify(caseData),
    ],
    enabled: !!caseData?.case_id,
    retry: false,
    queryFn: async () => {
      if (!caseData?.method?.id) throw new Error('Zone provenance unavailable')
      return loadVerifiedZones(
        import.meta.env.VITE_DATA_BASE_URL || '/',
        caseData,
      )
    },
  })

  useEffect(() => {
    if (!caseData?.case_id) return
    let active = true
    const caseId = caseData.case_id
    Promise.resolve().then(() => {
      if (!active) return
      try {
        setDocument(loadAnnotations(caseId))
        setStorageCase(caseId)
        setError('')
      } catch {
        setStorageCase(null)
        setError(
          'Saved annotations cannot be read safely. Existing data was not changed.',
        )
      }
    })
    return () => {
      active = false
    }
  }, [caseData?.case_id])

  function addAnnotation() {
    try {
      if (!caseData || storageCase !== caseData.case_id)
        throw new Error('Case data or storage is unavailable.')
      const zone =
        selection.type === 'zone'
          ? zoneQuery.data?.features.find(
              (feature) => feature.id === selection.zoneId,
            )
          : undefined
      if (selection.type === 'zone' && !zone)
        throw new Error(
          'Zone provenance cannot be verified for this case and method; no annotation was saved.',
        )
      const existing = loadAnnotations(caseData.case_id)
      if (
        existing &&
        (existing.data_status !== caseData.data_status ||
          existing.method_id !== caseData.method?.id)
      )
        throw new Error(
          'Saved annotations belong to a different data status or method. Existing data was not changed.',
        )
      const empty: Evidence = {
        change_index: null,
        hh_delta_db: null,
        hv_delta_db: null,
        perimeter_relation: 'unknown',
      }
      const point =
        selection.type === 'point'
          ? client.getQueryData<PointEvidence>([
              'inspect-point',
              ...selection.point,
            ])
          : undefined
      const evidence: Evidence =
        point &&
        point.data_status === caseData.data_status &&
        point.method_id === caseData.method?.id &&
        point.valid
          ? {
              change_index: point.change_index,
              hh_delta_db: point.hh_db.delta,
              hv_delta_db: point.hv_db.delta,
              perimeter_relation: point.perimeter_relation,
              caveat_ids: point.caveats
                .filter((caveat) => caveat.triggered)
                .map((caveat) => caveat.id),
            }
          : empty
      if (zone) {
        const median = (value: unknown, key: string): number | null => {
          if (typeof value !== 'object' || value === null || !(key in value))
            return null
          const candidate = (value as Record<string, unknown>)[key]
          return typeof candidate === 'number' && Number.isFinite(candidate)
            ? candidate
            : null
        }
        evidence.hh_delta_db = median(zone.properties.hh_db, 'delta_median')
        evidence.hv_delta_db = median(zone.properties.hv_db, 'delta_median')
        evidence.change_index = median(zone.properties.change_index, 'median')
        if (Array.isArray(zone.properties.caveats)) {
          evidence.caveat_ids = zone.properties.caveats.flatMap(
            (caveat: unknown) =>
              typeof caveat === 'object' &&
              caveat !== null &&
              'id' in caveat &&
              typeof caveat.id === 'string' &&
              'fraction' in caveat &&
              typeof caveat.fraction === 'number' &&
              Number.isFinite(caveat.fraction) &&
              caveat.fraction > 0 &&
              caveat.fraction <= 1
                ? [caveat.id]
                : [],
          )
        }
        evidence.perimeter_relation =
          zone.properties.kind === 'change_outside_perimeter'
            ? 'outside'
            : zone.properties.kind === 'no_change_inside_perimeter' ||
                zone.properties.kind === 'change_inside_perimeter'
              ? 'inside'
              : 'unknown'
      }
      const feature = createAnnotation({
        selection,
        author,
        note,
        verdict,
        evidence,
        zoneGeometry: zone?.geometry,
      })
      const next: AnnotationDocument = {
        type: 'FeatureCollection',
        contract_version: '1.2.0',
        case_id: caseData.case_id,
        data_status: caseData.data_status,
        method_id: caseData.method?.id,
        exported_at: new Date().toISOString(),
        features: [...(existing?.features ?? []), feature],
      }
      saveAnnotations(next)
      setDocument(next)
      setNote('')
      setError('')
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Unable to save annotation.',
      )
    }
  }

  async function prepareImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !caseData) return
    try {
      const parsed = parseExport(await file.text(), caseData.case_id)
      if (
        parsed.data_status !== caseData.data_status ||
        parsed.method_id !== caseData.method?.id
      )
        throw new Error(
          'Import data status or method does not match this case.',
        )
      setPending(parsed)
      setError('')
    } catch {
      setPending(null)
      setError(
        'The annotation file is invalid or incompatible. Existing data was not changed.',
      )
    }
  }

  function confirmImport() {
    if (
      !pending ||
      !caseData ||
      storageCase !== caseData.case_id ||
      pending.case_id !== caseData.case_id ||
      pending.data_status !== caseData.data_status ||
      pending.method_id !== caseData.method?.id
    )
      return
    try {
      saveAnnotations(pending)
      setDocument(pending)
      setPending(null)
      setError('')
    } catch {
      setError('Unable to import annotations. Existing data was not changed.')
    }
  }

  function exportReport() {
    if (!document || !caseData || !captureMap || compare) {
      setError(
        'A map and saved annotations are required; exit comparison before exporting the report.',
      )
      return
    }
    try {
      const image = captureMap()
      if (!image.startsWith('data:image/png;base64,'))
        throw new Error('Map capture unavailable')
      const entries = document.features
        .map(
          (feature) =>
            `| ${safeText(feature.properties.target.type)} | ${safeText(feature.properties.verdict)} | ${safeText(feature.properties.author)} | ${safeText(feature.properties.note)} | ${safeText(JSON.stringify(feature.properties.evidence))} |`,
        )
        .join('\n')
      const sources = (caseData.sources ?? [])
        .map((source) => `- ${safeText(source.label)}: ${safeText(source.url)}`)
        .join('\n')
      const reference = caseData.reference
      const report = `# Analyst report — ${safeText(caseData.name)}\n\n${document.data_status === 'mock' || displayStatus === 'mock' ? '**MOCK — synthetic data; not scientific validation.**\n\n' : ''}Radar changes do not confirm burned area. Verdicts are analyst judgement, not validated classifications.\n\n## Map\n\nPrimary map canvas; selection markers and overlays are not included.\n\n![Primary map](${image})\n\n## Annotations\n\n| Target | Analyst judgement | Author | Note | Evidence |\n| --- | --- | --- | --- | --- |\n${entries}\n\n## Method\n\n${safeText(caseData.method.name)} — ${safeText(caseData.method.description)}\n\n## Sources\n\n${sources}\n\n## Official fire perimeter\n\n${safeText(reference.source)} — ${safeText(reference.datetime)}\n\n${safeText(reference.note)}\n`
      download('firetrace-report.md', report, 'text/markdown;charset=utf-8')
      setError('')
    } catch {
      setError(
        'Unable to capture the map or export the report. Existing data was not changed.',
      )
    }
  }

  return (
    <section
      aria-labelledby="annotations-heading"
      className="mt-6 space-y-3 rounded-lg border border-slate-300 p-4"
    >
      <h2 id="annotations-heading" className="text-xl font-semibold">
        Analyst annotations
      </h2>
      <p>
        Verdicts are analyst judgement, not scientific validation. Select a
        point, profile or a zone with verified bundle provenance.
      </p>
      {(caseData?.data_status === 'mock' || displayStatus === 'mock') && (
        <p>MOCK — synthetic evidence, not scientific validation.</p>
      )}
      {error && <p role="alert">{error}</p>}
      {zoneId && zoneQuery.isPending && (
        <p role="status">Loading zone geometry…</p>
      )}
      {zoneId && zoneQuery.isError && (
        <p role="alert">Zone geometry is unavailable.</p>
      )}
      {typeof zoneQuery.data === 'object' &&
        zoneQuery.data !== null &&
        'features' in zoneQuery.data &&
        Array.isArray(zoneQuery.data.features) && (
          <label className="block">
            Select a zone
            <select
              className="block rounded border p-1"
              value={zoneId ?? ''}
              onChange={(event) => {
                if (event.target.value)
                  select({ type: 'zone', zoneId: event.target.value })
              }}
            >
              <option value="">Choose a zone</option>
              {zoneQuery.data.features
                .filter(
                  (item: unknown) =>
                    typeof item === 'object' &&
                    item !== null &&
                    'id' in item &&
                    typeof item.id === 'string' &&
                    'geometry' in item &&
                    validGeometry(item.geometry),
                )
                .map((item: { id: string }) => (
                  <option key={item.id} value={item.id}>
                    {item.id}
                  </option>
                ))}
            </select>
          </label>
        )}
      <label className="block">
        Author{' '}
        <input
          className="block rounded border p-1"
          value={author}
          onChange={(event) => setAuthor(event.target.value)}
        />
      </label>
      <label className="block">
        Verdict{' '}
        <select
          className="block rounded border p-1"
          value={verdict}
          onChange={(event) => setVerdict(event.target.value as Verdict)}
        >
          {verdicts.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        Note{' '}
        <textarea
          className="block w-full rounded border p-1"
          maxLength={2000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <button
        type="button"
        className="rounded border px-3 py-2"
        disabled={!caseData || storageCase !== caseData.case_id}
        onClick={addAnnotation}
      >
        Save annotation
      </button>
      <ul>
        {document?.features.map((feature) => (
          <li key={feature.id}>
            {feature.properties.author}: {feature.properties.note} —{' '}
            {verdicts.find(([id]) => id === feature.properties.verdict)?.[1]}
            <p>
              Target: {feature.properties.target.type}
              {feature.properties.target.zone_id
                ? ` (${feature.properties.target.zone_id})`
                : ''}
            </p>
            <p>Created: {feature.properties.created_at}</p>
            <p>
              Change index:{' '}
              {feature.properties.evidence.change_index ?? 'Unavailable'}
            </p>
            <p>
              HH change:{' '}
              {feature.properties.evidence.hh_delta_db ?? 'Unavailable'}; HV
              change: {feature.properties.evidence.hv_delta_db ?? 'Unavailable'}
            </p>
            <p>
              Perimeter relation:{' '}
              {feature.properties.evidence.perimeter_relation}
            </p>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="rounded border px-3 py-2"
        disabled={!document}
        onClick={() => {
          if (!document) return
          try {
            download(
              'firetrace-annotations.geojson',
              JSON.stringify(
                { ...document, exported_at: new Date().toISOString() },
                null,
                2,
              ),
              'application/geo+json',
            )
            setError('')
          } catch {
            setError('Unable to export annotations.')
          }
        }}
      >
        Export GeoJSON
      </button>{' '}
      <label>
        Import GeoJSON{' '}
        <input
          type="file"
          accept=".json,.geojson,application/geo+json"
          onChange={prepareImport}
        />
      </label>
      {pending && (
        <div>
          <p>
            Import {pending.features.length} annotations? This replaces saved
            annotations.
          </p>
          <button
            type="button"
            className="rounded border px-3 py-2"
            onClick={confirmImport}
          >
            Confirm replace annotations
          </button>{' '}
          <button type="button" onClick={() => setPending(null)}>
            Cancel import
          </button>
        </div>
      )}
      <button
        type="button"
        className="rounded border px-3 py-2"
        onClick={exportReport}
      >
        Export Markdown report
      </button>
    </section>
  )
}
