import {test,expect} from '@playwright/test';

// Presentation boundary only; encrypted-client tests retain the real client.
test.beforeEach(async({context})=>{
 await context.route('**/src/features/encryption/client.ts',route=>route.fulfill({contentType:'application/javascript',body:'export * from "/tests/fixtures/presentation-client.ts";'}));
});

const catalog=()=>({user:{id:10,role:'owner'},projects:[{id:'old',title:'Annatar'},{id:'new',title:'Workspace'}],threads:[
 {id:'thread-old',project_id:'old',title:'Old task',status:'idle',updated_at:100},
 {id:'thread-second',project_id:'new',title:'Second task',status:'idle',updated_at:200},
 {id:'thread-newest',project_id:'new',title:'Newest task',status:'idle',updated_at:300}
],messages:[],catalog_updated:1,collector_seen:Date.now()/1000});

test('sorts projects and tasks, restores across new tabs, and prioritizes explicit links',async({context,page})=>{
 const state=catalog();
 await context.route('**/auth/session',r=>r.fulfill({json:{csrf:'test',workspace:state}}));
 await context.route('**/web/**',r=>r.fulfill({json:new URL(r.request().url()).pathname==='/web/state'?state:{messages:[],pending:false}}));
 await page.goto('/');
 await expect(page.getByRole('combobox',{name:'Проект'}).locator('option')).toHaveText(['Workspace','Annatar']);
 await expect(page.locator('.workspace-header')).toContainText('Newest task');
 await expect(page.locator('#sidebar-project-tasks button')).toHaveText(['Newest task','Second task']);
 await page.getByRole('button',{name:'Second task',exact:true}).click();
 const next=await context.newPage();await next.goto('/');
 await expect(next.locator('.workspace-header')).toContainText('Second task');
 await next.goto('/#thread=thread-old');
 await expect(next.locator('.workspace-header')).toContainText('Old task');
 state.threads=state.threads.filter(t=>t.id!=='thread-old');
 await next.goto('/');
 await expect(next.locator('.workspace-header')).toContainText('Newest task');
});
