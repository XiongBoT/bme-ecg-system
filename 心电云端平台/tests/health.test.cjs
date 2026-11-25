const test=require('node:test');const assert=require('node:assert/strict');
const core=require('../web/health_core.js');
test('settings reject corrupted and out-of-range persisted values',()=>{
  assert.deepEqual(core.preferences({duration:2,refreshSeconds:1,textSize:'huge',contrast:'broken'}),core.defaults);
  assert.equal(core.preferences({duration:'60',textSize:'large'}).duration,60);
});
test('missing heart rate remains a gap and is never charted as zero',()=>{
  const values=core.series([{hr_mean:72},{hr_mean:null},{hr_mean:80}],'hr');
  assert.deepEqual(values,[72,null,80]);assert.equal(core.points(values)[1],null);
});
test('duration series uses minutes and actual records not page lengths',()=>{
  assert.deepEqual(core.series([{duration_s:120,records:7}],'duration'),[2]);
  assert.deepEqual(core.series([{duration_s:120,records:7}],'records'),[7]);
});
test('local date formatting does not use UTC day conversion',()=>assert.equal(core.day(new Date(2024,1,29,23,59)),'2024-02-29'));
