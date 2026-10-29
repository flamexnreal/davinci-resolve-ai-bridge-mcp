local home = __BRIDGE_HOME__
local app = fusion or fu
local file = app:OpenFile(home .. "/StatusLua.lua", 1)
if not file then print("Install Resolve AI Bridge first"); return end
local chunks = {}
while true do local line = file:ReadLine(); if line == nil then break end; chunks[#chunks+1] = line end
file:Close()
assert(loadstring(table.concat(chunks, "\n"), "AI Bridge Lua Status"))()
