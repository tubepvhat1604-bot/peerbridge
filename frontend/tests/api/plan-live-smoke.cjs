// Real HTTP + actual frontend API client, against the explicitly isolated demo command.
// All students, future time, LLM and Vision/Data1/SE adapters in this scenario are SIMULATED.
const assert = require("node:assert/strict");
const {readFileSync,writeFileSync,mkdirSync} = require("node:fs");
const path = require("node:path");
const {randomUUID} = require("node:crypto");
const vm = require("node:vm");
const ts = require("typescript");
const base = process.env.PLAN_DEMO_URL || "http://127.0.0.1:8015";
if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base)) throw new Error("This smoke test only runs against an explicit localhost demo.");
const source = readFileSync(path.resolve(__dirname,"../../lib/api.ts"),"utf8");
const {outputText} = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}});
const exportsForClient = {};
vm.runInNewContext(outputText,{exports:exportsForClient,fetch,JSON,process:{env:{NEXT_PUBLIC_API_URL:base}}});
const {api} = exportsForClient;

async function main() {
  const health = await (await fetch(`${base}/health`)).json();
  assert.equal(health.mode,"simulated-plan-demo","Refuse to modify a real/dev product database");
  const outputFlag = process.argv.indexOf("--output-dir");
  if (outputFlag !== -1 && (!process.argv[outputFlag+1] || process.argv[outputFlag+1].startsWith("--"))) throw new Error("--output-dir requires a new directory path");
  const outputDir = outputFlag === -1
    ? path.resolve(__dirname,`../../../docs/evidence/ai-data-2/http-smoke-${Date.now()}-${randomUUID()}`)
    : path.resolve(process.argv[outputFlag+1]);
  mkdirSync(path.dirname(outputDir),{recursive:true});
  mkdirSync(outputDir); // Exclusive claim before registering personas or mutating the demo.
  const people=[];
  for (const [index,track] of ["SQL","Python"].entries()) {
    const auth = await api.register({email:`simulated-${track}-${Date.now()}@example.test`,password:"Simulated-Only-2030",display_name:`Demo ${track}`,age:22,city:"Demo",intent:"conversation"});
    const windows=[0,1,2,3,4].map(day=>({day_of_week:day,start_time:index?"18:00":"19:00",end_time:index?"19:30":"20:30",timezone:"Asia/Ho_Chi_Minh"}));
    await api.updateProfile(auth.access_token,{profile:{display_name:`Demo ${track}`,bio:"SIMULATED PERSONA",school:"Demo",major:"Demo",subjects:[track],learning_goals:[`Learn basic ${track}`]},needs_help_with:[{topic:track,description:"SIMULATED",current_level:"beginner",target_outcome:"Basic exercises"}],can_help_with:[],availability:windows});
    people.push({...auth,track});
  }
  const invite = await api.requestConnection(people[0].access_token,{recipient_id:people[1].user_id});
  const accepted = await api.acceptConnection(people[1].access_token,invite.id);
  const pair = accepted.peer_match_id;
  const setup = await api.planSetup(people[0].access_token,pair);
  assert.equal(setup.catalog_source,"demo");assert.equal(setup.provider_mode,"fake");
  const members = people.map((p,index)=>({user_id:p.user_id,goal:`Learn basic ${p.track}`,concept_ids:[index?"python.loops":"sql.join"],known_concept_ids:[],can_help_concept_ids:[],committed_minutes_per_week:index?240:180,timezone:"Asia/Ho_Chi_Minh",location:"SIMULATED study corner",deadline:null,availability:setup.members.find(m=>m.user_id===p.user_id).availability.map(w=>({id:String(w.id),day_of_week:w.day_of_week,start_time:w.start_time,end_time:w.end_time}))}));
  const payload = {pair_id:pair,members,horizon_days:7};
  const key = `SIMULATED-${Date.now()}`;
  const generated = await api.generatePlan(people[0].access_token,payload,key);
  const repeat = await api.generatePlan(people[0].access_token,payload,key);
  assert.deepEqual(generated,repeat);
  const own = await api.plan(people[0].access_token,pair);
  const partner = await api.plan(people[1].access_token,pair);
  assert.equal(own.plan.items.length,3);assert.equal(partner.plan.items.length,3);
  assert.ok(own.plan.items.every(i=>i.concept_id.startsWith("sql.")));
  assert.ok(partner.plan.items.every(i=>i.concept_id.startsWith("python.")));
  const advanced = await (await fetch(`${base}/__demo/advance`,{method:"POST"})).json();
  assert.equal(advanced.simulation,true);
  const event={event_id:"SIMULATED-VISION-EVENT",plan_item_id:own.plan.items[0].id,pair_id:pair,user_id:people[0].user_id,plan_version:1,confirmed_at:advanced.now,confirmed:true};
  const unconfirmed={...event};delete unconfirmed.confirmed;
  const rejected=await fetch(`${base}/api/v1/plans/events/completion`,{method:"POST",headers:{"Content-Type":"application/json","X-Vision-Key":"SIMULATED-VISION-ONLY"},body:JSON.stringify(unconfirmed)});
  assert.equal(rejected.status,422);
  assert.equal((await api.plan(people[0].access_token,pair)).plan.items[0].status,"SCHEDULED");
  async function checkin(){const response=await fetch(`${base}/api/v1/plans/events/completion`,{method:"POST",headers:{"Content-Type":"application/json","X-Vision-Key":"SIMULATED-VISION-ONLY"},body:JSON.stringify(event)});assert.equal(response.status,200);return response.json();}
  assert.equal((await checkin()).applied,true);assert.equal((await checkin()).duplicate,true);
  const decision = await api.evaluateCoach(people[0].access_token,pair);
  assert.equal(decision.action,"replan");assert.equal(decision.delivery_status,"SIMULATED");assert.equal(decision.sent,false);
  if (process.argv.includes("--coach-v2")) {
    assert.equal(decision.variant,"ai");assert.equal(decision.selection.mode,"v2");
    assert.deepEqual(decision.selection.nodes,["load_context","eligibility","decide","validate_action","prepare_action","save_log"]);
    assert.equal(decision.selection.provider_mode,"fake");
    assert.equal(decision.message_source,"ai");
    assert.equal(decision.text,"Bạn có thể xem phương án giảm tải và tự quyết định khi sẵn sàng.");
    assert.ok(decision.trace_id);
  }
  assert.equal((await api.evaluateCoach(people[0].access_token,pair)).reason,"DAILY_LIMIT");
  const preview = await api.plan(people[0].access_token,pair);
  assert.equal(preview.plan.plan_version,1);assert.ok(preview.proposal);
  const budget=preview.proposal.budget.find(b=>b.week_start==="2030-01-07");
  assert.equal(budget.baseline_minutes,144);assert.equal(budget.completed_minutes,30);
  assert.equal(budget.remaining_minutes,114);assert.equal(budget.proposed_limit_minutes,91);
  assert.equal(preview.proposal.after.items.find(i=>i.id===event.plan_item_id).status,"COMPLETED");
  assert.equal((await api.decideReplan(people[0].access_token,pair,preview.proposal.id,1,true)).applied,true);
  assert.equal((await api.decideReplan(people[0].access_token,pair,preview.proposal.id,1,true)).duplicate,true);
  const final = await api.plan(people[0].access_token,pair);
  assert.ok(final.plan.plan_version>1);assert.equal(final.plan.items.find(i=>i.id===event.plan_item_id).status,"COMPLETED");
  const report={ran_at:new Date().toISOString(),simulation:true,transport:"real localhost HTTP, actual frontend api.ts",fake_components:["personas","2030 clock","FakeLLM","Vision confirmation event","Data1 metrics","notification"],pair_id:pair,goals:members.map(m=>m.goal),scheduled_counts:[own.plan.items.length,partner.plan.items.length],idempotent_generation:true,idempotent_checkin:true,explicit_vision_confirmation_required:true,coach_action:decision.action,delivery_status:decision.delivery_status,real_sends:0,replan_budget:budget,replan_requires_confirmation:true,replan_accepted_once:true,completed_id_preserved:true,final_version:final.plan.plan_version};
  report.coach_variant=decision.variant;report.coach_selection=decision.selection;
  report.coach_message_source=decision.message_source;report.coach_trace_id=decision.trace_id;
  report.external_trace=decision.external_trace;
  report.visual_browser_qa=false;
  const output = path.join(outputDir,"results.json");
  writeFileSync(output,JSON.stringify(report,null,2)+"\n",{flag:"wx"});
  console.log(`Artifacts: ${outputDir}`);
  console.log(JSON.stringify(report,null,2));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
