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
                                  'user_2': {'title': 'Gute Nacht, kleiner Bär', 'audiobook': True, 'tracks': ['file_1']}},
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
        expect(rows.nth(0).locator('[data-track-cache]')).to_be_disabled()
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

        page.goto(url + '#/')
        for width in (390, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            for playlist in ('user_1', 'user_2'):
                card = page.locator('[data-pl="%s"]' % playlist)
                expect(card).to_be_visible()
                assert card.evaluate('(c) => { const t=c.querySelector(".meta").getBoundingClientRect(), b=c.querySelector(".play").getBoundingClientRect(); return t.right <= b.left && t.bottom <= c.getBoundingClientRect().bottom; }')
            expect(page.locator('[data-pl=user_1]')).to_contain_text('1/3 offline')
            expect(page.locator('[data-pl=user_2]')).to_contain_text('1/1 offline')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(args.out / ('playlist-cards-%d.png' % width)), full_page=True)
        checks.append('German footer text and cache badges cannot overlap Play at 390 or 1440 px, including local books')

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
        assert not errors, errors
        browser.close()
    server.shutdown()
    server.server_close()
    (args.out / 'results.json').write_text(json.dumps({'passed': len(checks), 'checks': checks}, indent=2))
    for check in checks:
        print('PASS', check)


if __name__ == '__main__':
    main()
