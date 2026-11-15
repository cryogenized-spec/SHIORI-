import test from "node:test";
import assert from "node:assert/strict";
import {requiredScopesForRpc,normalizeGrantedScopes,hasRequiredScopes} from "../scope-policy.js";

test("read methods retain mcp:read only",()=>{
 for(const method of ["initialize","ping","tools/list"]){
  assert.deepEqual(requiredScopesForRpc({method}),["mcp:read"]);
 }
 for(const name of ["shiori_tasks_list","shiori_system_capabilities_read","shiori_tasks_get",
                     "shiori_tasks_dependencies_list","shiori_spatial_scene_read"]){
  assert.deepEqual(requiredScopesForRpc({method:"tools/call",params:{name}}),["mcp:read"]);
 }
});

test("known writes and unknown tools both require mcp:write",()=>{
 for(const name of ["shiori_tasks_create","shiori_tasks_status_set",
                    "shiori_spatial_node_position_set","shiori_spatial_edge_style_set",
                    "shiori_not_implemented",undefined]){
  const needed=requiredScopesForRpc({method:"tools/call",params:{name}});
  assert.deepEqual(needed,["mcp:read","mcp:write"]);
  assert.equal(hasRequiredScopes(["mcp:read"],needed),false);
  assert.equal(hasRequiredScopes(["mcp:read","mcp:write"],needed),true);
 }
});

test("OAuth scopes are compared exactly, not as substrings",()=>{
 assert.equal(hasRequiredScopes("mcp:read mcp:write",["mcp:write"]),true);
 assert.equal(hasRequiredScopes("mcp:read mcp:write-other",["mcp:write"]),false);
 assert.equal(hasRequiredScopes(["mcp:read","mcp:write-extra"],["mcp:write"]),false);
 assert.deepEqual(normalizeGrantedScopes(null),[]);
 assert.deepEqual(normalizeGrantedScopes("mcp:read    mcp:write"),["mcp:read","mcp:write"]);
});
