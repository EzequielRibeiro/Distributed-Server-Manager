'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../dashboard/web/customer-instance-v2.js'),'utf8');
const names=['contentBundlePending','contentBundleFailed','checkContentInstallCompletion'];
const functions=names.map(name=>{
  const pattern=new RegExp(`^function ${name}\\([^\\n]*$`,'m');
  const match=source.match(pattern);
  assert.ok(match,`${name} missing`);
  return match[0];
}).join('\n');
function check(item){
  const feedback={textContent:''};
  const ctx={contentInstallLock:{contentId:'atm11',stage:'processing'},
    contentReconcileState:x=>x.reconciliation.status,
    contentSecurityState:x=>x.effective_security_state,
    $:()=>({querySelector:()=>feedback}),syncContentInstallLock:()=>{}};
  vm.runInNewContext(functions,ctx);
  ctx.checkContentInstallCompletion([item]);
  return {message:feedback.textContent,lock:ctx.contentInstallLock,failed:ctx.contentBundleFailed(item)};
}
const installed={content_id:'atm11',reconciliation:{status:'applied'},effective_security_state:'clean',
  bundle_summary:{child_count:1,reconciliation_statuses:{applied:1},manifest_alignment:'metadata_aligned'}};
assert.equal(check(installed).message,'Instalação concluída.');
const drift={...installed,bundle_summary:{...installed.bundle_summary,manifest_alignment:'drift'}};
const observed=check(drift);
assert.equal(observed.failed,true);
assert.equal(observed.message,'Instalação não concluída. Verifique Conteúdo gerenciado e tente novamente.');
assert.equal(observed.lock,null);
const pending={...installed,bundle_summary:{child_count:1,reconciliation_statuses:{pending:1},manifest_alignment:'metadata_aligned'}};
assert.equal(check(pending).message,'');
assert.match(source,/Manifesto divergente/);
console.log('Server Pack manifest drift UI: 4 assertions passed');