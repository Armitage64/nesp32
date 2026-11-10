-- nesp32.lua: an NESP32 on controller port 2, for Mesen.
--
-- The NESP32 (github.com/Armitage64/nesp32) is a Wi-Fi board on the NES
-- controller port. Its cartridge talks to it over a serial line made of two
-- controller-port wires: OUT0 ($4016 bit 0, console -> NESP32) and D0
-- ($4017 bit 0, NESP32 -> console), timed to the CPU cycle.
--
-- This script is the console's end of those wires. The NESP32 itself (its
-- real firmware, and the Internet) is nesp32_bridge.py, which this connects
-- to. Every change of OUT0 is sent to the bridge with its cycle; the bridge
-- says which bytes go on D0 and when, and every read of $4017 is answered
-- from that.
--
-- The computer's keyboard is the NESP32's Bluetooth keyboard in typing
-- mode, which Scroll Lock or End (on a Mac, Fn and Right Arrow) turns on
-- and off (TYPING_KEYS below), once Setup has paired it (Setup > Bluetooth
-- > Pair device > Mesen PC keyboard), as a real one is paired. In
-- typing mode every key goes to the NESP32, and none to controller 1 or to
-- the NESP32's own buttons.
--
-- Set up, once:
--   1. Settings > Input: controller port 2 = None (this script is port 2).
--   2. Debug > Script Window > Settings (the gear): tick
--      "Allow access to I/O and OS functions" and "Allow network access".
-- Then load the NESP32 cartridge, open this script in the Script Window,
-- and run it.

local BRIDGE_HOST = "127.0.0.1"       -- the computer running nesp32_bridge.py (this one, by default)
local BRIDGE_PORT = 7878
local KEY_A = "Insert"                 -- the NESP32's own two buttons
local KEY_B = "Delete"
local TYPING_KEYS = { "Scroll Lock", "End" }   -- typing mode on and off
local PAD_WHILE_TYPING = false         -- true: controller 1 still has its keys in typing mode

local socket = require("socket.core")

-- The CPU's cycle count. emu.getCpuCycleCount is in MesenCE and recent
-- Mesen 2 builds; older ones only have it in emu.getState(), which is far
-- slower (a copy of the whole state each call), so the radio may stutter there.
local cycles
if emu.getCpuCycleCount then
  cycles = emu.getCpuCycleCount
else
  cycles = function() return emu.getState()["cpu.cycleCount"] end
end

local conn = nil
local changes = {}        -- OUT0 changes since the last sync: cycle, level, cycle, level...
local lastOut = 0
local busy = false        -- a byte from the console is partway into the bridge
local runs = {}           -- bytes on D0: { s = start, p = period, f = frame length, n = count, b = { bytes } }
local runFirst, runLast = 1, 0
local lastCycle = 0
local status = "connecting"
local keyWas = {}

local retryIn = 0

-- --- the keyboard ---------------------------------------------------------------

-- Mesen's names of the keys, to HID's usages (the keyboard page), which is
-- what a Bluetooth keyboard sends the NESP32. The NESP32 works out the
-- characters, as its firmware does for a US layout.
local USAGE = {
  ["Enter"] = 0x28, ["Esc"] = 0x29, ["Backspace"] = 0x2A, ["Tab"] = 0x2B, ["Space"] = 0x2C,
  ["-"] = 0x2D, ["="] = 0x2E, ["["] = 0x2F, ["]"] = 0x30, ["\\"] = 0x31, [";"] = 0x33,
  ["'"] = 0x34, ["`"] = 0x35, [","] = 0x36, ["."] = 0x37, ["/"] = 0x38, ["Caps Lock"] = 0x39,
  ["Insert"] = 0x49, ["Home"] = 0x4A, ["Page Up"] = 0x4B, ["Delete"] = 0x4C, ["End"] = 0x4D,
  ["Page Down"] = 0x4E, ["Right Arrow"] = 0x4F, ["Left Arrow"] = 0x50, ["Down Arrow"] = 0x51,
  ["Up Arrow"] = 0x52, ["Num Lock"] = 0x53, ["Numpad /"] = 0x54, ["Numpad *"] = 0x55,
  ["Numpad -"] = 0x56, ["Numpad +"] = 0x57, ["Numpad 0"] = 0x62, ["Numpad ."] = 0x63,
  ["|"] = 0x64,
  -- A Mac's Fn and an arrow
  ["FnLeftArrow"] = 0x4A, ["FnRightArrow"] = 0x4D, ["FnUpArrow"] = 0x4B, ["FnDownArrow"] = 0x4E,
}
for i = 0, 25 do USAGE[string.char(65 + i)] = 0x04 + i end           -- A to Z
for i = 1, 9 do USAGE[tostring(i)] = 0x1D + i end                    -- 1 to 9
USAGE["0"] = 0x27
for i = 1, 12 do USAGE["F" .. i] = 0x39 + i end                      -- F1 to F12
for i = 1, 9 do USAGE["Numpad " .. i] = 0x58 + i end

