"""Current UI: per-title cache/play, persistent metadata, covers and card footer layout."""
import argparse
import base64
import copy
import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_spotify_offline_ui import PEER, WEB, QuietHandler

URI = 'spotify:playlist:' + '1' * 22
TRACKS = ['spotify:track:' + str(i) * 22 for i in (1, 2, 3)]
IMAGE = '/offline-artwork/' + 'a' * 64
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP438HwHwAGmAKHfbWTmQAAAABJRU5ErkJggg==')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('build/spotify-offline/items-ui'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(WEB)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % server.server_port
    songs = [{'uri': uri, 'name': 'Kapitel %d – Ein sehr langes deutsches Abenteuer' % (i+1), 'artists': ['Feuerwehrgeschichten'],
              'duration_ms': 90000, 'cached': i == 0, 'image': IMAGE if i == 0 else None} for i, uri in enumerate(TRACKS)]
    state = {'device': {'id': 'fixture-device'},
             'db': {'playlists': {'user_1': {'title': 'Anton Fuchs mit langem Namen', 'tracks': [], 'spotify': {'uri': URI}},
                                  'user_2': {'title': 'Gute Nacht, kleiner Bär', 'audiobook': True, 'tracks': ['file_1']},
                                  'user_3': {'title': 'Auch hier', 'tracks': ['file_1']}},
                    'tracks': {'file_1': {'filename': '/music/chapter.mp3', 'title': 'Kapitel'}}, 'tokens': {}},
             'audio': {'config': {}, 'playback': {'state': 'STOPPED'}, 'nowPlaying': {}},
             'spotifyOffline': {'available': True, 'account_ready': True, 'metadata_ready': True, 'catalog_loaded': True,
                                'account_id': 'account-one', 'modes': {'user_1': 'auto'}, 'playlists': {},
                                'partials': {URI: {'cached_tracks': 1, 'total_tracks': 3}}, 'queue': [], 'jobs': {},
                                'previews': {URI: {'phase': 'complete', 'request': '1', 'offset': 0, 'total': 3, 'tracks': songs}}}}
    checks = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': 390, 'height': 844}, locale='de-DE')
        errors = []

        def page_for(initial):
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.add_init_script('window.offlineInitial = ' + json.dumps(initial) + '; localStorage.setItem("oj.lang","de"); localStorage.setItem("oj.parent","1234");')
            page.route('**/mqtt.js*', lambda r: r.fulfill(content_type='application/javascript', body=PEER))
            page.route('**/oj-auth.json', lambda r: r.fulfill(json={}))
            page.route('**/offline-artwork/*', lambda r: r.fulfill(content_type='image/png', body=PNG))
            return page

        page = page_for(state)
        page.goto(url + '#/p/user_1')
        rows = page.locator('[data-k=offline-tracks] li')
        expect(rows).to_have_count(3)
        expect(rows.nth(0).locator('[data-track-remove]')).to_be_enabled()
        expect(rows.nth(0)).to_contain_text('Offline gespeichert')
        expect(rows.nth(1)).to_contain_text('Online')
        expect(rows.nth(0).locator('img')).to_have_attribute('src', IMAGE)
        page.wait_for_function('document.querySelector(".offline-art img").naturalWidth > 0')
        checks.append('stored chip, online chip and local cover appear per title')

        def sent(kind, p=page):
            return p.evaluate('(kind) => window.offlineSent.filter(x => x.topic.endsWith("/" + kind)).pop()', kind)

        rows.nth(1).locator('[data-track-cache]').click()
        assert sent('OJ_OFFLINE_CACHE_TRACK')['payload'] == {'playlistId': 'user_1', 'trackIndex': 2, 'trackUri': TRACKS[1], 'play': False, 'code': '1234'}
        rows.nth(1).locator('[data-track-play]').click()
        assert sent('OJ_OFFLINE_CACHE_TRACK')['payload']['play'] is True
        rows.nth(0).locator('[data-track-play]').click()
        assert sent('OJ_OFFLINE_PLAY')['payload']['trackUri'] == TRACKS[0]
        checks.append('cache chip downloads one exact title; Play caches an uncached selection and directly plays a stored selection')
        rows.nth(0).locator('[data-track-remove]').click()
        page.get_by_role('dialog').get_by_role('button', name='Download entfernen', exact=True).click()
        assert sent('OJ_OFFLINE_REMOVE')['payload'] == {'playlistId': 'user_1', 'trackUri': TRACKS[0], 'code': '1234'}
        expect(page.get_by_role('button', name='Download entfernen', exact=True)).to_be_visible()
        checks.append('saved-song chip confirms individual removal and a partial playlist also offers whole-copy removal')

        page.goto(url + '#/')
        for width in (390, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            for playlist in ('user_1', 'user_2'):
                card = page.locator('[data-pl="%s"]' % playlist)
                expect(card).to_be_visible()
                assert card.evaluate('(c) => { const t=c.querySelector(".meta").getBoundingClientRect(), b=c.querySelector(".play").getBoundingClientRect(); return t.right <= b.left && t.bottom <= c.getBoundingClientRect().bottom; }')
            expect(page.locator('[data-pl=user_1] [data-k=playlist-cache]')).to_have_attribute('title', '1/3 offline')
            expect(page.locator('[data-pl=user_2] [data-k=playlist-cache]')).to_have_attribute('title', 'Offline verfügbar')
            expect(page.locator('[data-pl=user_1] .playlist-service')).to_have_attribute('title', 'Spotify-Wiedergabeliste')
            assert page.locator('[data-pl=user_1] .meta').inner_text() == ''
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(args.out / ('playlist-cards-%d.png' % width)), full_page=True)
        checks.append('German footer text and cache badges cannot overlap Play at 390 or 1440 px, including local books')

        page.goto(url + '#/library')
        expect(page.locator('.lib-folder')).to_have_count(1)
        page.locator('.lib-folder summary').click()
        local = page.locator('[data-track=file_1]')
        expect(local).to_be_visible()
        local.locator('input.check').check()
        page.locator('[data-k=delete-tracks]').click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_contain_text('aus allen Wiedergabelisten')
        dialog.get_by_role('button', name='Löschen', exact=True).click()
        assert sent('TRACK_DELETE')['payload'] == {'trackIds': ['file_1'], 'code': '1234'}
        assert sent('PLAYLIST_UPDATE') is None
        checks.append('audiobook tree tracks can be permanently deleted from the library, with confirmation that every playlist reference is removed')

        # A fresh page gets no metadata from the peer. Only its persisted, account-bound cache can supply titles.
        cold = copy.deepcopy(state)
        cold['spotifyOffline']['previews'] = {}
        fresh = page_for(cold)
        fresh.goto(url + '#/p/user_1')
        expect(fresh.locator('[data-k=offline-tracks] li')).to_have_count(3)
        fresh.wait_for_function('window.offlineSent.some(x => x.topic.endsWith("/OJ_OFFLINE_PREVIEW"))')
        checks.append('title pages survive a fresh browser page and refresh without hiding their cached names')
        fresh.screenshot(path=str(args.out / 'cached-titles.png'), full_page=True)

        cold['spotifyOffline'].update(account_id='account-two', partials={}, catalog_loaded=True)
        fresh.evaluate('(s) => window.offlinePeer.onmessage("/j/web/output/state", JSON.stringify(s))', cold)
        expect(fresh.locator('[data-k=offline-tracks] li')).to_have_count(0)
        assert not fresh.evaluate('Object.keys(localStorage).some(k => k.includes("account-one:"))')
        checks.append('switching accounts clears the old private title pages and rows')

        complete = copy.deepcopy(state)
        complete['spotifyOffline']['playlists'] = {URI: {'ready': True, 'snapshot_id': 'saved-one', 'cached_tracks': 0, 'total_tracks': 3,
                                                        'tracks': [dict(songs[1], bytes=999)]}}
        complete['spotifyOffline']['previews'][URI]['tracks'][0]['cached'] = False
        complete['spotifyOffline']['jobs'] = {URI: {'completed': 3}}
        accuracy = page_for(complete)
        accuracy.goto(url + '#/p/user_1')
        expect(accuracy.locator('[data-track-cache]').nth(1)).to_be_enabled()
        accuracy.goto(url + '#/')
        expect(accuracy.locator('[data-pl=user_1] [data-k=playlist-cache]')).to_have_attribute('title', 'Online')
        accuracy.goto(url + '#/p/user_1')
        removed = copy.deepcopy(complete)
        removed['spotifyOffline'].update(playlists={}, partials={}, previews={}, jobs={})
        accuracy.evaluate('(s) => window.offlinePeer.onmessage("/j/web/output/state", JSON.stringify(s))', removed)
        expect(accuracy.locator('[data-k=offline-tracks] li')).to_have_count(0)
        assert not accuracy.evaluate('Object.keys(localStorage).some(k => k.includes("account-one:"))')
        checks.append('explicit unavailable flags and zero counts override old progress; removing a copy clears cached rows and disk metadata')
        filtered = copy.deepcopy(state)
        blocked = [dict(uri='spotify:track:' + str(i)*22, name='Nicht verfügbar '+str(i), artists=['Artist'],
                        cached=False, problem='track_unavailable') for i in (4, 5)]
        filtered['spotifyOffline']['previews'][URI].update(request='filter-1', total=55,
            tracks=[dict(songs[0], problem='track_unavailable'), blocked[0], songs[1], blocked[1], songs[2]])
        fp = page_for(filtered)
        fp.goto(url + '#/p/user_1')
        filtered_rows = fp.locator('[data-k=offline-tracks] li')
        expect(fp.locator('[data-k=show-unavailable]')).not_to_be_checked()
        expect(filtered_rows).to_have_count(3)
        assert filtered_rows.evaluate_all('(rs)=>rs.map(r=>r.dataset.trackIndex)') == ['1','3','5']
        expect(fp.locator('[data-k=offline-hidden]')).to_contain_text('2 nicht verfügbare Titel')
        filtered_rows.nth(2).locator('[data-track-play]').click()
        assert sent('OJ_OFFLINE_CACHE_TRACK', fp)['payload']['trackIndex'] == 5
        fp.locator('[data-k=show-unavailable]').check()
        expect(filtered_rows).to_have_count(5)
        expect(fp.locator('li.unavailable')).to_have_count(2)
        for row in fp.locator('li.unavailable').all():
            expect(row).to_contain_text('Bei Spotify nicht verfügbar')
            expect(row.locator('button')).to_have_count(0)
        # A valid cached file is still usable even if its older metadata says unavailable.
        expect(filtered_rows.nth(0).locator('[data-track-play]')).to_be_enabled()
        fp.reload()
        expect(fp.locator('[data-k=show-unavailable]')).to_be_checked()
        expect(filtered_rows).to_have_count(5)
        fp.locator('[data-k=show-unavailable]').uncheck()
        filtered['spotifyOffline']['previews'][URI].update(request='filter-2', tracks=blocked)
        fp.evaluate('(s)=>window.offlinePeer.onmessage("/j/web/output/state", JSON.stringify(s))', filtered)
        expect(filtered_rows).to_have_count(0)
        expect(fp.locator('[data-k=offline-filter-empty]')).to_be_visible()
        expect(fp.get_by_role('button', name='Weiter', exact=True)).to_be_enabled()
        checks.append('unavailable songs start hidden; the remembered filter reveals gray rows with no actions, preserves source indexes and permits paging past empty pages')
        queued = copy.deepcopy(state)
        queued['spotifyOffline'].update(queue_progress={'completed': 10, 'total': 10, 'skipped': 2},
            download={'uri':URI, 'phase':'downloading','completed':2,'total':3},
            queue=[{'playlist':'user_3','uri':'spotify:playlist:'+'3'*22,'title':'More songs','total':4}])
        qp=page_for(queued);qp.goto(url+'#/p/user_1')
        expect(qp.locator('[data-k=offline-progress]')).to_have_count(1)
        expect(qp.locator('[data-k=offline-progress] b')).to_have_text('12 / 17')
        expect(qp.locator('details.offline-queue')).to_have_count(0)
        expect(qp.locator('.offline-storage')).to_contain_text('Offline-Speicher: —')
        expect(qp.locator('text=Das Speicherbudget richtet sich')).to_have_count(0)
        checks.append('one compact global progress row combines completed, active and appended work; unknown storage has no false zero or budget explanation')
        update = copy.deepcopy(state);update['device']['openjooki']='2.5.1'
        up=page_for(update);up.route('**/oj-latest.json*',lambda r:r.fulfill(json={'error':'no_release'}))
        up.goto(url+'#/settings/update')
        up.locator('[data-k=updcheck]').click()
        expect(up.locator('[data-k=updcard]')).to_contain_text('kein automatisches Update veröffentlicht',timeout=10000)
        expect(up.locator('[data-k=updcard] .danger')).to_have_count(0)
        checks.append('a missing published update is explained without a false GitHub connectivity error')
        assert not errors, errors
        browser.close()
    server.shutdown()
    server.server_close()
    (args.out / 'results.json').write_text(json.dumps({'passed': len(checks), 'checks': checks}, indent=2))
    for check in checks:
        print('PASS', check)


if __name__ == '__main__':
    main()
