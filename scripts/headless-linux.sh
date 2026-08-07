#!/usr/bin/env bash
# Bootstrap and launch claude-greenlight's monitor.py on a Linux box that has
# no display and no tkinter (e.g. this repo's own dev container).
#
# On the common devcontainer case where `python3 -c "import tkinter"` already
# succeeds, this script skips the bootstrap entirely and only makes sure a
# virtual X display exists. Otherwise it stages a checksum-pinned tcl/tk
# tree from official Debian .deb packages into a user-owned cache — no root,
# no sudo, no apt — starts (or reuses) an Xvfb display, and execs monitor.py.
#
# Usage: scripts/headless-linux.sh [--self-test] [monitor.py args...]
#   --self-test   bootstrap + display, verify a Tk() root can be built, print
#                 "self-test OK", exit 0. Does not launch the monitor.
#   (no args)     bootstrap + display, then exec monitor.py "$@"
#
# Env overrides:
#   GREENLIGHT_TK_CACHE   cache root (default: ${XDG_CACHE_HOME:-$HOME/.cache}/claude-greenlight/tk)
#   GREENLIGHT_DISPLAY    X display to start/reuse (default: :99)
#
# Requires (bootstrap path only): x86_64, python3.11, curl, dpkg, sha256sum,
# and an Xvfb binary on PATH for the display step. On a host with native
# tkinter, only Xvfb is needed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CACHE="${GREENLIGHT_TK_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/claude-greenlight/tk}"
DEBS_DIR="$CACHE/debs"
TREE="$CACHE/tree"
XVFB_LOG="$CACHE/xvfb.log"
STAMP="$TREE/.bootstrap-ok"
GREENLIGHT_DISPLAY="${GREENLIGHT_DISPLAY:-:99}"

SELF_TEST=0
if [ "${1:-}" = "--self-test" ]; then
  SELF_TEST=1
  shift
fi

# ---------------------------------------------------------------------------
# Native short-circuit: if tkinter already imports, skip the bootstrap
# entirely (no directory creation, no download, no extraction, no env
# exports) and fall straight through to the display step.
# ---------------------------------------------------------------------------
NEED_BOOTSTRAP=1
if python3 -c "import tkinter" >/dev/null 2>&1; then
  NEED_BOOTSTRAP=0
fi

if [ "$NEED_BOOTSTRAP" = "1" ]; then

  # -------------------------------------------------------------------------
  # Preflight guards — one clear actionable line each, no tracebacks.
  # -------------------------------------------------------------------------
  ARCH="$(uname -m)"
  if [ "$ARCH" != "x86_64" ]; then
    echo "ERROR: headless-linux.sh only supports x86_64 (found: $ARCH) — the pinned tcl/tk .deb packages are amd64-only." >&2
    exit 1
  fi

  PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  if [ "$PYVER" != "3.11" ]; then
    echo "ERROR: headless-linux.sh requires python3.11 (found: ${PYVER:-none}) — the pinned python3-tk package ships _tkinter.cpython-311-x86_64-linux-gnu.so. Install your distro's python3-tk instead if you're on a different python3." >&2
    exit 1
  fi

  for bin in curl dpkg sha256sum; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      echo "ERROR: headless-linux.sh requires '$bin' on PATH but it was not found." >&2
      exit 1
    fi
  done

  # -------------------------------------------------------------------------
  # Idempotent, checksum-pinned bootstrap.
  #
  # tcl8.6/tk8.6 are pinned at 8.6.11 (not bookworm's 8.6.13) because that
  # exact combination is the one verified working against python3-tk
  # 3.11.2-3 in this container. Do not "upgrade" the pins without
  # re-verifying end to end — the sha256 table below would have to move
  # with them.
  # -------------------------------------------------------------------------
  mkdir -p -m 700 "$CACHE" "$DEBS_DIR" "$TREE"

  BASE_URL="https://deb.debian.org/debian/pool/main/"

  # pool_path|sha256
  PACKAGES="
