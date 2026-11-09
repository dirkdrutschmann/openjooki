-- Individual cached titles and account-bound artwork. Native metadata paths stay private.
local util = require("services.util")
local json = require("vendor.json")
local items = {}
local copy, err = util.copy, util.err
local function facade() return require("services.spotify_offline") end
local function valid_uri(uri) return type(uri) == "string" and #uri == 36 and uri:match("^spotify:track:%w+$") ~= nil end
items.valid_uri = valid_uri

function items.assets(doc, int, data, reset)
  local account = data.account_id or (doc.spotify_offline or {}).account_id
  if reset or int.artwork_account ~= account then int.artwork = {} end
  int.artwork, int.artwork_account = int.artwork or {}, account
  local count, incoming = 0, 0
  for _ in pairs(int.artwork) do count = count + 1 end
  for key in pairs(type(data.artwork) == "table" and data.artwork or {}) do if not int.artwork[key] then incoming = incoming + 1 end end
  -- Keep the whole visible page, while bounding older, no-longer-visible image mappings.
  if count + incoming > 512 then int.artwork = {} end
  local root = (doc.config or {}).spotify_offline_root or "/jooki/external/openjooki-offline"
  local prefix = root .. "/store/accounts/" .. tostring(account) .. "/"
  for key, value in pairs(type(data.artwork) == "table" and data.artwork or {}) do
    if type(key) == "string" and #key == 64 and key:match("^%x+$") and type(value) == "table"
        and type(value.path) == "string" and value.path:sub(1, #prefix) == prefix
        and not value.path:find("..", 1, true) and value.path:match("/cover%-%x+%.img$")
        and ({ ["image/jpeg"] = true, ["image/png"] = true, ["image/webp"] = true, ["image/gif"] = true })[value.mime] then
      int.artwork[key] = { path = value.path, mime = value.mime }
    end
  end
  data.artwork = nil
end

function items.artwork(doc, path)
  local key = type(path) == "string" and path:match("^/offline%-artwork/(%x+)$")
  local pub, int = doc.spotify_offline or {}, doc.spotify_offline_int or {}
  if not key or #key ~= 64 or not pub.account_id or int.artwork_account ~= pub.account_id
      or not (pub.metadata_ready or pub.account_ready) then return nil end
  local value = (int.artwork or {})[key]
  if value then return value.path, value.mime end
end

function items.single_snapshot(doc, _, p, opts)
  if not valid_uri(opts.track_uri) or not (doc.spotify_offline or {}).account_ready then return nil end
  local pub = doc.spotify_offline or {}
  local preview = (pub.previews or {})[p.spotify.uri] or {}
  local snap = (pub.playlists or {})[p.spotify.uri] or {}
  local track
  for _, t in ipairs(preview.tracks or {}) do if t.uri == opts.track_uri then track = t; break end end
  if not track then for _, t in ipairs(snap.tracks or {}) do if t.uri == opts.track_uri then track = t; break end end end
  return { single = true, total_tracks = math.max(opts.index or 1, preview.total or snap.total_tracks or 1),
    tracks = {}, current_track = copy(track or { name = p.title, artists = {}, uri = opts.track_uri }) }
end

local function identity(doc)
  local n = (doc.playback or {}).now or {}
  return tostring(n.playlist or "") .. ":" .. tostring(n.track or n.uri or "")
end

function items.on_cache(doc, ev)
  local index = ev.index
  if type(index) ~= "number" or index % 1 ~= 0 or index < 1 or index > 10000 or not valid_uri(ev.track_uri) then
    return nil, err("invalid_argument", "track_uri", "invalid Spotify title selection")
  end
  local r, e = facade().on_sync(doc, ev)
  if not r then return nil, e end
  if ev.play then
    local p = doc.library.playlists[ev.playlist]
    local int = r.state.spotify_offline_int
    int.next_id = (int.next_id or 0) + 1
    int.pending_play = { playlist = ev.playlist, uri = p.spotify.uri, index = index, track_uri = ev.track_uri,
      token = tostring(ev.now or 0) .. "-" .. int.next_id, previous = identity(doc), now = ev.now }
    if (doc.playback or {}).now and doc.playback.now.service == facade().SERVICE and doc.playback.state == "playing" then
      r.commands[#r.commands + 1] = util.emit("playback.pause_request", { source = "offline-cache", now = ev.now })
    end
  end
  return r
end

function items.on_ready(doc, ev)
  local int = copy(doc.spotify_offline_int or {})
  if not int.ready_play or int.ready_play.token ~= ev.token then return nil end
  int.ready_play = nil
  if identity(doc) ~= ev.previous then return { state = { spotify_offline_int = int } } end
  local d = copy(doc); d.spotify_offline_int = int
  local r, e = facade().on_play(d, ev)
  if r then return r end
  return { state = { spotify_offline_int = int }, commands = { { kind = "log", level = "warn", key = "offline.title_play_failed", fields = { error = e and e.message } } } }
end

function items.on_cancel(doc, ev)
  local int = copy(doc.spotify_offline_int or {})
  if int.pending_play and int.pending_play.token == ev.token then int.pending_play = nil end
  if int.ready_play and int.ready_play.token == ev.token then int.ready_play = nil end
  return { state = { spotify_offline_int = int } }
end

function items.install(api, dispatch)
  local schema = { type = "object", required = { "playlist", "index", "track_uri" }, additionalProperties = false,
    properties = { playlist = { type = "string", minLength = 1, maxLength = 100 }, index = { type = "integer", minimum = 1, maximum = 10000 },
      track_uri = { type = "string", minLength = 36, maxLength = 36 }, play = { type = "boolean" } } }
  api.command("spotify_offline.cache_track", schema, function(doc, p, ev) p = copy(p); p.now = ev.now; return items.on_cache(doc, p) end)
  require("services.security").PROTECTED_V2["spotify_offline.cache_track"] = true
  dispatch.on("offline.play_cached", "spotify_offline.items", items.on_ready)
  dispatch.on("offline.cancel_pending", "spotify_offline.items", items.on_cancel)
  local function cancel(doc, ev)
    local int = doc.spotify_offline_int or {}
    local pending = int.pending_play or int.ready_play
    if not pending then return nil end
    local kind
    if ev.type == "api.cmd" then local ok, msg = pcall(json.decode, ev.raw or ""); if ok and type(msg) == "table" then kind = msg.type end
    elseif ev.type == "v1.cmd" then kind = ev.name
    elseif ev.source ~= "offline-cache" then kind = "playback.control" end
    if kind and (kind:match("^playback%.") or ({ PLAYLIST_PLAY = true, DO_PLAY = true, DO_PAUSE = true, DO_NEXT = true, DO_PREV = true, SET_POS = true })[kind]) then
      return { commands = { util.emit("offline.cancel_pending", { token = pending.token }) } }
    end
  end
  for _, name in ipairs({ "api.cmd", "v1.cmd", "playback.request", "playback.pause_request", "playback.next", "playback.prev", "playback.toggle_request" }) do
    dispatch.on(name, "spotify_offline.items", cancel)
  end
end
return items
