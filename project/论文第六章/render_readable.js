// Render the readable Markdown with MathJax; export a print-layout PDF.
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { marked } = require("marked");
const { chromium } = require("playwright");

const root = __dirname;
const source = path.join(root, "第六章_直观阅读版.md");
const htmlFile = path.join(root, "第六章_直观阅读版.html");
const pdfFile = path.join(root, "第六章_直观阅读版.pdf");
const formulas = [];
let markdown = fs.readFileSync(source, "utf8");
markdown = markdown.replace(/\$\$([\s\S]*?)\$\$/g, function (_, math) {
  const token = "DISPLAYMATH" + String(formulas.length).padStart(4, "0");
  formulas.push({ token, math, display: true });
  return "\n<div class=\"equation\">" + token + "</div>\n";
});
markdown = markdown.replace(/\$((?:\\.|[^$])+)\$/g, function (_, math) {
  const token = "INLINEMATH" + String(formulas.length).padStart(4, "0");
  formulas.push({ token, math, display: false });
  return token;
});
let body = marked.parse(markdown, { gfm: true });
for (const item of formulas) {
  const tex = item.display ? "\\[" + item.math + "\\]" : "\\(" + item.math + "\\)";
  body = body.replace(item.token, item.display ? tex : "<span class=\"math\">" + tex + "</span>");
}

const html = [
  "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
  "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
  "<title>第六章｜问题一与问题二的建模和求解</title>",
  "<script>window.MathJax={tex:{inlineMath:[[\"\\\\(\",\"\\\\)\"]],displayMath:[[\"\\\\[\",\"\\\\]\"]],packages:{'[+]':['noerrors']}},options:{enableMenu:false},svg:{fontCache:'global'}};</script>",
  "<script defer src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js\"></script>",
  "<style>",
  "@page{size:A4;margin:18mm 19mm 18mm 19mm}",
  "html{background:#e8edf0}body{max-width:800px;margin:22px auto;padding:52px 66px;background:#fff;color:#202b31;font:15px/1.72 'Microsoft YaHei','Noto Sans CJK SC',sans-serif;box-shadow:0 2px 24px #b9c4c9}",
  "h1{font-size:25px;line-height:1.25;margin:0 0 22px;color:#203e50}h2{font-size:19px;line-height:1.35;margin:35px 0 12px;padding-top:7px;border-top:1px solid #dce5e8;color:#245f78}h3{font-size:16px;margin:23px 0 8px;color:#344f5d}",
  "p{margin:0 0 13px}blockquote{margin:20px 0;padding:13px 18px;background:#f4f8fa;border-left:3px solid #245f78;color:#273840;break-inside:avoid}blockquote p{margin:0 0 6px}blockquote ol{margin:7px 0 4px 20px;padding:0}blockquote li{margin:4px 0}",
  "img{display:block;max-width:100%;height:auto;margin:18px auto 6px;break-inside:avoid}p:has(> img){margin:0}em{color:#566670;font-size:13px}a{color:#245f78}code{font:0.91em Consolas,'Microsoft YaHei',monospace;background:#eef3f5;padding:1px 3px}",
  "table{border-collapse:collapse;width:100%;font-size:13px;margin:16px 0 20px;break-inside:avoid}th,td{padding:6px 7px;border-bottom:1px solid #dbe3e6;text-align:center}th{border-top:1.5px solid #667b85;border-bottom:1px solid #667b85;background:#f5f8f9}tr:last-child td{border-bottom:1.5px solid #667b85}",
  ".equation{margin:15px 0 19px;overflow-x:auto}mjx-container[jax=\"SVG\"][display=\"true\"]{margin:0.6em 0!important}mjx-container svg{max-width:100%}",
  "@media print{html{background:#fff}body{max-width:none;margin:0;padding:0;box-shadow:none;font-size:10.5pt;line-height:1.58}h1{font-size:18pt}h2{font-size:14pt}h3{font-size:11.5pt}h1,h2,h3{break-after:avoid}blockquote,img,table{break-inside:avoid}p{orphans:3;widows:3}img{max-height:175mm;object-fit:contain}}",
  "</style></head><body>", body, "</body></html>"
].join("");
fs.writeFileSync(htmlFile, html, "utf8");

(async function () {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1150, height: 1500 } });
    await page.goto(pathToFileURL(htmlFile).href, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForFunction(
      () => window.MathJax && document.querySelectorAll("mjx-container").length >= 20,
      { timeout: 60000 }
    );
    const check = await page.evaluate(() => ({
      formulas: document.querySelectorAll("mjx-container").length,
      errors: document.querySelectorAll("mjx-merror").length,
      images: Array.from(document.images).filter(x => x.complete && x.naturalWidth > 0).length,
      totalImages: document.images.length
    }));
    if (check.errors || check.images !== 4 || check.totalImages !== 4) {
      throw new Error("formula/image render incomplete: " + JSON.stringify(check));
    }
    // Preserve the rendered SVG equations so the HTML also opens without network access.
    await page.evaluate(() => document.querySelectorAll("script").forEach(x => x.remove()));
    fs.writeFileSync(htmlFile, await page.content(), "utf8");
    await page.pdf({ path: pdfFile, format: "A4", printBackground: true,
                     preferCSSPageSize: true });
    console.log(JSON.stringify({ htmlFile, pdfFile, ...check }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
