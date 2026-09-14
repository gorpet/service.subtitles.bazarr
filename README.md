# service.subtitles.bazarr

Kodi subtitle addon that delegates all searching/downloading to an existing
**Bazarr** instance instead of scraping subtitle sites directly. Works only
for media that Bazarr already has indexed via Sonarr/Radarr, and requires
Kodi and Bazarr to see the media files at the same filesystem path (shared
SMB/NFS mount) - Bazarr writes the subtitle onto that share and this addon
just waits for it to appear.

## Install

Copy this whole folder to Kodi's `addons` directory as
`service.subtitles.bazarr`, or zip it and install from zip
(`Add-ons -> Install from zip file`).

## Configure

Addon settings (`Add-ons -> My add-ons -> Subtitles -> Bazarr -> Configure`):

- **Bazarr URL** - e.g. `http://192.168.1.10:6767`
- **Bazarr API key** - `Bazarr Settings -> General -> Security`
- **Verify SSL certificate** - turn off only for a self-signed cert you can't install
- **Seconds to wait for Bazarr to write the subtitle** - how long `download()`
  polls the video's folder before giving up
- **Enable debug logging** - verbose request/response lines in `kodi.log`

## Before relying on this in practice

Two parts of `resources/lib/bazarr.py` are best-effort reconstructions of
Bazarr's API and are marked with `VERIFY-BEFORE-RELYING-ON` / `***verify***`
comments in the code:

1. `_parse_search_result` - the field names of one manual-search result
   (from `/api/providers/episodes` and `/api/providers/movies`).
2. `_download_payload` - the POST body `/api/episodes/subtitles` and
   `/api/movies/subtitles` expect to download one chosen result.

To check both: open `http://<bazarr-host>:6767/api` in a browser (Bazarr is
a flask-restx app and serves interactive Swagger docs at that path), expand
the relevant sections, and compare their request/response models against
those two functions. Everything else (auth via `X-API-KEY`, `/api/series`,
`/api/episodes`, `/api/movies` shapes) is drawn straight from Bazarr's
published source layout and should not need changes.

Also worth double-checking on your setup:

- The **language code format** Bazarr returns in search results (alpha-2
  `hr` vs alpha-3 `hrv` vs a full name) - `search()` in `addon.py` assumes
  it can take the first two characters as an alpha-2 code. There's a `NOTE`
  comment at that exact line.
- The **subtitle filename pattern** Bazarr writes (depends on your Bazarr
  subtitle-naming settings) - `wait_for_subtitle_file` in `bazarr.py`
  doesn't hardcode a pattern; it just watches the video's folder for a new
  subtitle file and loosely matches it by filename stem or language code.
  If your naming scheme doesn't include either, loosen or adjust that match.

## Known limitation

`manualsearch` (Kodi's "search by typed term" action) just re-runs the
normal metadata-based search, because Bazarr's manual-search endpoints
match against the library item's own metadata rather than a free-text
query - there's nothing for a typed term to bind to on the Bazarr side.
