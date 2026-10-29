-- Object encoding and authenticated RPC adapted from ET-sec/resolve-console-bridge.
-- Copyright (c) 2026 Emmanuel Tigoue. MIT license: see LICENSE in this folder.
-- Host file transport and operation leases are maintained by Resolve AI Bridge.
local json=require("json_raw")
local sha=require("sha256")
local M={MAX_HANDLES=4096,DEFAULT_MAX_ITEMS=2000,PROTOCOL_VERSION="1.0",SURFACE_VERSION="1.0",VERSION="1.14.0"}
local OS_NAME=(jit and jit.os) or "Unknown"
local ROOT_NAMES={resolve=true,project_manager=true,project=true,media_pool=true,current_timeline=true}
local OperationError={}
local function op_error(code,message,details) return setmetatable({code=code,message=message,details=details},OperationError) end
local function is_op_error(e) return type(e)=="table" and getmetatable(e)==OperationError end
-- object model helpers

local function is_object(v)
  local tv = type(v)
  if tv == "userdata" then return true end
  if tv == "table" then
    local mt = getmetatable(v)
    return mt ~= nil and mt.__resolve_object == true
  end
  return false
end

local function type_name(obj)
  local ok, s = pcall(tostring, obj)
  if ok and type(s) == "string" then
    local name = s:match("^([%w_]+)")
    if name and name ~= "userdata" and name ~= "table" then return name end
  end
  return "Object"
end

local function member(obj, name)
  local ok, v = pcall(function() return obj[name] end)
  if ok then return v end
  return nil
end

