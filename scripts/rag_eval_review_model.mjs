/** The judgments apply only to supplied context and final generation. */
export const axes = ['context_relevance','answer_relevance','faithfulness'];
export const defaults = Object.fromEntries(axes.flatMap(axis=>[[axis,null],[`${axis}_note`,'']]));
export function validateReview(review) {
  // Existing uncertain labels remain readable; new judgments use High/Low.
  return Object.keys(review).length===6 && axes.every(axis=>[null,'pass','fail','defer'].includes(review[axis])&&typeof review[`${axis}_note`]==='string'&&review[`${axis}_note`].length<=20000);
}
export function requiredAxes(c) {
  if(!c)return [];
  return axes.filter(axis=>axis==='context_relevance'?c.output.has_context:axis==='answer_relevance'?c.output.has_generation:c.output.has_context&&c.output.has_generation);
}
export function complete(review,c) {const required=requiredAxes(c);return required.length>0&&required.every(axis=>['pass','fail'].includes(review?.[axis]));}
export function diagnosis(review,c) {
  const findings=[];
  if(review.context_relevance==='fail')findings.push('Low context relevance points to evidence selection. Recall separately measures reference coverage.');
  if(c.output.has_context&&c.output.has_generation&&review.faithfulness==='fail')findings.push('Low faithfulness indicates unsupported claims or misinterpretations in the generation.');
  if(c.output.has_generation&&review.answer_relevance==='fail')findings.push(review.faithfulness==='pass'?'The generation is supported by the context but does not address the question. Check its focus.':'Low answer relevance points to the generation’s focus on the approved question.');
  if(findings.length)return findings.join(' ');
  if(complete(review,c))return 'All available categories are High. Coverage remains a separate retrieval measurement.';
  return 'Judge each category independently. A description can identify the passage or claim behind a High or Low rating.';
}
