-- Installed absolute runtime, including custom homes. No Python needed in Resolve.
local home = __BRIDGE_HOME__
local app = fusion or fu
local file = app:OpenFile(home .. "/ResolveLua.lua", 1)
if not file then print("Install Resolve AI Bridge first"); return end
local chunks = {}
while true do local line = file:ReadLine(); if line == nil then break end; chunks[#chunks+1] = line end
file:Close()
-- Stay in the menu script's own context. RunScript would queue another start
-- behind a resident worker and unexpectedly restart it after Stop.
assert(loadstring(table.concat(chunks, "\n"), "Start AI Bridge Lua"))()
