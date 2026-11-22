import { useEffect, useRef, useState } from 'react';
import type { Ref } from 'react';

/**
 * Reveal a long list in chunks as the reader scrolls to the bottom.
 *
 * The Health page lists every problem, not a top-N sample, so the payload can
 * be thousands of rows. Painting all of them at once is what made the page
 * stutter; chunking keeps the DOM small while nothing is hidden by a cap.
 * The chunk count never resets on a poll: shrinking rows shrink the visible
 * slice naturally, growing ones extend it when the sentinel comes back into
 * view, so a 60s refresh does not yank the scroll position back to the top.
 */
export function useInfiniteChunk<T>(
  rows: T[],
  chunk = 100,
): { visible: T[]; hasMore: boolean; sentinelRef: Ref<HTMLTableRowElement> } {
  const [shown, setShown] = useState(chunk);
  const sentinelRef = useRef<HTMLTableRowElement>(null);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting) setShown(n => n + chunk);
      },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [shown, chunk]);

  return { visible: rows.slice(0, shown), hasMore: shown < rows.length, sentinelRef };
}
