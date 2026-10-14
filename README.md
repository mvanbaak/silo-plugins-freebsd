# silo-plugins-freebsd

A **FreeBSD** mirror of the [Silo](https://siloserver.org) plugin catalog.

Silo's official catalog (raw.githubusercontent.com/Silo-Server/silo-plugins)
ships only `darwin/arm64`, `linux/amd64` and `linux/arm64` binaries, so Silo
cannot install its own default plugins on FreeBSD. The plugins are pure Go, so
this repository cross-compiles each one for FreeBSD and republishes it in a
catalog Silo can consume.

## Use it

In Silo: **Admin → Plugins → Repositories → add this URL**, enabled:

```
https://raw.githubusercontent.com/mvanbaak/silo-plugins-freebsd/main/manifest.json
```

Then install plugins from **Admin → Plugins → Catalog**.

The `multimedia/silo` FreeBSD port additionally points its managed
"Silo maintained" repository at this catalog, so the default plugins
(`silo.tmdb`, `silo.tvdb`, `silo.theintrodb`) install automatically.

## How it works

`scripts/build-catalog.sh` fetches the upstream catalog, clones each plugin at
its release tag, cross-compiles with `GOOS=freebsd CGO_ENABLED=0 go build`,
computes checksums, and writes `manifest.json` (mirroring upstream manifests,
adding `freebsd` to `supported_platforms` and a `freebsd/<arch>` binary).

`.github/workflows/catalog.yml` runs it on a schedule / manual dispatch. It is
**incremental**: only plugins whose upstream version is new (or that lack a
FreeBSD build) are compiled. Unchanged plugins keep pointing at the release
that built them. When there are changes it publishes a new immutable release
tagged `catalog-<UTC timestamp>` containing just those binaries, and commits the
refreshed `manifest.json`. When nothing changed it does nothing — no build, no
release, no commit.

Run it locally too:

```sh
GO=go126 ./scripts/build-catalog.sh \
  https://github.com/mvanbaak/silo-plugins-freebsd/releases/download/catalog
```

`ARCHES` defaults to `amd64`; the workflow builds `amd64` and `arm64`. Set
`ALLOWLIST=/path/to/ids.txt` to restrict which plugins are built.

## Licensing

The plugins are built unmodified from their upstream source repositories,
which are licensed **AGPL-3.0-or-later** and linked in each catalog entry's
`repo_url`. This repository only redistributes those builds.
