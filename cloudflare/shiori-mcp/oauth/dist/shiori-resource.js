// node_modules/@cloudflare/workers-oauth-provider/dist/oauth-provider.js
import { WorkerEntrypoint } from "cloudflare:workers";
var OAUTH_SCOPE_TOKEN_PATTERN = /^[\x21\x23-\x5B\x5D-\x7E]+$/;
function isValidOAuthScopeToken(scopeToken) {
  return OAUTH_SCOPE_TOKEN_PATTERN.test(scopeToken);
}
var version = "1.2.4";
var OUTBOUND_USER_AGENT = `workers-oauth-provider/${version} (+https://github.com/cloudflare/workers-oauth-provider)`;
function withCorsHeaders(response, request) {
  const origin = request.headers.get("Origin");
  if (!origin) return response;
  const cors = new Response(response.body, response);
  const setUnlessPresent = (name, value) => {
    if (!cors.headers.has(name)) cors.headers.set(name, value);
  };
  setUnlessPresent("Access-Control-Allow-Origin", origin);
  setUnlessPresent("Access-Control-Allow-Methods", "*");
  setUnlessPresent("Access-Control-Allow-Headers", "Authorization, *");
  setUnlessPresent("Access-Control-Max-Age", "86400");
  appendHeaderValue(cors.headers, "Vary", "Origin");
  appendHeaderValue(cors.headers, "Access-Control-Expose-Headers", "WWW-Authenticate");
  appendHeaderValue(cors.headers, "Access-Control-Expose-Headers", "Retry-After");
  return cors;
}
function appendHeaderValue(headers, name, value) {
  const values = (headers.get(name) ?? "").split(",").map((item) => item.trim()).filter(Boolean);
  if (!values.some((item) => item.toLowerCase() === value.toLowerCase())) values.push(value);
  headers.set(name, values.join(", "));
}
function resolveRequiredScopes(requiredScopes, deprecatedScopesSupported) {
  if (requiredScopes !== void 0 && deprecatedScopesSupported !== void 0) throw new TypeError("Set requiredScopes only: resourceMetadata.scopes_supported is deprecated in its favour");
  const scopes = requiredScopes ?? deprecatedScopesSupported;
  return scopes === void 0 ? void 0 : [...scopes];
}
function baselineResourceScopes(scopes) {
  return [...new Set(scopes)].filter((scope) => scope !== "offline_access");
}
var OAuthError = class extends Error {
  constructor(code, options) {
    super(options.description);
    this.name = "OAuthError";
    this.code = code;
    this.options = {
      ...options,
      statusCode: options.statusCode ?? 400
    };
    this.description = this.options.description;
    this.statusCode = this.options.statusCode;
    this.headers = this.options.headers;
    this.requiredScopes = this.options.requiredScopes;
  }
};
var EMA_MAX_JWT_BYTES = 16 * 1024;
var EMA_JWKS_MAX_SIZE_BYTES = 64 * 1024;
var CLIENT_ASSERTION_MAX_BYTES = 16 * 1024;
function isLoopbackHostname(hostname) {
  const host = hostname.toLowerCase();
  if (host === "localhost" || host === "::1" || host === "[::1]") return true;
  const ipv4 = /^127\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  return ipv4 !== null && ipv4.slice(1).every((octet) => Number(octet) <= 255);
}
function hasAcceptedCanonicalScheme(url) {
  return url.protocol === "https:" || url.protocol === "http:" && isLoopbackHostname(url.hostname);
}
function validateResourceUri(uri) {
  if (!uri || typeof uri !== "string") return false;
  if (!/^[\x21-\x7e]+$/.test(uri) || /["\\#]/.test(uri) || !/^[A-Za-z][A-Za-z0-9+.-]*:\/\/[^/?#]+(?:\/[^?#]*)?(?:\?[^#]*)?$/.test(uri) || /%(?![0-9A-Fa-f]{2})/.test(uri) || !/^[A-Za-z0-9:/?@!$&'()*+,;=._~%\[\]-]+$/.test(uri)) return false;
  try {
    const parsed = new URL(uri);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}
function resourceMatches(requested, granted) {
  const foldedRequested = foldResourceSchemeAndHost(requested);
  const foldedGranted = foldResourceSchemeAndHost(granted);
  if (foldedRequested === void 0 || foldedGranted === void 0) return false;
  return normalizeEmptyPath(foldedRequested) === normalizeEmptyPath(foldedGranted);
}
function foldResourceSchemeAndHost(resource) {
  const schemeSeparator = resource.indexOf("://");
  if (schemeSeparator <= 0) return void 0;
  const authorityStart = schemeSeparator + 3;
  const authorityEndOffset = resource.slice(authorityStart).search(/[/?#]/);
  const authorityEnd = authorityEndOffset === -1 ? resource.length : authorityStart + authorityEndOffset;
  const authority = resource.slice(authorityStart, authorityEnd);
  const hostStart = authority.lastIndexOf("@") + 1;
  let hostEnd;
  if (authority[hostStart] === "[") {
    const closingBracket = authority.indexOf("]", hostStart + 1);
    if (closingBracket === -1) return void 0;
    hostEnd = closingBracket + 1;
  } else {
    const portSeparator = authority.indexOf(":", hostStart);
    hostEnd = portSeparator === -1 ? authority.length : portSeparator;
  }
  const asciiLower = (value) => value.replace(/[A-Z]/g, (character) => character.toLowerCase());
  return asciiLower(resource.slice(0, schemeSeparator)) + "://" + authority.slice(0, hostStart) + asciiLower(authority.slice(hostStart, hostEnd)) + authority.slice(hostEnd) + resource.slice(authorityEnd);
}
function normalizeEmptyPath(resource) {
  const authorityStart = resource.indexOf("://") + 3;
  const pathOffset = resource.slice(authorityStart).search(/[/?#]/);
  if (pathOffset === -1) return `${resource}/`;
  const pathStart = authorityStart + pathOffset;
  return resource[pathStart] === "/" ? resource : `${resource.slice(0, pathStart)}/${resource.slice(pathStart)}`;
}
function requestCarriesResourceQuery(requestUrl, resourceUrl) {
  for (const [name, value] of resourceUrl.searchParams) if (!requestUrl.searchParams.getAll(name).includes(value)) return false;
  return true;
}
var CIMD_MAX_SIZE_BYTES = 5 * 1024;
var CIMD_CACHE_MAX_TTL_SECONDS = 10080 * 60;
var PROTECTED_RESOURCE_WELL_KNOWN_PREFIX$1 = "/.well-known/oauth-protected-resource";
var NO_CACHE_HEADERS$1 = {
  "Cache-Control": "no-store",
  Pragma: "no-cache"
};
function insufficientScope(auth, scope, description) {
  if (!Array.isArray(scope) || scope.length === 0 || scope.some((value) => typeof value !== "string" || !isValidOAuthScopeToken(value))) throw new TypeError("insufficientScope requires at least one valid OAuth scope token");
  let challenge = `Bearer realm="OAuth", error="insufficient_scope", scope="${[...new Set(scope)].join(" ")}"`;
  challenge += `, resource_metadata="${getResourceMetadataUrl(auth.audience)}"`;
  if (description !== void 0) {
    const quotable = description.replace(/["\\]/g, "").replace(/[^\x21-\x7e]+/g, " ").trim();
    if (quotable) challenge += `, error_description="${quotable}"`;
  }
  return new Response(JSON.stringify({
    error: "insufficient_scope",
    ...description !== void 0 ? { error_description: description } : {}
  }), {
    status: 403,
    headers: {
      ...NO_CACHE_HEADERS$1,
      "Content-Type": "application/json",
      "WWW-Authenticate": challenge
    }
  });
}
var OAuthResourceServer = class {
  #options;
  #validated;
  constructor(options) {
    this.#validated = validateOptions(options);
    this.#options = options;
  }
  async fetch(request, env, ctx) {
    const options = this.#options;
    const validated = this.#validated;
    const url = new URL(request.url);
    if (isProtectedResourceMetadataPath(url)) {
      if (request.method === "OPTIONS") return withCorsHeaders(new Response(null, {
        status: 204,
        headers: { "Content-Length": "0" }
      }), request);
      if (!isMetadataUrlRequest(url, validated.metadataUrl)) return withCorsHeaders(new Response(null, { status: 404 }), request);
      if (request.method !== "GET" && request.method !== "HEAD") return withCorsHeaders(new Response(null, {
        status: 405,
        headers: { Allow: "GET, HEAD, OPTIONS" }
      }), request);
      const metadata = Response.json(validated.metadata, { headers: NO_CACHE_HEADERS$1 });
      return withCorsHeaders(request.method === "HEAD" ? new Response(null, {
        status: 200,
        headers: metadata.headers
      }) : metadata, request);
    }
    if (!isCanonicalResourceRequest(url, validated.resourceUrl)) return new Response(null, { status: 404 });
    if (request.method === "OPTIONS") return withCorsHeaders(new Response(null, {
      status: 204,
      headers: { "Content-Length": "0" }
    }), request);
    const token = parseBearerToken(request.headers.get("Authorization"));
    if (!token) return withCorsHeaders(createBearerChallenge(url, validated, false), request);
    let validation;
    try {
      validation = await options.validateToken(env, request)(validated.resource, token);
    } catch (error) {
      if (error instanceof OAuthError) return withCorsHeaders(createOAuthErrorResponse(error, url, validated), request);
      return withCorsHeaders(createValidationUnavailableResponse(), request);
    }
    if (!isValidTokenValidation(validation, validated.resource)) return withCorsHeaders(createBearerChallenge(url, validated, true), request);
    const context = ctx;
    context.props = validation.props;
    context.auth = {
      token,
      audience: validated.resource,
      ...validation.expiresAt !== void 0 ? { expiresAt: validation.expiresAt } : {},
      scope: [...validation.scope ?? []],
      ...validation.userId !== void 0 ? { userId: validation.userId } : {},
      ...validation.clientId !== void 0 ? { clientId: validation.clientId } : {}
    };
    const handler = options.handler;
    return withCorsHeaders(isEntrypointClass(handler) ? await new handler(context, env).fetch(request) : await handler.fetch(request, env, context), request);
  }
};
function validateOptions(options) {
  if (!options || typeof options !== "object") throw new TypeError("OAuth resource server options are required");
  if (!options.handler || !isEntrypointClass(options.handler) && typeof options.handler.fetch !== "function") throw new TypeError("handler must provide a fetch function or extend WorkerEntrypoint");
  if (typeof options.validateToken !== "function") throw new TypeError("validateToken must be a function");
  const resource = options.resourceMetadata?.resource;
  const resourceUrl = parseCanonicalUrl(resource);
  if (!resourceUrl) throw new TypeError("resourceMetadata.resource must be a canonical absolute HTTPS URI without a fragment (http is accepted only on a loopback host)");
  if (isProtectedResourceMetadataPath(resourceUrl)) throw new TypeError(`resourceMetadata.resource must not be inside the ${PROTECTED_RESOURCE_WELL_KNOWN_PREFIX$1} namespace`);
  const authorizationServers = options.resourceMetadata.authorization_servers;
  if (!Array.isArray(authorizationServers) || authorizationServers.length === 0) throw new TypeError("resourceMetadata.authorization_servers must contain at least one issuer");
  for (const issuer of authorizationServers) {
    const issuerUrl = parseCanonicalUrl(issuer);
    if (!issuerUrl || issuerUrl.search || issuerUrl.hash) throw new TypeError("resourceMetadata.authorization_servers must contain canonical HTTPS issuer URLs (http is accepted only on a loopback host)");
  }
  const bearerMethods = options.resourceMetadata.bearer_methods_supported;
  if (bearerMethods !== void 0 && (bearerMethods.length !== 1 || bearerMethods[0] !== "header")) throw new TypeError("resourceMetadata.bearer_methods_supported only supports 'header'");
  const configuredScopes = resolveRequiredScopes(options.requiredScopes, options.resourceMetadata.scopes_supported) ?? [];
  if (configuredScopes.some((scope) => typeof scope !== "string" || !isValidOAuthScopeToken(scope))) throw new TypeError("requiredScopes (or the deprecated resourceMetadata.scopes_supported) must contain valid OAuth scope tokens");
  const resourceScopes = baselineResourceScopes(configuredScopes);
  return {
    resource,
    resourceUrl,
    metadataUrl: new URL(getResourceMetadataUrl(resource)),
    metadata: {
      resource,
      authorization_servers: [...authorizationServers],
      ...resourceScopes.length ? { scopes_supported: resourceScopes } : {},
      bearer_methods_supported: bearerMethods ? [...bearerMethods] : ["header"],
      ...options.resourceMetadata.resource_name !== void 0 ? { resource_name: options.resourceMetadata.resource_name } : {}
    }
  };
}
function parseCanonicalUrl(value) {
  if (typeof value !== "string" || !validateResourceUri(value)) return null;
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  if (!hasAcceptedCanonicalScheme(parsed) || parsed.username || parsed.password || parsed.protocol !== parsed.protocol.toLowerCase() || parsed.hostname !== parsed.hostname.toLowerCase()) return null;
  if (parsed.href !== value && parsed.origin !== value) return null;
  return parsed;
}
function getResourceMetadataUrl(resource) {
  const parsed = new URL(resource);
  const suffix = parsed.pathname === "/" ? "" : parsed.pathname;
  return `${parsed.origin}${PROTECTED_RESOURCE_WELL_KNOWN_PREFIX$1}${suffix}${parsed.search}`;
}
function isEntrypointClass(handler) {
  return typeof handler === "function" && handler.prototype instanceof WorkerEntrypoint;
}
function isProtectedResourceMetadataPath(url) {
  return url.pathname === PROTECTED_RESOURCE_WELL_KNOWN_PREFIX$1 || url.pathname.startsWith(`${PROTECTED_RESOURCE_WELL_KNOWN_PREFIX$1}/`);
}
function isMetadataUrlRequest(requestUrl, metadataUrl) {
  return requestUrl.origin === metadataUrl.origin && requestUrl.pathname === metadataUrl.pathname && requestCarriesResourceQuery(requestUrl, metadataUrl);
}
function isCanonicalResourceRequest(requestUrl, resourceUrl) {
  if (requestUrl.origin !== resourceUrl.origin) return false;
  if (!requestCarriesResourceQuery(requestUrl, resourceUrl)) return false;
  const resourcePath = resourceUrl.pathname;
  if (requestUrl.pathname === resourcePath) return true;
  if (resourcePath === "/") return requestUrl.pathname.startsWith("/");
  const descendantPrefix = resourcePath.endsWith("/") ? resourcePath : `${resourcePath}/`;
  return requestUrl.pathname.startsWith(descendantPrefix);
}
function parseBearerToken(authorization) {
  if (!authorization) return null;
  return /^Bearer[\t ]+([^\s,]+)$/i.exec(authorization)?.[1] || null;
}
function isValidTokenValidation(validation, canonicalResource) {
  if (!validation || typeof validation !== "object") return false;
  if (typeof validation.audience !== "string" || !resourceMatches(validation.audience, canonicalResource)) return false;
  if (!Object.prototype.hasOwnProperty.call(validation, "props")) return false;
  if (validation.expiresAt !== void 0) {
    if (typeof validation.expiresAt !== "number" || !Number.isFinite(validation.expiresAt)) return false;
    if (validation.expiresAt <= Date.now() / 1e3) return false;
  }
  if (validation.scope !== void 0) {
    if (!Array.isArray(validation.scope)) return false;
    if (validation.scope.some((scope) => typeof scope !== "string" || !isValidOAuthScopeToken(scope))) return false;
  }
  if (validation.userId !== void 0 && typeof validation.userId !== "string") return false;
  if (validation.clientId !== void 0 && typeof validation.clientId !== "string") return false;
  return true;
}
function createBearerChallenge(requestUrl, validated, invalidToken) {
  let challenge = 'Bearer realm="OAuth"';
  if (isCanonicalResourceRequest(requestUrl, validated.resourceUrl)) challenge += `, resource_metadata="${validated.metadataUrl.href}"`;
  if (invalidToken) challenge += ', error="invalid_token"';
  const scopes = validated.metadata.scopes_supported;
  if (scopes && scopes.length > 0) challenge += `, scope="${scopes.join(" ")}"`;
  return new Response(null, {
    status: 401,
    headers: {
      ...NO_CACHE_HEADERS$1,
      "WWW-Authenticate": challenge
    }
  });
}
function createOAuthErrorResponse(error, requestUrl, validated) {
  const headers = {
    ...NO_CACHE_HEADERS$1,
    "Content-Type": "application/json",
    ...error.headers
  };
  const hasChallenge = Object.keys(headers).some((name) => name.toLowerCase() === "www-authenticate");
  let status = error.statusCode;
  if (error.code === "invalid_token") {
    status = 401;
    if (!hasChallenge) headers["WWW-Authenticate"] = createBearerChallenge(requestUrl, validated, true).headers.get("WWW-Authenticate");
  } else if (error.code === "insufficient_scope") {
    status = 403;
    if (!hasChallenge) {
      const scopes = [...new Set(error.requiredScopes ?? validated.metadata.scopes_supported ?? [])];
      if (scopes.some((scope) => typeof scope !== "string" || !isValidOAuthScopeToken(scope))) return createValidationUnavailableResponse();
      headers["WWW-Authenticate"] = 'Bearer realm="OAuth", error="insufficient_scope"' + (scopes.length > 0 ? `, scope="${scopes.join(" ")}"` : "") + `, resource_metadata="${validated.metadataUrl.href}"`;
    }
  }
  return new Response(JSON.stringify({
    error: error.code,
    error_description: error.description
  }), {
    status,
    headers
  });
}
function createValidationUnavailableResponse() {
  return new Response(null, {
    status: 503,
    headers: NO_CACHE_HEADERS$1
  });
}
var DEFAULT_REMEMBER_SECONDS = 720 * 60 * 60;
if (!(typeof Cloudflare !== "undefined" && Cloudflare.compatibilityFlags?.global_fetch_strictly_public === true)) console.warn(`CIMD (Client ID Metadata Document) is disabled: add '"compatibility_flags": ["global_fetch_strictly_public"]' to your wrangler.jsonc to enable. See: https://developers.cloudflare.com/workers/configuration/compatibility-flags/#global-fetch-strictly-public`);
var DEFAULT_REFRESH_TOKEN_TTL = 720 * 60 * 60;
var DEFAULT_CLIENT_REGISTRATION_TTL = 2160 * 60 * 60;
var TOKEN_LENGTH = 32;
var ISSUED_TOKEN_SECRET_PATTERN = /* @__PURE__ */ new RegExp(`^[A-Za-z0-9_-]{${TOKEN_LENGTH}}$`);
var WRAPPING_KEY_HMAC_KEY = new Uint8Array([
  34,
  126,
  38,
  134,
  141,
  241,
  225,
  109,
  128,
  112,
  234,
  23,
  151,
  91,
  71,
  166,
  130,
  24,
  250,
  135,
  40,
  174,
  222,
  133,
  181,
  29,
  74,
  217,
  150,
  202,
  202,
  67
]);

// ../src/worker.js
var SERVER = "shiori-mcp-cloudflare";
var VERSION = "0.1.0-alpha";
var PROTOCOL = "2025-06-18";
var MAX_BODY = 32768;
var MAX_LIMIT = 100;
var allowedStatuses = /* @__PURE__ */ new Set(["todo", "in_progress", "done"]);
var allowedStyles = /* @__PURE__ */ new Set(["circuit", "curved", "straight"]);
var W = () => ({ type: "string", minLength: 1, maxLength: 128 });
var S = (max = 160) => ({ type: "string", minLength: 1, maxLength: max });
var I = (max) => ({ type: "integer", minimum: 0, ...max ? { maximum: max } : {} });
var F = { workspace_id: W(), task_id: S(), node_id: S(), title: S(), text: { type: "string", maxLength: 32768 }, status: { enum: ["todo", "in_progress", "done"] }, style: { enum: ["circuit", "curved", "straight"] }, idempotency_key: { type: "string", minLength: 8, maxLength: 128 }, expected_revision: I(), limit: { type: "integer", minimum: 1, maximum: 100 }, cursor: { type: "string", maxLength: 64 }, x: { type: "number", minimum: -1e6, maximum: 1e6 }, y: { type: "number", minimum: -1e6, maximum: 1e6 } };
var op = (id, fields, required = [], description = "", write = false) => ({
  id,
  name: "shiori_" + id.replaceAll(".", "_"),
  description,
  inputSchema: {
    type: "object",
    additionalProperties: false,
    required: ["workspace_id", ...required, ...write ? ["idempotency_key"] : []],
    properties: Object.fromEntries(["workspace_id", ...fields, ...write ? ["idempotency_key"] : []].map((k) => [k, F[k]]))
  }
});
var OPERATIONS = [
  op("system.capabilities.read", [], [], "Read actual deployed capabilities and isolation status"),
  op("tasks.list", ["cursor", "limit"], [], "List tasks in this isolated Cloudflare workspace"),
  op("tasks.get", ["task_id"], ["task_id"], "Read one task from the remote D1 workspace"),
  op("tasks.create", ["title", "text"], ["title"], "Create remote-only task (local Rust sync not enabled)", true),
  op("tasks.status.set", ["task_id", "status", "expected_revision"], ["task_id", "status", "expected_revision"], "Update remote task status with revision guard", true),
  op("tasks.dependencies.list", ["task_id"], ["task_id"], "Read remote task prerequisite links"),
  op("spatial.scene.read", ["limit", "cursor"], [], "Read remote spatial task scene (not local Rust SQLite)"),
  op("spatial.node.position.set", ["node_id", "x", "y", "expected_revision"], ["node_id", "x", "y", "expected_revision"], "Persist visual-only node position in remote D1", true),
  op("spatial.edge.style.set", ["style", "expected_revision"], ["style", "expected_revision"], "Persist visual-only connector style", true)
];
var BY_ID = new Map(OPERATIONS.map((o) => [o.id, o]));
var BY_TOOL = new Map(OPERATIONS.map((o) => [o.name, o]));
var ServiceError = class extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
};
var E = (status, code, msg) => {
  throw new ServiceError(status, code, msg);
};
var json = (o, status = 200, headers = {}) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff", ...headers } });
var field = (v, k, required = false) => {
  if (required && v[k] === void 0) E(400, "VALIDATION_FAILED", k + " is required");
};
var object = (o) => o !== null && typeof o === "object" && !Array.isArray(o);
function validate(def, args, env) {
  if (!object(args)) E(400, "VALIDATION_FAILED", "Arguments must be a JSON object");
  const schema = def.inputSchema;
  for (const k of Object.keys(args)) if (!Object.hasOwn(schema.properties, k)) E(400, "VALIDATION_FAILED", "Unknown field: " + k);
  for (const k of schema.required) field(args, k, true);
  for (const [k, v] of Object.entries(args)) {
    const p = schema.properties[k];
    if (p.enum && !p.enum.includes(v)) E(400, "VALIDATION_FAILED", "Invalid " + k);
    if (p.type === "string" && (typeof v !== "string" || v.length > (p.maxLength ?? 99999) || v.length < (p.minLength ?? 0))) E(400, "VALIDATION_FAILED", "Invalid " + k);
    if (p.type === "integer" && (!Number.isSafeInteger(v) || v < (p.minimum ?? -Infinity) || v > (p.maximum ?? Infinity))) E(400, "VALIDATION_FAILED", "Invalid " + k);
    if (p.type === "number" && (typeof v !== "number" || !Number.isFinite(v) || v < (p.minimum ?? -Infinity) || v > (p.maximum ?? Infinity))) E(400, "VALIDATION_FAILED", "Invalid " + k);
  }
  if (args.workspace_id !== (env.WORKSPACE_ID || "personal")) E(403, "FORBIDDEN", "Workspace not granted by this credential");
  return args;
}
async function readRequest(request) {
  if (Number(request.headers.get("content-length") || 0) > MAX_BODY) E(413, "VALIDATION_FAILED", "Payload too large");
  const raw = await request.text();
  if (raw.length > MAX_BODY) E(413, "VALIDATION_FAILED", "Payload too large");
  try {
    return JSON.parse(raw);
  } catch {
    E(400, "VALIDATION_FAILED", "Invalid JSON");
  }
}
async function sha256(s) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
}
async function safeEqual(a, b) {
  const aa = await sha256(a), bb = await sha256(b);
  let x = 0;
  for (let i = 0; i < aa.length; i++) x |= aa[i] ^ bb[i];
  return x === 0 && a.length === b.length;
}
async function authenticate(request, env) {
  if (!env.SHIO_AUTH_TOKEN || !env.DB) E(503, "UNAVAILABLE", "Shiori auth/database bindings not configured");
  const auth = request.headers.get("authorization") || "";
  if (!auth.startsWith("Bearer ") || auth.length > 240) E(401, "UNAUTHENTICATED", "Bearer token required");
  if (!await safeEqual(auth.slice(7), env.SHIO_AUTH_TOKEN)) E(401, "UNAUTHENTICATED", "Invalid token");
  const origin = request.headers.get("origin");
  if (origin && new URL(origin).host !== new URL(request.url).host) E(403, "FORBIDDEN", "Cross-origin browser writes disabled");
}
async function rateLimit(db) {
  const window = Math.floor(Date.now() / 6e4);
  await db.prepare("INSERT INTO access_limits(bucket,window_min,count) VALUES('owner',?,1) ON CONFLICT(bucket,window_min) DO UPDATE SET count=count+1").bind(window).run();
  const row = await db.prepare("SELECT count FROM access_limits WHERE bucket='owner' AND window_min=?").bind(window).first();
  if (row.count > 90) E(429, "RATE_LIMITED", "Temporary request limit reached");
}
function listParams(v) {
  let n = Number.parseInt(v.cursor || "0", 10);
  if (!Number.isSafeInteger(n) || n < 0 || n > 1e5) E(400, "VALIDATION_FAILED", "Invalid cursor");
  return { offset: n, limit: Math.min(v.limit || 50, MAX_LIMIT) };
}
function formatTask(row) {
  return { id: row.id, title: row.title, body: row.notes, project: row.project, status: row.status, priority: row.priority, version: row.version, created_at: row.created_at, updated_at: row.updated_at, origin: "cloudflare-d1-remote-alpha" };
}
async function getTask(db, w, id) {
  const row = await db.prepare("SELECT * FROM remote_tasks WHERE workspace_id=? AND id=? AND deleted_at IS NULL").bind(w, id).first();
  if (!row) E(404, "NOT_FOUND", "Task not found in remote workspace");
  return row;
}
async function duplicate(db, w, id, key) {
  const row = await db.prepare("SELECT result_json FROM idempotency WHERE workspace_id=? AND operation_id=? AND token=?").bind(w, id, key).first();
  return row ? JSON.parse(row.result_json) : null;
}
function idemp(db, w, id, key, result) {
  return db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) VALUES(?,?,?,?,?)").bind(w, id, key, JSON.stringify(result), (/* @__PURE__ */ new Date()).toISOString());
}
async function writeOnce(env, w, id, key, result, statement) {
  const saved = await duplicate(env.DB, w, id, key);
  if (saved) return saved;
  try {
    await env.DB.batch([statement, idemp(env.DB, w, id, key, result)]);
  } catch (err) {
    const after = await duplicate(env.DB, w, id, key);
    if (after) return after;
    throw err;
  }
  return result;
}
async function run(id, arg, env) {
  const def = BY_ID.get(id);
  if (!def) E(404, "UNSUPPORTED_CAPABILITY", "Operation not deployed");
  const a = validate(def, arg, env), db = env.DB, w = a.workspace_id;
  if (id === "system.capabilities.read") return { capabilities: { server: SERVER, version: VERSION, workspace_id: w, backend: "isolated-cloudflare-d1", local_rust_sync: false, oauth: false, authentication: "single-user-bearer", planned_total: 113 }, operations: OPERATIONS.map((o) => o.id) };
  if (id === "tasks.list") {
    const { offset, limit } = listParams(a);
    const rows = await db.prepare("SELECT * FROM remote_tasks WHERE workspace_id=? AND deleted_at IS NULL ORDER BY created_at DESC,id LIMIT ? OFFSET ?").bind(w, limit, offset).all();
    const items = rows.results.map(formatTask);
    return { items, next_cursor: items.length === limit ? String(offset + limit) : null };
  }
  if (id === "tasks.get") return { item: formatTask(await getTask(db, w, a.task_id)) };
  if (id === "tasks.create") {
    let cached = await duplicate(db, w, id, a.idempotency_key);
    if (cached) return cached;
    if (a.title.trim().length === 0 || a.title.length > 160) E(400, "VALIDATION_FAILED", "Title must contain 1\u2013160 characters");
    const taskId = crypto.randomUUID(), now = (/* @__PURE__ */ new Date()).toISOString();
    const task = { id: taskId, title: a.title.trim(), body: a.text || "", project: "Remote alpha", status: "todo", priority: "medium", version: 1, created_at: now, updated_at: now, origin: "cloudflare-d1-remote-alpha" };
    const result = { changed: true, resource_id: taskId, revision: 1 };
    return writeOnce(env, w, id, a.idempotency_key, result, db.prepare("INSERT INTO remote_tasks(id,workspace_id,title,notes,project,status,priority,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)").bind(taskId, w, task.title, task.body, task.project, task.status, task.priority, 1, now, now));
  }
  if (id === "tasks.status.set") {
    const cached = await duplicate(db, w, id, a.idempotency_key);
    if (cached) return cached;
    const current = await getTask(db, w, a.task_id);
    if (current.version !== a.expected_revision) E(409, "CONFLICT", "Task revision has changed");
    if (!allowedStatuses.has(a.status)) E(400, "VALIDATION_FAILED", "Invalid status");
    const result = { changed: true, resource_id: a.task_id, revision: a.expected_revision + 1 };
    const now = (/* @__PURE__ */ new Date()).toISOString();
    const updates = await db.batch([
      db.prepare("UPDATE remote_tasks SET status=?,version=version+1,updated_at=? WHERE workspace_id=? AND id=? AND version=? AND deleted_at IS NULL").bind(a.status, now, w, a.task_id, a.expected_revision),
      db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) SELECT ?,?,?,?,? WHERE changes()=1").bind(w, id, a.idempotency_key, JSON.stringify(result), now)
    ]);
    if (updates[0].meta.changes !== 1) {
      const again = await duplicate(db, w, id, a.idempotency_key);
      if (again) return again;
      E(409, "CONFLICT", "Task was modified concurrently");
    }
    return result;
  }
  if (id === "tasks.dependencies.list") {
    await getTask(db, w, a.task_id);
    const rows = await db.prepare("SELECT depends_on_id FROM remote_dependencies WHERE workspace_id=? AND task_id=? ORDER BY depends_on_id").bind(w, a.task_id).all();
    return { items: rows.results.map((x) => ({ task_id: a.task_id, depends_on_id: x.depends_on_id })) };
  }
  if (id === "spatial.scene.read") {
    const { offset, limit } = listParams(a);
    const rows = (await db.prepare("SELECT t.*,p.x,p.y,p.revision AS position_revision FROM remote_tasks t LEFT JOIN remote_positions p ON p.workspace_id=t.workspace_id AND p.node_id=t.id WHERE t.workspace_id=? AND t.deleted_at IS NULL ORDER BY t.created_at DESC,t.id LIMIT ? OFFSET ?").bind(w, limit, offset).all()).results;
    const nodes = rows.map((x, i) => ({ ...formatTask(x), kind: "task", x: x.x ?? 120 + i % 4 * 300, y: x.y ?? 140 + Math.floor(i / 4) * 170, position_revision: x.position_revision ?? 0 }));
    const ids = new Set(nodes.map((x) => x.id));
    const deps = (await db.prepare("SELECT task_id,depends_on_id FROM remote_dependencies WHERE workspace_id=?").bind(w).all()).results;
    const edges = deps.filter((x) => ids.has(x.task_id) && ids.has(x.depends_on_id)).map((x) => ({ from: x.depends_on_id, to: x.task_id, kind: "blocks" }));
    const style = await db.prepare("SELECT value,revision FROM remote_settings WHERE workspace_id=? AND key='connector_style'").bind(w).first();
    return { scene: { nodes, edges, connector_style: style?.value || "circuit", layout_revision: style?.revision || 0, origin: "cloudflare-d1-remote-alpha", synchronized_with_local_rust: false }, next_cursor: nodes.length === limit ? String(offset + limit) : null };
  }
  if (id === "spatial.node.position.set") {
    const cached = await duplicate(db, w, id, a.idempotency_key);
    if (cached) return cached;
    await getTask(db, w, a.node_id);
    const old = await db.prepare("SELECT revision FROM remote_positions WHERE workspace_id=? AND node_id=?").bind(w, a.node_id).first();
    if ((old?.revision || 0) !== a.expected_revision) E(409, "CONFLICT", "Visual position revision changed");
    const revision = a.expected_revision + 1;
    const update = old ? db.prepare("UPDATE remote_positions SET x=?,y=?,revision=revision+1 WHERE workspace_id=? AND node_id=? AND revision=?").bind(a.x, a.y, w, a.node_id, a.expected_revision) : db.prepare("INSERT INTO remote_positions(workspace_id,node_id,x,y,revision) VALUES(?,?,?,?,1)").bind(w, a.node_id, a.x, a.y);
    const result = { position: { node_id: a.node_id, x: a.x, y: a.y, revision } };
    try {
      const out = await db.batch([
        update,
        db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) SELECT ?,?,?,?,? WHERE changes()=1").bind(w, id, a.idempotency_key, JSON.stringify(result), (/* @__PURE__ */ new Date()).toISOString())
      ]);
      if (out[0].meta.changes !== 1) E(409, "CONFLICT", "Visual position changed concurrently");
    } catch (err) {
      const again = await duplicate(db, w, id, a.idempotency_key);
      if (again) return again;
      throw err;
    }
    return result;
  }
  if (id === "spatial.edge.style.set") {
    const cached = await duplicate(db, w, id, a.idempotency_key);
    if (cached) return cached;
    if (!allowedStyles.has(a.style)) E(400, "VALIDATION_FAILED", "Invalid connector style");
    const current = await db.prepare("SELECT revision FROM remote_settings WHERE workspace_id=? AND key='connector_style'").bind(w).first();
    if ((current?.revision || 0) !== a.expected_revision) E(409, "CONFLICT", "Connector style revision changed");
    const result = { changed: true, resource_id: "connector_style", revision: a.expected_revision + 1, style: a.style };
    const update = current ? db.prepare("UPDATE remote_settings SET value=?,revision=revision+1 WHERE workspace_id=? AND key='connector_style' AND revision=?").bind(a.style, w, a.expected_revision) : db.prepare("INSERT INTO remote_settings(workspace_id,key,value,revision) VALUES(?,'connector_style',?,1)").bind(w, a.style);
    try {
      const out = await db.batch([update, db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) SELECT ?,?,?,?,? WHERE changes()=1").bind(w, id, a.idempotency_key, JSON.stringify(result), (/* @__PURE__ */ new Date()).toISOString())]);
      if (out[0].meta.changes !== 1) E(409, "CONFLICT", "Connector style changed concurrently");
    } catch (err) {
      const again = await duplicate(db, w, id, a.idempotency_key);
      if (again) return again;
      throw err;
    }
    return result;
  }
  E(404, "UNSUPPORTED_CAPABILITY", "Operation not implemented");
}
async function mcp(body, env) {
  if (!object(body) || body.jsonrpc !== "2.0" || Array.isArray(body)) return { jsonrpc: "2.0", id: body?.id ?? null, error: { code: -32600, message: "Invalid JSON-RPC request" } };
  if (body.id === void 0) {
    return null;
  }
  const id = body.id;
  try {
    if (body.method === "initialize") return { jsonrpc: "2.0", id, result: { protocolVersion: PROTOCOL, capabilities: { tools: { listChanged: false } }, serverInfo: { name: SERVER, version: VERSION } } };
    if (body.method === "ping") return { jsonrpc: "2.0", id, result: {} };
    if (body.method === "tools/list") return { jsonrpc: "2.0", id, result: { tools: OPERATIONS.map((o) => ({ name: o.name, description: o.description, inputSchema: o.inputSchema })) } };
    if (body.method === "tools/call") {
      const tool = BY_TOOL.get(body.params?.name);
      if (!tool) return { jsonrpc: "2.0", id, error: { code: -32602, message: "Unknown MCP tool" } };
      try {
        const data = await run(tool.id, body.params?.arguments || {}, env);
        return { jsonrpc: "2.0", id, result: { content: [{ type: "text", text: JSON.stringify(data) }], structuredContent: data } };
      } catch (err) {
        const msg = err instanceof ServiceError ? err.message : "Operation failed";
        return { jsonrpc: "2.0", id, result: { isError: true, content: [{ type: "text", text: JSON.stringify({ error: err.code || "INTERNAL_ERROR", message: msg }) }] } };
      }
    }
    return { jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } };
  } catch {
    return { jsonrpc: "2.0", id, error: { code: -32603, message: "Internal error" } };
  }
}
async function handle(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/health") return json({ service: SERVER, version: VERSION, service_state: env.SHIO_AUTH_TOKEN && env.DB ? "ready" : "unconfigured", source: "isolated-cloudflare-d1", local_sync: false });
  if (url.pathname !== "/mcp" && !url.pathname.startsWith("/api/v1/ops/")) return json({ error: "NOT_FOUND" }, 404);
  if (request.method !== "POST") return json({ error: "METHOD_NOT_ALLOWED" }, 405, { "allow": "POST" });
  await authenticate(request, env);
  await rateLimit(env.DB);
  const body = await readRequest(request);
  if (url.pathname === "/mcp") {
    const response = await mcp(body, env);
    return response ? json(response) : new Response(null, { status: 202, headers: { "cache-control": "no-store" } });
  }
  const name = url.pathname.slice("/api/v1/ops/".length);
  const data = await run(name, body, env);
  return json({ ok: true, operation_id: name, data });
}
var worker_default = { async fetch(request, env) {
  try {
    return await handle(request, env);
  } catch (err) {
    const known = err instanceof ServiceError;
    return json({ ok: false, error: { code: known ? err.code : "INTERNAL_ERROR", message: known ? err.message : "Internal service error", retryable: known && err.status >= 500 } }, known ? err.status : 500, known && err.status === 401 ? { "www-authenticate": 'Bearer realm="Shiori"' } : {});
  }
} };

// resource-server.js
var ENDPOINT = "https://shiori-mcp-oauth.cryogenized.workers.dev/mcp";
var ISSUER = "https://shiori-auth.cryogenized.workers.dev";
var readOnly = /* @__PURE__ */ new Set([
  "shiori_system_capabilities_read",
  "shiori_tasks_list",
  "shiori_tasks_get",
  "shiori_tasks_dependencies_list",
  "shiori_spatial_scene_read"
]);
var isWrite = (id) => !readOnly.has(id);
var oauthResource = new OAuthResourceServer({
  resourceMetadata: {
    resource: ENDPOINT,
    authorization_servers: [ISSUER],
    resource_name: "Shiori MCP"
  },
  requiredScopes: ["mcp:read"],
  validateToken: (env) => env.AUTH_SERVER.validateToken,
  handler: {
    async fetch(request, env, ctx) {
      if (ctx.props?.userId !== "shiori-owner") return new Response("Forbidden", { status: 403 });
      const u = new URL(request.url), isMcp = u.pathname === "/mcp";
      if (!isMcp) return new Response("Not found", { status: 404 });
      let needed = ["mcp:read"];
      if (isMcp && request.method === "POST") {
        let rpc;
        try {
          rpc = await request.clone().json();
        } catch {
          return new Response("Invalid JSON", { status: 400 });
        }
        if (rpc?.method === "tools/call" && isWrite(rpc?.params?.name)) needed = ["mcp:read", "mcp:write"];
      }
      if (!needed.every((s) => ctx.auth.scope.includes(s))) return insufficientScope(ctx.auth, needed);
      if (!env.DB) return new Response("Shiori backend unconfigured", { status: 503 });
      const internalKey = crypto.randomUUID() + crypto.randomUUID();
      const internalEnv = { ...env, SHIO_AUTH_TOKEN: internalKey };
      const h = new Headers(request.headers);
      h.set("authorization", "Bearer " + internalKey);
      h.delete("cookie");
      h.delete("origin");
      return worker_default.fetch(new Request(request, { headers: h }), internalEnv);
    }
  }
});
var resource_server_default = {
  async fetch(request, env, ctx) {
    if (new URL(request.url).pathname === "/health" && request.method === "GET") {
      return Response.json({
        service: "shiori-mcp-oauth",
        oauth: "configured",
        cloud_dataset: "isolated-d1",
        local_rust_sync: false
      }, { headers: { "cache-control": "no-store" } });
    }
    return oauthResource.fetch(request, env, ctx);
  }
};
export {
  resource_server_default as default
};
