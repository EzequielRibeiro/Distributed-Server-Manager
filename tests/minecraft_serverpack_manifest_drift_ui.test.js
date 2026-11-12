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
const installed={content_type:'modpack',content_id:'atm11',reconciliation:{status:'applied'},effective_security_state:'clean',
  bundle_summary:{child_count:1,reconciliation_statuses:{applied:1},manifest_alignment:'metadata_aligned'}};
assert.equal(check(installed).message,'Instalação concluída.');
const blockedBoot={...installed,bundle_summary:{...installed.bundle_summary,
  health_gate:'blocked',health_reason:'runtime_boot_not_attested',
  physical_attestation:'verified',convergence_status:'pending'}};
const guarded=check(blockedBoot);
assert.match(guarded.message,/Arquivos aplicados.*Liberação bloqueada/);
assert.equal(guarded.lock.contentId,'atm11');
const contradictory={...blockedBoot,bundle_summary:{...blockedBoot.bundle_summary,convergence_status:'ready'}};
const guardedReady=check(contradictory);
assert.match(guardedReady.message,/Liberação bloqueada/);
assert.equal(guardedReady.lock.contentId,'atm11');
assert.equal(check({...blockedBoot,bundle_summary:{...blockedBoot.bundle_summary,health_gate:'ready',convergence_status:'ready'}}).message,'Instalação concluída.');
assert.match(source,/\.zip ou \.mrpack/);
const drift={...installed,bundle_summary:{...installed.bundle_summary,manifest_alignment:'drift'}};
const observed=check(drift);
assert.equal(observed.failed,true);
assert.equal(observed.message,'Instalação não concluída. Verifique Conteúdo gerenciado e tente novamente.');
assert.equal(observed.lock,null);
const pending={...installed,bundle_summary:{child_count:1,reconciliation_statuses:{pending:1},manifest_alignment:'metadata_aligned'}};
assert.equal(check(pending).message,'');
assert.match(source,/Manifesto divergente/);
const evidenceSource=source.match(/function serverpackEvidenceLabel\([\s\S]*?\n}\n/);
assert.ok(evidenceSource,'serverpackEvidenceLabel missing');
const evidenceCtx={};
vm.runInNewContext(evidenceSource[0],evidenceCtx);
const blocked={health_gate:'blocked',current_physical_observation:'verified',current_boot_witness:'observed'};
assert.match(evidenceCtx.serverpackEvidenceLabel(blocked),/Liberação bloqueada/);
assert.match(evidenceCtx.serverpackEvidenceLabel(blocked),/consultiva/);
assert.match(evidenceCtx.serverpackEvidenceLabel({health_gate:'blocked',current_boot_witness:'missing'}),/inicialização não atestada/);
assert.match(evidenceCtx.serverpackEvidenceLabel({...blocked,health_gate:'ready'}),/Saúde operacional confirmada/);
assert.match(evidenceCtx.serverpackEvidenceLabel({...blocked,health_reason:'activation_hold_active'}),/hold operacional ativo/);
console.log('Server Pack manifest drift, health gate and completion-label UI checks passed');