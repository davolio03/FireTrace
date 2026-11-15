import { useMapStore } from '../../state/mapStore'
import { type Layer, visibleMapLayers } from './layers'
import { isSupportedComparison } from './comparison'

function Legend({ layer }: { layer: Layer }) {
  const legend = layer.legend
  return (
    <div
      className="mt-2 text-xs text-slate-700"
      aria-label={`Legend for ${layer.title}`}
    >
      <p className="font-semibold">Legend</p>
      {legend.type === 'continuous' && (
        <>
          <span>{legend.units}</span>
          <div className="mt-1 flex flex-wrap gap-3">
            {legend.stops.map((stop) => (
              <span key={stop.value} className="flex items-center gap-1">
                <span
                  aria-hidden="true"
                  className="inline-block h-3 w-3 border border-slate-500"
                  style={{ backgroundColor: stop.color }}
                />
                {stop.value}
              </span>
            ))}
          </div>
        </>
      )}
      {legend.type === 'categorical' &&
        legend.items.map((item) => (
          <span key={item.value} className="flex items-center gap-1">
            <span
              aria-hidden="true"
              className="inline-block h-3 w-3 border border-slate-500"
              style={{ backgroundColor: item.color }}
            />
            {item.label}
          </span>
        ))}
      {'note' in legend && legend.note && <p>{legend.note}</p>}
      {layer.kind === 'raster' && <p>Transparent pixels indicate no data.</p>}
    </div>
  )
}

export function LayerControls({ layers }: { layers: Layer[] }) {
  const visible = useMapStore((state) => state.visible)
  const opacity = useMapStore((state) => state.opacity)
  const toggleLayer = useMapStore((state) => state.toggleLayer)
  const setOpacity = useMapStore((state) => state.setOpacity)
  const compare = useMapStore((state) => state.compare)
  const comparing = isSupportedComparison(compare, layers)

  return (
    <section
      aria-label="Map layers"
      className="rounded-lg border border-slate-300 p-4"
    >
      <h2 className="text-xl font-semibold">Map layers</h2>
      <p className="mt-2 text-sm text-slate-700">
        The first layer is at the bottom and the last is at the top. Visible
        layers above can hide layers below.
      </p>
      {comparing && (
        <p className="mt-2 text-sm text-slate-700">
          Raster layer controls are paused during comparison. Their selections
          and opacity are restored when comparison ends.
        </p>
      )}
      {visibleMapLayers(layers).map((layer) => (
        <div key={layer.id} className="mt-4 border-t border-slate-200 pt-3">
          <label className="flex gap-2 font-medium">
            <input
              type="checkbox"
              disabled={comparing && layer.kind === 'raster'}
              checked={visible.includes(layer.id)}
              onChange={() => toggleLayer(layer.id)}
            />
            <span>{layer.title}</span>
          </label>
          <label className="mt-2 block text-sm">
            Opacity for {layer.title}
            <input
              className="block w-full"
              type="range"
              disabled={
                !visible.includes(layer.id) ||
                (comparing && layer.kind === 'raster')
              }
              min="0"
              max="1"
              step="0.05"
              value={opacity[layer.id] ?? layer.default_opacity}
              onChange={(event) =>
                setOpacity(layer.id, Number(event.target.value))
              }
            />
          </label>
          <Legend layer={layer} />
        </div>
      ))}
    </section>
  )
}
