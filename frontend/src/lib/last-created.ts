// Tiny module-level signal so /report/new can hand off the freshly-created
// report to the map screen. The map will:
//   1) optimistically insert it into state so it appears INSTANTLY,
//   2) reset its filter to "all" if the type doesn't match the active one,
//   3) refetch + fly to the marker.
//
// Carrying the full ReportItem (not just the type) is what guarantees an
// instant on-screen marker — no race against the next /api/reports fetch.
import type { ReportItem } from "@/src/api/client";

let lastCreated: ReportItem | null = null;

export function markReportCreated(r: ReportItem) {
  lastCreated = r;
}

/** Returns the last-created report (if any) and clears the signal. */
export function consumeLastCreated(): ReportItem | null {
  const v = lastCreated;
  lastCreated = null;
  return v;
}
