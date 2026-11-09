  var offlineShowUnavailable = lsGet('oj.offline.unavailable') === '1';
  function spotifyTrackUnavailable(track) { return !track.cached && !!track.problem; }
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
    var old = Object.assign({}, obj(before.partials), obj(before.playlists)), fresh = Object.assign({}, obj(after.partials), obj(after.playlists)), account = after.account_id || '';
    Object.keys(old).concat(Object.keys(fresh)).filter(function (uri, i, a) { return a.indexOf(uri) === i; }).forEach(function (uri) {
      if (obj(old[uri]).snapshot_id === obj(fresh[uri]).snapshot_id && obj(old[uri]).ready === obj(fresh[uri]).ready && obj(old[uri]).cached_tracks === obj(fresh[uri]).cached_tracks) return;
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
      list.forEach(function (t) { if (t.uri && t.uri === track.uri && (typeof t.cached === 'boolean' || t.bytes > 0)) result = Object.assign({}, track, { cached: t.cached !== false, image: t.image || track.image }); });
    });
    return result;
  }
  function spotifyQueueProgress(o) {
    var active = obj(o.download), waiting = arr(o.queue), done = obj(o.queue_progress), busy = offlineBusy();
    if (!busy && !waiting.length) return null;
    var completed = Number(done.completed) || 0, total = Number(done.total) || 0, unknown = false;
    if (busy) { completed += Number(active.completed) || 0; total += Number(active.total) || 0; unknown = !Number(active.total); }
    waiting.forEach(function (item) {
      var count = Number(item.total) || Number(obj(obj(o.playlists)[item.uri]).total_tracks) || Number(obj(obj(o.partials)[item.uri]).total_tracks) || (item.track_uri ? 1 : 0);
      if (!count) unknown = true;
      total += count;
    });
    var playlist = userPlaylists().filter(function (p) { return p.spotify && p.spotify.uri === active.uri; })[0];
    return h('div', { class: 'offline-progress compact', role: 'status', 'data-k': 'offline-progress' },
      icon('download'), h('span', { class: 'grow' }, t('of_queue') + ' · ' + (busy ? t('of_busy') : t('of_queued')),
        busy && playlist ? [' · ', h('a', { href: '#/p/' + encodeURIComponent(playlist.id) }, playlist.title || 'Spotify')] : null),
      h('b', null, completed + ' / ' + (unknown ? '…' : total)),
      h('progress', { max: Math.max(1, total), value: completed, 'aria-label': t('of_queue') }));
  }
  function spotifyStorageBadge(p) {
    var o = obj(S.spotifyOffline), ready = false, count = 0, total = 0, downloading = false;
    if (!p.spotify) {
      var files = arr(p.tracks);
      if (!files.length) return null;
      count = files.filter(function (id) { var track = obj(S.db.tracks[id]); return track.filename && !track.isUrl; }).length;
      total = files.length; ready = count === total;
    } else {
      if (!o.available) return null;
      var snap = obj(obj(o.playlists)[p.spotify.uri]), partial = obj(obj(o.partials)[p.spotify.uri]), job = obj(obj(o.jobs)[p.spotify.uri]);
      ready = !!snap.ready;
      count = snap.cached_tracks !== undefined ? Number(snap.cached_tracks) : partial.cached_tracks !== undefined ? Number(partial.cached_tracks) : (ready ? Number(snap.total_tracks) : Number(job.completed) - Number(job.skipped || 0)) || 0;
      if (snap.cached_tracks === 0) ready = false;
      total = Number(snap.total_tracks || partial.total_tracks || job.total) || 0;
      downloading = obj(o.download).uri === p.spotify.uri && offlineBusy();
    }
    var label = downloading ? t('of_busy') : ready ? t('of_ready') : count ? t('of_stored_count', count, total || count) : t('of_online_badge');
    return h('span', { class: 'offline-badge status-icon' + (ready ? ' ready' : ''), role: 'img', title: label, 'aria-label': label, 'data-k': 'playlist-cache' },
      icon(downloading ? 'download' : ready ? 'check' : count ? 'disk' : 'globe'));
  }
  function spotifyTrackActions(p, track, position, busy) {
    var o = obj(S.spotifyOffline), queued = arr(o.queue).some(function (q) { return q.uri === p.spotify.uri && q.track_uri === track.uri; });
    if (!o.account_ready || spotifyTrackUnavailable(track)) return null;
    var current = obj(o.download), loading = busy && current.uri === p.spotify.uri && (!current.track_uri || current.track_uri === track.uri);
    var label = track.cached ? t('of_remove_item') : queued ? t('of_queued') : loading ? t('of_busy') : t('of_cache_item');
    function cache(play) { send('OJ_OFFLINE_CACHE_TRACK', { playlistId: p.id, trackIndex: position, trackUri: track.uri, play: play }); }
    var inUse = obj(S.audio.nowPlaying).service === 'SPOTIFY_OFFLINE' && obj(S.audio.nowPlaying).playlistId === p.id && !/^(STOPPED|ENDED)$/.test(obj(S.audio.playback).state || '');
    return h('span', { class: 'offline-track-actions' },
      h('button', { class: 'offline-chip' + (track.cached ? ' ready' : ''), disabled: loading || queued || !o.account_ready || (track.cached && (busy || inUse)),
        title: label, 'aria-label': label + ': ' + (track.name || ''), 'data-track-cache': track.uri, 'data-track-remove': track.cached ? track.uri : null,
        onclick: function () {
          if (!track.cached) { cache(false); return; }
          confirmBox(t('of_remove_q'), t('of_remove_item_help', track.name || ''), t('of_remove'), true).then(function (yes) {
            if (yes) send('OJ_OFFLINE_REMOVE', { playlistId: p.id, trackUri: track.uri });
          });
        } }, icon(track.cached ? 'check' : 'download')),
      o.account_ready ? h('button', { class: 'icon-btn', disabled: busy || queued, title: t('of_play_item'),
        'aria-label': t('of_play_item') + ': ' + (track.name || ''), 'data-track-play': track.uri,
        onclick: function () {
          if (track.cached) send('OJ_OFFLINE_PLAY', { playlistId: p.id, trackIndex: position, trackUri: track.uri });
          else cache(true);
        } }, icon('play')) : null);
  }
