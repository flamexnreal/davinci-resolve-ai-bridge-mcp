-- Run the short control script here; do not queue behind the resident worker.
local home = __BRIDGE_HOME__
local app = fusion or fu
local file = app:OpenFile(home .. "/StopLua.lua", 1)
if not file then print("Install Resolve AI Bridge first"); return end
local chunks = {}
while true do local line = file:ReadLine(); if line == nil then break end; chunks[#chunks+1] = line end
file:Close()
assert(loadstring(table.concat(chunks, "\n"), "Stop AI Bridge Lua"))()
