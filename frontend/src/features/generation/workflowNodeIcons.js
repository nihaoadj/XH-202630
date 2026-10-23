// Fixed, shared node glyphs; unknown nodes remain passive in the graph.
const NODE_ICON_PATHS = Object.freeze({
  diagnose: ['M12 3a9 9 0 1 0 9 9', 'M12 7a5 5 0 1 0 5 5', 'M12 3v9l7-7', 'M12 11v2M11 12h2'],
  retrieve: ['M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Z', 'm15.5 15.5 5 5', 'M7.5 9h6M7.5 12h4'],
  evidence_gate: ['M12 3 20 6v6c0 4.5-4.5 7.5-8 9-3.5-1.5-8-4.5-8-9V6Z', 'm8 12 3 3 5-6'],
  plan: ['M5 5h14M5 12h7M12 12v7h7', 'M4 3v4M18 3v4M4 10v4M18 17v4'],
  generate: ['m12 3 9 5-9 5-9-5Z', 'm3 12 9 5 9-5M3 16l9 5 9-5'],
  review: ['M9 5h11M9 12h11M9 19h11', 'm3 5 1.5 1.5L7 3M3 12l1.5 1.5L7 10M3 19l1.5 1.5L7 17'],
  claim_extract: ['M5 5h14M5 19h14', 'M5 9v4h4c0 2-1 3-3 3M15 9v4h4c0 2-1 3-3 3'],
  claim_judge: ['M12 3v17M7 21h10M4 7h16', 'm5 7-3 7h6ZM19 7l-3 7h6Z', 'M2 14a3 3 0 0 0 6 0M16 14a3 3 0 0 0 6 0'],
  prepare_revision: ['M3 10a9 9 0 1 1 2.5 8.5', 'M3 4v6h6'],
  prepare_claim_revision: ['M13 3H5v18h14v-6', 'm11 13 8-8 3 3-8 8-4 1Z', 'm17 7 3 3'],
  finalize_draft: ['M14 3H5v18h14V8Z', 'M14 3v5h5', 'M8 12h8M8 16h5'],
  claim_decide: ['m12 3 5 5-5 5-5-5Z', 'M12 13v3M5 21v-5h14v5', 'm3 19 2 2 2-2M17 19l2 2 2-2'],
  finalize: ['M5 21V3', 'M5 4h14l-3 4 3 4H5', 'M3 21h5'],
  finalize_evidence_insufficient: ['m12 3 10 18H2Z', 'M12 9v5M12 17v.1'],
})
const UNKNOWN_ICON_PATHS = Object.freeze(['M7 7h10v10H7ZM12 4v3M12 17v3M4 12h3M17 12h3'])

export function iconPaths(key) {
  return Object.hasOwn(NODE_ICON_PATHS, key) ? NODE_ICON_PATHS[key] : UNKNOWN_ICON_PATHS
}
