import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createReviewEditor} from '../scripts/chat_eval_review_editing.mjs';
import {defaults,validateReview,requiredAxes,complete,diagnosis} from '../scripts/rag_eval_review_model.mjs';

const both={output:{has_context:true,has_generation:true}};
test('RAG axes separate context, answer relevance and faithfulness with scoped diagnosis',()=>{
 assert.deepEqual(requiredAxes(both),['context_relevance','answer_relevance','faithfulness']);
 assert.deepEqual(requiredAxes({output:{has_context:true,has_generation:false}}),['context_relevance']);
 assert.equal(complete({...defaults,context_relevance:'pass'},{output:{has_context:true,has_generation:false}}),true);
 assert.equal(complete(defaults,{output:{has_context:false,has_generation:false}}),false);
 assert.equal(complete({...defaults,context_relevance:'defer'},{output:{has_context:true,has_generation:false}}),false);
 assert.match(diagnosis({...defaults,faithfulness:'fail'},both),/unsupported/);
 assert.match(diagnosis({...defaults,answer_relevance:'fail'},both),/focus/);
 assert.doesNotMatch(diagnosis(defaults,both),/before/);
 assert.match(diagnosis({...defaults,context_relevance:'fail'},both),/evidence selection/);
 assert.match(diagnosis({...defaults,context_relevance:'pass',faithfulness:'fail'},both),/unsupported/);
 assert.match(diagnosis({...defaults,context_relevance:'pass',faithfulness:'pass',answer_relevance:'fail'},both),/does not address/);
});
test('independent RAG labels and evidence survive autosave, undo, reload and navigation',async()=>{
 const stored=new Map(),writes=[];
 const options={caseNames:['a','b'],reviews:{},runId:'run',reviewIdentity:'identity',reviewDefaults:defaults,validateReview,draftNamespace:'rag-review-drafts',storage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},scheduler:{setTimeout:()=>1,clearTimeout:()=>{}},persistReview:async p=>writes.push(p)};
 let editor=createReviewEditor(options);
 await editor.setField('context_relevance','pass');
 editor.editField('context_relevance_note','Exact selected passage');
 await editor.setField('answer_relevance','fail');
 await editor.setField('faithfulness','pass');
 assert.equal(writes.at(-1).review.context_relevance_note,'Exact selected passage');
 assert.equal(writes.at(-1).review.context_relevance,'pass');
 assert.equal(writes.at(-1).review.answer_relevance,'fail');
 await editor.undo();
 assert.equal(editor.state.reviews.a.faithfulness,null);
 editor.editField('faithfulness_note','Citation does not support claim');
 assert.equal(stored.has('rag-review-drafts:run:identity'),true);
 assert.equal(stored.has('chat-review-drafts:run:identity'),false);
 editor=createReviewEditor(options);
 await editor.flush();
 assert.equal(editor.state.reviews.a.faithfulness_note,'Citation does not support claim');
 await editor.navigate(1,()=>['a','b']);
 assert.equal(editor.state.selectedCase,'b');
 assert.equal(editor.state.reviews.a.answer_relevance,'fail');
 await editor.setField('unknown','fail');
 assert.equal(Object.hasOwn(editor.state.reviews.b,'unknown'),false);
});

