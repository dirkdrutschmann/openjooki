"""German device UI on the real core, including narrow layout, characters, pictures and storage."""
import os
from playwright.sync_api import sync_playwright, expect
import bench as B
from jk import PAGE

R = B.Results()
j = B.boot(ui=True)
j.nfc("04000000F00001", "101"); j.nfc_off()
j.nfc("04A1B2C3D49C41", "200"); j.nfc_off()
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--no-sandbox"])
    ctx = browser.new_context(locale="de-DE", viewport={"width": 375, "height": 812})
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(PAGE + "/#/settings"); pg.wait_for_selector("[data-k=langnav]")
    R.check("German browser detected", pg.locator("html").get_attribute("lang") == "de" and pg.locator("h1").inner_text() == "Einstellungen")
    for key in ("heartpress", "knobmode"):
        width = pg.wait_for_function("""key => {
            var el = document.querySelector('[data-k=' + key + ']');
            if (!el) return false;
            el.scrollIntoView({block: 'center'});
            return el.closest('.srow').querySelector('.lbl').getBoundingClientRect().width;
        }""", arg=key).json_value()
        R.check("readable narrow label " + key, width >= 180, width)
    for route in ("settings", "settings/language", "settings/night", "settings/bluetooth", "settings/wifi", "tokens", "library", "playlists"):
        pg.goto(PAGE + "/#/" + route); pg.wait_for_selector("h1")
        R.check("narrow layout " + route, pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
    pg.goto(PAGE + "/#/tokens"); pg.wait_for_selector("[data-char='Jooki.Fox']")
    R.check("German figure name", "Fuchs" in pg.locator("[data-char='Jooki.Fox']").inner_text())
    pg.locator("[data-char='flat.04A1B2C3D49C41']").click(); pg.click("[data-k=libpick]")
    pg.wait_for_selector("[data-libcat=animals]")
    R.check("German picture category", pg.get_attribute("[data-libcat=animals]", "aria-label") == "Tiere")
    pg.fill("[data-k=imgq]", "Katze"); pg.wait_for_selector("[data-img=cat]")
    R.check("German picture name and search", pg.locator("[data-img=cat]").inner_text() == "Katze")
    pg.click("[data-k=libcancel]"); pg.click("[data-k=charclose]")
    # Keep the player sheet open as a song becomes a book, then Spotify takes over.
    music = j.newpl("Musik", ["media/song1.mp3", "media/song2.mp3"])
    book = j.newpl("Hörbuch", ["media/song1.mp3", "media/song2.mp3"], audiobook=True)
    j.send("OJ_BEDTIME_SET", {"enabled": False})
    j.send("PLAYLIST_PLAY", {"playlistId": music}); j.wait_state("audio.playback.state", "PLAYING")
    pg.locator(".player .info").click()
    label = pg.locator("[data-sleep-min=track]")
    label.wait_for(); R.check("song sleep button in German", label.inner_text() == "Am Songende", label.inner_text())
    label.click(); j.wait(lambda: j.get("bedtime.sleep.mode") == "track")
    expect(pg.locator("[data-sleep-short]")).to_have_text("Am Songende")
    R.check("song timer in the player bar", pg.locator("[data-sleep-short]").inner_text() == "Am Songende")
    pg.click("[data-k=sleepoff]"); j.wait(lambda: not j.get("bedtime.sleep"))
    j.send("PLAYLIST_PLAY", {"playlistId": book}); j.wait(lambda: j.np.get("playlistId") == book and j.pb == "PLAYING")
    expect(label).to_have_text("Am Kapitelende")
    R.check("audiobook sleep button in German", label.inner_text() == "Am Kapitelende")
    label.click(); j.wait(lambda: j.get("bedtime.sleep.mode") == "track")
    expect(pg.locator("[data-sleep-short]")).to_have_text("Am Kapitelende")
    R.check("audiobook timer in the player bar", pg.locator("[data-sleep-short]").inner_text() == "Am Kapitelende")
    pg.click("[data-k=sleepoff]"); j.wait(lambda: not j.get("bedtime.sleep"))
    j.c.publish("/j/spotify/input/now_playing", '{"source_uri":"spotify:playlist:sleep","track":"Spotify song","duration_ms":120000}')
    j.c.publish("/j/spotify/input/playing", "")
    j.wait(lambda: j.np.get("service") == "SPOTIFY" and j.pb == "PLAYING")
    expect(label).to_have_text("Am Songende")
    R.check("Spotify sleep button in German", label.inner_text() == "Am Songende")
    R.check("sleep controls fit the narrow screen", pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
    pg.emulate_media(color_scheme="dark")
    os.makedirs("shots", exist_ok=True); pg.screenshot(path="shots/german-song-sleep.png", animations="disabled")
    pg.keyboard.press("Escape")
    pg.goto(PAGE + "/#/settings/language"); pg.click("[data-k=lang-de]")
    pg.reload(); pg.wait_for_selector("[data-k=lang-de]")
    R.check("German persists after reload", pg.evaluate("() => localStorage.getItem('oj.lang')") == "de" and pg.locator("html").get_attribute("lang") == "de")
    pg.click("[data-k=lang-en]"); pg.reload(); pg.wait_for_selector("h1:text-is('Language')")
    R.check("saved choice overrides German browser", pg.locator("html").get_attribute("lang") == "en")
    R.check("no JavaScript errors", not errors, errors)
    os.makedirs("shots", exist_ok=True)
    pg.click("[data-k=lang-de]"); pg.goto(PAGE + "/#/settings"); pg.wait_for_selector("[data-k=langnav]")
    pg.evaluate("() => scrollTo(0,0)"); pg.screenshot(path="shots/german-settings.png")
    browser.close()
B.check_clean_log(R, "German UI")
j.close(); R.finish()
