// Shared by the existing city renderer and the bounded handoff exporter.
// Values are the original Qinglan campus geometry, in local ENU metres.
export const CAMPUS_BUILDINGS = Object.freeze([
  [-10,75,68,36,22],[-88,85,48,30,16],[70,78,50,30,18],
  [70,125,44,24,12],[-80,130,52,26,14],[0,128,42,22,12],
  [-142,24,72,42,16],[-142,74,72,34,13],[42,-82,58,38,14],
  [126,-87,62,42,12],[156,15,44,28,10],
].map((dimensions, index) => Object.freeze({ id: `qinglan-campus-building-${String(index+1).padStart(2,"0")}`, dimensions: Object.freeze(dimensions) })));

export const CAMPUS_ROADS = Object.freeze([
  { id: "qinglan-campus-road-ew", x: 0, y: -25, width: 405, depth: 14 },
  { id: "qinglan-campus-runway", x: 0, y: -145, width: 294, depth: 19 },
  { id: "qinglan-campus-road-ns", x: 112, y: 12, width: 12, depth: 265 },
]);
