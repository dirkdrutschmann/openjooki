local offline = require("services.spotify_offline")
local items = require("services.spotify_offline_items")
local httpd = require("adapters.httpd")
local json = require("vendor.json")
local util = require("services.util")
local URI, TRACK = "spotify:playlist:" .. string.rep("1", 22), "spotify:track:" .. string.rep("2", 22)
local ACCOUNT, KEY = string.rep("a", 64), string.rep("b", 64)
local function doc()
  return { config = { spotify_offline_enabled = true, spotify_offline_root = "/offline" },
    library = { playlists = { user_1 = { title = "Songs", spotify = { uri = URI } } } },
    spotify_offline = { available = true, account_ready = true, metadata_ready = true, catalog_loaded = true,
      account_id = ACCOUNT, queue = {}, jobs = {}, modes = { user_1 = "online" }, playlists = {}, previews = {} },
    spotify_offline_int = { next_id = 0 }, playback = { state = "idle" } }
end
local function apply(d, r) for k, v in pairs((r or {}).state or {}) do d[k] = v end; return r end
local function find(r, kind, field, value)
  for _, c in ipairs((r or {}).commands or {}) do if c.kind == kind and (not field or c[field] == value) then return c end end
end

describe("individual Spotify cache controls", function()
  it("queues only the selected title, without changing the playlist's playback mode", function()
    local d = doc()
    local r = items.on_cache(d, { playlist = "user_1", index = 52, track_uri = TRACK, now = 10 })
    apply(d, r)
    local c = find(r, "shell", "action", "offline_cache_track")
    assert_eq(c.args.index, 51); assert_eq(c.args.track_uri, TRACK)
    assert_eq(d.spotify_offline.modes.user_1, "online")
    assert_nil(d.spotify_offline_int.pending_play)
  end)
  it("retains a single-title selection when restoring an active download after restart", function()
    local d = doc()
    local r = items.on_cache(d, { playlist = "user_1", index = 52, track_uri = TRACK, now = 10 })
    local saved
    for _, c in ipairs(r.commands) do if c.kind == "files.write" and c.path:match("queue.json$") then saved = c.doc end end
    assert_eq(saved.active.index, 52); assert_eq(saved.active.track_uri, TRACK)
    local restored = doc(); restored.spotify_offline_int.restore_pending = true
    apply(restored, offline.on_queue(restored, { text = json.encode(saved) }))
    r = offline.on_timer(restored, { now = 20 })
    local c = find(r, "shell", "action", "offline_cache_track")
    assert_true(c); assert_eq(c.args.index, 51); assert_eq(c.args.track_uri, TRACK)
  end)
  it("rejects invalid ids and indexes before queueing anything", function()
    for _, change in ipairs({ { index = 0 }, { index = 1.5 }, { track_uri = "/etc/passwd" }, { track_uri = "spotify:album:" .. string.rep("2", 22) } }) do
      local ev = { playlist = "user_1", index = 1, track_uri = TRACK }; for k, v in pairs(change) do ev[k] = v end
      local r, e = items.on_cache(doc(), ev); assert_nil(r); assert_eq(e.code, "invalid_argument")
    end
  end)
  it("a play click waits for this title's successful cache completion", function()
    local d = doc()
    apply(d, items.on_cache(d, { playlist = "user_1", index = 52, track_uri = TRACK, play = true, now = 10 }))
    local event = { text = json.encode({ version = 1, account_id = ACCOUNT, request = d.spotify_offline_int.job_request,
      uri = URI, track_uri = TRACK, track_index = 52, phase = "complete", completed = 1, total = 1 }) }
    local r = apply(d, offline.on_job(d, event))
    local ready = find(r, "emit"); assert_true(ready); assert_eq(ready.event.type, "offline.play_cached")
    assert_eq(ready.event.index, 52); assert_nil(d.spotify_offline_int.pending_play)
    assert_true(d.spotify_offline_int.ready_play)
  end)
  it("failed or canceled downloads cannot start a title later", function()
    local d = doc(); apply(d, items.on_cache(d, { playlist = "user_1", index = 2, track_uri = TRACK, play = true, now = 10 }))
    local intent = util.copy(d.spotify_offline_int.pending_play)
    apply(d, items.on_cancel(d, { token = intent.token }))
    assert_nil(items.on_ready(d, intent))
    assert_nil(d.spotify_offline_int.pending_play)
  end)
  it("forwards the selected cached title from the browser API without a complete snapshot", function()
    local d = doc()
    local r = require("api.v1").on_cmd(d, { name = "OJ_OFFLINE_PLAY", raw = json.encode({ playlistId = "user_1", trackIndex = 52, trackUri = TRACK }), now = 10 })
    local c = find(r, "shell", "action", "offline_play")
    assert_true(c); assert_eq(c.args.index, 51); assert_eq(c.args.track_uri, TRACK)
  end)
  it("allows a specific cached title without claiming the full playlist is ready", function()
    local d = doc()
    local snap = items.single_snapshot(d, "user_1", d.library.playlists.user_1, { index = 52, track_uri = TRACK })
    assert_true(snap.single); assert_eq(snap.total_tracks, 52)
    local r = offline.on_play(d, { playlist = "user_1", index = 52, track_uri = TRACK, now = 10 })
    local c = find(r, "shell", "action", "offline_play")
    assert_eq(c.args.index, 51); assert_eq(c.args.track_uri, TRACK)
    assert_false(r.state.playback.now.has_next)
    assert_nil(d.spotify_offline.playlists[URI])
  end)
end)

