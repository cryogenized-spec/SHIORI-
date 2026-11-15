// Keep OAuth resource authorization independent of the legacy Worker.
// Unknown tools fail closed: read-only grants cannot invoke them.
const READ_TOOLS=new Set([
 "shiori_system_capabilities_read","shiori_tasks_list","shiori_tasks_get",
 "shiori_tasks_dependencies_list","shiori_spatial_scene_read"
]);
export function requiredScopesForRpc(rpc){
 if(rpc?.method==="tools/call" && !READ_TOOLS.has(rpc?.params?.name))
  return ["mcp:read","mcp:write"];
 return ["mcp:read"];
}
export function normalizeGrantedScopes(scope){
 if(Array.isArray(scope))return scope.filter(s=>typeof s==="string");
 if(typeof scope==="string")return scope.split(/\s+/).filter(Boolean);
 return [];
}
export function hasRequiredScopes(scope,needed){
 const grants=new Set(normalizeGrantedScopes(scope));
 return needed.every(s=>grants.has(s));
}
