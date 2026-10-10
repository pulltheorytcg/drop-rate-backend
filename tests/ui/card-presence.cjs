// Deterministic pixel-level scan guard tests. No camera, network or data writes.
const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.resolve(__dirname,'../../backend/app/static/scanner-flow.js'),'utf8');
const dom=new JSDOM('<div></div>',{url:'https://example.test',runScripts:'outside-only'});
dom.window.eval(source);
const detect=dom.window.DropRateScanner.analyzeCardPresence;
const W=48,H=68;

function picture({kind='blank',rect=null,bg=[193,189,183],light=1}={}){
 const pixels=new Uint8ClampedArray(W*H*4);
 let seed=12345;
 const random=()=>{seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return ((seed>>>0)%256);};
 for(let y=0;y<H;y++)for(let x=0;x<W;x++){
   let rgb=[...bg];
   if(kind==='gradient')rgb=[110+x*2,100+y,125+x+y];
   if(kind==='noise')rgb=[random(),random(),random()];
   if(kind==='checker')rgb=(Math.floor(x/2)+Math.floor(y/2))%2===0?[30,85,160]:[210,182,105];
   if(kind==='stripes')rgb=Math.floor(x/4)%2===0?[40,40,40]:[230,230,230];
   if(kind==='poster')rgb=[36+(x%4),41+(y%4),50];
   if(kind==='hand'){
     const ellipse=((x-24)/14)**2+((y-34)/25)**2;
     if(ellipse<1)rgb=[178+Math.round(x/7),100+Math.round(y/13),78];
   }
   if(rect && x>=rect.left && x<=rect.right && y>=rect.top && y<=rect.bottom){
     const border=x===rect.left||x===rect.right||y===rect.top||y===rect.bottom;
     rgb=border?[15,28,48]:[
       55+(x*7+y*11)%120,
       52+(x*13+y*3)%90,
       70+(x*5+y*17)%120,
     ];
   }
   const index=(y*W+x)*4;
   for(let channel=0;channel<3;channel++)pixels[index+channel]=Math.round(rgb[channel]*light);
   pixels[index+3]=255;
 }
 return pixels;
}
let checks=0;
const noCard=[
 ['plain desk',picture()],
 ['bright desk',picture({bg:[253,254,255]})],
 ['low-light empty desk',picture({bg:[28,32,35]})],
 ['lighting gradient',picture({kind:'gradient'})],
 ['moving hands (nonrectangular)',picture({kind:'hand'})],
 ['high-frequency patterned desk',picture({kind:'checker'})],
 ['high-variance noise',picture({kind:'noise'})],
 ['vertical-striped wall',picture({kind:'stripes'})],
 ['poster occupying camera frame',picture({kind:'poster'})],
 ['card far off centre',picture({rect:{left:0,right:30,top:8,bottom:58}})],
 ['partially visible card',picture({rect:{left:7,right:40,top:0,bottom:48}})],
];
for(const [name,pixels] of noCard){
 const result=detect(pixels,W,H);
 assert.equal(result.present,false,'No card should trigger on '+name+' '+JSON.stringify(result));
 checks++;
}
const card={left:8,right:40,top:9,bottom:58};
for(const [name,pixels] of [
 ['centered printed trading card',picture({rect:card})],
 ['bright card on light surface',picture({rect:card,bg:[238,236,231]})],
 ['printed slab/pack in darker lighting',picture({rect:card,bg:[28,32,39],light:0.82})],
]){
 const result=detect(pixels,W,H);
 assert.equal(result.present,true,'Visible framed item was not detected: '+name+' '+JSON.stringify(result));
 assert.ok(result.box.left>=4 && result.box.right>result.box.left);
 assert.ok(result.edgeConfidence>0.5);
 checks++;
}
assert.equal(detect(new Uint8ClampedArray(1),W,H).present,false);
checks++;

// Temporal controls must wait for observed absence, then a genuine stationary
// rectangle; jitter or one missing frame never authorises another auto scan.
const w=dom.window;
w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
w.HTMLDialogElement.prototype.close=function(){this.open=false;};
const session={access_token:'valid-seller-session',user:{id:'seller-test'}};
const scanner=new w.DropRateScanner.Scanner({
 role:'seller',session:()=>session,request:async()=>({}),afterSave:async()=>{},viewInventory:()=>{}
});
scanner.stream={getTracks:()=>[]};
scanner.view='camera';
Object.defineProperty(scanner.video,'videoWidth',{value:1920,configurable:true});
let frameResult={present:false,fingerprint:new Uint8Array(560).fill(100),
 box:null};
scanner.frame=()=>frameResult;
let captures=0;
scanner.capture=()=>{captures++;scanner.awaitingRemoval=true;};
const sample=(present,brightness=100,box={left:8,right:40,top:9,bottom:58})=>{
 frameResult={present,fingerprint:new Uint8Array(560).fill(brightness),box:present?box:null};
 scanner.tick();
};
// A false-positive/static rectangular scene present immediately at camera
// startup can NEVER trigger before an empty guide is observed.
for(let i=0;i<12;i++)sample(true);
assert.equal(captures,0);
assert.match(scanner.find('.dr-scan-status').textContent,/Clear the guide/);
checks++;
// After at least three empty frames, scan only a stable object.
for(let i=0;i<3;i++)sample(false);
for(let i=0;i<8;i++)sample(false);
assert.equal(captures,0);
for(let i=0;i<7;i++)sample(true);
assert.equal(captures,1,'Centered card should scan once when held steady');
checks++;
// Do not rescan identical content while it stays in frame.
for(let i=0;i<10;i++)sample(true);
sample(false);sample(true);for(let i=0;i<7;i++)sample(true);
assert.equal(captures,1,'Brief detection flicker must not rescan the same card');
checks++;
// 3 truly empty frames rearm the scanner for the next physical card.
for(let i=0;i<3;i++)sample(false);
for(let i=0;i<7;i++)sample(true);
assert.equal(captures,2);
checks++;
// Motion, border drift and shaking must block auto-capture until settled.
for(let i=0;i<3;i++)sample(false);
for(let i=0;i<8;i++)sample(true,i%2?50:135,{left:i%2?6:10,right:i%2?41:38,top:9,bottom:58});
assert.equal(captures,2,'Motion/geometry jitter must not be accepted');
for(let i=0;i<7;i++)sample(true,90,card);
assert.equal(captures,3,'Once steady, a properly framed card should scan');
checks++;
scanner.destroy();dom.window.close();
console.log('Card-only auto-capture: '+checks+' empty scene, realistic rectangle and temporal removal cases passed.');
