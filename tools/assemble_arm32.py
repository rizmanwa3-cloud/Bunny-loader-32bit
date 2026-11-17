#!/usr/bin/env python3
"""Merakit APK Bunny Loader versi 32-bit (armeabi-v7a).

Bahan:
  --base        bunny-loader.v0.4.0.apk (ARM64, sumber UI/dex/aset)
  --terraria    Terraria-1.4.5.8.6.apk  (punya lib/armeabi-v7a asli: il2cpp, unity, main)
  --mono        folder hasil ekstrak paket NuGet Microsoft.NETCore.App.Runtime.Mono.android-arm
  --shadowhook  folder hasil ekstrak AAR com.bytedance.android:shadowhook (jni/armeabi-v7a)
  --gpath       folder hasil ekstrak AAR androidx.graphics:graphics-path (jni/armeabi-v7a)
  --libbunny    (opsional) libbunny.so ARMv7 hasil port

Keluaran: APK belum ditandatangani (zipalign + apksigner dilakukan di workflow).
"""
import argparse
import os
import re
import sys
import zipfile

ARM64 = "lib/arm64-v8a/"
ARM32 = "lib/armeabi-v7a/"
FROM_TERRARIA = {"libil2cpp.so", "libunity.so", "libmain.so"}
MUST_HAVE = {"libil2cpp.so", "libunity.so", "libmain.so", "libmonosgen-2.0.so"}
SIG = re.compile(r"^META-INF/[^/]+\.(SF|RSA|DSA|EC)$|^META-INF/MANIFEST\.MF$")


def index_dir(root, suffix, must_contain=None):
    """Petakan nama berkas -> path penuh untuk semua berkas ber-akhiran suffix."""
    found = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            if not name.endswith(suffix):
                continue
            path = os.path.join(dirpath, name)
            if must_contain and must_contain not in path.replace(os.sep, "/"):
                continue
            found.setdefault(name, path)
    return found


def read_file(path):
    with open(path, "rb") as fh:
        return fh.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--terraria", required=True)
    ap.add_argument("--mono", required=True)
    ap.add_argument("--shadowhook", required=True)
    ap.add_argument("--gpath", required=True)
    ap.add_argument("--libbunny")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default="build-report.txt")
    ap.add_argument("--keep-arm64", action="store_true", help="biarkan lib ARM64 (APK universal)")
    args = ap.parse_args()

    base = zipfile.ZipFile(args.base)
    terr = zipfile.ZipFile(args.terraria)

    mono_native = index_dir(args.mono, ".so", "/android-arm/")
    mono_dll = index_dir(args.mono, ".dll", "/android-arm/")
    shook = index_dir(args.shadowhook, ".so", "armeabi-v7a")
    gpath = index_dir(args.gpath, ".so", "armeabi-v7a")

    report = []
    log = lambda s: (report.append(s), print(s))
    log(f"paket mono android-arm: {len(mono_native)} .so, {len(mono_dll)} .dll")

    arm64_names = sorted(
        n[len(ARM64):] for n in base.namelist() if n.startswith(ARM64) and not n.endswith("/")
    )
    log(f"lib ARM64 di APK dasar: {', '.join(arm64_names)}")

    def get32(name):
        if name in FROM_TERRARIA:
            try:
                return terr.read(ARM32 + name), "terraria"
            except KeyError:
                return None, None
        if name == "libbunny.so":
            if args.libbunny and os.path.isfile(args.libbunny):
                return read_file(args.libbunny), "port libbunny"
            return None, None
        if name == "libshadowhook.so" and name in shook:
            return read_file(shook[name]), "shadowhook aar"
        if name == "libandroidx.graphics.path.so" and name in gpath:
            return read_file(gpath[name]), "graphics-path aar"
        if name in mono_native:
            return read_file(mono_native[name]), "mono android-arm"
        return None, None

    out = zipfile.ZipFile(args.out, "w")
    replaced = []
    for info in base.infolist():
        name = info.filename
        if SIG.match(name):
            continue
        if name.startswith(ARM64) and not args.keep_arm64:
            continue
        data = base.read(info)
        if name.startswith("assets/dotnet/") and name.endswith(".dll"):
            short = os.path.basename(name)
            if short in mono_dll:
                data = read_file(mono_dll[short])
                replaced.append(short)
        zi = zipfile.ZipInfo(name, info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        out.writestr(zi, data)
    log(f"DLL managed diganti dengan versi android-arm: {len(replaced)}")

    missing, added = [], []
    for name in arm64_names:
        data, src = get32(name)
        if data is None:
            missing.append(name)
            continue
        zi = zipfile.ZipInfo(ARM32 + name, (2026, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        out.writestr(zi, data)
        added.append(f"{name} <- {src} ({len(data)} byte)")
    out.close()

    for line in added:
        log(f"  + {ARM32}{line}")
    for name in missing:
        log(f"  ! BELUM ADA untuk 32-bit: {name}")

    fatal = sorted(MUST_HAVE & set(missing))
    bad = zipfile.ZipFile(args.out).testzip()
    if bad:
        log(f"ZIP rusak di entri: {bad}")
        fatal.append(bad)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    if fatal:
        print(f"GAGAL: komponen wajib tidak ada: {fatal}", file=sys.stderr)
        return 1
    print(f"OK -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
