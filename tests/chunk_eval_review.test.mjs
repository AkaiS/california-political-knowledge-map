import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {createReviewEditor} from '../scripts/chat_eval_review_editing.mjs';

test('chunk page saves and advances, preserves descriptions and defer, and recovers labels on reload', async()=>{
 const page=readFileSync(new URL('../scripts/chunk_eval_review.html',import.meta.url),'utf8');
 const script=page.match(/<script type="module">([\s\S]*?)<\/script>/)[1].replace(/^import .*;$/gm,'');
 const reviews={}, stored=new Map(), writes=[];
 const cases=Array.from({length:3},(_,i)=>({name:`pair-${i}`,inputs:{question:`Question ${i}?`},output:{text:`Exact chunk ${i} <script>unsafe</script>`}}));
 const report={review_identity:'sample-identity',report:{cases}};
 const tick=()=>new Promise(resolve=>setImmediate(resolve));
 function load(){
  const elements=new Map(),listeners={};
  function get(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',disabled:false,hidden:false,tagName:'DIV',classList:{toggle(){},add(){}},setAttribute(k,v){this[k]=v;},click(){if(!this.disabled)return this.onclick?.({preventDefault(){}});}});return elements.get(id);}
  get('filter').value='all';
  const document={getElementById:get,activeElement:{tagName:'BODY'},createElement:()=>({click(){}})};
  runInNewContext(script,{createReviewEditor,document,location:{pathname:'/chunks/sample'},window:{scrollTo(){},addEventListener:(k,f)=>{listeners[k]=f;}},URL,setTimeout:(...a)=>setTimeout(...a),clearTimeout:(...a)=>clearTimeout(...a),localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},fetch:async(url,options)=>{if(options){const p=JSON.parse(options.body);writes.push(p);reviews[p.name]=p.review;return {ok:true};}return {ok:true,json:async()=>url.endsWith('/report')?report:reviews};}});
  return {get,document,key:key=>listeners.keydown({key,preventDefault(){}})};
 }
 let ui=load();await tick();
 assert.equal(ui.get('question').textContent,'Question 0?');
 assert.equal(ui.get('chunk').textContent,cases[0].output.text);
 await ui.get('high').click();assert.equal(ui.get('position').textContent,'Item 2 of 3');
 assert.deepEqual(reviews['pair-0'],{verdict:'pass',note:''});
 ui.key('d');await tick();assert.equal(reviews['pair-1'].verdict,'defer');
 assert.equal(ui.get('position').textContent,'Item 3 of 3');
 ui.get('note').value='Wrong relationship';ui.get('note').oninput();
 ui.document.activeElement={tagName:'TEXTAREA'};ui.key('1');await tick();assert.equal(reviews['pair-2'],undefined);
 ui.document.activeElement={tagName:'BODY'};await ui.get('low').click();
 assert.deepEqual(reviews['pair-2'],{verdict:'fail',note:'Wrong relationship'});
 assert.match(ui.get('progress').textContent,/2 labeled · 1 deferred · 0 unmarked/);
 ui=load();await tick();assert.equal(ui.get('high')['aria-pressed'],'true');
 ui.get('filter').value='defer';ui.get('filter').onchange();await tick();
 assert.equal(ui.get('question').textContent,'Question 1?');assert.equal(ui.get('defer')['aria-pressed'],'true');
 ui.get('filter').value='all';ui.get('filter').onchange();await tick();
 ui.key('ArrowRight');await tick();ui.key('ArrowRight');await tick();
 assert.equal(ui.get('note').value,'Wrong relationship');
 await ui.get('high').click();ui.key('u');await tick();
 assert.equal(reviews['pair-2'].verdict,'fail');
 assert.ok(writes.every(p=>p.review_identity==='sample-identity'));
 assert.ok([...stored.keys()].every(k=>k.startsWith('chunk-review-drafts:')));
});

test('chunk page presents no rank, reference labels, answer or retrieval dashboards',()=>{
 const page=readFileSync(new URL('../scripts/chunk_eval_review.html',import.meta.url),'utf8');
 assert.doesNotMatch(page,/innerHTML|\.metadata|Precision|Faithfulness|Final generation/);
 for(const id of ['high','low','defer','question','chunk','note','undo'])assert.ok(page.includes(`id="${id}"`));
});