p/python3-stdlib-extensions/python3-tk_3.11.2-3_amd64.deb|33badffb9316204fda015b1a9d331c03bd322dfbb217930de5dd5ca95b6af7d2
t/tcl8.6/libtcl8.6_8.6.11+dfsg-1_amd64.deb|785df3d81010a67ded4a2c216c7b99657c6ab3d1ba7369119894abc851e5bb0c
t/tcl8.6/tcl8.6_8.6.11+dfsg-1_amd64.deb|a83fad95e774f1e120f47098fc101159b086ade930cf5e0426c5ef964d8dd4d4
t/tk8.6/libtk8.6_8.6.11-2_amd64.deb|20d70721a5d539266a8736800378398d088419b986b5313ca811203284690f12
t/tk8.6/tk8.6_8.6.11-2_amd64.deb|d7bd1f052a5313a765519d041e321ed9c18a0687321465624ebbff55df442c62
t/tcltk-defaults/tk_8.6.11+1_amd64.deb|dc1cdf09b2e5c27797b34bca1468c46c2216c2eb708cd0406b36f0660be11f7c
b/blt/tk8.6-blt2.5_2.5.3+dfsg-8_amd64.deb|9f9ba386406c21e14b706ba137f1fe09d025636e2099b3f8eaee1948681fd58a
b/blt/blt_3.0~1+08570046+dfsg-8_amd64.deb|72cfdfcccc4a72b7397305cf2025276ed4915d2bb64404ddb9d8a36dc92d5aeb
x/xft/libxft2_2.3.6-1_amd64.deb|cedaedf108a8c18e9d9ae8d773801db7c7f9a70b50ecd7723c607d549dacccee
libx/libxss/libxss1_1.2.3-1+b3_amd64.deb|302d4a97800429fa0d67ae2e0e8e3adc1228b12d25d3d3cca6c9d24eeff40a6c
"

  if [ -f "$STAMP" ]; then
    echo "reusing cached tcl/tk tree at $TREE"
  else
    while IFS='|' read -r pool_path sha; do
      [ -z "$pool_path" ] && continue
      fname="$(basename "$pool_path")"
      dest="$DEBS_DIR/$fname"

      if [ ! -f "$dest" ]; then
        curl -fsSL "$BASE_URL$pool_path" -o "$dest"
      fi

      actual_sha="$(sha256sum "$dest" | awk '{print $1}')"
      if [ "$actual_sha" != "$sha" ]; then
        echo "ERROR: checksum mismatch for $fname (expected $sha, got $actual_sha) — deleting so a re-run fetches a clean copy." >&2
        rm -f "$dest"
        exit 1
      fi
    done <<EOF_PKGS
$PACKAGES
EOF_PKGS

    while IFS='|' read -r pool_path sha; do
      [ -z "$pool_path" ] && continue
      fname="$(basename "$pool_path")"
      dpkg -x "$DEBS_DIR/$fname" "$TREE"
    done <<EOF_PKGS
$PACKAGES
EOF_PKGS

    touch "$STAMP"
  fi

  # -------------------------------------------------------------------------
  # Runtime environment — append to any pre-existing values rather than
  # clobbering them.
  # -------------------------------------------------------------------------
  export LD_LIBRARY_PATH="$TREE/usr/lib/x86_64-linux-gnu:$TREE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export PYTHONPATH="$TREE/usr/lib/python3.11:$TREE/usr/lib/python3.11/lib-dynload${PYTHONPATH:+:$PYTHONPATH}"
  export TCL_LIBRARY="$TREE/usr/share/tcltk/tcl8.6"
  export TK_LIBRARY="$TREE/usr/share/tcltk/tk8.6"
fi

# ---------------------------------------------------------------------------
# Display.
# ---------------------------------------------------------------------------
if [ -n "${DISPLAY:-}" ]; then
  : # already set — use as-is, start nothing
elif pgrep -f "Xvfb $GREENLIGHT_DISPLAY" >/dev/null 2>&1; then
  export DISPLAY="$GREENLIGHT_DISPLAY"
else
  if ! command -v Xvfb >/dev/null 2>&1; then
    echo "ERROR: Xvfb binary not found on PATH — install the 'xvfb' package to provide a virtual X display." >&2
    exit 1
  fi

  mkdir -p -m 700 "$CACHE"
  Xvfb "$GREENLIGHT_DISPLAY" -screen 0 1280x800x24 >"$XVFB_LOG" 2>&1 &

  sock_num="${GREENLIGHT_DISPLAY#:}"
  ready=0
  for _ in $(seq 1 50); do
    if [ -S "/tmp/.X11-unix/X${sock_num}" ]; then
      ready=1
      break
    fi
    sleep 0.1
  done
  if [ "$ready" != "1" ]; then
    echo "ERROR: Xvfb did not become ready on display $GREENLIGHT_DISPLAY within 5 seconds — see $XVFB_LOG" >&2
    exit 1
  fi

  export DISPLAY="$GREENLIGHT_DISPLAY"
fi

# ---------------------------------------------------------------------------
# Self-test mode: verify tkinter can actually build a Tk() root, then exit
# without launching the monitor.
# ---------------------------------------------------------------------------
if [ "$SELF_TEST" = "1" ]; then
  python3 - <<'PY'
import tkinter
root = tkinter.Tk()
root.destroy()
print("self-test OK")
PY
  exit 0
fi

# ---------------------------------------------------------------------------
# Launch. Do not cd first, and never touch/read/reference .env here —
# monitor.py resolves it itself relative to its own __file__.
# ---------------------------------------------------------------------------
exec python3 "$REPO_ROOT/monitor.py" "$@"
