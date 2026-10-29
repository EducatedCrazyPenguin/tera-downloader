// Private pipe worker. Never write browser errors, API bodies or signed URLs to logs.
'use strict';
const path = require('node:path');
const readline = require('node:readline');
// Keep all owned helper consoles hidden, including Playwright cleanup children.
const childProcess = require('node:child_process');
const spawn = childProcess.spawn;
childProcess.spawn = (command,args,options) => spawn(command,args,{...options,windowsHide:true});
const SITE = 'https://teradownloader.com';
const MEDIA = 'play.terafile.workers.dev';
let context, page, origin, setup, activeId, closing = false;
let sources = new Set(), pending = 0, fatal = null, verificationFailed = false;
const write = value => process.stdout.write(JSON.stringify(value)+'\n');
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));

function supported(value) {
  try {
    if (typeof value!=='string' || value.length>32768 || /[\x00-\x1f]/.test(value)) return null;
    const u = new URL(value, SITE);
    if (u.protocol!=='https:' || u.username || u.password || u.hash || u.port) return null;
    if (u.hostname===MEDIA) return u.href;
    if (u.hostname!=='teradownloader.com' || u.pathname!=='/player' || u.searchParams.getAll('url').length!==1 || u.searchParams.getAll('filename').length>1) return null;
    const inner = new URL(decodeURIComponent(u.searchParams.get('url')));
    if (inner.protocol==='https:' && inner.hostname===MEDIA && !inner.username && !inner.password && !inner.port && !inner.hash) return u.href;
  } catch {}
  return null;
}
function capture(value) {
  const source = supported(value);
  if (source) {
    if (sources.size>=100 && !sources.has(source)) fatal='too_many';
    else sources.add(source);
  }
  return !!source;
}
async function close() {
  if (closing) return;
  closing=true;
  const forced=setTimeout(()=>process.exit(2),4500);
  try { await context?.close(); } catch {}
  clearTimeout(forced); process.exit(0);
}
async function init(command) {
  origin=command.origin; setup=command.setup;
  const parsed = new URL(origin);
  if (origin!==SITE && !(parsed.protocol==='http:' && parsed.hostname==='127.0.0.1' && parsed.port && parsed.origin===origin)) throw Error('startup');
  const {firefox} = require(path.join(command.runtime,'playwright-core'));
  const config=JSON.stringify({addons:[path.join(command.runtime,'addons','ublock')],timezone:'Asia/Kolkata'});
  const env={...process.env,DEBUG:'',PWDEBUG:'0'};
  for(let i=0;i<config.length;i+=2047) env['CAMOU_CONFIG_'+(Math.floor(i/2047)+1)]=config.slice(i,i+2047);
  const prefs={'browser.safebrowsing.blockedURIs.enabled':true,'browser.safebrowsing.downloads.enabled':true,
    'browser.safebrowsing.malware.enabled':true,'browser.safebrowsing.phishing.enabled':true,
    'extensions.blocklist.enabled':true,'extensions.autoDisableScopes':15,
    'xpinstall.signatures.required':true,'extensions.langpacks.signatures.required':true,
    'services.settings.server':'https://firefox.settings.services.mozilla.com/v2',
    'browser.safebrowsing.provider.mozilla.updateURL':'moz-sbrs:://antitracking'};
  env.CAMOU_PREFS_1=JSON.stringify(prefs);
  context=await firefox.launchPersistentContext(command.profile,{
    executablePath:path.join(command.runtime,'native','camoufox.exe'),headless:command.headless,
    viewport:{width:1280,height:720},acceptDownloads:false,ignoreHTTPSErrors:false,
    env,firefoxUserPrefs:prefs,timeout:18000,
  });
  context.on('close',()=>{if(!closing)process.exit(0);});
  if(!setup) await context.route('**/*',async route=>{
    const request=route.request();
    let url;try{url=new URL(request.url());}catch{return route.abort();}
    const found=capture(url.href);
    if(found || url.hostname===MEDIA || request.resourceType()==='media' || /\.(m3u8|mp4|mkv|ts|vdo)$/i.test(url.pathname)) return route.abort();
    if(!['https:','http:'].includes(url.protocol) || url.username || url.password) return route.abort();
    if(url.origin!==origin && url.protocol!=='https:') return route.abort();
    if(request.isNavigationRequest() && url.origin!==origin && url.origin!=='https://challenges.cloudflare.com') return route.abort();
    return route.continue();
  });
  page=context.pages().find(p=>p.url()==='about:blank') || await context.newPage();
  context.on('page',p=>{
    p.on('download',d=>d.cancel());
    // Popup navigation is blocked; context shutdown closes every owned tab together.
  });
  page.on('download',d=>d.cancel());
  page.on('pageerror',()=>{fatal='page_script';});
  page.on('console',message=>{if(/\[Cloudflare Turnstile\]\s*Error:\s*\d{6}(?!\d)/.test(message.text()))verificationFailed=true;});
  page.on('response',async response=>{
    if(setup || !activeId)return;
    const u=new URL(response.url());
    if(u.origin!==origin || u.pathname!=='/api/generate')return;
    pending++;
    try{
      const length=Number(response.headers()['content-length']);
      if(length>1048576)return;
      const body=await response.body();
      if(body.length>1048576)return;
      const data=JSON.parse(body.toString('utf8'));
      if(typeof data.dlink==='string')capture(data.dlink);
    }catch{}finally{pending--;}
  });
  return {version:context.browser().version()};
}
async function resolve(command) {
  sources=new Set();pending=0;fatal=null;verificationFailed=false;
  const limit=Date.now()+command.seconds*1000;
  try{await page.goto(origin+'/download?'+new URLSearchParams({l:command.share}),{waitUntil:'domcontentloaded',timeout:Math.min(60000,command.seconds*1000)});}
  catch{throw Error('navigation');}
  let quiet=null, nextStatus=0, waiting=null;
  while(Date.now()<limit){
    if(fatal)throw Error(fatal);
    const buttons=page.getByRole('button',{name:'Watch Online',exact:true});
    let remaining=0;
    if(waiting!==null && sources.size>waiting)waiting=null;
    if(waiting===null)for(const button of await buttons.all()){
      if(await button.evaluate(el=>el.dataset.teraWatched==='1').catch(()=>true))continue;
      remaining++;
      if(await button.isVisible().catch(()=>false)){
        await button.evaluate(el=>{el.dataset.teraWatched='1';});
        waiting=sources.size;
        try{await button.click({timeout:1200});remaining--;}
        catch{waiting=null;await button.evaluate(el=>{delete el.dataset.teraWatched;}).catch(()=>{});}
        break;
      }
    }
    // Recount after each ordinary click; another row can change its button label.
    remaining=0;
    for(const button of await page.getByRole('button',{name:'Watch Online',exact:true}).all()){
      if(!await button.evaluate(el=>el.dataset.teraWatched==='1').catch(()=>true))remaining++;
    }
    const closeButton=page.getByRole('button',{name:'Close',exact:true}).first();
    if(await closeButton.isVisible().catch(()=>false))await closeButton.click({timeout:800}).catch(()=>{});
    if(waiting!==null && sources.size>waiting)waiting=null;
    if(sources.size && remaining===0 && pending===0 && waiting===null){
      quiet??=Date.now();if(Date.now()-quiet>=800)return [...sources];
    }else quiet=null;
    if(Date.now()>nextStatus){write({id:command.id,event:'challenge'});nextStatus=Date.now()+5000;}
    await delay(200);
  }
  throw Error(verificationFailed?'verification':'timeout');
}
async function execute(command){
  activeId=command.id;
  try{
    let result;
    if(command.op==='init')result=await init(command);
    else if(command.op==='resolve' && !setup)result=await resolve(command);
    else if(command.op==='navigate') {await page.goto(command.url,{waitUntil:'domcontentloaded',timeout:10000});result=true;}
    else if(command.op==='evaluate')result=await page.evaluate(command.expression);
    else throw Error('protocol');
    write({id:command.id,result});
  }catch(error){
    const allowed=['timeout','navigation','too_many','protocol','verification'];
    write({id:command.id,error:command.op==='init'?'startup':allowed.includes(error.message)?error.message:'helper'});
  }finally{activeId=null;}
}
let chain=Promise.resolve();
const input=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',line=>{
  if(line.length>1048576)return close();
  let command;try{command=JSON.parse(line);}catch{return close();}
  if(command.op==='close')return close();
  chain=chain.then(()=>execute(command)).catch(()=>close());
});
input.on('close',close);
process.on('uncaughtException',()=>close());
process.on('unhandledRejection',()=>close());
// Parent job cancellation is authoritative; this watchdog also bounds abandoned workers.
setTimeout(close,15*60*1000).unref();