local function invoke(obj, name, args, n)
  local fn = member(obj, name)
  if type(fn) ~= "function" then
    return nil, op_error("capability_unavailable", type_name(obj) .. " has no callable '" .. name .. "' in this Resolve build")
  end
  local packed = { pcall(fn, obj, unpack(args, 1, n or #args)) }
  if not packed[1] then
    return nil, op_error("resolve_raised", "Resolve raised while running " .. name .. ": " .. tostring(packed[2]):sub(1, 200))
  end
  return packed[2], nil, packed.n
end

local function call_ok(obj, name, ...)
  local v, err = invoke(obj, name, { ... }, select("#", ...))
  if err then error(err, 0) end
  return v
end

-- operations

local Ops = {}
Ops.__index = Ops

function M.new_ops(resolve, config, lifecycle)
  local self = setmetatable({}, Ops)
  self.resolve = resolve
  self.config = config
  self.lifecycle = lifecycle
  self.max_items = M.DEFAULT_MAX_ITEMS
  self.handles = {}
  self.object_handles = {}
  self.handle_order = {}
  self.handle_count = 0
  self.handle_counter = 0
  math.randomseed(os.time() + math.floor((os.clock() % 1) * 1000000))
  self.session = (bmd and bmd.createuuid and bmd.createuuid()) or
    string.format("%08x%08x", math.random(0, 0x7fffffff), math.random(0, 0x7fffffff))
  self.truncation = {}
  return self
end

function Ops:project_manager()
  local pm = call_ok(self.resolve, "GetProjectManager")
  if pm == nil then error(op_error("resolve_not_ready", "Resolve has no project manager yet"), 0) end
  return pm
end

function Ops:project()
  local p = call_ok(self:project_manager(), "GetCurrentProject")
  if p == nil then error(op_error("no_project", "no Resolve project is currently open"), 0) end
  return p
end

function Ops:timeline(arguments)
  local project = self:project()
  local name = arguments.timeline_name
  if name == nil or name == json.null or name == "" then
    local tl = call_ok(project, "GetCurrentTimeline")
    if tl == nil then error(op_error("no_timeline", "no current timeline is selected"), 0) end
    return tl
  end
  local matches = {}
  local count = tonumber(call_ok(project, "GetTimelineCount")) or 0
  for i = 1, count do
    local c = call_ok(project, "GetTimelineByIndex", i)
    if c ~= nil and call_ok(c, "GetName") == name then matches[#matches + 1] = c end
  end
  if #matches == 0 then error(op_error("not_found", "timeline '" .. tostring(name) .. "' was not found"), 0) end
  if #matches > 1 then error(op_error("ambiguous_locator", "more than one timeline is named '" .. tostring(name) .. "'"), 0) end
  return matches[1]
end

-- handles

function Ops:mint(obj, shape)
  local key = tostring(obj)
  local existing = self.object_handles[key]
  if existing and self.handles[existing] then return existing end
  self.handle_counter = self.handle_counter + 1
  local h = string.format("h:%s:%d", self.session, self.handle_counter)
  self.handles[h] = { obj = obj, shape = shape or "?" }
  self.object_handles[key] = h
  self.handle_order[#self.handle_order + 1] = h
  self.handle_count = self.handle_count + 1
  while self.handle_count > M.MAX_HANDLES do
    local oldest = table.remove(self.handle_order, 1)
    if self.handles[oldest] then self.handles[oldest] = nil; self.handle_count = self.handle_count - 1 end
  end
  return h
end

function Ops:shape_of(target)
  if type(target) == "string" and ROOT_NAMES[target] then return target end
  local e = type(target) == "string" and self.handles[target] or nil
  return e and e.shape or "?"
end

function Ops:named_root(name)
  if name == "resolve" then return self.resolve end
  local pm = self:project_manager()
  if name == "project_manager" then return pm end
  local project = call_ok(pm, "GetCurrentProject")
  if project == nil then error(op_error("no_project", "no Resolve project is currently open"), 0) end
  if name == "project" then return project end
  if name == "media_pool" then return call_ok(project, "GetMediaPool") end
  if name == "current_timeline" then
    local tl = call_ok(project, "GetCurrentTimeline")
    if tl == nil then error(op_error("no_timeline", "no current timeline is selected"), 0) end
    return tl
  end
  error(op_error("invalid_arguments", "unknown root object '" .. tostring(name) .. "'"), 0)
end

function Ops:resolve_target(target)
  if type(target) ~= "string" or target == "" then
    error(op_error("invalid_arguments", "target must be a root name or a bridge handle"), 0)
  end
  if ROOT_NAMES[target] then return self:named_root(target) end
  if target:sub(1, 2) == "h:" then
    local e = self.handles[target]
    if e then return e.obj end
    error(op_error("stale_handle", "that handle is no longer held by the bridge; re-fetch the object and retry",
      { hint = "handles are session-scoped and bounded; a restart or heavy enumeration evicts them" }), 0)
  end
  error(op_error("invalid_arguments", "target must be one of resolve, project_manager, project, media_pool, current_timeline or a bridge-issued handle"), 0)
end

-- value encoding: Resolve return value -> JSON-safe, minting handles for live objects

-- Resolve's Lua tables carry a "__flags" bookkeeping key; it is not data and must not leak or
-- turn a list into a dict.
local function is_meta_key(k) return k == "__flags" end

local function table_kind(t)
  local n = 0
  for k in pairs(t) do if not is_meta_key(k) then n = n + 1 end end
  if n == 0 then return "empty", 0 end
  local len = #t
  if len == n then
    for i = 1, len do if t[i] == nil then return "dict", n end end
    return "list", len
  end
  return "dict", n
end

function Ops:note_truncation(total, kind, depth, shape)
  if total <= self.max_items then return end
  self.truncation[#self.truncation + 1] = json.object({
    shape = shape, kind = kind, depth = depth, returned = self.max_items, total = total, dropped = total - self.max_items,
  })
end

function Ops:encode(value, depth, shape)
  depth = depth or 0
  local tv = type(value)
  if value == nil or tv == "boolean" or tv == "number" or tv == "string" then return value end
  if depth > 6 then return tostring(value) end
  if is_object(value) then
    return json.object({ __handle__ = self:mint(value, shape), __type__ = type_name(value), __shape__ = shape })
  end
  if tv == "table" then
    local kind, n = table_kind(value)
    if kind == "list" then
      self:note_truncation(n, "list", depth, shape)
      local out = json.array({})
      local limit = math.min(n, self.max_items)
      for i = 1, limit do out[i] = self:encode(value[i], depth + 1, shape) end
      out.n = limit
      return out
    end
    self:note_truncation(n, "dict", depth, shape)
    local out = json.object({})
    local count = 0
    for k, v in pairs(value) do
      if not is_meta_key(k) then
        count = count + 1
        if count > self.max_items then break end
        out[tostring(k)] = self:encode(v, depth + 1, shape)
      end
    end
    return out
  end
  return tostring(value)
end

function Ops:encoded(value, shape)
  self.truncation = {}
  local encoded = self:encode(value, 0, shape)
  local reply = json.object({ value = encoded })
  if #self.truncation > 0 then
    local dropped = 0
    local containers = json.array({})
    for i, row in ipairs(self.truncation) do
      dropped = dropped + row.dropped
      if i <= 8 then containers[i] = row end
    end
    reply.truncated = json.object({
      dropped = dropped, limit = self.max_items, containers = containers,
      hint = "This reply is INCOMPLETE. The value is not evidence of how many items exist. Re-read in smaller pieces, or count from the object itself rather than from this list.",
    })
    self.truncation = {}
  end
  return reply
end

-- argument decoding: JSON value -> Lua value, rehydrating bridge handles
function Ops:decode(value)
  if value == json.null then return nil end
  if type(value) == "table" then
    local mt = getmetatable(value)
    if mt and mt.__jsontype == "object" then
      if value.__handle__ ~= nil then return self:resolve_target(value.__handle__) end
      local out = {}
      for k, v in pairs(value) do out[k] = self:decode(v) end
      return out
    end
    local out = {}
    local n = value.n or #value
    for i = 1, n do out[i] = self:decode(value[i]) end
    return out
  end
  return value
end

function Ops:op_call(arguments)
  local method = arguments.method
  if type(method) ~= "string" or method == "" then error(op_error("invalid_arguments", "method must be a non-empty string"), 0) end
  if method:sub(1, 1) == "_" then error(op_error("method_not_allowed", "private and dunder attributes are not reachable"), 0) end
  local target_key = arguments.target
  if target_key == nil or target_key == json.null then target_key = "resolve" end
  local target = self:resolve_target(target_key)
  if target == nil then error(op_error("not_found", "the requested object is not available right now"), 0) end
  local raw_args = arguments.args
  if raw_args == nil or raw_args == json.null then raw_args = json.array({}) end
  local mt = getmetatable(raw_args)
  if type(raw_args) ~= "table" or (mt and mt.__jsontype == "object") then error(op_error("invalid_arguments", "args must be a list"), 0) end
  local n = raw_args.n or #raw_args
  if n > 64 then error(op_error("invalid_arguments", "too many arguments"), 0) end
  local args = {}
  for i = 1, n do args[i] = self:decode(raw_args[i]) end
  -- Native comp:Execute queues another Console script. A resident Console
  -- worker cannot finish that queued script before replying, so run generated
  -- Fusion Lua synchronously with the requested comp and its constructors.
  -- Editing behavior remains in operations.py; this only adapts Execute's
  -- interpreter context. Never fall back after an execution failure.
  if method == "Execute" and type_name(target) == "Composition" then
    if n ~= 1 or type(args[1]) ~= "string" then
      error(op_error("invalid_arguments", "Fusion Execute requires one Lua string"), 0)
    end
    local chunk, compile_error = loadstring(args[1], "bridge Fusion")
    if not chunk then error(op_error("invalid_arguments", tostring(compile_error)), 0) end
    local env = setmetatable({
      comp = target, composition = target,
      BezierSpline = function(...) return target:BezierSpline(...) end,
      XYPath = function(...) return target:XYPath(...) end,
    }, { __index = _G })
    setfenv(chunk, env)
    local ok, value = pcall(chunk)
    if not ok then error(op_error("resolve_raised", tostring(value)), 0) end
    return self:encoded(value, self:shape_of(target_key) .. "." .. method)
  end
  local result, err = invoke(target, method, args, n)
  if err then error(err, 0) end
  return self:encoded(result, self:shape_of(target_key) .. "." .. method)
end

function Ops:op_get_attribute(arguments)
  local name = arguments.name
  if type(name) ~= "string" or name == "" then error(op_error("invalid_arguments", "name must be a non-empty string"), 0) end
  if name:sub(1, 1) == "_" then error(op_error("method_not_allowed", "private and dunder attributes are not reachable"), 0) end
  local target_key = arguments.target
  if target_key == nil or target_key == json.null then target_key = "resolve" end
  local target = self:resolve_target(target_key)
  local ok, value = pcall(function() return target[name] end)
  if not ok then error(op_error("resolve_raised", "reading " .. name .. " raised: " .. tostring(value):sub(1, 200)), 0) end
  if value == nil then
    return json.object({ kind = "absent" })
  end
  if type(value) == "function" then return json.object({ kind = "callable" }) end
  local reply = self:encoded(value, self:shape_of(target_key) .. "." .. name)
  reply.kind = "value"
  return reply
end

function Ops:op_release_handles(arguments)
  local handles = arguments.handles
  if handles == nil or handles == json.null then
    local count = self.handle_count
    self.handles, self.handle_order, self.handle_count, self.object_handles = {}, {}, 0, {}
    return json.object({ released = count, all = true })
  end
  local mt = getmetatable(handles)
  if type(handles) ~= "table" or (mt and mt.__jsontype == "object") then error(op_error("invalid_arguments", "handles must be a list"), 0) end
  local released = 0
  for i = 1, (handles.n or #handles) do
    local h = handles[i]
    if self.handles[h] then self.handles[h] = nil; self.handle_count = self.handle_count - 1; released = released + 1 end
  end
  return json.object({ released = released, all = false, held = self.handle_count })
end

function Ops:op_health()
 return json.object({connected=true,session=self.session,version=self.resolve:GetVersionString(),
                     busy=self.transaction~=nil})
end
function Ops:dispatch(op,args)
 if op=="health" then return self:op_health() end
 if op=="begin_operation" then
  if self.transaction and self.transaction_deadline>os.time() then
   error(op_error("busy","Another operation owns this Lua worker"),0)
  end
  if type(self.incoming_transaction)~="string" or #self.incoming_transaction<16 or
     type(args.deadline)~="number" or args.deadline<=os.time() or args.deadline>os.time()+600 then
   error(op_error("invalid_arguments","Invalid operation lease"),0)
  end
  self.transaction=self.incoming_transaction
  self.transaction_deadline=args.deadline
  return json.object({begun=true})
 end
 if not self.transaction or self.incoming_transaction~=self.transaction then
  error(op_error("lease_mismatch","Inspect and begin a new operation before dispatch"),0)
 end
 if op=="finish_operation" then
  self:op_release_handles({})
  self.transaction=nil
  self.transaction_deadline=nil
  return json.object({finished=true})
 end
 if op=="call" then return self:op_call(args) end
 if op=="get_attribute" then return self:op_get_attribute(args) end
 if op=="release_handles" then return self:op_release_handles(args) end
 error(op_error("operation_not_allowed","Unknown RPC operation"),0)
end
local function node_get(obj_node, key)
  for _, p in ipairs(obj_node.pairs) do if p.key == key then return p.value end end
  return nil
end

local Nonces = {}
Nonces.__index = Nonces
function M.new_nonces(skew) return setmetatable({ retention = skew * 2, seen = {}, count = 0 }, Nonces) end
function Nonces:check_and_add(nonce, now)
  local cutoff = now - self.retention
  if self.count > 5000 then
    for k, t in pairs(self.seen) do if t < cutoff then self.seen[k] = nil; self.count = self.count - 1 end end
  end
  -- hard cap: only a holder of the token can fill this store with signed requests, so a flood past
  -- the cap is dropped wholesale rather than growing without bound inside Resolve
  if self.count > 50000 then self.seen = {}; self.count = 0 end
  local t = self.seen[nonce]
  if t and t >= cutoff then return false end
  if not t then self.count = self.count + 1 end
  self.seen[nonce] = now
  return true
end

function M.authenticate(node, token, skew, nonces, now)
  now = now or os.time()
  if node.t ~= "object" then return "invalid_request" end
  local proto = node_get(node, "protocol")
  if not proto or proto.t ~= "string" or proto.value ~= M.PROTOCOL_VERSION then return "protocol_mismatch" end
  if node_get(node, "token") then return "unauthorized" end
  local ts, nonce, sig = node_get(node, "timestamp"), node_get(node, "nonce"), node_get(node, "signature")
  if not ts or ts.t ~= "number" or ts.raw:find("[%.eE]") then return "unauthorized" end
  if not nonce or nonce.t ~= "string" or not nonce.value:match("^[A-Za-z0-9_%-]+$") or #nonce.value < 16 or #nonce.value > 128 then return "unauthorized" end
  if not sig or sig.t ~= "string" or not sig.value:match("^[0-9a-f]+$") or #sig.value ~= 64 then return "unauthorized" end
  local expected = sha.hmac_sha256(token, json.canonical(node, "signature"))
  if not sha.digest_equal(expected, sig.value) then return "unauthorized" end
  if math.abs(now - ts.value) > skew then return "stale_request" end
  if not nonces:check_and_add(nonce.value, now) then return "replayed_request" end
  return nil
end

-- request processing

local function error_reply(id, code, message, details)
  local e = json.object({ code = code })
  if message then e.message = tostring(message):sub(1, 300) end
  if type(details) == "table" then e.details = details end
  return json.object({ id = id, ok = false, error = e })
end

function M.process(line, ops, config, nonces)
  local node, perr = json.parse(line)
  if not node then return error_reply(json.null, "invalid_json") end
  local id = json.null
  if node.t == "object" then
    local idn = node_get(node, "id")
    if idn and idn.t == "string" then id = idn.value end
  end
  local auth_error = M.authenticate(node, config.token, config.auth_clock_skew_seconds, nonces)
  if auth_error then return error_reply(id, auth_error) end
  local expected = node_get(node, "expected_session")
  if expected and (expected.t ~= "string" or expected.value ~= ops.session) then
    return error_reply(id, "session_changed", "Lua worker restarted; inspect before submitting a new operation")
  end
  local deadline = node_get(node, "deadline")
  if deadline and (deadline.t ~= "number" or deadline.value <= os.time()) then
    return error_reply(id, "expired", "Request expired before native dispatch")
  end
  local opn = node_get(node, "operation")
  local argn = node_get(node, "arguments")
  if not opn or opn.t ~= "string" then return error_reply(id, "invalid_request") end
  -- Health alone may omit the expected session. Every object operation belongs
  -- to one inspected session and one OS-locked complete Python operation.
  if opn.value ~= "health" and not expected then
    return error_reply(id, "session_required")
  end
  local transaction = node_get(node, "transaction")
  ops.incoming_transaction = transaction and transaction.t == "string" and transaction.value or nil
  local arguments = json.object({})
  if argn then
    if argn.t ~= "object" then return error_reply(id, "invalid_request") end
    arguments = json.value(argn)
  end
  local ok, result = pcall(function() return ops:dispatch(opn.value, arguments) end)
  if not ok then
    if is_op_error(result) then return error_reply(id, result.code, result.message, result.details) end
    return error_reply(id, "operation_failed", tostring(result))
  end
  return json.object({ id = id, ok = true, result = result })
end

return M
