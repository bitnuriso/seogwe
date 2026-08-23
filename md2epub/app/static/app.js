const $ = (id) => document.getElementById(id);
const meta = () => ({ title: $('title').value, author: $('author').value, language: $('language').value || 'ko', description: $('description').value });

document.querySelectorAll('[data-tab]').forEach(btn => btn.onclick = () => {
  document.querySelectorAll('[data-tab]').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  btn.classList.add('active'); $(btn.dataset.tab).classList.add('active');
});

function status(text, error=false) { $('status').classList.remove('hidden'); $('status').innerHTML = `<span class="${error?'error':''}">${text}</span>`; }
function render(project, url) {
  const volumes = project.volumes.map(v => `<li><strong>${escapeHtml(v.title)}</strong><ul>${v.sections.map(s => `<li>${escapeHtml(s.title)}<ul>${s.chapters.map(c => `<li>${escapeHtml(c.title)}</li>`).join('')}</ul></li>`).join('')}</ul></li>`).join('');
  $('tree').innerHTML = `<p><strong>${escapeHtml(project.title)}</strong> · ${project.chapter_count}개 장</p><ul>${volumes}</ul>`;
  $('download').href = url; $('result').classList.remove('hidden'); status('완료했습니다.');
}
function escapeHtml(s='') { return s.replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
async function send(url, body) {
  status('원고를 분석하고 EPUB을 만드는 중입니다…'); $('result').classList.add('hidden');
  try { const r = await fetch(url, {method:'POST', body}); const data = await r.json(); if (!r.ok) throw new Error(data.detail || '처리 실패'); render(data.project, data.download_url); }
  catch (e) { status(e.message, true); }
}
$('buildLocal').onclick = () => { const f = new FormData(); Object.entries(meta()).forEach(([k,v])=>f.append(k,v)); f.append('local_path',$('localPath').value); send('/api/build/local',f); };
$('buildUpload').onclick = () => { const file=$('file').files[0]; if(!file) return status('파일을 선택하세요.',true); const f=new FormData(); Object.entries(meta()).forEach(([k,v])=>f.append(k,v)); f.append('file',file); send('/api/build/upload',f); };
