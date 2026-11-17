/** Single-owner Shiori OAuth consent: explicit read requirement, optional write. */
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&#39;"}[c]));

/** Keep the two scope choices together, rather than scattered through the page. */
export function renderConsentPage({clientName,requestedScopes,nonce}) {
 const writeRequested=requestedScopes.includes("mcp:write");
 const css=[
  ':root{color-scheme:dark;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}',
  '*{box-sizing:border-box}',
  'body{background:#0d1117;color:#edf2fc;margin:0;min-height:100vh;display:grid;place-items:center;padding:24px}',
  '.panel{width:100%;max-width:472px;padding:30px;border:1px solid #344258;border-radius:16px;background:#161d29;box-shadow:0 14px 45px #05070b44}',
  'h1{font-size:26px;line-height:1.2;letter-spacing:-.5px;margin:0 0 12px}',
  'h2{font-size:15px;line-height:1.4;margin:24px 0 11px}',
  'p{line-height:1.55;margin:0;color:#b7c3d6}',
  '.intro{font-size:14px}.intro strong{color:#eef2fc}',
  '.permission-list{display:grid;gap:10px}',
  '.permission{display:flex;align-items:flex-start;gap:12px;cursor:pointer;background:#101823;border:1px solid #37465c;border-radius:10px;padding:14px}',
  '.permission:hover{border-color:#7398c8}',
  '.permission:has(input:focus-visible){outline:2px solid #b6cff3;outline-offset:2px}',
  '.permission input{margin:2px 0 0;flex:none}',
  'input[type=checkbox]{accent-color:#b6cff3;width:18px;height:18px;cursor:pointer}',
  '.permission-text{display:block;min-width:0;flex:1}',
  '.permission-heading{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:4px;color:#f0f5ff;font-weight:650;font-size:14px}',
  '.permission-desc{display:block;font-size:13px;color:#aab8ca;line-height:1.5}',
  '.flag{border:1px solid #465773;border-radius:999px;padding:2px 7px;font-size:11px;font-weight:550;color:#b6c9e3}',
  '.hint{font-size:12px;margin-top:9px;color:#aab8ca;line-height:1.55}',
  '.code-label{display:block;font-size:14px;margin:22px 0 7px;color:#e7eefb;font-weight:600}',
  'input[type=password]{display:block;width:100%;padding:12px;border-radius:8px;background:#0d1117;border:1px solid #62718a;color:#fff;font-size:16px}',
  'input[type=password]:focus-visible{outline:2px solid #b6cff3;outline-offset:2px}',
  '.confirm{display:flex;align-items:flex-start;gap:10px;margin:20px 0 16px;font-size:13px;line-height:1.5;cursor:pointer;color:#d9e4f5}',
  '.confirm input{margin-top:1px;flex:none}',
  'button{display:block;width:100%;padding:12px;border:0;border-radius:8px;background:#b6cff3;color:#142136;font-size:14px;font-weight:700;cursor:pointer}',
  'button:hover{background:#c6daf6}button:focus-visible{outline:2px solid #fff;outline-offset:3px}',
  '.isolation{border-top:1px solid #344258;padding-top:14px;margin-top:18px;font-size:12px}',
  '@media(max-width:480px){body{padding:14px;place-items:start center}.panel{padding:22px 18px}h1{font-size:24px}}'
 ].join("");
 return [
  '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
  '<title>Shiori — Authorize App</title><style>',css,'</style></head><body><main class="panel">',
  '<h1>Connect to Shiori</h1><p class="intro"><strong>',esc(clientName),'</strong> requests access to your personal cloud workspace.</p>',
  '<form method="post" action="/authorize"><input type="hidden" name="nonce" value="',esc(nonce),'">',
  '<h2 id="permissions-heading">Workspace permissions</h2><div class="permission-list" role="group" aria-labelledby="permissions-heading">',
  '<label class="permission"><input type="checkbox" name="read_access" value="yes" checked required>',
  '<span class="permission-text"><span class="permission-heading">Read access <span class="flag">Required</span></span>',
  '<span class="permission-desc">View tasks, dependencies and spatial layouts. (mcp:read)</span></span></label>',
  '<label class="permission"><input type="checkbox" name="write_access" value="yes">',
  '<span class="permission-text"><span class="permission-heading">Write access <span class="flag">Optional</span></span>',
  '<span class="permission-desc">Create tasks, change statuses and adjust spatial layouts. (mcp:write)</span></span></label>',
  '</div><p class="hint">',
  (writeRequested?'ChatGPT requested both permissions. Write access is granted only if selected.':'ChatGPT requested read access. Select write access separately to enable editing tools.'),
  '</p>',
  '<label class="code-label" for="approval-code">Owner approval code</label>',
  '<input id="approval-code" type="password" name="code" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" minlength="24" maxlength="160" aria-describedby="code-hint" required>',
  '<p class="hint" id="code-hint">Use your separate Shiori OAuth approval code, not your original MCP bearer token.</p>',
  '<label class="confirm"><input type="checkbox" name="approve" value="yes" required>',
  '<span>I approve this connection with the permissions selected above.</span></label>',
  '<button type="submit">Authorize Shiori</button></form>',
  '<p class="isolation">Your Cloudflare workspace is not yet synchronized with your offline Rust tasks.</p>',
  '</main></body></html>'
 ].join("");
}

/** Server-side validation: browser checkboxes are not a security boundary. */
export function validateConsentSelections(fields) {
 const read=fields.getAll("read_access");
 if(read.length!==1||read[0]!=="yes")
  return {ok:false,error:"Read access is required to connect."};
 const write=fields.getAll("write_access");
 if(write.length>1||(write.length===1&&write[0]!=="yes"))
  return {ok:false,error:"Invalid write permission selection."};
 const approve=fields.getAll("approve");
 if(approve.length!==1||approve[0]!=="yes")
  return {ok:false,error:"Consent not granted."};
 return {ok:true,writeApproved:write.length===1};
}
