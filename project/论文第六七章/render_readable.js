const fs=require('fs');
const path=require('path');
const {pathToFileURL}=require('url');
const {marked}=require('marked');
const {chromium}=require('playwright');
const root=__dirname, base=path.join(root,'第六七章_阅读版');
let source=fs.readFileSync(base+'.md','utf8');
const math=[];
source=source.replace(/\$\$([\s\S]*?)\$\$/g,(_,x)=>{
  const id='MATHDISPLAYTOKEN'+math.length;math.push({id,x,display:true});return '\n<div class="equation">'+id+'</div>\n';});
source=source.replace(/\$((?:\\.|[^$])+)\$/g,(_,x)=>{
  const id='MATHINLINETOKEN'+math.length;math.push({id,x,display:false});return id;});
let body=marked.parse(source);
for(const m of math)body=body.replace(m.id,m.display?'\\['+m.x+'\\]':'\\('+m.x+'\\)');
const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>第六章与第七章：问题一、二建模与求解</title>
<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']]},options:{enableMenu:false},svg:{fontCache:'global'}};</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<style>
@page{size:A4;margin:19mm 20mm 20mm}
body{max-width:170mm;margin:24px auto;padding:20px;background:white;color:#000;font:16px/1.65 'SimSun','STSong','Times New Roman',serif}
h1{font:700 23px/1.4 'SimHei','Microsoft YaHei',sans-serif;margin:0 0 22px;break-before:page}h1:first-child{break-before:auto}
h2{font:700 18px/1.4 'SimHei','Microsoft YaHei',sans-serif;margin:25px 0 10px}p{margin:0 0 10px;text-align:justify;text-indent:2em}
h1,h2{break-after:avoid}p{orphans:3;widows:3}a{color:#000}code{font-family:'Consolas',monospace;font-size:0.92em}
.equation{margin:13px 0;break-inside:avoid;text-indent:0}mjx-container[jax="SVG"][display="true"]{margin:0.7em 0!important}mjx-container svg{max-width:100%}
figure{margin:18px 0 12px;break-inside:avoid}figure img{display:block;width:100%;height:auto}figcaption{font-size:13px;line-height:1.5;text-align:left;margin:7px 0}
table{width:100%;border-collapse:collapse;margin:18px 0;break-inside:avoid;font-size:14px;text-align:center}caption{font-size:14px;margin:0 0 7px}th,td{padding:5px 7px}thead{border-top:1.2px solid black;border-bottom:0.8px solid black}tbody{border-bottom:1.2px solid black}th{font-weight:normal}
.algorithm{border:1px solid black;padding:12px 15px;margin:20px 0;font-size:14px;line-height:1.6;break-inside:avoid}.algtitle{font-weight:bold;font-family:'SimHei','Microsoft YaHei',sans-serif;border-bottom:1px solid black;padding:0 0 7px;margin-bottom:7px;font-size:15px}.algio{margin:2px 0}.algline{display:flex;align-items:baseline;margin:2px 0}.num{flex:0 0 1.7em}.step{flex:1;min-width:0}.algorithm mjx-container{font-size:100%!important}
.references{break-inside:avoid;font-size:12px;line-height:1.35}.references h2{font-size:13px;margin:12px 0 5px}.references p{margin:4px 0;text-indent:0;text-align:left}
@media print{body{max-width:none;margin:0;padding:0;font-size:11pt;line-height:1.58}h1{font-size:16pt}h2{font-size:12pt}table{font-size:9.7pt}figcaption{font-size:9pt}.algorithm{font-size:9.7pt;line-height:1.55}.algtitle{font-size:10.5pt}p{margin-bottom:8px}}
</style></head><body>${body}</body></html>`;
fs.writeFileSync(base+'.html',html,'utf8');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:1400}});
  await page.goto(pathToFileURL(base+'.html').href,{waitUntil:'networkidle',timeout:60000});
  await page.waitForFunction(()=>window.MathJax&&window.MathJax.startup&&window.MathJax.startup.document);
  await page.evaluate(()=>MathJax.startup.promise);
  const check=await page.evaluate(()=>({formulas:document.querySelectorAll('mjx-container').length,
   errors:document.querySelectorAll('[data-mml-node="merror"]').length,
   images:[...document.images].filter(x=>x.complete&&x.naturalWidth).length,
   algorithms:document.querySelectorAll('.algorithm').length,
   headings:[...document.querySelectorAll('h1')].map(x=>x.textContent),
   equationOverflow:[...document.querySelectorAll('.equation')].filter(x=>x.scrollWidth>x.clientWidth+3).length}));
  if(check.errors||check.images!==3||check.algorithms!==2||check.headings.length!==2||check.equationOverflow)throw Error(JSON.stringify(check));
  await page.evaluate(()=>document.querySelectorAll('script').forEach(s=>s.remove()));
  fs.writeFileSync(base+'.html',await page.content(),'utf8');
  await page.pdf({path:base+'.pdf',format:'A4',preferCSSPageSize:true,printBackground:true,displayHeaderFooter:true,
   headerTemplate:'<span></span>',footerTemplate:'<div style="width:100%;text-align:center;font:10px Times New Roman;color:#000">— <span class="pageNumber"></span> —</div>'});
  fs.writeFileSync(path.join(root,'render_check.json'),JSON.stringify(check,null,2)+'\n');
  console.log(JSON.stringify(check));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
