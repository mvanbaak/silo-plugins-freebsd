# silo-plugins-freebsd

A **FreeBSD** mirror of the [Silo](https://siloserver.org) plugin catalog.

Silo's official catalog (raw.githubusercontent.com/Silo-Server/silo-plugins)
ships only `darwin/arm64`, `linux/amd64` and `linux/arm64` binaries, so Silo
cannot install its own default plugins on FreeBSD. The plugins are pure Go, so
this repository cross-compiles each one for FreeBSD and republishes it in a
catalog Silo can consume.

## Use it

This repository publishes two catalogs from the same signed release:

| Catalog | URL | Contents |
| --- | --- | --- |
| Official | `https://raw.githubusercontent.com/mvanbaak/silo-plugins-freebsd/main/manifest.json` | Only the plugins from Silo's official catalog |
| Community | `https://raw.githubusercontent.com/mvanbaak/silo-plugins-freebsd/main/community-manifest.json` | Only the plugins from the Silo community catalog |

In Silo: **Admin → Plugins → Repositories → add this URL**, enabled. Add the
official one first; add the community one as a second repository if you want
those plugins too.

Then install plugins from **Admin → Plugins → Catalog**.

The `multimedia/silo` FreeBSD port additionally points its managed
"Silo maintained" repository at the official catalog, so the default plugins
(`silo.tmdb`, `silo.tvdb`, `silo.theintrodb`) install automatically. The
community plugins are never part of that catalog.

## How it works

`scripts/build-catalog.sh` fetches one upstream catalog, clones each plugin at
its exact release tag (no fallback to upstream main), cross-compiles with
`GOOS=freebsd CGO_ENABLED=0 go build`, computes checksums, and rewrites the
catalog it was pointed at (`MANIFEST`, default `manifest.json`) with
`freebsd` added to `supported_platforms` and a `freebsd/<arch>` binary. New
entries carry a package-level `bundle_url` pointing at the Sigstore bundle
published beside the binaries; unsigned legacy entries are rebuilt on the first
signed run.

Two jq filters turn the upstream feeds into builder input: `official-catalog.jq`
requires `silo.tmdb`, `silo.tvdb` and `silo.theintrodb` and keeps only the
official feed, `community-catalog.jq` mirrors the whole community feed. Both
reject malformed entries and duplicate plugin IDs.

`.github/workflows/catalog.yml` runs on a schedule / manual dispatch and builds
both catalogs in one run: the official manifest from
[Silo-Server/silo-plugins](https://github.com/Silo-Server/silo-plugins) and the
community manifest from
[Silo-Community/silo-plugins](https://github.com/Silo-Community/silo-plugins).
It is **incremental**: only plugins whose upstream version is new (or that lack
a FreeBSD build) are compiled. Unchanged plugins keep pointing at the release
that built them. When there are changes it attests all binaries once, publishes
one new immutable release tagged `catalog-<UTC timestamp>` containing just those
binaries plus a single `plugin.sigstore.json`, and commits the refreshed
manifests; both manifests may reference that same bundle. When nothing changed
it does nothing — no build, no release, no commit.

The archived `silo.watchprovider.trakt` entry was removed from the official
catalog; existing installs are not affected.

Run it locally too (repeat with `MANIFEST`/`UPSTREAM`/`BUILT` for the second
catalog):

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