-- And the modifiers, as bits of a report's first byte.
local MODIFIER = {
  ["Left Ctrl"] = 0x01, ["Left Shift"] = 0x02, ["Left Alt"] = 0x04, ["Left Win"] = 0x08,
  ["Right Ctrl"] = 0x10, ["Right Shift"] = 0x20, ["Right Alt"] = 0x40, ["Right Win"] = 0x80,
}

local KEYBOARD_CONNECTED = 4
local typing = false
local typingWas = false
local sentKeys = nil      -- the last report sent, so a report goes only when it changes
local kbdState, kbdOn = 0, false

-- A key name Mesen knows on this computer: isKeyPressed raises an error
-- for any other.
local function known(name)
  return (pcall(emu.isKeyPressed, name))
end

local isToggle = {}
for _, name in ipairs(TYPING_KEYS) do isToggle[name] = true end

-- The keys down now, by name. emu.getPressedKeys is one call; a Mesen
-- without it is asked of each key.
local pressedKeys
if emu.getPressedKeys then
  pressedKeys = function() return emu.getPressedKeys() end
else
  local names = {}
  for name in pairs(USAGE) do if known(name) then names[#names + 1] = name end end
  for name in pairs(MODIFIER) do if known(name) then names[#names + 1] = name end end
  for name in pairs(isToggle) do if USAGE[name] == nil and known(name) then names[#names + 1] = name end end
  pressedKeys = function()
    local down = {}
    for _, name in ipairs(names) do
      if emu.isKeyPressed(name) then down[#down + 1] = name end
    end
    return down
  end
end

-- What the keyboard sends: its modifiers, and up to 6 keys (1 if more are
-- down: a report a keyboard sends to say it cannot tell which).
local function keyReport(down)
  local modifiers, keys = 0, {}
  for _, name in pairs(down) do
    if MODIFIER[name] then
      modifiers = modifiers | MODIFIER[name]
    elseif USAGE[name] and not isToggle[name] then
      keys[#keys + 1] = USAGE[name]
    end
  end
  if #keys > 6 then keys = { 1 } end
  table.sort(keys)
  return "K " .. modifiers .. (#keys > 0 and (" " .. table.concat(keys, " ")) or "")
end

local function sendKeys(report)
  if conn ~= nil and report ~= sentKeys then
    conn:send(report .. "\n")
    sentKeys = report
  end
end

local function setTyping(on)
  typing = on
  if on then
    emu.displayMessage("NESP32", "Typing mode on: the keyboard is the NESP32's")
  else
    sendKeys("K 0")                             -- every key let go of
    emu.displayMessage("NESP32", "Typing mode off: the keyboard is the controller's")
  end
end

-- The keyboard, once a frame: typing mode's key, and in typing mode what
-- is down.
local function pollKeyboard()
  local down = pressedKeys()
  local toggle = false
  for _, name in pairs(down) do
    if isToggle[name] then toggle = true end
  end
  if toggle and not typingWas then
    setTyping(not typing)
  end
  typingWas = toggle
  if typing then
    sendKeys(keyReport(down))
  end
end

-- In typing mode, controller 1 has none of the keyboard's keys (the
-- NESP32's programs take the arrows, Enter and Escape as its buttons).
local NO_BUTTONS = { a = false, b = false, start = false, select = false,
                     up = false, down = false, left = false, right = false }
local function onInputPolled()
  if typing and not PAD_WHILE_TYPING then
    pcall(emu.setInput, NO_BUTTONS, 0)
  end
end

local function drawTyping()
  emu.drawString(4, 212, "TYPING (" .. TYPING_KEYS[1] .. ": stop)", 0xFFFFFF, 0x40000080)
  if kbdState ~= KEYBOARD_CONNECTED then
    emu.drawString(4, 222, "No keyboard paired: Setup > Bluetooth", 0xFFFF00, 0x40000000)
  elseif not kbdOn then
    emu.drawString(4, 222, "This program takes no keys", 0xFFFF00, 0x40000000)
  end
end

-- --- the line -------------------------------------------------------------------

local function connect()
  local c = socket.tcp()
  c:settimeout(0.3)
  local ok, err = c:connect(BRIDGE_HOST, BRIDGE_PORT)
  if not ok then
    status = "no bridge at " .. BRIDGE_HOST .. ":" .. BRIDGE_PORT .. " (" .. tostring(err) .. ")"
    emu.log("NESP32: " .. status)
    return nil
  end
  c:setoption("tcp-nodelay", true)
  c:settimeout(2)
  -- A fresh board: what the console did while there was none is of no use
  -- to it, and the line starts quiet.
  changes, runs, runFirst, runLast = {}, {}, 1, 0
  busy = false
  sentKeys = nil
  status = "connected"
  emu.log("NESP32: connected to " .. BRIDGE_HOST .. ":" .. BRIDGE_PORT)
  return c
end

local function addRuns(words, i, count)
  for _ = 1, count do
    local s, p, hex = tonumber(words[i]), tonumber(words[i + 1]), words[i + 2]
    i = i + 3
    local bytes = {}
    for k = 1, #hex, 2 do
      bytes[#bytes + 1] = tonumber(string.sub(hex, k, k + 1), 16)
    end
    runLast = runLast + 1
    runs[runLast] = { s = s, p = p, f = p * 11, n = #bytes, b = bytes, e = s + p * 11 * #bytes }
  end
  return i
end

-- Tell the bridge the time and OUT0's changes; take the bytes it puts on D0.
local function sync(cycle)
  if conn == nil then
    return
  end
  local parts = { "S", tostring(math.floor(cycle)), tostring(#changes // 2) }
  for k = 1, #changes do
    parts[#parts + 1] = tostring(math.floor(changes[k]))
  end
  changes = {}
  local ok, err = conn:send(table.concat(parts, " ") .. "\n")
  if not ok then
    status = "bridge lost (" .. tostring(err) .. ")"
    conn = nil
    return
  end
  local line, rerr = conn:receive("*l")
  if not line then
    status = "bridge lost (" .. tostring(rerr) .. ")"
    conn = nil
    return
  end
  local words = {}
  for w in string.gmatch(line, "%S+") do
    words[#words + 1] = w
  end
  busy = words[2] == "1"
  local i = addRuns(words, 4, tonumber(words[3]))
  if words[i] == "K" then
    kbdState, kbdOn = tonumber(words[i + 1]), words[i + 2] == "1"
  end
end

-- The level of D0 at a cycle: mark (1) when nothing is being sent.
local function level(cycle)
  while runFirst <= runLast and cycle >= runs[runFirst].e do
    runs[runFirst] = nil
    runFirst = runFirst + 1
  end
  local run = runs[runFirst]
  if run == nil or cycle < run.s then
    return 1
  end
  local rel = cycle - run.s
  local index = rel // run.f
  local bit = (rel - index * run.f) / run.p
  if bit < 1 then
    return 0                                    -- start bit
  elseif bit < 9 then
    return (run.b[index + 1] >> math.floor(bit - 1)) & 1
  end
  return 1                                      -- stop bits
end

local function resetLine(cycle)
  changes, runs, runFirst, runLast = {}, {}, 1, 0
  busy = false
  lastCycle = cycle
end

-- $4016 write: OUT0 is bit 0
local function onWrite(address, value)
  local cycle = cycles()
  local out = value & 1
  if out ~= lastOut then
    lastOut = out
    changes[#changes + 1] = cycle
    changes[#changes + 1] = out
  end
end

-- $4017 read: D0, inverted by the console's buffer, in bit 0
local function onRead(address, value)
  local cycle = cycles()
  if cycle < lastCycle then
    resetLine(cycle)
  end
  lastCycle = cycle
  if #changes > 0 or busy then
    sync(cycle)
  end
  return (value & 0xFE) | (level(cycle) ~ 1)
end

-- The NESP32's own buttons, by name; a name this Mesen does not know is
-- left out, with a word in the log.
local buttons = {}
for i, key in ipairs({ KEY_A, KEY_B }) do
  if known(key) then
    buttons[#buttons + 1] = { key = key, code = i }
  else
    emu.log("NESP32: no key named " .. key .. " in this Mesen")
  end
end

local function onFrame()
  local cycle = cycles()
  if conn == nil then
    retryIn = retryIn - 1
    if retryIn <= 0 then
      retryIn = 120                             -- try again every two seconds
      conn = connect()
    end
  end
  if cycle < lastCycle then
    resetLine(cycle)
  end
  lastCycle = cycle
  pollKeyboard()
  for _, button in ipairs(buttons) do
    local down = not typing and emu.isKeyPressed(button.key)
    if down and not keyWas[button.code] and conn ~= nil then
      conn:send("B " .. button.code .. "\n")
    end
    keyWas[button.code] = down
  end
  sync(cycle)
  if conn == nil then
    emu.drawString(4, 4, "NESP32: " .. status, 0xFFFFFF, 0x80000000)
  end
  if typing then
    drawTyping()
  end
end

conn = connect()
emu.addMemoryCallback(onWrite, emu.callbackType.write, 0x4016)
emu.addMemoryCallback(onRead, emu.callbackType.read, 0x4017)
emu.addEventCallback(onFrame, emu.eventType.endFrame)
if emu.eventType.inputPolled and emu.setInput then
  emu.addEventCallback(onInputPolled, emu.eventType.inputPolled)
end
emu.displayMessage("NESP32", status .. "; typing mode: " .. table.concat(TYPING_KEYS, " or "))
