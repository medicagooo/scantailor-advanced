// Execute the generated viewer script against a minimal DOM to verify language
// changes and opaque report text. No report content is evaluated as markup/code.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const make = () => ({value:'0', selectedIndex:0, children:[], dataset:{}, classList:{toggle(){}},
  append(item){this.children.push(item)}, setAttribute(key,value){this[key]=value}});
const elements = Object.fromEntries(['#language','#page','#info','#heading','#original img','#result img','#original','#result','#prev','#next','#zoom','main'].map(key=>[key,make()]));
const messages = [...html.matchAll(/data-i18n="([^"]+)"/g)].map(match=>Object.assign(make(),{dataset:{i18n:match[1]}}));
const modes = ['both','original','result'].map(mode=>Object.assign(make(),{dataset:{mode}}));
const document = {documentElement:{},body:make(),title:'',querySelector:key=>elements[key],
 querySelectorAll:key=>key==='[data-i18n]'?messages:key==='[data-mode]'?modes:[],createElement:make};
const context=vm.createContext({document});
new vm.Script(script).runInContext(context);
for(const [locale,title,status] of [['en','Preview comparison','Complete'],['zh-Hans','预览对比','完成'],['zh-Hant','預覽比較','完成']]){
 elements['#language'].value=locale;elements['#language'].onchange();
 assert.equal(document.documentElement.lang,locale);
 assert.equal(document.title,'ScanTailor · '+title);
 assert.ok(elements['#info'].textContent.includes(status));
 assert.ok(elements['#info'].textContent.includes('__LANGUAGE__ __TRANSLATIONS__ __DATA__'));
}
console.log('PASS: generated JavaScript parses; all three language switches preserve opaque report data.');
