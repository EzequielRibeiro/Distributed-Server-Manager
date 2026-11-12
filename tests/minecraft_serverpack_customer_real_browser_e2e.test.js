'use strict';
// Actual Chromium DOM and cookies against the isolated Python customer HTTP
// gateway and authoritative temporary SQLite read model. Never production.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');

async function main(){
  if(process.env.CAPIVARA_RUN_1013_BROWSER_E2E!=='1'||
     process.env.GITHUB_ACTIONS!=='true'||
     process.env.RUNNER_ENVIRONMENT!=='github-hosted'){
    throw new Error('browser E2E restricted to opted-in GitHub-hosted runner');
  }
  if(fs.existsSync('/opt/dsm/runtime/hybrid-instance-storage')){
    throw new Error('installed DSM detected: forbidden browser E2E');
  }
  const info=JSON.parse(fs.readFileSync(process.env.DSM_1013_BROWSER_READY_FILE,'utf8'));
  const {base_url,instance_id,customer_token,controller_token}=info;
  const positive=info.health_gate==='ready';
  assert.equal(positive,process.env.DSM_1013_BROWSER_HEALTH_READY==='1');
  const url=base_url+'/api/customer/instance/workspace/content?instance_id='+encodeURIComponent(instance_id);
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  try{
    const customer=await browser.newContext({viewport:{width:1320,height:900},locale:'pt-BR'});
    await customer.addCookies([{
      name:'capivara_customer_session',value:customer_token,url:base_url,
      httpOnly:true,sameSite:'Lax',
    }]);
    const data=await customer.request.get(url,{headers:{'X-Capivara-Auth-Area':'customer'}});
    assert.equal(data.status(),200);
    const readModel=await data.json();
    assert.equal(readModel.content.length,1);
    const item=readModel.content[0];
    assert.equal(item.reconciliation.status,'applied');
    assert.equal(item.bundle_summary.child_count,291);
    assert.equal(item.bundle_summary.absent_child_count,201);
    assert.equal(item.bundle_summary.health_gate,positive?'ready':'blocked');
    assert.equal(item.bundle_summary.current_boot_witness,positive?'observed':'missing');
    if(positive){
      assert.equal(item.bundle_summary.current_operational_attestation,'observed');
      assert.equal(item.bundle_summary.runtime_process_observation,'reported_running');
      assert.equal(item.bundle_summary.health_reason,'runtime_functionally_attested');
    }
    const page=await customer.newPage();
    const response=await page.goto(base_url+'/customer-instance.html?instance_id='+encodeURIComponent(instance_id),{
      waitUntil:'domcontentloaded',timeout:25000,
    });
    assert.equal(response.status(),200);
    await page.locator('button[data-view="content"]').click();
    await page.locator('#content-installed .content-item').first().waitFor({timeout:20000});
    const panelText=await page.locator('#content-installed').innerText();
    assert.match(panelText,/291 ativos/);
    assert.match(panelText,/201 removidos/);
    if(positive){
      assert.match(panelText,/Saúde operacional confirmada para a revisão instalada/);
      assert.doesNotMatch(panelText,/Liberação bloqueada/);
    }else{
      assert.match(panelText,/Liberação bloqueada/);
      assert.match(panelText,/inicialização não atestada/);
    }
    assert.match(panelText,/Aplicado: aplicado/);
    assert.doesNotMatch(panelText,/Instalação concluída\./);
    assert.equal(await page.locator('#content-installed button', {hasText:'Reverter'}).count(),0);
    assert.equal(await page.locator('button[data-view="content"]').getAttribute('class'),'active');
    const health=await page.locator('#health').innerText();
    assert.equal(health,positive?'healthy':'degraded');
    if(positive&&process.env.DSM_1013_BROWSER_SCREENSHOT){
      await page.screenshot({
        path:process.env.DSM_1013_BROWSER_SCREENSHOT.replace(/\.png$/, '-ready.png'),
        fullPage:true,
      });
    }
    if(positive){
      // Explicit fixture-only revocation: simulate loss of current runtime
      // health, then confirm the Controller and Chromium fail closed.
      const revoke=await customer.request.post(base_url+'/__dsm_fixture__/revoke',{
        headers:{'X-DSM-Fixture-Control':info.fixture_control_token},
      });
      assert.equal(revoke.status(),200);
      const revoked=await customer.request.get(url,{
        headers:{'X-Capivara-Auth-Area':'customer'},
      });
      assert.equal(revoked.status(),200);
      const after=await revoked.json();
      assert.equal(after.content[0].bundle_summary.health_gate,'blocked');
      assert.equal(after.content[0].bundle_summary.runtime_process_observation,'not_running');
      await page.reload({waitUntil:'domcontentloaded'});
      await page.locator('button[data-view="content"]').click();
      await page.locator('#content-installed .content-item').first().waitFor({timeout:20000});
      const revokedText=await page.locator('#content-installed').innerText();
      assert.match(revokedText,/Liberação bloqueada/);
      assert.doesNotMatch(revokedText,/Saúde operacional confirmada/);
      assert.equal(await page.locator('#health').innerText(),'degraded');
    }
    if(process.env.DSM_1013_BROWSER_SCREENSHOT){
      await page.screenshot({path:process.env.DSM_1013_BROWSER_SCREENSHOT,fullPage:true});
    }
    const anonymous=await browser.newContext();
    const unauthorized=await anonymous.request.get(url,{headers:{'X-Capivara-Auth-Area':'customer'}});
    assert.equal(unauthorized.status(),401);
    await anonymous.close();
    const admin=await browser.newContext();
    await admin.addCookies([{
      name:'capivara_controller_session',value:controller_token,url:base_url,
      httpOnly:true,sameSite:'Lax',
    }]);
    const wrongArea=await admin.request.get(url,{headers:{'X-Capivara-Auth-Area':'customer'}});
    assert.equal(wrongArea.status(),401);
    await admin.close();
    await customer.close();
    console.log('DSM1013_AUTHENTICATED_CHROMIUM_READMODEL_PASS',JSON.stringify({
      browser:'chromium',dom:'real_customer_instance_html_and_js',
      server:'real_http_controller_read_model',session:'actual_customer_cookie',
      anon_rejected:true,controller_cookie_rejected:true,mods:291,
      absent_states:201,health_gate:positive?'ready_then_blocked':'blocked',
      boot_witness:positive?'injected_disposable':'missing',
      status_presented:positive?'ready_then_revoked':'applied_but_not_released',
      evidence_scope:info.evidence_scope,
      production_touched:false,
    }));
  }finally{
    await browser.close();
  }
}
main().catch(e=>{console.error(e);process.exitCode=1});
