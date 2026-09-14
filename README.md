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
(`Add-ons -> Install from zip file`). If updating an existing install,
remove the old copy first rather than installing on top of it - Kodi
doesn't always cleanly overwrite `settings.xml`.

## Configure

Addon settings (`Add-ons -> My add-ons -> Subtitles -> Bazarr -> Configure`):

- **Bazarr URL** - e.g. `http://192.168.1.10:6767`
- **Bazarr API key** - `Bazarr Settings -> General -> Security`
- **Verify SSL certificate** - turn off only for a self-signed cert you can't install
- **Seconds to wait for Bazarr to write the subtitle** - how long `download()`
  polls the video's folder before giving up
- **Enable debug logging** - verbose request/response lines in `kodi.log`

## How it works

1. `search()` resolves the currently playing/focused item to a Bazarr
   library id - `find_series_id` + `find_episode` (via `/api/series` +
   `/api/episodes`) for TV, `find_movie` (via `/api/movies`) for movies -
   matching on TVDB/IMDB id, falling back to title.
2. It calls Bazarr's manual-search endpoint for that id
   (`GET /api/providers/episodes` or `/api/providers/movies`) and lists the
   results in Kodi.
3. Picking a result calls `download()`, which POSTs to the *same path* as
   the search (`/api/providers/episodes` / `/api/providers/movies` - not
   `/api/episodes|movies/subtitles`, which is Bazarr's upload endpoint and
   expects a multipart file). Bazarr fetches the subtitle itself and writes
   it into the media folder using its own naming.
4. The addon polls that folder (`wait_for_subtitle_file`) for the new file
   and hands its path back to Kodi.

All of the above is confirmed against Bazarr's actual source
(`morpheus65535/bazarr`, `api/providers/providers_episodes.py` /
`providers_movies.py` / `subtitles/manual.py`), not guessed:

- Auth is the `X-API-KEY` header.
- `hi`, `forced`, and `original_format` are sent as the literal strings
  `"True"`/`"False"`, not JSON booleans - Bazarr's request parser expects
  strings.
- A search result's `release_info` comes back as a **list** of strings
  (joined into one string by `_parse_search_result`), not a single string.
- The download call needs `provider` and `subtitle` copied verbatim from
  the chosen search result - `subtitle` is an opaque cache handle, not a
  real id.

## The one thing that's easy to break again

In `_add_search_result_item`, the search result's **`label` must be a
plain language name/code** (e.g. `"Croatian"`), nothing else appended to
it. This isn't cosmetic: Kodi's C++ subtitle dialog
(`GUIDialogSubtitles.cpp`) reads exactly this field to compute the
filename it saves to (`CLangCodeExpander::ConvertToISO6391(label, ...)`
-> `{video}.{code}.{ext}`). If `label` isn't parseable as a language,
Kodi can't determine the code, saves with an empty one instead
(`{video}..srt`), and you get a second, wrongly-named file sitting
alongside the one Bazarr already wrote - this happened once already when
`label` was changed to `"{provider} [{lang}]"` for display purposes.
Put anything else you want shown (provider, release info) in `label2`
instead.

## Known limitation

`manualsearch` (Kodi's "search by typed term" action) just re-runs the
normal metadata-based search, because Bazarr's manual-search endpoints
match against the library item's own metadata rather than a free-text
query - there's nothing for a typed term to bind to on the Bazarr side.

## Worth knowing about, not addon bugs

- **Kodi's own "Subtitle storage location" setting**
  (`Settings -> Player -> Subtitles`, `subtitles.storagemode` /
  `subtitles.custompath`) independently saves a copy of whatever gets
  loaded next to the video. With the `label` fix above it lands on the
  same filename Bazarr used (a real overwrite, one file) - but if the
  language codes ever don't line up, this is where a second file would
  come from again, not from this addon's own logic.
- Bazarr's manual-download endpoints (`episode_manually_download_specific_subtitle`
  / `movie_manually_download_specific_subtitle`) run through Bazarr's job
  queue asynchronously - the POST returns almost immediately, and the
  actual provider fetch + disk write happens shortly after. That's why
  `download()` polls for the file instead of expecting it to exist the
  instant the POST returns.
