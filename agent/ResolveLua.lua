-- Lua bridge for current Resolve Free. BRIDGE_HOME/ACTION are installed headers.
-- Only native Fusion file APIs are used: no io, FFI, socket or Python in Resolve.
local home = BRIDGE_HOME or os.getenv("RESOLVE_AI_BRIDGE_HOME") or
  ((os.getenv("USERPROFILE") or os.getenv("HOME")) .. "/.resolve-ai-bridge")
local action = BRIDGE_ACTION or "start"
local app = fusion or fu
assert(app and app.OpenFile, "This Resolve build has no native Fusion file API")
if bmd and bmd.direxists and bmd.direxists(home .. ".install-lock") then
  error("Bridge installation is in progress; start after it completes")
end

local function read_file(path, first_line, limit)
  local f = app:OpenFile(path, 1) -- FILE_MODE_READ (not exported as a Lua constant)
  if not f then return nil end
  if f:GetFileSize() > (limit or 1048576) then f:Close(); return nil end
  local chunks = {}
  while true do
    local line = f:ReadLine()
    if line == nil then break end
    chunks[#chunks + 1] = line
    if first_line then break end
  end
  f:Close()
  return table.concat(chunks, "\n")
end

local function write_file(path, value)
  -- Python pre-creates these slots with 0600 inside a 0700 home. Refuse to
  -- create a new file with native default permissions if setup is incomplete.
  local existing = assert(app:OpenFile(path, 1), "Reinstall the bridge: missing private IPC slot")
  existing:Close()
  local f = assert(app:OpenFile(path, 2), "Cannot open the private IPC slot for writing")
  local ok, err = pcall(function()
    assert(f:WriteLine(value), "Native write failed")
    assert(f:Flush(), "Native flush failed")
  end)
  f:Close()
  if not ok then error(err, 0) end
end

local modules = {}
local function native_require(name)
  if modules[name] then return modules[name] end
  assert(name == "json_raw" or name == "sha256" or name == "rpc", "Unknown bridge module")
  local source = assert(read_file(home .. "/lua/" .. name .. ".lua"), "Missing bridge module: " .. name)
  local chunk = assert(loadstring(source, "Resolve AI Bridge " .. name))
  setfenv(chunk, setmetatable({require = native_require}, {__index = _G}))
  modules[name] = chunk()
  return modules[name]
end

local json = native_require("json_raw")
local sha = native_require("sha256")
local token = assert(read_file(home .. "/token.txt", true, 4096), "Run the installer first"):match("^%s*(.-)%s*$")
assert(#token >= 43, "Invalid bridge token; run the installer")

local function signed(value)
  local payload = json.encode(value)
  return json.encode(json.object({payload = payload, signature = sha.hmac_sha256(token, payload)}))
end

local function authenticated_file(name)
  local raw = read_file(home .. "/" .. name, true, 65536)
  if not raw then return nil end
  local node = json.parse(raw)
  if not node then return nil end
  local envelope = json.value(node)
  if type(envelope) ~= "table" or type(envelope.payload) ~= "string" or
     not sha.digest_equal(sha.hmac_sha256(token, envelope.payload), envelope.signature) then return nil end
  local payload = json.parse(envelope.payload)
  return payload and json.value(payload) or nil
end

if action == "status" or action == "stop" then
  local heartbeat = authenticated_file("lua-agent.json")
  if not heartbeat or not heartbeat.active then print("Resolve AI Bridge Lua is not running"); return end
  if action == "status" then
    print("RESOLVE AI BRIDGE LUA: " .. tostring(heartbeat.state) ..
      "; Resolve " .. tostring(heartbeat.resolve_version) ..
      "; heartbeat age " .. tostring(os.time() - heartbeat.time) .. "s")
  else
    write_file(home .. "/lua-stop.json", signed(json.object({
      session = heartbeat.session, deadline = os.time() + 600,
      nonce = bmd.createuuid(), action = "stop"
    })))
    print("Lua stop requested; the active complete operation will finish first")
  end
  return
end
assert(action == "start", "Unknown Lua bridge action")

local owner_key = "ResolveAIBridge.NativeSession"
local owner_app_key = "ResolveAIBridge.NativeApp"
local identity = tostring(app)
local previous = authenticated_file("lua-agent.json")
local current_owner = app:GetData(owner_key)
if current_owner and (not previous or previous.app == identity) then
  print("Resolve AI Bridge Lua is already running")
  return
end
if previous and previous.active then
  local age = os.time() - previous.time
  if previous.app == identity and (app:GetData(owner_key) == previous.session or
     (age >= -10 and age < 25)) then
    print("Resolve AI Bridge Lua is already running")
    return
  end
end

local rpc = native_require("rpc")
local r = resolve or bmd.scriptapp("Resolve")
assert(r, "Resolve has no API object; open a project and retry")
local config = {token = token, auth_clock_skew_seconds = 60}
local ops = rpc.new_ops(r, config)
local nonces = rpc.new_nonces(60)
local cached = {resolve_version = r:GetVersionString(), product = r:GetProductName(), pid = bmd.getpid()}
app:SetData(owner_key, ops.session)
app:SetData(owner_app_key, identity)
local last, last_heartbeat, served = "", 0, 0
local stop_pending = false

local function heartbeat(active, error_message)
  local value = json.object({
    session = ops.session, time = os.time(), active = active, app = identity,
    state = active and (ops.transaction and "busy" or "idle") or "stopped",
    busy = ops.transaction ~= nil, protocol = "native-file-v1", served = served,
    agent_version = rpc.VERSION, resolve_version = cached.resolve_version,
    product = cached.product, pid = cached.pid, error = error_message
  })
  write_file(home .. "/lua-agent.json", signed(value))
  last_heartbeat = os.time()
end

local ok, err = xpcall(function()
  heartbeat(true)
  print("RESOLVE AI BRIDGE LUA READY")
  while app:GetData(owner_key) == ops.session do
    local now = os.time()
    if now ~= last_heartbeat then heartbeat(true) end
    local stop = authenticated_file("lua-stop.json")
    if stop and stop.action == "stop" and stop.session == ops.session and
       type(stop.deadline) == "number" and now <= stop.deadline and stop.deadline <= now + 600 then
      stop_pending = true
    end
    -- A dead client cannot hold the worker indefinitely. Native calls are
    -- synchronous here; an expired lease is released only after that call ends.
    if ops.transaction and now > ops.transaction_deadline then
      ops:op_release_handles({})
      ops.transaction, ops.transaction_deadline = nil, nil
    end
    if stop_pending and not ops.transaction then break end
    local raw = read_file(home .. "/lua-inbox.json", true)
    if raw and raw ~= last and #raw > 2 then
      last = raw
      local reply = rpc.process(raw, ops, config, nonces)
      served = served + 1
      write_file(home .. "/lua-outbox.json", signed(reply))
      heartbeat(true)
    end
    bmd.wait(0.005)
  end
end, function(message) return tostring(message) end)

if app:GetData(owner_key) == ops.session then
  pcall(function() app:SetData(owner_key, nil) end)
  pcall(function() app:SetData(owner_app_key, nil) end)
  pcall(heartbeat, false, not ok and tostring(err) or nil)
end
if not ok then print("RESOLVE AI BRIDGE LUA STOPPED: " .. tostring(err)) end
