/** The judgments apply only to supplied context and final generation. */
export const axes = ['context_relevance','answer_relevance','faithfulness'];
export const defaults = Object.fromEntries(axes.flatMap(axis=>[[axis,null],[`${axis}_note`,'']]));
export function validateReview(review) {
  return Object.keys(review).length===6 && axes.every(axis=>[null,'pass','fail','defer'].includes(review[axis])&&typeof review[`${axis}_note`]==='string'&&review[`${axis}_note`].length<=20000);
}
export function requiredAxes(c) {
  if(!c)return [];
  return axes.filter(axis=>axis==='context_relevance'?c.output.has_context:axis==='answer_relevance'?c.output.has_generation:c.output.has_context&&c.output.has_generation);
}
export function complete(review,c) {const required=requiredAxes(c);return required.length>0&&required.every(axis=>['pass','fail','defer'].includes(review?.[axis]));}
export function diagnosis(review,c) {
  if(!c.output.has_context)return 'No selected context is available. Context relevance and faithfulness cannot be judged.';
  if(review.context_relevance==='fail')return 'Low context relevance points to evidence selection. Recall separately measures reference coverage.';
  if(review.context_relevance!=='pass')return 'Judge context relevance before diagnosing answer behavior.';
  if(!c.output.has_generation)return 'Context judged; this retrieval-only run has no final generation to diagnose.';
  if(review.faithfulness==='fail')return 'Relevant context was supplied, but the generation contains unsupported claims or misinterpretations.';
  if(review.faithfulness==='pass'&&review.answer_relevance==='fail')return 'The generation is supported by the context but does not address the question. Check its focus.';
  if(review.faithfulness==='pass'&&review.answer_relevance==='pass')return 'Context relevance, answer relevance and faithfulness pass. Coverage remains a separate retrieval measurement.';
  return 'Complete answer relevance and faithfulness to diagnose generation behavior.';
}
