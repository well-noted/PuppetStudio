// DOM-free interaction checks. These supplement, rather than replace, browser QA.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../web/index.html'),'utf8').split('<script>')[1].split('</script>')[0];
const elements=new Map();let created=0;
const element=id=>{
 if(!elements.has(id))elements.set(id,{id,attributes:{},setAttribute(k,v){this.attributes[k]=v},style:{},value:'',textContent:'',innerHTML:'',hidden:false,checked:false,files:[],children:[],paused:true,currentTime:0,playbackRate:1,pause(){this.paused=true;this.onpause?.()},play(){this.paused=false;this.onplay?.();return Promise.resolve()},appendChild(x){this.children.push(x)},replaceChildren(...x){this.children=x},getContext:()=>new Proxy({measureText:t=>({width:t.length*8})},{get:(o,k)=>o[k]||(()=>{})}),getBoundingClientRect:()=>({left:0,top:0,width:1280,height:720})});
 return elements.get(id);
};
let confirmations=0,requests=[];
const project={schema:'puppet-studio-1',name:'Test project',media:null,transcript:null,speakers:[],clips:[],productions:[],settings:{backend:'still',sadtalker_repo:'',sadtalker_python:'',expression_scale:1,chunk_seconds:75,transcription:'local',planning:'rules',whisper_model:'small',language:'',target_seconds:60,max_seconds:150,api_base:'https://example.test/v1',key_env:'STUDIO_API_KEY',chat_model:'test',image_model:'test',transcription_model:'test',style:'Line art'}};
const context={console,Date,JSON,Math,Error,Promise,encodeURIComponent,clearTimeout:()=>{},setTimeout:()=>1,setInterval:()=>1,confirm:()=>{confirmations++;return false;},document:{documentElement:{dataset:{}},cookie:'',getElementById:element,querySelectorAll:()=>[],createElement:()=>element('created_'+created++)},fetch:async(url,options)=>{requests.push(url);return{ok:true,json:async()=>(url.startsWith('/api/machine')?{platform:'Linux',architecture:'x86_64',python:'python',python_version:'3.12',tools_home:'/tmp/tools',free_gib:20,gpus:[],ffmpeg:'ffmpeg',ffprobe:'ffprobe',suggested_preset:'composition',note:'Test machine'}:url.startsWith('/api/renders')?{renders:[{path:'renders/solo/clips/test_preview.mp4',production_id:'solo',production_name:'Solo',title:'Test clip',kind:'preview',preview:true,size_bytes:100,modified:1,duration:12}]}:{project,meta:{},job:null})}}};context.window=context;vm.createContext(context);vm.runInContext(source,context);
(async()=>{
 await new Promise(r=>setImmediate(r));
 const productionBeforeTheme=JSON.stringify(project);
 vm.runInContext("applyTheme('light');toggleTheme()",context);assert.equal(context.document.documentElement.dataset.theme,'dark');assert.equal(element('themeToggle').attributes['aria-pressed'],'true');assert(context.document.cookie.includes('puppet_studio_theme=dark'));
 vm.runInContext('initializeTheme()',context);assert.equal(context.document.documentElement.dataset.theme,'dark');assert.equal(JSON.stringify(project),productionBeforeTheme);
 vm.runInContext('toggleTheme()',context);assert.equal(context.document.documentElement.dataset.theme,'light');
 for(const tab of ['Recording','Speakers & art','Clips','Productions','Render queue','Advanced']){
  vm.runInContext(`tab(${JSON.stringify(tab)})`,context);assert(element('main').innerHTML.includes('<h1>'),tab);
 }
 assert(element('main').innerHTML.includes('Check model environment'));
 vm.runInContext("job={id:'test',action:'transcribe',status:'running',started:Date.now()/1000,lines:['Working']};updateJob()",context);
 assert.equal(element('globalJob').hidden,false);assert(element('globalJob').textContent.includes('transcribe'));
 vm.runInContext("P.media={path:'media/source.mp4',video:true,duration:30}",context);
 const input={files:[{name:'new.mp4'}],value:'new.mp4'};context.input=input;
 await vm.runInContext("upload(input,'import-media')",context);
 assert.equal(confirmations,1);assert.equal(input.value,'');assert(!requests.some(x=>x.includes('upload')));
 vm.runInContext("addClip();tab('Clips')",context);assert(element('main').innerHTML.includes('Review source clip'));
 vm.runInContext("P.speakers=[{id:'speaker',name:'Person',title:'Role',poses:[],asset:null,profile:null,approved:false}];tab('Speakers & art')",context);
 assert(element('main').innerHTML.includes('Person'));assert(element('main').innerHTML.includes('Detect anatomy'));
 vm.runInContext("P.clips[0].reviewed=true;put(P.clips[0],'start',1)",context);assert.equal(vm.runInContext('P.clips[0].reviewed',context),true);
 const fixture=JSON.parse(require('child_process').execFileSync(process.env.STUDIO_TEST_PYTHON||'python',['-c',"import json;from studio.core import actor;from scene import default_scene;s={'id':'speaker','name':'Person','title':'Role'};scene=default_scene();scene['actors']=[actor(s)];print(json.dumps(scene))"],{cwd:require('path').join(__dirname,'..'),encoding:'utf8'}));
 context.sceneFixture=fixture;
 vm.runInContext("P.productions=[{id:'solo',name:'Solo',clips:[],output:'both',intro_mode:'clip',scene:sceneFixture}];prodId='solo';tab('Productions')",context);
 assert(element('main').innerHTML.includes('Audio processing'));assert(!element('main').innerHTML.includes('This page could not open'));
 const phraseInput=element('main').innerHTML.match(/Emphasis phrases \(one per line\)<\/label><textarea oninput="([^"]+)"/);
 assert(phraseInput);context.phraseEdit={value:'  A new point  \nFor this reason\n\n'};
 vm.runInContext('(function(){'+phraseInput[1]+'}).call(phraseEdit)',context);
 assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(activeActor().gestures.phrases)',context)),['A new point','For this reason']);
 assert.equal(vm.runInContext('dirty',context),true);
 vm.runInContext("tab('Clips');tab('Productions')",context);assert(element('main').innerHTML.includes('A new point\nFor this reason'));

 vm.runInContext("tab('Clips');tab('Productions')",context);assert(element('main').innerHTML.includes('Audio processing'));
 // Place clip-specific cues from the source player's current time.
 vm.runInContext("P.speakers[0].poses=[{id:'explain',path:'assets/person/explain.png'}];P.clips[0].speaker='speaker';P.clips[0].start=10;P.clips[0].end=25;production().clips=[P.clips[0].id];tab('Productions')",context);
 assert(element('main').innerHTML.includes('Start and End are seconds'));assert(element('main').innerHTML.includes('Add gesture here'));
 vm.runInContext('openGestureClip(P.clips[0].id);gesturePlayback.video.readyState=2;gesturePlayback.video.currentTime=13;$("gestureInsertDuration").value="3";$("gestureInsertPose").value="explain";addGestureHere()',context);
 const marked=JSON.parse(vm.runInContext('JSON.stringify(activeActor().gestures.cues[0])',context));
 assert.equal(marked.start,3);assert.equal(marked.end,6);assert.equal(marked.clip,vm.runInContext('P.clips[0].id',context));assert.equal(vm.runInContext('activeActor().gestures.mode',context),'manual');
 assert(vm.runInContext('gesturePlayback!==null',context));assert(element('manualCueList').innerHTML.includes('Start (seconds into clip)'));
 vm.runInContext('gesturePlayback.video.currentTime=14;addGestureHere()',context);assert.equal(vm.runInContext('activeActor().gestures.cues.length',context),1);assert(element('toast').textContent.includes('overlaps'));
 vm.runInContext('gesturePlayback.video.currentTime=24.5;addGestureHere()',context);assert.equal(vm.runInContext('activeActor().gestures.cues[1].end',context),15);
 vm.runInContext('gesturePlayback.video.paused=false;gesturePlayback.video.currentTime=25;gesturePlayback.video.ontimeupdate()',context);assert(vm.runInContext('gesturePlayback.video.paused',context));
 // An unrelated malformed scene must not permanently strand navigation.
 const previousConsole=context.console;context.console={...console,error:()=>{}};
 vm.runInContext("delete P.productions[0].scene.audio;tab('Productions')",context);assert(element('main').innerHTML.includes('This page could not open'));
 vm.runInContext("tab('Clips')",context);assert(element('main').innerHTML.includes('Review source clip'));context.console=previousConsole;
 vm.runInContext("P.clips[0].start=1;P.clips[0].end=10;P.clips[0].reviewed=true;playClip(P.clips[0].id)",context);
 const clipId=vm.runInContext('P.clips[0].id',context);context.clipId=clipId;
 vm.runInContext("setTrim(clipId,'start',3.5)",context);assert.equal(vm.runInContext('P.clips[0].start',context),3.5);assert.equal(vm.runInContext('P.clips[0].reviewed',context),true);assert(element('clipReviewStats').textContent.includes('1 approved'));assert.equal(element('reviewStatus_'+clipId).textContent,'Approved');assert.equal(element('clip_'+clipId+'_start').value,3.5);
 vm.runInContext("setTrim(clipId,'end',2)",context);assert(vm.runInContext('P.clips[0].end>P.clips[0].start',context));
 vm.runInContext("let state=sourcePlayers.get(clipId);state.video.currentTime=P.clips[0].end+.1;state.video.paused=false;scheduleSourceStop(clipId)",context);assert(vm.runInContext('sourcePlayers.get(clipId).video.paused',context));assert.equal(vm.runInContext('sourcePlayers.get(clipId).video.currentTime',context),vm.runInContext('P.clips[0].end',context));
 vm.runInContext("tab('Renders')",context);await vm.runInContext('loadRenders()',context);assert(element('renderList').innerHTML.includes('Test clip'));assert(element('renderList').innerHTML.includes('Download'));vm.runInContext('playRender(0)',context);assert(element('completedVideo').src.includes('test_preview.mp4'));assert.equal(element('renderPlayer').hidden,false);
 vm.runInContext("put(P.clips[0],'reviewed',false)",context);assert(element('clipReviewStats').textContent.includes('1 not approved'));
 vm.runInContext("put(P.clips[0],'intro','Changed context')",context);assert.equal(vm.runInContext('P.clips[0].reviewed',context),false);
 const sliced=vm.runInContext("clipTranscript({words:[{start:0,end:1,word:'before'},{start:1,end:2,word:'inside'},{start:2,end:3,word:'after'}]},1,2)",context);assert.equal(sliced.text,'inside');
 const fallback=vm.runInContext("clipTranscript({segments:[{start:0,end:4,text:'Whole segment'},{start:8,end:9,text:'Outside'}]},1,2)",context);assert.equal(fallback.text,'Whole segment');assert(fallback.note.includes('edges'));
 vm.runInContext("tab('Clips');P.transcript='transcript/transcript.json';transcriptData={words:[{start:3,end:4,word:'Visible text'}]};$('transcript_'+P.clips[0].id).hidden=true",context);
 await vm.runInContext('toggleClipTranscript(P.clips[0].id)',context);assert.equal(element('transcriptText_'+clipId).textContent,'Visible text');
 vm.runInContext("put(P.clips[0],'start',4.5)",context);assert.equal(element('transcriptText_'+clipId).textContent,'No transcript text in this interval.');
 await vm.runInContext('toggleClipTranscript(P.clips[0].id)',context);assert(element('transcript_'+clipId).hidden);
 vm.runInContext("P.speakers[0].reference='assets/person/reference.png';tab('Speakers & art')",context);assert(element('main').innerHTML.includes('Open image'));assert(element('main').innerHTML.includes('Download reference'));assert(element('main').innerHTML.includes('assets/person/reference.png'));
 assert(element('main').innerHTML.includes('Prepare gesture locally'));assert(element('main').innerHTML.includes('Feather inside region'));assert(element('main').innerHTML.includes('Generate mask proposal (local)'));assert(element('main').innerHTML.includes('Extract padded bust (local)'));assert(element('main').innerHTML.includes('Generate gesture draft (API)'));
 vm.runInContext("tab('Getting started')",context);assert(element('main').innerHTML.includes('Find and verify existing animation tools'));assert(element('main').innerHTML.includes('Your next steps'));assert(element('main').innerHTML.includes('does not mean your computer lacks them'));vm.runInContext("P.settings.sadtalker_repo='existing';P.settings.sadtalker_python='python.exe';tab('Getting started')",context);assert(element('main').innerHTML.includes('installing another one is optional'));vm.runInContext("tab('Speakers & art')",context);assert(element('main').innerHTML.includes('Style preset'));assert(element('main').innerHTML.includes('Use another assistant'));
 vm.runInContext("P.clips[0].speaker='speaker';P.clips[0].start=1;P.clips[0].end=10;tab('Speakers & art')",context);
 assert(element('main').innerHTML.includes('Capture this frame'));assert(element('main').innerHTML.includes('Choose a speaker clip'));
 vm.runInContext('openReferenceClip(clipId)',context);assert.equal(vm.runInContext('sourcePlayers.get(clipId).lo',context),1);
 const beforeCapture=requests.length;
 vm.runInContext('sourcePlayers.get(clipId).video.readyState=2;sourcePlayers.get(clipId).video.currentTime=11;captureReferenceClip()',context);
 assert.equal(requests.length,beforeCapture);
 vm.runInContext("tab('Advanced')",context);assert(element('main').innerHTML.includes('Model download authentication'));assert(element('main').innerHTML.includes('Hugging Face hosted ASR'));
 assert.equal(vm.runInContext("gestureUploadId('explain.png')",context),'explain');
 assert.equal(vm.runInContext("gestureUploadId('Open palm.png')",context),'Open_palm');
 assert.equal(vm.runInContext("gestureUploadId('character.png')",context),'gesture_character');
 assert.equal(vm.runInContext("gestureUploadId('explain.png',[{id:'explain'}])",context),'explain_2');
 // Windows paths must travel as data, never as a JavaScript string literal.
 context.windowsDraft='assets\\person\\draft_breath.png';
 const draftHtml=vm.runInContext("assetDraftControls({asset_drafts:[{kind:'breath',path:windowsDraft}]})",context);
 const draftButton=draftHtml.match(/<button data-draft-path="([^"]+)" onclick="([^"]+)">Import reviewed draft/);
 assert(draftButton);assert.equal(draftButton[1],context.windowsDraft);
 context.capturedDraft=null;vm.runInContext('act=(name,args)=>{capturedDraft=args.path}',context);
 vm.runInContext('(function(){'+draftButton[2]+'}).call({dataset:{draftPath:windowsDraft}})',context);
 assert.equal(context.capturedDraft,context.windowsDraft);
 console.log('PASS: empty workflow pages, diagnostics controls, global progress, replacement confirmation, clip and speaker pages');
})().catch(e=>{console.error(e);process.exitCode=1});
