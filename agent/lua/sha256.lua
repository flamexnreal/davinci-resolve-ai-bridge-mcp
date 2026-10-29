-- SHA-256 and HMAC-SHA256 for LuaJIT (Resolve's embedded Lua). Pure Lua, uses the bit library.
-- Verified against FIPS 180-4 and RFC 4231 vectors by test/test_protocol.lua.
local bit = rawget(_G, "bit") or require("bit")
local band, bxor, bnot, rshift, ror, tohex = bit.band, bit.bxor, bit.bnot, bit.rshift, bit.ror, bit.tohex
local byte, char, rep, concat = string.byte, string.char, string.rep, table.concat
local bor32

local M = {}

local K = {
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
}

local function u32(x) return band(x, 0xffffffff) end

local function be32(s, i)
  local a, b, c, d = byte(s, i, i + 3)
  return bor32(a, b, c, d)
end

bor32 = function(a, b, c, d)
  return u32(a * 16777216 + b * 65536 + c * 256 + d)
end

local function raw32(x)
  x = u32(x)
  if x < 0 then x = x + 4294967296 end
  local a = math.floor(x / 16777216) % 256
  local b = math.floor(x / 65536) % 256
  local c = math.floor(x / 256) % 256
  local d = x % 256
  return char(a, b, c, d)
end

local function digest_raw(msg)
  local ml = #msg
  local bits = ml * 8
  local pad = (56 - (ml + 1) % 64) % 64
  local hi = math.floor(bits / 4294967296)
  local lo = bits % 4294967296
  msg = msg .. "\128" .. rep("\0", pad) .. raw32(hi) .. raw32(lo)

  local H = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 }
  local w = {}
  for chunk = 1, #msg, 64 do
    for i = 0, 15 do w[i] = be32(msg, chunk + i * 4) end
    for i = 16, 63 do
      local x, y = w[i - 15], w[i - 2]
      local s0 = bxor(ror(x, 7), ror(x, 18), rshift(x, 3))
      local s1 = bxor(ror(y, 17), ror(y, 19), rshift(y, 10))
      w[i] = u32(w[i - 16] + s0 + w[i - 7] + s1)
    end
    local a, b, c, d, e, f, g, h = H[1], H[2], H[3], H[4], H[5], H[6], H[7], H[8]
    for i = 0, 63 do
      local S1 = bxor(ror(e, 6), ror(e, 11), ror(e, 25))
      local ch = bxor(band(e, f), band(bnot(e), g))
      local t1 = u32(h + S1 + ch + K[i + 1] + w[i])
      local S0 = bxor(ror(a, 2), ror(a, 13), ror(a, 22))
      local maj = bxor(band(a, b), band(a, c), band(b, c))
      local t2 = u32(S0 + maj)
      h, g, f, e, d, c, b, a = g, f, e, u32(d + t1), c, b, a, u32(t1 + t2)
    end
    H[1], H[2], H[3], H[4] = u32(H[1] + a), u32(H[2] + b), u32(H[3] + c), u32(H[4] + d)
    H[5], H[6], H[7], H[8] = u32(H[5] + e), u32(H[6] + f), u32(H[7] + g), u32(H[8] + h)
  end
  local out = {}
  for i = 1, 8 do out[i] = raw32(H[i]) end
  return concat(out)
end

local function tohexstr(raw)
  local out = {}
  for i = 1, #raw do out[i] = string.format("%02x", byte(raw, i)) end
  return concat(out)
end

function M.sha256(msg) return tohexstr(digest_raw(msg)) end
function M.sha256_raw(msg) return digest_raw(msg) end

function M.hmac_sha256(key, msg)
  if #key > 64 then key = digest_raw(key) end
  key = key .. rep("\0", 64 - #key)
  local ipad, opad = {}, {}
  for i = 1, 64 do
    local k = byte(key, i)
    ipad[i] = char(bxor(k, 0x36))
    opad[i] = char(bxor(k, 0x5c))
  end
  local inner = digest_raw(concat(ipad) .. msg)
  return tohexstr(digest_raw(concat(opad) .. inner))
end

-- Compare two hex digests without an early exit on the first differing byte.
function M.digest_equal(a, b)
  if type(a) ~= "string" or type(b) ~= "string" or #a ~= #b then return false end
  local diff = 0
  for i = 1, #a do diff = bor32(0, 0, 0, bxor(byte(a, i), byte(b, i))) + diff end
  return diff == 0
end

return M
