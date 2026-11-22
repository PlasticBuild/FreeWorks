# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keeps a downloaded GitHub project up to date: one updater for every add-in app tab.

No FreeCAD or Qt in here, so any thread can reuse it (the ScanRuler and Diotopo tabs do; the 3D Slicer tab's
Update button can call latest()/install() too).

    info = latest("owner/repo")                  # newest release, else newest tag, else newest commit
    path = install(root, "owner/repo", info)     # downloads, checks, unpacks beside the old copy, then switches
    current(root)                                # (tag, folder) of the copy in use, or None

Safety: the download is only ever read from GitHub's own hosts, a release asset's sha256 is checked when GitHub
gives one, a zip never writes outside its folder, a new version is unpacked beside the old one and only then made
current, and the one before stays as a fallback. Nothing is installed or run: files are unpacked, that is all.
"""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

API = "https://api.github.com"
UA = "FreeWorks-updater"
HOSTS = ("api.github.com", "github.com", "codeload.github.com", "objects.githubusercontent.com",
         "release-assets.githubusercontent.com")
MAX_BYTES = 400 * 1024 * 1024
KEEP = 2


def network_off():
    ""
    return os.environ.get("FREEWORKS_NO_NET", "") not in ("", "0")


class UpdateError(Exception):
    pass


# selfupdate: a token for a PRIVATE repository, sent only to GitHub's own API/web hosts and dropped on a redirect
TOKEN = ""
AUTH_HOSTS = ("api.github.com", "github.com")


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (urllib.parse.urlparse(newurl).hostname or "") not in AUTH_HOSTS:
            new.headers.pop("Authorization", None)
        return new


def _open(req, timeout):
    return urllib.request.build_opener(_NoAuthRedirect).open(req, timeout=timeout)


def _request(url, accept="application/vnd.github+json"):
    if network_off():
        raise UpdateError("update checks are off on this run")     # extapps/74: the switch is not named in the status bar
    host = urllib.parse.urlparse(url).hostname or ""
    if API == "https://api.github.com" and not (host in HOSTS or host.endswith(".githubusercontent.com")):
        raise UpdateError("refused host %s" % host)
    headers = {"User-Agent": UA, "Accept": accept}
    if TOKEN and host in AUTH_HOSTS:
        headers["Authorization"] = "Bearer " + TOKEN
    return urllib.request.Request(url, headers=headers)


def _json(url):
    try:
        with _open(_request(url), 20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code in (401, 403) and not TOKEN:
            raise UpdateError("GitHub needs a token for this repository (Options > General > Software updates)")
        if e.code in (401, 403):
            raise UpdateError("GitHub refused the token (expired, or no read access to this repository)")
        raise UpdateError("GitHub answered %s for %s" % (e.code, url))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError("no answer from GitHub (%s)" % e)


def _assets(release):
    out = []
    for a in release.get("assets") or []:
        digest = a.get("digest") or ""
        out.append({"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "size": a.get("size", 0),
                    "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else ""})
    return out


def latest(repo):
    """The newest thing to install from repo: a release when it has any, else a tag, else the default branch."""
    rel = _json("%s/repos/%s/releases/latest" % (API, repo))
    if rel and rel.get("tag_name"):
        return {"repo": repo, "kind": "release", "tag": rel["tag_name"], "title": rel.get("name") or rel["tag_name"],
                "notes": rel.get("body") or "", "page": rel.get("html_url", ""), "date": rel.get("published_at", ""),
                "assets": _assets(rel), "zip": rel.get("zipball_url", "")}
    tags = _json("%s/repos/%s/tags?per_page=1" % (API, repo))
    if tags:
        t = tags[0]
        return {"repo": repo, "kind": "tag", "tag": t["name"], "title": t["name"], "notes": "",
                "page": "https://github.com/%s/releases" % repo, "date": "", "assets": [],
                "zip": t.get("zipball_url", "")}
    c = _json("%s/repos/%s/commits/HEAD" % (API, repo))
    if c and c.get("sha"):
        sha = c["sha"]
        msg = ((c.get("commit") or {}).get("message") or "").split("\n")[0]
        return {"repo": repo, "kind": "commit", "tag": sha[:7], "title": msg or sha[:7], "notes": "",
                "page": "https://github.com/%s" % repo, "date": ((c.get("commit") or {}).get("committer") or {}).get("date", ""),
                "assets": [], "zip": "%s/repos/%s/zipball/%s" % (API, repo, sha)}
    raise UpdateError("%s has no release, tag or commit to read" % repo)


def _numbers(tag):
    return [int(n) for n in re.findall(r"\d+", tag or "")]


def is_newer(new_tag, old_tag):
    """True when new_tag should replace old_tag: a bigger version number, or any other tag/commit that differs."""
    if not new_tag:
        return False
    if not old_tag:
        return True
    a, b = _numbers(new_tag), _numbers(old_tag)
    if a and b and "." in new_tag and "." in old_tag:
        return a > b
    return new_tag != old_tag


def pick_asset(info, patterns):
    """The first release asset whose name matches one of the regexes (in order), else None."""
    for pat in patterns:
        for a in info.get("assets", ()):
            if re.search(pat, a["name"], re.I):
                return a
    return None


# ------------------------------------------------------------------ what is installed
def _slug(repo):
    return repo.replace("/", "__")


def _base(root, repo):
    return os.path.join(root, _slug(repo))


def current(root, repo):
    """(tag, folder) of the copy in use, or None."""
    marker = os.path.join(_base(root, repo), "current.json")
    try:
        with open(marker, encoding="utf-8") as f:
            data = json.load(f)
        folder = os.path.join(_base(root, repo), data["folder"])
        if os.path.isdir(folder):
            return data["tag"], folder
    except (OSError, ValueError, KeyError) as _fw_err:
        _fw_log("extupdate.py:145", _fw_err)
    return None


def installed_versions(root, repo):
    base = _base(root, repo)
    try:
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and not d.endswith(".partial"))
    except OSError:
        return []


# ------------------------------------------------------------------ install
def _download(url, target, want_sha, progress, limit):
    sha = hashlib.sha256()
    done = 0
    try:
        with _open(_request(url, "application/octet-stream"), 30) as r, open(target, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            if total and total > limit:
                raise UpdateError("download is %d MB, over the %d MB limit" % (total >> 20, limit >> 20))
            while True:
                block = r.read(256 * 1024)
                if not block:
                    break
                done += len(block)
                if done > limit:
                    raise UpdateError("download passed the %d MB limit" % (limit >> 20))
                sha.update(block)
                f.write(block)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("download failed (%s)" % e)
    if total and done < total:      # extapps136: the connection closed early: said so, not "not a zip file"
        raise UpdateError("download failed (connection reset before the end)")
    if want_sha and sha.hexdigest().lower() != want_sha.lower():
        raise UpdateError("the download does not match GitHub's checksum; not installed")
    return done


def safe_extract(zip_path, target):
    """Unpacks a zip without letting any entry leave target."""
    root = os.path.realpath(target)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            dest = os.path.realpath(os.path.join(root, member.filename))
            if dest != root and not dest.startswith(root + os.sep):
                raise UpdateError("unsafe path in the archive: %s" % member.filename)
        z.extractall(root)
    return root


def _flatten(folder):
    """A GitHub source zip holds one top folder: use what is inside it."""
    names = os.listdir(folder)
    if len(names) == 1 and os.path.isdir(os.path.join(folder, names[0])):
        inner = os.path.join(folder, names[0])
        for n in os.listdir(inner):
            shutil.move(os.path.join(inner, n), os.path.join(folder, n))
        os.rmdir(inner)


def install(root, repo, info, asset=None, progress=None, limit=MAX_BYTES):
    """Downloads info (the zip asset when given, else the source zip), unpacks it as <root>/<repo>/<tag> and makes
    it current. Returns the folder. A copy that is already there is only made current."""
    base = _base(root, repo)
    os.makedirs(base, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9._-]", "_", info["tag"])
    final = os.path.join(base, tag)
    if not os.path.isdir(final):
        url = asset["url"] if asset else info.get("zip")
        if not url:
            raise UpdateError("nothing to download for %s" % info["tag"])
        part = final + ".partial"
        shutil.rmtree(part, ignore_errors=True)
        os.makedirs(part)
        archive = os.path.join(base, tag + ".zip.download")
        try:
            _download(url, archive, asset["sha256"] if asset else "", progress, limit)
            if not zipfile.is_zipfile(archive):
                raise UpdateError("the download is not a zip file")
            safe_extract(archive, part)
            if not asset or not any(os.path.splitext(n)[1].lower() == ".exe" for n in os.listdir(part)):
                _flatten(part)
            os.replace(part, final)
        finally:
            shutil.rmtree(part, ignore_errors=True)
            try:
                os.remove(archive)
            except OSError as _fw_err:
                _fw_log("extupdate.py:234", _fw_err)
    marker = os.path.join(base, "current.json")
    temp = marker + ".new"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump({"tag": info["tag"], "folder": tag, "kind": info.get("kind"), "at": time.time()}, f)
    os.replace(temp, marker)
    prune(root, repo, tag)
    return final


def prune(root, repo, keep_tag):
    """Keeps the current copy and the one before it."""
    base = _base(root, repo)
    others = [d for d in installed_versions(root, repo) if d != keep_tag]
    others.sort(key=lambda d: os.path.getmtime(os.path.join(base, d)), reverse=True)
    for d in others[max(KEEP - 1, 0):]:
        shutil.rmtree(os.path.join(base, d), ignore_errors=True)
