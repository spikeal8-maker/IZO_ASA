# Gallery Video Storage Contract

## Tariff limits

The `tariffs` record in `admin_settings` is the runtime source of truth. The
initial storage limits are:

| Plan | Videos kept in the private gallery |
| --- | ---: |
| Free | 0 |
| Mini | 1 |
| Plus | 5 |
| Pro | 10 |
| Business | 25 |

`video_slots` means concurrently stored videos. It is not a download or monthly
export limit. An administrator may change the value after the one-time
`video_storage_tariffs_v1` migration; later admin edits are not overwritten.

The value is edited on `/admin/tariffs` as **Мест для видео в галерее**. The
profile and public tariff cards describe the same value as **Хранение до N видео
в галерее**. These labels must not be changed back to video exports because
downloads are not metered by this setting.

## Model counts

Tariff payloads include two calculated, read-only fields:

- `image_model_count` is the number of distinct image model IDs available to the
  plan across image modes, including the built-in local server model.
- `video_model_count` is the number of distinct video model IDs assigned to the
  plan and currently enabled in at least one video mode.

The counts are derived from the access configuration on `/admin/models`. They
are displayed on `/admin/tariffs`, `/profile#tariffs`, and `/tariffs`, but are
never stored inside `admin_settings.tariffs`. This keeps model access as the
single source of truth and prevents a manually entered count from drifting from
the real catalog.

## Reservation and eviction

- A generation reserves a slot before tokens are charged and before the remote
  job is submitted.
- Completed and favorite videos are counted separately from unfinished jobs.
- A non-favorite oldest video may be evicted only after the replacement video
  has been downloaded and validated.
- Favorite videos are protected. Generation is rejected when favorite videos
  plus unfinished video jobs occupy every slot.
- After a tariff downgrade, an over-limit gallery shrinks gradually: two oldest
  non-favorite videos are removed when one new video is successfully saved.
- Provider failure never evicts an existing video.

## File safety

- Provider output is streamed to `<job>.mp4.part`, capped at 300 MiB, checked
  for an MP4 `ftyp` header, flushed, and atomically renamed.
- Database deletion is committed before physical deletion. The durable
  `video_file_deletions` queue retries files that Windows temporarily locks.
- Startup drains the pending deletion queue.
- Gallery cards lazy-load videos near the viewport; the page does not request
  metadata for every stored video at once.

## Publication to the feed

- A completed private gallery video can be published from the video result or
  from the gallery through the same publication form and API contract.
- Publication does not move, replace, or recompress the private original. It
  creates a separate public poster, interaction preview, and compatible MP4
  under the feed media root.
- Preparation is asynchronous. The publication has `preparing`, `published`,
  or `failed` status, and both gallery surfaces poll the owner-only status
  endpoint until preparation finishes.
- Encoding is intentionally server-side because generated video is already on
  the server. Client-side transcoding would download and upload the same file,
  consume mobile battery and traffic, and produce browser-dependent output.
- Server load is bounded by one low-priority FFmpeg worker, one encoding thread,
  atomic `.part` files, a three-second preview, and a 1920px maximum long edge
  for the public MP4. `FEED_VIDEO_PUBLICATION_ENABLED=0` is the emergency kill
  switch.
- Deleting a private original is blocked while its public copy is preparing.
  After successful publication, deleting the private original leaves the
  independent feed publication available until the owner or an administrator
  removes it.

## Operations

Run the focused audit from the canonical project folder:

```powershell
python backend/video_storage_audit.py --fail-on-issues
```

The combined media check also includes this report:

```powershell
python backend/media_health_check.py --fail-on-issues
```

`over_limit_users` is a warning, not silent deletion. Such accounts are reduced
only during later successful video generations according to the rule above.
