  // Metadata pages survive reloads. Audio availability always comes from the current account.
  var offlineTitleAccountId = null;
  function offlineTitlePrefix() { return 'oj.titles.1:' + (S.device.id || S.device.hostname || location.host) + ':'; }
  function offlineTitleAccount(o) {
    var account = o.account_id || '';
    if (!account && !o.catalog_loaded) return;
    if (offlineTitleAccountId === account) return;
    offlineTitleAccountId = account;
    try {
      var prefix = offlineTitlePrefix();
      Object.keys(localStorage).forEach(function (k) {
        if (k.indexOf(prefix) === 0 && (!account || k.indexOf(prefix + account + ':') !== 0)) localStorage.removeItem(k);
      });
    } catch (e) {}
  }
  function offlineTitleChanged(before, after) {
    if (!before || before.account_id !== after.account_id) return;
    var old = obj(before.playlists), fresh = obj(after.playlists), account = after.account_id || '';
    Object.keys(old).concat(Object.keys(fresh)).filter(function (uri, i, a) { return a.indexOf(uri) === i; }).forEach(function (uri) {
      if (obj(old[uri]).snapshot_id === obj(fresh[uri]).snapshot_id && obj(old[uri]).ready === obj(fresh[uri]).ready) return;
      var prefix = account + ':' + uri + ':';
      Object.keys(offlinePreviewCache).forEach(function (k) { if (k.indexOf(prefix) === 0) delete offlinePreviewCache[k]; });
      offlinePreviewAsked = {};
      try { var disk = offlineTitlePrefix() + prefix; Object.keys(localStorage).forEach(function (k) { if (k.indexOf(disk) === 0) localStorage.removeItem(k); }); } catch (e) {}
    });
  }
  function offlineTitleKey(uri, offset) { return offlineTitlePrefix() + obj(S.spotifyOffline).account_id + ':' + uri + ':' + offset; }
  function offlineLoadTitles(uri, offset, snapshot) {
    try {
      var saved = JSON.parse(lsGet(offlineTitleKey(uri, offset)) || 'null');
      if (!saved || saved.uri !== uri || saved.offset !== offset || !Array.isArray(saved.tracks) || saved.tracks.length > 50) return null;
      if (snapshot && saved.snapshot_id !== snapshot) return null;
      saved.from_disk = true;
      if (!snapshot || saved.snapshot_id !== snapshot) saved.tracks.forEach(function (t) { t.cached = false; });
      return saved;
    } catch (e) { return null; }
  }
  function offlineSaveTitles(uri, page, snapshot) {
    if (page.phase !== 'complete' || !obj(S.spotifyOffline).account_id) return;
    try {
      var saved = { uri: uri, phase: 'complete', offset: Number(page.offset) || 0, total: page.total, name: page.name,
        tracks: arr(page.tracks).slice(0, 50), snapshot_id: snapshot || '', saved_at: Date.now(), fetched_at: page.fetched_at };
      var prefix = offlineTitlePrefix(), key = offlineTitleKey(uri, saved.offset);
      var keys = Object.keys(localStorage).filter(function (k) { return k.indexOf(prefix) === 0 && k !== key; });
      keys.sort(function (a, b) { return (JSON.parse(lsGet(a) || '{}').saved_at || 0) - (JSON.parse(lsGet(b) || '{}').saved_at || 0); });
      while (keys.length >= 48) localStorage.removeItem(keys.shift());
      lsSet(key, JSON.stringify(saved));
    } catch (e) {}
  }
  function spotifyStoredTrack(p, track) {
    var o = obj(S.spotifyOffline), snap = obj(obj(o.playlists)[p.spotify.uri]), result = snap.ready && track.cached === undefined && !track.problem ? Object.assign({}, track, { cached: true }) : track;
    [arr(snap.tracks), arr(obj(o.download).uri === p.spotify.uri ? obj(o.download).tracks : [])].forEach(function (list) {
      list.forEach(function (t) { if (t.uri && t.uri === track.uri && (t.cached === true || (t.cached === undefined && t.bytes > 0))) result = Object.assign({}, track, { cached: true, image: t.image || track.image }); });
    });
    return result;
  }
  function spotifyStorageBadge(p) {
    var o = obj(S.spotifyOffline);
    if (!p.spotify) {
      var files = arr(p.tracks), stored = files.filter(function (id) { var t = obj(S.db.tracks[id]); return t.filename && !t.isUrl; }).length;
      return files.length ? h('div', { class: 'pl-offline-status' }, h('span', { class: 'offline-badge' + (stored === files.length ? ' ready' : '') },
        icon(stored === files.length ? 'check' : 'globe'), stored ? t('of_stored_count', stored, files.length) : t('of_online_badge'))) : null;
    }
    if (!o.available) return null;
    var snap = obj(obj(o.playlists)[p.spotify.uri]), partial = obj(obj(o.partials)[p.spotify.uri]);
    var job = obj(obj(o.jobs)[p.spotify.uri]), count = snap.cached_tracks !== undefined ? Number(snap.cached_tracks) : partial.cached_tracks !== undefined ? Number(partial.cached_tracks) : (snap.ready ? Number(snap.total_tracks) : Number(job.completed) - Number(job.skipped || 0)) || 0;
    var total = Number(snap.total_tracks || partial.total_tracks || job.total) || 0;
    var downloading = obj(o.download).uri === p.spotify.uri && offlineBusy(), mode = obj(o.modes)[p.id] || 'online';
    return h('div', { class: 'pl-offline-status' },
      h('span', { class: 'offline-badge' + (snap.ready ? ' ready' : ''), 'data-k': 'playlist-cache' },
        icon(snap.ready ? 'check' : count ? 'disk' : 'globe'), downloading ? t('of_busy') : count ? t('of_stored_count', count, total || count) : t('of_online_badge')),
      snap.ready ? h('span', { class: 'small muted' }, t(mode === 'online' ? 'of_route_online' : 'of_route_offline')) : null);
  }
  function spotifyTrackActions(p, track, position, busy) {
    var o = obj(S.spotifyOffline), queued = arr(o.queue).some(function (q) { return q.uri === p.spotify.uri && q.track_uri === track.uri; });
    if (!o.account_ready) return null;
    var current = obj(o.download), loading = busy && current.uri === p.spotify.uri && (!current.track_uri || current.track_uri === track.uri);
    var label = track.cached ? t('of_item_stored') : queued ? t('of_queued') : loading ? t('of_busy') : t('of_cache_item');
    function cache(play) { send('OJ_OFFLINE_CACHE_TRACK', { playlistId: p.id, trackIndex: position, trackUri: track.uri, play: play }); }
    return h('span', { class: 'offline-track-actions' },
      h('button', { class: 'offline-chip' + (track.cached ? ' ready' : ''), disabled: track.cached || loading || queued || !o.account_ready,
        title: label, 'aria-label': label + ': ' + (track.name || ''), 'data-track-cache': track.uri,
        onclick: function () { cache(false); } }, icon(track.cached ? 'check' : 'download')),
      o.account_ready ? h('button', { class: 'icon-btn', disabled: busy || queued, title: t('of_play_item'),
        'aria-label': t('of_play_item') + ': ' + (track.name || ''), 'data-track-play': track.uri,
        onclick: function () {
          if (track.cached) send('OJ_OFFLINE_PLAY', { playlistId: p.id, trackIndex: position, trackUri: track.uri });
          else cache(true);
        } }, icon('play')) : null);
  }
