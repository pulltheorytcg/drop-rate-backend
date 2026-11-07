// Execute the actual API predicates in disposable PostgreSQL, including the
// comic regression: an ordinary book uses condition and never a seal state.
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {PGlite} from "../tools/history-archive-verify/node_modules/@electric-sql/pglite/dist/index.js";

const root=fileURLToPath(new URL("../",import.meta.url));
const predicates=JSON.parse(execFileSync(process.env.TEST_PYTHON || "python",["-c",
  "import json; from app.api import READY_SQL, ISSUE_FILTERS; print(json.dumps({'ready':READY_SQL,'condition':ISSUE_FILTERS['missing_condition'],'seal':ISSUE_FILTERS['missing_seal_status']}))"
],{cwd:root,env:{...process.env,PYTHONPATH:`${root}backend`},encoding:"utf8"}));
const db=new PGlite();
const sql=`with p as (select $1::text product_type),i as (
 select $2::text condition,$3::text seal_status,$4::text grading_company,$5::text grade,
 $6::text certificate_number,$7::integer acquisition_cost_minor,$8::uuid storage_location_id,
 $9::text language,$10::bigint store_price_minor,$11::boolean identity_confirmed,
 'INSPECTION'::text status,'FOR_SALE'::text sale_intent)
 select coalesce((${predicates.ready}),false) as ready,
 coalesce((${predicates.condition}),false) as missing_condition,
 coalesce((${predicates.seal}),false) as missing_seal from i cross join p`;
const base={kind:"COMIC",condition:"Mint",seal:null,company:null,grade:null,certificate:null,
 cost:500,location:"00000000-0000-0000-0000-000000000001",language:"English",price:1000,identity:true};
const cases=[
 ["raw comic",{},true,false,false],
 ["graded comic",{condition:null,company:"CGC",grade:"9.8"},true,false,false],
 ["comic needs condition",{condition:null},false,true,false],
 ["comic does not use seal",{seal:"SEALED"},false,false,false],
 ["invalid book condition",{condition:"Lightly Played"},false,false,false],
 ["invalid book grade",{condition:null,company:"CGC",grade:"11"},false,false,false],
 ["raw book certificate",{certificate:"123"},false,false,false],
 ["figure without packaging",{kind:"FIGURE",condition:"Like New"},true,false,false],
 ["figure with packaging",{kind:"FIGURE",condition:"New",seal:"SEALED"},true,false,false],
 ["figure needs condition",{kind:"FIGURE",condition:null},false,true,false],
 ["figure cannot use grade",{kind:"FIGURE",condition:null,company:"CGC",grade:"9.8"},false,false,false],
 ["raw card",{kind:"CARD",condition:"Near Mint"},true,false,false],
 ["sealed product",{kind:"SEALED",condition:null,seal:"SEALED"},true,false,false],
 ["collection product",{kind:"COLLECTION",condition:null,seal:"UNSEALED"},true,false,false],
 ["sealed needs seal",{kind:"SEALED",condition:null},false,false,true],
 ["purchase cost is optional",{cost:null},true,false,false],
 ["explicit zero purchase cost",{cost:0},true,false,false],
 ["unknown cost still requires location",{cost:null,location:null},false,false,false],
 ["unknown cost still requires identity",{cost:null,identity:false},false,false,false],
 ["location gate",{location:null},false,false,false],
 ["identity gate",{identity:false},false,false,false],
 ["language gate",{language:null},false,false,false],
 ["price gate",{price:null},false,false,false],
];
for(const [label,changes,ready,missing_condition,missing_seal] of cases){
 const row={...base,...changes};
 const args=[row.kind,row.condition,row.seal,row.company,row.grade,row.certificate,
   row.cost,row.location,row.language,row.price,row.identity];
 const result=await db.query(sql,args);
 assert.deepEqual(result.rows[0],{ready,missing_condition,missing_seal},label);
}
await db.close();
console.log(`PASS: ${cases.length} actual PostgreSQL inventory-readiness cases`);
