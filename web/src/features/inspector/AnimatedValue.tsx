import { animate, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'

/**
 * A measured value that counts to its new reading, the way an instrument
 * settles after a measurement arrives. The final text is exactly the value
 * the contract returned; the animation only changes how it arrives.
 */
export function AnimatedValue({
  value,
  fallback = 'Not available',
}: {
  value: number | null | undefined
  fallback?: string
}) {
  const reduced = useReducedMotion()
  const key = value ?? null
  const [rendered, setRendered] = useState<{
    key: number | null
    text: string | null
  }>({ key, text: key === null ? null : String(value) })
  const previous = useRef<number | null>(key)

  // A new measurement replaces the reading; the effect below animates it.
  if (rendered.key !== key) {
    setRendered({ key, text: key === null ? null : String(value) })
  }

  useEffect(() => {
    if (value === null || value === undefined) return
    const from = previous.current
    previous.current = value
    if (reduced || from === null || from === value) return
    const controls = animate(from, value, {
      duration: 0.55,
      ease: [0.2, 0.7, 0.2, 1],
      onUpdate: (current) =>
        setRendered((state) => ({ ...state, text: current.toFixed(2) })),
      onComplete: () =>
        setRendered((state) => ({ ...state, text: String(value) })),
    })
    return () => controls.stop()
  }, [value, reduced])

  if (rendered.text === null) return <>{fallback}</>
  return <span className="readout-value">{rendered.text}</span>
}