describe("private Spotify cover routing", function()
  local path = "/offline/store/accounts/" .. ACCOUNT .. "/pending/" .. KEY .. "/cover-" .. KEY .. ".img"
  it("keeps filesystem paths in private state and exposes only the active account's covers", function()
    local d, int = doc(), {}
    local data = { account_id = ACCOUNT, artwork = { [KEY] = { path = path, mime = "image/jpeg" } } }
    items.assets(d, int, data, true)
    assert_nil(data.artwork); d.spotify_offline_int = int
    local file, mime = items.artwork(d, "/offline-artwork/" .. KEY)
    assert_eq(file, path); assert_eq(mime, "image/jpeg")
    d.spotify_offline.account_id = string.rep("c", 64)
    assert_nil(items.artwork(d, "/offline-artwork/" .. KEY))
    d.spotify_offline.account_id = nil
    assert_nil(items.artwork(d, "/offline-artwork/" .. KEY))
  end)
  it("bounds accumulated artwork mappings while retaining the entire incoming page", function()
    local d, int = doc(), { artwork = {}, artwork_account = ACCOUNT }
    for i = 1, 512 do int.artwork[string.format("%064x", i)] = { path = path, mime = "image/jpeg" } end
    items.assets(d, int, { account_id = ACCOUNT, artwork = { [KEY] = { path = path, mime = "image/jpeg" } } })
    local count = 0; for _ in pairs(int.artwork) do count = count + 1 end
    assert_eq(count, 1); assert_eq(int.artwork[KEY].path, path)
  end)
  it("rejects audio files, traversal, other accounts and active document types", function()
    for _, value in ipairs({ { path = "/etc/passwd", mime = "image/jpeg" },
      { path = path:gsub(ACCOUNT, string.rep("c", 64)), mime = "image/jpeg" },
      { path = path, mime = "image/svg+xml" }, { path = path .. "/../credentials.json", mime = "image/jpeg" },
      { path = path:gsub("%.img$", ".spdl"), mime = "image/jpeg" } }) do
      local d, int = doc(), {}; items.assets(d, int, { account_id = ACCOUNT, artwork = { [KEY] = value } }, true)
      d.spotify_offline_int = int; assert_nil(items.artwork(d, "/offline-artwork/" .. KEY))
    end
  end)
  it("serves the authorized image with its MIME type, including HEAD, and returns 404 otherwise", function()
    local file = os.tmpname(); local f = assert(io.open(file, "wb")); f:write("image fixture"); f:close()
    local allowed = true
    local h = httpd.new({ offline_file = function(url) if allowed and url == "/offline-artwork/" .. KEY then return file, "image/png" end end })
    for _, method in ipairs({ "GET", "HEAD" }) do
      local c = { inbuf = method .. " /offline-artwork/" .. KEY .. " HTTP/1.1\r\nHost: jooki.local\r\n\r\n", phase = "head", headers = {}, last = 0 }
      h:parse_head(c); assert_match(c.out, "^HTTP/1.1 200"); assert_match(c.out, "Content%-Type: image/png")
      if c.out_file then c.out_file:close() end
    end
    allowed = false
    local c = { inbuf = "GET /offline-artwork/" .. KEY .. " HTTP/1.1\r\n\r\n", phase = "head", headers = {}, last = 0 }
    h:parse_head(c); assert_match(c.out, "^HTTP/1.1 404"); os.remove(file)
  end)
end)
