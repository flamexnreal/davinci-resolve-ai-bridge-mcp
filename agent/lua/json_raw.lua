-- JSON for the Resolve bridge (LuaJIT 5.1 compatible).
--
-- Two jobs the stock libraries cannot do:
--   1. parse() keeps every number's wire literal, so canonical() can re-emit the request byte for byte
--      the way Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True) would.
--      That is what the HMAC signature is computed over on the client, so it must match exactly.
--   2. encode() writes replies with Python-style ASCII escaping and sorted keys.
--
-- Node shapes from parse():
--   {t="object", pairs={{key=<decoded>, value=<node>}, ...}}
--   {t="array", items={<node>...}, n=<count>}
--   {t="string", value=<decoded utf-8>}     {t="number", raw=<literal>, value=<number>}
--   {t="true"} {t="false"} {t="null"}
local byte, char, sub, find, format, concat = string.byte, string.char, string.sub, string.find, string.format, table.concat
local floor = math.floor

local M = {}
M.null = setmetatable({}, { __tostring = function() return "null" end })

-- ── decoding ─────────────────────────────────────────────────────────────────

local function utf8_encode(cp)
  if cp < 0x80 then return char(cp) end
  if cp < 0x800 then return char(0xC0 + floor(cp / 0x40), 0x80 + cp % 0x40) end
  if cp < 0x10000 then
    return char(0xE0 + floor(cp / 0x1000), 0x80 + floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
  end
  return char(0xF0 + floor(cp / 0x40000), 0x80 + floor(cp / 0x1000) % 0x40,
              0x80 + floor(cp / 0x40) % 0x40, 0x80 + cp % 0x40)
end

local ESC = { ['"'] = '"', ['\\'] = '\\', ['/'] = '/', b = '\b', f = '\f', n = '\n', r = '\r', t = '\t' }

local function parse_error(s, pos, msg)
  return nil, format("json: %s at byte %d", msg, pos)
end

local function skip_ws(s, pos)
  local _, e = find(s, "^[ \t\r\n]*", pos)
  return e + 1
end

local parse_value

local function parse_string(s, pos)
  -- pos is at the opening quote
  local out, i, n = {}, pos + 1, #s
  while i <= n do
    local c = byte(s, i)
    if c == 34 then
      return { t = "string", value = concat(out) }, i + 1
    elseif c == 92 then
      local e = sub(s, i + 1, i + 1)
      if e == "u" then
        local hex = sub(s, i + 2, i + 5)
        if not find(hex, "^%x%x%x%x$") then return parse_error(s, i, "bad \\u escape") end
        local cp = tonumber(hex, 16)
        i = i + 6
        if cp >= 0xD800 and cp <= 0xDBFF then
          local hex2 = sub(s, i + 2, i + 5)
          if sub(s, i, i + 1) == "\\u" and find(hex2, "^%x%x%x%x$") then
            local lo = tonumber(hex2, 16)
            if lo >= 0xDC00 and lo <= 0xDFFF then
              cp = 0x10000 + (cp - 0xD800) * 0x400 + (lo - 0xDC00)
              i = i + 6
            end
          end
        end
        out[#out + 1] = utf8_encode(cp)
      elseif ESC[e] then
        out[#out + 1] = ESC[e]
        i = i + 2
      else
        return parse_error(s, i, "bad escape")
      end
    elseif c < 32 then
      return parse_error(s, i, "control character in string")
    else
      local j = find(s, '["\\%c]', i) or (n + 1)
      out[#out + 1] = sub(s, i, j - 1)
      i = j
    end
  end
  return parse_error(s, pos, "unterminated string")
end

local function parse_number(s, pos)
  local _, e = find(s, "^-?%d+%.?%d*[eE]?[-+]?%d*", pos)
  if not e then return parse_error(s, pos, "bad number") end
  local raw = sub(s, pos, e)
  local v = tonumber(raw)
  if v == nil then return parse_error(s, pos, "bad number") end
  return { t = "number", raw = raw, value = v }, e + 1
end

parse_value = function(s, pos, depth)
  if depth > 64 then return parse_error(s, pos, "nesting too deep") end
  pos = skip_ws(s, pos)
  local c = byte(s, pos)
  if c == nil then return parse_error(s, pos, "unexpected end") end
  if c == 123 then -- {
    local pairs_ = {}
    pos = skip_ws(s, pos + 1)
    if byte(s, pos) == 125 then return { t = "object", pairs = pairs_ }, pos + 1 end
    while true do
      pos = skip_ws(s, pos)
      if byte(s, pos) ~= 34 then return parse_error(s, pos, "expected string key") end
      local k, np = parse_string(s, pos)
      if not k then return nil, np end
      pos = skip_ws(s, np)
      if byte(s, pos) ~= 58 then return parse_error(s, pos, "expected ':'") end
      local v, np2 = parse_value(s, pos + 1, depth + 1)
      if not v then return nil, np2 end
      pairs_[#pairs_ + 1] = { key = k.value, value = v }
      pos = skip_ws(s, np2)
      local d = byte(s, pos)
      if d == 44 then pos = pos + 1
      elseif d == 125 then return { t = "object", pairs = pairs_ }, pos + 1
      else return parse_error(s, pos, "expected ',' or '}'") end
    end
  elseif c == 91 then -- [
    local items = {}
    pos = skip_ws(s, pos + 1)
    if byte(s, pos) == 93 then return { t = "array", items = items, n = 0 }, pos + 1 end
    while true do
      local v, np = parse_value(s, pos, depth + 1)
      if not v then return nil, np end
      items[#items + 1] = v
      pos = skip_ws(s, np)
      local d = byte(s, pos)
      if d == 44 then pos = pos + 1
      elseif d == 93 then return { t = "array", items = items, n = #items }, pos + 1
      else return parse_error(s, pos, "expected ',' or ']'") end
    end
  elseif c == 34 then
    return parse_string(s, pos)
  elseif c == 116 and sub(s, pos, pos + 3) == "true" then return { t = "true" }, pos + 4
  elseif c == 102 and sub(s, pos, pos + 4) == "false" then return { t = "false" }, pos + 5
  elseif c == 110 and sub(s, pos, pos + 3) == "null" then return { t = "null" }, pos + 4
  else
    return parse_number(s, pos)
  end
end

--- Parse one JSON document. Returns node, or nil + error.
function M.parse(s)
  if type(s) ~= "string" then return nil, "json: not a string" end
  local node, pos = parse_value(s, 1, 0)
  if not node then return nil, pos end
  pos = skip_ws(s, pos)
  if pos <= #s then return parse_error(s, pos, "trailing data") end
  return node
end

--- Plain Lua value from a node. Objects and arrays get a __jsontype metatable; JSON null becomes M.null.
local array_mt, object_mt = { __jsontype = "array" }, { __jsontype = "object" }
function M.value(node)
  local t = node.t
  if t == "string" then return node.value
  elseif t == "number" then return node.value
  elseif t == "true" then return true
  elseif t == "false" then return false
  elseif t == "null" then return M.null
  elseif t == "array" then
    local out = setmetatable({}, array_mt)
    for i = 1, node.n do out[i] = M.value(node.items[i]) end
    out.n = node.n
    return out
  else
    local out = setmetatable({}, object_mt)
    for _, p in ipairs(node.pairs) do out[p.key] = M.value(p.value) end
    return out
  end
end

-- ── encoding (Python json.dumps, ensure_ascii=True, sort_keys=True, separators=(",", ":")) ───────

local function bytewise_less(a, b)
  local la, lb = #a, #b
  local n = la < lb and la or lb
  for i = 1, n do
    local x, y = byte(a, i), byte(b, i)
    if x ~= y then return x < y end
  end
  return la < lb
end
M.bytewise_less = bytewise_less

-- Python escapes everything outside 0x20..0x7E plus the quote and the backslash.
local SHORT = { [8] = "\\b", [9] = "\\t", [10] = "\\n", [12] = "\\f", [13] = "\\r", [34] = '\\"', [92] = "\\\\" }

local function utf8_next(s, i)
  local c = byte(s, i)
  if c < 0x80 then return c, i + 1 end
  if c >= 0xF0 then
    local b2, b3, b4 = byte(s, i + 1, i + 3)
    return (c - 0xF0) * 0x40000 + (b2 - 0x80) * 0x1000 + (b3 - 0x80) * 0x40 + (b4 - 0x80), i + 4
  elseif c >= 0xE0 then
    local b2, b3 = byte(s, i + 1, i + 2)
    return (c - 0xE0) * 0x1000 + (b2 - 0x80) * 0x40 + (b3 - 0x80), i + 3
  else
    local b2 = byte(s, i + 1)
    return (c - 0xC0) * 0x40 + (b2 - 0x80), i + 2
  end
end

function M.encode_string(s)
  local out, i, n = { '"' }, 1, #s
  while i <= n do
    local cp, ni = utf8_next(s, i)
    if SHORT[cp] then out[#out + 1] = SHORT[cp]
    elseif cp >= 0x20 and cp <= 0x7E then out[#out + 1] = char(cp)
    elseif cp < 0x10000 then out[#out + 1] = format("\\u%04x", cp)
    else
      local v = cp - 0x10000
      out[#out + 1] = format("\\u%04x\\u%04x", 0xD800 + floor(v / 0x400), 0xDC00 + v % 0x400)
    end
    i = ni
  end
  out[#out + 1] = '"'
  return concat(out)
end

--- Canonical text of a parsed node: the exact bytes the client signed.
function M.canonical(node, skip_key)
  local t = node.t
  if t == "string" then return M.encode_string(node.value)
  elseif t == "number" then return node.raw
  elseif t == "true" then return "true"
  elseif t == "false" then return "false"
  elseif t == "null" then return "null"
  elseif t == "array" then
    local parts = {}
    for i = 1, node.n do parts[i] = M.canonical(node.items[i]) end
    return "[" .. concat(parts, ",") .. "]"
  else
    local keys, byname = {}, {}
    for _, p in ipairs(node.pairs) do
      if p.key ~= skip_key then
        if byname[p.key] == nil then keys[#keys + 1] = p.key end
        byname[p.key] = p.value -- later duplicates win, as in Python
      end
    end
    table.sort(keys, bytewise_less)
    local parts = {}
    for i, k in ipairs(keys) do parts[i] = M.encode_string(k) .. ":" .. M.canonical(byname[k]) end
    return "{" .. concat(parts, ",") .. "}"
  end
end

-- Python-style float text: shortest digits that round-trip, "-0.0" kept, exponent as e-07.
local function encode_number(v)
  if v ~= v or v == math.huge or v == -math.huge then return "null" end
  if v == 0 and 1 / v < 0 then return "-0.0" end
  if v == floor(v) and math.abs(v) < 9007199254740992 then return format("%d", v) end
  local s
  for prec = 15, 17 do
    s = format("%." .. prec .. "g", v)
    if tonumber(s) == v then break end
  end
  if not find(s, "[%.eEn]") then s = s .. ".0" end
  s = s:gsub("e([-+])0*(%d)", function(sign, d) return "e" .. sign .. (#d < 2 and "0" or "") .. d end)
  return s
end

local function is_array(t)
  local mt = getmetatable(t)
  if mt and mt.__jsontype then return mt.__jsontype == "array" end
  if t.n ~= nil then return true end
  local n = #t
  if n == 0 then return false end
  local count = 0
  for k in pairs(t) do
    if type(k) ~= "number" or k < 1 or k > n or k ~= floor(k) then return false end
    count = count + 1
  end
  return count == n
end

--- Encode a Lua value as compact JSON with sorted keys. Tables with a __jsontype metatable
--- are typed explicitly; other tables are arrays when they are dense 1..n sequences, else objects.
function M.encode(v, depth)
  depth = depth or 0
  if depth > 64 then return '"<too deep>"' end
  local tv = type(v)
  if v == nil or v == M.null then return "null"
  elseif tv == "boolean" then return v and "true" or "false"
  elseif tv == "number" then return encode_number(v)
  elseif tv == "string" then return M.encode_string(v)
  elseif tv == "table" then
    if is_array(v) then
      local n = v.n or #v
      local parts = {}
      for i = 1, n do parts[i] = M.encode(v[i], depth + 1) end
      return "[" .. concat(parts, ",") .. "]"
    end
    local keys = {}
    for k in pairs(v) do
      if k ~= "n" or type(v[k]) ~= "number" or not getmetatable(v) then keys[#keys + 1] = tostring(k) end
    end
    table.sort(keys, bytewise_less)
    local parts = {}
    for i, k in ipairs(keys) do
      local val = v[k]
      if val == nil then val = v[tonumber(k)] end
      parts[i] = M.encode_string(k) .. ":" .. M.encode(val, depth + 1)
    end
    return "{" .. concat(parts, ",") .. "}"
  else
    return M.encode_string(tostring(v))
  end
end

function M.array(t) return setmetatable(t or {}, array_mt) end
function M.object(t) return setmetatable(t or {}, object_mt) end

return M
