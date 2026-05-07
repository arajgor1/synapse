/**
 * synapse.beliefs — semantic-conflict detection that scope-overlap can't catch.
 *
 * Two agents can disagree about a domain fact without ever touching the same
 * file. The beliefs module catches that case via BELIEF emissions +
 * per-emission divergence detection.
 */
export {
  type AgentBelief,
  type BeliefDivergence,
  type BeliefSource,
  beliefsFromDbRows,
  detectDivergences,
  evidentialWeight,
  valuesEqual,
} from "./divergence.js";

export {
  type ExtractBeliefsArgs,
  type FactExtraction,
  extractBeliefsWithLLM,
  parseExtraction,
} from "./extractor.js";

export {
  type DetectLiveDivergenceArgs,
  type LiveDivergenceResult,
  buildRationale,
  detectLiveDivergence,
  makeLiveDivergenceResult,
} from "./liveDetector.js";

export {
  type EmitBeliefArgs,
  divergencesForKey,
  emitBelief,
  listDivergences,
} from "./api.js";
