import { describe, expect, it } from 'vite-plus/test'

import { buildKaraokeSpans, isKaraokeEnabled } from './caption-karaoke'

const cue = {
  text: 'Hello there world',
  words: [
    { text: 'Hello', start: 0, end: 0.4 },
    { text: 'there', start: 0.4, end: 0.9 },
    { text: 'world', start: 0.9, end: 1.3 },
  ],
}

const style = { karaokeStyle: 'word' as const, karaokeColor: '#ffd400', color: '#ffffff' }

describe('caption karaoke', () => {
  it('is off unless karaokeStyle is word', () => {
    expect(isKaraokeEnabled(undefined)).toBe(false)
    expect(isKaraokeEnabled({ karaokeStyle: 'off' })).toBe(false)
    expect(isKaraokeEnabled({ karaokeStyle: 'word' })).toBe(true)
  })

  it('returns null when karaoke is disabled or the cue has no word timings', () => {
    expect(buildKaraokeSpans(cue, 0.1, { karaokeStyle: 'off' })).toBeNull()
    expect(buildKaraokeSpans({ text: 'plain', words: [] }, 0.1, style)).toBeNull()
    expect(buildKaraokeSpans({ text: 'plain' }, 0.1, style)).toBeNull()
  })

  it('returns null in intra-cue gaps and after the last word so the base-color phrase renders', () => {
    expect(buildKaraokeSpans(cue, 2.0, style)).toBeNull()
    expect(
      buildKaraokeSpans(
        {
          text: 'Hello there',
          words: [
            { text: 'Hello', start: 0, end: 0.4 },
            { text: 'there', start: 0.7, end: 1.0 },
          ],
        },
        0.55,
        style,
      ),
    ).toBeNull()
  })

  it('highlights the active word with the accent color in one inline line', () => {
    const first = buildKaraokeSpans(cue, 0.2, style)
    expect(first).not.toBeNull()
    expect(first!.spanLayout).toBe('inline')
    expect(first!.text).toBe('Hello there world')
    expect(first!.spans.map((span) => span.color)).toEqual(['#ffd400', '#ffffff', '#ffffff'])

    const second = buildKaraokeSpans(cue, 0.6, style)
    expect(second!.spans.map((span) => span.color)).toEqual(['#ffffff', '#ffd400', '#ffffff'])

    const third = buildKaraokeSpans(cue, 1.1, style)
    expect(third!.spans.map((span) => span.color)).toEqual(['#ffffff', '#ffffff', '#ffd400'])
  })

  it('falls back to the default accent when karaokeColor is missing', () => {
    const result = buildKaraokeSpans(cue, 0.2, { karaokeStyle: 'word', color: '#ffffff' })
    expect(result!.spans[0]!.color).toBe('#ffd400')
  })
})