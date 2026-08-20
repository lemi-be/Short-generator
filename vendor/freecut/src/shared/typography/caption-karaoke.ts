import type { TextSpan } from '@/types/text'
import type { CaptionKaraokeStyle, TranscriptCaptionWord } from '@/types/timeline'

export const DEFAULT_KARAOKE_COLOR = '#ffd400'

interface KaraokeSegmentStyle {
  karaokeStyle?: CaptionKaraokeStyle
  karaokeColor?: string
  color?: string
}

export interface KaraokeCueView {
  text: string
  words?: readonly TranscriptCaptionWord[]
}

export interface KaraokeSpanResult {
  /** Full phrase text (words joined with spaces). */
  text: string
  /** One span per word; the active word carries the accent color. */
  spans: TextSpan[]
  /** Karaoke recolors words inside one wrapped line. */
  spanLayout: 'inline'
}

/**
 * Build the inline spans for a karaoke caption cue.
 *
 * When `karaokeStyle === 'word'` and the cue carries word timings, the whole
 * phrase renders in `color` and the word active at `secondsIntoCue` is
 * recolored with `karaokeColor`. Returns `null` to fall back to the plain
 * (markup-parsed) caption path when karaoke isn't applicable for this frame.
 */
export function buildKaraokeSpans(
  cue: KaraokeCueView,
  secondsIntoCue: number,
  style: KaraokeSegmentStyle,
): KaraokeSpanResult | null {
  const words = cue.words
  if (!isKaraokeEnabled(style) || !words || words.length === 0) return null

  const activeIndex = words.findIndex(
    (word) => secondsIntoCue >= word.start && secondsIntoCue < word.end,
  )
  // Between words (or outside the last word's window) there is nothing to
  // highlight yet — fall back to the plain rendering in the base color.
  if (activeIndex < 0) return null

  const baseColor = style.color ?? '#ffffff'
  const accentColor = style.karaokeColor ?? DEFAULT_KARAOKE_COLOR
  const spans: TextSpan[] = words.map((word, index) => ({
    text: index < words.length - 1 ? `${word.text} ` : word.text,
    color: index === activeIndex ? accentColor : baseColor,
  }))

  return {
    text: spans.map((span) => span.text).join(''),
    spans,
    spanLayout: 'inline',
  }
}

export function isKaraokeEnabled(style: KaraokeSegmentStyle | undefined): boolean {
  return style?.karaokeStyle === 'word'
}