/** The judgments apply only to supplied context and final generation. */
export const axes = ['context_relevance','answer_relevance','faithfulness'];
export const defaults = {...Object.fromEntries(axes.flatMap(axis=>[[axis,null],[`${axis}_note`,'']])),execution_note:''};
export function validateReview(review) {
  // Existing uncertain labels remain readable; new judgments use High/Low.
  const fields=axes.flatMap(axis=>[axis,`${axis}_note`]);
  return Object.keys(review).every(key=>fields.includes(key)||key==='execution_note') && axes.every(axis=>[null,'pass','fail','defer'].includes(review[axis])&&typeof review[`${axis}_note`]==='string'&&review[`${axis}_note`].length<=20000) && (review.execution_note===undefined||typeof review.execution_note==='string'&&review.execution_note.length<=20000);
}
export function requiredAxes(c) {
  if(!c)return [];
  return axes.filter(axis=>axis==='context_relevance'?c.output.has_context:axis==='answer_relevance'?c.output.has_generation:c.output.has_context&&c.output.has_generation);
}
export function complete(review,c) {const required=requiredAxes(c);return required.length>0?required.every(axis=>['pass','fail'].includes(review?.[axis])):Boolean(review?.execution_note?.trim());}
export function diagnosis(review,c) {
  if(!requiredAxes(c).length)return 'Inspect the execution outcome and record an execution note. Relevance and faithfulness require evidence or an answer.';
  const findings=[];
  if(review.context_relevance==='fail')findings.push('Low context relevance points to evidence selection. Recall separately measures reference coverage.');
  if(c.output.has_context&&c.output.has_generation&&review.faithfulness==='fail')findings.push('Low faithfulness indicates unsupported claims or misinterpretations in the generation.');
  if(c.output.has_generation&&review.answer_relevance==='fail')findings.push(review.faithfulness==='pass'?'The generation is supported by the context but does not address the question. Check its focus.':'Low answer relevance points to the generation’s focus on the approved question.');
  if(findings.length)return findings.join(' ');
  if(complete(review,c))return 'All available categories are High. Coverage remains a separate retrieval measurement.';
  return 'Judge each category independently. A description can identify the passage or claim behind a High or Low rating.';
}