test('focused page loads specs, preserves independent judgments and disables absent generation',async()=>{
 const {readFileSync}=await import('node:fs');const {runInNewContext}=await import('node:vm');
 const elements=new Map(),all=[],requests=[],writes=[],stored=new Map();
 function element(tag='div'){const el={tagName:tag.toUpperCase(),dataset:{},value:'',textContent:'',children:[],disabled:false,hidden:false,classList:{toggle(){},add(){}},append(child){this.children.push(child);},replaceChildren(...children){this.children=children;},setAttribute(key,value){this[key]=value;},click(){if(!this.disabled)this.onclick?.({preventDefault(){}});}};Object.defineProperty(el,'id',{set(value){elements.set(value,el);},get(){return [...elements].find(([,node])=>node===el)?.[0];}});all.push(el);return el;}
 function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
 get('filter').value='all';get('branch').value='fused';
 // Window timers reject a foreign receiver; Node's timers silently accept it.
 function browserSetTimeout(...args){assert.equal(this,undefined,'Illegal invocation: setTimeout receiver');return setTimeout(...args);}
 function browserClearTimeout(...args){assert.equal(this,undefined,'Illegal invocation: clearTimeout receiver');return clearTimeout(...args);}
 const document={getElementById:get,createElement:element,activeElement:element('body'),addEventListener(){},querySelector:()=>get('main'),querySelectorAll:selector=>all.filter(el=>el.dataset.axis===selector.match(/data-axis="(\w+)"/)?.[1]&&Object.hasOwn(el.dataset,'value'))};
 const page=readFileSync(new URL('../scripts/rag_eval_review.html',import.meta.url),'utf8');const script=page.match(/<script type="module">([\s\S]*?)<\/script>/)[1].replace(/^import .*;$/gm,'');
 runInNewContext(script,{createReviewEditor,axes:Object.keys(defaults).filter(k=>!k.endsWith('_note')),defaults,validateReview,requiredAxes,complete,diagnosis,document,location:{pathname:'/runs/chat--run'},window:{addEventListener(){}},URL,setTimeout:browserSetTimeout,clearTimeout:browserClearTimeout,localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},fetch:(url,options)=>options?(writes.push(JSON.parse(options.body)),Promise.resolve({ok:true})):new Promise(resolve=>requests.push({url,resolve}))});
 get('search').oninput();get('filter').onchange();
 const c={name:'case-a',question:'Approved question',metrics:[],output:{...both.output,sources:[{citation:{title:'Source',url:'https://example.org'},passages:[{chunk_id:'a',text:'Exact context'}]}],semantic_context:[{branch:'structural',semantic_results:[{fact:'Selected graph fact',evidence_chunk_ids:['a']}]}],generation:'Final'}};
 const run={task:'chat',review_identity:'identity',model:'model',metrics:[],specs:{dataset:'dataset',label_quality:'silver',configurations:[],definitions:{}},report:{cases:[c,{...c,name:'case-b',output:{...c.output,has_generation:false,generation:null}}]}};
 for(const r of requests)r.resolve({ok:true,json:async()=>r.url.endsWith('/report')?run:r.url.endsWith('/presentation')?{html:{Final:'<p>Final</p>'}}:{}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('question').textContent,'Approved question');assert.equal(get('loading').hidden,true);assert.equal(get('answer').innerHTML,'<p>Final</p>');
 assert.ok(all.some(el=>el.tagName==='PRE'&&el.textContent.includes('Selected graph fact')));
 const button=(axis,value)=>all.find(el=>el.dataset.axis===axis&&el.dataset.value===value);
 const secondCase=get('case-list').children[1];
 assert.equal(button('answer_relevance','pass').disabled,false);
 assert.equal(button('faithfulness','fail').disabled,false);
 assert.equal(button('answer_relevance','pass').textContent,'High');
 assert.equal(button('faithfulness','fail').textContent,'Low');
 assert.equal(button('faithfulness','defer'),undefined);
 // An answer can be graded first, without selecting context relevance.
 button('answer_relevance','pass').click();button('faithfulness','fail').click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(writes.at(-1).review.context_relevance,null);
 assert.match(get('diagnosis').textContent,/unsupported/);
 secondCase.click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('position').textContent.includes('case-b'),true);
 assert.equal(get('progress').textContent.includes('0 reviewed'),true);
 get('case-list').children[0].click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('position').textContent.includes('case-a'),true);
 button('context_relevance','pass').click();
 assert.equal(get('case-list').children[1],secondCase);
 get('note-faithfulness').value='Unsupported claim';get('note-faithfulness').oninput();secondCase.click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(writes.at(-1).review.context_relevance,'pass');assert.equal(writes.at(-1).review.faithfulness,'fail');assert.equal(writes.at(-1).review.faithfulness_note,'Unsupported claim');
 assert.equal(get('position').textContent.includes('case-b'),true);assert.equal(button('faithfulness','pass').disabled,true);assert.equal(button('answer_relevance','pass').disabled,true);assert.equal(button('context_relevance','pass').disabled,false);
 assert.equal(get('progress').textContent.includes('1 reviewed'),true);
 get('case-list').children[0].click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('position').textContent.includes('case-a'),true);
 assert.equal(get('note-faithfulness').value,'Unsupported claim');
 get('next').click();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('position').textContent.includes('case-b'),true);
});

test('sidebar and article have separate scrolling and run metrics can collapse',async()=>{
 const {readFileSync}=await import('node:fs');
 const page=readFileSync(new URL('../scripts/rag_eval_review.html',import.meta.url),'utf8');
 assert.match(page, /\.layout\{[^}]*height:100dvh;overflow:hidden/);
 assert.match(page, /#case-list\{[^}]*overflow-y:auto;min-height:0;flex:1/);
 assert.match(page, /main\{[^}]*overflow-y:auto/);
 assert.match(page, /<details class="panel" id="run-summary" open><summary>/);
 assert.match(page, /Choose High or Low for each category independently/);
});
